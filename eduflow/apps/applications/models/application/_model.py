from uuid import uuid4

from django.db import models

from eduflow.apps.applications.choices import ApplicationStatus
from eduflow.apps.applications.models.application.manager import ApplicationManager
from eduflow.apps.applications.models.application.mixins import (
    ApplicationReminderMixin,
    ApplicationStatusMixin,
)


class Application(ApplicationStatusMixin, ApplicationReminderMixin, models.Model):
    id = models.UUIDField(
        "접수번호", primary_key=True, default=uuid4, editable=False,
        help_text="교육 신청 한 건을 고유하게 식별하는 접수번호입니다.",
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.PROTECT, related_name="applications",
        verbose_name="신청 교육", help_text="신청자가 신청한 교육입니다.",
    )
    submission_id = models.UUIDField(
        "제출 식별자", unique=True, editable=False,
        help_text="동일한 제출 요청을 다시 보냈을 때 중복 접수를 막는 식별자입니다.",
    )
    submission_fingerprint = models.CharField(
        "제출 검증값", max_length=64, editable=False,
        help_text="재시도한 요청의 입력이 최초 제출과 일치하는지 확인하는 검증값입니다.",
    )
    name = models.CharField(
        "신청자 이름", max_length=100, help_text="교육을 신청한 사람의 이름입니다."
    )
    email = models.EmailField(
        "이메일", help_text="교육 안내와 연락에 사용할 신청자의 이메일 주소입니다."
    )
    address = models.CharField(
        "주소", max_length=500, help_text="교육 신청 시 신청자가 입력한 주소입니다."
    )
    contact_date = models.DateField(
        "연락 가능 날짜", help_text="신청자가 교육 관련 연락을 받을 수 있는 날짜입니다."
    )
    status = models.CharField(
        "신청 상태", max_length=12, choices=ApplicationStatus,
        default=ApplicationStatus.RECEIVED,
        help_text="신청 처리 진행 상황을 접수, 확인중, 완료로 구분합니다.",
    )
    completed_at = models.DateTimeField(
        "완료 시각", null=True, blank=True, editable=False,
        help_text="신청 상태를 완료로 변경한 시각입니다.",
    )
    created_at = models.DateTimeField(
        "접수 시각", auto_now_add=True, help_text="신청을 처음 접수한 시각입니다."
    )
    updated_at = models.DateTimeField(
        "수정 시각", auto_now=True, help_text="신청 정보를 마지막으로 수정한 시각입니다."
    )

    objects = ApplicationManager()

    class Meta:
        verbose_name = "교육 신청"
        verbose_name_plural = "교육 신청"
        permissions = [("export_application", "교육 신청 내보내기")]
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "contact_date"], name="app_status_contact_idx"),
            models.Index(fields=["contact_date"], name="app_contact_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ApplicationStatus.values),
                name="application_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(completed_at__isnull=True)
                | models.Q(status=ApplicationStatus.COMPLETED),
                name="application_completed_at_status",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)
