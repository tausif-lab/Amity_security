import re
PLACEHOLDERS = {"", "unknown", "n/a", "na", "none", "null"}
PW_TYPES = {"0": "plain", "7": "type7", "type7": "type7", "5": "md5", "8": "sha256", "9": "scrypt"}
PW_RANK = ["plain", "type7", "md5", "sha256", "scrypt"]   # weakest first


def sanitize(data, node, config_text=""):
    """Walk the output along the schema. Placeholder strings and values outside
    an enum become None, so the rule engine reports Unknown instead of a fake value."""
    t = node.get("type")
    if t == "object" and isinstance(data, dict):
        props = node.get("properties", {})
        return {k: sanitize(v, props.get(k, {}), config_text) for k, v in data.items()}
    if t == "array" and isinstance(data, list):
        return [sanitize(x, node.get("items", {}), config_text) for x in data]
    if isinstance(data, str):
        if data.strip().lower() in PLACEHOLDERS:
            return None
        enum = node.get("enum")
        if enum and data not in enum:
            return None
    return data


def drop_unsupported_interfaces(data, config_text):
    """Keep only interfaces whose name literally appears in the config text."""
    text = config_text.lower()
    data["interfaces"] = [
        i for i in (data.get("interfaces") or [])
        if isinstance(i, dict) and str(i.get("name", "")).lower() in text
    ]
    return data


def _set_path(data, path, value):
    cur = data
    for key in path[:-1]:
        if not isinstance(cur.get(key), dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def cisco_fact_overrides(config_text):
    """Facts literally present on single Cisco lines. Returns [(path, value), ...]."""
    found = []
    ntp = re.findall(r"^\s*ntp server\s+(\S+)", config_text, re.M)
    if ntp:
        found.append((("ntp", "servers"), ntp))
    hosts = re.findall(r"^\s*logging host\s+(\S+)", config_text, re.M)
    if hosts:
        found.append((("logging", "remote_servers"), hosts))
    if re.search(r"^\s*logging buffered", config_text, re.M):
        found.append((("logging", "local_buffered"), True))
    if re.search(r"^\s*ip http server", config_text, re.M):
        found.append((("management", "http_enabled"), True))
    elif re.search(r"^\s*no ip http server", config_text, re.M):
        found.append((("management", "http_enabled"), False))
    communities = re.findall(r"^\s*snmp-server community\s+(\S+)", config_text, re.M)
    if communities:
        found.append((("management", "snmp", "community_strings"), communities))
    if (re.search(r"^\s*transport input ssh\s*$", config_text, re.M)
            and not re.search(r"transport input .*\b(telnet|all)\b", config_text)):
        found.append((("management", "telnet_enabled"), False))

    kinds = [PW_TYPES[k] for k in re.findall(r"\b(?:secret|password)\s+(type7|\d)\b", config_text)
             if k in PW_TYPES]
    if kinds:
        found.append((("authentication", "password_encryption"), min(kinds, key=PW_RANK.index)))
    return found


def apply_overrides(normalized_data, config_text, vendor):
    if (vendor or "").lower() in ("cisco", "ios"):
        for path, value in cisco_fact_overrides(config_text):
            _set_path(normalized_data, path, value)
    normalized_data["vendor"] = (vendor or "").lower()   # known from the form, never ask the LLM
    return normalized_data