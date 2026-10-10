"""
translator/ir.py
Semantic intermediate representation (IR) plus Cisco -> IR normalization.

The IR is a Pydantic model tree so downstream consumers (planner, validator,
explainer) work against clean typed data instead of raw text lines.
"""

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from ipaddress import IPv4Address, IPv4Interface, IPv4Network

from .cisco_parser import ConfigNode, InterfaceNode, LineNode


# ---------------------------------------------------------------------------
# IR models
# ---------------------------------------------------------------------------

class SnmpIR(BaseModel):
    community_strings: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    contact: Optional[str] = None


class LoggingIR(BaseModel):
    hosts: List[str] = Field(default_factory=list)
    buffered: bool = False


class NtpIR(BaseModel):
    servers: List[str] = Field(default_factory=list)


class AaaIR(BaseModel):
    methods: List[str] = Field(default_factory=list)


class GlobalConfigIR(BaseModel):
    hostname: Optional[str] = None
    snmp: SnmpIR = Field(default_factory=SnmpIR)
    logging: LoggingIR = Field(default_factory=LoggingIR)
    ntp: NtpIR = Field(default_factory=NtpIR)
    aaa: AaaIR = Field(default_factory=AaaIR)
    ssh_version: Optional[int] = None
    telnet_enabled: bool = False
    motd: Optional[str] = None
    cdp_enabled: bool = True
    ip_http_server: bool = False
    ip_dns_servers: List[str] = Field(default_factory=list)
    raw_commands: List[str] = Field(default_factory=list)


class InterfaceIR(BaseModel):
    name: str = ""
    cisco_name: str = ""
    description: Optional[str] = None
    ipv4: List[IPv4Interface] = Field(default_factory=list)
    ipv6: List[str] = Field(default_factory=list)
    vlan_members: Optional[Union[str, List[str]]] = None
    vlan_mode: Optional[str] = None          # access | trunk
    enabled: bool = True
    mtu: Optional[int] = None
    cdp_enabled: bool = True
    ip_ospf: Optional[Dict[str, str]] = None
    juniper_name: Optional[str] = None


class VlanIR(BaseModel):
    vlan_id: int = 0
    name: Optional[str] = None


class OspfIR(BaseModel):
    process_id: str = "0"
    networks: List[Dict[str, str]] = Field(default_factory=list)
    router_id: Optional[str] = None
    passive_interfaces: List[str] = Field(default_factory=list)


class BgpIR(BaseModel):
    asn: str = "0"
    neighbors: List[Dict[str, str]] = Field(default_factory=list)
    networks: List[IPv4Network] = Field(default_factory=list)


class StaticRouteIR(BaseModel):
    destination: IPv4Network
    next_hop: str


class AclIR(BaseModel):
    name: str
    acl_type: str = "standard"
    entries: List[str] = Field(default_factory=list)


class DeviceIR(BaseModel):
    vendor: str = "cisco"
    interfaces: List[InterfaceIR] = Field(default_factory=list)
    vlans: List[VlanIR] = Field(default_factory=list)
    ospf: List[OspfIR] = Field(default_factory=list)
    bgp: List[BgpIR] = Field(default_factory=list)
    static_routes: List[StaticRouteIR] = Field(default_factory=list)
    acls: List[AclIR] = Field(default_factory=list)
    global_config: GlobalConfigIR = Field(default_factory=GlobalConfigIR)

    def model_dump_safe(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Cisco interface name -> Junos
# ---------------------------------------------------------------------------

INTERFACE_TYPE_MAP = [
    (re.compile(r"^GigabitEthernet(\d+)/(\d+)/(\d+)$"), "ge", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^GigabitEthernet(\d+)/(\d+)$"), "ge", lambda m: f"{m[0]}/0/{m[1]}"),
    (re.compile(r"^FastEthernet(\d+)/(\d+)/(\d+)$"), "ge", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^FastEthernet(\d+)/(\d+)$"), "fe", lambda m: f"{m[0]}/0/{m[1]}"),
    (re.compile(r"^TenGigabitEthernet(\d+)/(\d+)/(\d+)$"), "xe", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^TenGigabitEthernet(\d+)/(\d+)$"), "xe", lambda m: f"{m[0]}/0/{m[1]}"),
    (re.compile(r"^Ethernet(\d+)/(\d+)/(\d+)$"), "ge", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^Ethernet(\d+)/(\d+)$"), "ge", lambda m: f"{m[0]}/0/{m[1]}"),
    (re.compile(r"^Port-channel(\d+)$"), "ae", lambda m: f"{m[0]}"),
    (re.compile(r"^Loopback(\d+)$"), "lo", lambda m: f"{m[0]}"),
    (re.compile(r"^Vlan(\d+)$"), "vlan", lambda m: f"{m[0]}"),
    (re.compile(r"^Tunnel(\d+)$"), "tun", lambda m: f"{m[0]}"),
    (re.compile(r"^TenGigE(\d+)/(\d+)/(\d+)$"), "xe", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^TwentyFiveGigE(\d+)/(\d+)/(\d+)$"), "et", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^FortyGigE(\d+)/(\d+)/(\d+)$"), "et", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^HundredGigE(\d+)/(\d+)/(\d+)$"), "et", lambda m: f"{m[0]}/{m[1]}/{m[2]}"),
    (re.compile(r"^Management(\d+)$"), "me", lambda m: f"{m[0]}"),
]


def map_interface_name(cisco_name: str) -> str:
    """Map a Cisco interface name to a Junos-style name."""
    name = cisco_name.strip()
    for regex, jtype, conv in INTERFACE_TYPE_MAP:
        m = regex.match(name)
        if m:
            return f"{jtype}-{conv(m.groups())}"
    digits = re.findall(r"\d+", name)
    fallback = digits[-1] if digits else "0"
    return f"ge-0/0/{fallback}"


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

def mask_to_prefix_len(mask: str) -> int:
    try:
        return IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except Exception:
        octets = mask.split(".")
        bits = sum(bin(int(o)).count("1") for o in octets if o.isdigit())
        return bits


def wildcard_to_prefix_len(wildcard: str) -> int:
    # wildcard 0.0.0.255 inverts to mask 255.255.255.0
    try:
        inverted = ".".join(str(255 - int(o)) for o in wildcard.split("."))
        return mask_to_prefix_len(inverted)
    except Exception:
        return 32


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(ast: ConfigNode) -> DeviceIR:
    ir = DeviceIR()
    ir.global_config.hostname = ast.hostname

    consumed_global = _normalize_global(ir, ast.global_lines)

    for iface_node in ast.interfaces:
        ir.interfaces.append(_normalize_interface(iface_node))

    for vnode in ast.vlans:
        name = None
        for ln in vnode.lines:
            if ln.text.lower().startswith("name "):
                name = ln.text.split(None, 1)[1].strip()
        ir.vlans.append(VlanIR(vlan_id=vnode.vlan_id, name=name))

    for router in ast.routers:
        if router.protocol == "ospf":
            ospf = OspfIR(process_id=router.instance)
            for ln in router.lines:
                low = ln.text.lower()
                if low.startswith("network "):
                    parts = ln.text.split()
                    if len(parts) >= 5:
                        net, wc, area = parts[1], parts[2], parts[4]
                        try:
                            prefix = wildcard_to_prefix_len(wc)
                            ospf.networks.append({
                                "network": str(IPv4Network(f"{net}/{prefix}", strict=False)),
                                "wildcard": wc, "area": area,
                            })
                        except Exception:
                            ospf.networks.append({"network": net, "wildcard": wc, "area": area})
                elif low.startswith("router-id "):
                    ospf.router_id = ln.text.split(None, 1)[1].strip()
                elif low.startswith("passive-interface "):
                    ospf.passive_interfaces.append(ln.text.split(None, 1)[1].strip())
            ir.ospf.append(ospf)

        elif router.protocol == "bgp":
            bgp = BgpIR(asn=router.instance)
            for ln in router.lines:
                low = ln.text.lower()
                if low.startswith("neighbor ") and "remote-as" in low:
                    parts = ln.text.split()
                    if len(parts) >= 4:
                        bgp.neighbors.append({"ip": parts[1], "remote_as": parts[3]})
                elif low.startswith("network "):
                    parts = ln.text.split()
                    if len(parts) >= 2:
                        try:
                            mask = parts[2] if len(parts) > 2 else None
                            prefix = mask_to_prefix_len(mask) if mask else 24
                            bgp.networks.append(IPv4Network(f"{parts[1]}/{prefix}", strict=False))
                        except Exception:
                            pass
            ir.bgp.append(bgp)

    for ln in ast.global_lines:
        low = ln.text.lower()
        if low.startswith("ip route "):
            parts = ln.text.split()
            # tokens: ip route <dest> <mask> <next-hop>
            if len(parts) >= 4:
                try:
                    prefix = mask_to_prefix_len(parts[3])
                    dest = IPv4Network(f"{parts[2]}/{prefix}", strict=False)
                    next_hop = parts[4] if len(parts) > 4 else None
                    if next_hop:
                        ir.static_routes.append(StaticRouteIR(destination=dest, next_hop=next_hop))
                except Exception:
                    pass
            consumed_global.add(id(ln))

    for acl in ast.acls:
        ir.acls.append(AclIR(name=acl.name, acl_type=acl.acl_type,
                             entries=[ln.text for ln in acl.entries]))

    ir.global_config.raw_commands = [
        ln.text for ln in ast.global_lines if id(ln) not in consumed_global]

    return ir


def _normalize_global(ir: DeviceIR, lines: list) -> set:
    """Populate global_config, returning ids of consumed lines for raw capture."""
    consumed = set()
    g = ir.global_config
    for ln in lines:
        low = ln.text.lower()
        if low.startswith("hostname "):
            consumed.add(id(ln))
        elif low.startswith("ip ssh version "):
            try:
                g.ssh_version = int(ln.text.split()[3])
            except Exception:
                pass
            consumed.add(id(ln))
        elif low.startswith("ip name-server "):
            g.ip_dns_servers.append(ln.text.split(None, 2)[2])
            consumed.add(id(ln))
        elif low.startswith("snmp-server community "):
            parts = ln.text.split()
            if len(parts) >= 3:
                g.snmp.community_strings.append(parts[2])
            consumed.add(id(ln))
        elif low.startswith("snmp-server location "):
            g.snmp.location = ln.text.split(None, 2)[2]
            consumed.add(id(ln))
        elif low.startswith("snmp-server contact "):
            g.snmp.contact = ln.text.split(None, 2)[2]
            consumed.add(id(ln))
        elif low.startswith("logging host "):
            g.logging.hosts.append(ln.text.split(None, 2)[2])
            consumed.add(id(ln))
        elif low.startswith("ntp server "):
            g.ntp.servers.append(ln.text.split(None, 2)[2])
            consumed.add(id(ln))
        # NOTE: lines like `logging buffered`, `banner motd`, `no cdp run`,
        # `ip http server`, `aaa ...`, `line vty`, `transport input` are NOT
        # consumed here; they are captured as raw_commands and then handled by
        # the table map (core/mappings.py) or surfaced as unmapped.
    return consumed


def _normalize_interface(iface: InterfaceNode) -> InterfaceIR:
    ir = InterfaceIR(name=map_interface_name(iface.name), cisco_name=iface.name,
                     juniper_name=map_interface_name(iface.name))
    for ln in iface.lines:
        low = ln.text.lower()
        if ln.negated and low == "shutdown":
            continue  # no shutdown -> default enabled
        elif low == "shutdown":
            ir.enabled = False
        elif low.startswith("description "):
            ir.description = ln.text.split(None, 1)[1].strip()
        elif low.startswith("ip address "):
            parts = ln.text.split()
            if len(parts) >= 3:
                ip, mask = parts[2], parts[3]
                prefix = mask_to_prefix_len(mask)
                try:
                    ir.ipv4.append(IPv4Interface(f"{ip}/{prefix}"))
                except Exception:
                    pass
        elif low.startswith("ip ospf ") and "area" in low:
            parts = ln.text.split()
            try:
                area = parts[4] if len(parts) > 4 else "0"
                ir.ip_ospf = {"area": area, "pid": parts[2]}
            except Exception:
                pass
        elif low.startswith("switchport access vlan "):
            ir.vlan_members = ln.text.split(None, 3)[3]
            ir.vlan_mode = "access"
        elif low.startswith("switchport mode trunk"):
            ir.vlan_mode = "trunk"
        elif low.startswith("switchport trunk allowed vlan "):
            ir.vlan_members = ln.text.split(None, 4)[4]
            ir.vlan_mode = "trunk"
        elif low.startswith("mtu "):
            try:
                ir.mtu = int(ln.text.split()[1])
            except Exception:
                pass
        elif low.startswith("no cdp"):
            ir.cdp_enabled = False
    return ir