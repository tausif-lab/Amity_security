"""
rag/main.py
FastAPI entry point for the rag translator.

Run from the rag/ directory (flat imports need rag/ on sys.path):
    python main.py
or:
    uvicorn main:app --host 127.0.0.1 --port 8001
"""

import sys
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router

app = FastAPI(
    title="Cisco/Junos RAG Translator API",
    version="1.0.0",
    description=(
        "Deterministic Cisco IOS -> Junos translator with RAG evidence, "
        "translation memory, LLM fallback for unmapped lines, and "
        "normalised_{vendor}.json output files."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"service": "rag-translator-api", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)