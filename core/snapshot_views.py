import hashlib

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Device, DeviceUpload, ConfigSnapshot, ComplianceResult, ChangeEvent
from .diff_utils import compute_changes

def _result_row(r):
    return {"framework": r.framework, "score": r.score, "pass_count": r.pass_count,
            "fail_count": r.fail_count, "unknown_count": r.unknown_count,
            "created_at": r.created_at}


@api_view(["POST"])
def push_upload(request, upload_id):
    """POST /api/uploads/<id>/push/  body: {"uploaded_by": "name"}
    Saves this audited upload as a read-only snapshot on its device's timeline,
    with its compliance result. Nothing is sent to any network device."""
    try:
        upload = DeviceUpload.objects.select_related("device").get(id=upload_id)
    except DeviceUpload.DoesNotExist:
        return Response({"error": "Upload not found."}, status=404)

    if upload.device is None:
        return Response({"error": "This upload is not linked to a device. Upload again with a device_id."},
                        status=400)
    if not (upload.compliance_report and upload.baseline_json and upload.original_config_text):
        return Response({"error": "Upload has no compliance report yet."}, status=400)

    existing = ConfigSnapshot.objects.filter(upload=upload).first()
    if existing:
        return Response({"status": "already_pushed", "snapshot_id": existing.id,
                         "device_id": upload.device.device_id})

    if upload.status == "review" and not request.data.get("confirm_unreviewed"):
        return Response({"error": "Normalization still has items awaiting human review. "
                                  "Resolve them, or send confirm_unreviewed=true."}, status=409)

    user = getattr(request, "user", None)
    uploaded_by = (getattr(user, "email", "") or request.data.get("uploaded_by") or "").strip() or "unknown"

    raw = upload.original_config_text
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    report = upload.compliance_report
    s = report["summary"]
    total = s.get("total", 0)

    with transaction.atomic():
        # Lock the device row so two simultaneous pushes cannot both become "latest".
        device = Device.objects.select_for_update().get(pk=upload.device_id)
        latest = ConfigSnapshot.objects.filter(device=device, is_latest=True).first()
        if latest and latest.config_hash == digest:
            return Response({"status": "no_changes", "snapshot_id": latest.id,
                             "device_id": device.device_id, "config_hash": digest})

        ConfigSnapshot.objects.filter(device=device, is_latest=True).update(is_latest=False)
        snap = ConfigSnapshot.objects.create(
            device=device, upload=upload, raw_config=raw,
            normalized_config=upload.baseline_json, config_hash=digest,
            uploaded_by=uploaded_by,
        )
        result = ComplianceResult.objects.create(
            snapshot=snap,
            framework=report.get("framework", "CIS"),
            score=round(100 * s.get("passed", 0) / total, 1) if total else 0.0,
            pass_count=s.get("passed", 0),
            fail_count=s.get("failed", 0),
            unknown_count=s.get("unknown", 0) + s.get("manual", 0),
            findings_json={"results": report["results"], "remediation": upload.remediation_json or []},
        )

        # Raw line diff against the previous snapshot (`latest` is the one that was latest
        # before this push). The first snapshot of a device has nothing to compare with.
        events = compute_changes(latest.raw_config, raw) if latest else []
        ChangeEvent.objects.bulk_create([
            ChangeEvent(snapshot=snap, previous_snapshot=latest, change_type=kind,
                        line_number=number, line_text=text, parent_block=parent)
            for kind, number, text, parent in events
        ])
        added = sum(1 for e in events if e[0] == "added")
        removed = len(events) - added

    return Response({"status": "pushed", "snapshot_id": snap.id, "device_id": device.device_id,
                     "hostname": device.hostname, "config_hash": digest,
                     "uploaded_by": uploaded_by, "uploaded_at": snap.uploaded_at,
                     "result": _result_row(result),
                     "changes": {"first_snapshot": latest is None, "added": added, "removed": removed}},
                    status=201)


@api_view(["GET"])
def device_snapshots(request, device_id):
    """GET /api/devices/DEV-0001/snapshots/ - the device's timeline, newest first."""
    try:
        device = Device.objects.select_related("tenant").get(device_id=device_id)
    except Device.DoesNotExist:
        return Response({"error": "Device not found."}, status=404)
    snaps = device.snapshots.prefetch_related("results")
    return Response({
        "device_id": device.device_id, "hostname": device.hostname, "tenant": device.tenant.name,
        "snapshots": [{
            "id": s.id, "uploaded_at": s.uploaded_at, "uploaded_by": s.uploaded_by,
            "config_hash": s.config_hash, "is_latest": s.is_latest,
            "results": [_result_row(r) for r in s.results.all()],
        } for s in snaps],
    })


@api_view(["GET"])
def snapshot_detail(request, snapshot_id):
    """GET /api/snapshots/<id>/ - normalized config and full findings (raw text is not served)."""
    try:
        snap = ConfigSnapshot.objects.select_related("device").prefetch_related("results").get(id=snapshot_id)
    except ConfigSnapshot.DoesNotExist:
        return Response({"error": "Snapshot not found."}, status=404)
    return Response({
        "id": snap.id, "device_id": snap.device.device_id, "hostname": snap.device.hostname,
        "uploaded_at": snap.uploaded_at, "uploaded_by": snap.uploaded_by,
        "config_hash": snap.config_hash, "is_latest": snap.is_latest,
        "normalized_config": snap.normalized_config,
        "results": [{**_result_row(r), "findings": r.findings_json} for r in snap.results.all()],
    })