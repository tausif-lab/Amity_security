from django.urls import path
from . import views

urlpatterns = [
    path("me/", views.me, name="me"),
    path("normalization-reviews/", views.normalization_reviews, name="normalization_reviews"),
    path("normalization-reviews/<int:memory_id>/", views.resolve_normalization_review, name="resolve_normalization_review"),
    # path("uploads/", views.upload_config, name="upload_config"),
    path("normalize/", views.normalize_upload, name="normalize_upload"),
    path("uploads/<uuid:upload_id>/audit/", views.audit_upload, name="audit_upload"),
    path("uploads/<uuid:upload_id>/", views.get_upload, name="get_upload"),
    path("uploads/<uuid:upload_id>/remediation/propose/", views.propose_remediation, name="propose_remediation"),
    path("uploads/<uuid:upload_id>/remediation/execute/", views.execute_remediation_view, name="execute_remediation"),
    path("uploads/report/pdf/", views.download_combined_report_pdf, name="download_combined_report_pdf"),
    path("uploads/<uuid:upload_id>/remediation/propose/<str:rule_id>/", views.propose_single_remediation, name="propose_single_remediation"),
    path("uploads/<uuid:upload_id>/corrected-config/", views.download_corrected_config, name="download_corrected_config"),
]
