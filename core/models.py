import uuid
from django.db import models
from django.contrib.auth.models import User
from pgvector.django import VectorField


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
    original_config_text = models.TextField(null=True, blank=True)

    baseline_json = models.JSONField(null=True, blank=True)
    compliance_report = models.JSONField(null=True, blank=True)


class RemediationLog(models.Model):
    """Audit trail for any remediation actually executed on a device."""
    upload = models.ForeignKey(DeviceUpload, on_delete=models.CASCADE, related_name="remediation_logs")
    executed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    commands = models.JSONField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class NormalizationMemory(models.Model):
    """A reusable, human-reviewable interpretation of one config command."""
    STATUS_CHOICES = [("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")]

    vendor = models.CharField(max_length=50, default="unknown")
    command = models.TextField()
    embedding = VectorField(dimensions=384)
    # Dot path and JSON value make an approved memory safe to apply deterministically.
    normalized_path = models.CharField(max_length=255, blank=True)
    normalized_value = models.JSONField(null=True, blank=True)
    description = models.TextField(blank=True)
    llm_confidence = models.FloatField(null=True, blank=True)
    similarity_threshold = models.FloatField(default=0.88)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["vendor", "status"])]
