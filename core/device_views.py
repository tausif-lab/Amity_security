from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Tenant, Device
from .serializers import DeviceSerializer

# Must match the vendor names _load_rules() understands.
ALLOWED_VENDORS = {"cisco": "cisco", "juniper": "juniper", "junos": "juniper"}


@api_view(["GET", "POST"])
def devices(request):
    """GET /api/devices/[?tenant=Name&device_type=firewall]
       POST /api/devices/  (register a device)"""
    if request.method == "GET":
        qs = Device.objects.select_related("tenant").order_by("-id")

        tenant = request.query_params.get("tenant")
        if tenant:
            qs = qs.filter(tenant__name__iexact=tenant)

        device_type = request.query_params.get("device_type")
        if device_type:
            qs = qs.filter(device_type=device_type.lower())

        return Response(DeviceSerializer(qs, many=True).data)

    # ---- POST: register a new device ----
    d = request.data
    tenant_name = (d.get("tenant_name") or "").strip()
    hostname = (d.get("hostname") or "").strip()
    registered_by = (d.get("registered_by") or "").strip()
    serial = (d.get("serial_number") or "").strip()
    vendor = ALLOWED_VENDORS.get((d.get("vendor") or "").strip().lower())
    device_type = (d.get("device_type") or "").strip().lower()
    valid_types = dict(Device.DEVICE_TYPES)

    missing = [name for name, value in (("tenant_name", tenant_name),
                                        ("hostname", hostname),
                                        ("registered_by", registered_by)) if not value]
    if missing:
        return Response({"error": f"Required: {', '.join(missing)}"}, status=400)
    if not vendor:
        return Response({"error": "vendor must be 'cisco' or 'juniper'."}, status=400)
    if device_type not in valid_types:
        return Response({"error": f"device_type must be one of: {', '.join(valid_types)}."}, status=400)

    with transaction.atomic():
        tenant = (Tenant.objects.filter(name__iexact=tenant_name).first()
                  or Tenant.objects.create(name=tenant_name))
        if serial and Device.objects.filter(tenant=tenant, serial_number__iexact=serial).exists():
            return Response({"error": f"Serial number '{serial}' is already registered for this tenant."},
                            status=409)
        device = Device.objects.create(
            tenant=tenant,
            site=(d.get("site") or "").strip(),
            vendor=vendor,
            device_type=device_type,
            hostname=hostname,
            serial_number=serial,
            registered_by=registered_by,
        )
    return Response(DeviceSerializer(device).data, status=201)


@api_view(["GET"])
def device_detail(request, device_id):
    """GET /api/devices/DEV-0001/"""
    try:
        device = Device.objects.select_related("tenant").get(device_id=device_id)
    except Device.DoesNotExist:
        return Response({"error": "Device not found."}, status=404)
    return Response(DeviceSerializer(device).data)