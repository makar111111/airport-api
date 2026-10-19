from django.db import migrations


def add_airplane_exclusion(apps, schema_editor):
    """PostgreSQL protects direct ORM writes as well as the locked services."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    schema_editor.execute(
        "ALTER TABLE airport_flight "
        "ADD CONSTRAINT flight_airplane_no_overlap "
        "EXCLUDE USING gist ("
        "airplane_id WITH =, "
        "tstzrange(departure_time, arrival_time, '[)') WITH &&"
        ")"
    )


def remove_airplane_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "ALTER TABLE airport_flight "
            "DROP CONSTRAINT flight_airplane_no_overlap"
        )


class Migration(migrations.Migration):
    dependencies = [("airport", "0002_catalogue_validation")]

    operations = [
        migrations.RunPython(
            add_airplane_exclusion, remove_airplane_exclusion,
        ),
    ]
