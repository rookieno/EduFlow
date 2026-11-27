import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from eduflow.apps.courses.choices import IntakeStatus
from eduflow.apps.courses.models import Course

from eduflow.apps.applications.exceptions import (
    IntakeClosed,
    SheetsExportLimitExceeded,
    SubmissionConflict,
)
from eduflow.apps.applications.models.application.queryset import ApplicationQuerySet
from eduflow.modules.google_sheets.gateway import GoogleSheetGateWay

if TYPE_CHECKING:
    from eduflow.apps.applications.models.application._model import Application


MAX_SHEETS_APPLICATIONS = 500


@dataclass(frozen=True)
class SheetsExportResult:
    count: int
    sheet_url: str


class ApplicationManager(models.Manager.from_queryset(ApplicationQuerySet)):
    def export_to_google_sheets(
        self, applications: models.QuerySet["Application"],
    ) -> SheetsExportResult:
        rows = [("접수번호", "교육", "이름", "이메일", "상태", "연락 가능일", "접수 시각", "완료 시각")]
        records = applications[:MAX_SHEETS_APPLICATIONS + 1].iterator(chunk_size=100)
        for index, application in enumerate(records, start=1):
            if index > MAX_SHEETS_APPLICATIONS:
                raise SheetsExportLimitExceeded(MAX_SHEETS_APPLICATIONS)
            rows.append((
                str(application.pk), application.course.title, application.name, application.email,
                application.get_status_display(), application.contact_date.isoformat(),
                timezone.localtime(application.created_at).isoformat(timespec="minutes"),
                timezone.localtime(application.completed_at).isoformat(timespec="minutes")
                if application.completed_at else "",
            ))
        gateway = GoogleSheetGateWay(
            spreadsheet_id=settings.GOOGLE_SHEETS_SPREADSHEET_ID,
            credentials_path=settings.GOOGLE_APPLICATION_CREDENTIALS,
        )
        title = f"신청 목록 {timezone.localtime():%Y-%m-%d %H-%M} {uuid4().hex[:8]}"
        sheet_url = gateway.create_tab(title=title, rows=rows)
        return SheetsExportResult(count=len(rows) - 1, sheet_url=sheet_url)

    def submit(
        self,
        *,
        course_slug: str,
        submission_id: UUID,
        name: str,
        email: str,
        address: str,
        contact_date: date,
    ) -> tuple["Application", bool]:
        """Return the application and whether this call created it."""
        name, email, address = name.strip(), self._normalize_email(email), address.strip()
        fingerprint = sha256(
            json.dumps([course_slug, name, email, address, contact_date.isoformat()]).encode()
        ).hexdigest()

        try:
            with transaction.atomic(using=self.db):
                course = (
                    Course.objects.using(self.db)
                    .select_for_update()
                    .get(slug=course_slug)
                )
                existing = self.filter(submission_id=submission_id).first()
                if existing is not None:
                    return self._replay(existing, fingerprint)

                now = timezone.now()
                self._validate_input(
                    name, email, address, contact_date, today=timezone.localdate(now)
                )
                status = course.intake_status(at=now)
                if status != IntakeStatus.OPEN:
                    raise IntakeClosed(status)

                application = self.create(
                    course=course,
                    submission_id=submission_id,
                    submission_fingerprint=fingerprint,
                    name=name,
                    email=email,
                    address=address,
                    contact_date=contact_date,
                )
                application.synchronize_contact_reminder()
                return application, True
        except IntegrityError:
            # Requests for different courses hold different locks but share the key space.
            existing = self.filter(submission_id=submission_id).first()
            if existing is None:
                raise
            return self._replay(existing, fingerprint)

    @staticmethod
    def _normalize_email(email: str) -> str:
        local, separator, domain = email.strip().rpartition("@")
        return f"{local}{separator}{domain.lower()}" if separator else domain

    @staticmethod
    def _replay(application: "Application", fingerprint: str) -> tuple["Application", bool]:
        if application.submission_fingerprint != fingerprint:
            raise SubmissionConflict
        return application, False

    @staticmethod
    def _validate_input(
        name: str, email: str, address: str, contact_date: date, *, today: date
    ) -> None:
        errors = {}
        if not name or len(name) > 100:
            errors["name"] = "이름은 1자 이상 100자 이하로 입력해 주세요."
        if not address or len(address) > 500:
            errors["address"] = "주소는 1자 이상 500자 이하로 입력해 주세요."
        try:
            validate_email(email)
        except ValidationError as exc:
            errors["email"] = exc.messages
        if len(email) > 254:
            errors["email"] = "이메일은 254자 이하로 입력해 주세요."
        if contact_date < today:
            errors["contact_date"] = "연락 가능 날짜는 오늘 이후로 선택해 주세요."
        if errors:
            raise ValidationError(errors)
