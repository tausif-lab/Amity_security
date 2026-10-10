"""
translator/validation.py
Deterministic validation of generated Junos set commands.

Three layers:
  1. syntax   - command shape vs known Junos hierarchy templates
  2. semantics- cross-field checks (vlan exists, interface naming, ...)
  3. consistency - whole-config invariants (vlan referenced on access port, etc.)

All three are rule-based (no LLM): a translation never silently passes as
PASS based on the model's assurance -- the rules decide.
"""

import re
from typing import Dict, List, Tuple

# 1. SYNTAX: known Junos hierarchy templates

# template parts: literal strings or placeholders (<x>, {<x>} = optional)
JUNOS_HIERARCHY_TEMPLATES = [
    ["system", "host-name", "<name>"],
    ["system", "ntp", "server", "<addr>"],
    ["system", "syslog", "host", "<addr>"],
    ["system", "name-server", "<addr>"],
    ["system", "services", "ssh", "protocol-version", "v2"],
    ["system", "login", "user", "<name>", "uid"],
    ["system", "login", "user", "<name>", "class"],
    ["system", "login", "user", "<name>", "authentication", "encrypted-password", "<pw>"],
    ["system", "login", "message", "<text>"],
    ["snmp", "community", "<comm>", "authorization", "read-only"],
    ["snmp", "location", "<str>"],
    ["snmp", "contact", "<str>"],
    ["protocols", "ospf"],
    ["protocols", "ospf", "router-id", "<addr>"],
    ["protocols", "ospf", "area", "<area>", "interface", "<ifname>"],
    ["protocols", "ospf", "area", "<area>", "network", "<net>"],
    ["protocols", "bgp", "group", "<name>", "type", "external"],
    ["protocols", "bgp", "group", "<name>", "peer-as", "<asn>"],
    ["protocols", "bgp", "group", "<name>", "neighbor", "<addr>"],
    ["protocols", "lldp", "interface", "all"],
    ["protocols", "lldp", "disable"],
    ["routing-options", "static", "route", "<net>", "next-hop", "<addr>"],
    ["routing-options", "static", "route", "<net>", "discard"],
    ["vlans", "<vname>", "vlan-id", "<id>"],
    ["vlans", "<vname>", "vlan-range", "<range>"],
    ["interfaces", "<ifname>"],
    ["interfaces", "<ifname>", "description", "<text>"],
    ["interfaces", "<ifname>", "disable"],
    ["interfaces", "<ifname>", "mtu", "<n>"],
    ["interfaces", "<ifname>", "unit", "<unit>"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "inet"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "inet", "address", "<addr>"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "inet6"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "ethernet-switching", "interface-mode", "access"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "ethernet-switching", "interface-mode", "trunk"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "ethernet-switching", "vlan", "members", "{<vlan>|...}"],
    ["interfaces", "<ifname>", "unit", "<unit>", "family", "ethernet-switching", "port-mode", "trunk"],
    ["system", "authentication", "authentication-method", "<method>"],
]


def _template_match(parts: List[str], template: List[str]) -> bool:
    """Match command path parts against a template. Placeholder <x> matches
    exactly one part; {<x>} matches zero or one; a trailing <x> placeholder
    may consume any remaining tokens (multi-word values like descriptions)."""
    pi, ti = 0, 0
    while pi < len(parts) and ti < len(template):
        t = template[ti]
        if t.startswith("{") and t.endswith("}"):
            if pi < len(parts):
                pi += 1
            ti += 1
            continue
        if t.startswith("<"):
            # if this is the last template piece, consume the rest as value
            if ti == len(template) - 1:
                return True
            pi += 1
            ti += 1
            continue
        if parts[pi] == t:
            pi += 1
            ti += 1
            continue
        return False
    return pi == len(parts) and ti == len(template)


def validate_commands(commands: List[str], vendor: str = "junos") -> Tuple[List[dict], List[dict]]:
    """
    Validate a list of rendered commands. Returns (results, issues) where
    results is one dict per command and issues is a flat problem list.

    `vendor` selects the target syntax so the same function validates Junos
    `set` hierarchies and Cisco IOS block-structured configurations.
    """
    is_cisco = (vendor or "").lower() in ("cisco", "ios")
    results = []
    issues = []

    for cmd in commands:
        stripped = cmd.strip()
        if stripped.startswith("#") or stripped == "!":
            results.append({"command": stripped, "level": "ok", "messages": []})
            continue

        if is_cisco:
            level, messages = _validate_cisco_line(stripped)
        else:
            level, messages = _validate_junos_line(stripped)

        results.append({"command": stripped, "level": level, "messages": messages})
        if messages:
            issues.append({"command": stripped, "level": level, "messages": messages})

    return results, issues


def _validate_junos_line(stripped: str) -> Tuple[str, List[str]]:
    if not stripped.startswith("set ") and not stripped.startswith("delete "):
        return "error", ["Not a junos set/delete command: %s" % stripped[:60]]

    body = stripped[4:].strip()
    words = body.split()
    if not words:
        return "error", ["Empty set command"]

    # drop trailing leaf value tokens for hierarchy matching
    path_words = words
    eq = next((i for i, w in enumerate(words) if "=" in w), None)
    if eq is not None:
        path_words = [w.split("=")[0] for w in words[:eq + 1]]

    for template in JUNOS_HIERARCHY_TEMPLATES:
        if _template_match(path_words, template):
            return "ok", []

    return "warning", [f"Unknown Junos hierarchy: {body[:90]}"]


# Cisco IOS top-level block headers and the indented commands allowed inside.
CISCO_BLOCK_HEADERS = {
    "hostname", "ip ssh version", "ip ssh time-out", "ntp server", "logging host",
    "logging buffered", "snmp-server community", "snmp-server location",
    "snmp-server contact", "banner", "ip name-server", "no ip http server",
    "ip http server", "no cdp run", "cdp run", "aaa", "username", "enable secret",
    "ip route", "service password-encryption", "no service password-encryption",
    "line vty", "interface", "vlan", "router ospf", "router bgp",
    "transport input", "no snmp-server community",
}

CISCO_IFACE_COMMANDS = {
    "description", "ip address", "shutdown", "no shutdown", "mtu", "duplex",
    "speed", "switchport", "no switchport", "ip ospf", "no ip ospf",
    "channel-group", "no channel-group", "standby", "bandwidth", "ip helper-address",
}

CISCO_ROUTER_COMMANDS = {
    "network", "router-id", "neighbor", "no neighbor", "redistribute", "passive-interface",
    "no passive-interface", "auto-cost", "log-adjacency-changes",
}


def _validate_cisco_line(stripped: str) -> Tuple[str, List[str]]:
    """Validate one Cisco IOS config line (a block header or a child command)."""
    if stripped.endswith("!"):
        return "ok", []
    if stripped == "!" or not stripped:
        return "ok", []

    indented = stripped.startswith(" ") or stripped.startswith("\t")
    tokens = stripped.split()

    if indented:
        command = tokens[0].lower()
        if command in CISCO_IFACE_COMMANDS or command in CISCO_ROUTER_COMMANDS:
            return "ok", []
        # Sub-commands of switchport/logging/etc. that are not enumerated above.
        if any(command.startswith(prefix) for prefix in
               ("switchport", "ip ", "logging ", "snmp-server ", "ntp ", "standby ")):
            return "ok", []
        return "warning", [f"Unknown Cisco interface/router command: {stripped[:60]}"]

    header = tokens[0].lower()
    if header in {"interface", "vlan", "line", "router"}:
        if len(tokens) < 2:
            return "error", [f"Incomplete Cisco block header: {stripped[:60]}"]
        return "ok", []

    if any(stripped.lower().startswith(prefix + " ") or stripped.lower() == prefix
           for prefix in CISCO_BLOCK_HEADERS if " " in prefix or True):
        return "ok", []

    return "warning", [f"Unknown Cisco global command: {stripped[:60]}"]


# 2. SEMANTICS: cross-field checks

def validate_semantics(ir, commands: List[str], vendor: str = "junos") -> List[dict]:
    """Cross-field checks that need the IR and the rendered output together."""
    problems = []
    is_cisco = (vendor or "").lower() in ("cisco", "ios")
    joined = " ".join(commands)
    vlan_ids = {str(v.vlan_id) for v in ir.vlans}

    if is_cisco:
        # access/trunk vlan must be defined in the config
        for m in re.finditer(r"switchport access vlan (\d+)", joined):
            vid = m.group(1)
            # An empty vlan set means the config declares no VLANs at all, which
            # is itself the finding: the port references a VLAN nobody defined.
            if vid not in vlan_ids:
                problems.append({
                    "level": "warning", "command": m.group(0),
                    "messages": [f"VLAN {vid} assigned but not defined in config."],
                })
        # a trunk with no allowed-vlan list will carry nothing useful
        if "switchport mode trunk" in joined and "switchport trunk allowed vlan" not in joined:
            problems.append({
                "level": "warning", "command": "switchport mode trunk",
                "messages": ["Trunk port has no 'switchport trunk allowed vlan' list; "
                             "it will carry no VLANs by default."],
            })
    else:
        for m in re.finditer(r"ethernet-switching vlan members ([\w\-,\[\] ]+)", joined):
            val = m.group(1).strip()
            for vid in re.findall(r"\d+", val):
                if vlan_ids and vid not in vlan_ids:
                    problems.append({
                        "level": "warning", "command": m.group(0),
                        "messages": [f"VLAN {vid} referenced but not defined in config."],
                    })

    # banned duplicates of host-name / router-id
    if is_cisco:
        host_count = sum(1 for c in commands if c.strip().lower().startswith("hostname "))
    else:
        host_count = sum(1 for c in commands if c.startswith("set system host-name "))
    if host_count > 1:
        problems.append({"level": "error", "command": "host-name",
                         "messages": ["Multiple host-name statements."]})
    return problems


# 3. CONSISTENCY: whole-config invariants

def check_consistency(ir, commands: List[str], vendor: str = "junos") -> List[dict]:
    problems = []
    is_cisco = (vendor or "").lower() in ("cisco", "ios")

    for itf in ir.interfaces:
        if is_cisco:
            j = itf.cisco_name or itf.name
        else:
            j = itf.juniper_name or itf.name
        if itf.vlan_mode == "access" and not itf.vlan_members:
            problems.append({
                "level": "warning", "command": f"interfaces {j}",
                "messages": [f"Interface {itf.cisco_name or itf.juniper_name} is access "
                             "mode but has no vlan assigned."]})
        if itf.vlan_mode == "trunk" and itf.vlan_members:
            problems.append({
                "level": "info", "command": f"interfaces {j}",
                "messages": [f"Interface {itf.cisco_name or itf.juniper_name} trunk: "
                             "verify allowed vlans list on the target device."]})
    return problems


def all_ok(results: List[dict]) -> bool:
    return all(r["level"] != "error" for r in results if r["command"].strip())