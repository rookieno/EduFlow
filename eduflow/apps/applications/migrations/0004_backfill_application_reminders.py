from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.apps.registry import Apps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations import Migration as BaseMigration
from django.db.migrations import RunPython


def schedule_existing_applications(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    application_model = apps.get_model("applications", "Application")
    reminder_model = apps.get_model("applications", "ApplicationReminder")
    database = schema_editor.connection.alias
    kst = ZoneInfo("Asia/Seoul")
    applications = application_model.objects.using(database).filter(
        contact_date__gte=datetime.now(kst).date(),
    ).exclude(status="COMPLETED").exclude(email__iendswith=".invalid")
    reminders = reminder_model.objects.using(database)
    pending = []
    for application_id, contact_date in applications.values_list(
        "pk", "contact_date"
    ).iterator(chunk_size=500):
        scheduled_at = datetime.combine(contact_date, time(9), tzinfo=kst)
        pending.append(reminder_model(
            application_id=application_id,
            scheduled_at=scheduled_at,
            next_attempt_at=scheduled_at,
        ))
        if len(pending) == 500:
            reminders.bulk_create(pending)
            pending.clear()
    if pending:
        reminders.bulk_create(pending)


class Migration(BaseMigration):
    dependencies = [("applications", "0003_application_reminders")]

    operations = [RunPython(schedule_existing_applications, RunPython.noop)]
