from django.urls import path
from . import views
from . import device_views
from . import snapshot_views
from . import analysis_views
urlpatterns = [
    path("devices/", device_views.devices, name="devices"),
    path("devices/<str:device_id>/", device_views.device_detail, name="device_detail"),
    path("health/", views.health, name="health"),
    path("me/", views.me, name="me"),
    path("frameworks/", views.list_frameworks, name="list_frameworks"),
    path("cache/stats/", views.cache_report, name="cache_stats"),
    path("cache/clear/", views.cache_invalidate, name="cache_clear"),
    path("normalization-reviews/", views.normalization_reviews, name="normalization_reviews"),
    path("normalization-reviews/<int:memory_id>/", views.resolve_normalization_review, name="resolve_normalization_review"),
    path("uploads/", views.upload_config, name="upload_config"),
    path("normalize/", views.normalize_upload, name="normalize_upload"),
    path("uploads/<uuid:upload_id>/audit/", views.audit_upload, name="audit_upload"),
    path("uploads/<uuid:upload_id>/", views.get_upload, name="get_upload"),
    path("uploads/<uuid:upload_id>/drift/", views.drift_for_upload, name="drift_for_upload"),
    path("devices/<str:hostname>/history/", views.device_history, name="device_history"),
    path("uploads/<uuid:upload_id>/remediation/propose/", views.propose_remediation, name="propose_remediation"),
    path("uploads/<uuid:upload_id>/remediation/execute/", views.execute_remediation_view, name="execute_remediation"),
    path("uploads/report/pdf/", views.download_combined_report_pdf, name="download_combined_report_pdf"),
    path("uploads/<uuid:upload_id>/remediation/propose/<str:rule_id>/", views.propose_single_remediation, name="propose_single_remediation"),
    path("uploads/<uuid:upload_id>/corrected-config/", views.download_corrected_config, name="download_corrected_config"),
    path("uploads/<uuid:upload_id>/push/", snapshot_views.push_upload, name="push_upload"),
    path("devices/<str:device_id>/snapshots/", snapshot_views.device_snapshots, name="device_snapshots"),
    path("snapshots/<int:snapshot_id>/", snapshot_views.snapshot_detail, name="snapshot_detail"),
    path("analysis/overview/", analysis_views.analysis_overview, name="analysis_overview"),
    path("devices/<str:device_id>/analysis/", analysis_views.device_analysis, name="device_analysis"),
    path("snapshots/<int:snapshot_id>/changes/", analysis_views.snapshot_changes, name="snapshot_changes"),
    
    path("analysis/query/", analysis_views.ask_devices, name="ask_devices"),
    path("analysis/query/fields/", analysis_views.ask_devices_fields, name="ask_devices_fields"),
]
