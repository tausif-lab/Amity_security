"""
translator/confidence.py
Confidence scoring per construct and overall.

Scores start from a per-step base (deterministic mappings are high, LLM lower)
and are adjusted by:
  * validation result (error -> cap low)
  * presence/strength of RAG evidence
  * round-trip through the verification loop (>1 rounds -> slight penalty)
  * memorized (translation memory) -> boost
"""

CATEGORY_BY_MAPPING = {
    "hostname": "Global Systems",
    "ntp": "Global Systems",
    "snmp_community": "Global Systems",
    "snmp_location": "Global Systems",
    "logging_host": "Global Systems",
    "ssh": "Global Systems",
    "iface_desc": "Interfaces",
    "iface_addr": "Interfaces",
    "iface_disabled": "Interfaces",
    "iface_vlan": "Interfaces",
    "iface_trunk": "Interfaces",
    "iface_mtu": "Interfaces",
    "vlan": "VLAN",
    "vlan_irb": "VLAN",
    "ospf": "OSPF",
    "ospf_rid": "OSPF",
    "ospf_area": "OSPF",
    "bgp": "BGP",
    "static_route": "Routing",
    "llm_assisted": "LLM Assisted",
    "memorized": "Memorized",
    "unmapped": "Unmapped",
}


def category_of(mapping: str) -> str:
    return CATEGORY_BY_MAPPING.get(mapping, "Other")


def construct_confidence(step: dict, validation_level: str = "ok",
                         max_evidence_score: float = 0.0,
                         in_verify_loop: bool = False) -> float:
    conf = float(step.get("base_confidence", 0.8))
    kind = step.get("kind")

    if kind == "unmapped":
        return 0.2

    # validation errors dominate regardless of mapping quality
    if validation_level == "error":
        conf = min(conf, 0.45)
    elif validation_level == "warning":
        conf -= 0.10

    # evidence: deterministic mappings should match docs; boost if strong hit
    if step.get("evidence"):
        conf += 0.02 * min(len(step.get("evidence")), 3)
    if max_evidence_score > 0.7:
        conf += 0.03
    if max_evidence_score < 0.3 and step.get("mapping") and step["mapping"] not in ("memorized",):
        conf -= 0.04  # low doc support, deterministic still ok

    if step.get("memorized"):
        conf += 0.04
    if step.get("llm_assisted"):
        conf = min(conf, 0.7)
    if in_verify_loop:
        conf -= 0.03

    return max(0.0, min(1.0, conf))


def aggregate_confidence(scores: list) -> dict:
    """scores: list of dicts {category, confidence, validated}.
    Returns {"overall": float, "by_category": {cat: float}}."""
    if not scores:
        return {"overall": 0.0, "by_category": {}}
    by_cat = {}
    for s in scores:
        by_cat.setdefault(s["category"], []).append(s["confidence"])
    by_category = {c: round(sum(v) / len(v), 3) for c, v in by_cat.items()}
    validated = [s for s in scores if s.get("validated")]
    base = sum(s["confidence"] for s in scores) / len(scores)
    coverage = (len(validated) / len(scores)) if scores else 0.0
    overall = round(0.7 * base + 0.3 * coverage, 3)
    return {"overall": overall, "by_category": by_category}