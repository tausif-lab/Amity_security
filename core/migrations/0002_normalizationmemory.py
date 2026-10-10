from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import pgvector.django.vector


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="NormalizationMemory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vendor", models.CharField(default="unknown", max_length=50)),
                ("command", models.TextField()),
                ("embedding", pgvector.django.vector.VectorField(dimensions=384)),
                ("normalized_path", models.CharField(blank=True, max_length=255)),
                ("normalized_value", models.JSONField(blank=True, null=True)),
                ("description", models.TextField(blank=True)),
                ("llm_confidence", models.FloatField(blank=True, null=True)),
                ("similarity_threshold", models.FloatField(default=0.88)),
                ("status", models.CharField(choices=[("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["vendor", "status"], name="core_normal_vendor_0e6cbd_idx")]},
        ),
    ]
