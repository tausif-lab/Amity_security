"""Vector-backed human-in-the-loop memory for configuration normalization."""
import os
from functools import lru_cache

from pgvector.django import CosineDistance

from core.models import NormalizationMemory

MEMORY_MATCH_THRESHOLD = 0.88
LOW_CONFIDENCE_THRESHOLD = 0.75


@lru_cache(maxsize=1)
def _embedding_model():
    # Keep the existing local/offline model behaviour; no configuration is sent away.
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed_command(command: str) -> list:
    return _embedding_model().encode(command, normalize_embeddings=True).tolist()


def config_commands(config_text: str) -> list[str]:
    """Keep meaningful config lines; comments and separators cannot become memories."""
    return [line.strip() for line in config_text.splitlines()
            if line.strip() and not line.lstrip().startswith(("!", "#"))]


def find_related(command: str, vendor: str, include_pending: bool = True) -> dict | None:
    """Return the closest semantic memory, but only approved entries are authoritative."""
    vector = embed_command(command)
    states = ["approved", "pending"] if include_pending else ["approved"]
    entry = (NormalizationMemory.objects.filter(vendor__iexact=vendor, status__in=states)
             .annotate(distance=CosineDistance("embedding", vector))
             .order_by("distance").first())
    if not entry:
        return None
    score = 1.0 - float(entry.distance)
    return {"id": entry.id, "command": entry.command, "similarity": round(score, 4),
            "status": entry.status, "normalized_path": entry.normalized_path,
            "normalized_value": entry.normalized_value, "description": entry.description,
            "threshold": entry.similarity_threshold}


def lookup_config_memories(config_text: str, vendor: str) -> list[dict]:
    matches = []
    for command in config_commands(config_text):
        related = find_related(command, vendor)
        if related and related["similarity"] >= related["threshold"]:
            related["input_command"] = command
            matches.append(related)
    return matches


def prompt_context(matches: list[dict]) -> str:
    if not matches:
        return "No prior command memories were found."
    lines = []
    for match in matches:
        if match["status"] == "approved" and match["normalized_path"]:
            lines.append(f"Approved mapping ({match['similarity']:.2f}): {match['input_command']!r} -> {match['normalized_path']} = {match['normalized_value']!r}")
        elif match["description"]:
            lines.append(f"Human/previous-review guidance ({match['similarity']:.2f}) for {match['input_command']!r}: {match['description']}")
    return "\n".join(lines) or "No usable prior command memories were found."


def store_pending(command: str, vendor: str, confidence: float | None, description: str = ""):
    """Save uncertainty as non-authoritative evidence for later human review."""
    existing = find_related(command, vendor)
    if existing and existing["similarity"] >= 0.98:
        return existing["id"]
    entry = NormalizationMemory.objects.create(
        vendor=vendor, command=command, embedding=embed_command(command),
        description=description, llm_confidence=confidence, status="pending",
    )
    return entry.id


def apply_approved_mappings(normalized: dict, matches: list[dict]) -> dict:
    """Apply only high-similarity approved mappings; pending memory is never applied."""
    for match in matches:
        if match["status"] != "approved" or not match["normalized_path"]:
            continue
        destination = normalized
        parts = match["normalized_path"].split(".")
        for part in parts[:-1]:
            destination = destination.setdefault(part, {})
        destination[parts[-1]] = match["normalized_value"]
    return normalized
