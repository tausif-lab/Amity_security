import uuid
from django.db import models
from django.contrib.auth.models import User
from pgvector.django import VectorField
from django.db.models import Q

class Tenant(models.Model):
    name = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Device(models.Model):
    DEVICE_TYPES = [
        ("router", "Router"),
        ("switch", "Switch"),
        ("firewall", "Firewall"),
        ("load_balancer", "Load Balancer"),
        ("wireless_controller", "Wireless Controller"),
        ("other", "Other"),
    ]

    device_id = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="devices")
    site = models.CharField(max_length=150, blank=True)
    vendor = models.CharField(max_length=50)
    device_type = models.CharField(max_length=30, choices=DEVICE_TYPES, default="other")   # NEW
    hostname = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=100, blank=True)
    registered_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.device_id:
            # Derived from the database primary key, so two simultaneous
            # registrations can never receive the same ID.
            self.device_id = f"DEV-{self.pk:04d}"
            super().save(update_fields=["device_id"])



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
    device = models.ForeignKey("Device", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="uploads")
    remediation_json = models.JSONField(null=True, blank=True)

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


class ConfigSnapshot(models.Model):
    """Read-only, timestamped copy of one device's config at the moment it was pushed."""
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="snapshots")
    upload = models.OneToOneField(DeviceUpload, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="config_snapshot")
    raw_config = models.TextField()
    normalized_config = models.JSONField()
    config_hash = models.CharField(max_length=64, db_index=True)    # SHA-256 of raw_config
    uploaded_by = models.CharField(max_length=150)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_latest = models.BooleanField(default=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        constraints = [
            # The database itself guarantees one "latest" snapshot per device.
            models.UniqueConstraint(fields=["device"], condition=Q(is_latest=True),
                                    name="one_latest_snapshot_per_device"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("ConfigSnapshot is read-only once created.")
        super().save(*args, **kwargs)


class ComplianceResult(models.Model):
    snapshot = models.ForeignKey(ConfigSnapshot, on_delete=models.CASCADE, related_name="results")
    framework = models.CharField(max_length=20)
    score = models.FloatField()
    pass_count = models.PositiveIntegerField()
    fail_count = models.PositiveIntegerField()
    unknown_count = models.PositiveIntegerField(default=0)
    findings_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class ChangeEvent(models.Model):
    """Created now, filled in the next step (the difflib comparison)."""
    CHANGE_TYPES = [("added", "Added"), ("removed", "Removed")]
    snapshot = models.ForeignKey(ConfigSnapshot, on_delete=models.CASCADE, related_name="changes")
    previous_snapshot = models.ForeignKey(ConfigSnapshot, on_delete=models.CASCADE, related_name="+")
    change_type = models.CharField(max_length=10, choices=CHANGE_TYPES)
    line_number = models.PositiveIntegerField()
    line_text = models.TextField()
    parent_block = models.CharField(max_length=255, blank=True)


class QueryLog(models.Model):
    """Audit trail: every question asked and the filter the LLM produced for it."""
    user_email = models.CharField(max_length=255, blank=True)
    question = models.TextField()
    generated_filter = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20)             # ok | unsupported | error
    result_count = models.PositiveIntegerField(default=0)
    executed_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-executed_at"]


class AuditSchedule(models.Model):
    """Re-audit the latest pushed snapshot of every selected device on a timer."""
    framework = models.CharField(max_length=20, default="CIS")
    devices = models.ManyToManyField(Device, related_name="audit_schedules")
    interval_minutes = models.PositiveIntegerField()               # 1, 2, 60, 120, 1440, ...
    daily_at = models.TimeField(null=True, blank=True)             # only for whole-day intervals
    timezone = models.CharField(max_length=50, default="UTC")      # how daily_at is read
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditRun(models.Model):
    """One scheduled audit of one device, with its timestamp. Written even when skipped."""
    STATUS_CHOICES = [("ok", "OK"), ("skipped", "Skipped"), ("error", "Error")]
    schedule = models.ForeignKey(AuditSchedule, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="runs")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="audit_runs")
    framework = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    message = models.CharField(max_length=500, blank=True)
    result = models.ForeignKey(ComplianceResult, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="runs")
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at", "-id"]
        indexes = [models.Index(fields=["device", "-ran_at"])]
 