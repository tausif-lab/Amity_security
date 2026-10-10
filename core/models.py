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

    # Provenance of the normalization, so a report can always explain how its
    # baseline was produced: which ingestion format was detected, whether the
    # LLM was called at all, and whether the dual-call check agreed.
    source_format = models.CharField(max_length=20, default="cli")
    cache_status = models.CharField(max_length=20, default="miss")
    dual_call_status = models.CharField(max_length=20, default="single")


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


class NormalizationCache(models.Model):
    """Layer 1 of the parser pipeline: an exact-match cache of LLM normalizations.

    The key is a hash of vendor + model + schema + prompt + config text. Editing
    the prompt or the schema therefore changes the key and invalidates every
    entry, instead of silently serving a baseline that was produced by different
    instructions. Only the raw model output is stored: the deterministic
    overrides (fact extraction, human-approved mappings) are cheap and must
    re-run on every upload so they always reflect the current rule set.
    """

    config_hash = models.CharField(max_length=64, unique=True)
    vendor = models.CharField(max_length=50, default="unknown")
    model = models.CharField(max_length=100, blank=True)
    normalized_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    hit_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["vendor"])]


class ComplianceSnapshot(models.Model):
    """One normalized baseline per upload, kept as a device's audit timeline.

    Drift detection compares the newest snapshot for a hostname against the one
    before it, so keeping one row per upload (rather than overwriting a single
    "current" row) preserves the full history of how a device changed.
    """

    hostname = models.CharField(max_length=255, db_index=True)
    vendor = models.CharField(max_length=50, default="unknown")
    upload = models.ForeignKey(DeviceUpload, on_delete=models.CASCADE,
                               related_name="snapshots", null=True, blank=True)
    baseline_json = models.JSONField()
    summary = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["hostname", "vendor", "-created_at"])]
