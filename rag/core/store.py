"""pgvector storage: creates DB + table + index, saves chunks, hybrid search."""

import re

import psycopg2

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER, EMBEDDING_LENGTH, INDEX_TABLE, TOP_K
from core.embed import embed_text, embed_texts
from config import CHUNK_WORDS

DDL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {INDEX_TABLE} (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    section     TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector({EMBEDDING_LENGTH}) NOT NULL
)
"""

DDL_INDEX = f"""
CREATE INDEX IF NOT EXISTS {INDEX_TABLE}_embed_idx
ON {INDEX_TABLE} USING hnsw (embedding vector_cosine_ops)
"""


def connect():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME,
    )
    return conn


def ensure_database():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{DB_NAME}"')
    conn.close()

    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            dbname=DB_NAME)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute(DDL_TABLE)
    cur.execute(DDL_INDEX)
    conn.close()


def clear_chunks():
    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {INDEX_TABLE}")
    conn.close()


def save_chunks(chunks: list):
    """chunks: list of (source, section, content). Embeds and bulk-inserts."""
    if not chunks:
        return 0
    rows = chunks
    texts = [c[2] for c in rows]
    vectors = embed_texts(texts)
    conn = connect()
    cur = conn.cursor()
    sql = f"INSERT INTO {INDEX_TABLE} (source, section, content, embedding) VALUES (%s, %s, %s, %s)"
    payload = [(src, sec, content, vec)
               for (src, sec, content), vec in zip(rows, vectors)]
    cur.executemany(sql, payload)
    conn.commit()
    conn.close()
    return len(payload)


def search(query: str, top_k: int = None, min_score: float = 0.25) -> list:
    """Return list of dicts {source, section, content, score} ordered by relevance."""
    top_k = top_k or TOP_K
    qvec = embed_text(query)
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        f"SELECT source, section, content, 1 - (embedding <=> %s::vector) AS score "
        f"FROM {INDEX_TABLE} WHERE embedding IS NOT NULL "
        f"ORDER BY embedding <=> %s::vector LIMIT %s",
        (str(qvec), str(qvec), top_k),
    )
    rows = cur.fetchall()
    conn.close()
    results = []
    for source, section, content, score in rows:
        # keyword bump for exact command mentions
        score = float(score)
        if contains_any(content, query):
            score = min(1.0, score + 0.08)
        if score >= min_score:
            results.append({"source": source, "section": section,
                            "content": content, "score": round(score, 4)})
    return results


def contains_any(content: str, query: str) -> bool:
    terms = re.findall(r"[a-z][a-z0-9-]{2,}", query.lower())
    return any(t in content.lower() for t in terms)


def count_chunks() -> int:
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {INDEX_TABLE}")
    n = cur.fetchone()[0]
    conn.close()
    return n