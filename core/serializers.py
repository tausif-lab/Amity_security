from rest_framework import serializers
from .models import DeviceUpload, RemediationLog


class DeviceUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceUpload
        fields = ["id", "vendor", "status", "created_at", "baseline_json",
                  "compliance_report", "source_format", "cache_status", "dual_call_status"]
        read_only_fields = fields


class RemediationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RemediationLog
        fields = ["id", "upload", "executed_by", "commands", "result", "created_at"]
        read_only_fields = fields