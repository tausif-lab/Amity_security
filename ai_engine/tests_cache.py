"""Tests for the ingestion engine, the normalization cache and the dual-call
agreement check.

The cache is exercised against the real database (TestCase) because that is the
part that must not regress; the LLM is never called - `call_ollama` is patched -
so the suite stays fast and offline.
"""

import json
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from ai_engine.services import ingest as ingest_mod
from ai_engine.services.ingest import detect_format, to_cli_text
from ai_engine.services import ollama_client
from ai_engine.services.ollama_client import compare_agreements, normalize_config_checked
from core.models import NormalizationCache
from core.services import normalization_cache

SAMPLES = Path(__file__).resolve().parents[1]


class IngestionFormatDetectionTests(SimpleTestCase):
    def test_cli_text_is_left_alone(self):
        text = (SAMPLES / "sample_config.txt").read_text(encoding="utf-8")
        converted, fmt = to_cli_text(text, "cisco")
        self.assertEqual(fmt, "cli")
        self.assertEqual(converted, text)

    def test_juniper_cli_is_not_mistaken_for_yaml(self):
        # `set system host-name SRX-01` has no colon, but a config with a
        # description field must not be reclassified either.
        text = (SAMPLES / "sample_config_juniper.txt").read_text(encoding="utf-8")
        self.assertEqual(detect_format(text), "cli")

    def test_detects_json_yaml_xml(self):
        self.assertEqual(detect_format('{"hostname": "R1"}'), "json")
        self.assertEqual(detect_format("hostname: R1\nip_http_server: true\n"), "yaml")
        self.assertEqual(detect_format("<config><hostname>R1</hostname></config>"), "xml")

    def test_broken_json_falls_back_to_raw_text(self):
        # A failed guess must never make the input worse than what was uploaded.
        broken = '{"hostname": "R1", '
        converted, fmt = to_cli_text(broken, "cisco")
        self.assertEqual(converted, broken)
        self.assertEqual(fmt, "cli")

    def test_json_becomes_cisco_cli(self):
        payload = json.dumps({
            "hostname": "Core-SW-02", "ip_http_server": True,
            "ntp": {"server": ["10.0.0.1", "10.0.0.2"]},
            "snmp": {"community": ["public"]},
        })
        text, fmt = to_cli_text(payload, "cisco")
        self.assertEqual(fmt, "json")
        self.assertIn("hostname Core-SW-02", text)
        self.assertIn("ip http server", text)
        self.assertIn("ntp server 10.0.0.1", text)
        self.assertIn("ntp server 10.0.0.2", text)
        self.assertIn("snmp-server community public ro", text)

    def test_yaml_becomes_cisco_cli(self):
        text, fmt = to_cli_text("hostname: Branch-R1\nntp:\n  server:\n    - 10.0.0.9\n", "cisco")
        self.assertEqual(fmt, "yaml")
        self.assertIn("hostname Branch-R1", text)
        self.assertIn("ntp server 10.0.0.9", text)

    def test_xml_becomes_cisco_cli(self):
        payload = "<config><hostname>Xml-SW</hostname><snmp><community>public</community></snmp></config>"
        text, fmt = to_cli_text(payload, "cisco")
        self.assertEqual(fmt, "xml")
        self.assertIn("hostname Xml-SW", text)
        self.assertIn("snmp-server community public ro", text)

    def test_json_becomes_juniper_cli(self):
        text, _ = to_cli_text(json.dumps({"hostname": "SRX-09", "telnet": True}), "juniper")
        self.assertIn("set system host-name SRX-09", text)
        self.assertIn("set system services telnet", text)

    def test_unknown_keys_are_kept_not_dropped(self):
        # Nothing may be silently discarded during conversion.
        text, _ = to_cli_text(json.dumps({"hostname": "R1", "custom_thing": "abc"}), "cisco")
        self.assertIn("custom_thing", text)


class DualCallAgreementTests(SimpleTestCase):
    INSTRUCTIONS = {"model": "test-model", "system_prompt": "prompt", "temperature": 0}
    SCHEMA = {"properties": {}}

    def _two_calls(self, first, second):
        with patch.object(ollama_client, "DUAL_CHECK_ENABLED", True), \
             patch.object(ollama_client, "call_ollama", side_effect=[first, second]):
            return normalize_config_checked("config", self.INSTRUCTIONS, self.SCHEMA, "")

    def test_identical_calls_are_accepted_as_agreed(self):
        payload = {"hostname": "R1", "management": {"ssh_version": 2}}
        baseline, status, disagreements = self._two_calls(dict(payload), dict(payload))
        self.assertEqual(status, "agreed")
        self.assertEqual(disagreements, [])
        self.assertEqual(baseline["hostname"], "R1")

    def test_divergence_is_reported_without_mutating_the_baseline(self):
        # The view decides what reaches a human; the client only reports.
        a = {"hostname": "R1", "management": {"ssh_version": 2}, "ntp": {"servers": ["10.0.0.1"]}}
        b = {"hostname": "R1", "management": {"ssh_version": 2}, "ntp": {"servers": ["10.9.9.9"]}}
        baseline, status, disagreements = self._two_calls(a, b)
        self.assertEqual(status, "diverged")
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0]["field"], "ntp.servers")
        self.assertEqual(disagreements[0]["call_a"], ("10.0.0.1",))
        self.assertNotIn("_normalization_assessment", baseline)

    def test_placeholder_strings_are_not_disagreements(self):
        # sanitize() turns 'Unknown'/'unknown'/null into None downstream, so a
        # difference between them is not evidence of anything.
        a = {"os_version": "Unknown", "hostname": "R1"}
        b = {"os_version": "unknown", "hostname": "R1"}
        self.assertEqual(compare_agreements(a, b), [])
        self.assertEqual(compare_agreements(a, {"os_version": None, "hostname": "R1"}), [])

    def test_ordering_of_lists_is_not_treated_as_disagreement(self):
        a = {"logging": {"remote_servers": ["10.0.0.5", "10.0.0.6"]}}
        b = {"logging": {"remote_servers": ["10.0.0.6", "10.0.0.5"]}}
        self.assertEqual(compare_agreements(a, b), [])

    def test_audit_metadata_is_not_compared(self):
        a = {"hostname": "R1", "_normalization_assessment": [{"command": "x", "confidence": 0.9}]}
        b = {"hostname": "R1", "_normalization_assessment": []}
        self.assertEqual(compare_agreements(a, b), [])

    def test_dual_check_can_be_disabled(self):
        with patch.object(ollama_client, "DUAL_CHECK_ENABLED", False), \
             patch.object(ollama_client, "call_ollama", return_value={"hostname": "R1"}) as call:
            baseline, status, disagreements = normalize_config_checked(
                "config", self.INSTRUCTIONS, self.SCHEMA, "")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(status, "single")
        self.assertEqual(disagreements, [])


class NormalizationCacheKeyTests(SimpleTestCase):
    BASE = {"vendor": "cisco", "model": "m", "schema": {"a": 1}, "prompt": "p", "config_text": "t"}

    def test_key_is_stable_for_identical_inputs(self):
        args = self.BASE
        self.assertEqual(normalization_cache.compute_key(**args), normalization_cache.compute_key(**args))

    def test_changing_config_text_changes_the_key(self):
        self.assertNotEqual(
            normalization_cache.compute_key(**self.BASE),
            normalization_cache.compute_key(**{**self.BASE, "config_text": "other"}))

    def test_changing_schema_retires_the_cache(self):
        # Editing the schema must never serve a baseline produced under the
        # old schema, so it has to change the key.
        self.assertNotEqual(
            normalization_cache.compute_key(**self.BASE),
            normalization_cache.compute_key(**{**self.BASE, "schema": {"a": 2}}))

    def test_changing_prompt_retires_the_cache(self):
        self.assertNotEqual(
            normalization_cache.compute_key(**self.BASE),
            normalization_cache.compute_key(**{**self.BASE, "prompt": "other"}))

    def test_changing_vendor_retires_the_cache(self):
        self.assertNotEqual(
            normalization_cache.compute_key(**self.BASE),
            normalization_cache.compute_key(**{**self.BASE, "vendor": "juniper"}))

    def test_key_is_vendor_case_insensitive(self):
        self.assertEqual(
            normalization_cache.compute_key(**self.BASE),
            normalization_cache.compute_key(**{**self.BASE, "vendor": "CISCO"}))


class NormalizationCacheStorageTests(TestCase):
    """These need the database: the cache is the part that must not regress."""

    def test_round_trip(self):
        key = "a" * 64
        self.assertIsNone(normalization_cache.get(key))
        normalization_cache.put(key, "cisco", "m", {"hostname": "R1"})
        self.assertEqual(normalization_cache.get(key), {"hostname": "R1"})

    def test_hit_counter_increments(self):
        key = "b" * 64
        normalization_cache.put(key, "cisco", "m", {"hostname": "R1"})
        normalization_cache.get(key)
        normalization_cache.get(key)
        self.assertEqual(NormalizationCache.objects.get(config_hash=key).hit_count, 2)

    def test_non_dict_payload_is_not_stored(self):
        normalization_cache.put("c" * 64, "cisco", "m", ["not", "a", "dict"])
        self.assertFalse(NormalizationCache.objects.filter(config_hash="c" * 64).exists())

    def test_clear_can_target_one_vendor(self):
        normalization_cache.put("d" * 64, "cisco", "m", {"a": 1})
        normalization_cache.put("e" * 64, "juniper", "m", {"a": 2})
        normalization_cache.clear("cisco")
        self.assertFalse(NormalizationCache.objects.filter(vendor="cisco").exists())
        self.assertTrue(NormalizationCache.objects.filter(vendor="juniper").exists())

    def test_stats_reports_a_hit_rate(self):
        normalization_cache.put("f" * 64, "cisco", "m", {"a": 1})
        normalization_cache.get("f" * 64)
        stats = normalization_cache.stats()
        self.assertEqual(stats["cached_configs"], 1)
        self.assertEqual(stats["cache_hits"], 1)
        self.assertAlmostEqual(stats["hit_rate"], 0.5)