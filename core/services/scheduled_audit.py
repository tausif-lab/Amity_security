"""Runs due audit schedules. Deterministic only: no LLM calls."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from compliance.services.rule_engine import compliance_engine
from core.models import AuditRun, AuditSchedule, ComplianceResult, ConfigSnapshot


def _is_daily(s):
    return s.daily_at is not None and s.interval_minutes % 1440 == 0


def first_run(s, now):
    """When a new (or re-timed) schedule fires first."""
    if _is_daily(s):
        tz = ZoneInfo(s.timezone)
        local = now.astimezone(tz)
        candidate = datetime.combine(local.date(), s.daily_at, tzinfo=tz)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(dt_timezone.utc)
    return now    # interval schedules audit at the next tick, then every N minutes


def next_after(s, now):
    """The following run time. Missed runs after downtime collapse into one."""
    if _is_daily(s):
        tz = ZoneInfo(s.timezone)
        day = now.astimezone(tz).date() + timedelta(days=s.interval_minutes // 1440)
        return datetime.combine(day, s.daily_at, tzinfo=tz).astimezone(dt_timezone.utc)
    step = timedelta(minutes=s.interval_minutes)
    nxt = s.next_run_at + step
    if nxt <= now:
        nxt += step * ((now - nxt) // step + 1)
    return nxt


def audit_device(schedule, device):
    """Audit one device's latest pushed snapshot. Always leaves an AuditRun row."""
    from core.views import _load_rules          # reuse the one rule-file lookup

    def record(status, message, result=None):
        return AuditRun.objects.create(
            schedule=schedule, device=device, framework=schedule.framework,
            status=status, message=message[:500], result=result)

    snap = ConfigSnapshot.objects.filter(device=device, is_latest=True).first()
    if snap is None:
        return record("skipped", "No pushed configuration for this device yet. Push an audit result first.")
    try:
        report = compliance_engine(snap.normalized_config, _load_rules(schedule.framework, device.vendor))
    except Exception as exc:
        return record("error", f"Audit failed: {exc}")

    s = report["summary"]
    total = s.get("total", 0)
    findings = json.loads(json.dumps(report["results"], default=str))

    # Same snapshot + same framework + same findings as last time: share that row
    # instead of storing an identical copy every minute.
    previous = (ComplianceResult.objects.filter(snapshot=snap, framework=schedule.framework)
                .order_by("-created_at", "-id").first())
    if previous is not None and (previous.findings_json or {}).get("results") == findings:
        result, note = previous, " (no change since the last audit)"
    else:
        result = ComplianceResult.objects.create(
            snapshot=snap, framework=schedule.framework,
            score=round(100 * s.get("passed", 0) / total, 1) if total else 0.0,
            pass_count=s.get("passed", 0), fail_count=s.get("failed", 0),
            unknown_count=s.get("unknown", 0) + s.get("manual", 0),
            findings_json={"results": findings})
        note = ""
    return record("ok", f"{result.pass_count} passed, {result.fail_count} failed, "
                        f"{result.unknown_count} undecided ({result.score}%){note}", result)


def audit_schedule_devices(schedule):
    return [audit_device(schedule, d) for d in schedule.devices.all()]


def run_due_schedules(now=None):
    """Audit every device of every enabled schedule that is due. Returns the audit count."""
    now = now or timezone.now()
    audited = 0
    due_ids = list(AuditSchedule.objects.filter(enabled=True, next_run_at__lte=now)
                   .values_list("id", flat=True))
    for sid in due_ids:
        with transaction.atomic():
            # Claim the schedule first so two overlapping ticks can never run it twice.
            schedule = (AuditSchedule.objects.select_for_update(skip_locked=True)
                        .filter(id=sid, enabled=True, next_run_at__lte=now).first())
            if schedule is None:
                continue
            schedule.next_run_at = next_after(schedule, now)
            schedule.last_run_at = now
            schedule.save(update_fields=["next_run_at", "last_run_at"])
        audited += len(audit_schedule_devices(schedule))
    return audited