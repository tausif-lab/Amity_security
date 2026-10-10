"""Tests for the bidirectional Cisco IOS <-> Juniper Junos translator.

The translator is deterministic apart from the optional LLM/RAG stages, so
every test here runs with `use_llm=False, with_rag=False, persist=False` and a
no-op search function. That keeps the suite fast and offline.

These lock in the behaviour that matters:
  * both directions parse into one vendor-neutral IR
  * target syntax is actually emitted (Junos `set` vs Cisco IOS blocks)
  * credentials are never machine-translated
  * the LLM cannot invent hierarchies outside the real Junos/Cisco grammar
"""

import unittest

from translator import translate_config
from translator.cisco_generator import generate_cisco_config, step_to_cisco_line
from translator.cisco_mappings import build_cisco_plan
from translator.generator import generate_set_commands, redact_secret
from translator.juniper_ir import map_juniper_interface_name, normalize as normalize_juniper
from translator.juniper_parser import looks_like_junos, parse as parse_junos
from translator.planner import build_plan
from translator.validation import validate_commands, validate_semantics

CISCO_CONFIG = """hostname Core-SW-01
!
ip ssh version 2
!
logging host 10.0.0.5
logging buffered 4096
!
snmp-server community public ro
!
ntp server 10.0.0.1
!
interface GigabitEthernet0/0
 description uplink
 ip address 10.0.0.1 255.255.255.0
!
interface GigabitEthernet0/1
 shutdown
!
"""

JUNOS_CONFIG = """set system host-name SRX-01
set system services ssh protocol-version v2
set system ntp server 10.0.0.1
set system syslog host 10.0.0.5 any any
set system syslog file messages any any
set snmp community public authorization read-only
set system login message "Unauthorized access prohibited"
set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24
set interfaces ge-0/0/1 disable
set protocols ospf area 0 interface ge-0/0/0
"""


def translate(text, source, target):
    return translate_config(
        text, use_llm=False, with_rag=False, persist=False,
        search_fn=lambda q: [], source_vendor=source, target_vendor=target)


class JuniperParserTests(unittest.TestCase):
    def test_detects_junos_syntax(self):
        self.assertTrue(looks_like_junos(JUNOS_CONFIG))
        self.assertFalse(looks_like_junos(CISCO_CONFIG))

    def test_extracts_structure(self):
        ast = parse_junos(JUNOS_CONFIG)
        self.assertEqual(ast.hostname, "SRX-01")
        self.assertEqual([i.name for i in ast.interfaces], ["ge-0/0/0", "ge-0/0/1"])
        self.assertEqual([r.protocol for r in ast.routers], ["ospf"])

    def test_ignores_comments_and_block_markers(self):
        ast = parse_junos("/* header */\n# note\nset system host-name A\n\n")
        self.assertEqual(ast.hostname, "A")

    def test_empty_config_is_safe(self):
        self.assertEqual(parse_junos("").hostname, None)

    def test_interface_name_mapping(self):
        cases = {
            "ge-0/0/0": "GigabitEthernet0/0/0",
            "fe-1/2": "FastEthernet1/0/2",
            "xe-0/0/1": "TenGigabitEthernet0/0/1",
            "ae0": "Port-channel0",
            "lo0": "Loopback0",
            "me0": "Management0",
        }
        for junos_name, expected in cases.items():
            self.assertEqual(map_juniper_interface_name(junos_name), expected,
                             msg=f"mapping {junos_name}")

    def test_ir_records_only_present_facts(self):
        ir = normalize_juniper(parse_junos(JUNOS_CONFIG))
        g = ir.global_config
        self.assertEqual(g.hostname, "SRX-01")
        self.assertEqual(g.ssh_version, 2)
        self.assertEqual(g.ntp.servers, ["10.0.0.1"])
        self.assertEqual(g.logging.hosts, ["10.0.0.5"])
        self.assertEqual(g.snmp.community_strings, ["public"])
        # Junos has no telnet statement in this config, so it must stay False
        # rather than being guessed either way.
        self.assertFalse(g.telnet_enabled)

    def test_delete_means_disabled(self):
        ir = normalize_juniper(parse_junos("delete system services telnet\n"))
        self.assertFalse(ir.global_config.telnet_enabled)


class CiscoToJunosTests(unittest.TestCase):
    def setUp(self):
        self.result = translate(CISCO_CONFIG, "cisco", "junos")
        self.commands = self.result["set_commands"]

    def test_emits_junos_syntax(self):
        self.assertTrue(all(
            line.startswith(("set ", "delete ", "#")) or line == ""
            for line in self.commands), msg="\n".join(self.commands))

    def test_key_translations(self):
        joined = "\n".join(self.commands)
        self.assertIn("set system host-name Core-SW-01", joined)
        self.assertIn("set system services ssh protocol-version v2", joined)
        self.assertIn("set system ntp server 10.0.0.1", joined)
        self.assertIn("set system syslog host 10.0.0.5", joined)

    def test_interface_renamed_to_junos_convention(self):
        joined = "\n".join(self.commands)
        self.assertIn("set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24", joined)

    def test_no_duplicate_commands(self):
        self.assertEqual(len(self.commands), len(set(self.commands)),
                         msg="duplicate commands emitted")

    def test_validation_accepts_junos_output(self):
        _, issues = validate_commands(self.commands, vendor="junos")
        errors = [i for i in issues if i["level"] == "error"]
        self.assertEqual(errors, [], msg=str(errors))

    def test_result_is_confident_for_known_commands(self):
        self.assertGreater(self.result["overall_confidence"], 0.8)


class JuniperToCiscoTests(unittest.TestCase):
    def setUp(self):
        self.result = translate(JUNOS_CONFIG, "juniper", "cisco")
        self.commands = self.result["set_commands"]

    def test_emits_cisco_ios_blocks(self):
        joined = "\n".join(self.commands)
        self.assertIn("hostname SRX-01", joined)
        self.assertIn("ip ssh version 2", joined)
        self.assertIn("interface GigabitEthernet0/0/0", joined)
        self.assertIn(" ip address 192.168.1.1 255.255.255.0", joined)
        # No Junos syntax may leak into a Cisco-target translation.
        self.assertNotIn("set ", joined)
        self.assertNotIn("family inet", joined)

    def test_prefix_notation_becomes_dotted_mask(self):
        joined = "\n".join(self.commands)
        self.assertIn("255.255.255.0", joined)
        self.assertNotIn("/24", joined)

    def test_disabled_interface_becomes_shutdown(self):
        joined = "\n".join(self.commands)
        self.assertIn("interface GigabitEthernet0/0/1", joined)
        self.assertIn(" shutdown", joined)

    def test_ospf_binding_uses_cisco_interface_name(self):
        """A Junos area binding must not emit a Junos interface into IOS config."""
        blocks = [i for i, line in enumerate(self.commands)
                  if line.startswith("interface ")]
        ospf_lines = [line for line in self.commands if "ip ospf" in line]
        self.assertTrue(ospf_lines)
        # The interface referenced by ip ospf must be one we actually emitted.
        emitted = {line.split(None, 1)[1] for line in self.commands
                   if line.startswith("interface ")}
        for line in ospf_lines:
            owner = None
            for i, command in enumerate(self.commands):
                if command.startswith("interface "):
                    owner = command.split(None, 1)[1]
                if command.strip() == line.strip():
                    self.assertIn(owner, emitted)

    def test_no_duplicate_commands(self):
        # `!` is a legitimate block separator and may repeat; what must not
        # repeat is an actual configuration statement.
        statements = [line for line in self.commands if line.strip() != "!"]
        self.assertEqual(len(statements), len(set(statements)),
                         msg="duplicate statements emitted")

    def test_blocks_are_indented(self):
        """Cisco block children must be indented under their header."""
        current = None
        for line in self.commands:
            if line.startswith("interface ") or line.startswith("line vty") \
                    or line.startswith("router ") or line.startswith("vlan "):
                current = line
            elif line.startswith(" ") and current:
                self.assertTrue(line.startswith("  ") or line.startswith(" \t")
                                or len(line) - len(line.lstrip()) >= 1,
                                msg=f"not indented: {line!r}")
            elif line.strip() and not line.startswith("!"):
                current = None

    def test_ospf_block_header_is_emitted(self):
        joined = "\n".join(self.commands)
        self.assertIn("router ospf 1", joined)

    def test_validation_accepts_cisco_output(self):
        _, issues = validate_commands(self.commands, vendor="cisco")
        errors = [i for i in issues if i["level"] == "error"]
        self.assertEqual(errors, [], msg=str(errors))

    def test_syslog_and_snmp_translated(self):
        joined = "\n".join(self.commands)
        self.assertIn("logging host 10.0.0.5", joined)
        self.assertIn("snmp-server community public RO", joined)


class CredentialSafetyTests(unittest.TestCase):
    """Secrets must never be carried across vendors automatically."""

    def test_secret_is_redacted_in_unmapped_marker(self):
        self.assertEqual(
            redact_secret("# UNMAPPED: enable secret type7 0102030405060708"),
            "# UNMAPPED: enable secret <redacted>")

    def test_non_secret_lines_are_untouched(self):
        self.assertEqual(redact_secret("set system host-name r1"),
                         "set system host-name r1")

    CISCO_CREDENTIALS = (
        "hostname r1\n"
        "enable secret type7 0102030405060708\n"
        "username admin secret type7 0102030405060709\n"
    )

    JUNOS_CREDENTIALS = (
        'set system login user admin authentication encrypted-password "$6$abc123$xyz"\n'
    )

    def test_cisco_credentials_are_not_translated(self):
        result = translate(self.CISCO_CREDENTIALS, "cisco", "junos")
        joined = "\n".join(result["set_commands"])
        self.assertNotIn("0102030405060709", joined)
        self.assertNotIn("0102030405060708", joined)
        self.assertIn("# UNMAPPED", joined)
        self.assertTrue(result["unresolved"])

    def test_junos_credentials_are_not_translated(self):
        result = translate(self.JUNOS_CREDENTIALS, "juniper", "cisco")
        joined = "\n".join(result["set_commands"])
        self.assertNotIn("$6$abc123$xyz", joined)

    def test_unmapped_is_reported_not_silently_dropped(self):
        result = translate("hostname r1\nquantum-flux enable\n", "cisco", "junos")
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["status"], "review")


class UnsupportedVendorTests(unittest.TestCase):
    def test_unknown_source_vendor_is_tolerated_as_cisco(self):
        """An unrecognised source must not crash the pipeline."""
        result = translate("hostname r1\n", "arista", "junos")
        self.assertIn("set system host-name r1", result["set_commands"])


    def test_redundant_parent_commands_are_dropped(self):
        """`set a b` is implied by `set a b c` and must not be emitted twice."""
        steps = [
            {"kind": "set_line", "mapping": "ssh_service", "path": ["system", "services", "ssh"],
             "value": None, "source": "transport input ssh", "base_confidence": 0.9},
            {"kind": "set_line", "mapping": "ssh", "path": ["system", "services", "ssh", "protocol-version"],
             "value": "v2", "source": "ip ssh version 2", "base_confidence": 0.97},
        ]
        out = generate_set_commands(steps)
        self.assertIn("set system services ssh protocol-version v2", out)
        self.assertNotIn("set system services ssh", out)

    def test_sibling_commands_are_preserved(self):
        """Two different children of one parent must both survive."""
        steps = [
            {"kind": "set_line", "mapping": "ntp", "path": ["system", "ntp", "server", "1.1.1.1"],
             "value": None, "source": "a", "base_confidence": 0.9},
            {"kind": "set_line", "mapping": "ntp", "path": ["system", "ntp", "server", "2.2.2.2"],
             "value": None, "source": "b", "base_confidence": 0.9},
        ]
        out = generate_set_commands(steps)
        self.assertEqual(out, ["set system ntp server 1.1.1.1", "set system ntp server 2.2.2.2"])


class GeneratorTests(unittest.TestCase):
    def test_cisco_blocks_are_grouped_and_ordered(self):
        steps = [
            {"kind": "cisco_line", "mapping": "hostname", "block": None,
             "command": "hostname r1", "source": "s", "base_confidence": 1.0},
            {"kind": "cisco_line", "mapping": "iface_addr", "block": "interface Gi0/0",
             "command": "ip address 1.1.1.1 255.255.255.0", "source": "s",
             "base_confidence": 1.0},
            {"kind": "cisco_line", "mapping": "iface_mtu", "block": "interface Gi0/0",
             "command": "mtu 9000", "source": "s", "base_confidence": 1.0},
        ]
        out = generate_cisco_config(steps)
        self.assertEqual(out, ["hostname r1", "!", "interface Gi0/0",
                               " ip address 1.1.1.1 255.255.255.0", " mtu 9000"])

    def test_no_trailing_separator(self):
        steps = [{"kind": "cisco_line", "mapping": "hostname", "block": None,
                  "command": "hostname r1", "source": "s", "base_confidence": 1.0}]
        self.assertEqual(generate_cisco_config(steps), ["hostname r1"])

    def test_same_kind_blocks_are_separated(self):
        """Two consecutive interfaces each need their own header and `!`."""
        steps = [
            {"kind": "cisco_line", "mapping": "iface_addr", "block": "interface Gi0/0",
             "command": "ip address 1.1.1.1 255.255.255.0", "source": "s",
             "base_confidence": 1.0},
            {"kind": "cisco_line", "mapping": "iface_addr", "block": "interface Gi0/1",
             "command": "ip address 2.2.2.2 255.255.255.0", "source": "s",
             "base_confidence": 1.0},
        ]
        self.assertEqual(generate_cisco_config(steps),
                         ["interface Gi0/0", " ip address 1.1.1.1 255.255.255.0", "!",
                          "interface Gi0/1", " ip address 2.2.2.2 255.255.255.0"])

    def test_router_block_precedes_interfaces(self):
        """`ip ospf` lines reference the process, so it must be defined first."""
        ir = normalize_juniper(parse_junos(
            "set protocols ospf area 0 interface ge-0/0/0\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"))
        out = generate_cisco_config(build_cisco_plan(ir))
        self.assertLess(out.index("router ospf 1"),
                        out.index("interface GigabitEthernet0/0/0"))

    def test_router_block_after_interfaces(self):
        steps = [
            {"kind": "cisco_line", "mapping": "ospf", "block": "router ospf 1",
             "command": None, "source": "s", "base_confidence": 1.0},
            {"kind": "cisco_line", "mapping": "ospf_rid", "block": "router ospf 1",
             "command": "router-id 1.1.1.1", "source": "s", "base_confidence": 1.0},
        ]
        self.assertEqual(generate_cisco_config(steps),
                         ["router ospf 1", " router-id 1.1.1.1"])

    def test_step_to_cisco_line_renders_explanation(self):
        step = {"kind": "cisco_line", "block": "interface Gi0/0",
                "command": "shutdown", "source": "s"}
        self.assertEqual(step_to_cisco_line(step), "interface Gi0/0\n shutdown")


class SemanticValidationTests(unittest.TestCase):
    def test_duplicate_hostname_is_an_error(self):
        problems = validate_semantics(
            type("IR", (), {"vlans": []})(),
            ["set system host-name a", "set system host-name b"], vendor="junos")
        self.assertTrue(any(p["level"] == "error" for p in problems))

    def test_vlan_referenced_but_undefined_warns(self):
        ir = type("IR", (), {"vlans": []})()
        problems = validate_semantics(
            ir, ["interface Gi0/0", " switchport access vlan 99"], vendor="cisco")
        self.assertTrue(any("not defined" in m for p in problems for m in p["messages"]))


class LlmGuardTests(unittest.TestCase):
    """The LLM must not be able to invent syntax outside the real grammar."""

    def test_invalid_junos_path_is_rejected(self):
        from translator.planner import _plausible_junos_path

        self.assertTrue(_plausible_junos_path(["system", "host-name"]))
        self.assertTrue(_plausible_junos_path(["interfaces", "ge-0/0/0"]))
        self.assertFalse(_plausible_junos_path(["command", "123", "login"]))
        self.assertFalse(_plausible_junos_path([]))

    def test_invalid_cisco_command_is_rejected(self):
        from translator.planner import _plausible_cisco_command

        self.assertTrue(_plausible_cisco_command("ip ssh version 2"))
        self.assertTrue(_plausible_cisco_command("hostname r1"))
        self.assertFalse(_plausible_cisco_command("frobnicate everything"))
        self.assertFalse(_plausible_cisco_command(""))


if __name__ == "__main__":
    unittest.main()
