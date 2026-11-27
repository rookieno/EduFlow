from django.db.models import TextChoices


class IntakeStatus(TextChoices):
    OPEN = "OPEN", "접수 가능"
    UNPUBLISHED = "UNPUBLISHED", "미공개"
    COURSE_FULL = "COURSE_FULL", "정원 마감"
    APPLICATION_DEADLINE_PASSED = "APPLICATION_DEADLINE_PASSED", "신청 기간 종료"
