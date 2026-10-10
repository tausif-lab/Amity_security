"""Splits raw text into overlapping chunks keyed by a short section label."""

import re

from config import CHUNK_OVERLAP, CHUNK_WORDS


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.match(r"^(#{1,6}\s+)", s):
        return True
    if re.match(r"^\d+(\.\d+)*[\.\)]\s*", s):
        return True
    # short, title-like, no trailing period
    return len(s.split()) <= 8 and not s.endswith(".")


def chunk_sections(text: str, max_words: int = None, overlap_words: int = None) -> list:
    max_words = max_words or CHUNK_WORDS
    overlap_words = overlap_words if overlap_words is not None else CHUNK_OVERLAP

    sections = []
    current = {"section": "", "lines": []}
    for line in text.splitlines():
        if _is_heading(line):
            if current["lines"]:
                sections.append(current)
            current = {"section": re.sub(r"^#{1,6}\s*", "", line.strip()), "lines": []}
        else:
            current["lines"].append(line)
    if current["lines"]:
        sections.append(current)

    chunks = []
    for sec in sections:
        words = " ".join(sec["lines"]).split()
        if not words:
            continue
        for i in range(0, len(words), max_words - overlap_words):
            piece = words[i:i + max_words]
            if not piece:
                break
            chunks.append({
                "section": sec["section"],
                "content": " ".join(piece),
            })
    return chunks