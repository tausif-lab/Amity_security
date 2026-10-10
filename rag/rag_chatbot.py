"""Simple RAG chatbot over knowledge_base (Cisco / Juniper).

Interactive:
    python rag_chatbot.py
One-shot (handy for scripting/tests):
    python rag_chatbot.py "what is the Junos equivalent of ip ssh timeout?"

Modes:
  - questions  -> retrieves relevant chunks, answers via Ollama (with sources)
  - config     -> Cisco config/commands get translated to Junos set commands
  - commands   -> :reindex | :wipe | :model | :sources | :quit
"""

import sys

from core.builder import answer_prompt, answer_system, call_ollama
from core.store import ensure_database, search

HELP = """\
  ask questions about Cisco/Junos configuration
  paste a Cisco config block -> receive Junos set commands
  :reindex          re-read knowledge_base into the vector store
  :wipe             clear the vector store then reindex
  :model            show current Ollama model
  :sources on|off   toggle source citations
  :quit
"""


def looks_like_config(text: str) -> bool:
    first = text.strip().splitlines()
    if not first:
        return False
    starter = first[0].strip().lower()
    return starter.startswith(("! ", "hostname ", "interface ", "ip ssh", "snmp-server",
                               "ntp server", "username ", "enable secret", "aaa ",
                               "logging ", "line vty", "crypto ", "no cdp"))


def translate(text: str, show_sources: bool) -> str:
    """Deterministic translator pipeline (parser -> IR -> planner -> validator)
    with RAG evidence + LLM fallback for unmapped lines."""
    from translator import translate_config
    res = translate_config(text, use_llm=True, with_rag=True, persist=False)
    if show_sources and res["unresolved"]:
        print("\n[unresolved / needs review]")
        for u in res["unresolved"]:
            print(f"  -> {u}")
    lines = []
    for l in res["set_commands"]:
        lines.append(l)
    return "\n".join(lines)


def clean_set_lines(raw: str) -> list:
    """Keep only Junos commands + UNMAPPED markers from an LLM response."""
    out = []
    for line in raw.splitlines():
        s = line.strip().lstrip("-*` ").strip()
        if not s:
            continue
        if s.startswith("```"):
            continue
        if s == "```":
            continue
        if s.lower().startswith(("set ", "delete ", "edit ", "deactivate ", "activate ",
                                 "# unmapped", "# no-op")):
            out.append(s)
    return out


def answer(question: str, show_sources: bool) -> str:
    evidence = search(question)
    if show_sources and evidence:
        print("\n[sources]")
        for r in evidence[:4]:
            print(f"  -> {r['source']}  (score {r['score']:.2f})")
    return call_ollama(answer_system(), answer_prompt(question, evidence))


def run_repl():
    ensure_database()
    print("Cisco/Junos RAG chatbot  (Postgres pgvector + Ollama)")
    print("  :help for commands, :quit to exit\n")
    show_sources = True
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return
        if not text:
            continue
        if text in ("/bye", ":quit"):
            print("bye.")
            return
        if text == ":help":
            print(HELP)
            continue
        if text in (":reindex", ":wipe"):
            run_indexer(wipe=(text == ":wipe"))
            continue
        if text == ":model":
            from config import OLLAMA_MODEL
            print(f"model: {OLLAMA_MODEL}  (set env RAG_OLLAMA_MODEL to override)")
            continue
        if text in (":sources on", ":sources off"):
            show_sources = text.endswith("on")
            print(f"sources {'on' if show_sources else 'off'}")
            continue
        if looks_like_config(text):
            print("\n[translating to Junos]")
            try:
                print(translate(text, show_sources) + "\n")
            except Exception as e:
                print(f"translate error: {e}\n")
        else:
            try:
                print("\n" + answer(text, show_sources) + "\n")
            except Exception as e:
                print(f"answer error: {e}\n")


def run_indexer(wipe: bool = False):
    from core.store import ensure_database, clear_chunks
    import index as index_mod
    ensure_database()
    if wipe:
        clear_chunks()
        print("table wiped.")
    total = index_mod.index_all()
    print(f"indexed {total} chunks.\n")


def main() -> int:
    if len(sys.argv) > 1 and not sys.argv[1].startswith(":"):
        ensure_database()
        q = " ".join(sys.argv[1:])
        if looks_like_config(q):
            print(translate(q, show_sources=True))
        else:
            print(answer(q, show_sources=True))
        return 0
    run_repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())