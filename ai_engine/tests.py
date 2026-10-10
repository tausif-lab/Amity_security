"""Regression tests for the deterministic fact-extraction layer.

These need no database and no LLM: every assertion is the override layer
rejecting something the model got wrong, or accepting text that is literally
in the config.
"""

from pathlib import Path

from django.test import SimpleTestCase

from ai_engine.services.fact_extractor import apply_overrides

SAMPLES = Path(__file__).resolve().parents[1]

# What a small model actually returns for `routing.protocols` when the config
# has no routing stanza: the schema enum, echoed back in full.
ECHOED_ENUM = ["ospf", "bgp", "eigrp", "rip"]


def _routing(config_text, vendor):
    baseline = {"routing": {"protocols": list(ECHOED_ENUM),
                            "authentication": {"bgp": False, "ospf": False}}}
    return apply_overrides(baseline, config_text, vendor)["routing"]


class RoutingOverrideTests(SimpleTestCase):
    def test_config_without_routing_reports_no_protocols(self):
        text = (SAMPLES / "sample_config.txt").read_text(encoding="utf-8")
        self.assertEqual(_routing(text, "cisco")["protocols"], [])

    def test_detected_protocols_come_from_the_config(self):
        text = "hostname R1\nrouter ospf 1\nrouter bgp 65000\n"
        self.assertEqual(_routing(text, "cisco")["protocols"], ["ospf", "bgp"])

    def test_protocol_order_is_schema_order_not_file_order(self):
        text = "hostname R1\nrouter bgp 65000\nrouter ospf 1\n"
        self.assertEqual(_routing(text, "cisco")["protocols"], ["ospf", "bgp"])

    def test_no_router_cancels_an_earlier_stanza(self):
        text = "hostname R1\nrouter ospf 1\nno router ospf 1\n"
        self.assertEqual(_routing(text, "cisco")["protocols"], [])

    def test_authentication_is_detected_from_the_config(self):
        text = ("router ospf 1\n area 0 authentication message-digest\n"
                "router bgp 65000\n neighbor 10.0.0.9 password 7 070C285F4D06\n")
        auth = _routing(text, "cisco")["authentication"]
        self.assertIs(auth["ospf"], True)
        self.assertIs(auth["bgp"], True)

    def test_running_protocol_without_auth_reports_false(self):
        text = "hostname R1\nrouter ospf 1\n"
        self.assertIs(_routing(text, "cisco")["authentication"]["ospf"], False)

    def test_unconfigured_protocol_is_unknown_not_false(self):
        # Claiming "authentication disabled" for a protocol that never runs is
        # the same fabricated fact this layer exists to remove; None makes the
        # rule engine report Unknown instead.
        auth = _routing("hostname R1\nrouter eigrp 100\n", "cisco")["authentication"]
        self.assertIsNone(auth["ospf"])
        self.assertIsNone(auth["bgp"])

    def test_static_and_nexthop_lines_are_not_protocols(self):
        text = "ip route 0.0.0.0 0.0.0.0 10.0.0.1\nno cdp run\n"
        self.assertEqual(_routing(text, "cisco")["protocols"], [])


class JuniperRoutingOverrideTests(SimpleTestCase):
    def test_sample_config_reports_ospf_with_authentication(self):
        text = (SAMPLES / "sample_config_juniper.txt").read_text(encoding="utf-8")
        routing = _routing(text, "juniper")
        self.assertEqual(routing["protocols"], ["ospf"])
        self.assertIs(routing["authentication"]["ospf"], True)

    def test_brace_form_protocols_block_is_detected(self):
        text = ("system {\n    protocols {\n        ospf {\n"
                "            area 0.0.0.0 { interface ge-0/0/0.0; }\n        }\n    }\n}\n")
        self.assertEqual(_routing(text, "juniper")["protocols"], ["ospf"])

    def test_config_without_protocols_reports_none(self):
        self.assertEqual(_routing("set system host-name SRX-01\n", "juniper")["protocols"], [])


class ExistingOverrideTests(SimpleTestCase):
    """The routing fix must not regress the fields already being overridden."""

    def test_cisco_sample_facts_are_unchanged(self):
        text = (SAMPLES / "sample_config.txt").read_text(encoding="utf-8")
        baseline = apply_overrides({}, text, "cisco")
        self.assertEqual(baseline["ntp"]["servers"], ["10.0.0.1"])
        self.assertEqual(baseline["logging"]["remote_servers"], ["10.0.0.5"])
        self.assertIs(baseline["logging"]["local_buffered"], True)
        self.assertIs(baseline["management"]["http_enabled"], True)
        self.assertIs(baseline["management"]["telnet_enabled"], False)
        self.assertEqual(baseline["management"]["snmp"]["community_strings"], ["public"])
        self.assertEqual(baseline["authentication"]["password_encryption"], "type7")
        self.assertEqual(baseline["vendor"], "cisco")

    def test_numeric_password_encryption_forms(self):
        # Real configs use `secret 5 ...` / `password 7 ...`; the demo file's
        # `secret type7 ...` is not valid Cisco syntax, so both must be covered.
        self.assertEqual(apply_overrides({}, "enable secret 5 $1$abc\n", "cisco")
                         ["authentication"]["password_encryption"], "md5")
        self.assertEqual(apply_overrides({}, "enable password 7 070C285F\n", "cisco")
                         ["authentication"]["password_encryption"], "type7")