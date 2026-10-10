"""
rag/api/routes.py
FastAPI routes exposing the translator + chatbot to the frontend.

Vendor flow (user is asked first):
    GET  /api/vendors                 -> supported source->target pairs
    POST /api/translate               -> JSON body {source_vendor, target_vendor, config_text}
    POST /api/translate/upload        -> multipart (source_vendor, target_vendor, file)
    GET  /api/health                  -> DB + Ollama status
    POST /api/ask                     -> RAG question answering
    POST /api/reindex                 -> rebuild knowledge base index
"""

import json
import sys
from pathlib import Path

import requests
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .normalizer import (
    ai_engine_baseline_filepath,
    ai_engine_filepath,
    build_normalized_response,
    source_txt_filepath,
    ir_to_baseline,
    target_filepath,
)
from .schemas import AskRequest, TranslateRequest, VendorPair

# The RAG service is started from inside rag/ (flat imports), so translator/
# sits on sys.path. Import the parsers here so a passthrough translation can
# still build a correct vendor-neutral IR.
RAG_DIR = Path(__file__).resolve().parents[1]
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

from translator import cisco_parser  # noqa: E402
from translator import juniper_parser  # noqa: E402
from translator import ir as cisco_ir  # noqa: E402
from translator import juniper_ir  # noqa: E402

router = APIRouter(prefix="/api")

# Both directions are first-class: the deterministic pipeline is bidirectional
# (Cisco IOS <-> Juniper Junos) because both vendors normalize into the same
# vendor-neutral IR. Same-vendor requests are an identity passthrough.
CISCO_ALIASES = {"cisco", "ios"}
JUNIPER_ALIASES = {"juniper", "junos"}
SUPPORTED_SOURCES = CISCO_ALIASES | JUNIPER_ALIASES
CANONICAL_TARGETS = {"junos", "juniper", "cisco", "ios"}
VENDOR_PAIRS = [
    VendorPair(source="cisco", target="junos"),
    VendorPair(source="juniper", target="cisco"),
    VendorPair(source="cisco", target="cisco"),
    VendorPair(source="juniper", target="juniper"),
]


def _canonical(vendor: str) -> str:
    """Collapse vendor aliases so 'junos'/'juniper' and 'cisco'/'ios' compare equal."""
    value = (vendor or "").strip().lower()
    if value in JUNIPER_ALIASES:
        return "junos"
    if value in CISCO_ALIASES:
        return "cisco"
    return value


def _validate_vendors(source_vendor: str, target_vendor: str):
    source = (source_vendor or "").strip().lower()
    target = (target_vendor or "").strip().lower()
    if source not in SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source vendor '{source_vendor}'. "
                   f"Supported sources: {sorted(SUPPORTED_SOURCES)}",
        )
    if target not in CANONICAL_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target vendor '{target_vendor}'. "
                   f"Supported targets: {sorted(CANONICAL_TARGETS)}",
        )
    return source, target


def _handoff_to_ai_engine(config_text: str, target_vendor: str) -> dict:
    """POST the translated config into Django's upload pipeline (LLM normalize +
    validate + compliance). Best-effort: never raises."""
    from config import AI_ENGINE_URL

    url = f"{AI_ENGINE_URL}/api/uploads/"
    try:
        filename = f"{target_vendor}_translated.txt"
        files = {"config": (filename, config_text.encode("utf-8"))}
        data = {"vendor": target_vendor}
        resp = requests.post(url, files=files, data=data, timeout=300)
        if resp.ok:
            payload = resp.json()
            # /api/uploads/ returns {"count": n, "results": [...]}, with one
            # entry per uploaded file. Unwrap the first result so callers get
            # the same flat shape regardless of which endpoint produced it.
            results = payload.get("results")
            if isinstance(results, list) and results:
                payload = results[0]
            elif isinstance(results, list):
                return {"success": False,
                        "error": "Django accepted the upload but returned no results."}
            return {
                "success": True,
                "upload_id": payload.get("id"),
                "status": payload.get("status"),
                "compliance_report": payload.get("compliance_report"),
                "baseline_json": payload.get("baseline_json"),
                "errors": payload.get("errors") or payload.get("error"),
                "normalization_review": payload.get("normalization_review") or [],
            }
        return {"success": False, "http_status": resp.status_code,
                "error": resp.text[:500]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_translation(config_text: str, source_vendor: str, target_vendor: str , source_stem: str = "sample_config") -> dict:
    from translator import translate_config

    source_family = _canonical(source_vendor)
    target_family = _canonical(target_vendor)

    # Only a same-vendor request is a passthrough; cisco -> junos and
    # junos -> cisco both run the real deterministic pipeline.
    passthrough = source_family == target_family

    # ---- translate (or pass through) ---------------------------------------
    if passthrough:
        # Deterministic parse only (no LLM, no RAG) so the baseline copy still
        # maps cleanly; the emitted config stays the unmodified source.
        try:
            if source_family == "junos":
                ir = juniper_ir.normalize(juniper_parser.parse(config_text))
            else:
                ir = cisco_ir.normalize(cisco_parser.parse(config_text))
            ir_result = {"ir": ir.model_dump_safe()}
        except Exception:
            ir_result = {"ir": {}}
        result = {
            "run_id": None,
            "status": "done",
            "overall_confidence": 1.0,
            "confidence_by_category": {},
            "set_commands": [l for l in config_text.splitlines() if l.strip()],
            "ir": ir_result["ir"],
            "explanations": [],
            "warnings": [f"Source and target are both {source_family} - config passed through without conversion."],
            "unresolved": [],
            "rounds": 0,
        }
        handoff_config = config_text
    else:
        result = translate_config(
            config_text,
            use_llm=True,
            with_rag=True,
            persist=True,
            search_fn=None,
            source_vendor=source_vendor,
            target_vendor=target_vendor,
        )
        handoff_config = "\n".join(result.get("set_commands") or [])

    # ---- save normalized copies: rag\ + ai_engine\ --------------------------
    path = target_filepath(target_vendor)
    ai_path = ai_engine_filepath(target_vendor)
    baseline_path = ai_engine_baseline_filepath(target_vendor)

    document = build_normalized_response(
        result, source_vendor=source_vendor, target_vendor=target_vendor,
        saved_path=str(path),
    )
    document["ai_engine_path"] = str(ai_path)
    document["baseline_path"] = str(baseline_path)
    document["passthrough"] = passthrough

    baseline = ir_to_baseline(result.get("ir"), target_vendor)

    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    ai_path.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False, default=str),
                             encoding="utf-8")
    txt_path = source_txt_filepath(source_stem, target_vendor)
    txt_path.write_text("\n".join(result.get("set_commands") or []), encoding="utf-8")
    document["txt_path"] = str(txt_path)

    # ---- hand the translated/normalized config to ai_engine ----------------
    handoff = _handoff_to_ai_engine(handoff_config, target_family)
    document["ai_engine_handoff"] = handoff
    # Surface the compliance summary at the top level so a caller does not have
    # to reach into ai_engine_handoff to show pass/fail counts.
    document["summary"] = (handoff.get("compliance_report") or {}).get("summary")
    document["passthrough"] = passthrough

    ai_path.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
    return document


@router.get("/vendors", response_model=dict)
def list_vendors():
    """Vendor options the frontend should ask the user about first."""
    return {
        "supported_sources": sorted(SUPPORTED_SOURCES),
        "supported_targets": sorted(CANONICAL_TARGETS),
        "pairs": VENDOR_PAIRS,
    }


@router.post("/translate")
def translate(req: TranslateRequest) -> dict:
    source, target = _validate_vendors(req.source_vendor, req.target_vendor)
    if not req.config_text or not req.config_text.strip():
        raise HTTPException(status_code=400, detail="config_text is required and cannot be empty")
    document = _run_translation(req.config_text, source, target , source_stem="sample_config")
    return JSONResponse(content=document)


@router.post("/translate/upload")
async def translate_upload(
    source_vendor: str,
    target_vendor: str,
    file: UploadFile = File(...),
) -> dict:
    source, target = _validate_vendors(source_vendor, target_vendor)
    raw = await file.read()
    try:
        config_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        config_text = raw.decode("latin-1")
    if not config_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded config file is empty")
    stem = Path(file.filename).stem if file.filename else "sample_config"
    # document = _run_translation(config_text, source, target , source_stem=stem)
    # return JSONResponse(content=document)
    document = _run_translation(config_text, source, target, source_stem=stem)
    document["download_source_stem"] = stem
    document["download_target_vendor"] = target
    return JSONResponse(content=document)


@router.get("/health")
def health() -> dict:
    from core.store import count_chunks
    from config import OLLAMA_MODEL, OLLAMA_URL

    db_ok = False
    chunk_count = 0
    db_error = ""
    try:
        chunk_count = count_chunks()
        db_ok = True
    except Exception as e:
        db_error = str(e)

    ollama_ok = False
    ollama_error = None
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_ok = resp.ok
        if not ollama_ok:
            ollama_error = f"HTTP {resp.status_code}"
    except Exception as e:
        ollama_error = str(e)

    payload = {
        "status": "ok" if db_ok and ollama_ok else "degraded",
        "database": {"connected": db_ok,
                     "chunk_count": chunk_count,
                     **({"error": db_error} if not db_ok else {})},
        "ollama": {"connected": ollama_ok, "model": OLLAMA_MODEL,
                   **({"error": ollama_error} if ollama_error else {})},
        "supported_vendors": {"sources": sorted(SUPPORTED_SOURCES),
                              "targets": sorted(CANONICAL_TARGETS)},
    }
    return JSONResponse(status_code=200, content=payload)


@router.post("/ask")
def ask(req: AskRequest) -> dict:
    from core.builder import answer_prompt, answer_system, call_ollama
    from core.store import ensure_database, search

    ensure_database()
    evidence = search(req.question)
    try:
        answer = call_ollama(answer_system(), answer_prompt(req.question, evidence))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama unavailable: {e}",
        )
    return {
        "question": req.question,
        "answer": answer,
        "sources": [
            {"source": r["source"], "section": r["section"], "score": r["score"]}
            for r in evidence[:4]
        ],
    }

# @router.get("/translate/download")
# def download_translated_file(target_vendor: str, source_stem: str = "sample_config"):
#     """
#     GET /api/translate/download?target_vendor=junos&source_stem=sample_config
#     Returns the translated config .txt file as a downloadable attachment.
#     """
#     path = source_txt_filepath(source_stem, target_vendor)
#     if not path.exists():
#         raise HTTPException(status_code=404, detail="Translated file not found. Run /translate/upload first.")

#     return FileResponse(
#         path=path,
#         media_type="text/plain",
#         filename=path.name,
#     )
@router.get("/translate/download")
def download_translated_file(target_vendor: str, source_stem: str = "sample_config"):
    path = source_txt_filepath(source_stem, target_vendor)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Translated file not found at {path}")

    return FileResponse(
        path=path,
        media_type="application/octet-stream",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.post("/reindex")
def reindex(wipe: bool = False) -> dict:
    import index as index_mod
    from config import INDEX_TABLE
    from core.store import count_chunks, ensure_database

    ensure_database()
    if wipe:
        from core.store import clear_chunks
        clear_chunks()
    total = index_mod.index_all()
    return {"indexed": total, "total_in_db": count_chunks(), "table": INDEX_TABLE}