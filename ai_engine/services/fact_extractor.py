import re
PLACEHOLDERS = {"", "unknown", "n/a", "na", "none", "null"}
PW_TYPES = {"0": "plain", "7": "type7", "type7": "type7", "5": "md5", "8": "sha256", "9": "scrypt"}
PW_RANK = ["plain", "type7", "md5", "sha256", "scrypt"]   # weakest first

# Routing is the field small models most often hallucinate: asked for a list
# whose enum is ["ospf","bgp","eigrp","rip"], they tend to answer with the whole
# enum instead of the protocols the config actually runs. Detect them from the
# literal config text instead, and leave the LLM no room to guess.
PROTOCOL_ORDER = ("ospf", "bgp", "eigrp", "rip")   # schema enum order: keeps output deterministic

# Cisco IOS: a protocol exists only when its `router <proto>` stanza does.
# `no router ...` / `delete protocols ...` cancel an earlier stanza, so the last
# mention of a protocol in the file wins.
CISCO_ROUTER_RE = re.compile(r"^[ \t]*(no[ \t]+)?(?:ipv6[ \t]+)?router[ \t]+(ospf|bgp|eigrp|rip)\b",
                             re.M | re.I)
CISCO_OSPF_AUTH_RE = re.compile(
    r"^[ \t]*(?:ip[ \t]+ospf(?:-v3)?[ \t]+authentication|area[ \t]+\S+[ \t]+authentication)\b",
    re.M | re.I)
CISCO_BGP_AUTH_RE = re.compile(r"^[ \t]*neighbor[ \t]+\S+[ \t]+password\b", re.M | re.I)

# Junos: `set protocols <proto> ...` and the indented `protocols { <proto> {`
# brace form. Unindented protocol keywords are the block headers themselves.
JUNOS_PROTOCOL_RE = re.compile(r"^[ \t]*(?:set[ \t]+)?(delete[ \t]+)?protocols[ \t]+(ospf|bgp|eigrp|rip)\b",
                               re.M | re.I)
JUNOS_BLOCK_RE = re.compile(r"^[ \t]+(delete[ \t]+)?(ospf|bgp|eigrp|rip)[ \t]*\{", re.M | re.I)
JUNOS_OSPF_AUTH_RE = re.compile(r"protocols[ \t]+ospf\b[^\n]*\bauthentication\b", re.M | re.I)
JUNOS_BGP_AUTH_RE = re.compile(r"protocols[ \t]+bgp\b[^\n]*\bauthentication-key\b", re.M | re.I)


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
    # Note: `management.snmp.version` is deliberately left to the LLM. Bare
    # `snmp-server community` lines are v1/v2c and carry no version keyword, so
    # there is nothing in the text to override it with - the model labels it
    # from the command's documented default, which is the best available answer.
    if (re.search(r"^\s*transport input ssh\s*$", config_text, re.M)
            and not re.search(r"transport input .*\b(telnet|all)\b", config_text)):
        found.append((("management", "telnet_enabled"), False))

    kinds = [PW_TYPES[k] for k in re.findall(r"\b(?:secret|password)\s+(type7|\d)\b", config_text)
             if k in PW_TYPES]
    if kinds:
        found.append((("authentication", "password_encryption"), min(kinds, key=PW_RANK.index)))
    return found


def _detected_protocols(pattern, config_text):
    """Protocol names whose stanza is literally present, in schema enum order.

    The last mention of a protocol wins, so a trailing `no router ospf` /
    `delete protocols ospf` correctly cancels an earlier stanza.
    """
    active = {}
    for match in pattern.finditer(config_text):
        groups = match.groups()
        negated, proto = groups[-2], groups[-1]
        active[proto.lower()] = not negated
    return [p for p in PROTOCOL_ORDER if active.get(p)]


def _auth_state(protocols, protocol, auth_found):
    """True/False only for a protocol that actually runs.

    An unconfigured protocol gets None, not False: claiming "authentication
    disabled" for a protocol that was never enabled is the same class of
    fabricated fact this whole module exists to remove. None makes the rule
    engine report Unknown instead of a false Pass/Fail.
    """
    if protocol not in protocols:
        return None
    return bool(auth_found)


def routing_overrides(config_text, vendor):
    """routing.protocols / routing.authentication from the config text alone."""
    if (vendor or "").lower() in ("cisco", "ios"):
        protocols = _detected_protocols(CISCO_ROUTER_RE, config_text)
        ospf_auth = bool(CISCO_OSPF_AUTH_RE.search(config_text))
        bgp_auth = bool(CISCO_BGP_AUTH_RE.search(config_text))
    elif (vendor or "").lower() in ("juniper", "junos"):
        protocols = _detected_protocols(JUNOS_PROTOCOL_RE, config_text)
        protocols += [p for p in _detected_protocols(JUNOS_BLOCK_RE, config_text)
                      if p not in protocols]
        protocols.sort(key=PROTOCOL_ORDER.index)
        ospf_auth = bool(JUNOS_OSPF_AUTH_RE.search(config_text))
        bgp_auth = bool(JUNOS_BGP_AUTH_RE.search(config_text))
    else:
        return []

    # protocol list is always written, so a config with no routing stanza
    # reports [] instead of the schema's full enum echoed back by the model.
    return [
        (("routing", "protocols"), protocols),
        (("routing", "authentication", "ospf"), _auth_state(protocols, "ospf", ospf_auth)),
        (("routing", "authentication", "bgp"), _auth_state(protocols, "bgp", bgp_auth)),
    ]


def deterministic_paths(config_text, vendor):
    """Paths this module will overwrite for a given config, as dotted tuples.

    Used to decide whether a field the LLM disagreed about still needs a human:
    anything proved from the text here is settled regardless of what the model
    claimed, so escalating it would only generate noise.
    """
    paths = set()
    if (vendor or "").lower() in ("cisco", "ios"):
        paths.update(tuple(path) for path, _ in cisco_fact_overrides(config_text))
    paths.update(tuple(path) for path, _ in routing_overrides(config_text, vendor))
    return paths


def apply_overrides(normalized_data, config_text, vendor):
    vendor_key = (vendor or "").lower()
    if vendor_key in ("cisco", "ios"):
        for path, value in cisco_fact_overrides(config_text):
            _set_path(normalized_data, path, value)
    for path, value in routing_overrides(config_text, vendor_key):
        _set_path(normalized_data, path, value)
    normalized_data["vendor"] = vendor_key   # known from the form, never ask the LLM
    return normalized_data