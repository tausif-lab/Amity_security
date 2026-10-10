# view_report.py — run as: python view_report.py <upload_id>
import sys

# The pass/fail marks are emoji, which the default Windows console codec
# (cp1252) cannot encode - printing them raised UnicodeEncodeError and killed
# the report halfway through. Force UTF-8 output so the report always renders.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import requests

upload_id = sys.argv[1]
resp = requests.get(f"http://127.0.0.1:8000/api/uploads/{upload_id}/")
data = resp.json()

print(f"\n{'='*60}")
print(f"UPLOAD REPORT — {data['id']}")
print(f"{'='*60}")
print(f"Vendor: {data['vendor']}")
print(f"Status: {data['status']}\n")

print("--- BASELINE JSON ---")
for key, value in data.get("baseline_json", {}).items():
    print(f"{key}: {value}")

report = data.get("compliance_report")
if report:
    s = report["summary"]
    print(f"\n--- COMPLIANCE SUMMARY ---")
    print(f"Total: {s['total']} | Passed: {s['passed']} | Failed: {s['failed']} | Critical/High fails: {s['critical_high']}")

    print(f"\n--- RULE RESULTS ---")
    for r in report["results"]:
        mark = "✅" if r["status"] == "Pass" else "❌"
        print(f"{mark} [{r['rule_id']}] {r['name']}")
        print(f"    Field: {r['field']} | Expected: {r['expected']} | Actual: {r['actual']}")
    print()