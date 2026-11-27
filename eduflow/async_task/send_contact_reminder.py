from uuid import UUID

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils.timezone import now

from eduflow.apps.applications.models import ApplicationReminder


@shared_task(
    name="applications.send_contact_reminder", ignore_result=True,
    acks_late=True, soft_time_limit=45, time_limit=60,
)
def send_contact_reminder(reminder_id: str) -> bool:
    reminders = ApplicationReminder.objects
    reminder = reminders.claim(UUID(reminder_id), at=now())
    if reminder is None:
        return False

    application = reminder.application
    if (
        not reminders.can_receive(application)
        or reminder.scheduled_at != reminders.scheduled_time(application)
    ):
        reminders.cancel_claim(reminder, at=now())
        return False

    try:
        sent = send_mail(
            "교육 연락 가능일 안내 · EduFlow",
            (
                f"{application.name}님, {application.course.title}의 연락 가능일은 "
                f"{application.contact_date:%Y-%m-%d}입니다.\n"
                "교육 신청 정보를 확인해 주세요."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [application.email],
            fail_silently=False,
        )
    except Exception as exc:
        # Store only the error class. Mail providers can include recipient data in messages.
        reminders.record_failure(reminder, at=now(), code=type(exc).__name__)
        return False
    if not sent:
        reminders.record_failure(reminder, at=now(), code="NOT_ACCEPTED")
        return False
    return reminders.record_sent(reminder, at=now())
