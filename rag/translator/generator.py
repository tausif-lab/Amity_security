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

    Unmapped steps become `# UNMAPPED: <source>  (reason)` comment lines.
    Identical commands are emitted once: several source lines (for example
    `ip ssh version 2` and `transport input ssh`) can legitimately map to the
    same Junos statement, and repeating it would be rejected by the device.
    """
    out = []
    seen = set()
    rendered = []
    for step in sort_steps(plan):
        if step.get("kind") == "unmapped":
            src = step.get("source", "")
            reason = step.get("reason", "No verified Junos equivalent found.")
            # Never echo a secret back out, not even inside a comment: the
            # generated file is downloaded and shared between reviewers.
            marker = f"# UNMAPPED: {redact_secret(src)}"
            if marker in seen:
                continue
            seen.add(marker)
            out.append(marker)
            out.append(f"#   reason: {reason}")
            continue
        cmd = step_to_set_command(step)
        if cmd and cmd not in seen:
            seen.add(cmd)
            rendered.append(cmd)
            out.append(cmd)
    return _drop_redundant_parents(out, rendered)


def _drop_redundant_parents(out: List[str], rendered: List[str]) -> List[str]:
    """Remove `set a b` when `set a b c` already configures the same branch.

    In Junos, configuring a leaf implicitly enables its parents, so emitting
    both `set system services ssh` and
    `set system services ssh protocol-version v2` is redundant noise.
    """
    redundant = set()
    for command in rendered:
        if not command.startswith("set "):
            continue
        # only a multi-level parent can be implied by a longer command
        while " " in command[4:]:
            command = command.rsplit(" ", 1)[0]
            if len(command.split(" ")) < 3:
                break
            if command in rendered and command not in redundant:
                redundant.add(command)
    if not redundant:
        return out
    return [line for line in out if line not in redundant]


# Token names after which the remainder of a command is treated as a secret.
_SECRET_TOKENS = ("secret", "password", "key-string",
                  "encrypted-password", "community", "pre-shared-key")


def redact_secret(text: str) -> str:
    """Replace a trailing credential value with `<redacted>`."""
    low = text.lower()
    for token in _SECRET_TOKENS:
        index = low.rfind(token)
        if index == -1:
            continue
        tail = text[index + len(token):]
        # only redact when the secret value is the last thing on the line
        value = tail.strip().lstrip("=").strip()
        if not value or value.startswith("#"):
            continue
        return text[:index + len(token)] + " <redacted>"
    return text


def generate_config_text(plan: List[dict]) -> str:
    return "\n".join(generate_set_commands(plan))