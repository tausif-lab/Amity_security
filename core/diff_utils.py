# NEW FILE: core/diff_utils.py
import difflib
import re

# Lines that change on every export without the device changing.
_NOISE = re.compile(
    r"^\s*(?:!|#|Building configuration|Current configuration|Last configuration change"
    r"|NVRAM config last updated|Using \d+ out of \d+ bytes)", re.I)

_SECRET = re.compile(
    r"(?i)\b(password|secret|community|key-string|pre-shared-key|encrypted-password)\b"
    r"(\s+(?:\d+\s+)?)(\S+)")


def _prepare(text):
    """Returns ([(original_line_number, line_text)], {line_number: parent_block}).
    Blank lines, comments and timestamps are dropped. A '!' line ends a Cisco block."""
    kept, parent, current = [], {}, ""
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.rstrip()
        if not line.strip():
            continue
        if line.strip() == "!":
            current = ""
            continue
        if _NOISE.match(line):
            continue
        if line[0].isspace():
            parent[n] = current
        else:
            current = line.strip()
            parent[n] = ""
        kept.append((n, line))
    return kept, parent


def compute_changes(old_text, new_text):
    """Raw line diff. Returns [(change_type, line_number, line_text, parent_block)].
    'removed' lines are numbered in the old file, 'added' lines in the new file."""
    old, old_parent = _prepare(old_text)
    new, new_parent = _prepare(new_text)
    sm = difflib.SequenceMatcher(None, [t for _, t in old], [t for _, t in new], autojunk=False)
    events = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            events += [("removed", n, t, old_parent.get(n, "")[:255]) for n, t in old[i1:i2]]
        if tag in ("replace", "insert"):
            events += [("added", n, t, new_parent.get(n, "")[:255]) for n, t in new[j1:j2]]
    return events


def mask_line(text):
    """'snmp-server community public RO' -> 'snmp-server community **** RO'"""
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}****", text or "")


def can_view_secrets(request):
    """Adapt to however roles are stored on your Supabase user. Masked by default."""
    return getattr(getattr(request, "user", None), "role", None) in {"admin", "manager"}


def rule_flips(previous_findings, new_findings):
    """Compliance rules whose status changed between two snapshots (e.g. Pass -> Fail)."""
    old = {r["rule_id"]: r["status"] for r in (previous_findings or {}).get("results", [])}
    return [{"rule_id": r["rule_id"], "name": r.get("name", ""), "from": old[r["rule_id"]], "to": r["status"]}
            for r in (new_findings or {}).get("results", [])
            if r["rule_id"] in old and old[r["rule_id"]] != r["status"]]