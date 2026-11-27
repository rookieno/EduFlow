from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.db.models import F, Manager
from django.utils.timezone import localdate, now

from eduflow.apps.applications.choices import ApplicationStatus, ReminderKind, ReminderStatus
from eduflow.apps.applications.models.application_reminder.queryset import (
    ApplicationReminderQuerySet,
)

if TYPE_CHECKING:
    from eduflow.apps.applications.models.application import Application
    from eduflow.apps.applications.models.application_reminder._model import ApplicationReminder


MAX_ATTEMPTS = 3
_LEASE = timedelta(minutes=5)
_KST = ZoneInfo("Asia/Seoul")
_ACTIVE = (ReminderStatus.PENDING, ReminderStatus.PROCESSING)
_TERMINAL_FOR_SAME_DATE = (ReminderStatus.SENT, ReminderStatus.FAILED)
_RELEASE = {"next_attempt_at": None, "claim_token": None, "lease_expires_at": None}


class ApplicationReminderManager(Manager.from_queryset(ApplicationReminderQuerySet)):
    @staticmethod
    def can_receive(application: "Application") -> bool:
        return (
            application.status != ApplicationStatus.COMPLETED
            and not application.email.lower().endswith(".invalid")
        )

    @staticmethod
    def scheduled_time(application: "Application") -> datetime:
        return datetime.combine(application.contact_date, time(9), tzinfo=_KST)

    def synchronize(self, application: "Application") -> None:
        """Adjust the reservation within the transaction that saves the application."""
        reminders = self.filter(application=application, kind=ReminderKind.CONTACT_DATE_NOTICE)
        active = reminders.filter(status__in=_ACTIVE)
        current_time = now()
        if not self.can_receive(application):
            active.update(status=ReminderStatus.CANCELLED, updated_at=current_time, **_RELEASE)
            return

        scheduled_at = self.scheduled_time(application)
        active.exclude(scheduled_at=scheduled_at).update(
            status=ReminderStatus.CANCELLED, updated_at=current_time, **_RELEASE,
        )
        if application.contact_date < localdate(current_time, _KST):
            return
        if reminders.filter(
            scheduled_at=scheduled_at, status__in=(*_ACTIVE, *_TERMINAL_FOR_SAME_DATE),
        ).exists():
            return
        self.create(
            application=application, kind=ReminderKind.CONTACT_DATE_NOTICE,
            scheduled_at=scheduled_at, next_attempt_at=scheduled_at,
        )

    def claim(self, reminder_id: UUID, *, at: datetime) -> "ApplicationReminder | None":
        token = uuid4()
        updated = self.get_queryset().due(at=at).filter(
            pk=reminder_id, attempt_count__lt=MAX_ATTEMPTS,
        ).update(
            status=ReminderStatus.PROCESSING, attempt_count=F("attempt_count") + 1,
            claim_token=token, lease_expires_at=at + _LEASE, next_attempt_at=None,
            updated_at=at,
        )
        if not updated:
            return None
        return self.filter(pk=reminder_id, claim_token=token).select_related(
            "application__course",
        ).first()

    def expire_exhausted(self, *, at: datetime) -> int:
        return self.filter(
            status=ReminderStatus.PROCESSING, lease_expires_at__lte=at,
            attempt_count__gte=MAX_ATTEMPTS,
        ).update(
            status=ReminderStatus.FAILED, last_error_code="LEASE_EXPIRED",
            updated_at=at, **_RELEASE,
        )

    def record_sent(self, reminder: "ApplicationReminder", *, at: datetime) -> bool:
        return bool(self._claim_queryset(reminder).update(
            status=ReminderStatus.SENT, sent_at=at, updated_at=at,
            last_error_code="", **_RELEASE,
        ))

    def record_failure(self, reminder: "ApplicationReminder", *, at: datetime, code: str) -> bool:
        retry = reminder.attempt_count < MAX_ATTEMPTS
        return bool(self._claim_queryset(reminder).update(
            status=ReminderStatus.PENDING if retry else ReminderStatus.FAILED,
            next_attempt_at=at + timedelta(minutes=5 * reminder.attempt_count) if retry else None,
            claim_token=None, lease_expires_at=None, last_error_code=code[:64], updated_at=at,
        ))

    def cancel_claim(self, reminder: "ApplicationReminder", *, at: datetime) -> bool:
        return bool(self._claim_queryset(reminder).update(
            status=ReminderStatus.CANCELLED, updated_at=at, **_RELEASE,
        ))

    def _claim_queryset(self, reminder: "ApplicationReminder") -> ApplicationReminderQuerySet:
        return self.get_queryset().filter(
            pk=reminder.pk, status=ReminderStatus.PROCESSING, claim_token=reminder.claim_token,
        )
