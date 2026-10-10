"""
compliance/services/rule_engine.py

Deterministic rule evaluation. NO LLM calls in this file, by design.
Same input JSON + same rule file always produces the same result.

A missing/None field is NEVER silently treated as Pass or Fail.
It becomes "Unknown", so a report can never claim something passed
just because the LLM failed to extract it.

Statuses: Pass | Fail | Unknown | Manual
"""

# Operators where None/missing is a meaningful answer, not a failed extraction.
OPERATORS_THAT_HANDLE_NONE = {"exists", "non_empty"}


def flatten_rules(rules: list) -> list:
    """Expands grouped rules (a nested 'rules' block, as in cis_juniper_rules.json)
    into individual rules, so the engine only ever sees one rule at a time."""
    flat = []
    for r in rules:
        if isinstance(r.get("rules"), dict):
            parent = {k: v for k, v in r.items() if k != "rules"}
            for key, sub in r["rules"].items():
                flat.append({**parent, "id": f"{r.get('framework', 'CIS')}-{key}", **sub})
        else:
            flat.append(r)
    return flat


def extract_value(data: dict, field_path: str):
    """Dotted-path extraction, e.g. 'management.ssh_version'."""
    parts = field_path.split(".")
    cur = data
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def evaluate_rule(rule: dict, norm_data: dict) -> dict:
    """Evaluates a single rule against normalized data."""

    # Fields every result carries, with safe defaults so rule files
    # that omit id/severity/etc. don't crash the engine.
    base = {
        "rule_id": rule.get("id", "UNNAMED"),
        "framework": rule.get("framework", "CIS"),
        "name": rule.get("name", "Unnamed rule"),
        "expected": rule.get("expected"),
        "operator": rule.get("operator"),
        "field": rule.get("field"),
        "severity": rule.get("severity", "Medium"),
        "level": rule.get("level"),
        "description": rule.get("description", ""),
    }

    # Rules with no field/operator (manual checks, or the NIST "checks" block)
    # cannot be automated, so flag them for a human instead of crashing.
    if "field" not in rule or "operator" not in rule:
        return {**base, "status": "Manual", "actual": None,
                "reason": "No automated check defined for this rule. Verify manually."}

    actual = extract_value(norm_data, rule["field"])
    expected = rule.get("expected", True)
    op = rule["operator"]

    # Field was not extracted: don't guess Pass/Fail.
    # if actual is None and op not in OPERATORS_THAT_HANDLE_NONE:
    if (actual is None or actual == "") and op not in OPERATORS_THAT_HANDLE_NONE:
        return {**base, "status": "Unknown", "actual": None,
                "reason": "Field not found in normalized data. Needs human review, not auto Pass/Fail."}

    if op == "eq":
        result = actual == expected
    elif op == "ge":
        result = actual >= expected
    elif op == "in":
        result = actual in expected
    elif op == "contains_any":
        if isinstance(actual, list):
            result = any(a in expected for a in actual)
        else:
            result = any(exp in str(actual) for exp in expected)
    elif op == "contains_all":
        result = isinstance(actual, list) and all(e in actual for e in expected)
    elif op == "not_contains_any":
        if isinstance(actual, list):
            result = not any(a in expected for a in actual)
        else:
            result = not any(exp in str(actual) for exp in expected)
    elif op == "exists":
        result = (actual is not None) == expected
    elif op == "non_empty":
        result = bool(actual) == expected
    elif op == "configured":
        result = bool(actual) == expected
    else:
        # Operator the engine doesn't know (e.g. approved_only, secure).
        return {**base, "status": "Unknown", "actual": actual,
                "reason": f"Operator '{op}' is not supported by the rule engine yet."}

    return {**base, "status": "Pass" if result else "Fail", "actual": actual}


def compliance_engine(normalized_data: dict, rules: list) -> dict:
    """Evaluates all rules and returns a summarized report."""
    results = [evaluate_rule(rule, normalized_data) for rule in flatten_rules(rules)]

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "Pass")
    failed = sum(1 for r in results if r["status"] == "Fail")
    unknown = sum(1 for r in results if r["status"] == "Unknown")
    manual = sum(1 for r in results if r["status"] == "Manual")
    high_fails = sum(1 for r in results if r["status"] == "Fail" and r["severity"] == "High")

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "unknown": unknown,
            "manual": manual,
            "critical_high": high_fails,
        },
        "results": results,
    }