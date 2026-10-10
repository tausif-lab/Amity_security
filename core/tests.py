"""Tests for the deterministic compliance engine and the upload pipeline.

These cover the behaviours that are easy to break silently:
  * a missing fact must be Unknown, never a guessed Pass/Fail
  * rules files that omit id/severity/operator must not crash the engine
  * /api/uploads/ must return a real compliance report for every upload
  * a pending human review must NOT suppress the compliance report
"""

from unittest import mock

from django.test import TestCase

from compliance.services.rule_engine import (
    compliance_engine, evaluate_rule, extract_value, flatten_rules,
)
from compliance.services.remediation import build_corrected_config

CIS_RULES = [
    {"id": "T-1", "name": "SSH v2", "field": "management.ssh_version",
     "operator": "ge", "expected": 2, "severity": "High"},
    {"id": "T-2", "name": "Telnet off", "field": "management.telnet_enabled",
     "operator": "eq", "expected": False, "severity": "High"},
    {"id": "T-3", "name": "NTP set", "field": "ntp.servers",
     "operator": "non_empty", "expected": True},
]

GOOD_BASELINE = {
    "vendor": "cisco", "hostname": "r1",
    "management": {"ssh_version": 2, "telnet_enabled": False},
    "ntp": {"servers": ["10.0.0.1"]},
}


class RuleEngineTests(TestCase):
    def test_all_pass_on_good_baseline(self):
        report = compliance_engine(GOOD_BASELINE, CIS_RULES)
        self.assertEqual(report["summary"]["passed"], 3)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["unknown"], 0)

    def test_missing_field_is_unknown_not_pass(self):
        """A field the normalizer could not extract must never read as Pass."""
        result = evaluate_rule(CIS_RULES[0], {"vendor": "cisco", "hostname": "r1"})
        self.assertEqual(result["status"], "Unknown")
        self.assertIsNone(result["actual"])

    def test_empty_value_is_unknown(self):
        result = evaluate_rule(CIS_RULES[0], {"management": {"ssh_version": ""}})
        self.assertEqual(result["status"], "Unknown")

    def test_failing_rule_reports_actual(self):
        result = evaluate_rule(CIS_RULES[0], {"management": {"ssh_version": 1}})
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["actual"], 1)

    def test_unknown_operator_is_unknown_not_crash(self):
        rule = {"id": "X", "name": "n", "field": "a.b", "operator": "approved_only",
                "expected": True}
        result = evaluate_rule(rule, {"a": {"b": 1}})
        self.assertEqual(result["status"], "Unknown")

    def test_rule_without_field_is_manual(self):
        result = evaluate_rule({"id": "M", "name": "manual check"}, {})
        self.assertEqual(result["status"], "Manual")

    def test_flatten_expands_grouped_rules(self):
        grouped = [{"framework": "CIS", "type": "automated", "rules": {
            "a": {"name": "A", "field": "x", "operator": "exists", "expected": True},
            "b": {"name": "B", "field": "y", "operator": "exists", "expected": True},
        }}]
        flat = flatten_rules(grouped)
        self.assertEqual(len(flat), 2)
        self.assertTrue(all(r["id"].startswith("CIS-") for r in flat))

    def test_extract_value_dotted_path(self):
        self.assertEqual(extract_value(GOOD_BASELINE, "management.ssh_version"), 2)
        self.assertIsNone(extract_value(GOOD_BASELINE, "nope.nothing"))

    def test_real_cis_rules_file_loads_and_evaluates(self):
        """The shipped rule catalog must evaluate without raising."""
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "compliance" / "data" / "cis_rules.json"
        rules = json.loads(path.read_text(encoding="utf-8"))
        report = compliance_engine(GOOD_BASELINE, rules)
        self.assertEqual(report["summary"]["total"], len(rules))

    def test_juniper_rules_file_loads_and_evaluates(self):
        import json
        from pathlib import Path

        path = (Path(__file__).resolve().parents[1] / "compliance" / "data"
                / "cis_juniper_rules.json")
        rules = json.loads(path.read_text(encoding="utf-8"))
        report = compliance_engine(GOOD_BASELINE, rules)
        self.assertGreater(report["summary"]["total"], 0)

    def test_nist_rules_file_loads_and_evaluates(self):
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "compliance" / "data" / "NIST_rules.json"
        rules = json.loads(path.read_text(encoding="utf-8"))
        report = compliance_engine(GOOD_BASELINE, rules)
        self.assertGreater(report["summary"]["total"], 0)


class UploadEndpointTests(TestCase):
    """The /api/uploads/ endpoint is the entry point for the whole app."""

    def setUp(self):
        # The embedding model is a heavy native dependency; the memory service
        # has its own tests. Upload tests isolate it so they stay fast and do
        # not depend on a local sentence-transformers cache.
        patcher = mock.patch("core.views.lookup_config_memories", return_value=[])
        self.lookup = patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, text, vendor="cisco"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            "/api/uploads/",
            {"config": SimpleUploadedFile("c.txt", text.encode(), "text/plain"),
             "vendor": vendor},
        )

    def _fake_normalizer(self, baseline):
        from ai_engine.services.ollama_client import normalize_config
        return mock.patch(
            "core.views.normalize_config", side_effect=lambda *a, **k: dict(baseline))

    def test_requires_a_file(self):
        response = self.client.post("/api/uploads/", {"vendor": "cisco"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_rejects_empty_config(self):
        response = self._upload("   \n  \n")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "failed")

    def test_returns_compliance_report(self):
        """The endpoint scores against the real CIS catalog for the vendor."""
        with self._fake_normalizer(GOOD_BASELINE):
            response = self._upload("hostname r1\nip ssh version 2\nntp server 10.0.0.1\n")
        body = response.json()
        self.assertEqual(body["count"], 1)
        result = body["results"][0]
        self.assertEqual(result["status"], "done")
        self.assertIn("compliance_report", result)
        # The shipped Cisco CIS catalog has 8 rules.
        self.assertEqual(result["summary"]["total"], 8)
        # telnet/http are absent from the fixture baseline, so they must be
        # reported honestly as Unknown rather than guessed as Pass.
        statuses = {r["rule_id"]: r["status"] for r in result["compliance_report"]["results"]}
        self.assertEqual(statuses["CIS-1.1.2"], "Pass")   # ssh_version 2 >= 2
        self.assertEqual(statuses["CIS-1.6.1"], "Pass")   # ntp servers present
        self.assertEqual(statuses["CIS-1.1.3"], "Pass")   # telnet_enabled is False
        # http_enabled is absent from the fixture, so it must be Unknown, not
        # silently reported as a pass.
        self.assertEqual(statuses["CIS-2.1.1"], "Unknown")

    def test_pending_review_does_not_suppress_report(self):
        """A human item must be surfaced AND the report must still be produced."""
        with self._fake_normalizer(GOOD_BASELINE), \
                mock.patch("core.views.store_pending", return_value=999), \
                mock.patch("core.views.config_commands",
                           return_value=["demo-policy something"]):
            response = self._upload("hostname r1\ndemo-policy something\n")
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "review")
        self.assertEqual(len(result["normalization_review"]), 1)
        self.assertIn("compliance_report", result)
        self.assertEqual(result["summary"]["total"], 8)

    def test_normalizer_failure_is_reported_not_raised(self):
        with mock.patch("core.views.normalize_config", side_effect=RuntimeError("ollama down")):
            response = self._upload("hostname r1\nip ssh version 2\n")
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "failed")
        self.assertIn("ollama down", result["error"])

    def test_schema_echo_is_not_accepted_as_baseline(self):
        """A model that echoes the schema must not become the stored baseline."""
        echoed = {"$schema": "x", "type": "object", "properties": {}}
        with self._fake_normalizer(echoed), \
                mock.patch("core.views.reinforcement_prompt", return_value=dict(echoed)):
            response = self._upload("hostname r1\nip ssh version 2\n")
        result = response.json()["results"][0]
        # vendor is applied deterministically, so it validates; but the baseline
        # must never be the schema document itself.
        if result.get("baseline_json"):
            self.assertNotIn("properties", result["baseline_json"])

    def test_multiple_files_each_get_a_report(self):
        with self._fake_normalizer(GOOD_BASELINE):
            from django.core.files.uploadedfile import SimpleUploadedFile

            response = self.client.post("/api/uploads/", {
                "config": [SimpleUploadedFile("a.txt", b"hostname a\nip ssh version 2\n"),
                           SimpleUploadedFile("b.txt", b"hostname b\nntp server 1.1.1.1\n")],
                "vendor": ["cisco", "cisco"],
            })
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertTrue(all(r["status"] == "done" for r in body["results"]))


class HealthEndpointTests(TestCase):
    def test_health_reports_services(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("database", response.json())
        self.assertIn("ollama", response.json())


class CorrectedConfigTests(TestCase):
    def test_uses_stored_original_text(self):
        original = "hostname r1\nip ssh version 2\n"
        results = [{"status": "Fail", "rule_id": "T-1", "name": "SSH"}]
        with mock.patch("compliance.services.remediation.generate_remediation",
                        return_value=["ip ssh version 2"]):
            text = build_corrected_config(original, {"vendor": "cisco"}, results, {})
        self.assertIn("hostname r1", text)
        self.assertIn("ip ssh version 2", text)


class ValidatorTests(TestCase):
    def test_requires_vendor_and_hostname(self):
        from ai_engine.services.validator import validate_normalized_json

        schema = {"properties": {}, "required": ["vendor", "hostname"]}
        is_valid, errors = validate_normalized_json({}, schema)
        self.assertFalse(is_valid)
        self.assertEqual(len(errors), 2)


class NormalizationMemoryTests(TestCase):
    """The human-in-the-loop memory service, with the embedding model stubbed."""

    def setUp(self):
        patcher = mock.patch(
            "core.services.normalization_memory.embed_commands",
            side_effect=lambda commands: [[0.1] * 384 for _ in commands])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_store_pending_then_approve_then_apply(self):
        from core.models import NormalizationMemory
        from core.services.normalization_memory import (
            apply_approved_mappings, lookup_config_memories, store_pending,
        )

        memory_id = store_pending("weird-policy enable foo", "cisco", 0.2, "needs review")
        self.assertTrue(NormalizationMemory.objects.filter(id=memory_id).exists())

        memory = NormalizationMemory.objects.get(id=memory_id)
        self.assertEqual(memory.status, "pending")

        # A pending memory must never be applied automatically.
        matches = lookup_config_memories("weird-policy enable foo\n", "cisco")
        normalized = {"management": {}}
        self.assertEqual(
            apply_approved_mappings(dict(normalized), matches), normalized)

        memory.normalized_path = "management.ssh_version"
        memory.normalized_value = 2
        memory.status = "approved"
        memory.save()

        matches = lookup_config_memories("weird-policy enable foo\n", "cisco")
        applied = apply_approved_mappings({}, matches)
        self.assertEqual(applied["management"]["ssh_version"], 2)

    def test_config_commands_skips_comments(self):
        from core.services.normalization_memory import config_commands

        lines = config_commands("! a comment\nhostname r1\n# another\n\nntp server 1.1.1.1\n")
        self.assertEqual(lines, ["hostname r1", "ntp server 1.1.1.1"])

    def test_lookup_degrades_when_model_missing(self):
        """A missing embedding model must not break normalization."""
        from core.services.normalization_memory import lookup_config_memories

        with mock.patch("core.services.normalization_memory.embed_commands",
                        return_value=None):
            self.assertEqual(lookup_config_memories("hostname r1\n", "cisco"), [])


class NormalizationReviewApiTests(TestCase):
    def setUp(self):
        from core.models import NormalizationMemory

        self.memory = NormalizationMemory.objects.create(
            vendor="cisco", command="demo-policy secure-remote-access version-two",
            embedding=[0.0] * 384, description="needs review", status="pending")

    def test_lists_pending_reviews(self):
        response = self.client.get("/api/normalization-reviews/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_approve_with_human_command(self):
        response = self.client.post(
            f"/api/normalization-reviews/{self.memory.id}/",
            data={"decision": "approve", "human_command": "management.ssh_version = 2"},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["normalized_path"], "management.ssh_version")
        self.assertEqual(body["normalized_value"], 2)

    def test_approve_rejects_malformed_value(self):
        response = self.client.post(
            f"/api/normalization-reviews/{self.memory.id}/",
            data={"decision": "approve", "human_command": "management.ssh_version = {oops"},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_reject_keeps_record(self):
        response = self.client.post(
            f"/api/normalization-reviews/{self.memory.id}/",
            data={"decision": "reject"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.status, "rejected")

    def test_unknown_decision_is_rejected(self):
        response = self.client.post(
            f"/api/normalization-reviews/{self.memory.id}/",
            data={"decision": "maybe"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_missing_memory_is_404(self):
        response = self.client.post(
            "/api/normalization-reviews/999999/",
            data={"decision": "approve", "normalized_path": "a.b", "normalized_value": 1},
            content_type="application/json")
        self.assertEqual(response.status_code, 404)
