"""
translator/mappings.py
Deterministic Cisco -> Junos mapping catalog.

Each mapping describes how a normalized IR value maps to a Junos `set` path
+ value. `keys` are matched against lowcased source lines; `kind` indicates
line-level vs construct-level mapping. Extend freely -- the LLM is only used
for constructs NOT present here.
"""

# mapping_id -> metadata used for confidence + explanations
MAPPING_META = {
    "hostname":      {"label": "Hostname",    "cisco": "hostname <name>",
                      "junos": "set system host-name <name>"},
    "ntp":           {"label": "NTP server",  "cisco": "ntp server <addr>",
                      "junos": "set system ntp server <addr>"},
    "snmp_community":{"label": "SNMP community", "cisco": "snmp-server community <comm> ro",
                      "junos": "set snmp community <comm> authorization read-only"},
    "snmp_location": {"label": "SNMP location", "cisco": "snmp-server location <str>",
                      "junos": "set snmp location <str>"},
    "logging_host":  {"label": "Syslog host", "cisco": "logging host <addr>",
                      "junos": "set system syslog host <addr>"},
    "ssh":           {"label": "SSH version", "cisco": "ip ssh version 2",
                      "junos": "set system services ssh protocol-version v2"},
    "iface_desc":    {"label": "Interface description", "cisco": "description <text>",
                      "junos": "set interfaces <if> description <text>"},
    "iface_addr":    {"label": "Interface address", "cisco": "ip address <ip> <mask>",
                      "junos": "set interfaces <if> unit 0 family inet address <ip/prefix>"},
    "iface_disabled":{"label": "Interface admin down", "cisco": "shutdown",
                      "junos": "set interfaces <if> disable"},
    "iface_vlan":    {"label": "Access VLAN", "cisco": "switchport access vlan <id>",
                      "junos": "set interfaces <if> unit 0 family ethernet-switching vlan members <id>"},
    "iface_trunk":   {"label": "Trunk VLANS", "cisco": "switchport trunk allowed vlan ...",
                      "junos": "set interfaces <if> unit 0 family ethernet-switching vlan members [ ... ]"},
    "iface_mtu":     {"label": "Interface MTU", "cisco": "mtu <n>",
                      "junos": "set interfaces <if> mtu <n>"},
    "vlan":          {"label": "VLAN", "cisco": "vlan <id> / name <name>",
                      "junos": "set vlans <name> vlan-id <id>"},
    "ospf":          {"label": "OSPF process", "cisco": "router ospf <pid>",
                      "junos": "set protocols ospf"},
    "ospf_rid":      {"label": "OSPF router-id", "cisco": "router-id <ip>",
                      "junos": "set protocols ospf router-id <ip>"},
    "ospf_area":     {"label": "OSPF area/interface", "cisco": "network <net> <wc> area <a>",
                      "junos": "set protocols ospf area <a> interface <if>"},
    "bgp":           {"label": "BGP", "cisco": "router bgp <asn>",
                      "junos": "set protocols bgp"},
    "static_route":  {"label": "Static route", "cisco": "ip route <net> <mask> <next-hop>",
                      "junos": "set routing-options static route <net> next-hop <nh>"},
}


def map_hostname(hostname: str) -> dict:
    return {"kind": "set_line", "mapping": "hostname", "path": ["system", "host-name"],
            "value": hostname, "source": f"hostname {hostname}", "base_confidence": 0.985}


def map_ntp(servers: list) -> list:
    out = []
    for s in servers:
        out.append({"kind": "set_line", "mapping": "ntp", "path": ["system", "ntp", "server", s],
                    "value": None, "source": f"ntp server {s}", "base_confidence": 0.985})
    return out


def map_snmp(community: str) -> dict:
    src = f"snmp-server community {community} ro"
    return {"kind": "set_line", "mapping": "snmp_community",
            "path": ["snmp", "community", community, "authorization"],
            "value": "read-only", "source": src, "base_confidence": 0.97}


def map_logging_host(host: str) -> dict:
    return {"kind": "set_line", "mapping": "logging_host",
            "path": ["system", "syslog", "host", host],
            "value": None, "source": f"logging host {host}", "base_confidence": 0.96}


def _iface_step(mapping: str, path_prefix: list, value, source: str, kind: str = "set_line",
                base_confidence: float = 0.98) -> dict:
    return {"kind": kind, "mapping": mapping, "path": path_prefix + [],
            "value": value, "source": source, "base_confidence": base_confidence}


def map_interface(iface) -> list:
    j = iface.juniper_name or iface.name
    steps = []
    if iface.vlan_mode == "trunk":
        steps.append(_iface_step(
            "iface_trunk",
            ["interfaces", j, "unit", "0", "family", "ethernet-switching", "vlan", "members"],
            iface.vlan_members, f"switchport trunk allowed vlan {iface.vlan_members}"))
    elif iface.vlan_members:
        steps.append(_iface_step(
            "iface_vlan",
            ["interfaces", j, "unit", "0", "family", "ethernet-switching", "vlan", "members"],
            str(iface.vlan_members), f"switchport access vlan {iface.vlan_members}"))

    if iface.description:
        steps.append(_iface_step(
            "iface_desc", ["interfaces", j, "description"],
            iface.description, f"description {iface.description}"))

    for addr in iface.ipv4:
        steps.append(_iface_step(
            "iface_addr", ["interfaces", j, "unit", "0", "family", "inet", "address"],
            str(addr), f"ip address {addr.ip} {addr.network.netmask}"))

    if iface.mtu:
        steps.append(_iface_step(
            "iface_mtu", ["interfaces", j, "mtu"], iface.mtu, f"mtu {iface.mtu}", base_confidence=0.96))

    if not iface.enabled:
        steps.append(_iface_step(
            "iface_disabled", ["interfaces", j, "disable"], None, "shutdown", base_confidence=0.98))
    else:
        steps.append(_iface_step(
            "noop", ["interfaces", j], None, "no shutdown", kind="noop", base_confidence=1.0))
    return steps


def map_vlan(vlan) -> dict:
    name = vlan.name or str(vlan.vlan_id)
    return {"kind": "set_line", "mapping": "vlan", "path": ["vlans", name, "vlan-id"],
            "value": vlan.vlan_id, "source": f"vlan {vlan.vlan_id}",
            "base_confidence": 0.97}


def map_ospf(ospf, ir) -> list:
    steps = [{"kind": "set_line", "mapping": "ospf", "path": ["protocols", "ospf"],
              "value": None, "source": f"router ospf {ospf.process_id}", "base_confidence": 0.98}]
    if ospf.router_id:
        steps.append({"kind": "set_line", "mapping": "ospf_rid",
                      "path": ["protocols", "ospf", "router-id"], "value": ospf.router_id,
                      "source": f"router-id {ospf.router_id}", "base_confidence": 0.97})
    for net in ospf.networks:
        itf = _find_interface_for_network(ir, net["network"])
        if itf:
            j = itf.juniper_name or itf.name
            steps.append({"kind": "set_line", "mapping": "ospf_area",
                          "path": ["protocols", "ospf", "area", net["area"], "interface", j],
                          "value": None,
                          "source": f"network {net['network']} {net['wildcard']} area {net['area']}",
                          "base_confidence": 0.94})
        else:
            steps.append({"kind": "unmapped", "mapping": "unmapped", "path": [],
                          "value": None,
                          "source": f"network {net['network']} {net['wildcard']} area {net['area']}",
                          "base_confidence": 0.3,
                          "reason": "OSPF network statement translated but no matching L3 interface found for area/interface binding."})
    return steps


def _find_interface_for_network(ir, network: str):
    try:
        target = IPv4NetworkUnsafe(network)
    except Exception:
        return None
    for itf in ir.interfaces:
        for addr in itf.ipv4:
            if addr.ip in target:
                return itf
    return None


def map_static_route(route) -> dict:
    return {"kind": "set_line", "mapping": "static_route",
            "path": ["routing-options", "static", "route", str(route.destination), "next-hop"],
            "value": route.next_hop, "source": f"ip route {route.destination.network_address} {route.destination.netmask} {route.next_hop}",
            "base_confidence": 0.95}


def IPv4NetworkUnsafe(network: str):
    from ipaddress import IPv4Network
    return IPv4Network(network, strict=False)