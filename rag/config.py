"""Central configuration for the simple RAG chatbot."""

import os
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
print(RAG_DIR)
KNOWLEDGE_BASE = RAG_DIR / "knowledge_base"
print(KNOWLEDGE_BASE)
LINKS_FILE = KNOWLEDGE_BASE / "links.txt"
print(LINKS_FILE)

# Database (PostgreSQL 18 + pgvector, local)
DB_HOST = os.environ.get("RAG_DB_HOST", "localhost")
DB_PORT = os.environ.get("RAG_DB_PORT", "5432")
DB_USER = os.environ.get("RAG_DB_USER", "postgres")
DB_PASSWORD = os.environ.get("RAG_DB_PASSWORD", "Prinshu@135")
DB_NAME = os.environ.get("RAG_DB_NAME", "rag_chatbot")

DATABASE_URI = f"postgresql+psycopg2://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Models
# all-MiniLM-L6-v2 (384 dims) is the ONLY model cached locally on this machine,
# so the RAG works fully offline with no downloads. Swap EMBEDDING_MODEL for a
# newer/bigger sentence-transformers model (e.g. all-MiniLM-L12-v2, bge-small,
# bge-m3) once internet is available and it has been pulled into the HF cache.
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_LENGTH = 384

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M")
OLLAMA_TEMPERATURE = 0.1

# Retrieval / chunking
TOP_K = 5
CHUNK_WORDS = 400
CHUNK_OVERLAP = 40
MAX_VERIFY_ROUNDS = 3

INDEX_TABLE = "chat_chunks"

# ai_engine integration (Django app at the project root)
AI_ENGINE_URL = os.environ.get("AI_ENGINE_URL", "http://127.0.0.1:8000")
AI_ENGINE_DIR = RAG_DIR.parent / "ai_engine"
RULES_PATH = AI_ENGINE_DIR.parent / "compliance" / "data" / "cis_rules.json"
JUNIPER_RULES_PATH = AI_ENGINE_DIR.parent / "compliance" / "data" / "cis_juniper_rules.json"