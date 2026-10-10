from rest_framework import serializers
from .models import DeviceUpload, RemediationLog


class DeviceUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceUpload
        fields = ["id", "vendor", "status", "created_at", "baseline_json", "compliance_report"]
        read_only_fields = ["id", "status", "created_at", "baseline_json", "compliance_report"]


class RemediationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RemediationLog
        fields = ["id", "upload", "executed_by", "commands", "result", "created_at"]
        read_only_fields = fields