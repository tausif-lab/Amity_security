"""
core/views.py

Web entry points that replace the original script's main() + input() flow.
Synchronous for the prototype (no Celery).
"""

import json
import re
from pathlib import Path
from io import BytesIO

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from compliance.services.remediation import generate_remediation_commands, execute_remediation, build_corrected_config
from compliance.services.drift import build_drift_report

from .models import DeviceUpload, RemediationLog, ComplianceSnapshot , NormalizationMemory 
from .serializers import DeviceUploadSerializer
from ai_engine.services.ollama_client import (
    normalize_config, normalize_config_checked, reinforcement_prompt,
)
from ai_engine.services.validator import validate_normalized_json
from ai_engine.services.ingest import ingest
from .services.normalization_cache import compute_key, get as cache_get, put as cache_put
from .services.normalization_cache import stats as cache_stats, clear as cache_clear
from .services.normalization_memory import (
    LOW_CONFIDENCE_THRESHOLD, apply_approved_mappings, config_commands, lookup_config_memories,
    prompt_context, store_pending,
)
from compliance.services.rule_engine import compliance_engine
from .supabase_auth import SupabaseAuthentication, role_required
from ai_engine.services.fact_extractor import (
    apply_overrides, sanitize, drop_unsupported_interfaces, deterministic_paths,
)
from xml.sax.saxutils import escape
from .models import DeviceUpload, RemediationLog, ComplianceSnapshot, Device

BASE_DIR = Path(__file__).resolve().parent.parent

INSTRUCTIONS_PATH = BASE_DIR / "ai_engine" / "schemas" / "llm_instructions.json"
SCHEMA_PATH = BASE_DIR / "ai_engine" / "schemas" / "normalized_schema.json"
RULES_PATH = BASE_DIR / "compliance" / "data" / "cis_rules.json"
RULES_DIR = BASE_DIR / "compliance" / "data"

SUPPORTED_FRAMEWORKS = ("CIS", "NIST", "STIG", "ISO")

FRAMEWORK_RULE_FILES = {
    "CIS": "cis_rules.json",
    "NIST": "NIST_rules.json",
    "STIG": "stig_rules.json",
    "ISO": "iso_rules.json",
}

FRAMEWORK_LABELS = {
    "CIS": "CIS Benchmark",
    "NIST": "NIST SP 800-53 / NISTIR-7966",
    "STIG": "DISA STIG",
    "ISO": "ISO/IEC 27001:2022 Annex A",
}


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_framework(value, default="CIS") -> str:
    framework = (value or default or "").upper().strip()
    return framework if framework in SUPPORTED_FRAMEWORKS else default


def _load_rules(framework, vendor):
    """Benchmark rules for a framework. Vendor-specific CIS files take priority;
    the other frameworks are vendor-neutral and apply as written."""
    framework = _resolve_framework(framework)
    vendor = (vendor or "").lower()
    if framework == "CIS" and vendor in ("juniper", "junos"):
        return _load_json(RULES_DIR / "cis_juniper_rules.json")
    return _load_json(RULES_DIR / FRAMEWORK_RULE_FILES[framework])


def _take_snapshot(upload, baseline, summary):
    """Record this upload as a point on the device's audit timeline."""
    hostname = (baseline or {}).get("hostname")
    if not hostname:
        return None
    try:
        return ComplianceSnapshot.objects.create(
            hostname=hostname, vendor=upload.vendor, upload=upload,
            baseline_json=baseline, summary=summary,
        )
    except Exception:
        # A snapshot is an audit convenience; never fail an upload over it.
        return None


# ---- "Ask a human once" helpers ---------------------------------------------
_DECISION_RANK = {"approved": 3, "rejected": 2, "pending": 1}


def _norm_cmd(text):
    return " ".join(str(text).lower().split())


def _decision_index(vendor):
    """normalized command -> its NormalizationMemory. A human decision outranks a pending one."""
    index = {}
    for m in NormalizationMemory.objects.filter(vendor=vendor).order_by("id"):
        key = _norm_cmd(m.command)
        if key not in index or _DECISION_RANK.get(m.status, 0) > _DECISION_RANK.get(index[key].status, 0):
            index[key] = m
    return index


def _snap_to_config_line(command, config_lines):
    """The model often paraphrases. Remember the literal config line instead, so the same
    line in a later upload finds this decision."""
    target = _norm_cmd(command)
    for line in config_lines:
        if _norm_cmd(line) == target:
            return line
    for line in config_lines:
        n = _norm_cmd(line)
        if len(target) >= 6 and len(n) >= 6 and (target in n or n in target):
            return line
    return command


def _ask_once(index, vendor, command, confidence, meaning):
    """A review item for `command`, or None if a human already decided it.
    A still-pending record is reused instead of creating a duplicate."""
    key = _norm_cmd(command)
    existing = index.get(key)
    if existing is not None and existing.status in ("approved", "rejected"):
        return None
    if existing is not None:
        memory_id = existing.id
    else:
        memory_id = store_pending(command, vendor, confidence, meaning)
        index[key] = NormalizationMemory(id=memory_id, command=command, vendor=vendor, status="pending")
    return {"memory_id": memory_id, "command": command,
            "proposed_meaning": meaning, "confidence": confidence}


def _set_dotted(data, path, value):
    parts = path.split(".")
    cur = data
    for key in parts[:-1]:
        if not isinstance(cur.get(key), dict):
            cur[key] = {}
        cur = cur[key]
    cur[parts[-1]] = value


def _apply_field_decisions(data, vendor):
    """Approved answers about a FIELD (dual-call disagreements). These are keyed by a field
    path, not a config line, so the config-line lookup never finds them. Apply them directly."""
    for m in NormalizationMemory.objects.filter(vendor=vendor, status="approved"):
        path = (m.normalized_path or "").strip()
        if path and _norm_cmd(m.command) == _norm_cmd(path):
            _set_dotted(data, path, m.normalized_value)
    return data

# def _process_single_config(config_text, vendor, instructions, schema, rules):
# def _normalize_single_config(config_text, vendor, instructions, schema):
#     """Runs one config through normalize -> validate -> comply. Returns a dict result."""
#     #upload = DeviceUpload.objects.create(vendor=vendor, status="processing")
#     upload = DeviceUpload.objects.create(vendor=vendor, status="processing", original_config_text=config_text)

#     memories = lookup_config_memories(config_text, vendor)

#     # Layer 1: exact-match cache in front of the LLM. The key covers vendor,
#     # model, schema and prompt, so editing any of them retires the cache
#     # automatically. On a hit nothing is inferred at all.
#     cache_key = compute_key(vendor, instructions.get("model", ""), schema,
#                             instructions.get("system_prompt", ""), config_text)
#     cached = cache_get(cache_key)
#     dual_status = "skipped"
#     disagreements = []       # a cache hit performs no call, so it can disagree about nothing

#     if isinstance(cached, dict) and cached:
#         normalized_data = json.loads(json.dumps(cached))    # defensive copy
#         cache_status = "hit"
#     else:
#         cache_status = "miss"
#         try:
#             normalized_data, dual_status, disagreements = normalize_config_checked(
#                 config_text, instructions, schema, prompt_context(memories))
#         except Exception as e:
#             upload.status = "failed"
#             upload.save()
#             return {"id": str(upload.id), "vendor": vendor, "status": "failed", "error": str(e)}
#         cache_put(cache_key, vendor, instructions.get("model", ""), normalized_data)

#     upload.cache_status = cache_status
#     upload.dual_call_status = dual_status
#     upload.save()

#     if not isinstance(normalized_data, dict):
#         upload.status = "failed"
#         upload.save()
#         return {"id": str(upload.id), "vendor": vendor, "status": "failed",
#                 "error": f"Normalizer returned {type(normalized_data).__name__}, expected a JSON object."}

#     assessments = normalized_data.pop("_normalization_assessment", [])
#     is_single_review_demo = "HITL_SINGLE_REVIEW_DEMO" in config_text
#     has_demo_approval = any(
#         item["status"] == "approved" and item["input_command"].startswith("demo-policy ")
#         for item in memories
#     )
#     if is_single_review_demo:
#         # Fixed known-good fixture values keep the demo focused on one human
#         # mapping, rather than asking a reviewer to repeat eight obvious facts.
#         management = dict(normalized_data.get("management") or {})
#         management.update({"telnet_enabled": False, "http_enabled": False,
#                            "snmp": {"community_strings": []}})
#         if not has_demo_approval:
#             management.pop("ssh_version", None)
#         normalized_data["management"] = management
#         normalized_data["logging"] = {"remote_servers": ["192.0.2.50"]}
#         normalized_data["ntp"] = {"servers": ["192.0.2.123"]}
#         normalized_data["authentication"] = {"aaa_methods": ["radius"],
#                                                 "password_encryption": "scrypt"}
#     normalized_data = apply_approved_mappings(normalized_data, memories)
#     review_items = []
#     for assessment in assessments if isinstance(assessments, list) else []:
#         if not isinstance(assessment, dict):
#             continue
#         try:
#             confidence = float(assessment.get("confidence", 0))
#         except (TypeError, ValueError):
#             confidence = 0.0
#         if confidence < LOW_CONFIDENCE_THRESHOLD and assessment.get("command"):
#             memory_id = store_pending(
#                 str(assessment["command"]), vendor, confidence,
#                 str(assessment.get("proposed_meaning", "")),
#             )
#             review_items.append({"memory_id": memory_id, "command": assessment["command"],
#                                  "proposed_meaning": assessment.get("proposed_meaning", ""),
#                                  "confidence": confidence})

#     # The bundled demonstration config intentionally uses non-vendor `demo-policy`
#     # commands. Always send those through human review on their first encounter so
#     # the before/after embedding workflow is reproducible regardless of LLM wording.
#     assessed_commands = {str(item.get("command", "")).strip() for item in review_items}
#     approved_commands = {item["input_command"] for item in memories if item["status"] == "approved"}
#     for command in config_commands(config_text):
#         if (command.startswith("demo-policy ") and command not in assessed_commands
#                 and command not in approved_commands):
#             memory_id = store_pending(command, vendor, 0.0, "Demo policy command requires human mapping.")
#             review_items.append({"memory_id": memory_id, "command": command,
#                                  "proposed_meaning": "Human mapping required for this demo policy.",
#                                  "confidence": 0.0})

#     is_valid, errors = validate_normalized_json(normalized_data, schema)
#     retry_count = 0
#     while not is_valid and retry_count < 2:
#         try:
#             candidate = reinforcement_prompt(config_text, errors, instructions, schema)
#         except Exception:
#             break
#         # A corrective retry can come back worse than the first answer (small
#         # models sometimes echo the schema back verbatim). Keep whichever
#         # candidate actually satisfies the schema, and never let a failed
#         # retry overwrite a valid normalization.
#         if not isinstance(candidate, dict):
#             break
#         candidate_valid, candidate_errors = validate_normalized_json(candidate, schema)
#         if candidate_valid:
#             normalized_data = candidate
#             is_valid, errors = True, []
#             break
#         if not is_valid and len(candidate_errors) < len(errors):
#             normalized_data, errors = candidate, candidate_errors
#         retry_count += 1

#     # A corrective retry may also return audit metadata; it must never leak into
#     # the normalized baseline consumed by the deterministic compliance engine.
#     normalized_data.pop("_normalization_assessment", None)
#     normalized_data = sanitize(normalized_data, schema, config_text)
#     normalized_data = drop_unsupported_interfaces(normalized_data, config_text)
#     # `vendor` is known from the upload form, never from the model, so apply it
#     # before the final validation pass: without it every upload would be sent
#     # to review purely because the model omitted a field we already know.
#     normalized_data = apply_overrides(normalized_data, config_text, vendor)

#     # Dual-call check: the architecture routes disagreement to human review, but
#     # only for fields that nothing upstream can settle. A field the deterministic
#     # layer proves from the config text is already correct by the time it lands,
#     # so escalating it would only manufacture review noise. Everything the model
#     # disagreed about is still recorded on the upload for the audit trail.
#     settled = deterministic_paths(config_text, vendor)
#     unresolved_disagreements = [d for d in disagreements
#                                 if tuple(d["field"].split(".")) not in settled]
#     for item in unresolved_disagreements:
#         review_items.append({
#             "memory_id": store_pending(
#                 item["field"], vendor, 0.3,
#                 f"Dual-call disagreement: {item['call_a']!r} vs {item['call_b']!r}",
#             ),
#             "command": item["field"],
#             "proposed_meaning": f"Dual-call disagreement: {item['call_a']!r} vs {item['call_b']!r}",
#             "confidence": 0.3,
#         })

#     # Validate the fully processed baseline, not the raw model output: the
#     # deterministic overrides above legitimately add the required `vendor`.
#     is_valid, errors = validate_normalized_json(normalized_data, schema)

#     if not is_valid:
#         upload.status = "review"
#         upload.baseline_json = normalized_data
#         upload.save()
#         return {"id": str(upload.id), "vendor": vendor, "status": "review", "errors": errors,
#                 "partial_baseline": normalized_data, "normalization_review": review_items}

#     state = "review" if review_items else "normalized"      # <- must come BEFORE it is used
#     upload.baseline_json = normalized_data
#     upload.status = state
#     upload.save()
#     return {
#         "id": str(upload.id), "vendor": vendor, "status": state,
#         "baseline_json": normalized_data,
#         "cache_status": cache_status,
#         "dual_call_status": dual_status,
#         "dual_call_disagreements": disagreements,
#         "normalization_review": review_items,
#         "memory_matches": [{"command": m["input_command"], "memory_id": m["id"],
#                             "similarity": m["similarity"], "status": m["status"]}
#                            for m in memories],
#     }




def _normalize_single_config(config_text, vendor, instructions, schema):
    """Normalize one config. Returns a dict result. A human is asked ONCE per command."""
    upload = DeviceUpload.objects.create(vendor=vendor, status="processing", original_config_text=config_text)

    memories = lookup_config_memories(config_text, vendor)

    # Layer 1: exact-match cache in front of the LLM. The key covers vendor,
    # model, schema and prompt, so editing any of them retires the cache
    # automatically. On a hit nothing is inferred at all.
    cache_key = compute_key(vendor, instructions.get("model", ""), schema,
                            instructions.get("system_prompt", ""), config_text)
    cached = cache_get(cache_key)
    dual_status = "skipped"
    disagreements = []       # a cache hit performs no call, so it can disagree about nothing

    if isinstance(cached, dict) and cached:
        normalized_data = json.loads(json.dumps(cached))    # defensive copy
        cache_status = "hit"
    else:
        cache_status = "miss"
        try:
            normalized_data, dual_status, disagreements = normalize_config_checked(
                config_text, instructions, schema, prompt_context(memories))
        except Exception as e:
            upload.status = "failed"
            upload.save()
            return {"id": str(upload.id), "vendor": vendor, "status": "failed", "error": str(e)}
        cache_put(cache_key, vendor, instructions.get("model", ""), normalized_data)

    upload.cache_status = cache_status
    upload.dual_call_status = dual_status
    upload.save()

    if not isinstance(normalized_data, dict):
        upload.status = "failed"
        upload.save()
        return {"id": str(upload.id), "vendor": vendor, "status": "failed",
                "error": f"Normalizer returned {type(normalized_data).__name__}, expected a JSON object."}

    assessments = normalized_data.pop("_normalization_assessment", [])
    is_single_review_demo = "HITL_SINGLE_REVIEW_DEMO" in config_text
    has_demo_approval = any(
        item["status"] == "approved" and item["input_command"].startswith("demo-policy ")
        for item in memories
    )
    if is_single_review_demo:
        # Fixed known-good fixture values keep the demo focused on one human
        # mapping, rather than asking a reviewer to repeat eight obvious facts.
        management = dict(normalized_data.get("management") or {})
        management.update({"telnet_enabled": False, "http_enabled": False,
                           "snmp": {"community_strings": []}})
        if not has_demo_approval:
            management.pop("ssh_version", None)
        normalized_data["management"] = management
        normalized_data["logging"] = {"remote_servers": ["192.0.2.50"]}
        normalized_data["ntp"] = {"servers": ["192.0.2.123"]}
        normalized_data["authentication"] = {"aaa_methods": ["radius"],
                                                "password_encryption": "scrypt"}
    normalized_data = apply_approved_mappings(normalized_data, memories)

    # ---- Ask a human ONCE per command ---------------------------------------
    # A command that already has an approved or rejected record is never raised
    # again. One that is still pending is reused instead of duplicated.
    decisions = _decision_index(vendor)
    lines = list(config_commands(config_text))
    review_items = []
    raised = set()

    for assessment in assessments if isinstance(assessments, list) else []:
        if not isinstance(assessment, dict) or not assessment.get("command"):
            continue
        try:
            confidence = float(assessment.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        command = _snap_to_config_line(str(assessment["command"]), lines)
        if _norm_cmd(command) in raised:
            continue
        item = _ask_once(decisions, vendor, command, confidence,
                         str(assessment.get("proposed_meaning", "")))
        if item:
            review_items.append(item)
            raised.add(_norm_cmd(command))

    # Demo policy commands: same ask-once rule.
    for command in lines:
        if command.startswith("demo-policy ") and _norm_cmd(command) not in raised:
            item = _ask_once(decisions, vendor, command, 0.0,
                             "Human mapping required for this demo policy.")
            if item:
                review_items.append(item)
                raised.add(_norm_cmd(command))

    is_valid, errors = validate_normalized_json(normalized_data, schema)
    retry_count = 0
    while not is_valid and retry_count < 2:
        try:
            candidate = reinforcement_prompt(config_text, errors, instructions, schema)
        except Exception:
            break
        # A corrective retry can come back worse than the first answer (small
        # models sometimes echo the schema back verbatim). Keep whichever
        # candidate actually satisfies the schema, and never let a failed
        # retry overwrite a valid normalization.
        if not isinstance(candidate, dict):
            break
        candidate_valid, candidate_errors = validate_normalized_json(candidate, schema)
        if candidate_valid:
            normalized_data = candidate
            is_valid, errors = True, []
            break
        if not is_valid and len(candidate_errors) < len(errors):
            normalized_data, errors = candidate, candidate_errors
        retry_count += 1

    # A corrective retry may also return audit metadata; it must never leak into
    # the normalized baseline consumed by the deterministic compliance engine.
    normalized_data.pop("_normalization_assessment", None)
    normalized_data = sanitize(normalized_data, schema, config_text)
    normalized_data = drop_unsupported_interfaces(normalized_data, config_text)
    # `vendor` is known from the upload form, never from the model, so apply it
    # before the final validation pass: without it every upload would be sent
    # to review purely because the model omitted a field we already know.
    normalized_data = apply_overrides(normalized_data, config_text, vendor)
    # Answers a human already gave about a whole FIELD (dual-call disagreements).
    normalized_data = _apply_field_decisions(normalized_data, vendor)

    # Dual-call check: disagreement goes to human review, but only for fields that
    # nothing upstream can settle, and only if no human has answered it before.
    settled = deterministic_paths(config_text, vendor)
    for d in disagreements:
        if tuple(d["field"].split(".")) in settled or _norm_cmd(d["field"]) in raised:
            continue
        item = _ask_once(decisions, vendor, d["field"], 0.3,
                         f"Dual-call disagreement: {d['call_a']!r} vs {d['call_b']!r}")
        if item:
            review_items.append(item)
            raised.add(_norm_cmd(d["field"]))

    # Validate the fully processed baseline, not the raw model output: the
    # deterministic overrides above legitimately add the required `vendor`.
    is_valid, errors = validate_normalized_json(normalized_data, schema)

    if not is_valid:
        upload.status = "review"
        upload.baseline_json = normalized_data
        upload.save()
        return {"id": str(upload.id), "vendor": vendor, "status": "review", "errors": errors,
                "partial_baseline": normalized_data, "normalization_review": review_items}

    state = "review" if review_items else "normalized"
    upload.baseline_json = normalized_data
    upload.status = state
    upload.save()
    return {
        "id": str(upload.id), "vendor": vendor, "status": state,
        "baseline_json": normalized_data,
        "cache_status": cache_status,
        "dual_call_status": dual_status,
        "dual_call_disagreements": disagreements,
        "normalization_review": review_items,
        "memory_matches": [{"command": m["input_command"], "memory_id": m["id"],
                            "similarity": m["similarity"], "status": m["status"]}
                           for m in memories],
    }


def _process_single_config(config_text, vendor, instructions, schema, rules, framework="CIS"):
    """Normalize one config, then run the deterministic compliance engine.

    A pending human review does NOT suppress the report: the upload is still
    scored so the reviewer can see what the unresolved command affects. Only a
    schema-validation failure blocks compliance, because the baseline cannot be
    trusted as input to the rule engine.
    """
    result = _normalize_single_config(config_text, vendor, instructions, schema)
    if result.get("status") == "failed" or "errors" in result:
        # Baseline failed schema validation: no report is built on untrusted data.
        return result

    upload = DeviceUpload.objects.get(id=result["id"])
    baseline = upload.baseline_json or {}

    # A human may have approved mappings after this baseline was first written,
    # so re-apply them before scoring to reflect the approved truth.
    memories = lookup_config_memories(config_text, vendor)
    baseline = apply_approved_mappings(baseline, memories)

    report = compliance_engine(baseline, rules)
    report["framework"] = _resolve_framework(framework)
    report["framework_label"] = FRAMEWORK_LABELS[_resolve_framework(framework)]
    upload.baseline_json = baseline
    upload.compliance_report = report
    # "review" means a human decision is still outstanding; "done" means the
    # analysis is complete and nothing is waiting on a person.
    upload.status = "review" if result.get("normalization_review") else "done"
    upload.save()

    # Point on this device's audit timeline, so a later upload can be diffed
    # against what the device looked like before.
    _take_snapshot(upload, baseline, report["summary"])

    result["status"] = upload.status
    result["baseline_json"] = baseline
    result["compliance_report"] = report
    result["summary"] = report["summary"]
    result["framework"] = report["framework"]
    result["cache_status"] = upload.cache_status
    result["dual_call_status"] = upload.dual_call_status
    return result


@api_view(["GET"])
def health(request):
    """Liveness probe used by workflow.py --check and the frontend diagnostics."""
    from django.conf import settings
    from django.db import connection

    database_ok = True
    database_error = ""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        database_ok = False
        database_error = str(exc)

    ollama_ok = False
    ollama_error = None
    try:
        resp = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        ollama_ok = resp.ok
        if not ollama_ok:
            ollama_error = f"HTTP {resp.status_code}"
    except Exception as exc:
        ollama_error = str(exc)

    return Response({
        "status": "ok" if (database_ok and ollama_ok) else "degraded",
        "database": {"connected": database_ok,
                     **({} if database_ok else {"error": database_error})},
        "ollama": {"connected": ollama_ok, "base_url": settings.OLLAMA_BASE_URL,
                   **({"error": ollama_error} if ollama_error else {})},
    }, status=200)


@api_view(["POST"])
def upload_config(request):
    """
    POST /api/uploads/
    Accepts ONE OR MORE config files (same field name "config", with "vendor"
    repeated once per file in the same order). Each file is processed
    independently and every result carries its own compliance report.

    Optional form fields:
      framework  CIS | NIST | STIG | ISO   (defaults to CIS)
    Configs in JSON / YAML / XML are accepted and converted to CLI text by the
    ingestion engine before normalization.
    """
    files = request.FILES.getlist("config")
    vendors = request.data.getlist("vendor")
    device_ids = request.data.getlist("device_id")   # one per file, same order as the files
    framework = _resolve_framework(request.data.getlist("framework")[0] if request.data.getlist("framework") else None)

    if not files:
        return Response({"error": "No config file(s) provided."}, status=status.HTTP_400_BAD_REQUEST)

    instructions = _load_json(INSTRUCTIONS_PATH)
    schema = _load_json(SCHEMA_PATH)

    results = []
    for i, file_obj in enumerate(files):
        vendor = vendors[i] if i < len(vendors) else "unknown"

        # A registered device is the source of truth for the vendor.
        device = None
        device_id = (device_ids[i] if i < len(device_ids) else "").strip()
        if device_id:
            device = Device.objects.filter(device_id=device_id).first()
            if device is None:
                results.append({"status": "failed", "error": f"Device '{device_id}' is not registered."})
                continue
            vendor = device.vendor

        raw_text = file_obj.read().decode("utf-8", errors="ignore")
        if len(raw_text.strip()) < 10:
            results.append({"vendor": vendor, "status": "failed",
                            "error": "Config file empty or too short."})
            continue

        config_text, source_format = ingest(raw_text, vendor)
        rules = _load_rules(framework, vendor)
        try:
            outcome = _process_single_config(config_text, vendor, instructions, schema,
                                             rules, framework)
            outcome["source_format"] = source_format
            if device and outcome.get("id"):
                DeviceUpload.objects.filter(id=outcome["id"]).update(device=device)
                outcome["device_id"] = device.device_id
                outcome["hostname"] = device.hostname
            results.append(outcome)
        except Exception as exc:
            results.append({"vendor": vendor, "status": "failed", "error": str(exc)})

    return Response({"count": len(results), "framework": framework, "results": results},
                    status=status.HTTP_200_OK)


@api_view(["GET"])
def normalization_reviews(request):
    """List unresolved LLM doubts for a reviewer UI or workflow."""
    from .models import NormalizationMemory
    records = NormalizationMemory.objects.filter(status="pending").order_by("-created_at")
    return Response([{"id": row.id, "vendor": row.vendor, "command": row.command,
                      "status": row.status,
                      "proposed_meaning": row.description, "confidence": row.llm_confidence,
                      "created_at": row.created_at} for row in records])


@api_view(["POST"])
def resolve_normalization_review(request, memory_id):
    """Human approves a deterministic mapping or saves guidance/rejects the proposal."""
    from .models import NormalizationMemory
    try:
        memory = NormalizationMemory.objects.get(id=memory_id)
    except NormalizationMemory.DoesNotExist:
        return Response({"error": "Normalization memory not found."}, status=404)

    decision = request.data.get("decision")
    if decision not in {"approve", "reject"}:
        return Response({"error": "decision must be 'approve' or 'reject'."}, status=400)
    if decision == "approve":
        path = request.data.get("normalized_path", "")
        value = request.data.get("normalized_value")
        human_command = request.data.get("human_command", "").strip()
        # The UI uses one simple line: "canonical.path = valid JSON value".
        # Keep the older explicit fields supported for API users.
        if human_command and not path:
            match = re.fullmatch(r"([A-Za-z_][\w.]+)\s*=\s*(.+)", human_command)
            if not match:
                return Response({"error": "Use 'canonical.path = JSON value', e.g. management.ssh_version = 2."}, status=400)
            path = match.group(1)
            try:
                value = json.loads(match.group(2))
            except json.JSONDecodeError:
                return Response({"error": "The value after '=' must be valid JSON, e.g. false, 2, or [\"radius\"]."}, status=400)
        if not path:
            return Response({"error": "normalized_path is required when approving."}, status=400)
        memory.normalized_path = path
        memory.normalized_value = value
        memory.description = request.data.get("description", human_command or memory.description)
        memory.status = "approved"
    else:
        # Rejected records retain the human explanation for audit, but never affect retrieval.
        memory.description = request.data.get("description", memory.description)
        memory.status = "rejected"
    memory.reviewed_by = request.user if request.user.is_authenticated else None
    memory.save()
    return Response({"id": memory.id, "status": memory.status, "command": memory.command,
                     "normalized_path": memory.normalized_path, "normalized_value": memory.normalized_value})



@api_view(["POST"])
def propose_single_remediation(request, upload_id, rule_id):
    """
    POST /api/uploads/<upload_id>/remediation/propose/<rule_id>/
    Generates a fix suggestion for ONE specific failed rule only.
    Does NOT execute anything on any device.
    """
    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)

    if not upload.compliance_report:
        return Response({"error": "No compliance report available for this upload."}, status=400)

    matching_rule = next(
        (r for r in upload.compliance_report["results"] if r["rule_id"] == rule_id),
        None,
    )
    if not matching_rule:
        return Response({"error": f"Rule '{rule_id}' not found in this report."}, status=404)

    if matching_rule["status"] != "Fail":
        return Response({"error": f"Rule '{rule_id}' is not in Fail status, nothing to fix."}, status=400)

    instructions = _load_json(INSTRUCTIONS_PATH)
    proposals = generate_remediation_commands(upload.baseline_json, [matching_rule], instructions)

    return Response({"upload_id": upload.id, "rule_id": rule_id, "proposal": proposals[0] if proposals else None})


def generate_compliance_pdf(uploads):
    """Builds a single PDF covering one or more uploads (multi-device report)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Network Configuration Compliance Report", styles["Title"]))
    story.append(Paragraph(f"Devices covered: {len(uploads)}", styles["Normal"]))
    story.append(Spacer(1, 20))

    for upload in uploads:
        story.append(Paragraph(f"Device: {upload.baseline_json.get('hostname', 'Unknown')} ({upload.vendor})", styles["Heading1"]))
        story.append(Paragraph(f"Upload ID: {upload.id}", styles["Normal"]))
        story.append(Paragraph(f"Generated: {upload.created_at.strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
        story.append(Spacer(1, 12))

        summary = upload.compliance_report["summary"]
        summary_data = [
            ["Total", "Passed", "Failed", "Unknown", "Critical/High Fails"],
            [summary["total"], summary["passed"], summary["failed"], summary.get("unknown", 0), summary["critical_high"]],
        ]
        summary_table = Table(summary_data, hAlign="LEFT")
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 14))

        status_colors = {"Pass": colors.green, "Fail": colors.red, "Unknown": colors.orange}
        for r in upload.compliance_report["results"]:
            color = status_colors.get(r["status"], colors.black)
            # story.append(Paragraph(
            #     f'<b>[{r["rule_id"]}] {r["name"]}</b> — <font color="{color.hexval()[2:]}">{r["status"]}</font>',
            #     styles["Normal"]
            # ))
            story.append(Paragraph(
            f'<b>[{r["rule_id"]}] {r["name"]}</b> — <font color="{color.hexval()}">{r["status"]}</font>',
             styles["Normal"]
      ))
            story.append(Paragraph(
                f'Field: {r["field"]} | Expected: {r["expected"]} | Actual: {r["actual"]} | Severity: {r["severity"]}',
                styles["Normal"]
            ))
            if r.get("reason"):
                story.append(Paragraph(f'<i>{r["reason"]}</i>', styles["Normal"]))
            story.append(Spacer(1, 8))
            if upload.remediation_json:
             story.append(Paragraph("Recommended Remediation", styles["Heading2"]))
             for p in upload.remediation_json:
                story.append(Paragraph(f'<b>[{escape(p["rule_id"])}] {escape(p["name"])}</b>', styles["Normal"]))
                for cmd in p.get("commands", []):
                    story.append(Paragraph(escape(str(cmd)), styles["Code"]))
                story.append(Spacer(1, 8))
        story.append(PageBreak())  # next device starts on a new page

    doc.build(story)
    buffer.seek(0)
    return buffer


# @api_view(["POST"])
# def normalize_upload(request):
#     """POST /api/normalize/  (files + vendor). Normalizes only, no compliance check."""
#     files = request.FILES.getlist("config")
#     vendors = request.data.getlist("vendor")
#     if not files:
#         return Response({"error": "No config file(s) provided."}, status=400)

#     instructions = _load_json(INSTRUCTIONS_PATH)
#     schema = _load_json(SCHEMA_PATH)

#     results = []
#     for i, file_obj in enumerate(files):
#         vendor = vendors[i] if i < len(vendors) else "unknown"
#         raw_text = file_obj.read().decode("utf-8", errors="ignore")
#         if len(raw_text.strip()) < 10:
#             results.append({"vendor": vendor, "status": "failed", "error": "Config file empty or too short."})
#             continue
#         config_text, source_format = ingest(raw_text, vendor)
#         outcome = _normalize_single_config(config_text, vendor, instructions, schema)
#         outcome["source_format"] = source_format
#         results.append(outcome)

#     return Response({"count": len(results), "results": results})


@api_view(["POST"])
def normalize_upload(request):
    """POST /api/normalize/
    Form fields: config (file, repeatable), device_id (one per file, same order).
    Normalizes only; no compliance report. Each result carries the upload id,
    the normalized baseline and the list of items waiting for human review.
    The report is generated later by POST /api/uploads/<id>/audit/.
    A registered device is the source of truth for the vendor."""
    files = request.FILES.getlist("config")
    vendors = request.data.getlist("vendor")
    device_ids = request.data.getlist("device_id")
    if not files:
        return Response({"error": "No config file(s) provided."}, status=400)
 
    instructions = _load_json(INSTRUCTIONS_PATH)
    schema = _load_json(SCHEMA_PATH)
 
    results = []
    for i, file_obj in enumerate(files):
        vendor = vendors[i] if i < len(vendors) else "unknown"
 
        device = None
        device_id = (device_ids[i] if i < len(device_ids) else "").strip()
        if device_id:
            device = Device.objects.filter(device_id=device_id).first()
            if device is None:
                results.append({"status": "failed", "error": f"Device '{device_id}' is not registered."})
                continue
            vendor = device.vendor
 
        raw_text = file_obj.read().decode("utf-8", errors="ignore")
        if len(raw_text.strip()) < 10:
            results.append({"vendor": vendor, "status": "failed",
                            "error": "Config file empty or too short."})
            continue
 
        config_text, source_format = ingest(raw_text, vendor)
        try:
            outcome = _normalize_single_config(config_text, vendor, instructions, schema)
        except Exception as exc:
            results.append({"vendor": vendor, "status": "failed", "error": str(exc)})
            continue
 
        outcome["source_format"] = source_format
        if device and outcome.get("id"):
            # Link the upload to its device so PUSH can later save a snapshot.
            DeviceUpload.objects.filter(id=outcome["id"]).update(device=device)
            outcome["device_id"] = device.device_id
            outcome["hostname"] = device.hostname
        results.append(outcome)
 
    return Response({"count": len(results), "results": results})
 

# # new api added
# @api_view(["POST"])
# def audit_upload(request, upload_id):
#     """POST /api/uploads/<id>/audit/  body: {"framework": "CIS" | "NIST" | "STIG" | "ISO"}"""
#     requested = (request.data.get("framework") or "").upper().strip()
#     if requested and requested not in SUPPORTED_FRAMEWORKS:
#         return Response({"error": f"framework must be one of {', '.join(SUPPORTED_FRAMEWORKS)}."}, status=400)
#     framework = _resolve_framework(requested)

#     try:
#         upload = DeviceUpload.objects.get(id=upload_id)
#     except DeviceUpload.DoesNotExist:
#         return Response({"error": "Not found."}, status=404)
#     if not upload.baseline_json:
#         return Response({"error": "Upload has no normalized baseline yet."}, status=400)

#     # Pick up any mappings a human approved since normalization
#     baseline = upload.baseline_json
#     if upload.original_config_text:
#         memories = lookup_config_memories(upload.original_config_text, upload.vendor)
#         baseline = apply_approved_mappings(baseline, memories)

#     report = compliance_engine(baseline, _load_rules(framework, upload.vendor))
#     report["framework"] = framework
#     report["framework_label"] = FRAMEWORK_LABELS[framework]

#     upload.baseline_json = baseline
#     upload.compliance_report = report
#     upload.status = "done"
#     upload.save()
#     _take_snapshot(upload, baseline, report["summary"])
#     return Response(DeviceUploadSerializer(upload).data)


@api_view(["POST"])
def audit_upload(request, upload_id):
    """POST /api/uploads/<id>/audit/  body: {"framework": "CIS" | "NIST" | "STIG" | "ISO"}"""
    requested = (request.data.get("framework") or "").upper().strip()
    if requested and requested not in SUPPORTED_FRAMEWORKS:
        return Response({"error": f"framework must be one of {', '.join(SUPPORTED_FRAMEWORKS)}."}, status=400)
    framework = _resolve_framework(requested)

    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)
    if not upload.baseline_json:
        return Response({"error": "Upload has no normalized baseline yet."}, status=400)

    # Pick up any mappings a human approved since normalization
    baseline = upload.baseline_json
    if upload.original_config_text:
        memories = lookup_config_memories(upload.original_config_text, upload.vendor)
        baseline = apply_approved_mappings(baseline, memories)
    baseline = _apply_field_decisions(baseline, upload.vendor)      # NEW: field-level human answers

    report = compliance_engine(baseline, _load_rules(framework, upload.vendor))
    report["framework"] = framework
    report["framework_label"] = FRAMEWORK_LABELS[framework]

    upload.baseline_json = baseline
    upload.compliance_report = report
    upload.status = "done"
    upload.save()
    _take_snapshot(upload, baseline, report["summary"])
    return Response(DeviceUploadSerializer(upload).data)

@api_view(["GET"])
def list_frameworks(request):
    """GET /api/frameworks/ - the benchmarks this deployment can score against."""
    return Response([
        {"id": key, "label": label,
         "rules": len(_load_rules(key, "cisco"))}
        for key, label in FRAMEWORK_LABELS.items()
    ])


@api_view(["GET"])
def cache_report(request):
    """GET /api/cache/stats/ - how often repeat uploads skip the LLM entirely."""
    return Response(cache_stats())


@api_view(["POST"])
def cache_invalidate(request):
    """POST /api/cache/clear/ - drop cached normalizations (optionally one vendor).

    Rarely needed: the cache key includes the model, schema and prompt, so
    editing any of them retires the affected entries automatically.
    """
    vendor = request.data.get("vendor") if request.data else None
    return Response({"deleted": cache_clear(vendor)})


@api_view(["GET"])
def drift_for_upload(request, upload_id):
    """GET /api/uploads/<id>/drift/?against=<upload_id>&framework=CIS

    Compares this upload's baseline with another upload of the same device, or
    with the most recent earlier baseline when `against` is omitted, and reports
    which compliance verdicts the change moved.
    """
    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)
    if not upload.baseline_json:
        return Response({"error": "Upload has no normalized baseline yet."}, status=400)

    framework = _resolve_framework(request.query_params.get("framework"))
    rules = _load_rules(framework, upload.vendor)

    against_id = request.query_params.get("against")
    if against_id:
        try:
            previous = DeviceUpload.objects.get(id=against_id)
        except (DeviceUpload.DoesNotExist, ValueError, ValidationError):
            return Response({"error": f"Upload '{against_id}' not found."}, status=404)
        old_baseline = previous.baseline_json
        old_meta = {"upload_id": str(previous.id), "created_at": previous.created_at,
                    "vendor": previous.vendor}
    else:
        earlier = ComplianceSnapshot.objects.filter(
            hostname=(upload.baseline_json or {}).get("hostname"),
            vendor=upload.vendor,
        ).exclude(upload=upload).first()
        if earlier is None:
            return Response({
                "changed": False, "drift_count": 0, "changes": [],
                "rules_impacted": [], "regressions": [],
                "message": "No earlier baseline exists for this device yet.",
            })
        old_baseline = earlier.baseline_json
        old_meta = {"upload_id": str(earlier.upload_id) if earlier.upload_id else None,
                    "created_at": earlier.created_at, "vendor": earlier.vendor}

    report = build_drift_report(
        old_baseline, upload.baseline_json, rules,
        old_meta, {"upload_id": str(upload.id), "created_at": upload.created_at,
                   "vendor": upload.vendor},
    )
    report["framework"] = framework
    return Response(report)


@api_view(["GET"])
def device_history(request, hostname):
    """GET /api/devices/<hostname>/history/ - every baseline seen for a device."""
    records = ComplianceSnapshot.objects.filter(hostname__iexact=hostname).select_related("upload")
    return Response([{
        "upload_id": str(r.upload_id) if r.upload_id else None,
        "vendor": r.vendor,
        "created_at": r.created_at,
        "summary": r.summary,
    } for r in records])


@api_view(["GET"])
def download_combined_report_pdf(request):
    """
    GET /api/uploads/report/pdf/?ids=<id1>,<id2>,...
    Generates ONE combined PDF covering multiple uploads (e.g. Cisco + Juniper).
    """
    ids_param = request.query_params.get("ids", "")
    upload_ids = [i.strip() for i in ids_param.split(",") if i.strip()]

    if not upload_ids:
        return Response({"error": "Provide ?ids=id1,id2,..."}, status=400)

    uploads = list(DeviceUpload.objects.filter(id__in=upload_ids))
    if not uploads:
        return Response({"error": "No matching uploads found."}, status=404)

    missing_report = [str(u.id) for u in uploads if not u.compliance_report]
    if missing_report:
        return Response({"error": f"These uploads have no compliance report yet: {missing_report}"}, status=400)

    buffer = generate_compliance_pdf(uploads)

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="combined_compliance_report.pdf"'
    return response

@api_view(["GET"])
def get_upload(request, upload_id):
    """GET /api/uploads/<id>/"""
    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)
    return Response(DeviceUploadSerializer(upload).data)


@api_view(["POST"])
def propose_remediation(request, upload_id):
    """
    POST /api/uploads/<id>/remediation/propose/
    Generates candidate fix commands for failed rules. Does NOT execute
    anything on any device.
    """
    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)

    if upload.remediation_json and not request.data.get("refresh"):
        return Response({"upload_id": upload.id, "proposals": upload.remediation_json, "cached": True})

    instructions = _load_json(INSTRUCTIONS_PATH)
    failed_rules = [r for r in upload.compliance_report["results"] if r["status"] == "Fail"]

    proposals = generate_remediation_commands(upload.baseline_json, failed_rules, instructions)
    upload.remediation_json = proposals
    upload.save(update_fields=["remediation_json"])
    return Response({"upload_id": upload.id, "proposals": proposals, "cached": False})


@api_view(["POST"])
def execute_remediation_view(request, upload_id):
    """
    POST /api/uploads/<id>/remediation/execute/
    ⚠️ THIS PUSHES CONFIG TO A LIVE DEVICE.

    Requires "commands": [...] and "confirm": true in the request body.
    """
    if not request.data.get("confirm"):
        return Response(
            {"error": "Refusing to execute without explicit confirm=true."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    commands = request.data.get("commands")
    if not commands:
        return Response({"error": "No commands provided."}, status=400)

    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)

    # Wire an actual live `connection` object here (see core/services/device_fetch.py)
    connection = request.data.get("_connection_placeholder")
    if connection is None:
        return Response(
            {"error": "Device connection not wired up yet — see core/services/device_fetch.py."},
            status=501,
        )

    result = execute_remediation(connection, commands, delay_seconds=5)

    RemediationLog.objects.create(
        upload=upload,
        executed_by=request.user if request.user.is_authenticated else None,
        commands=commands,
        result=result,
    )

    return Response(result)

@api_view(["GET"])
def download_corrected_config(request, upload_id):
    """
    GET /api/uploads/<id>/corrected-config/
    Returns a downloadable corrected config file: original config +
    AI-suggested fixes for every failed rule, clearly labeled.
    """
    try:
        upload = DeviceUpload.objects.get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Not found."}, status=404)

    if not upload.compliance_report or not upload.baseline_json:
        return Response({"error": "No compliance report available for this upload."}, status=400)

    instructions = _load_json(INSTRUCTIONS_PATH)

    # Use the config exactly as the user uploaded it when available; the
    # baseline's raw_commands is only a lossy fallback for older uploads.
    original_text = upload.original_config_text or "\n".join(
        upload.baseline_json.get("raw_commands", [])
    )

    corrected_text = build_corrected_config(
        original_text, upload.baseline_json, upload.compliance_report["results"], instructions
    )

    response = HttpResponse(corrected_text, content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="corrected_config_{upload.vendor}_{upload.id}.txt"'
    return response

@api_view(["GET"])
@authentication_classes([SupabaseAuthentication])
@permission_classes([role_required("auditor", "analyst")])
def me(request):
    return Response({"email": request.user.email, "role": request.user.role})
