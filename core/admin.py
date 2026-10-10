from django.contrib import admin
from .models import NormalizationMemory


@admin.register(NormalizationMemory)
class NormalizationMemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "vendor", "command", "llm_confidence", "status", "updated_at")
    list_filter = ("vendor", "status")
    search_fields = ("command", "description", "normalized_path")

# Register your models here.
