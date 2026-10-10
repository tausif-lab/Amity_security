"""
translator/juniper_ir.py
Junos config text -> the SAME vendor-neutral DeviceIR that Cisco produces.

This is the key to bidirectional translation: both parsers feed one IR, so the
planner, confidence scorer and verifier never need to know which side a config
came from. Only the generator differs, because it must emit target syntax.

Values are only recorded when they are LITERALLY present in the config. A
setting that is absent stays None/empty so the compliance engine reports
"Unknown" rather than inventing a passing or failing fact.
"""

import re
from ipaddress import IPv4Interface, IPv4Network

from .ir import (
    AaaIR,
    AclIR,
    BgpIR,
    DeviceIR,
    GlobalConfigIR,
    InterfaceIR,
    InterfaceIR as _InterfaceIR,  # re-exported for readability in imports
    LoggingIR,
    NtpIR,
    OspfIR,
    SnmpIR,
    StaticRouteIR,
    VlanIR,
)


# ---------------------------------------------------------------------------
# Junos interface name -> Cisco IOS name
# ---------------------------------------------------------------------------

JUNOS_IFACE_RE = re.compile(
    r"^(?P<type>[a-z]{2,4})-(?P<rest>\d+(?:/\d+)*)$", re.IGNORECASE
)

# Logical/aggregate units are written without a dash: `ae0`, `lo0`, `irb`.
JUNOS_LOGICAL_RE = re.compile(r"^(?P<type>[a-z]{2,4})(?P<num>\d+)$", re.IGNORECASE)

JUNOS_TYPE_TO_CISCO = {
    "ge": "GigabitEthernet",
    "fe": "FastEthernet",
    "xe": "TenGigabitEthernet",
    "te": "TenGigabitEthernet",
    "et": "FortyGigE",
    "so": "Serial",
    "ae": "Port-channel",
    "lo": "Loopback",
    "tun": "Tunnel",
    "em": "GigabitEthernet",
    "fxp": "GigabitEthernet",
    "me": "Management",
    "irb": "Vlan",
    "vlan": "Vlan",
}

# Management ports carry a unit, not a slot triple.
JUNOS_MANAGEMENT_RE = re.compile(r"^me-?(?P<num>\d*)$", re.IGNORECASE)


def map_juniper_interface_name(juniper_name: str) -> str:
    """`ge-0/0/1` -> `GigabitEthernet0/0/1`, `ae0` -> `Port-channel0`."""
    name = (juniper_name or "").strip()
    if not name:
        return "GigabitEthernet0/0/0"

    # Junos logical units (unit 0) are not part of the physical name.
    mgmt = JUNOS_MANAGEMENT_RE.match(name)
    if mgmt:
        return f"Management{mgmt.group('num') or ''}"

    m = JUNOS_IFACE_RE.match(name)
    if not m:
        logical = JUNOS_LOGICAL_RE.match(name)
        if logical:
            cisco_type = JUNOS_TYPE_TO_CISCO.get(logical.group("type").lower())
            return f"{cisco_type}{logical.group('num')}" if cisco_type else name
        # An already-Cisco name (GigabitEthernet0/0) passes through unchanged.
        return name

    iftype = m.group("type").lower()
    rest = m.group("rest")
    cisco_type = JUNOS_TYPE_TO_CISCO.get(iftype)
    if not cisco_type:
        return name

    if iftype in {"lo", "ae", "tun"}:
        # These have no slot/slot/slot form: `lo0`, `ae0`, `tun0`.
        return f"{cisco_type}{rest}"

    # Junos always uses slot/slot/unit for physical media interfaces, while IOS
    # accepts the short `slot/port` form. Expand so `fe-1/2` -> `FastEthernet1/0/2`,
    # matching how the rest of the catalog names interfaces.
    parts = rest.split("/")
    if len(parts) == 2 and cisco_type not in ("Management",):
        parts = [parts[0], "0", parts[1]]
    return f"{cisco_type}{'/'.join(parts)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prefix_len_to_mask(prefix_len: int) -> str:
    """24 -> '255.255.255.0' (Cisco wants a dotted mask, not a prefix)."""
    return str(IPv4Network(f"0.0.0.0/{int(prefix_len)}").netmask)


# Juniper `$6$` is SHA-512-crypt, `$5$` is SHA-256-crypt, `$1$` is MD5-crypt.
# The schema enum only accepts sha256/scrypt/md5/etc, so map to the closest
# value the CIS rules understand instead of inventing one.
_HASH_MAP = {"6": "sha512", "5": "sha256", "1": "md5"}


def _detect_password_hash(passwords: list) -> str | None:
    """Strongest hash present wins; None when no hash marker was found."""
    best = None
    rank = {"md5": 1, "sha256": 2, "sha512": 3}
    for pw in passwords:
        if not pw:
            continue
        m = re.match(r"^\$(\d)\$", str(pw).strip().strip('"'))
        if m and m.group(1) in _HASH_MAP:
            candidate = _HASH_MAP[m.group(1)]
            if best is None or rank[candidate] > rank[best]:
                best = candidate
    return best


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(ast) -> DeviceIR:
    """Build a DeviceIR from a ConfigNode produced by juniper_parser.parse()."""
    ir = DeviceIR(vendor="juniper")
    _normalize_global(ir, ast.global_lines)

    for iface_node in ast.interfaces:
        ir.interfaces.append(_normalize_interface(iface_node))

    for vlan_node in ast.vlans:
        name = None
        for ln in vlan_node.lines:
            if ln.text.lower().startswith("name "):
                name = ln.text.split(None, 1)[1].strip()
        ir.vlans.append(VlanIR(vlan_id=vlan_node.vlan_id, name=name or str(vlan_node.vlan_id)))

    for router in ast.routers:
        if router.protocol == "ospf":
            ir.ospf.append(_normalize_ospf(router))
        elif router.protocol == "bgp":
            ir.bgp.append(_normalize_bgp(router))

    _normalize_static_routes(ir, ast.global_lines)

    for acl in ast.acls:
        ir.acls.append(AclIR(name=acl.name, acl_type=acl.acl_type,
                             entries=[ln.text for ln in acl.entries]))

    return ir


def _normalize_global(ir: DeviceIR, lines: list) -> None:
    g = ir.global_config
    passwords: list = []

    for ln in lines:
        low = ln.text.lower()
        args = ln.args or ln.text.split()

        # The parser already stripped the `set` prefix, so `hostname` arrives as
        # `system host-name <name>`.
        if low.startswith("system host-name"):
            g.hostname = args[2] if len(args) >= 3 else None
        elif low.startswith("system services telnet"):
            g.telnet_enabled = not ln.negated
        elif low.startswith("system services ssh"):
            # Only claim a version when it is literally stated.
            m = re.search(r"protocol-version\s+v(\d+)", low)
            if m:
                g.ssh_version = int(m.group(1))
        elif low.startswith("system ntp server"):
            # `set system ntp server 10.0.0.1` -> args == [system, ntp, server, ip]
            server = args[3] if len(args) >= 4 else None
            if server:
                g.ntp.servers.append(server)
        elif low.startswith("system syslog host"):
            # `set system syslog host 10.0.0.5 any any` -> [system, syslog, host, ip, ...]
            host = args[3] if len(args) >= 4 else None
            if host:
                g.logging.hosts.append(host)
        elif low.startswith("system syslog file"):
            g.logging.buffered = True
        elif low.startswith("system login message"):
            g.motd = _unquote(ln.text.split("message", 1)[1].strip()) or g.motd
        elif low.startswith("system name-server"):
            for ns in args[2:]:
                g.ip_dns_servers.append(ns.strip('"'))
        elif low.startswith("system domain-name"):
            continue
        elif low.startswith("system services web-management"):
            # HTTP is on unless a `delete`/`https` statement is the only one.
            if not ln.negated and "https" not in low:
                g.ip_http_server = True
        elif low.startswith("system authentication"):
            method = args[-1] if args else ""
            if method and method not in g.aaa.methods:
                g.aaa.methods.append(method)
        elif low.startswith("snmp community"):
            community = args[2] if len(args) >= 3 else None
            if community:
                g.snmp.community_strings.append(community.strip('"'))
        elif low.startswith("snmp location"):
            g.snmp.location = _unquote(ln.text.split("location", 1)[1].strip())
        elif low.startswith("snmp contact"):
            g.snmp.contact = _unquote(ln.text.split("contact", 1)[1].strip())
        elif low.startswith("system login user"):
            m = re.search(r"encrypted-password\s+(\S+)", ln.text, re.IGNORECASE)
            if m:
                passwords.append(m.group(1))

    g.password_hashes = passwords
    detected = _detect_password_hash(passwords)
    if detected:
        g.password_encryption = detected


def _normalize_interface(iface) -> InterfaceIR:
    cisco_name = map_juniper_interface_name(iface.name)
    ir = InterfaceIR(name=cisco_name, cisco_name=cisco_name, juniper_name=iface.name)

    for ln in iface.lines:
        low = ln.text.lower()
        args = ln.args or ln.text.split()

        if low == "disable":
            # `delete ... disable` re-enables the interface.
            ir.enabled = ln.negated
            continue
        if low.startswith("description"):
            ir.description = _unquote(ln.text.split(None, 1)[1].strip()) if len(args) > 1 else None
            continue
        if low.startswith("mtu"):
            try:
                ir.mtu = int(args[1])
            except (IndexError, ValueError):
                pass
            continue
        if "family inet address" in low:
            address = args[-1] if args else ""
            try:
                ir.ipv4.append(IPv4Interface(address))
            except ValueError:
                pass
            continue
        if "family inet6 address" in low:
            ir.ipv6.append(args[-1] if args else "")
            continue
        if "vlan members" in low:
            idx = low.index("vlan members")
            members = ln.text[idx + len("vlan members"):].strip()
            if members:
                ir.vlan_members = members
                ir.vlan_mode = "trunk" if _looks_trunk(ln.text) else "access"
            continue
        if "interface-mode trunk" in low or "port-mode trunk" in low:
            ir.vlan_mode = "trunk"
            continue
        if "interface-mode access" in low:
            ir.vlan_mode = "access"
            continue

    return ir


def _looks_trunk(text: str) -> bool:
    return "all" in text.lower() or re.search(r"vlan members\s+[\d,\[\]-]*\d+\s*-", text)


def _normalize_ospf(router) -> OspfIR:
    """Junos binds OSPF per-interface (`area A interface I`) rather than with a
    wildcard network statement, so bindings are kept as `area_interfaces` and the
    Cisco generator turns them into `ip ospf <pid> area <a>` interface commands.
    """
    ospf = OspfIR(process_id="1")
    for ln in router.lines:
        low = ln.text.lower()
        if "router-id" in low:
            ospf.router_id = ln.args[-1] if ln.args else None
            continue
        if not ln.negated and re.search(r"interface-mode\s+passive", low):
            continue

        m = re.search(r"area\s+(\S+)\s+interface\s+(\S+)", low)
        if m and not ln.negated:
            ospf.area_interfaces.append({"area": m.group(1), "interface": m.group(2)})
            continue

        # Junos also accepts the network form: `0.0.0.0/0 interface ALL`
        m = re.search(r"(\d+\.\d+\.\d+\.\d+/\d+)\s+interface\s+(\S+)", low)
        if m and not ln.negated:
            ospf.networks.append({"network": m.group(1), "wildcard": "0.0.0.0",
                                  "area": ospf.area_interfaces[0]["area"]
                                  if ospf.area_interfaces else "0"})
    return ospf


def _normalize_bgp(router) -> BgpIR:
    bgp = BgpIR()
    for ln in router.lines:
        low = ln.text.lower()
        if "local-address" in low:
            bgp.asn = ln.args[-1] if ln.args else bgp.asn
            continue
        m = re.search(r"neighbor\s+(\S+)\s+peer-as\s+(\S+)", low)
        if m and not ln.negated:
            bgp.neighbors.append({"ip": m.group(1), "remote_as": m.group(2)})
            continue
        m = re.search(r"neighbor\s+(\S+)", low)
        if m and len(ln.args) >= 4 and ln.args[-1] == "as":
            bgp.neighbors.append({"ip": m.group(1), "remote_as": ln.args[3]})
    return bgp


def _normalize_static_routes(ir: DeviceIR, lines: list) -> None:
    for ln in lines:
        low = ln.text.lower()
        if not low.startswith("routing-options static route"):
            continue
        if ln.negated:
            continue
        m = re.search(r"(\d+\.\d+\.\d+\.\d+/\d+)\s+next-hop\s+(\S+)", ln.text)
        if not m:
            continue
        try:
            ir.static_routes.append(
                StaticRouteIR(destination=IPv4Network(m.group(1), strict=False),
                              next_hop=m.group(2)))
        except ValueError:
            continue


def _unquote(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
