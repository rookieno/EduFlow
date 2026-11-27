from datetime import datetime
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from eduflow.apps.applications.choices import ReminderStatus

if TYPE_CHECKING:
    from eduflow.apps.applications.models.application_reminder._model import ApplicationReminder


class ApplicationReminderQuerySet(QuerySet):
    def due(self, *, at: datetime) -> QuerySet["ApplicationReminder"]:
        return self.filter(
            Q(status=ReminderStatus.PENDING, next_attempt_at__lte=at)
            | Q(status=ReminderStatus.PROCESSING, lease_expires_at__lte=at)
        )
