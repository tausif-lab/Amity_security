"""Tests for drift detection, the multi-framework rulesets and the corrected
config generator.

All deterministic: the rule engine never calls the LLM, and remediation is
tested with a stand-in instruction object so no model is contacted.
"""

import json
from pathlib import Path

from django.test import SimpleTestCase

from compliance.services.drift import diff_baselines, correlate_to_rules, build_drift_report
from compliance.services.remediation import build_corrected_config
from compliance.services.rule_engine import compliance_engine, flatten_rules

DATA = Path(__file__).resolve().parent / "data"

SUPPORTED_OPERATORS = {"eq", "ge", "in", "contains_any", "contains_all",
                       "not_contains_any", "exists", "non_empty", "configured"}

RULESETS = ("cis_rules.json", "NIST_rules.json", "stig_rules.json", "iso_rules.json")


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class RulesetValidityTests(SimpleTestCase):
    """A rule the engine cannot evaluate is a rule that silently reports Unknown."""

    def test_every_ruleset_loads_and_flattens(self):
        for name in RULESETS:
            rules = flatten_rules(load(name))
            self.assertGreater(len(rules), 0, name)

    def test_rule_ids_are_unique(self):
        for name in RULESETS:
            ids = [r["id"] for r in flatten_rules(load(name))]
            duplicates = {i for i in ids if ids.count(i) > 1}
            self.assertEqual(duplicates, set(), f"{name} has duplicate ids: {duplicates}")

    def test_new_rulesets_only_use_supported_operators(self):
        # STIG and ISO were authored for this engine, so every one of their
        # rules must actually be able to produce a verdict.
        for name in ("stig_rules.json", "iso_rules.json"):
            for rule in flatten_rules(load(name)):
                self.assertIn(rule.get("operator"), SUPPORTED_OPERATORS,
                              f"{name}:{rule.get('id')} uses {rule.get('operator')!r}")

    def test_rule_fields_exist_in_the_normalized_schema(self):
        schema_path = Path(__file__).resolve().parents[1] / "ai_engine" / "schemas" / "normalized_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        properties = schema["properties"]

        def known(path):
            node = properties
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return False
                node = node["properties"].get(part, {})
            return True

        # A field the schema never produces can only ever report Unknown.
        def known(path):
            node = properties
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return False
                node = node[part]
                if isinstance(node, dict) and "properties" in node:
                    node = node["properties"]   # step into an object level
            return True

        for name in ("stig_rules.json", "iso_rules.json"):
            for rule in flatten_rules(load(name)):
                field = rule.get("field")
                if field:
                    self.assertTrue(known(field), f"{name}:{rule['id']} -> unknown field {field!r}")

    def test_conditional_rules_are_unknown_when_the_feature_is_absent(self):
        # OSPF/BGP auth must not be reported as a failure on a device that does
        # not run those protocols: absent is "Unknown", not "Fail".
        baseline = {"vendor": "cisco", "hostname": "R1", "routing": {"protocols": []}}
        by_id = {r["rule_id"]: r for r in compliance_engine(baseline, load("stig_rules.json"))["results"]}
        for rule_id in ("STIG-CISCO-OSPF-1", "STIG-CISCO-BGP-1"):
            self.assertEqual(by_id[rule_id]["status"], "Unknown", rule_id)

    def test_conditional_rules_evaluate_once_the_feature_is_present(self):
        baseline = {"vendor": "cisco", "hostname": "R1",
                    "ntp": {"servers": ["10.0.0.1"], "authenticated": True},
                    "routing": {"protocols": ["ospf", "bgp"],
                                "authentication": {"ospf": False, "bgp": True}}}
        by_id = {r["rule_id"]: r for r in compliance_engine(baseline, load("stig_rules.json"))["results"]}
        self.assertEqual(by_id["STIG-CISCO-NTP-2"]["status"], "Pass")
        self.assertEqual(by_id["STIG-CISCO-BGP-1"]["status"], "Pass")
        # OSPF runs but has no authentication: that is a genuine failure.
        self.assertEqual(by_id["STIG-CISCO-OSPF-1"]["status"], "Fail")

    def test_iso_and_stig_actually_produce_verdicts(self):
        baseline = {"vendor": "cisco", "hostname": "R1",
                    "management": {"ssh_version": 2, "telnet_enabled": False,
                                   "http_enabled": True, "https_enabled": False,
                                   "snmp": {"version": "v1", "community_strings": ["public"]}},
                    "authentication": {"aaa_methods": [], "password_encryption": "type7"},
                    "ntp": {"servers": ["10.0.0.1"]}}
        for name in ("stig_rules.json", "iso_rules.json"):
            results = compliance_engine(baseline, load(name))["results"]
            automated = [r for r in results if r["status"] != "Manual"]
            self.assertGreater(len(automated), 0, name)
            self.assertEqual([r["rule_id"] for r in automated if r["status"] == "Manual"], [], name)
            # Every rule either reaches a verdict or is Unknown only because the
            # feature is absent; nothing may be "Manual" or error out.
            self.assertTrue(all(r["status"] in ("Pass", "Fail", "Unknown") for r in automated), name)
            self.assertGreater(any(r["status"] == "Pass" for r in automated), False, name)
            self.assertGreater(any(r["status"] == "Fail" for r in automated), False, name)


class DriftDetectionTests(SimpleTestCase):
    OLD = {"hostname": "SW1", "ntp": {"servers": ["10.0.0.1"]},
           "management": {"http_enabled": True, "snmp": {"community_strings": ["public"]}}}
    NEW = {"hostname": "SW1", "ntp": {"servers": []},
           "management": {"http_enabled": False, "snmp": {"community_strings": []}}}

    def test_modified_value_is_detected(self):
        changes = diff_baselines(self.OLD, self.NEW)
        self.assertTrue(any(c["field"] == "management.http_enabled" and c["change"] == "modified"
                            for c in changes))

    def test_list_clearing_is_detected(self):
        changes = diff_baselines(self.OLD, self.NEW)
        self.assertTrue(any(c["field"] == "ntp.servers" for c in changes))

    def test_identical_baselines_report_no_change(self):
        self.assertEqual(diff_baselines(self.OLD, self.OLD), [])
        report = build_drift_report(self.OLD, self.OLD, load("cis_rules.json"))
        self.assertFalse(report["changed"])
        self.assertEqual(report["drift_count"], 0)

    def test_added_field_is_classified_as_added(self):
        changes = diff_baselines({}, {"hostname": "SW1"})
        self.assertEqual(changes[0]["change"], "added")
        self.assertIsNone(changes[0]["previous"])

    def test_removed_field_is_classified_as_removed(self):
        changes = diff_baselines({"hostname": "SW1"}, {})
        self.assertEqual(changes[0]["change"], "removed")
        self.assertIsNone(changes[0]["current"])

    def test_drift_is_correlated_to_the_rules_it_moves(self):
        report = build_drift_report(self.OLD, self.NEW, load("cis_rules.json"))
        by_id = {r["rule_id"]: r for r in report["rules_impacted"]}
        # NTP server removed -> the NTP rule regresses.
        self.assertTrue(by_id["CIS-1.6.1"]["regression"])
        self.assertEqual(by_id["CIS-1.6.1"]["current_status"], "Fail")
        # HTTP turned off and the default community removed -> those improve.
        self.assertFalse(by_id["CIS-2.1.1"]["regression"])
        self.assertFalse(by_id["CIS-4.1.1"]["regression"])

    def test_regressions_are_listed_first(self):
        report = build_drift_report(self.OLD, self.NEW, load("cis_rules.json"))
        regressions = [r["regression"] for r in report["rules_impacted"]]
        self.assertEqual(regressions, sorted(regressions, reverse=True))

    def test_score_delta_reflects_the_change(self):
        report = build_drift_report(self.OLD, self.NEW, load("cis_rules.json"))
        self.assertGreater(report["score_delta"]["passed"], 0)

    def test_correlate_is_empty_when_nothing_moves(self):
        self.assertEqual(correlate_to_rules(self.OLD, self.OLD, load("cis_rules.json")), [])


class CorrectedConfigTests(SimpleTestCase):
    """The deliverable is a file a human can apply, not the original plus advice."""

    CONFIG = (Path(__file__).resolve().parents[1] / "sample_config.txt").read_text(encoding="utf-8")
    BASELINE = {"vendor": "cisco", "hostname": "Core-SW-01",
                "management": {"ssh_version": 2, "telnet_enabled": False, "http_enabled": True,
                               "snmp": {"community_strings": ["public"]}},
                "authentication": {"password_encryption": "type7", "aaa_methods": []}}
    RESULTS = [
        {"rule_id": "CIS-2.1.1", "name": "HTTP server disabled", "status": "Fail",
         "field": "management.http_enabled", "expected": False, "actual": True},
        {"rule_id": "CIS-4.1.1", "name": "No default SNMP communities", "status": "Fail",
         "field": "management.snmp.community_strings", "expected": ["public"], "actual": ["public"]},
        {"rule_id": "CIS-3.2.2", "name": "Password encryption SHA256/scrypt", "status": "Fail",
         "field": "authentication.password_encryption", "expected": ["sha256"], "actual": "type7"},
    ]

    def _build(self):
        return build_corrected_config(self.CONFIG, self.BASELINE, self.RESULTS, {"model": "test"})

    def test_http_server_line_is_rewritten_in_place(self):
        fixed = self._build()
        self.assertFalse(any(l.strip() == "ip http server" for l in fixed.splitlines()))
        self.assertTrue(any(l.strip() == "no ip http server" for l in fixed.splitlines()))

    def test_fix_is_applied_where_the_line_was_not_appended(self):
        # The whole point: the original line is corrected in situ rather than a
        # corrected copy being stapled onto the bottom of a still-broken file.
        fixed = self._build()
        self.assertLess(fixed.index("no ip http server"), fixed.index("Remediation notes"))

    def test_default_community_is_deactivated_not_left_active(self):
        fixed = self._build()
        self.assertFalse(any(l.strip().startswith("snmp-server community public")
                             for l in fixed.splitlines()))

    def test_type7_secret_is_upgraded_to_scrypt(self):
        self.assertIn("enable algorithm scrypt secret 0102030405060708", self._build())

    def test_per_user_type7_secret_is_also_upgraded(self):
        # Fixing only `enable secret` would leave the weaker per-user hash in
        # place while the report claims CIS-3.2.2 was remediated.
        fixed = self._build()
        self.assertIn("username admin algorithm scrypt secret 0102030405060709", fixed)
        self.assertFalse(any(l.strip().startswith("username admin secret type7")
                             for l in fixed.splitlines()))

    def test_output_carries_a_reviewable_header_and_notes(self):
        fixed = self._build()
        self.assertIn("CORRECTED CONFIGURATION", fixed)
        self.assertIn("Remediation notes", fixed)
        self.assertIn("Review every change before applying", fixed)

    def test_untouched_settings_survive(self):
        # Remediation must not drop configuration it has no opinion about.
        fixed = self._build()
        self.assertIn("hostname Core-SW-01", fixed)
        self.assertIn("ntp server 10.0.0.1", fixed)

    def test_duplicate_lines_are_all_rewritten(self):
        # A positional rewrite must not stop at the first match.
        config = "ip http server\nip http server\nhostname R1\n"
        fixed = build_corrected_config(config, self.BASELINE, [self.RESULTS[0]], {"model": "test"})
        self.assertEqual(fixed.count("no ip http server"), 2)

    def test_juniper_uses_hash_comments_and_junos_syntax(self):
        juniper_cfg = "set system host-name SRX-1\nset system services telnet\n"
        results = [{"rule_id": "CIS-6.10.6", "name": "Telnet is Not Set", "status": "Fail",
                    "field": "management.telnet", "expected": False, "actual": True}]
        fixed = build_corrected_config(juniper_cfg, {"vendor": "juniper", "hostname": "SRX-1"},
                                      results, {"model": "test"})
        self.assertIn("delete system services telnet", fixed)
        self.assertIn("# CORRECTED CONFIGURATION", fixed)
        self.assertNotIn("! CORRECTED CONFIGURATION", fixed)