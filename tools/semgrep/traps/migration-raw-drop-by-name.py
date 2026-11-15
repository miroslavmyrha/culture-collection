from django.db import migrations, models


class Migration(migrations.Migration):
    operations = [
        # ruleid: migration-raw-drop-by-name
        migrations.RunSQL("DROP INDEX lab_sample_box_id_4f2a1c3e;"),
        # ruleid: migration-raw-drop-by-name
        migrations.RunSQL(
            sql="ALTER TABLE lab_sample DROP CONSTRAINT lab_sample_box_id_9b3c2d1e_fk_lab_box_id;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # ok: migration-raw-drop-by-name
        migrations.RunSQL("DROP INDEX CONCURRENTLY IF EXISTS sample_note_trgm;"),
        # ok: migration-raw-drop-by-name
        migrations.RemoveIndex(model_name="sample", name="sample_status_idx"),
        # ok: migration-raw-drop-by-name
        migrations.RunSQL("CREATE INDEX IF NOT EXISTS sample_note_trgm ON lab_sample USING gin (note);"),
        # ok: migration-raw-drop-by-name
        migrations.AddField(model_name="sample", name="note", field=models.TextField(default="")),
    ]
