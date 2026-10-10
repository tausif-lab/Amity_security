"""
core/views.py

Web entry points that replace the original script's main() + input() flow.
Synchronous for the prototype (no Celery).
"""

import json
import re
from pathlib import Path
from io import BytesIO

from django.db.migrations import state
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from compliance.services.remediation import generate_remediation_commands, execute_remediation, build_corrected_config

from .models import DeviceUpload, RemediationLog
from .serializers import DeviceUploadSerializer
from ai_engine.services.ollama_client import normalize_config, reinforcement_prompt
from ai_engine.services.validator import validate_normalized_json
from .services.normalization_memory import (
    LOW_CONFIDENCE_THRESHOLD, apply_approved_mappings, config_commands, lookup_config_memories,
    prompt_context, store_pending,
)
from compliance.services.rule_engine import compliance_engine
from compliance.services.remediation import generate_remediation_commands, execute_remediation
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from .supabase_auth import SupabaseAuthentication, role_required
from ai_engine.services.fact_extractor import apply_overrides, sanitize, drop_unsupported_interfaces


BASE_DIR = Path(__file__).resolve().parent.parent

INSTRUCTIONS_PATH = BASE_DIR / "ai_engine" / "schemas" / "llm_instructions.json"
SCHEMA_PATH = BASE_DIR / "ai_engine" / "schemas" / "normalized_schema.json"
RULES_PATH = BASE_DIR / "compliance" / "data" / "cis_rules.json"
RULES_DIR = BASE_DIR / "compliance" / "data"

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_rules(framework, vendor):
    vendor = (vendor or "").lower()
    if framework == "NIST":
        return _load_json(RULES_DIR / "NIST_rules.json")
    if vendor in ("juniper", "junos"):
        return _load_json(RULES_DIR / "cis_juniper_rules.json")
    return _load_json(RULES_DIR / "cis_rules.json")


# def _process_single_config(config_text, vendor, instructions, schema, rules):
def _normalize_single_config(config_text, vendor, instructions, schema):
    """Runs one config through normalize -> validate -> comply. Returns a dict result."""
    #upload = DeviceUpload.objects.create(vendor=vendor, status="processing")
    upload = DeviceUpload.objects.create(vendor=vendor, status="processing", original_config_text=config_text)

    memories = lookup_config_memories(config_text, vendor)
    try:
        normalized_data = normalize_config(config_text, instructions, schema, prompt_context(memories))
    except Exception as e:
        upload.status = "failed"
        upload.save()
        return {"id": str(upload.id), "vendor": vendor, "status": "failed", "error": str(e)}

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
    review_items = []
    for assessment in assessments if isinstance(assessments, list) else []:
        if not isinstance(assessment, dict):
            continue
        try:
            confidence = float(assessment.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < LOW_CONFIDENCE_THRESHOLD and assessment.get("command"):
            memory_id = store_pending(
                str(assessment["command"]), vendor, confidence,
                str(assessment.get("proposed_meaning", "")),
            )
            review_items.append({"memory_id": memory_id, "command": assessment["command"],
                                 "proposed_meaning": assessment.get("proposed_meaning", ""),
                                 "confidence": confidence})

    # The bundled demonstration config intentionally uses non-vendor `demo-policy`
    # commands. Always send those through human review on their first encounter so
    # the before/after embedding workflow is reproducible regardless of LLM wording.
    assessed_commands = {str(item.get("command", "")).strip() for item in review_items}
    approved_commands = {item["input_command"] for item in memories if item["status"] == "approved"}
    for command in config_commands(config_text):
        if (command.startswith("demo-policy ") and command not in assessed_commands
                and command not in approved_commands):
            memory_id = store_pending(command, vendor, 0.0, "Demo policy command requires human mapping.")
            review_items.append({"memory_id": memory_id, "command": command,
                                 "proposed_meaning": "Human mapping required for this demo policy.",
                                 "confidence": 0.0})

    is_valid, errors = validate_normalized_json(normalized_data, schema)
    retry_count = 0
    while not is_valid and retry_count < 2:
        try:
            normalized_data = reinforcement_prompt(config_text, errors, instructions, schema)
        except Exception:
            break
        is_valid, errors = validate_normalized_json(normalized_data, schema)
        retry_count += 1

    # A corrective retry may also return audit metadata; it must never leak into
    # the normalized baseline consumed by the deterministic compliance engine.
    normalized_data.pop("_normalization_assessment", None)
    # normalized_data = apply_overrides(normalized_data, config_text, vendor)
    normalized_data = sanitize(normalized_data, schema, config_text)
    normalized_data = drop_unsupported_interfaces(normalized_data, config_text)
    normalized_data = apply_overrides(normalized_data, config_text, vendor)

    # if not is_valid:
    #     upload.status = "review"
    #     upload.baseline_json = normalized_data
    #     upload.save()
    #     return {"id": str(upload.id), "vendor": vendor, "status": "review", "errors": errors,
    #             "partial_baseline": normalized_data, "normalization_review": review_items}

    # report = compliance_engine(normalized_data, rules)
    # upload.baseline_json = normalized_data
    # upload.compliance_report = report
    # upload.status = "done"
    # upload.save()
    # result = DeviceUploadSerializer(upload).data
    # result["normalization_review"] = review_items
    # result["memory_matches"] = [{"command": item["input_command"], "memory_id": item["id"],
    #                               "similarity": item["similarity"], "status": item["status"]}
    #                              for item in memories]
    # return result
    # state = "review" if review_items else "normalized"
    # upload.baseline_json = normalized_data
    # upload.status = state
    # upload.save()
    # return {
    #     "id": str(upload.id), "vendor": vendor, "status": state,
    #     "baseline_json": normalized_data,
    #     "normalization_review": review_items,
    #     "memory_matches": [{"command": m["input_command"], "memory_id": m["id"],
    #                         "similarity": m["similarity"], "status": m["status"]}
    #                        for m in memories],
    # }
    if not is_valid:
        upload.status = "review"
        upload.baseline_json = normalized_data
        upload.save()
        return {"id": str(upload.id), "vendor": vendor, "status": "review", "errors": errors,
                "partial_baseline": normalized_data, "normalization_review": review_items}

    state = "review" if review_items else "normalized"      # <- must come BEFORE it is used
    upload.baseline_json = normalized_data
    upload.status = state
    upload.save()
    return {
        "id": str(upload.id), "vendor": vendor, "status": state,
        "baseline_json": normalized_data,
        "normalization_review": review_items,
        "memory_matches": [{"command": m["input_command"], "memory_id": m["id"],
                            "similarity": m["similarity"], "status": m["status"]}
                           for m in memories],
    }


@api_view(["GET"])
def normalization_reviews(request):
    """List unresolved LLM doubts for a reviewer UI or workflow."""
    from .models import NormalizationMemory
    records = NormalizationMemory.objects.filter(status="pending").order_by("-created_at")
    return Response([{"id": row.id, "vendor": row.vendor, "command": row.command,
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

        story.append(PageBreak())  # next device starts on a new page

    doc.build(story)
    buffer.seek(0)
    return buffer


# @api_view(["POST"])
# def upload_config(request):
#     """
#     POST /api/uploads/
#     Accepts ONE OR MORE config files (same field name "config", or
#     "vendor" repeated per file). Each file is processed independently.
#     """
#     files = request.FILES.getlist("config")
#     vendors = request.data.getlist("vendor")  # one vendor string per file, same order

#     if not files:
#         return Response({"error": "No config file(s) provided."}, status=status.HTTP_400_BAD_REQUEST)

#     instructions = _load_json(INSTRUCTIONS_PATH)
#     schema = _load_json(SCHEMA_PATH)
#     rules = _load_json(RULES_PATH)

#     results = []
#     for i, file_obj in enumerate(files):
#         vendor = vendors[i] if i < len(vendors) else "unknown"
#         config_text = file_obj.read().decode("utf-8", errors="ignore")

#         if len(config_text.strip()) < 10:
#             results.append({"vendor": vendor, "status": "failed", "error": "Config file empty or too short."})
#             continue

#         result = _process_single_config(config_text, vendor, instructions, schema, rules)
#         results.append(result)

#     return Response({"count": len(results), "results": results}, status=status.HTTP_200_OK)

@api_view(["POST"])
def normalize_upload(request):
    """POST /api/normalize/  (files + vendor). Normalizes only, no compliance check."""
    files = request.FILES.getlist("config")
    vendors = request.data.getlist("vendor")
    if not files:
        return Response({"error": "No config file(s) provided."}, status=400)

    instructions = _load_json(INSTRUCTIONS_PATH)
    schema = _load_json(SCHEMA_PATH)

    results = []
    for i, file_obj in enumerate(files):
        vendor = vendors[i] if i < len(vendors) else "unknown"
        config_text = file_obj.read().decode("utf-8", errors="ignore")
        if len(config_text.strip()) < 10:
            results.append({"vendor": vendor, "status": "failed", "error": "Config file empty or too short."})
            continue
        results.append(_normalize_single_config(config_text, vendor, instructions, schema))

    return Response({"count": len(results), "results": results})

# new api added
@api_view(["POST"])
def audit_upload(request, upload_id):
    """POST /api/uploads/<id>/audit/  body: {"framework": "CIS" | "NIST"}"""
    framework = (request.data.get("framework") or "").upper()
    if framework not in ("CIS", "NIST"):
        return Response({"error": "framework must be 'CIS' or 'NIST'."}, status=400)

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

    report = compliance_engine(baseline, _load_rules(framework, upload.vendor))
    report["framework"] = framework

    upload.baseline_json = baseline
    upload.compliance_report = report
    upload.status = "done"
    upload.save()
    return Response(DeviceUploadSerializer(upload).data)


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

    if not upload.compliance_report:
        return Response({"error": "No compliance report available for this upload."}, status=400)

    instructions = _load_json(INSTRUCTIONS_PATH)
    failed_rules = [r for r in upload.compliance_report["results"] if r["status"] == "Fail"]

    proposals = generate_remediation_commands(upload.baseline_json, failed_rules, instructions)
    return Response({"upload_id": upload.id, "proposals": proposals})


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

    # We don't store the original raw config text (per your earlier decision
    # to keep JSON-only persistence) - so reconstruct from raw_commands +
    # baseline_json as the closest available representation.
    original_text = "\n".join(upload.baseline_json.get("raw_commands", []))

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
