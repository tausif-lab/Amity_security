# NEW FILE: core/services/nl_query.py
"""Natural-language search over the latest normalized config of every device.

The LLM only translates the question into a small JSON filter built from a CLOSED list of
fields. It never reads configs and never produces facts: validate_filter() rejects anything
outside the list, and run_filter() answers from the stored normalized_config in the database.
"""
import json
import os

import requests

QUERY_MODEL = os.environ.get("QUERY_LLM_MODEL", "qwen2.5:3b")
QUERY_TIMEOUT = int(os.environ.get("QUERY_LLM_TIMEOUT", "180"))
MAX_CONDITIONS = 3

# The closed taxonomy. `path` is where the value lives inside ConfigSnapshot.normalized_config.
FIELDS = {
    "telnet_enabled":        {"path": "management.telnet_enabled", "type": "bool", "label": "Telnet enabled"},
    "http_enabled":          {"path": "management.http_enabled", "type": "bool", "label": "HTTP server enabled"},
    "https_enabled":         {"path": "management.https_enabled", "type": "bool", "label": "HTTPS server enabled"},
    "ssh_version":           {"path": "management.ssh_version", "type": "int", "label": "SSH version"},
    "snmp_version":          {"path": "management.snmp.version", "type": "str", "label": "SNMP version (v1, v2c, v3)"},
    "snmp_community":        {"path": "management.snmp.community_strings", "type": "list", "label": "SNMP community strings"},
    "password_encryption":   {"path": "authentication.password_encryption", "type": "str", "label": "Password encryption type"},
    "aaa_methods":           {"path": "authentication.aaa_methods", "type": "list", "label": "AAA methods"},
    "remote_logging_servers": {"path": "logging.remote_servers", "type": "list", "label": "Remote syslog servers"},
    "local_logging_buffered": {"path": "logging.local_buffered", "type": "bool", "label": "Local log buffer enabled"},
    "ntp_servers":           {"path": "ntp.servers", "type": "list", "label": "NTP servers"},
    "ntp_authenticated":     {"path": "ntp.authenticated", "type": "bool", "label": "NTP authentication enabled"},
    "routing_protocols":     {"path": "routing.protocols", "type": "list", "label": "Routing protocols (ospf, bgp, eigrp, rip)"},
    "ospf_authentication":   {"path": "routing.authentication.ospf", "type": "bool", "label": "OSPF authentication enabled"},
    "bgp_authentication":    {"path": "routing.authentication.bgp", "type": "bool", "label": "BGP authentication enabled"},
    "vendor":                {"path": "vendor", "type": "str", "label": "Vendor in the config"},
    "os_version":            {"path": "os_version", "type": "str", "label": "OS version"},
}
OPS = {
    "bool": {"eq", "ne"},
    "int": {"eq", "ne", "gt", "gte", "lt", "lte"},
    "str": {"eq", "ne", "contains"},
    "list": {"contains", "not_contains", "empty", "not_empty"},
}
OP_TEXT = {"eq": "is", "ne": "is not", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
           "contains": "includes", "not_contains": "does not include",
           "empty": "is empty", "not_empty": "is not empty"}

EXAMPLES = [
    ("which devices have http enabled", {"conditions": [{"field": "http_enabled", "op": "eq", "value": True}]}),
    ("telnet is on in tenant Acme", {"conditions": [{"field": "telnet_enabled", "op": "eq", "value": True}], "tenant": "Acme"}),
    ("devices using the public snmp community", {"conditions": [{"field": "snmp_community", "op": "contains", "value": "public"}]}),
    ("not running ssh version 2", {"conditions": [{"field": "ssh_version", "op": "ne", "value": 2}]}),
    ("cisco devices with no remote logging", {"conditions": [{"field": "remote_logging_servers", "op": "empty"}], "vendor": "cisco"}),
    ("what is the weather today", {"unsupported": True}),
]


# ---- 1. question -> filter (the only LLM step) ----------------------------------------------

def build_prompt(question, tenant_names):
    fields = "\n".join(f"{k} | {v['type']} | {v['label']}" for k, v in FIELDS.items())
    shots = "\n".join(
        f"Q: {q}\nA: " + json.dumps({"conditions": [], "tenant": None, "vendor": None, "site": None, **a}
                                     if "conditions" in a else a)
        for q, a in EXAMPLES)
    return (
        "You convert a question about network devices into ONE JSON filter. Output JSON only.\n\n"
        f"Allowed fields (name | type | meaning). Use these names exactly:\n{fields}\n\n"
        "Operators: eq, ne (bool, int, str); gt, gte, lt, lte (int); contains (str, list); "
        "not_contains, empty, not_empty (list).\n"
        'Shape: {"conditions":[{"field":"..","op":"..","value":..}],"tenant":null,"vendor":null,"site":null}\n'
        f"Known tenants: {', '.join(tenant_names) or '(none)'}\n\n"
        "Rules:\n"
        "- bool fields take value true or false. enabled / on / running / has -> true. disabled / off -> false.\n"
        '- If the question cannot be answered with the allowed fields, output {"unsupported": true}.\n'
        "- Never answer the question and never invent devices. Only describe the filter.\n\n"
        f"{shots}\nQ: {question}\nA:"
    )


def ask_llm(question, tenant_names):
    """Returns the model's raw JSON (a dict) or None. Raises OllamaUnavailable if Ollama is down."""
    from django.conf import settings
    from ai_engine.services.ollama_client import OllamaUnavailable, _parse_json_lenient
    payload = {
        "model": QUERY_MODEL, "prompt": build_prompt(question, tenant_names), "stream": False,
        "format": "json", "keep_alive": "30m",       # keep the model loaded between questions
        "options": {"temperature": 0, "num_predict": 200, "num_ctx": 2048},
    }
    try:
        resp = requests.post(f"{settings.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=QUERY_TIMEOUT)
    except requests.RequestException as exc:
        raise OllamaUnavailable(f"Cannot reach Ollama: {exc}. Is `ollama serve` running?") from exc
    if resp.status_code == 404:
        raise OllamaUnavailable(f"Ollama has no model named '{QUERY_MODEL}'. Run `ollama pull {QUERY_MODEL}`.")
    resp.raise_for_status()
    return _parse_json_lenient(resp.json().get("response", ""))


# ---- 2. validate the model's output against the closed list ---------------------------------

def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "yes", "enabled", "on", "1"}:
            return True
        if s in {"false", "no", "disabled", "off", "0"}:
            return False
    return None


def validate_filter(raw, tenant_names):
    """Returns (clean_filter, None) or (None, message). Nothing outside FIELDS/OPS gets through."""
    if not isinstance(raw, dict) or raw.get("unsupported"):
        return None, "unsupported"
    items = raw.get("conditions")
    if not isinstance(items, list) or not items or len(items) > MAX_CONDITIONS:
        return None, "unsupported"

    conditions = []
    for c in items:
        spec = FIELDS.get(c.get("field")) if isinstance(c, dict) else None
        op = c.get("op") if spec else None
        if spec is None or op not in OPS[spec["type"]]:
            return None, "unsupported"
        value, kind = c.get("value"), spec["type"]
        if kind == "bool":
            value = _as_bool(value)
            if value is None:
                return None, "unsupported"
            if op == "ne":
                op, value = "eq", not value
        elif kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return None, "unsupported"
        elif kind == "list" and op in ("empty", "not_empty"):
            value = None
        else:                                                    # str, and list contains
            value = str(value).strip() if value is not None else ""
            if not value:
                return None, "unsupported"
        conditions.append({"field": c["field"], "op": op, "value": value})

    clean = {"conditions": conditions, "tenant": None, "vendor": None, "site": None}
    tenant = raw.get("tenant")
    if tenant not in (None, "", "null"):
        match = next((t for t in tenant_names if t.lower() == str(tenant).strip().lower()), None)
        if match is None:
            return None, f"There is no tenant named '{tenant}'."
        clean["tenant"] = match
    for key in ("vendor", "site"):
        v = raw.get(key)
        clean[key] = str(v).strip() if v not in (None, "", "null") else None
    return clean, None


def describe(flt):
    parts = []
    for c in flt["conditions"]:
        v = "" if c["value"] is None else f" {json.dumps(c['value']) if not isinstance(c['value'], str) else c['value']}"
        parts.append(f"{FIELDS[c['field']]['label']} {OP_TEXT[c['op']]}{v}")
    text = " AND ".join(parts)
    scope = [f"{k}: {flt[k]}" for k in ("tenant", "vendor", "site") if flt[k]]
    return text + (f"  ({', '.join(scope)})" if scope else "")


# ---- 3. deterministic query over the stored normalized configs -------------------------------

def _get(cfg, path):
    cur = cfg
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def evaluate(cfg, cond):
    """Returns (state, actual). state is True / False, or None when the config does not say
    (the normalizer stores null for settings the file never mentions)."""
    spec = FIELDS[cond["field"]]
    actual = _get(cfg, spec["path"])
    if actual is None:
        return None, None
    kind, op, val = spec["type"], cond["op"], cond["value"]
    if kind == "bool":
        a = _as_bool(actual)
        return (None if a is None else a == val), actual
    if kind == "int":
        try:
            a = int(actual)
        except (TypeError, ValueError):
            return None, actual
        return {"eq": a == val, "ne": a != val, "gt": a > val, "gte": a >= val,
                "lt": a < val, "lte": a <= val}[op], actual
    if kind == "str":
        a, v = str(actual).strip().lower(), str(val).lower()
        return {"eq": a == v, "ne": a != v, "contains": v in a}[op], actual
    if not isinstance(actual, list):
        return None, actual
    items = [str(x).strip().lower() for x in actual]
    v = str(val).lower() if val is not None else ""
    return {"contains": v in items, "not_contains": v not in items,
            "empty": not items, "not_empty": bool(items)}[op], actual


def run_filter(flt, devices):
    """`devices` is the Device queryset this user may see (tenant isolation is applied by the caller)."""
    from core.models import ConfigSnapshot
    if flt["tenant"]:
        devices = devices.filter(tenant__name=flt["tenant"])
    if flt["vendor"]:
        devices = devices.filter(vendor__iexact=flt["vendor"])
    if flt["site"]:
        devices = devices.filter(site__iexact=flt["site"])

    snaps = ConfigSnapshot.objects.filter(is_latest=True, device__in=devices).select_related("device__tenant")
    matched, unknown, scanned, newest = [], 0, 0, None
    for s in snaps:
        scanned += 1
        newest = s.uploaded_at if newest is None or s.uploaded_at > newest else newest
        results = [evaluate(s.normalized_config or {}, c) for c in flt["conditions"]]
        if any(state is False for state, _ in results):
            continue
        if any(state is None for state, _ in results):
            unknown += 1
            continue
        d = s.device
        matched.append({
            "device_id": d.device_id, "hostname": d.hostname, "tenant": d.tenant.name, "site": d.site,
            "vendor": d.vendor, "device_type": d.device_type, "serial_number": d.serial_number,
            "snapshot_id": s.id, "uploaded_at": s.uploaded_at, "uploaded_by": s.uploaded_by,
            "facts": [{"field": c["field"], "label": FIELDS[c["field"]]["label"], "value": actual}
                      for c, (_, actual) in zip(flt["conditions"], results)],
        })
    matched.sort(key=lambda m: m["device_id"])
    return {"count": len(matched), "scanned": scanned, "not_audited": devices.count() - scanned,
            "not_determined": unknown, "last_updated": newest, "devices": matched}


def catalog():
    return [{"field": k, "label": v["label"], "type": v["type"]} for k, v in FIELDS.items()]