"""Ensure pgvector exists before any VectorField table is created.

`CREATE EXTENSION IF NOT EXISTS vector` is what makes `vector(384)` a valid
column type. It only has to run once per database, but Django creates a fresh
*test* database for every test run, so the extension must be enabled by a
migration that runs before `NormalizationMemory.embedding` is created --
otherwise `manage.py test` fails with `type "vector" does not exist`.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
