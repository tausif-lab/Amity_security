"""
compliance/services/remediation.py

⚠️ SAFETY NOTE:
This module can push LLM-generated CLI commands onto a LIVE network device.

- generate_remediation_commands() only PROPOSES commands. Safe, read-only.
- execute_remediation() actually pushes config to the device. Only call
  this from an endpoint that requires explicit human confirmation.
- Never call execute_remediation() automatically as part of the normal
  upload -> normalize -> compliance-check flow.
"""

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


def build_corrected_config(original_config_text: str, normalized_data: dict, 
                             compliance_results: list, instructions: dict) -> str:
    """
    Produces a full corrected config: original lines for Pass rules kept as-is,
    AI-generated fixes inserted (with comments) for Fail rules.
    Does NOT touch any device — output is a text file only.
    """
    vendor = normalized_data.get("vendor", "unknown")
    os_version = normalized_data.get("os_version", "unknown")

    output_lines = [
        f"! Corrected configuration - generated {vendor}",
        "! Lines marked [AI-FIX] were changed to meet CIS benchmark requirements",
        "! Review every AI-FIX line before applying to any device",
        "",
        original_config_text,
        "",
        "! ===== AI-Suggested Fixes for Failed Rules =====",
    ]

    failed_rules = [r for r in compliance_results if r["status"] == "Fail"]
    for rule in failed_rules:
        commands = generate_remediation(vendor, os_version, rule, instructions)
        output_lines.append(f"! [AI-FIX] {rule['rule_id']} - {rule['name']}")
        for cmd in commands:
            output_lines.append(cmd)
        output_lines.append("")

    return "\n".join(output_lines)