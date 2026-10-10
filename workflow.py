"""
workflow.py — one-shot CLI that drives the full Cisco->Junos chain:

    config file  ->  RAG translate API (:8001)  ->  normalised_*.json
                 ->  ai_engine (Django :8000)   ->  compliance report

Usage:
    python workflow.py --config D:\\Security_Compilence\\sample_config.txt --source cisco --target junos
    python workflow.py --target juniper                       # prompt for config path
    python workflow.py --check                                # health: RAG + Django + Ollama + DB

Flags are optional; anything missing is prompted interactively.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

RAG_URL = "http://127.0.0.1:8001"
DJANGO_URL = "http://127.0.0.1:8000"

TARGETS = ["junos", "juniper", "cisco"]
SOURCES = ["cisco", "ios"]


def check() -> None:
    print("\n=== HEALTH CHECK ===\n")
    services = {
        "RAG API (:8001)": f"{RAG_URL}/api/health",
        "Django (:8000)": f"{DJANGO_URL}/api/health/",
        "Ollama (:11434)": "http://127.0.0.1:11434/api/tags",
    }
    ok = True
    for name, url in services.items():
        try:
            r = requests.get(url, timeout=10)
            print(f"  [{'OK' if r.ok else 'ERR'}] {name}  (HTTP {r.status_code})")
            if not r.ok:
                ok = False
        except Exception as e:
            print(f"  [DOWN] {name}  -> {type(e).__name__}: {e}")
            ok = False

    try:
        r = requests.get(f"{RAG_URL}/api/health", timeout=10)
        body = r.json()
        print(f"\n  RAG details: DB connected={body['database']['connected']} "
              f"chunks={body['database'].get('chunk_count')}, "
              f"Ollama connected={body['ollama']['connected']}")
        print(f"  Supported vendors: sources={body['supported_vendors']['sources']} "
              f"targets={body['supported_vendors']['targets']}")
    except Exception as e:
        print(f"\n  RAG details unavailable: {e}")

    print("\n" + ("All services up." if ok else "Some services are down - fix them first."))
    sys.exit(0 if ok else 1)


def upload_to_rag(config_path: Path, source: str, target: str) -> dict:
    with open(config_path, "rb") as f:
        resp = requests.post(
            f"{RAG_URL}/api/translate/upload",
            params={"source_vendor": source, "target_vendor": target},
            files={"file": (config_path.name, f)},
            timeout=240,
        )
    resp.raise_for_status()
    return resp.json()


def fetch_report(upload_id) -> dict:
    try:
        r = requests.get(f"{DJANGO_URL}/api/uploads/{upload_id}/", timeout=30)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


def print_compliance(report: dict) -> None:
    if not report:
        print("  (no compliance report available)")
        return
    s = report.get("summary", {})
    print(f"  Total: {s.get('total')} | Passed: {s.get('passed')} | "
          f"Failed: {s.get('failed')} | Critical/High: {s.get('critical_high')} | "
          f"Unknown: {s.get('unknown')}")
    for r in report.get("results", []):
        mark = {"Pass": "PASS", "Fail": "FAIL", "Unknown": "UNKN"}.get(r["status"], "???")
        print(f"    [{mark:<4}] {r.get('rule_id')} {r.get('name')}")


def run(config_path: Path, source: str, target: str) -> int:
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    print(f"\n>> Uploading {config_path.name} to RAG  ({source} -> {target})")
    try:
        doc = upload_to_rag(config_path, source, target)
    except Exception as e:
        print(f"RAG translate failed: {e}")
        print("Is the RAG API running?  ->  python rag/main.py  (port 8001)")
        return 1

    print(f"\n=== TRANSLATION RESULT ===")
    print(f"  status            : {doc.get('status')}")
    print(f"  overall confidence: {doc.get('overall_confidence')}")
    print(f"  passthrough       : {doc.get('passthrough')}")
    print(f"  saved (rag)       : {doc.get('saved_path')}")
    print(f"  saved (ai_engine) : {doc.get('ai_engine_path')}")
    print(f"  baseline          : {doc.get('baseline_path')}")
    print(f"  unresolved        : {doc.get('unresolved')}")
    print(f"  txt_path          : {doc.get('txt_path')}")

    print(f"\n  --- Juniper set commands ({len(doc.get('set_commands') or [])}) ---")
    for c in doc.get("set_commands") or []:
        print(f"    {c}")

    handoff = doc.get("ai_engine_handoff") or {}
    print(f"\n=== AI ENGINE HANDOFF ===")
    if handoff.get("success"):
        print(f"  upload_id : {handoff.get('upload_id')}")
        print(f"  status    : {handoff.get('status')}")
        print("\n  Compliance summary:")
        print_compliance(handoff.get("compliance_report") or {})
    else:
        print(f"  NOT uploaded: {handoff.get('error')}")
        print("  Start Django with `python manage.py runserver` (port 8000) to enable auto-handoff.")

    print("\nDone. Copy of the normalized response:")
    print(f"  {doc.get('ai_engine_path')}  (also at {doc.get('saved_path')})")
    print(f"  Schema baseline: {doc.get('baseline_path')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Drive Cisco->Junos via RAG + ai_engine")
    p.add_argument("--config", help="path to the Cisco config file")
    p.add_argument("--source", choices=SOURCES, help="source vendor")
    p.add_argument("--target", choices=TARGETS, help="target vendor")
    p.add_argument("--check", action="store_true", help="health check only")
    args = p.parse_args()

    if args.check:
        check()
        return 0

    config_path = Path(args.config) if args.config else None
    if not config_path:
        default = Path(__file__).parent / "sample_config.txt"
        inp = input(f"Config file path [{default}]: ").strip()
        config_path = Path(inp) if inp else default

    source = args.source or input(f"Source vendor {SOURCES} [cisco]: ").strip() or "cisco"
    target = args.target or input(f"Target vendor {TARGETS} [junos]: ").strip() or "junos"

    return run(config_path, source, target)


if __name__ == "__main__":
    raise SystemExit(main())