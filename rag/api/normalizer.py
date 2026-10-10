"""
rag/api/normalizer.py
Turn the translator's result dict into the normalized JSON document and
write it to the rag directory as `normalised_{target_vendor}.json`.
"""

import json
import re
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parents[1]
AI_ENGINE_DIR = RAG_DIR.parent / "ai_engine"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "vendor"


def target_filepath(target_vendor: str) -> Path:
    return RAG_DIR / f"normalised_{slugify(target_vendor)}.json"

def source_txt_filepath(source_stem : str , target_vendor : str) -> Path:
    stem = slugify(source_stem) if source_stem else "sample_config"
    return AI_ENGINE_DIR / f"{stem}_to_{slugify(target_vendor)}.txt"

def ai_engine_filepath(target_vendor: str) -> Path:
    return AI_ENGINE_DIR / f"normalised_{slugify(target_vendor)}.json"


def ai_engine_baseline_filepath(target_vendor: str) -> Path:
    return AI_ENGINE_DIR / f"normalised_{slugify(target_vendor)}_baseline.json"


def ir_to_baseline(ir: dict, target_vendor: str) -> dict:
    """Map the translator's IR dict into ai_engine's normalized_schema.json shape.

    The output passes ai_engine.services.validator.validate_normalized_json and
    is consumable by compliance.services.rule_engine.compliance_engine.

    `target_vendor` decides which way the security booleans read: a translated
    Cisco config has telnet off by default, whereas Junos enables telnet only
    when `set system services telnet` is present (which the IR records).
    """
    gc = ir.get("global_config", {}) if ir else {}
    snmp = gc.get("snmp", {}) or {}
    logging_ir = gc.get("logging", {}) or {}
    ntp_ir = gc.get("ntp", {}) or {}
    aaa = gc.get("aaa", {}) or {}

    target = (target_vendor or "cisco").lower()
    is_cisco_target = target in ("cisco", "ios")

    protocols = []
    for proto in ("ospf", "bgp", "eigrp", "rip"):
        if ir.get(proto):
            protocols.append(proto)
    if ir.get("static_routes"):
        protocols.append("static")
    protocols = list(dict.fromkeys(protocols))

    interfaces = []
    for i in (ir or {}).get("interfaces", []):
        # Name the interface the way the TARGET platform spells it, because the
        # compliance rule set is chosen by target vendor.
        name = (i.get("cisco_name") if is_cisco_target
                else i.get("juniper_name") or i.get("name"))
        interfaces.append({
            "name": name or i.get("name") or i.get("cisco_name"),
            "admin_down": not bool(i.get("enabled", True)),
            "cdp_enabled": i.get("cdp_enabled", True),
            "lldp_enabled": None,
        })

    return {
        "vendor": ("cisco" if is_cisco_target else target),
        "hostname": gc.get("hostname"),
        "os_version": None,
        "management": {
            "ssh_version": gc.get("ssh_version"),
            "telnet_enabled": bool(gc.get("telnet_enabled", False)),
            "http_enabled": bool(gc.get("ip_http_server", False)),
            "https_enabled": None,
            "snmp": {
                "version": None,
                "community_strings": snmp.get("community_strings") or [],
            },
        },
        "authentication": {
            "aaa_methods": aaa.get("methods") or [],
            "password_encryption": gc.get("password_encryption"),
        },
        "logging": {
            "remote_servers": logging_ir.get("hosts") or [],
            "local_buffered": bool(logging_ir.get("buffered", False)),
        },
        "ntp": {
            "servers": ntp_ir.get("servers") or [],
            "authenticated": None,
        },
        "routing": {
            "protocols": protocols,
            "authentication": {"ospf": False, "bgp": False},
        },
        "interfaces": interfaces,
        "banners": {"motd": gc.get("motd"), "login": None},
        "raw_commands": gc.get("raw_commands") or [],
    }


def build_normalized_response(
    result: dict,
    source_vendor: str,
    target_vendor: str,
    saved_path: str,
) -> dict:
    """Attach vendor metadata + a plain Junos text form to the engine result."""
    set_commands = result.get("set_commands") or []

    document = {
        "run_id": result.get("run_id"),
        "source_vendor": source_vendor,
        "target_vendor": target_vendor,
        "saved_path": saved_path,
        "status": result.get("status"),
        "overall_confidence": result.get("overall_confidence"),
        "confidence_by_category": result.get("confidence_by_category"),
        "set_commands": set_commands,
        "normalized_config": "\n".join(set_commands),
        "ir": result.get("ir"),
        "explanations": result.get("explanations"),
        "warnings": result.get("warnings"),
        "unresolved": result.get("unresolved"),
        "rounds": result.get("rounds"),
    }
    return document


def save_normalized(document: dict, target_path: Path = None) -> Path:
    """Write the document to normalised_{target_vendor}.json in the rag dir."""
    path = target_path or target_filepath(document.get("target_vendor", "junos"))
    payload = json.dumps(document, indent=2, ensure_ascii=False, default=str)
    path.write_text(payload, encoding="utf-8")
    return path