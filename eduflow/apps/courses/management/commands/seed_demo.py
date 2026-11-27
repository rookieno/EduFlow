from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from hashlib import sha256
from re import fullmatch
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.management.base import BaseCommand, CommandError
from django.db.transaction import atomic
from django.utils.timezone import get_current_timezone, localdate, now

from eduflow.apps.applications.choices import ApplicationStatus, ReminderStatus
from eduflow.apps.applications.models import Application, ApplicationReminder
from eduflow.apps.applications.models.application_reminder.manager import MAX_ATTEMPTS
from eduflow.apps.courses.models import Course

if TYPE_CHECKING:
    from faker import Faker


@dataclass(frozen=True)
class DemoCourse:
    slug: str
    title: str
    tagline: str
    curriculum: tuple[str, ...]
    capacity: int
    deadline_days: int
    application_count: int


_COURSES = (
    DemoCourse(
        "digital-project-lab", "디지털 프로젝트 랩",
        "아이디어를 작동하는 프로토타입으로 만드는 실습 과정",
        (
            "사용자 문제 정의와 아이디어 발굴",
            "화면과 서비스 흐름 설계",
            "프로토타입 제작과 사용자 피드백",
        ),
        24, 14, 3,
    ),
    DemoCourse(
        "ux-research-workshop", "UX 리서치 워크숍",
        "인터뷰부터 문제 정의까지 사용자 관점에서 설계합니다.",
        ("조사 질문 만들기", "사용자 인터뷰 실습", "인사이트 정리"),
        18, 9, 4,
    ),
    DemoCourse(
        "python-data-studio", "파이썬 데이터 스튜디오",
        "데이터를 정리하고 작은 분석 보고서를 완성합니다.",
        ("데이터 기초", "표와 그래프 읽기", "결과 발표"),
        20, 15, 3,
    ),
    DemoCourse(
        "product-storytelling", "제품 스토리텔링",
        "복잡한 기능을 이해하기 쉬운 제품 이야기로 전달합니다.",
        ("청중과 메시지", "사용자 여정 구성", "피드백과 수정"),
        12, 6, 3,
    ),
    DemoCourse(
        "service-prototype-clinic", "서비스 프로토타입 클리닉",
        "한 가지 가설을 작동하는 화면으로 검증합니다.",
        ("가설 선택", "프로토타입 제작", "검증 결과 공유"),
        1, 8, 1,
    ),
    DemoCourse(
        "design-sprint-archive", "디자인 스프린트 실습",
        "짧은 스프린트로 아이디어를 구체화합니다.",
        ("스프린트 계획", "아이디어 스케치", "검증 질문 작성"),
        16, -2, 2,
    ),
)

_STATUSES = (
    ApplicationStatus.RECEIVED,
    ApplicationStatus.IN_REVIEW,
    ApplicationStatus.COMPLETED,
)


def _demo_submission_id(sample: DemoCourse, slot: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"eduflow:demo:{sample.slug}:{slot}")


def _delete_demo_applications(course: Course, sample: DemoCourse) -> int:
    sample_ids = (
        _demo_submission_id(sample, slot)
        for slot in range(1, sample.application_count + 1)
    )
    removable = [
        pk
        for pk, key, fingerprint in course.applications.filter(
            submission_id__in=sample_ids
        ).values_list("pk", "submission_id", "submission_fingerprint")
        if fingerprint == sha256(key.bytes).hexdigest()
    ]
    _, deleted = course.applications.filter(pk__in=removable).delete()
    return deleted.get(Application._meta.label, 0)


def _is_demo_course(course: Course, sample: DemoCourse) -> bool:
    return (
        course.title == sample.title
        and course.tagline == sample.tagline
        and course.curriculum == list(sample.curriculum)
        and course.capacity == sample.capacity
        and course.is_published
        and not course.course_image
        and not course.course_image_alt
    )


def _demo_name(fake: "Faker") -> str:
    for _ in range(100):
        name = fake.unique.name()
        if fullmatch(r"[가-힣]{3}", name):
            return name
    raise CommandError("Faker에서 세 글자 한글 이름을 생성하지 못했습니다.")


def _seed_mail_history(application: Application) -> bool:
    if application.reminders.exists():
        return False

    sent_at = None
    attempt_count = 0
    last_error_code = ""
    if application.status == ApplicationStatus.COMPLETED:
        status = ReminderStatus.CANCELLED
        scheduled_at = ApplicationReminder.objects.scheduled_time(application)
        recorded_at = application.completed_at or application.updated_at
    else:
        # The application's current contact date is kept for the list filters.
        # These terminal records represent a previous delivery schedule.
        scheduled_at = datetime.combine(
            localdate(application.created_at), time(9), tzinfo=get_current_timezone(),
        )
        if scheduled_at > application.created_at:
            scheduled_at -= timedelta(days=1)
        if application.status == ApplicationStatus.IN_REVIEW:
            status = ReminderStatus.FAILED
            attempt_count = MAX_ATTEMPTS
            last_error_code = "SMTPException"
            recorded_at = application.created_at + timedelta(minutes=15)
        else:
            status = ReminderStatus.SENT
            attempt_count = 1
            sent_at = recorded_at = application.created_at + timedelta(minutes=1)

    reminder = application.reminders.create(
        status=status, scheduled_at=scheduled_at, sent_at=sent_at,
        attempt_count=attempt_count, last_error_code=last_error_code,
    )
    application.reminders.filter(pk=reminder.pk).update(
        created_at=application.created_at, updated_at=recorded_at,
    )
    return True


def _seed_applications(
    course: Course, sample: DemoCourse, seeded_at: datetime, fake: "Faker"
) -> tuple[int, int]:
    used_places = course.applications.count()
    # Archived samples represent applications accepted before their deadline.
    received_at = min(seeded_at, course.application_deadline_at) - timedelta(hours=1)
    applications_created = 0
    reminders_created = 0
    for index in range(sample.application_count):
        slot = index + 1
        submission_id = _demo_submission_id(sample, slot)
        fingerprint = sha256(submission_id.bytes).hexdigest()
        email = f"{sample.slug}-{slot}@example.invalid"
        existing = Application.objects.filter(submission_id=submission_id).first()
        if existing is not None:
            if (
                existing.course_id == course.pk
                and existing.submission_fingerprint == fingerprint
                and existing.email.lower() == email
            ):
                reminders_created += _seed_mail_history(existing)
            continue
        if not course.is_published or used_places + applications_created >= course.capacity:
            continue
        status = _STATUSES[index % len(_STATUSES)]
        completed_at = None
        if status == ApplicationStatus.COMPLETED:
            completed_at = received_at + timedelta(minutes=30)
        application = course.applications.create(
            submission_id=submission_id,
            submission_fingerprint=fingerprint,
            name=_demo_name(fake),
            email=email,
            address=f"화면 테스트용 예시 주소 {slot}",
            contact_date=localdate(seeded_at) + timedelta(days=index),
            status=status,
            completed_at=completed_at,
        )
        course.applications.filter(pk=application.pk).update(
            created_at=received_at, updated_at=completed_at or received_at,
        )
        application.created_at = received_at
        applications_created += 1
        reminders_created += _seed_mail_history(application)
    return applications_created, reminders_created


class Command(BaseCommand):
    help = "Create sample courses, applications, and mail history without replacing existing records."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--reset", action="store_true",
            help="Remove previous sample data and recreate it without deleting real applications.",
        )

    @atomic
    def handle(self, *args: Any, **options: Any) -> None:
        try:
            from faker import Faker
        except ImportError as exc:
            raise CommandError("샘플 명령을 실행하려면 pipenv sync --dev를 실행해 주세요.") from exc

        fake = Faker("ko_KR")
        seeded_at = now()
        courses_created = 0
        applications_created = 0
        reminders_created = 0
        courses_deleted = 0
        applications_deleted = 0

        for sample in _COURSES:
            courses = Course.objects.select_for_update()
            if options["reset"]:
                existing = courses.filter(slug=sample.slug).first()
                if existing is not None:
                    applications_deleted += _delete_demo_applications(existing, sample)
                    if not existing.applications.exists() and _is_demo_course(existing, sample):
                        existing.delete()
                        courses_deleted += 1
                    else:
                        self.stdout.write(f"{existing.title}: 기존 교육과 일반 신청 유지")
                        continue

            course, created = courses.get_or_create(
                slug=sample.slug,
                defaults={
                    "title": sample.title,
                    "tagline": sample.tagline,
                    "curriculum": list(sample.curriculum),
                    "is_published": True,
                    "capacity": sample.capacity,
                    "application_deadline_at": seeded_at + timedelta(days=sample.deadline_days),
                },
            )
            enrolled, deliveries = _seed_applications(course, sample, seeded_at, fake)
            courses_created += int(created)
            applications_created += enrolled
            reminders_created += deliveries
            course_result = "생성" if created else "기존 교육 유지"
            self.stdout.write(
                f"{course.title}: {course_result}, 새 신청 {enrolled}건, 메일 발송 내역 {deliveries}건"
            )

        if options["reset"]:
            self.stdout.write(f"초기화: 샘플 교육 {courses_deleted}개, 신청 {applications_deleted}건 삭제")
        self.stdout.write(
            self.style.SUCCESS(
                f"완료: 교육 {courses_created}개, 샘플 신청 {applications_created}건, "
                f"메일 발송 내역 {reminders_created}건을 생성했습니다."
            )
        )
