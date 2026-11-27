from datetime import datetime

from django.utils import timezone

from eduflow.apps.applications.choices import ApplicationStatus
from eduflow.apps.courses.choices import IntakeStatus


class CourseIntakeMixin:
    def intake_status(self, *, at: datetime | None = None) -> IntakeStatus:
        if not self.is_published:
            return IntakeStatus.UNPUBLISHED
        if (at if at is not None else timezone.now()) >= self.application_deadline_at:
            return IntakeStatus.APPLICATION_DEADLINE_PASSED
        completed_count = self.applications.filter(status=ApplicationStatus.COMPLETED).count()
        if completed_count >= self.capacity:
            return IntakeStatus.COURSE_FULL
        return IntakeStatus.OPEN
