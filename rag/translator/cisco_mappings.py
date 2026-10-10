"""
translator/cisco_mappings.py
Junos DeviceIR -> Cisco IOS configuration steps.

Mirror image of `mappings.py` (Cisco IR -> Junos `set` steps). Both modules
consume the same vendor-neutral DeviceIR and emit plan steps with the identical
shape, so the planner, generator, validator and confidence scorer stay shared.

Cisco IOS uses indented blocks rather than a flat hierarchy, so these steps
carry `block` (the header line) plus `command` (the indented child line)
instead of a single `path` list.
"""

from .ir import DeviceIR
from .juniper_ir import prefix_len_to_mask


CISCO_MAPPING_META = {
    "hostname": {"label": "Hostname", "junos": "set system host-name <name>",
                 "cisco": "hostname <name>"},
    "ntp": {"label": "NTP server", "junos": "set system ntp server <addr>",
            "cisco": "ntp server <addr>"},
    "snmp_community": {"label": "SNMP community",
                       "junos": "set snmp community <comm> authorization read-only",
                       "cisco": "snmp-server community <comm> RO"},
    "snmp_location": {"label": "SNMP location", "junos": "set snmp location <str>",
                      "cisco": "snmp-server location <str>"},
    "snmp_contact": {"label": "SNMP contact", "junos": "set snmp contact <str>",
                     "cisco": "snmp-server contact <str>"},
    "logging_host": {"label": "Syslog host", "junos": "set system syslog host <addr>",
                     "cisco": "logging host <addr>"},
    "logging_buffered": {"label": "Local logging", "junos": "set system syslog file messages any any",
                         "cisco": "logging buffered 4096"},
    "ssh": {"label": "SSH version", "junos": "set system services ssh protocol-version v2",
            "cisco": "ip ssh version 2"},
    "telnet_disabled": {"label": "Telnet disabled",
                        "junos": "delete system services telnet",
                        "cisco": "line vty 0 4\n transport input ssh"},
    "http_disabled": {"label": "HTTP disabled", "junos": "delete system services web-management http",
                      "cisco": "no ip http server"},
    "banner": {"label": "Login banner", "junos": 'set system login message "<text>"',
               "cisco": "banner motd <text>"},
    "dns": {"label": "DNS servers", "junos": "set system name-server <addr>",
            "cisco": "ip name-server <addr>"},
    "aaa": {"label": "AAA method", "junos": "set system authentication authentication-method <method>",
            "cisco": "aaa authentication login default group <method>"},
    "iface_desc": {"label": "Interface description",
                   "junos": "set interfaces <if> description <text>",
                   "cisco": "interface <if>\n description <text>"},
    "iface_addr": {"label": "Interface address",
                   "junos": "set interfaces <if> unit 0 family inet address <ip/prefix>",
                   "cisco": "interface <if>\n ip address <ip> <mask>"},
    "iface_disabled": {"label": "Interface admin down", "junos": "set interfaces <if> disable",
                       "cisco": "interface <if>\n shutdown"},
    "iface_mtu": {"label": "Interface MTU", "junos": "set interfaces <if> mtu <n>",
                  "cisco": "interface <if>\n mtu <n>"},
    "iface_vlan": {"label": "Access VLAN", "junos": "set interfaces <if> ... vlan members <id>",
                   "cisco": "interface <if>\n switchport mode access\n switchport access vlan <id>"},
    "iface_trunk": {"label": "Trunk VLANs", "junos": "set interfaces <if> ... vlan members [...]",
                    "cisco": "interface <if>\n switchport trunk encapsulation dot1q\n switchport mode trunk"},
    "vlan": {"label": "VLAN", "junos": "set vlans <name> vlan-id <id>",
             "cisco": "vlan <id>\n name <name>"},
    "ospf": {"label": "OSPF process", "junos": "set protocols ospf",
             "cisco": "router ospf <pid>"},
    "ospf_rid": {"label": "OSPF router-id", "junos": "set protocols ospf router-id <ip>",
                 "cisco": "router ospf <pid>\n router-id <ip>"},
    "ospf_area": {"label": "OSPF area binding",
                  "junos": "set protocols ospf area <a> interface <if>",
                  "cisco": "interface <if>\n ip ospf <pid> area <a>"},
    "static_route": {"label": "Static route", "junos": "set routing-options static route <net> next-hop <nh>",
                     "cisco": "ip route <net> <mask> <nh>"},
    "bgp": {"label": "BGP", "junos": "set protocols bgp", "cisco": "router bgp <asn>"},
}


def _step(mapping, block, command, source, value=None, confidence=0.97):
    return {"kind": "cisco_line", "mapping": mapping, "block": block,
            "command": command, "value": value, "source": source,
            "base_confidence": confidence}


def build_cisco_plan(ir: DeviceIR) -> list:
    """Translate a Junos DeviceIR into a list of Cisco IOS plan steps."""
    plan: list = []
    g = ir.global_config

    # ---- global system ----------------------------------------------------
    if g.hostname:
        plan.append(_step("hostname", None, f"hostname {g.hostname}",
                          f"set system host-name {g.hostname}", g.hostname, 0.985))

    if g.ssh_version:
        version = g.ssh_version
        plan.append(_step("ssh", None, f"ip ssh version {version}",
                          f"set system services ssh protocol-version v{version}",
                          version, 0.97))

    # Junos cannot enable telnet-by-default: it is opt-in. Emitting the
    # transport restriction is what actually secures the equivalent device.
    if not g.telnet_enabled:
        plan.append({"kind": "cisco_block", "mapping": "telnet_disabled",
                     "block": "line vty 0 4", "lines": ["transport input ssh"],
                     "source": "delete system services telnet",
                     "base_confidence": 0.9})

    if not g.ip_http_server:
        plan.append(_step("http_disabled", None, "no ip http server",
                          "delete system services web-management http", None, 0.93))

    for server in g.ntp.servers:
        plan.append(_step("ntp", None, f"ntp server {server}",
                          f"set system ntp server {server}", server, 0.985))

    for host in g.logging.hosts:
        plan.append(_step("logging_host", None, f"logging host {host}",
                          f"set system syslog host {host}", host, 0.96))

    if g.logging.buffered:
        plan.append(_step("logging_buffered", None, "logging buffered 4096",
                          "set system syslog file messages any any", None, 0.88))

    for community in g.snmp.community_strings:
        plan.append(_step("snmp_community", None,
                          f"snmp-server community {community} RO",
                          f"set snmp community {community} authorization read-only",
                          community, 0.95))

    if g.snmp.location:
        plan.append(_step("snmp_location", None, f"snmp-server location {g.snmp.location}",
                          f"set snmp location {g.snmp.location}", g.snmp.location, 0.96))

    if g.snmp.contact:
        plan.append(_step("snmp_contact", None, f"snmp-server contact {g.snmp.contact}",
                          f"set snmp contact {g.snmp.contact}", g.snmp.contact, 0.96))

    if g.motd:
        plan.append(_step("banner", None, f"banner motd {g.motd}",
                          f'set system login message "{g.motd}"', g.motd, 0.92))

    for ns in g.ip_dns_servers:
        plan.append(_step("dns", None, f"ip name-server {ns}",
                          f"set system name-server {ns}", ns, 0.95))

    for method in g.aaa.methods:
        cisco_method = {"radius": "radius", "tacacs+": "tacacs+", "tacplus": "tacacs+",
                        "local": "local"}.get(str(method).lower(), str(method).lower())
        plan.append(_step("aaa", None,
                          f"aaa authentication login default group {cisco_method}",
                          f"set system authentication authentication-method {method}",
                          cisco_method, 0.9))

    # ---- vlans -------------------------------------------------------------
    for vlan in ir.vlans:
        name = vlan.name or str(vlan.vlan_id)
        plan.append({"kind": "cisco_block", "mapping": "vlan",
                     "block": f"vlan {vlan.vlan_id}", "lines": [f"name {name}"],
                     "source": f"set vlans {name} vlan-id {vlan.vlan_id}",
                     "base_confidence": 0.96})

    # ---- interfaces --------------------------------------------------------
    for itf in ir.interfaces:
        cisco = itf.cisco_name or itf.name

        if itf.vlan_mode == "trunk":
            plan.append({"kind": "cisco_block", "mapping": "iface_trunk", "block": f"interface {cisco}",
                         "lines": ["switchport trunk encapsulation dot1q",
                                   "switchport mode trunk"],
                         "source": f"{itf.juniper_name} vlan members {itf.vlan_members}",
                         "base_confidence": 0.93})
            if itf.vlan_members:
                members = str(itf.vlan_members).strip()
                plan.append(_step("iface_trunk", f"interface {cisco}",
                                  f"switchport trunk allowed vlan {members}",
                                  f"set interfaces {itf.juniper_name} ... vlan members {members}",
                                  members, 0.88))
        elif itf.vlan_members:
            members = str(itf.vlan_members).strip()
            plan.append({"kind": "cisco_block", "mapping": "iface_vlan", "block": f"interface {cisco}",
                         "lines": ["switchport mode access",
                                   f"switchport access vlan {members}"],
                         "source": f"{itf.juniper_name} vlan members {members}",
                         "base_confidence": 0.95})

        if itf.description:
            plan.append(_step("iface_desc", f"interface {cisco}",
                              f"description {itf.description}",
                              f"set interfaces {itf.juniper_name} description {itf.description}",
                              itf.description, 0.97))

        for addr in itf.ipv4:
            mask = prefix_len_to_mask(addr.network.prefixlen)
            plan.append(_step("iface_addr", f"interface {cisco}",
                              f"ip address {addr.ip} {mask}",
                              f"set interfaces {itf.juniper_name} unit 0 family inet address {addr}",
                              str(addr), 0.97))

        if itf.mtu:
            plan.append(_step("iface_mtu", f"interface {cisco}", f"mtu {itf.mtu}",
                              f"set interfaces {itf.juniper_name} mtu {itf.mtu}",
                              itf.mtu, 0.96))

        if not itf.enabled:
            plan.append(_step("iface_disabled", f"interface {cisco}", "shutdown",
                              f"delete interfaces {itf.juniper_name} disable", None, 0.95))

    # ---- routing -----------------------------------------------------------
    # OSPF area bindings name Junos interfaces; remap them to IOS names so the
    # generated `ip ospf` command targets an interface that actually exists.
    iface_by_junos = {i.juniper_name: (i.cisco_name or i.name) for i in ir.interfaces}

    for ospf in ir.ospf:
        pid = ospf.process_id or "1"
        plan.append(_step("ospf", f"router ospf {pid}", None,
                          f"set protocols ospf", pid, 0.95))
        if ospf.router_id:
            plan.append(_step("ospf_rid", f"router ospf {pid}",
                              f"router-id {ospf.router_id}",
                              f"set protocols ospf router-id {ospf.router_id}",
                              ospf.router_id, 0.96))
        for binding in ospf.area_interfaces:
            cisco_if = iface_by_junos.get(binding["interface"], binding["interface"])
            plan.append(_step("ospf_area", f"interface {cisco_if}",
                              f"ip ospf {pid} area {binding['area']}",
                              f"set protocols ospf area {binding['area']} interface {binding['interface']}",
                              binding["area"], 0.92))
        for net in ospf.networks:
            destination, _, prefix = net["network"].partition("/")
            plan.append(_step("ospf", f"router ospf {pid}",
                              f"network {destination} {net['wildcard']} area {net['area']}",
                              f"set protocols ospf {net['network']} interface ...",
                              net["area"], 0.9))

    for bgp in ir.bgp:
        asn = bgp.asn or "65000"
        plan.append(_step("bgp", f"router bgp {asn}", None, "set protocols bgp", asn, 0.93))
        for neighbor in bgp.neighbors:
            plan.append(_step("bgp", f"router bgp {asn}",
                              f"neighbor {neighbor['ip']} remote-as {neighbor['remote_as']}",
                              f"set protocols bgp group EXT neighbor {neighbor['ip']}",
                              neighbor["remote_as"], 0.9))

    for route in ir.static_routes:
        destination = str(route.destination)
        address, _, prefix = destination.partition("/")
        plan.append(_step("static_route", None,
                          f"ip route {address} {prefix_len_to_mask(int(prefix or 0))} {route.next_hop}",
                          f"set routing-options static route {destination} next-hop {route.next_hop}",
                          route.next_hop, 0.95))

    # ---- acls --------------------------------------------------------------
    for acl in ir.acls:
        plan.append({"kind": "unmapped", "mapping": "unmapped", "path": [],
                     "value": None, "block": None, "command": None,
                     "source": f"set firewall family inet filter {acl.name}",
                     "base_confidence": 0.3,
                     "reason": ("Junos firewall filters have no safe mechanical "
                                "translation to a Cisco IOS access-list; rewrite by hand.")})

    return plan
