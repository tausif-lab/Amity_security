"""Cached local embeddings (sentence-transformers, 384 dims).

Runs fully offline: the model is loaded from the local HF cache once it has
been downloaded. The HF_*_OFFLINE flags stop every load from pinging
huggingface.co (which hangs when there is no internet access).
"""

import os

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def _model():
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_texts(texts: list) -> list:
    """Return list of lists (embeddings)."""
    if not texts:
        return []
    return _model().encode(texts, normalize_embeddings=True).tolist()


def embed_text(text: str) -> list:
    return embed_texts([text])[0]