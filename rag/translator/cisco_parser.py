"""
translator/cisco_parser.py
Deterministic Cisco IOS configuration parser.

Lexes raw config text into tokens (handling `!` block separators, comments,
`no` negation) then infers a flat AST of interfaces, vlans, routers, ACLs and
global lines. Kept dependency-free so it is usable standalone.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional

SEP_TOKEN = "__SEP__"
COMMENT_PREFIXES = ("!", "*", ";")


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

@dataclass
class LineNode:
    """A single configuration line. `negated` True for `no <cmd>`."""
    text: str = ""
    negated: bool = False
    args: List[str] = field(default_factory=list)


@dataclass
class InterfaceNode:
    name: str = ""
    lines: List[LineNode] = field(default_factory=list)


@dataclass
class VlanNode:
    vlan_id: int = 0
    lines: List[LineNode] = field(default_factory=list)


@dataclass
class RouterNode:
    protocol: str = ""       # ospf | bgp | eigrp | rip
    instance: str = ""       # process/AS number
    lines: List[LineNode] = field(default_factory=list)


@dataclass
class AclNode:
    name: str = ""
    acl_type: str = ""       # standard | extended | ipv6
    entries: List[LineNode] = field(default_factory=list)


@dataclass
class ConfigNode:
    hostname: Optional[str] = None
    global_lines: List[LineNode] = field(default_factory=list)
    interfaces: List[InterfaceNode] = field(default_factory=list)
    vlans: List[VlanNode] = field(default_factory=list)
    routers: List[RouterNode] = field(default_factory=list)
    acls: List[AclNode] = field(default_factory=list)
    blocks: List[LineNode] = field(default_factory=list)
    raw_unparsed: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

def tokenize(config_text: str) -> list:
    """Return a list of (kind, text, negated) tuples.
    kind is one of "line", "sep" (blank/! separators are preserved as sep)."""
    tokens = []
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!") or stripped.startswith("*"):
            tokens.append(("sep", SEP_TOKEN, False))
            continue
        negated = False
        text = stripped
        if not stripped.startswith("#"):
            if re.match(r"^no\s+", stripped, re.IGNORECASE):
                negated = True
                text = re.sub(r"^no\s+", "", stripped, flags=re.IGNORECASE)
        tokens.append(("line", text, negated))
    return tokens


# ---------------------------------------------------------------------------
# Block-starter detection
# ---------------------------------------------------------------------------

INTERFACE_RE = re.compile(r"^interface\s+(?P<name>(\S+))$", re.IGNORECASE)
VLAN_RE = re.compile(r"^vlan\s+(?P<id>\d+)$", re.IGNORECASE)
ROUTER_RE = re.compile(r"^router\s+(?P<proto>\S+)\s*(?P<id>\S+)?$", re.IGNORECASE)
ACL_RE = re.compile(r"^(?:ip\s+)?access-list\s+(?P<name>\S+)", re.IGNORECASE)
IP_ACL_RE = re.compile(r"^ip\s+access-list\s+(?P<name>\S+)", re.IGNORECASE)


def _first(tokens: list, i: int, default: str = ""):
    return tokens[i].args[0] if i < len(tokens) and tokens[i].args else default


def parse(config_text: str) -> ConfigNode:
    """
    Parse a Cisco config into a ConfigNode. `!` separators close any open
    block so global lines after an interface/router are treated as global.
    """
    root = ConfigNode()
    tokens = []
    for kind, text, negated in tokenize(config_text):
        args = text.split()
        tokens.append(LineNode(text=text, negated=negated, args=args))

    current_interface = None
    current_vlan = None
    current_router = None
    current_acl = None

    for ln in tokens:
        if ln.text == SEP_TOKEN:
            current_interface = None
            current_vlan = None
            current_router = None
            current_acl = None
            continue

        # ---- block openers ------------------------------------------------
        m = INTERFACE_RE.match(ln.text)
        if m:
            current_interface = InterfaceNode(name=m.group("name"))
            root.interfaces.append(current_interface)
            current_vlan = current_router = current_acl = None
            continue
        m = VLAN_RE.match(ln.text)
        if m:
            current_vlan = VlanNode(vlan_id=int(m.group("id")))
            root.vlans.append(current_vlan)
            current_interface = current_router = current_acl = None
            continue
        m = ROUTER_RE.match(ln.text)
        if m:
            current_router = RouterNode(protocol=m.group("proto").lower(),
                                        instance=m.group("id") or "0")
            root.routers.append(current_router)
            current_interface = current_vlan = current_acl = None
            continue
        m = IP_ACL_RE.match(ln.text)
        if m:
            current_acl = AclNode(name=m.group("name"),
                                  acl_type=("ipv6" if ln.text.lower().startswith("ipv6") else "extended"))
            root.acls.append(current_acl)
            current_interface = current_vlan = current_router = None
            continue
        m = ACL_RE.match(ln.text)
        if m and not IP_ACL_RE.match(ln.text):
            current_acl = AclNode(name=m.group("name"), acl_type="standard")
            root.acls.append(current_acl)
            current_interface = current_vlan = current_router = None
            continue

        # ---- hostname (global) --------------------------------------------
        low = ln.text.lower()
        if low.startswith("hostname "):
            root.hostname = ln.text.split(None, 1)[1].strip()
            root.global_lines.append(ln)
            continue

        # ---- attach to current block/global --------------------------------
        if current_interface is not None:
            current_interface.lines.append(ln)
        elif current_vlan is not None:
            current_vlan.lines.append(ln)
        elif current_router is not None:
            current_router.lines.append(ln)
        elif current_acl is not None:
            current_acl.entries.append(ln)
        else:
            root.global_lines.append(ln)

    return root