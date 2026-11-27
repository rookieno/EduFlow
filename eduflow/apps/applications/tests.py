from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

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
            curriculum=["교육 개요"],
            is_published=True,
            capacity=1,
            application_deadline_at=timezone.now() + timedelta(days=1),
        )

    def test_concurrent_submissions_can_exceed_capacity(self) -> None:
        # Given a published course with a planned capacity of one.
        barrier = Barrier(2, timeout=5)

        def submit() -> bool:
            try:
                barrier.wait()
                _, created = Application.objects.submit(
                    course_slug=self.course.slug,
                    submission_id=uuid4(),
                    name="신청자",
                    email="example@example.com",
                    address="서울",
                    contact_date=timezone.localdate(),
                )
                return created
            finally:
                connections.close_all()

        # When two applications are submitted concurrently.
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit(), range(2)))

        # Then both are recorded and intake remains open.
        self.assertEqual(results, [True, True])
        self.assertEqual(self.course.applications.count(), 2)
        self.assertEqual(self.course.intake_status(), IntakeStatus.OPEN)

    def test_deadline_closes_intake_and_existing_submission_can_replay(self) -> None:
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

    def test_capacity_can_drop_below_the_application_count(self) -> None:
        # Given two stored applications for a course with a planned capacity of two.
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
        # When the planned capacity is reduced.
        self.course.capacity = 1
        self.course.full_clean()
        self.course.save(update_fields=["capacity"])

        # Then both existing applications are retained.
        self.course.refresh_from_db()
        self.assertEqual(self.course.capacity, 1)
        self.assertEqual(self.course.applications.count(), 2)
