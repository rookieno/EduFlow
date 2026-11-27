from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone

from eduflow.apps.courses.choices import IntakeStatus
from eduflow.apps.courses.models import Course

from eduflow.apps.applications.exceptions import IntakeClosed, SubmissionConflict
from eduflow.apps.applications.models import Application


class IntakeTests(TransactionTestCase):
    def setUp(self) -> None:
        self.course = Course.objects.create(
            slug="demo",
            title="교육",
            tagline="교육 소개",
            is_published=True,
            capacity=1,
            application_deadline_at=timezone.now() + timedelta(days=1),
        )

    def test_last_place_is_allocated_only_once(self) -> None:
        barrier = Barrier(2, timeout=5)

        def submit() -> IntakeStatus:
            try:
                barrier.wait()
                Application.objects.submit(
                    course_slug=self.course.slug,
                    submission_id=uuid4(),
                    name="신청자",
                    email="example@example.com",
                    address="서울",
                    contact_date=timezone.localdate(),
                )
                return IntakeStatus.OPEN
            except IntakeClosed as exc:
                return exc.status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit(), range(2)))

        self.assertCountEqual(results, [IntakeStatus.OPEN, IntakeStatus.COURSE_FULL])
        self.assertEqual(self.course.applications.count(), 1)

    def test_deadline_precedes_capacity_and_existing_submission_can_replay(self) -> None:
        payload = {
            "course_slug": self.course.slug,
            "submission_id": uuid4(),
            "name": "신청자",
            "email": "example@example.com",
            "address": "서울",
            "contact_date": timezone.localdate(),
        }
        application, created = Application.objects.submit(**payload)
        self.assertTrue(created)
        deadline = timezone.now()
        self.course.application_deadline_at = deadline
        self.course.save(update_fields=["application_deadline_at"])
        self.assertEqual(
            self.course.intake_status(at=deadline), IntakeStatus.APPLICATION_DEADLINE_PASSED
        )
        self.assertEqual(Application.objects.submit(**payload), (application, False))
        with self.assertRaises(SubmissionConflict):
            Application.objects.submit(**{**payload, "name": "다른 이름"})
        with self.assertRaises(IntakeClosed) as caught:
            Application.objects.submit(**{**payload, "submission_id": uuid4()})
        self.assertEqual(caught.exception.status, IntakeStatus.APPLICATION_DEADLINE_PASSED)

    def test_capacity_cannot_drop_below_accepted_applications(self) -> None:
        self.course.capacity = 2
        self.course.save(update_fields=["capacity"])
        for _ in range(2):
            Application.objects.submit(
                course_slug=self.course.slug,
                submission_id=uuid4(),
                name="신청자",
                email="example@example.com",
                address="서울",
                contact_date=timezone.localdate(),
            )
        self.course.capacity = 1
        with self.assertRaises(ValidationError):
            self.course.save(update_fields=["capacity"])
        self.course.refresh_from_db()
        self.assertEqual(self.course.capacity, 2)
