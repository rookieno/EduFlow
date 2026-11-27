from django.db.models import TextChoices


class ApplicationStatus(TextChoices):
    RECEIVED = "RECEIVED", "접수"
    IN_REVIEW = "IN_REVIEW", "확인중"
    COMPLETED = "COMPLETED", "완료"


class ReminderKind(TextChoices):
    CONTACT_DATE_NOTICE = "CONTACT_DATE_NOTICE", "연락 가능일 안내"


class ReminderStatus(TextChoices):
    PENDING = "PENDING", "발송 대기"
    PROCESSING = "PROCESSING", "발송 처리 중"
    SENT = "SENT", "발송 완료"
    CANCELLED = "CANCELLED", "발송 취소"
    FAILED = "FAILED", "발송 실패"
