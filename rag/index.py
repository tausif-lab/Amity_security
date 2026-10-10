"""One-shot indexer: read knowledge_base (PDFs, DOCX, links) into pgvector.

Usage:
    python index.py            # incremental (skips nothing; re-embeds every source)
    python index.py --wipe     # clear table, then index everything
"""

import sys
from pathlib import Path

from config import KNOWLEDGE_BASE, LINKS_FILE
from core.chunker import chunk_sections
from core.extract import extract_file, extract_http
from core.store import clear_chunks, ensure_database, save_chunks, count_chunks


def unique_links() -> list:
    if not Path(LINKS_FILE).exists():
        return []
    seen, urls = set(), []
    for line in Path(LINKS_FILE).read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def walk_files() -> list:
    files = []
    for ext in ("*.pdf", "*.docx", "*.txt", "*.md", "*.html", "*.htm"):
        files.extend(sorted(KNOWLEDGE_BASE.rglob(ext)))
    print(f"This are the files {files}")
    return files


def index_all() -> int:
    ensure_database()
    total = 0
    for path in walk_files():
        try:
            text = extract_file(path)
        except Exception as e:
            print(f"  skip {path.name}: {e}")
            continue
        chunks = chunk_sections(text)
        rows = [(str(path.resolve()), c["section"], c["content"]) for c in chunks]
        if rows:
            n = save_chunks(rows)
            total += n
            print(f"  {path.name:<40} {n:>4} chunks")
    for url in unique_links():
        host = Path(url.split("/")[-1] or url)
        try:
            text = extract_http(url)
        except Exception as e:
            print(f"  skip {url}: {e}")
            continue
        chunks = chunk_sections(text)
        rows = [(url, c["section"], c["content"]) for c in chunks]
        if rows:
            n = save_chunks(rows)
            total += n
            print(f"  {str(host)[:38]:<40} {n:>4} chunks")
    return total


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        ensure_database()
        clear_chunks()
        print("table wiped.")
    total = index_all()
    print(f"\nTotal indexed: {total} chunks -> {count_chunks()} in postgres ({'rag_chatbot'}).")