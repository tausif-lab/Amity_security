"""
run_tests.py — run every test suite in this repository with one command.

    python run_tests.py            # everything
    python run_tests.py django     # Django app tests only
    python run_tests.py translator # RAG translator tests only

The translator suite runs standalone (it has no Django dependency), so it is
executed in a separate process with rag/ on sys.path.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAG = ROOT / "rag"


def _run(label: str, command: list, cwd: Path) -> bool:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(command, cwd=str(cwd))
    ok = result.returncode == 0
    print(f"--- {label}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()

    if which in ("all", "django"):
        django_ok = _run("Django app tests", [sys.executable, "manage.py", "test",
                                              "--noinput"], ROOT)
    else:
        django_ok = True

    if which in ("all", "translator", "rag"):
        translator_ok = _run("RAG translator tests",
                             [sys.executable, "-m", "unittest", "discover",
                              "-s", "translator", "-p", "tests.py"], RAG)
    else:
        translator_ok = True

    print("\n" + "=" * 46)
    if django_ok and translator_ok:
        print("ALL SUITES PASSED")
        return 0
    print("SOME SUITES FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
