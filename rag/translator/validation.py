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


def validate_commands(commands: List[str]) -> Tuple[List[dict], List[dict]]:
    """
    Validate a list of rendered commands. Returns (results, issues) where
    results is one dict per command and issues is a flat problem list.
    """
    results = []
    issues = []
    for cmd in commands:
        stripped = cmd.strip()
        if not stripped.startswith("set ") and not stripped.startswith("delete "):
            if stripped.startswith("#"):
                results.append({"command": stripped, "level": "ok", "messages": []})
                continue
            results.append({"command": stripped, "level": "error",
                            "messages": ["Not a junos set/delete command: %s" % stripped[:60]]})
            issues.append({"command": stripped, "level": "error",
                           "messages": ["Not a junos set/delete command"]})
            continue

        body = stripped[4:].strip()
        words = body.split()
        if not words:
            results.append({"command": stripped, "level": "error",
                            "messages": ["Empty set command"]})
            issues.append({"command": stripped, "level": "error", "messages": ["Empty set command"]})
            continue

        # drop trailing leaf value tokens for hierarchy matching
        path_words = words
        eq = next((i for i, w in enumerate(words) if "=" in w), None)
        if eq is not None:
            path_words = [w.split("=")[0] for w in words[:eq + 1]]

        known = False
        reason = ""
        for template in JUNOS_HIERARCHY_TEMPLATES:
            if _template_match(path_words, template):
                known = True
                break
        if not known:
            reason = f"Unknown Junos hierarchy: {body[:90]}"
            results.append({"command": stripped, "level": "warning",
                            "messages": [reason]})
            issues.append({"command": stripped, "level": "warning", "messages": [reason]})
            continue

        results.append({"command": stripped, "level": "ok", "messages": []})

    return results, issues


# 2. SEMANTICS: cross-field checks

def validate_semantics(ir, commands: List[str]) -> List[dict]:
    problems = []
    vlan_ids = {str(v.vlan_id) for v in ir.vlans}
    # access-port vlan must exist
    for m in re.finditer(r"ethernet-switching vlan members ([\w\-,\[\] ]+)", " ".join(commands)):
        val = m.group(1).strip()
        for vid in re.findall(r"\d+", val):
            if vlan_ids and vid not in vlan_ids:
                problems.append({
                    "level": "warning",
                    "command": m.group(0),
                    "messages": [f"VLAN {vid} referenced but not defined in config."],
                })
    # banned duplicates of host-name / router-id
    host_count = sum(1 for c in commands if c.startswith("set system host-name "))
    if host_count > 1:
        problems.append({"level": "error", "command": "system host-name",
                         "messages": ["Multiple host-name statements."]})
    return problems


# 3. CONSISTENCY: whole-config invariants

def check_consistency(ir, commands: List[str]) -> List[dict]:
    problems = []
    # every access interface should have a vlan members; trunk must define mode
    for itf in ir.interfaces:
        j = itf.juniper_name or itf.name
        if itf.vlan_mode == "access" and not itf.vlan_members:
            problems.append({
                "level": "warning", "command": f"interfaces {j}",
                "messages": [f"Interface {itf.cisco_name} is access mode but has no vlan assigned."]})
        if itf.vlan_mode == "trunk" and itf.vlan_members:
            problems.append({
                "level": "info", "command": f"interfaces {j}",
                "messages": [f"Interface {itf.cisco_name} trunk: verify allowed vlans list in Junos."]})
    return problems


def all_ok(results: List[dict]) -> bool:
    return all(r["level"] != "error" for r in results if r["command"].strip())