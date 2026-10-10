"""
translator/engine.py
Orchestrator for the merged pipeline:

    Cisco config text
      -> parse                   (deterministic)
      -> normalize to IR         (deterministic)
      -> translation memory hit? (psycopg2, before LLM)
      -> plan (deterministic mappings first)
      -> RAG evidence (core.store.search) per construct
      -> LLM fallback for unmapped only
      -> generate set commands   (deterministic)
      -> validate + verify loop  (rules-based; never LLM-asserted)
      -> score confidence + explanations
      -> persist run + verified mappings to translation memory

Retrieval is provided by the chatbot's existing core.store.search so the two
approaches share one knowledge base and one vector store.
"""

from typing import Callable, Optional

from .cisco_parser import parse as cisco_parse
from .juniper_parser import parse as juniper_parse
from .ir import normalize as normalize_cisco
from .juniper_ir import normalize as normalize_juniper
from .planner import build_plan, attach_evidence, consult_memory, llm_fallback
from .generator import generate_set_commands, step_to_set_command
from .cisco_generator import generate_cisco_config, step_to_cisco_line
from .validation import validate_commands, validate_semantics, check_consistency
from .verify import run_verification_loop
from .confidence import construct_confidence, aggregate_confidence, category_of


CISCO_ALIASES = {"cisco", "ios"}
JUNIPER_ALIASES = {"juniper", "junos"}


def translate_config(
    config_text: str,
    use_llm: bool = True,
    with_rag: bool = True,
    persist: bool = True,
    search_fn: Optional[Callable] = None,
    source_vendor: str = "cisco",
    target_vendor: str = "junos",
) -> dict:
    """
    Translate a configuration between Cisco IOS and Juniper Junos.

        Cisco config  -> parse -> IR -> plan -> validate -> Junos `set` commands
        Junos config  -> parse -> IR -> plan -> validate -> Cisco IOS config

    Both directions share one vendor-neutral IR, so only the parser, the mapping
    catalog and the generator differ. search_fn defaults to core.store.search
    (the chatbot's pgvector store) so the two approaches share one knowledge
    base. Returns a structured result dict.
    """
    from . import memory as mem

    source = (source_vendor or "cisco").strip().lower()
    target = (target_vendor or "junos").strip().lower()

    if search_fn is None:
        from core.store import search as default_search
        search_fn = default_search

    is_cisco_target = target in CISCO_ALIASES

    # ---- 1. deterministic parse -> IR --------------------------------------
    if source in JUNIPER_ALIASES:
        ast = juniper_parse(config_text)
        ir = normalize_juniper(ast)
    else:
        ast = cisco_parse(config_text)
        ir = normalize_cisco(ast)

    # ---- 2. plan: deterministic first, memory second ------------------------
    plan = build_plan(ir, target_vendor=target)
    try:
        plan = consult_memory(plan)
    except Exception:
        pass

    # ---- 3. RAG evidence per construct --------------------------------------
    if with_rag:
        try:
            plan = attach_evidence(plan, search_fn)
        except Exception:
            with_rag = False

    # ---- 4. LLM fallback for unmapped only ----------------------------------
    if use_llm:
        try:
            plan = llm_fallback(plan, ir, search_fn=search_fn if with_rag else None,
                                source_vendor=source, target_vendor=target)
        except Exception:
            pass

    # ---- 5. generate + validate + verify loop ---------------------------------
    def render(plan_steps):
        if is_cisco_target:
            return generate_cisco_config(plan_steps)
        return generate_set_commands(plan_steps)

    def steps_validate(plan_steps):
        cmds = render(plan_steps)
        results, issues = validate_commands(cmds, vendor=target)
        sem = validate_semantics(ir, cmds, vendor=target)
        for p in sem:
            issues.append({"command": p.get("command", ""), "level": p["level"],
                           "messages": p.get("messages", [])})
        return cmds, issues

    verify = run_verification_loop(ir, plan, steps_validate)
    final_plan = verify["final_plan"]
    final_commands = verify["final_commands"]
    issues = verify["problems"]

    consistency = check_consistency(ir, final_commands, vendor=target)

    # ---- 6. confidence + explanations -----------------------------------------
    warnings = []
    unresolved = list(dict.fromkeys(verify["unresolved"]))
    explanations = []
    scores = []

    for step in final_plan:
        mapping = step.get("mapping", "")
        source_line = step.get("source", "")
        target_command = (step_to_cisco_line(step) if is_cisco_target
                          else step_to_set_command(step)) or (
            f"# UNMAPPED: {source_line}" if step.get("kind") == "unmapped" else "")
        cat = category_of(mapping)

        issue_level = _issue_level(target_command, issues)
        if issue_level == "warning" and target_command and not mapping.startswith("llm"):
            warnings.append(f"{source_line or target_command}: {issue_level}")

        evidence = step.get("evidence", [])
        conf = construct_confidence(
            step,
            validation_level=issue_level,
            max_evidence_score=max((e.get("score", 0) for e in evidence), default=0.0),
            in_verify_loop=verify["rounds"] > 1,
        )
        validated = issue_level != "error" and step.get("kind") != "unmapped"

        reasons = _reasons(step, mapping)

        explanations.append({
            "source_line": source_line,
            "target_command": target_command,
            "mapping": mapping,
            "category": cat,
            "confidence": round(conf, 3),
            "validated": validated,
            "llm_assisted": bool(step.get("llm_assisted")),
            "memorized": bool(step.get("memorized")),
            "reasons": reasons,
            "evidence": evidence,
        })
        scores.append({"category": cat, "confidence": conf, "validated": validated})

        if step.get("kind") == "unmapped":
            warnings.append(f"{source_line}: {step.get('reason', 'unmapped')}")
            if source_line not in unresolved:
                unresolved.append(source_line)

    for p in consistency:
        msg = p.get("messages", [""])[0]
        warnings.append(msg)
        if p["level"] == "warning" and msg not in unresolved:
            unresolved.append(msg)

    agg = aggregate_confidence(scores)

    # ---- 7. persist -------------------------------------------------------------
    run_id = None
    if persist:
        run_id = _persist(mem, config_text, final_commands, agg, unresolved, warnings,
                          explanations, verify["rounds"])

    return {
        "run_id": run_id,
        "source_vendor": source,
        "target_vendor": target,
        "source_config": config_text,
        "ir": ir.model_dump_safe(),
        "set_commands": final_commands,
        "overall_confidence": agg["overall"],
        "confidence_by_category": agg["by_category"],
        "explanations": explanations,
        "warnings": list(dict.fromkeys(warnings)),
        "unresolved": unresolved,
        "rounds": verify["rounds"],
        "status": "done" if not unresolved else "review",
    }


def _issue_level(target: str, issues: list) -> str:
    for i in issues:
        if i.get("command") and target.startswith(i["command"].split("#")[0].strip()[:20]):
            if i.get("level") in ("error", "warning"):
                return i["level"]
    return "ok"


def _reasons(step: dict, mapping: str) -> list:
    from . import mappings as junos_meta
    reasons = []
    # The explanation catalog differs per direction: cisco_mappings documents
    # Junos -> IOS, mappings documents IOS -> Junos.
    try:
        from .cisco_mappings import CISCO_MAPPING_META
        meta = CISCO_MAPPING_META.get(mapping)
    except Exception:
        meta = None
    if meta is None:
        meta = junos_meta.MAPPING_META.get(mapping)
    if meta:
        reasons.append(meta.get("label", mapping))
        if "cisco" in meta:
            reasons.append(f"Source: {meta.get('junos', '')}")
            reasons.append(f"Target: {meta.get('cisco', '')}")
        else:
            reasons.append(f"Cisco: {meta.get('cisco', '')}")
            reasons.append(f"Junos: {meta.get('junos', '')}")
    if step.get("memorized"):
        reasons.append("Matched verified translation memory.")
    if step.get("llm_assisted"):
        reasons.append("LLM-assisted translation (lower confidence).")
    if step.get("kind") == "unmapped":
        reasons.append(step.get("reason", "No verified target equivalent found."))
    return reasons


def _persist(mem, source, commands, agg, unresolved, warnings, explanations, rounds) -> Optional[int]:
    try:
        run_id = mem.record_run(
            source=source,
            juniper="\n".join(commands),
            overall=agg["overall"],
            by_category=agg["by_category"],
            unresolved=unresolved,
            warnings=warnings,
        )
        for ex in explanations:
            if (ex.get("validated") and ex.get("source_line") and ex.get("target_command")
                    and ex.get("confidence", 0) >= 0.85):
                mem.save_mapping(
                    source_line=ex["source_line"],
                    mapping=ex.get("mapping", "deterministic"),
                    target=ex["target_command"],
                    confidence=ex["confidence"],
                    run_id=run_id,
                )
        return run_id
    except Exception:
        return None