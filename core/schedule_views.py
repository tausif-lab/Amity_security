from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .models import AuditRun, AuditSchedule, Device
from .services.scheduled_audit import audit_schedule_devices, first_run
from .supabase_auth import SupabaseAuthentication, role_required
from .views import SUPPORTED_FRAMEWORKS, _load_rules

MAX_INTERVAL = 43200      # 30 days, in minutes


def secured(methods, *roles):
    def wrap(fn):
        fn = permission_classes([role_required(*roles)])(fn)
        fn = authentication_classes([SupabaseAuthentication])(fn)
        return api_view(methods)(fn)
    return wrap


def _require_analyst(request):
    if getattr(request.user, "role", None) != "analyst":
        return Response({"error": "Only analysts can change audit schedules."}, status=403)
    return None


def _check_daily(interval, daily_at):
    if daily_at is not None and interval % 1440 != 0:
        return "daily_at can only be used when interval_minutes is a whole number of days (1440, 2880, ...)."
    return None


def _clean(data, creating):
    """Validate the fields that were sent. Returns (values, error)."""
    out = {}
    if creating or "framework" in data:
        fw = str(data.get("framework") or "CIS").upper().strip()
        if fw not in SUPPORTED_FRAMEWORKS:
            return None, f"framework must be one of {', '.join(SUPPORTED_FRAMEWORKS)}."
        try:
            _load_rules(fw, "cisco")
        except FileNotFoundError:
            return None, f"No rules file is installed for {fw}."
        out["framework"] = fw
    if creating or "interval_minutes" in data:
        try:
            n = int(data.get("interval_minutes"))
        except (TypeError, ValueError):
            return None, "interval_minutes must be a whole number."
        if not 1 <= n <= MAX_INTERVAL:
            return None, f"interval_minutes must be between 1 and {MAX_INTERVAL}."
        out["interval_minutes"] = n
    if "daily_at" in data:
        raw = data.get("daily_at")
        if raw in (None, ""):
            out["daily_at"] = None
        else:
            try:
                out["daily_at"] = datetime.strptime(str(raw), "%H:%M").time()
            except ValueError:
                return None, "daily_at must look like 09:30."
    if "timezone" in data:
        try:
            ZoneInfo(str(data["timezone"]))
        except (ZoneInfoNotFoundError, ValueError):
            return None, "timezone must be a valid name such as Asia/Kolkata or UTC."
        out["timezone"] = str(data["timezone"])
    if creating or "device_ids" in data:
        ids = data.get("device_ids")
        if not isinstance(ids, list) or not ids:
            return None, "device_ids must be a non-empty list."
        found = {d.device_id: d for d in Device.objects.filter(device_id__in=ids)}
        missing = [str(i) for i in ids if i not in found]
        if missing:
            return None, f"Unknown device id(s): {', '.join(missing)}."
        out["devices"] = list(found.values())
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    return out, None


def _schedule_json(s):
    return {
        "id": s.id, "framework": s.framework, "interval_minutes": s.interval_minutes,
        "daily_at": s.daily_at.strftime("%H:%M") if s.daily_at else None,
        "timezone": s.timezone, "enabled": s.enabled,
        "next_run_at": s.next_run_at, "last_run_at": s.last_run_at,
        "created_by": s.created_by, "created_at": s.created_at,
        "devices": [{"device_id": d.device_id, "hostname": d.hostname} for d in s.devices.all()],
    }


def _run_json(r):
    res = r.result
    return {
        "id": r.id, "ran_at": r.ran_at, "status": r.status, "message": r.message,
        "framework": r.framework, "schedule_id": r.schedule_id,
        "result": None if res is None else {
            "id": res.id, "snapshot_id": res.snapshot_id, "score": res.score,
            "pass_count": res.pass_count, "fail_count": res.fail_count,
            "unknown_count": res.unknown_count},
    }


@secured(["GET", "POST"], "auditor", "analyst")
def schedules(request):
    """GET /api/schedules/   POST /api/schedules/ (analyst)"""
    if request.method == "GET":
        qs = AuditSchedule.objects.prefetch_related("devices").order_by("-id")
        return Response([_schedule_json(s) for s in qs])

    denied = _require_analyst(request)
    if denied:
        return denied
    clean, error = _clean(request.data, creating=True)
    if error:
        return Response({"error": error}, status=400)
    error = _check_daily(clean["interval_minutes"], clean.get("daily_at"))
    if error:
        return Response({"error": error}, status=400)

    now = timezone.now()
    s = AuditSchedule(
        framework=clean["framework"], interval_minutes=clean["interval_minutes"],
        daily_at=clean.get("daily_at"), timezone=clean.get("timezone", "UTC"),
        enabled=clean.get("enabled", True),
        created_by=getattr(request.user, "email", "") or "unknown", next_run_at=now)
    s.next_run_at = first_run(s, now)
    with transaction.atomic():
        s.save()
        s.devices.set(clean["devices"])
    return Response(_schedule_json(s), status=201)


@secured(["GET", "PATCH", "DELETE"], "auditor", "analyst")
def schedule_detail(request, schedule_id):
    """GET / PATCH / DELETE /api/schedules/<id>/ (changes need analyst)"""
    s = AuditSchedule.objects.prefetch_related("devices").filter(id=schedule_id).first()
    if s is None:
        return Response({"error": "Schedule not found."}, status=404)
    if request.method == "GET":
        return Response(_schedule_json(s))

    denied = _require_analyst(request)
    if denied:
        return denied
    if request.method == "DELETE":
        s.delete()       # the audit history is kept
        return Response(status=204)

    clean, error = _clean(request.data, creating=False)
    if error:
        return Response({"error": error}, status=400)
    interval = clean.get("interval_minutes", s.interval_minutes)
    daily_at = clean["daily_at"] if "daily_at" in clean else s.daily_at
    error = _check_daily(interval, daily_at)
    if error:
        return Response({"error": error}, status=400)

    was_enabled = s.enabled
    retimed = any(k in clean for k in ("interval_minutes", "daily_at", "timezone"))
    for key in ("framework", "interval_minutes", "daily_at", "timezone", "enabled"):
        if key in clean:
            setattr(s, key, clean[key])
    if retimed or (s.enabled and not was_enabled):
        s.next_run_at = first_run(s, timezone.now())
    with transaction.atomic():
        s.save()
        if "devices" in clean:
            s.devices.set(clean["devices"])
    return Response(_schedule_json(s))


@secured(["POST"], "analyst")
def schedule_run_now(request, schedule_id):
    """POST /api/schedules/<id>/run-now/ : audit its devices now, without moving next_run_at."""
    s = AuditSchedule.objects.filter(id=schedule_id).first()
    if s is None:
        return Response({"error": "Schedule not found."}, status=404)
    runs = audit_schedule_devices(s)
    return Response({"audited": len(runs), "runs": [_run_json(r) for r in runs]})


@secured(["GET"], "auditor", "analyst")
def device_audits(request, device_id):
    """GET /api/devices/DEV-0001/audits/[?framework=CIS&limit=100] : the device's audit history."""
    device = Device.objects.filter(device_id=device_id).first()
    if device is None:
        return Response({"error": "Device not found."}, status=404)
    qs = AuditRun.objects.filter(device=device).select_related("result")
    fw = (request.query_params.get("framework") or "").upper()
    if fw:
        qs = qs.filter(framework=fw)
    try:
        limit = max(1, min(int(request.query_params.get("limit", 100)), 500))
    except ValueError:
        limit = 100
    return Response({"device_id": device.device_id, "hostname": device.hostname,
                     "runs": [_run_json(r) for r in qs[:limit]]})


@secured(["GET"], "auditor", "analyst")
def audit_run_detail(request, run_id):
    """GET /api/audit-runs/<id>/ : one audit with every criterion, passed and failed."""
    run = AuditRun.objects.select_related("result", "device").filter(id=run_id).first()
    if run is None:
        return Response({"error": "Audit run not found."}, status=404)
    criteria = (run.result.findings_json or {}).get("results", []) if run.result else []
    return Response({**_run_json(run), "device_id": run.device.device_id,
                     "hostname": run.device.hostname, "criteria": criteria})