"""
translator/juniper_parser.py
Deterministic Juniper Junos configuration parser.

Junos uses a flat, fully-qualified `set`/`delete` hierarchy rather than Cisco's
indented block structure:

    set system host-name edge-01
    set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24
    set protocols ospf area 0 interface ge-0/0/0

So the lexer here is much simpler than the Cisco one: every statement is one
self-contained line whose leading keyword and path tokens are unambiguous.

The resulting ConfigNode reuses the SAME node types as cisco_parser.ConfigNode,
which is what lets the rest of the pipeline (normalize -> plan -> generate)
stay vendor-agnostic: a Juniper config is normalized into the same DeviceIR
that a Cisco config produces, and the generator then emits target syntax.

Kept dependency-free so it stays usable standalone.
"""

import re
from typing import Optional

from .cisco_parser import AclNode, ConfigNode, InterfaceNode, LineNode, RouterNode, VlanNode


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

def tokenize(config_text: str) -> list:
    """Return [(action, text, negated, args)] for each meaningful Junos line.

    action is "set" or "delete". Comments (#, /* */) and blank lines are
    dropped. Junos `delete` is the semantic inverse of Cisco `no ...`.
    """
    tokens = []
    # Strip /* ... */ block comments first; they can span several lines.
    text = re.sub(r"/\*.*?\*/", " ", config_text, flags=re.DOTALL)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # Line comments: '#' or a trailing ';' separator.
        if line.startswith("#") or line.startswith("/*"):
            continue
        if line.startswith("set "):
            tokens.append(("set", line[4:].strip(), False, line[4:].strip().split()))
        elif line.startswith("delete ") or line.startswith("deactivate "):
            # `delete a b;` and `set a b delete` are both negations.
            body = line.split(None, 1)[1].strip() if " " in line else ""
            if body.endswith(";"):
                body = body[:-1].strip()
            tokens.append(("delete", body, True, body.split()))
        # Hierarchical `edit`/`top` navigation and bare prompts are not config.
    return tokens


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

def _interface_index(args: list) -> Optional[tuple]:
    """`interfaces ge-0/0/0 unit 0 ...` -> (name, remainder)."""
    if len(args) < 2:
        return None
    return args[1], args[2:]


def _is_interface_path(path: list) -> bool:
    return len(path) >= 2 and path[0] == "interfaces"


def _is_vlan_path(path: list) -> bool:
    return path[:1] == ["vlans"] and len(path) >= 2


def _is_router_path(path: list) -> bool:
    return path[:1] == ["protocols"] and len(path) >= 2


def _is_acl_path(path: list) -> bool:
    return (path[:2] == ["firewall", "family"] and "inet" in path) or \
           (path[:1] == ["access"] and len(path) >= 2)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(config_text: str) -> ConfigNode:
    """
    Parse a Junos configuration into a ConfigNode.

    `!` has no structural meaning in Junos, so unlike the Cisco parser there is
    no separator-driven block state: each line is routed purely by its own path.
    """
    root = ConfigNode()

    interfaces: dict = {}
    vlans: dict = {}
    routers: dict = {}
    acls: dict = {}

    for action, text, negated, args in tokenize(config_text):
        if not args:
            continue

        if args[0] == "system" and len(args) >= 3 and args[1] == "host-name":
            root.hostname = text.split()[2]
            root.global_lines.append(LineNode(text=text, negated=negated, args=args))
            continue

        if _is_interface_path(args):
            name, remainder = _interface_index(args)
            node = interfaces.get(name)
            if node is None:
                node = InterfaceNode(name=name)
                interfaces[name] = node
                root.interfaces.append(node)
            # A `delete interfaces X unit 0 family inet address A.B.C.D/nn`
            # still belongs to that interface block.
            if remainder:
                node.lines.append(
                    LineNode(text=" ".join(remainder), negated=negated, args=remainder))
            continue

        if _is_vlan_path(args):
            vlan_key = args[1]
            node = vlans.get(vlan_key)
            if node is None:
                # Junos vlans are named; a bare numeric name means vlan-id == name.
                node = VlanNode(vlan_id=int(vlan_key) if vlan_key.isdigit() else 0)
                vlans[vlan_key] = node
                root.vlans.append(node)
            if len(args) >= 4 and args[2] == "vlan-id":
                node.vlan_id = _to_int(args[3], node.vlan_id)
            # `set vlans NAME name DISPLAY` is recorded as a "name DISPLAY"
            # line so the Juniper IR normalizer reads it exactly like the
            # Cisco one does for a `vlan N` / `name DISPLAY` block.
            if len(args) >= 4 and args[2] == "name":
                node.lines.append(LineNode(text=f"name {args[3]}", negated=negated,
                                           args=["name", args[3]]))
            continue

        if _is_router_path(args):
            proto = args[1]
            node = routers.get(proto)
            if node is None:
                node = RouterNode(protocol=proto, instance=proto)
                routers[proto] = node
                root.routers.append(node)
            node.lines.append(LineNode(text=text, negated=negated, args=args))
            continue

        if _is_acl_path(args):
            name = args[-1]
            node = acls.get(name)
            if node is None:
                node = AclNode(name=name, acl_type="extended")
                acls[name] = node
                root.acls.append(node)
            node.entries.append(LineNode(text=text, negated=negated, args=args))
            continue

        # Everything else is a global statement the IR normalizer understands.
        root.global_lines.append(LineNode(text=text, negated=negated, args=args))

    return root


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def looks_like_junos(config_text: str) -> bool:
    """Cheap heuristic used by the API to detect (or validate) the source vendor."""
    sample = config_text[:4000]
    junos_markers = [
        r"(?m)^\s*set\s+system\b",
        r"(?m)^\s*set\s+interfaces\s+\S+",
        r"(?m)^\s*set\s+protocols\b",
        r"(?m)^\s*set\s+vlans\b",
        r"(?m)^\s*set\s+security\b",
    ]
    hits = sum(1 for pattern in junos_markers if re.search(pattern, sample))
    if hits >= 1:
        return True
    # `set system host-name` is decisive even on a very short config.
    return bool(re.search(r"(?m)^\s*set\s+system\s+host-name\b", sample))
