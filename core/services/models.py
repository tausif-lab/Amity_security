import uuid
from django.db import models
from django.contrib.auth.models import User


class DeviceUpload(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("review", "Needs Review"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    baseline_json = models.JSONField(null=True, blank=True)
    compliance_report = models.JSONField(null=True, blank=True)


class RemediationLog(models.Model):
    """Audit trail for any remediation actually executed on a device."""
    upload = models.ForeignKey(DeviceUpload, on_delete=models.CASCADE, related_name="remediation_logs")
    executed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    commands = models.JSONField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)