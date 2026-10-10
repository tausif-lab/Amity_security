"""
ai_engine/services/ingest.py

Unified Ingestion Engine (slide 2/3: "CLI, JSON, YAML, XML").

Detects the format of an uploaded config and converts JSON/YAML/XML into the
plain CLI text the LLM normalizer already understands, so every downstream
stage (fact extraction, compliance engine, drift) keeps working on one shape.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

try:
    import yaml
    HAVE_YAML = True
except ImportError:      # optional: CLI/JSON/XML still work without PyYAML
    HAVE_YAML = False


def detect_format(text: str) -> str:
    """Sniff the config format. Returns one of cli|json|yaml|xml."""
    stripped = (text or "").lstrip()
    if not stripped:
        return "cli"

    # JSON first: it is a strict subset of YAML, so order matters.
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            pass

    if stripped.startswith("<"):
        try:
            ET.fromstring(stripped)
            return "xml"
        except ET.ParseError:
            pass

    if HAVE_YAML:
        try:
            loaded = yaml.safe_load(stripped)
            if isinstance(loaded, (dict, list)):
                # Guard against a stray ':' in CLI text being read as a mapping.
                if re.search(r"^\s*[\w.-]+\s*:", stripped, re.M):
                    return "yaml"
        except Exception:
            pass

    return "cli"


def _xml_to_dict(elem):
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    return {child.tag: _xml_to_dict(child) for child in children}


def _flatten_mapping(data, vendor: str) -> str:
    """Turn a structured config into vendor-flavoured CLI-ish lines.

    Keys are mapped to the command each vendor actually uses, because the point
    of the conversion is to hand the LLM text it can read without a translation
    step. Unknown keys fall back to a readable "key value" line so nothing is
    silently dropped.
    """
    if isinstance(data, list):
        return "\n".join(_flatten_mapping(item, vendor) for item in data)
    if not isinstance(data, dict):
        return str(data)

    is_cisco = vendor.lower() in ("cisco", "ios")
    lines = []

    def emit(key: str, value):
        k = str(key).strip()
        if isinstance(value, dict):
            for sub, subval in value.items():
                emit(f"{k}.{sub}", subval)
            return
        if isinstance(value, list):
            for item in value:
                emit(k, item)
            return
        v = str(value).strip()
        if v == "":
            return
        # Map a small, high-signal set of canonical keys to real CLI commands.
        if is_cisco:
            if k == "hostname":
                lines.append(f"hostname {v}")
            elif k == "ntp.server":
                lines.append(f"ntp server {v}")
            elif k == "logging.host":
                lines.append(f"logging host {v}")
            elif k == "logging.buffered" and v.lower() in ("true", "1"):
                lines.append("logging buffered 4096")
            elif k == "ip_http_server" and v.lower() in ("true", "1"):
                lines.append("ip http server")
            elif k == "snmp.community":
                lines.append(f"snmp-server community {v} ro")
            elif k == "enable_secret":
                lines.append(f"enable secret type7 {v}")
            elif k == "transport_input":
                lines.append(f" transport input {v}")
            else:
                lines.append(f"{k} {v}")
        else:  # juniper
            if k == "hostname":
                lines.append(f"set system host-name {v}")
            elif k == "ntp.server":
                lines.append(f"set system ntp server {v}")
            elif k == "logging.host":
                lines.append(f"set system syslog host {v} any any")
            elif k == "snmp.community":
                lines.append(f"set snmp community {v} authorization read-only")
            elif k == "telnet" and v.lower() in ("true", "1"):
                lines.append("set system services telnet")
            else:
                lines.append(f"set {k.replace('.', ' ')} {v}")

    for key, value in data.items():
        emit(key, value)
    return "\n".join(line for line in lines if line.strip())


def _strip_xml_tag_markers(text: str) -> str:
    """Fallback when a document is XML-ish but not well-formed."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def to_cli_text(text: str, vendor: str) -> tuple[str, str]:
    """Convert any supported format to CLI text.

    Returns (cli_text, detected_format). On an unrecognised or unparseable
    format the ORIGINAL text is returned untouched with format "cli": the
    normalizer handles raw CLI perfectly well, and a failed guess must never
    make the input worse than what the user actually uploaded.
    """
    fmt = detect_format(text)
    if fmt == "cli":
        return text, "cli"

    try:
        if fmt == "json":
            return _flatten_mapping(json.loads(text), vendor), "json"
        if fmt == "yaml":
            if not HAVE_YAML:
                return text, "cli"
            return _flatten_mapping(yaml.safe_load(text), vendor), "yaml"
        if fmt == "xml":
            root = ET.fromstring(text)
            data = _xml_to_dict(root)
            return _flatten_mapping(data, vendor), "xml"
    except Exception as exc:
        logger.info("Ingestion conversion from %s failed (%s); using raw text", fmt, exc)
        return text, "cli"

    return text, fmt


def ingest(config_text: str, vendor: str) -> tuple[str, str]:
    """Public entry point used by the upload views."""
    return to_cli_text(config_text, vendor)