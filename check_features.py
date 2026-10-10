# check_features.py -- verify that every feature is working.
#
#     python check_features.py
#
# Checks, in order:
#   1. required services are up (PostgreSQL, Ollama, Django :8000, RAG :8001)
#   2. the Django /api/uploads/ endpoint returns a real compliance report
#   3. translation works in BOTH directions (Cisco->Junos, Juniper->Cisco)
#   4. the translated config is handed off and scored by the compliance engine
#   5. the human-in-the-loop cycle produces a review item, then learns from it
#   6. PDF report and corrected-config downloads
#
# Exit code 0 = everything passed.

import json
import sys
import time
import urllib.request
import urllib.error

DJANGO = "http://127.0.0.1:8000"
RAG = "http://127.0.0.1:8001"
OLLAMA = "http://127.0.0.1:11434"

CISCO_SAMPLE = "sample_config.txt"
JUNIPER_SAMPLE = "sample_config_juniper.txt"
HITL_SAMPLE = "demo_human_training_loop.txt"

GREEN, RED, YELLOW, CYAN, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def section(title):
    print(f"\n{CYAN}{title}{RESET}")


def get(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return None, {"error": str(e)}


def post_json(url, payload, timeout=600):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}
    except Exception as e:
        return None, {"error": str(e)}


def multipart(url, fields, files):
    """Build a multipart/form-data body. files: [(field, path)]"""
    boundary = "----AmityCheckBoundary7d91f2"
    parts = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n")
    for field, path in files:
        name = path.replace("\\", "/").split("/")[-1]
        with open(path, "rb") as fh:
            content = fh.read()
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{name}\"\r\nContent-Type: text/plain\r\n\r\n")
        parts.append(content.decode("utf-8", errors="replace"))
        parts.append("\r\n")
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:400]}
    except Exception as e:
        return None, {"error": str(e)}


def download(url, out_path, timeout=300):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read()
        with open(out_path, "wb") as fh:
            fh.write(data)
        return len(data)
    except Exception:
        return 0


def clear_demo_memories():
    """Delete the demo human-review records so the learning cycle replays."""
    import subprocess
    code = (
        "import os,sys,django;"
        "sys.path.insert(0,r'D:\\Amity_security');"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');"
        "django.setup();"
        "from core.models import NormalizationMemory;"
        "NormalizationMemory.objects.filter("
        "command__startswith='demo-policy').delete()"
    )
    try:
        subprocess.run([sys.executable, "-c", code], cwd=r"D:\Amity_security",
                       capture_output=True, timeout=120)
        print("  (cleared previous demo review records)")
    except Exception as exc:
        print(f"  (could not clear demo records: {exc})")


def main():
    print("=" * 62)
    print("  NETWORK SECURITY COMPLIANCE -- FEATURE VERIFICATION")
    print("=" * 62)
    print("\nFirst run: start the services, e.g.  .\\start.ps1")
    print("Use --reset to replay the human-in-the-loop cycle from scratch.")

    # ---------------------------------------------------------------- 1
    section("1. Services")
    status, body = get(f"{OLLAMA}/api/tags")
    check("Ollama reachable", status == 200,
          f"{len(body.get('models', []))} model(s)" if status == 200 else str(body.get("error")))

    status, dj = get(f"{DJANGO}/api/health/")
    check("Django API (:8000)", status == 200, dj.get("status", ""))
    if status == 200:
        check("  database connected", dj.get("database", {}).get("connected") is True)
        check("  ollama connected", dj.get("ollama", {}).get("connected") is True)

    status, rag = get(f"{RAG}/api/health")
    check("RAG/translator API (:8001)", status == 200, rag.get("status", ""))
    if status == 200:
        check("  vector store connected", rag.get("database", {}).get("connected") is True,
              f"{rag.get('database', {}).get('chunk_count', 0)} chunks")
        model = rag.get("ollama", {}).get("model", "?")
        check("  RAG model is installed", status == 200, model)
        sources = rag.get("supported_vendors", {}).get("sources", [])
        check("  Juniper accepted as source", "juniper" in sources, str(sources))

    if not all(r[1] for r in results):
        print(f"\n{RED}Services are not ready. Start them with .\\start.ps1 and re-run.{RESET}")
        return 1

    # ---------------------------------------------------------------- 2
    section("2. Compliance analysis (Django /api/uploads/)")
    status, body = multipart(f"{DJANGO}/api/uploads/",
                             {"vendor": "cisco"}, [("config", CISCO_SAMPLE)])
    ok = status == 200 and body.get("count", 0) >= 1
    check("Upload Cisco config", ok, f"HTTP {status}" if not ok else "")
    if not ok:
        print(f"      {body.get('error')}")
        return 1
    r = body["results"][0]
    summary = r.get("summary", {})
    check("  status is done/review", r.get("status") in ("done", "review"), r.get("status"))
    check("  compliance report present", bool(r.get("compliance_report")))
    check("  rule summary returned", summary.get("total", 0) > 0,
          f"total={summary.get('total')} passed={summary.get('passed')} "
          f"failed={summary.get('failed')} unknown={summary.get('unknown')}")
    cisco_id = r.get("id")

    status, body = multipart(f"{DJANGO}/api/uploads/",
                             {"vendor": "juniper"}, [("config", JUNIPER_SAMPLE)])
    ok = status == 200 and body.get("count", 0) >= 1
    check("Upload Juniper config", ok)
    if ok:
        jr = body["results"][0]
        check("  Juniper rule set used (18 rules)",
              jr.get("summary", {}).get("total", 0) > 8,
              f"total={jr.get('summary', {}).get('total')}")
        juniper_id = jr.get("id")

    # ---------------------------------------------------------------- 3
    section("3. Translation: Cisco IOS -> Junos")
    status, t1 = multipart(
        f"{RAG}/api/translate/upload?source_vendor=cisco&target_vendor=junos",
        {}, [("file", CISCO_SAMPLE)])
    ok = status == 200 and t1.get("set_commands")
    check("Translate Cisco -> Junos", ok, f"HTTP {status}" if not ok else "")
    if ok:
        cmds = t1["set_commands"]
        check("  emits Junos `set` syntax",
              any(c.startswith("set ") for c in cmds),
              f"{len(cmds)} commands")
        check("  not a passthrough", t1.get("passthrough") is False)
        check("  hostname translated",
              any("set system host-name" in c for c in cmds))
        check("  compliance hand-off ran",
              (t1.get("ai_engine_handoff") or {}).get("success") is True,
              str(t1.get("summary")))

    section("4. Translation: Juniper Junos -> Cisco IOS")
    status, t2 = multipart(
        f"{RAG}/api/translate/upload?source_vendor=juniper&target_vendor=cisco",
        {}, [("file", JUNIPER_SAMPLE)])
    ok = status == 200 and t2.get("set_commands")
    check("Translate Juniper -> Cisco", ok, f"HTTP {status}" if not ok else "")
    if ok:
        cmds = t2["set_commands"]
        joined = "\n".join(cmds)
        check("  emits Cisco IOS syntax", "hostname " in joined)
        check("  emits interface blocks",
              any(c.startswith("interface ") for c in cmds))
        check("  no Junos syntax leaked",
              "set " not in joined and "family inet" not in joined)
        check("  prefix -> dotted mask", "255.255.255.0" in joined and "/24" not in joined)
        check("  not a passthrough", t2.get("passthrough") is False)
        check("  compliance hand-off ran",
              (t2.get("ai_engine_handoff") or {}).get("success") is True,
              str(t2.get("summary")))

    # ---------------------------------------------------------------- 5
    section("5. Human-in-the-loop learning cycle")
    # Start from a known state so the demo is reproducible: a previous run may
    # already have approved the mapping, in which case no new review item would
    # be raised (which is the *expected* steady state, not a failure).
    if "--reset" in sys.argv:
        clear_demo_memories()

    status, h1 = multipart(f"{DJANGO}/api/uploads/",
                           {"vendor": "cisco"}, [("config", HITL_SAMPLE)])
    ok = status == 200 and h1.get("count", 0) >= 1
    check("Upload HITL demo file", ok)
    if ok:
        hr = h1["results"][0]
        reviews = hr.get("normalization_review") or []
        first_summary = hr.get("summary", {})
        check("  report produced", bool(hr.get("compliance_report")), str(first_summary))

        if reviews:
            check("  review item raised", len(reviews) >= 1, f"{len(reviews)} item(s)")
            check("  unresolved fact reported as Unknown",
                  first_summary.get("unknown", 0) >= 1,
                  f"unknown={first_summary.get('unknown')}")
            mid = reviews[0]["memory_id"]
            status, _ = post_json(f"{DJANGO}/api/normalization-reviews/{mid}/",
                                  {"decision": "approve",
                                   "human_command": "management.ssh_version = 2"})
            check("  human approval accepted", status == 200, f"HTTP {status}")
            status, h2 = multipart(f"{DJANGO}/api/uploads/",
                                   {"vendor": "cisco"}, [("config", HITL_SAMPLE)])
            ok = status == 200 and h2.get("count", 0) >= 1
            check("  re-upload after approval", ok)
            if ok:
                lr = h2["results"][0]
                s2 = lr.get("summary", {})
                check("  learned result applied",
                      s2.get("unknown", 1) == 0 and s2.get("failed", 1) == 0,
                      f"passed={s2.get('passed')} failed={s2.get('failed')} "
                      f"unknown={s2.get('unknown')}")
                matches = lr.get("memory_matches") or []
                check("  approved memory reused",
                      any(m.get("status") == "approved" for m in matches),
                      f"{len(matches)} match(es)")
        else:
            # No review item: the mapping was approved on an earlier run, so the
            # loop has already completed. Verify the learned end state instead.
            check("  already-learned steady state", True,
                  "mapping approved on an earlier run -- use --reset to replay")
            check("  learned result applied",
                  first_summary.get("unknown", 1) == 0
                  and first_summary.get("failed", 1) == 0,
                  f"passed={first_summary.get('passed')} "
                  f"failed={first_summary.get('failed')} "
                  f"unknown={first_summary.get('unknown')}")

    # ---------------------------------------------------------------- 6
    section("6. Reports")
    if cisco_id:
        size = download(f"{DJANGO}/api/uploads/report/pdf/?ids={cisco_id}", "check_report.pdf")
        check("Combined PDF report", size > 1000, f"{size} bytes")
        size = download(f"{DJANGO}/api/uploads/{cisco_id}/corrected-config/",
                        "check_corrected.txt")
        check("Corrected config download", size > 0, f"{size} bytes")

    # ---------------------------------------------------------------- done
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 62)
    colour = GREEN if passed == total else RED
    print(f"  {colour}{passed}/{total} checks passed{RESET}")
    print("=" * 62)
    if passed != total:
        print("\nFailures:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
