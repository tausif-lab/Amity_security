# NEW FILE: core/analysis_views.py  (read-only endpoints for the analyst dashboard)
from collections import defaultdict

from django.db.models import Count, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .diff_utils import can_view_secrets, mask_line, rule_flips
from .models import ChangeEvent, ConfigSnapshot, Device , QueryLog, Tenant

from ai_engine.services.ollama_client import OllamaUnavailable

from .services import nl_query
 
def _pick_result(snap, framework=None):
    """The compliance result for a snapshot (optionally for one framework), newest first."""
    results = [r for r in snap.results.all() if not framework or r.framework == framework]
    return max(results, key=lambda r: (r.created_at, r.id)) if results else None


def _result_dict(r):
    if r is None:
        return None
    return {"framework": r.framework, "score": r.score, "pass_count": r.pass_count,
            "fail_count": r.fail_count, "unknown_count": r.unknown_count}


def _change_counts(snapshot_ids):
    counts = defaultdict(lambda: {"added": 0, "removed": 0})
    rows = (ChangeEvent.objects.filter(snapshot_id__in=snapshot_ids)
            .values("snapshot_id", "change_type").annotate(n=Count("id")))
    for row in rows:
        counts[row["snapshot_id"]][row["change_type"]] = row["n"]
    return counts


@api_view(["GET"])
def analysis_overview(request):
    """GET /api/analysis/overview/?framework=CIS&tenant=<name>
    One concise row per device (latest snapshot) plus fleet totals."""
    framework = (request.query_params.get("framework") or "").upper() or None
    devices = Device.objects.select_related("tenant").order_by("device_id")
    if request.query_params.get("tenant"):
        devices = devices.filter(tenant__name=request.query_params["tenant"])
    device_pks = [d.pk for d in devices]

    latest = {s.device_id: s for s in
              ConfigSnapshot.objects.filter(device_id__in=device_pks, is_latest=True).prefetch_related("results")}

    # Newest first per device, so index 0 is the latest and index 1 the one before it.
    history = defaultdict(list)
    for row in (ConfigSnapshot.objects.filter(device_id__in=device_pks)
                .order_by("device_id", "-uploaded_at", "-id").values("device_id", "config_hash")):
        history[row["device_id"]].append(row["config_hash"])

    counts = _change_counts([s.id for s in latest.values()])

    rows, totals = [], {"devices": len(device_pks), "audited": 0, "compliant": 0, "non_compliant": 0,
                        "changed": 0, "rules_passed": 0, "rules_failed": 0, "scores": []}
    for d in devices:
        snap = latest.get(d.pk)
        row = {"device_id": d.device_id, "hostname": d.hostname, "tenant": d.tenant.name, "site": d.site,
               "vendor": d.vendor, "device_type": d.device_type, "status": "not_audited",
               "latest": None, "change_status": None, "hash_changed": None, "snapshot_count": 0,
               "lines_added": 0, "lines_removed": 0}
        if snap:
            result = _pick_result(snap, framework)
            hashes = history[d.pk]
            row["snapshot_count"] = len(hashes)
            row["latest"] = {"snapshot_id": snap.id, "uploaded_at": snap.uploaded_at,
                             "uploaded_by": snap.uploaded_by, "config_hash": snap.config_hash,
                             **(_result_dict(result) or {})}
            c = counts[snap.id]
            row["lines_added"], row["lines_removed"] = c["added"], c["removed"]
            if len(hashes) < 2:
                row["change_status"] = "initial"
            else:
                row["hash_changed"] = hashes[0] != hashes[1]
                # A new hash with zero changed lines means only comments/timestamps moved.
                row["change_status"] = "changed" if (c["added"] or c["removed"]) else "no_effective_change"
            if result:
                row["status"] = "compliant" if result.fail_count == 0 else "non_compliant"
                totals["audited"] += 1
                totals["compliant" if result.fail_count == 0 else "non_compliant"] += 1
                totals["rules_passed"] += result.pass_count
                totals["rules_failed"] += result.fail_count
                totals["scores"].append(result.score)
            if row["change_status"] == "changed":
                totals["changed"] += 1
        rows.append(row)

    scores = totals.pop("scores")
    totals["average_score"] = round(sum(scores) / len(scores), 1) if scores else None
    return Response({"framework": framework, "totals": totals, "devices": rows})


@api_view(["GET"])
def device_analysis(request, device_id):
    """GET /api/devices/DEV-0001/analysis/?framework=CIS
    Everything the drill-down view and future charts need for one device."""
    try:
        device = Device.objects.select_related("tenant").get(device_id=device_id)
    except Device.DoesNotExist:
        return Response({"error": "Device not found."}, status=404)
    framework = (request.query_params.get("framework") or "").upper() or None

    snaps = list(device.snapshots.prefetch_related("results").order_by("uploaded_at", "id"))  # oldest first
    counts = _change_counts([s.id for s in snaps])

    timeline, rule_stats, by_framework = [], defaultdict(lambda: {"name": "", "passed": 0, "failed": 0}), {}
    for s in snaps:
        r = _pick_result(s, framework)
        timeline.append({"snapshot_id": s.id, "uploaded_at": s.uploaded_at, "uploaded_by": s.uploaded_by,
                         "config_hash": s.config_hash, "is_latest": s.is_latest,
                         "lines_added": counts[s.id]["added"], "lines_removed": counts[s.id]["removed"],
                         "result": _result_dict(r)})
        for res in s.results.all():
            fw = by_framework.setdefault(res.framework, {"audits": 0, "score_sum": 0.0, "passed": 0, "failed": 0})
            fw["audits"] += 1; fw["score_sum"] += res.score
            fw["passed"] += res.pass_count; fw["failed"] += res.fail_count
            if not framework or res.framework == framework:
                for rule in (res.findings_json or {}).get("results", []):
                    st = rule_stats[rule["rule_id"]]
                    st["name"] = rule.get("name", "")
                    if rule.get("status") == "Pass":
                        st["passed"] += 1
                    elif rule.get("status") == "Fail":
                        st["failed"] += 1

    latest = snaps[-1] if snaps else None
    previous = snaps[-2] if len(snaps) > 1 else None
    latest_block = None
    if latest:
        reveal = can_view_secrets(request)
        events = ChangeEvent.objects.filter(snapshot=latest).order_by("id")[:500]
        res_new, res_old = _pick_result(latest, framework), (_pick_result(previous, framework) if previous else None)
        latest_block = {
            "snapshot_id": latest.id, "uploaded_at": latest.uploaded_at, "config_hash": latest.config_hash,
            "previous_snapshot_id": previous.id if previous else None,
            "hash_changed": (previous.config_hash != latest.config_hash) if previous else None,
            "result": _result_dict(res_new),
            "rule_changes": rule_flips(res_old.findings_json if res_old else None,
                                       res_new.findings_json if res_new else None),
            "changes": [{"change_type": e.change_type, "line_number": e.line_number,
                         "line_text": e.line_text if reveal else mask_line(e.line_text),
                         "parent_block": e.parent_block if reveal else mask_line(e.parent_block)}
                        for e in events],
            "normalized_config": latest.normalized_config,
        }

    return Response({
        "device": {"device_id": device.device_id, "hostname": device.hostname, "tenant": device.tenant.name,
                   "site": device.site, "vendor": device.vendor, "device_type": device.device_type,
                   "serial_number": device.serial_number},
        "framework": framework, "snapshot_count": len(snaps),
        "latest": latest_block, "timeline": timeline,
        "frameworks": [{"framework": k, "audits": v["audits"], "average_score": round(v["score_sum"] / v["audits"], 1),
                        "rules_passed": v["passed"], "rules_failed": v["failed"]} for k, v in by_framework.items()],
        "rule_stats": [{"rule_id": k, **v} for k, v in sorted(rule_stats.items())],
    })


@api_view(["GET"])
def snapshot_changes(request, snapshot_id):
    """GET /api/snapshots/<id>/changes/ : the raw line diff against the previous snapshot."""
    try:
        snap = ConfigSnapshot.objects.select_related("device").get(id=snapshot_id)
    except ConfigSnapshot.DoesNotExist:
        return Response({"error": "Snapshot not found."}, status=404)
    previous = (ConfigSnapshot.objects.filter(device_id=snap.device_id)
                .filter(Q(uploaded_at__lt=snap.uploaded_at) | Q(uploaded_at=snap.uploaded_at, id__lt=snap.id))
                .first())     # model ordering is newest first
    reveal = can_view_secrets(request)
    events = ChangeEvent.objects.filter(snapshot=snap).order_by("id")
    return Response({
        "snapshot_id": snap.id, "device_id": snap.device.device_id, "uploaded_at": snap.uploaded_at,
        "previous_snapshot_id": previous.id if previous else None,
        "hash_changed": (previous.config_hash != snap.config_hash) if previous else None,
        "secrets_masked": not reveal,
        "changes": [{"change_type": e.change_type, "line_number": e.line_number,
                     "line_text": e.line_text if reveal else mask_line(e.line_text),
                     "parent_block": e.parent_block if reveal else mask_line(e.parent_block)}
                    for e in events],
    })


def _visible_devices(request):
    """Tenant isolation hook. Today every analyst sees every device. When you add per-user tenant
    access, return only the devices of the tenants this user may see, e.g.
    Device.objects.filter(tenant__in=allowed_tenants_for(request.user))."""
    return Device.objects.all()
 
 
@api_view(["POST"])
def ask_devices(request):
    """POST /api/analysis/query/  body: {"question": "which devices have http enabled?"}
    The LLM only turns the question into a validated filter. The answer comes from the
    normalized_config stored with each device's latest snapshot."""
    question = (request.data.get("question") or "").strip()
    if not question:
        return Response({"error": "Type a question first."}, status=400)
    if len(question) > 300:
        return Response({"error": "Keep the question under 300 characters."}, status=400)
 
    email = getattr(getattr(request, "user", None), "email", "") or ""
    tenants = list(Tenant.objects.values_list("name", flat=True))
 
    def log(status, flt=None, count=0):
        QueryLog.objects.create(user_email=email, question=question, generated_filter=flt,
                                status=status, result_count=count)
 
    try:
        raw = nl_query.ask_llm(question, tenants)
    except OllamaUnavailable as exc:
        log("error")
        return Response({"error": str(exc)}, status=503)
 
    flt, problem = nl_query.validate_filter(raw, tenants)
    if flt is None:
        log("unsupported", raw if isinstance(raw, dict) else None)
        message = ("I can't answer that. Ask about management services, SNMP, logging, NTP, "
                   "routing or password settings." if problem == "unsupported" else problem)
        return Response({"status": "unsupported", "message": message, "supported": nl_query.catalog()})
 
    result = nl_query.run_filter(flt, _visible_devices(request))
    log("ok", flt, result["count"])
    return Response({"status": "ok", "question": question, "interpretation": nl_query.describe(flt),
                     "filter": flt, **result})
 
 
@api_view(["GET"])
def ask_devices_fields(request):
    """GET /api/analysis/query/fields/ : what can be asked, for help text and example chips."""
    return Response({"fields": nl_query.catalog(),
                     "examples": [q for q, a in nl_query.EXAMPLES if "conditions" in a]})
 