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
import re
from typing import List, Optional

from . import mappings as M
from .ir import DeviceIR


def build_plan(ir: DeviceIR, target_vendor: str = "junos") -> List[dict]:
    """Build the translation plan for the requested target vendor.

    Both branches consume the SAME vendor-neutral DeviceIR; only the target
    mapping catalog and generator differ.
    """
    if (target_vendor or "junos").lower() in ("cisco", "ios"):
        from .cisco_mappings import build_cisco_plan
        return build_cisco_plan(ir)
    return _build_junos_plan(ir)


def _build_junos_plan(ir: DeviceIR) -> List[dict]:
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
        if _is_credential_line(raw):
            # Never machine-translate a secret across vendors.
            plan.append({"kind": "unmapped", "mapping": "unmapped", "path": [],
                         "value": None, "source": raw, "base_confidence": 0.0,
                         "reason": "Credential line: re-create the account on the target "
                                   "device with its own hashing instead of translating it."})
            continue
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


def llm_fallback(plan: List[dict], ir: DeviceIR, search_fn=None,
                 source_vendor: str = "cisco", target_vendor: str = "junos") -> List[dict]:
    """
    Keep deterministic steps untouched. For `unmapped` steps, build an
    evidence-grounded prompt and ask the local Ollama for the target hierarchy.
    Never lets the model silently rewrite a mapped step.
    """
    from . import memory as mem
    from core.builder import call_ollama
    from config import OLLAMA_MODEL

    is_cisco_target = (target_vendor or "").lower() in ("cisco", "ios")
    source_label = _vendor_label(source_vendor)
    target_label = _vendor_label(target_vendor)
    itf_names = [i.cisco_name or i.name for i in ir.interfaces] if is_cisco_target \
        else [i.juniper_name or i.name for i in ir.interfaces]

    for step in plan:
        if step.get("kind") != "unmapped":
            continue

        # Credentials must never be machine-translated. A Cisco type7 hash or a
        # Junos encrypted-password cannot be carried across platforms: emitting
        # one into the other vendor's syntax yields a config that silently
        # fails authentication. Keep these for a human, always.
        if _is_credential_line(step.get("source", "")):
            step["reason"] = ("Credentials cannot be translated automatically. Re-create "
                              "the account on the target device with its own hashing "
                              "(Cisco: `username <n> secret <hash>`; Junos: "
                              "`set system login user <n> authentication encrypted-password`).")
            continue

        rec = mem.lookup_mapping(step.get("source", ""))
        if rec and rec.get("target"):
            path = _parse_target_path(rec["target"])
            if path and not is_cisco_target:
                step["kind"] = "set_line"
                step["mapping"] = rec.get("mapping", "memorized")
                step["path"] = path
                step["value"] = _parse_target_value(rec["target"])
                step["base_confidence"] = rec.get("confidence", 0.95)
                step["memorized"] = True
                continue
            if rec and is_cisco_target:
                # A memorized Cisco line is already in final syntax.
                block, command = _split_cisco_line(rec["target"])
                if command:
                    step["kind"] = "cisco_line"
                    step["mapping"] = rec.get("mapping", "memorized")
                    step["block"] = block
                    step["command"] = command
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

        if is_cisco_target:
            prompt = (
                f"Translate this single {source_label} configuration line into the equivalent "
                "Cisco IOS CLI command.\n"
                f"{source_label}: {step.get('source', '')}\n"
                f"Reason it needs manual mapping: {step.get('reason', '')}\n"
                "Target Cisco interface names: " + json.dumps(itf_names) + "\n\n"
                "Reference:\n" + evidence[:1500] + "\n\n"
                "Output ONLY JSON: {\"block\": \"interface GigabitEthernet0/0\" or null, "
                "\"command\": \"ip address 10.0.0.1 255.255.255.0\"}. "
                "Use null for block on a global command. If you cannot map it confidently, "
                "output {\"block\": null, \"command\": null}."
            )
            system = ("You convert network configurations to Cisco IOS CLI. Output ONLY "
                      "{\"block\": ..., \"command\": ...} JSON. No prose.")
        else:
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
            system = ("You convert Cisco IOS config lines to Junos. Output ONLY "
                      "{\"path\": [...], \"value\": ...} JSON. Use canonical Junos "
                      "hierarchy. No prose.")

        try:
            raw = call_ollama(system, prompt, temperature=0.0)
            suggestion = _extract_json(raw) or {}
            if is_cisco_target:
                command = (suggestion.get("command") or "").strip()
                if command and _plausible_cisco_command(command):
                    step["kind"] = "cisco_line"
                    step["mapping"] = "llm_assisted"
                    step["block"] = (suggestion.get("block") or "").strip() or None
                    step["command"] = command
                    step["base_confidence"] = 0.65
                    step["llm_assisted"] = True
            else:
                path = [str(p) for p in (suggestion.get("path") or [])]
                # Small models happily invent hierarchies (`set command 123 login set`).
                # Only accept a path whose root is a real Junos top-level node.
                if path and _plausible_junos_path(path):
                    step["kind"] = "set_line"
                    step["mapping"] = "llm_assisted"
                    step["path"] = path
                    step.setdefault("value", suggestion.get("value"))
                    step["base_confidence"] = 0.65
                    step["llm_assisted"] = True
                elif path:
                    step["reason"] = (
                        f"The model proposed '{' '.join(path)}', which is not a valid Junos "
                        f"hierarchy. Manual mapping required."
                    )
        except Exception:
            pass
    return plan


# Real Junos top-level configuration nodes.
JUNOS_TOP_LEVEL = {
    "system", "interfaces", "vlans", "protocols", "routing-options", "policy-options",
    "snmp", "firewall", "security", "services", "chassis", "groups", "event-options",
    "forwarding-options", "class-of-service", "multicast-routing", "switching-options",
    "vlan", "access", "radius-server", "tacplus-server", "logical-systems",
    "vrrp", "rmon", "ethernet-switching", "service-accounting",
}


def _plausible_junos_path(path: list) -> bool:
    """Reject LLM-proposed paths that are not rooted at a real Junos node."""
    if not path:
        return False
    return path[0].lower() in JUNOS_TOP_LEVEL


CISCO_TOP_LEVEL_PREFIXES = (
    "hostname", "ip ", "no ", "ntp ", "logging ", "snmp-server ", "banner ",
    "username", "enable ", "aaa ", "line ", "interface ", "vlan ", "router ",
    "service ", "crypto ", "cdp ", "clock ", "archive ", "boot ", "tacacs ",
    "radius ", "version ", "end", "exit", "wr", "copy", "access-list", "default ",
)


def _plausible_cisco_command(command: str) -> bool:
    """Reject LLM-proposed IOS lines that are not real global/block commands."""
    lowered = command.strip().lower()
    if not lowered:
        return False
    return lowered.startswith(CISCO_TOP_LEVEL_PREFIXES)


def _vendor_label(vendor: str) -> str:
    return {"cisco": "Cisco IOS", "ios": "Cisco IOS",
            "juniper": "Junos", "junos": "Junos"}.get(
        (vendor or "").lower(), (vendor or "unknown").title())


# Lines that carry secrets. The LLM must never be asked to convert these.
_CREDENTIAL_PATTERNS = (
    r"\bsecret\b", r"\bpassword\b", r"\benable\s+password\b", r"\bkey(-|_)string\b",
    r"\bpre-shared\b", r"\bencrypted-password\b", r"\bmd5\b.*\bkey\b",
    r"\bcommunity\b", r"\bauth(?:entication)?-key\b", r"\btoken\b",
    r"\$6\$", r"\$9\$", r"\bsha-?256\b", r"\bsha-?512\b",
)


def _is_credential_line(source: str) -> bool:
    text = (source or "").lower()
    return any(re.search(pattern, text) for pattern in _CREDENTIAL_PATTERNS)


def _split_cisco_line(target: str):
    """'interface Gi0/0\\n description x' -> ('interface Gi0/0', 'description x')."""
    for separator in ("\n", " / "):
        if separator in target:
            block, _, command = target.partition(separator)
            return block.strip(), command.strip()
    return None, target.strip()


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