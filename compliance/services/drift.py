"""
compliance/services/drift.py

Configuration Drift Detection / Continuous Compliance Monitoring.

A plain config diff answers "what text changed". This answers the question an
auditor actually asks: "what changed, and which compliance verdicts did it
move?". Every change is correlated back to the benchmark rules it flips, so a
removed NTP server is reported as "CIS-1.6.1 regressed", not just as a deleted
line.
"""

from .rule_engine import compliance_engine


def flatten(data, prefix="") -> dict:
    """Flatten a nested baseline into dotted paths -> comparable values."""
    flat = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            flat.update(flatten(value, path))
    elif isinstance(data, list):
        flat[prefix] = tuple(data)
    else:
        flat[prefix] = data
    return flat


def _comparable(value):
    if isinstance(value, tuple):
        return tuple("" if item is None else item for item in value)
    return value


def diff_baselines(old: dict, new: dict) -> list[dict]:
    """Field-level changes between two normalized baselines."""
    old_flat = {k: _comparable(v) for k, v in flatten(old or {}).items()}
    new_flat = {k: _comparable(v) for k, v in flatten(new or {}).items()}

    changes = []
    for path in sorted(set(old_flat) | set(new_flat)):
        before = old_flat.get(path, KeyError)
        after = new_flat.get(path, KeyError)
        if before == after:
            continue
        changes.append({
            "field": path,
            "change": "added" if path not in old_flat else
                      "removed" if path not in new_flat else "modified",
            "previous": None if before is KeyError else before,
            "current": None if after is KeyError else after,
        })
    return changes


def correlate_to_rules(old_baseline: dict, new_baseline: dict, rules: list) -> list[dict]:
    """Which rules changed verdict between the two baselines."""
    old_report = compliance_engine(old_baseline or {}, rules)
    new_report = compliance_engine(new_baseline or {}, rules)
    old_by_id = {r["rule_id"]: r for r in old_report["results"]}
    new_by_id = {r["rule_id"]: r for r in new_report["results"]}

    moved = []
    for rule_id, new_result in new_by_id.items():
        old_result = old_by_id.get(rule_id)
        old_status = old_result["status"] if old_result else None
        if old_status == new_result["status"]:
            continue
        moved.append({
            "rule_id": rule_id,
            "name": new_result["name"],
            "severity": new_result.get("severity", "Medium"),
            "previous_status": old_status,
            "current_status": new_result["status"],
            "regression": new_result["status"] == "Fail" and old_status != "Fail",
        })
    moved.sort(key=lambda item: (not item["regression"], item["rule_id"]))
    return moved


def build_drift_report(old_baseline: dict, new_baseline: dict, rules: list,
                       old_meta: dict | None = None, new_meta: dict | None = None) -> dict:
    """Full drift result: what changed, what it broke, and the score delta."""
    changes = diff_baselines(old_baseline, new_baseline)
    moved = correlate_to_rules(old_baseline, new_baseline, rules)

    old_report = compliance_engine(old_baseline or {}, rules)
    new_report = compliance_engine(new_baseline or {}, rules)

    return {
        "changed": bool(changes),
        "drift_count": len(changes),
        "changes": changes,
        "rules_impacted": moved,
        "regressions": [m for m in moved if m["regression"]],
        "previous_summary": old_report["summary"],
        "current_summary": new_report["summary"],
        "score_delta": {
            "passed": new_report["summary"]["passed"] - old_report["summary"]["passed"],
            "failed": new_report["summary"]["failed"] - old_report["summary"]["failed"],
        },
        "baseline_before": old_meta or {},
        "baseline_after": new_meta or {},
    }