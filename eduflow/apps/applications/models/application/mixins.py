from django.utils.timezone import now

from eduflow.apps.applications.choices import ApplicationStatus


class ApplicationReminderMixin:
    def synchronize_contact_reminder(self) -> None:
        from eduflow.apps.applications.models.application_reminder import ApplicationReminder

        ApplicationReminder.objects.db_manager(self._state.db).synchronize(self)


class ApplicationStatusMixin:
    def change_status(self, status: ApplicationStatus) -> None:
        if self.status == status:
            return

        self.status = status
        self.completed_at = now() if status == ApplicationStatus.COMPLETED else None
