"""
translator/generator.py
Renders plan steps into Junos `set` commands.

A step is a dict:
  {"kind": "set_line"|"noop"|"unmapped",
   "mapping": id, "path": [...], "value": ..., "source": "...",
   "base_confidence": float,
   "requires": [...], "method": "set"|"edit", "llm_assisted": bool}

Rendering rules:
  * path of length>1 -> `set <path...> <value>` using canonical Junos syntax
  * list values -> `[ a b ]` ; values containing spaces -> quoted
"""

from typing import List


def render_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        inner = " ".join(str(v) for v in value)
        return f"[ {inner} ]"
    text = str(value)
    if " " in text:
        return f'"{text}"'
    return text


def step_to_set_command(step: dict) -> str:
    """Render ONE step into a `set` line (or '' if nothing to render)."""
    kind = step.get("kind")
    if kind == "unmapped":
        return ""
    if kind == "noop":
        return f"# no-op (default): set {' '.join(step.get('path', []))}"
    if kind == "verbatim":
        return str(step.get("verbatim", "")).strip()

    path = step.get("path") or []
    if not path:
        return ""
    value = render_value(step.get("value"))
    if value:
        return f"set {' '.join(path)} {value}"
    return f"set {' '.join(path)}"


SORT_RANK = {"noop": 0, "set_line": 1, "verbatim": 1, "edit": 2, "unmapped": 3}


def sort_steps(plan: List[dict]) -> List[dict]:
    return sorted(plan, key=lambda s: (SORT_RANK.get(s.get("kind"), 9),
                                       len(s.get("path", []))))


def generate_set_commands(plan: List[dict]) -> List[str]:
    """Render an entire plan to a stable, ordered list of set commands.
    Unmapped steps become `# UNMAPPED: <source>  (reason)` comment lines."""
    out = []
    for step in sort_steps(plan):
        if step.get("kind") == "unmapped":
            src = step.get("source", "")
            reason = step.get("reason", "No verified Junos equivalent found.")
            out.append(f"# UNMAPPED: {src}")
            out.append(f"#   reason: {reason}")
            continue
        cmd = step_to_set_command(step)
        if cmd:
            out.append(cmd)
    return out


def generate_config_text(plan: List[dict]) -> str:
    return "\n".join(generate_set_commands(plan))