"""
translator/cisco_generator.py
Renders Cisco-targeted plan steps into an indented IOS configuration.

Cisco IOS is block-structured: a header line (`interface GigabitEthernet0/0`)
followed by indented children. Junos is flat (`set a b c`). So this generator
groups steps by `block` and emits children at one indent level, which is what
`show running-config` actually looks like on IOS.

Ordering is deterministic (globals, then vlans, then interfaces, then routing)
so two runs over the same config always produce byte-identical output.
"""

from typing import List

from .generator import redact_secret


# Cisco `show running-config` order: globals, then router processes, then
# interfaces, then VLANs. Routing blocks are emitted before interfaces because
# interface lines such as `ip ospf 1 area 0` reference the process they belong
# to, so a reader (and a config loader) meets the definition first.
BLOCK_RANK = {
    "router ospf": 10,
    "router bgp": 15,
    "interface": 20,
    "vlan": 30,
    "line vty": 40,
}

# Steps with a block render inside that block; `None` means top-level global.
GLOBAL_RANK = 5


def _block_rank(block):
    if not block:
        return GLOBAL_RANK
    for prefix, rank in BLOCK_RANK.items():
        if block.startswith(prefix):
            return rank
    return 60


def step_to_cisco_line(step: dict) -> str:
    """Render ONE step into its flat textual form (used for explanations)."""
    command = (step.get("command") or "").strip()
    block = step.get("block")
    if command:
        return f"{block}\n {command}" if block else command
    if step.get("kind") == "cisco_block":
        lines = " / ".join(step.get("lines") or [])
        return f"{block} / {lines}" if lines else str(block)
    return ""


def generate_cisco_config(steps: List[dict]) -> List[str]:
    """
    Render the whole plan into ordered IOS configuration lines.

    Unmapped steps become `# UNMAPPED: <source>` comment pairs so nothing is
    silently dropped -- the reviewer sees exactly what still needs a human.
    """
    blocks: dict = {}
    order: List[str] = []

    for step in steps:
        kind = step.get("kind")

        if kind == "unmapped":
            source = redact_secret(str(step.get("source", "")))
            reason = step.get("reason", "No verified Cisco equivalent found.")
            key = "__unmapped__"
            if key not in blocks:
                blocks[key] = []
                order.append(key)
            blocks[key].append(f"# UNMAPPED: {source}")
            blocks[key].append(f"#   reason: {reason}")
            continue

        block = step.get("block")
        if kind == "cisco_block":
            lines = [str(x) for x in (step.get("lines") or []) if str(x).strip()]
            if not block or not lines:
                continue
            key = f"__block__{block}"
            if key not in blocks:
                blocks[key] = [block]
                order.append(key)
            # Children of a block are indented, exactly like `show running-config`.
            blocks[key].extend(line if line.startswith(" ") else f" {line}"
                               for line in lines)
            continue

        if kind == "noop":
            continue

        command = (step.get("command") or "").strip()
        if not command:
            # A step may declare a block header with no command of its own
            # (e.g. `set protocols ospf` -> `router ospf 1`). The header still
            # has to be emitted or its children would be orphaned.
            if not block:
                continue
            key = f"__block__{block}"
            if key not in blocks:
                blocks[key] = [block]
                order.append(key)
            continue

        key = f"__block__{block}" if block else "__global__"
        if key not in blocks:
            blocks[key] = [block] if block else []
            order.append(key)
        if block:
            blocks[key].append(f" {command}")
        else:
            blocks[key].append(command)

    def key_block(key):
        return key[len("__block__"):] if key.startswith("__block__") else None

    def sort_key(key):
        if key == "__unmapped__":
            return (999, 0)
        return (_block_rank(key_block(key)), order.index(key))

    # In a Cisco running-config every block is terminated by `!`, including two
    # consecutive blocks of the same kind (two interfaces, two VLANs). Emitting
    # the separator after every block except the last reproduces that exactly.
    ordered = sorted(order, key=sort_key)
    output: List[str] = []
    for index, key in enumerate(ordered):
        output.extend(blocks[key])
        if key != "__unmapped__" and index + 1 < len(ordered):
            output.append("!")
    return output


def generate_cisco_text(steps: List[dict]) -> str:
    return "\n".join(generate_cisco_config(steps))
