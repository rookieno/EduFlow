from celery import shared_task
from django.utils.timezone import now

from eduflow.apps.applications.models import ApplicationReminder
from eduflow.apps.applications.models.application_reminder.manager import MAX_ATTEMPTS
from eduflow.async_task.send_contact_reminder import send_contact_reminder


@shared_task(name="applications.dispatch_due_reminders", ignore_result=True)
def dispatch_due_reminders() -> int:
    reminders = ApplicationReminder.objects
    current_time = now()
    reminders.expire_exhausted(at=current_time)
    due_ids = list(
        reminders.due(at=current_time).filter(attempt_count__lt=MAX_ATTEMPTS)
        .order_by("scheduled_at", "pk").values_list("pk", flat=True)[:100]
    )
    for reminder_id in due_ids:
        send_contact_reminder.delay(str(reminder_id))
    return len(due_ids)
