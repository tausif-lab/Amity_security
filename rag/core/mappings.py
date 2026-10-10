"""Small deterministic Cisco -> Junos command table used for fast, exact
translations before falling back to the LLM. Extend freely."""

# Prefix-matched commands: <key> <rest args...> -> NAME_IN_PLACE + " " + rest
PREFIX_MAPPINGS = {
    "hostname": "set system host-name",
    "ntp server": "set system ntp server",
    "logging host": "set system syslog host",
    "ip name-server": "set system name-server",
    "ip domain-name": "set system domain-name",
    "snmp-server community": "set snmp community",
    "snmp-server location": "set snmp location",
    "snmp-server contact": "set snmp contact",
    "banner motd": "set system login message",
    "banner login": "set system login message",
    "username": "set system login user",
}

# Substring-matched phrases used only when args are already fully defined.
SUBSTRING_MAPPINGS = {
    "no cdp run": "delete protocols lldp disable  # (CDP disabled; Junos uses LLDP)",
    "cdp run": "set protocols lldp interface all",
    "service timestamps log datetime": "set system syslog time-format year",
    "aaa new-model": "set system authentication",
    "enable secret": "# UNMAPPED: Cisco enable secret has no direct Junos analog (use root auth)",
    "transport input ssh": "set system services ssh",
}


def table_translate(text: str) -> tuple:
    """Return (output_lines, any_missing). Table-matched lines become Junos set
    commands; unmatched lines are left as None for the LLM to handle."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            out.append(line)
            continue

        # numeric, self-contained commands -> exact replacement
        exact = None
        if line.lower().startswith("ip ssh version"):
            exact = "set system services ssh protocol-version v2"
        elif line.lower().startswith("ip ssh time-out"):
            exact = "set system services ssh idle-timeout"
        elif line.lower().startswith("logging buffered"):
            exact = "set system syslog file messages any any"
        if exact:
            out.append(exact)
            continue

        key = next((k for k in PREFIX_MAPPINGS if line.lower().startswith(k)), None)
        if key:
            out.append(PREFIX_MAPPINGS[key] + (" " + line[len(key):].strip() if line[len(key):].strip() else ""))
            continue

        sub = next((s for s in SUBSTRING_MAPPINGS if s in line.lower()), None)
        if sub:
            out.append(SUBSTRING_MAPPINGS[sub])
            continue

        out.append(None)
    return out, any(o is None for o in out)