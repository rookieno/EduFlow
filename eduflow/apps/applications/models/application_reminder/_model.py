from uuid import uuid4

from django.db.models import (
    CASCADE, CharField, DateTimeField, ForeignKey, Index, Model, PositiveSmallIntegerField,
    Q, UUIDField, UniqueConstraint,
)

from eduflow.apps.applications.choices import ReminderKind, ReminderStatus
from eduflow.apps.applications.models.application_reminder.manager import (
    ApplicationReminderManager,
)


class ApplicationReminder(Model):
    id = UUIDField(
        "예약 ID", primary_key=True, default=uuid4, editable=False,
        help_text="메일 안내 예약을 고유하게 식별하는 값입니다.",
    )
    application = ForeignKey(
        "applications.Application", on_delete=CASCADE, related_name="reminders",
        verbose_name="신청", help_text="안내 메일을 발송할 대상 신청입니다.",
    )
    kind = CharField(
        "안내 종류", max_length=32, choices=ReminderKind,
        default=ReminderKind.CONTACT_DATE_NOTICE, help_text="예약된 안내 메일의 목적입니다.",
    )
    status = CharField(
        "발송 상태", max_length=12, choices=ReminderStatus, default=ReminderStatus.PENDING,
        help_text="예약부터 발송 요청 수락, 취소 또는 실패까지의 진행 상태입니다.",
    )
    scheduled_at = DateTimeField(
        "예약 시각", help_text="신청자가 선택한 연락 가능일의 한국 시간 오전 9시입니다.",
    )
    next_attempt_at = DateTimeField(
        "다음 시도 시각", blank=True, null=True,
        help_text="다음 발송 시도가 가능한 시각입니다.",
    )
    attempt_count = PositiveSmallIntegerField(
        "시도 횟수", default=0, help_text="Worker가 발송 처리를 선점한 횟수입니다.",
    )
    claim_token = UUIDField(
        "선점 식별자", blank=True, null=True, editable=False,
        help_text="현재 예약을 처리 중인 Worker의 시도를 식별합니다.",
    )
    lease_expires_at = DateTimeField(
        "선점 만료 시각", blank=True, null=True, editable=False,
        help_text="중단된 발송 시도를 다시 가져올 수 있는 시각입니다.",
    )
    sent_at = DateTimeField(
        "발송 수락 시각", blank=True, null=True, editable=False,
        help_text="메일 백엔드가 발송 요청을 수락한 시각입니다.",
    )
    provider_message_id = CharField(
        "메일 제공자 ID", max_length=255, blank=True, editable=False,
        help_text="메일 제공자가 발송 결과에서 추적용 식별자를 반환하면 저장합니다.",
    )
    last_error_code = CharField(
        "최근 실패 코드", max_length=64, blank=True, editable=False,
        help_text="마지막 발송 실패의 분류 코드이며 신청자 정보는 저장하지 않습니다.",
    )
    created_at = DateTimeField(
        "생성 시각", auto_now_add=True, help_text="예약을 처음 기록한 시각입니다.",
    )
    updated_at = DateTimeField(
        "갱신 시각", auto_now=True, help_text="예약이나 발송 상태를 마지막으로 갱신한 시각입니다.",
    )

    objects = ApplicationReminderManager()

    class Meta:
        verbose_name = "안내 메일 발송 예약"
        verbose_name_plural = "안내 메일 발송 예약"
        constraints = [
            UniqueConstraint(
                fields=["application", "kind"],
                condition=Q(status__in=(ReminderStatus.PENDING, ReminderStatus.PROCESSING)),
                name="app_reminder_one_active_kind",
            ),
        ]
        indexes = [
            Index(
                fields=["next_attempt_at"], condition=Q(status=ReminderStatus.PENDING),
                name="app_reminder_pending_due_idx",
            ),
            Index(
                fields=["lease_expires_at"], condition=Q(status=ReminderStatus.PROCESSING),
                name="app_reminder_lease_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)
