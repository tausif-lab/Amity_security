"""
translator/planner.py
Turns a normalized IR into a translation plan (list of steps).

Strategy:
  1. deterministic mappings (translation/mappings) -- no LLM
  2. translation memory lookup for any prior verified source -> target
  3. retrieval evidence (core.store.search) is attached to each step when
     available; it is used in explanation and to boost confidence
  4. LLM fallback ONLY for steps that remain unmapped
"""

import json
from typing import List, Optional

from . import mappings as M
from .ir import DeviceIR


def build_plan(ir: DeviceIR) -> List[dict]:
    plan: List[dict] = []

    # --- global system ------------------------------------------------------
    if ir.global_config.hostname:
        plan.append(M.map_hostname(ir.global_config.hostname))

    if ir.global_config.ntp.servers:
        plan.extend(M.map_ntp(ir.global_config.ntp.servers))

    for comm in ir.global_config.snmp.community_strings:
        plan.append(M.map_snmp(comm))

    if ir.global_config.snmp.location:
        plan.append({"kind": "set_line", "mapping": "snmp_location",
                     "path": ["snmp", "location"],
                     "value": ir.global_config.snmp.location,
                     "source": f"snmp-server location {ir.global_config.snmp.location}",
                     "base_confidence": 0.97})

    for host in ir.global_config.logging.hosts:
        plan.append(M.map_logging_host(host))

    if ir.global_config.ssh_version:
        plan.append({"kind": "set_line", "mapping": "ssh",
                     "path": ["system", "services", "ssh", "protocol-version"],
                     "value": f"v{ir.global_config.ssh_version}",
                     "source": f"ip ssh version {ir.global_config.ssh_version}",
                     "base_confidence": 0.97})

    # --- interfaces ----------------------------------------------------------
    for itf in ir.interfaces:
        plan.extend(M.map_interface(itf))

    # --- vlans ---------------------------------------------------------------
    for vlan in ir.vlans:
        plan.append(M.map_vlan(vlan))

    # --- routing -------------------------------------------------------------
    for ospf in ir.ospf:
        plan.extend(M.map_ospf(ospf, ir))
    for bgp in ir.bgp:
        plan.append({"kind": "set_line", "mapping": "bgp",
                     "path": ["protocols", "bgp"], "value": None,
                     "source": f"router bgp {bgp.asn}", "base_confidence": 0.95})
        for nbr in bgp.neighbors:
            plan.append({"kind": "set_line", "mapping": "bgp",
                         "path": ["protocols", "bgp", "group", "EXT", "neighbor", nbr["ip"]],
                         "value": f"peer-as {nbr['remote_as']}",
                         "source": f"neighbor {nbr['ip']} remote-as {nbr['remote_as']}",
                         "base_confidence": 0.94})

    for route in ir.static_routes:
        plan.append(M.map_static_route(route))

    # --- raw/unhandled commands: try the chatbot table, else unmapped --------
    for raw in ir.global_config.raw_commands:
        mapped_line = _table_lookup(raw)
        if mapped_line:
            plan.append({"kind": "verbatim", "mapping": "table",
                         "verbatim": mapped_line,
                         "source": raw, "base_confidence": 0.85,
                         "table_mapped": True})
        else:
            plan.append({"kind": "unmapped", "mapping": "unmapped", "path": [],
                         "value": None, "source": raw, "base_confidence": 0.2,
                         "reason": f"No verified Junos equivalent for '{raw}'. Manual review required."})

    return plan


def _table_lookup(line: str) -> str:
    """Reuse the chatbot's deterministic table (core/mappings.py) for global
    commands that have no first-class IR construct."""
    try:
        from core.mappings import table_translate
        out, _ = table_translate(line)
        for o in out:
            if o and o.startswith(("set ", "delete ")):
                return o
        if out and out[-1] and out[-1].startswith("# UNMAPPED"):
            return None
    except Exception:
        pass
    return None


def attach_evidence(plan: List[dict], search_fn) -> List[dict]:
    """Annotate each step with relevant RAG evidence (if the store is loaded)."""
    for step in plan:
        src = step.get("source")
        if not src:
            continue
        try:
            hits = search_fn(src) or []
        except Exception:
            hits = []
        step["evidence"] = [
            {"source": h.get("source"), "score": round(h.get("score", 0), 4),
             "content": str(h.get("content", ""))[:500], "section": h.get("section")}
            for h in hits[:3]
        ]
    return plan


def consult_memory(plan: List[dict]) -> List[dict]:
    """Replace deterministic steps whose source was verified in the past with
    the memorized target (higher confidence than the base table)."""
    from . import memory as mem
    for step in plan:
        src = step.get("source")
        if not src or step.get("kind") == "unmapped":
            continue
        rec = mem.lookup_mapping(src)
        if rec:
            step["base_confidence"] = max(step.get("base_confidence", 0.0),
                                          rec.get("confidence", 0.9))
            step["memorized"] = True
    return plan


def llm_fallback(plan: List[dict], ir: DeviceIR, search_fn=None) -> List[dict]:
    """
    Keep deterministic steps untouched. For `unmapped` steps, build an
    evidence-grounded prompt and ask the local Ollama for a Junos hierarchy.
    Never lets the model silently rewrite a mapped step.
    """
    from . import memory as mem
    from core.builder import call_ollama
    from config import OLLAMA_MODEL

    itf_names = [i.juniper_name or i.name for i in ir.interfaces]
    for step in plan:
        if step.get("kind") != "unmapped":
            continue

        rec = mem.lookup_mapping(step.get("source", ""))
        if rec and rec.get("target"):
            path = _parse_target_path(rec["target"])
            if path:
                step["kind"] = "set_line"
                step["mapping"] = rec.get("mapping", "memorized")
                step["path"] = path
                step["value"] = _parse_target_value(rec["target"])
                step["base_confidence"] = rec.get("confidence", 0.95)
                step["memorized"] = True
                continue

        evidence = ""
        if search_fn:
            try:
                hits = search_fn(step.get("source", "")) or []
                evidence = "\n".join(
                    f"- [{h.get('source')}] {str(h.get('content', ''))[:600]}"
                    for h in hits[:3])
            except Exception:
                pass
        if not evidence:
            evidence = "(no knowledge base match)"

        prompt = (
            "Translate this single Cisco IOS line into an equivalent Junos `set`"
            " hierarchy (path only, no values with spaces).\n"
            f"Cisco: {step.get('source', '')}\n"
            f"Reason it needs manual mapping: {step.get('reason', '')}\n"
            "Available translated interface Junos names: " + json.dumps(itf_names) + "\n\n"
            "Junos reference:\n" + evidence[:1500] + "\n\n"
            "Output ONLY JSON: {\"path\": [\"interfaces\", \"...\"], \"value\": <value or null>}. "
            "If you cannot map it confidently, output {\"path\": []}."
        )
        try:
            raw = call_ollama(
                ("You convert Cisco IOS config lines to Junos. Output ONLY "
                 "{\"path\": [...], \"value\": ...} JSON. Use canonical Junos "
                 "hierarchy. No prose."),
                prompt, temperature=0.0)
            suggestion = _extract_json(raw)
            path = (suggestion or {}).get("path") or []
            if path:
                step["kind"] = "set_line"
                step["mapping"] = "llm_assisted"
                step["path"] = [str(p) for p in path]
                step.setdefault("value", (suggestion or {}).get("value"))
                step["base_confidence"] = 0.65
                step["llm_assisted"] = True
        except Exception:
            pass
    return plan


def _extract_json(raw: str) -> Optional[dict]:
    raw = raw.strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
    except Exception:
        pass
    return None


def _parse_target_path(target: str) -> list:
    # target may be "path=value" or bare "path words"
    body = target[len("set "):] if target.startswith("set ") else target
    words = body.split()
    if "=" in body:
        eq = next(i for i, w in enumerate(words) if "=" in w)
        return words[:eq]
    return words


def _parse_target_value(target: str) -> str:
    body = target[len("set "):] if target.startswith("set ") else target
    words = body.split()
    if "=" in body:
        eq = next(i for i, w in enumerate(words) if "=" in w)
        return "=".join(words[eq].split("=")[1:]) or None
    return None