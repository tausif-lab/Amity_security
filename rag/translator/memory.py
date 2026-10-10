"""
translator/memory.py
Persistent memory for the translator, stored in the same `rag_chatbot`
PostgreSQL database used by core/store.py (direct psycopg2, no ORM):

  * translator_mem   - verified source->target mappings (translation memory)
  * translation_runs - audit trail of every translate_config() call

Translation memory is consulted BEFORE the LLM fallback so previously
verified translations win over a fresh model guess, and verified runs
bump confidence.
"""

import json
from typing import Optional

import psycopg2

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

DDL = """
CREATE TABLE IF NOT EXISTS translator_mem (
    id          BIGSERIAL PRIMARY KEY,
    source_line TEXT NOT NULL,
    mapping     TEXT NOT NULL,
    target      TEXT NOT NULL,
    confidence  DOUBLE PRECISION NOT NULL DEFAULT 0.9,
    run_ids     TEXT[] NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS translator_mem_source_idx
    ON translator_mem (lower(source_line));

CREATE TABLE IF NOT EXISTS translation_runs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    juniper     TEXT NOT NULL,
    overall     DOUBLE PRECISION NOT NULL,
    by_category JSONB NOT NULL DEFAULT '{}',
    unresolved  JSONB NOT NULL DEFAULT '[]',
    warnings    JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_memory_tables():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER,
                            password=DB_PASSWORD, dbname=DB_NAME)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    conn.close()


def connect():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER,
                            password=DB_PASSWORD, dbname=DB_NAME)


def save_mapping(source_line: str, mapping: str, target: str,
                 confidence: float = 0.9, run_id: Optional[int] = None) -> None:
    """Upsert one verified mapping into translation memory."""
    ensure_memory_tables()
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO translator_mem (source_line, mapping, target, confidence, run_ids)
           VALUES (%s, %s, %s, %s, ARRAY[%s]::TEXT[])
           ON CONFLICT DO NOTHING""",
        (source_line, mapping, target, confidence, str(run_id) if run_id else ""),
    )
    conn.commit()
    conn.close()


def lookup_mapping(source_line: str) -> Optional[dict]:
    ensure_memory_tables()
    try:
        conn = connect()
        cur = conn.cursor()
        cur.execute(
            """SELECT source_line, mapping, target, confidence
               FROM translator_mem WHERE lower(source_line) = lower(%s)
               ORDER BY confidence DESC LIMIT 1""",
            (source_line,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {"source_line": row[0], "mapping": row[1], "target": row[2],
                    "confidence": float(row[3])}
    except Exception:
        return None
    return None


def record_run(source: str, juniper: str, overall: float, by_category: dict,
               unresolved: list, warnings: list) -> int:
    ensure_memory_tables()
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO translation_runs (source, juniper, overall, by_category, unresolved, warnings)
           VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb) RETURNING id""",
        (source, juniper, overall, json.dumps(by_category), json.dumps(unresolved),
         json.dumps(warnings)),
    )
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return int(run_id)