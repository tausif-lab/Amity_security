"""
core/services/normalization_cache.py

Layer 1 of the parser pipeline ("Cache Lookup -> Heuristics -> Mapping DB ->
RAG + LLM"). An exact-match cache in front of the LLM, so re-uploading a config
that was already normalized costs no inference at all.

What is cached: the raw model output for a given (vendor, model, schema, prompt,
config) tuple.

What is deliberately NOT cached: the normalized baseline that the compliance
engine reads. Deterministic post-processing (fact extraction, human-approved
mappings, schema sanitising) must re-run on every upload, otherwise a cache hit
would silently freeze the parser's behaviour and the human-in-the-loop loop
would stop having any effect on repeat uploads. Only the LLM call is skipped.
"""

import hashlib
import json
import logging

from django.db import IntegrityError

from core.models import NormalizationCache

logger = logging.getLogger(__name__)


def compute_key(vendor: str, model: str, schema: dict, prompt: str, config_text: str) -> str:
    """Stable content hash over everything that can change the answer.

    Including the schema and the prompt means a rule/schema/prompt edit rotates
    the cache automatically. There is no manual invalidation step to forget.
    """
    digest = hashlib.sha256()
    for part in (
        (vendor or "").strip().lower(),
        model or "",
        json.dumps(schema or {}, sort_keys=True, default=str),
        prompt or "",
        (config_text or "").strip(),
    ):
        digest.update(part.encode("utf-8", errors="ignore"))
        digest.update(b"\x00")
    return digest.hexdigest()


def get(config_hash: str) -> dict | None:
    """Return the cached model output, or None on a miss."""
    try:
        entry = NormalizationCache.objects.filter(config_hash=config_hash).first()
    except Exception as exc:                      # DB unavailable: never fail an upload
        logger.warning("Normalization cache read failed, treating as a miss: %s", exc)
        return None
    if entry is None:
        return None
    try:
        NormalizationCache.objects.filter(pk=entry.pk).update(
            hit_count=entry.hit_count + 1, last_used_at=_now())
    except Exception as exc:
        logger.debug("Could not bump cache hit counter: %s", exc)
    return entry.normalized_json


def _now():
    from django.utils import timezone
    return timezone.now()


def put(config_hash: str, vendor: str, model: str, normalized_json: dict) -> None:
    """Store a model output. A duplicate key means a concurrent upload won the
    race, which is harmless: the stored value is identical by construction."""
    if not isinstance(normalized_json, dict):
        return
    try:
        NormalizationCache.objects.update_or_create(
            config_hash=config_hash,
            defaults={"vendor": vendor or "unknown", "model": model or "",
                      "normalized_json": normalized_json},
        )
    except IntegrityError:
        pass
    except Exception as exc:                      # caching is an optimisation
        logger.warning("Could not write normalization cache entry: %s", exc)


def clear(vendor: str | None = None) -> int:
    """Drop cached normalizations. Used by the admin action and tests."""
    qs = NormalizationCache.objects.all()
    if vendor:
        qs = qs.filter(vendor__iexact=vendor)
    deleted, _ = qs.delete()
    return deleted


def stats() -> dict:
    """Hit-rate numbers, so the 'repeat uploads skip the LLM' claim is measured
    rather than asserted."""
    total = NormalizationCache.objects.count()
    hits = sum(entry.hit_count or 0 for entry in NormalizationCache.objects.all())
    lookups = total + hits
    return {
        "cached_configs": total,
        "cache_hits": hits,
        "cache_misses": total,
        "lookups": lookups,
        "hit_rate": round(hits / lookups, 4) if lookups else 0.0,
    }