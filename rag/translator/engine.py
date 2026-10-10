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
from .ir import normalize
from .planner import build_plan, attach_evidence, consult_memory, llm_fallback
from .generator import generate_set_commands, step_to_set_command
from .validation import validate_commands, validate_semantics, check_consistency
from .verify import run_verification_loop
from .confidence import construct_confidence, aggregate_confidence, category_of


def translate_config(
    config_text: str,
    use_llm: bool = True,
    with_rag: bool = True,
    persist: bool = True,
    search_fn: Optional[Callable] = None,
) -> dict:
    """
    Translate a Cisco config into validated Junos set commands.
    search_fn defaults to core.store.search (chatbot's pgvector store).
    Returns a structured result dict (see _default_search for fallback).
    """
    from . import memory as mem

    if search_fn is None:
        from core.store import search as default_search
        search_fn = default_search

    # ---- 1. deterministic parse -> IR --------------------------------------
    ast = cisco_parse(config_text)
    ir = normalize(ast)

    # ---- 2. plan: deterministic first, memory second ------------------------
    plan = build_plan(ir)
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
            plan = llm_fallback(plan, ir, search_fn=search_fn if with_rag else None)
        except Exception:
            pass

    # ---- 5. generate + validate + verify loop ---------------------------------
    def steps_validate(plan_steps):
        cmds = generate_set_commands(plan_steps)
        results, issues = validate_commands(cmds)
        sem = validate_semantics(ir, cmds)
        for p in sem:
            issues.append({"command": p.get("command", ""), "level": p["level"],
                           "messages": p.get("messages", [])})
        return cmds, issues

    verify = run_verification_loop(ir, plan, steps_validate)
    final_plan = verify["final_plan"]
    final_commands = verify["final_commands"]
    issues = verify["problems"]

    consistency = check_consistency(ir, final_commands)

    # ---- 6. confidence + explanations -----------------------------------------
    warnings = []
    unresolved = list(dict.fromkeys(verify["unresolved"]))
    explanations = []
    scores = []

    for step in final_plan:
        mapping = step.get("mapping", "")
        source = step.get("source", "")
        target = step_to_set_command(step) or (
            f"# UNMAPPED: {source}" if step.get("kind") == "unmapped" else "")
        cat = category_of(mapping)

        issue_level = _issue_level(target, issues)
        if issue_level == "warning" and target and not mapping.startswith("llm"):
            warnings.append(f"{source or target}: {issue_level}")

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
            "source_line": source,
            "target_command": target,
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
            warnings.append(f"{source}: {step.get('reason', 'unmapped')}")
            if source not in unresolved:
                unresolved.append(source)

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
    from .mappings import MAPPING_META
    reasons = []
    meta = MAPPING_META.get(mapping)
    if meta:
        reasons.append(meta.get("label", mapping))
        reasons.append(f"Cisco: {meta.get('cisco', '')}")
        reasons.append(f"Junos: {meta.get('junos', '')}")
    if step.get("memorized"):
        reasons.append("Matched verified translation memory.")
    if step.get("llm_assisted"):
        reasons.append("LLM-assisted translation (lower confidence).")
    if step.get("kind") == "unmapped":
        reasons.append(step.get("reason", "No verified Junos equivalent found."))
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