"""Vector-backed human-in-the-loop memory for configuration normalization."""
import logging
import os
from functools import lru_cache

from django.db import transaction
from pgvector.django import CosineDistance

from core.models import NormalizationMemory

logger = logging.getLogger(__name__)

MEMORY_MATCH_THRESHOLD = 0.88
LOW_CONFIDENCE_THRESHOLD = 0.75


@lru_cache(maxsize=1)
def _embedding_model():
    # Keep the existing local/offline model behaviour; no configuration is sent away.
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def _embedding_model_or_none():
    """Load the embedding model, or return None if it is unavailable.

    The human-in-the-loop memory is an *enhancement*: if the embedding model
    cannot be loaded (not cached, offline, out of memory) the upload must still
    normalize and produce a compliance report. Degrading to "no memories" keeps
    the pipeline usable and only turns off learned reuse.
    """
    try:
        return _embedding_model()
    except Exception as exc:
        logger.warning(
            "Embedding model unavailable, continuing without command memory: %s", exc)
        return None


def embed_command(command: str) -> list:
    return _embedding_model().encode(command, normalize_embeddings=True).tolist()


def embed_commands(commands: list) -> list:
    """Embed many commands in one model call instead of one call per line.

    SentenceTransformer caches per process, but each `.encode()` still pays
    tokenization + forward-pass overhead. Batching turns N round trips into 1,
    which is what makes large configs practical. Returns None when the model
    is unavailable, so callers can skip the lookup entirely.
    """
    model = _embedding_model_or_none()
    if model is None or not commands:
        return None
    vectors = model.encode(commands, normalize_embeddings=True,
                           batch_size=32, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def config_commands(config_text: str) -> list[str]:
    """Keep meaningful config lines; comments and separators cannot become memories."""
    return [line.strip() for line in config_text.splitlines()
            if line.strip() and not line.lstrip().startswith(("!", "#"))]


def find_related(command: str, vendor: str, include_pending: bool = True) -> dict | None:
    """Return the closest semantic memory, but only approved entries are authoritative."""
    return _find_related_batch([command], vendor, include_pending)[0]


def _find_related_batch(commands: list, vendor: str, include_pending: bool = True) -> list:
    """Batch nearest-neighbour lookup: one embedding pass, one query per command."""
    if not commands:
        return []
    vectors = embed_commands(commands)
    if vectors is None:
        return [None] * len(commands)
    states = ["approved", "pending"] if include_pending else ["approved"]
    results = []
    with transaction.atomic():
        for command, vector in zip(commands, vectors):
            entry = (NormalizationMemory.objects.filter(vendor__iexact=vendor, status__in=states)
                     .annotate(distance=CosineDistance("embedding", vector))
                     .order_by("distance").first())
            if not entry:
                results.append(None)
                continue
            score = 1.0 - float(entry.distance)
            results.append({
                "id": entry.id, "command": entry.command, "similarity": round(score, 4),
                "status": entry.status, "normalized_path": entry.normalized_path,
                "normalized_value": entry.normalized_value, "description": entry.description,
                "threshold": entry.similarity_threshold,
            })
    return results


def lookup_config_memories(config_text: str, vendor: str) -> list[dict]:
    commands = config_commands(config_text)
    matches = []
    for command, related in zip(commands, _find_related_batch(commands, vendor)):
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

    vector = embed_commands([command])
    if vector is None:
        # No embedding model: keep the review item visible to the human even
        # though it cannot take part in similarity search yet.
        logger.info("Storing review without embedding (model unavailable): %s", command)
        return NormalizationMemory.objects.create(
            vendor=vendor, command=command, embedding=[0.0] * 384,
            description=description, llm_confidence=confidence, status="pending",
        ).id

    entry = NormalizationMemory.objects.create(
        vendor=vendor, command=command, embedding=vector[0],
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
