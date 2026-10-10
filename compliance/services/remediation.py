"""
compliance/services/remediation.py

⚠️ SAFETY NOTE:
This module can push LLM-generated CLI commands onto a LIVE network device.

- generate_remediation_commands() only PROPOSES commands. Safe, read-only.
- execute_remediation() actually pushes config to the device. Only call
  this from an endpoint that requires explicit human confirmation.
- Never call execute_remediation() automatically as part of the normal
  upload -> normalize -> compliance-check flow.

build_corrected_config() rewrites the uploaded config into a real, applicable
file: deterministic fixes edit the actual command lines, and the LLM is consulted
only for the rules no deterministic fix covers.
"""

import re
import time

from ai_engine.services.ollama_client import generate_remediation


def generate_remediation_commands(normalized_data: dict, failed_rules: list, instructions: dict) -> list:
    """For each failed rule, ask the LLM for candidate fix commands. Proposals only."""
    vendor = normalized_data.get("vendor", "unknown")
    os_version = normalized_data.get("os_version", "unknown")

    proposals = []
    for rule in failed_rules:
        commands = generate_remediation(vendor, os_version, rule, instructions)
        proposals.append({
            "rule_id": rule["rule_id"],
            "name": rule["name"],
            "commands": commands,
        })
    return proposals


def execute_remediation(connection, commands: list, delay_seconds: int = 5) -> dict:
    """
    Pushes commands to a live device via an already-open netmiko connection.
    Caller (the view) must require explicit confirm=true and log who
    triggered this.
    """
    if not commands:
        return {"executed": False, "reason": "No commands provided."}

    time.sleep(delay_seconds)

    try:
        output = connection.send_config_set(commands)
        connection.send_command("write memory")
        return {"executed": True, "output": output}
    except Exception as e:
        return {"executed": False, "reason": str(e)}


# --------------------------------------------------------------------------
# Deterministic remediation catalogue
#
# These are applied as real edits to the config text, not appended as advice,
# because the deliverable is a file a human can read and apply. Model-proposed
# commands are used only where no deterministic edit exists (for example AAA,
# which needs a real RADIUS/TACACS+ server address that must not be invented).
# --------------------------------------------------------------------------

CISCO_LINE_FIXES = {
    "CIS-2.1.1": [(r"^(\s*)ip http server\s*$", r"\1no ip http server")],
    "CIS-1.1.3": [
        (r"^(\s*)transport input\s+.*(?:\btelnet\b|\ball\b).*$", r"\1transport input ssh"),
    ],
    "CIS-4.1.1": [
        (r"^(\s*)snmp-server community\s+(public|private)\b(.*)$",
         r"\1! [CIS-4.1.1] removed default community: snmp-server community \2\3"),
    ],
    "CIS-3.2.2": [
        (r"^(\s*)enable secret\s+type7\s+(\S+)\s*$",
         r"\1enable algorithm scrypt secret \2"),
        (r"^(\s*)enable password\s+type7\s+(\S+)\s*$",
         r"\1enable algorithm scrypt password \2"),
        (r"^(\s*)enable secret\s+7\s+(\S+)\s*$",
         r"\1enable algorithm scrypt secret \2"),
        # The same weak type-7 hashing applies to per-user credentials, and a
        # rule that only fixes `enable secret` would leave the weaker per-user
        # hash in place while the report claims the finding was remediated.
        (r"^(\s*)(username\s+\S+)\s+secret\s+(?:type7|7)\s+(\S+)\s*$",
         r"\1\2 algorithm scrypt secret \3"),
        (r"^(\s*)(username\s+\S+)\s+password\s+(?:type7|7)\s+(\S+)\s*$",
         r"\1\2 algorithm scrypt password \3"),
    ],
}

CISCO_APPEND_FIXES = {
    "CIS-1.1.2": ["ip ssh version 2"],
    "CIS-1.5.1": ["logging buffered 4096"],
}

CISCO_APPEND_TEMPLATES = {
    # These need an operator-supplied value, so emit a template rather than a
    # fabricated address.
    "CIS-1.6.1": ["! [CIS-1.6.1] uncomment and set your NTP server",
                   "! ntp server <NTP_SERVER_IP>"],
    "CIS-3.1.1": ["! [CIS-3.1.1] enable AAA with your RADIUS/TACACS+ servers",
                   "! aaa new-model",
                   "! aaa authentication login default group radius",
                   "! aaa authorization exec default group radius",
                   "! aaa accounting exec default start-stop group radius"],
}

JUNIPER_LINE_FIXES = {
    "CIS-6.10.6": [(r"^(\s*)set system services telnet\s*$",
                    r"\1delete system services telnet")],
}

JUNIPER_APPEND_FIXES = {
    "CIS-6.10.1.2": ["set system services ssh protocol-version v2"],
}

JUNIPER_APPEND_TEMPLATES = {
    "CIS-6.10.4": ["# [CIS-6.10.4] uncomment and set your NTP server",
                   "# set system ntp server <NTP_SERVER_IP>"],
}


def _apply_line_fixes(lines, patterns):
    """Apply regex substitutions in place. Returns (lines, change_count).

    Rebuilds the list by position rather than using list.index(line), which
    would rewrite the first duplicate and silently leave the rest untouched.
    """
    changes = 0
    result = []
    for line in lines:
        new_line = line
        for pattern, replacement in patterns:
            new_line, hits = re.subn(pattern, replacement, new_line)
            if hits:
                changes += hits
                break
        result.append(new_line)
    return result, changes


def _fix_catalogue(vendor):
    vendor = (vendor or "").lower()
    if vendor in ("juniper", "junos"):
        return JUNIPER_LINE_FIXES, JUNIPER_APPEND_FIXES, JUNIPER_APPEND_TEMPLATES
    return CISCO_LINE_FIXES, CISCO_APPEND_FIXES, CISCO_APPEND_TEMPLATES


def verify_deterministic_facts(fixed_text: str, vendor: str) -> dict:
    """Re-derive the facts the deterministic extractor can prove from text.

    This is deliberately not a second LLM normalization: it only confirms the
    specific settings that had a deterministic fix, so the file can claim
    "verified" for exactly those and stay silent about everything else.
    """
    try:
        from ai_engine.services.fact_extractor import apply_overrides
        return apply_overrides({}, fixed_text, vendor)
    except Exception:
        return {}


def build_corrected_config(original_config_text: str, normalized_data: dict,
                           compliance_results: list, instructions: dict) -> str:
    """
    Produces a full corrected config that can actually be applied:

    - deterministic edits rewrite the offending command lines in place
    - settings that are simply missing are appended
    - settings needing a real value are emitted as clearly marked templates
    - only rules with no deterministic fix fall back to a model proposal

    Does NOT touch any device; the output is a text file only.
    """
    vendor = (normalized_data.get("vendor") or "unknown")
    hostname = normalized_data.get("hostname") or "unknown"
    comment = "!" if vendor.lower() in ("cisco", "ios") else "#"

    line_fixes, append_fixes, append_templates = _fix_catalogue(vendor)
    failed_rules = [r for r in compliance_results if r["status"] == "Fail"]

    body = (original_config_text or "").splitlines()
    notes = []
    appended = []
    templated = []
    model_rules = []

    for rule in failed_rules:
        rule_id = rule["rule_id"]

        patterns = line_fixes.get(rule_id)
        if patterns:
            body, changes = _apply_line_fixes(body, patterns)
            if changes:
                notes.append((rule_id, rule["name"], f"rewrote {changes} command line(s) in place"))
                continue

        if rule_id in append_fixes:
            appended.extend(append_fixes[rule_id])
            notes.append((rule_id, rule["name"], f"appended: {', '.join(append_fixes[rule_id])}"))
            continue

        if rule_id in append_templates:
            templated.extend(append_templates[rule_id])
            notes.append((rule_id, rule["name"], "added a template; supply the value before applying"))
            continue

        model_rules.append(rule)

    # Anything still unhandled needs judgement about the real environment, so
    # it goes to the model and is clearly labelled as a proposal.
    proposed = []
    for rule in model_rules:
        commands = generate_remediation(vendor, normalized_data.get("os_version", "unknown"),
                                        rule, instructions)
        if commands:
            proposed.append((rule, commands))

    verified = verify_deterministic_facts("\n".join(body + appended), vendor)

    out = [
        f"{comment} ============================================================",
        f"{comment} CORRECTED CONFIGURATION - generated by Suraksha Astra",
        f"{comment} Device: {hostname} ({vendor})",
        f"{comment}",
        f"{comment} Remediations applied: {len(notes)} deterministic"
        f"{f', {len(proposed)} model-proposed' if proposed else ''}"
        f"{f', {len(templated)} template lines' if templated else ''}",
        f"{comment} Review every change before applying to a production device.",
        f"{comment} ============================================================",
        "",
    ]
    out.extend(body)

    if appended:
        out += ["", f"{comment} ===== Added to satisfy benchmark (review first) ====="]
        out.extend(appended)

    if templated:
        out += ["", f"{comment} ===== Templates: supply a real value before applying ====="]
        out.extend(templated)

    if proposed:
        out += ["", f"{comment} ===== Model-proposed changes: VERIFY BEFORE APPLYING ====="]
        for rule, commands in proposed:
            out.append(f"{comment} [{rule['rule_id']}] {rule['name']}")
            out.extend(commands)
            out.append("")

    out += ["", f"{comment} ===== Remediation notes ====="]
    if notes:
        for rule_id, name, detail in notes:
            out.append(f"{comment} [{rule_id}] {name}: {detail}")
    else:
        out.append(f"{comment} No deterministic fixes applied; see above for proposals.")
    if verified:
        out.append(f"{comment} Post-fix deterministic re-check: "
                   f"http_enabled={verified.get('management', {}).get('http_enabled')}, "
                   f"telnet_enabled={verified.get('management', {}).get('telnet_enabled')}, "
                   f"snmp={verified.get('management', {}).get('snmp', {}).get('community_strings')}")

    return "\n".join(out) + "\n"