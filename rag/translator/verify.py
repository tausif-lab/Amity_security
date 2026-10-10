"""
translator/verify.py
Rethink-style verification loop:

    generate -> validate -> critique
    if problems -> repair (deterministic) -> re-validate (max N rounds)

Never reports PASS for something known invalid. Remaining problems become
warnings surfaced to the caller; nothing is silently dropped.
"""

import copy
from typing import List

from config import MAX_VERIFY_ROUNDS

MAX_ROUNDS = MAX_VERIFY_ROUNDS


def critique(ir, plan: List[dict], commands: List[str], issues: List[dict]) -> List[dict]:
    """Find problems: coverage of IR constructs + validation issues + unmapped."""
    problems = []
    mapped_sources = {s.get("source", "").lower() for s in plan if s.get("kind") != "unmapped"}
    mapped_paths = {" ".join(s.get("path") or []).lower() for s in plan if s.get("kind") != "unmapped"}

    for itf in ir.interfaces:
        jname = (itf.juniper_name or itf.name).lower()
        covered = (jname in " ".join(mapped_sources)
                   or any(jname in pth for pth in mapped_paths))
        if not covered and (itf.ipv4 or itf.description or itf.vlan_members):
            problems.append({
                "type": "coverage", "severity": "high",
                "construct": f"interface {itf.cisco_name}",
                "message": "Interface has properties but no mapped translation found.",
            })

    for iss in issues:
        if iss.get("level") == "error":
            problems.append({
                "type": "syntax", "severity": "high",
                "construct": iss.get("command", ""),
                "message": "; ".join(iss.get("messages", [])),
            })

    for s in plan:
        if s.get("kind") == "unmapped":
            problems.append({
                "type": "unmapped", "severity": "medium",
                "construct": str(s.get("source", "")),
                "message": s.get("reason", "No verified Junos equivalent found."),
            })
    return problems


def _repair(plan: List[dict], problems: List[dict]) -> tuple:
    """Deterministic repairs only. Unmapped/unsolvable -> unresolved."""
    new_plan = copy.deepcopy(plan)
    unresolved = []
    for p in problems:
        if p.get("type") == "unmapped":
            unresolved.append(p.get("construct"))
        # syntax problems with known fixes could be handled here; currently
        # the planner is deterministic so repairs are rarely needed.
    return new_plan, [], unresolved


def run_verification_loop(ir, plan, steps_validate) -> dict:
    """
    steps_validate(plan) -> (commands, issues)
    Returns {"final_commands", "final_plan", "problems", "unresolved", "rounds"}
    """
    current_plan = copy.deepcopy(plan)
    problems = []
    unresolved = []
    rounds = 0

    for rounds in range(1, MAX_ROUNDS + 1):
        commands, issues = steps_validate(current_plan)
        new_problems = critique(ir, current_plan, commands, issues)

        if not new_problems:
            return {
                "rounds": rounds, "final_plan": current_plan,
                "final_commands": commands, "problems": [],
                "unresolved": unresolved,
            }

        if rounds == MAX_ROUNDS:
            problems = new_problems
            break

        repaired, _, _unresolved = _repair(current_plan, new_problems)
        current_plan = repaired
        for u in _unresolved:
            if u not in unresolved:
                unresolved.append(u)
        problems = new_problems

    for p in problems:
        construct = str(p.get("construct", ""))
        if construct and construct not in unresolved:
            unresolved.append(construct)

    return {
        "rounds": rounds, "final_plan": current_plan,
        "final_commands": commands, "problems": problems,
        "unresolved": unresolved,
    }