from datetime import timedelta
from io import StringIO
from re import fullmatch
from uuid import uuid4

from django.core.management import call_command
from django.db.models import F
from django.utils.timezone import localdate, now

import pytest

from eduflow.apps.applications.choices import ApplicationStatus, ReminderStatus
from eduflow.apps.applications.models import Application, ApplicationReminder
from eduflow.apps.courses.choices import IntakeStatus
from eduflow.apps.courses.models import Course


pytestmark = pytest.mark.django_db


def test_seed_demo_populates_all_courses_and_does_not_duplicate():
    # Given an empty database and the current date.
    today = localdate()
    output = StringIO()

    # When the demo command runs twice.
    call_command("seed_demo", stdout=output)
    originals = set(Application.objects.values_list("pk", flat=True))
    original_reminders = set(ApplicationReminder.objects.values_list("pk", flat=True))
    call_command("seed_demo", stdout=output)

    # Then the same 16 applications span six courses, three states and multiple dates.
    assert Course.objects.count() == 6
    assert len(originals) == 16
    assert set(Application.objects.values_list("pk", flat=True)) == originals
    assert set(Application.objects.values_list("status", flat=True)) == set(
        ApplicationStatus.values
    )
    assert set(Application.objects.values_list("contact_date", flat=True)) == {
        today + timedelta(days=days) for days in range(4)
    }
    assert Application.objects.filter(email__endswith="@example.invalid").count() == 16
    names = set(Application.objects.values_list("name", flat=True))
    assert len(names) == 16 and all(fullmatch(r"[가-힣]{3}", name) for name in names)
    assert not Application.objects.filter(
        status=ApplicationStatus.COMPLETED, completed_at__isnull=True,
    ).exists()
    assert not Application.objects.exclude(status=ApplicationStatus.COMPLETED).filter(
        completed_at__isnull=False,
    ).exists()
    full = Course.objects.get(slug="service-prototype-clinic")
    archived = Course.objects.get(slug="design-sprint-archive")
    assert full.intake_status() == IntakeStatus.COURSE_FULL
    assert archived.intake_status() == IntakeStatus.APPLICATION_DEADLINE_PASSED
    before_deadline = archived.applications.filter(
        created_at__lt=archived.application_deadline_at,
    )
    assert before_deadline.count() == 2
    reminders = ApplicationReminder.objects.all()
    assert len(original_reminders) == 16
    assert set(reminders.values_list("pk", flat=True)) == original_reminders
    assert set(reminders.values_list("application_id", flat=True)) == originals
    assert set(reminders.values_list("status", flat=True)) == {
        ReminderStatus.SENT, ReminderStatus.FAILED, ReminderStatus.CANCELLED,
    }
    sent = reminders.filter(status=ReminderStatus.SENT)
    assert sent.exists() and not sent.filter(sent_at__isnull=True).exists()
    assert not sent.filter(sent_at__lt=F("scheduled_at")).exists()
    assert reminders.filter(status=ReminderStatus.FAILED, last_error_code="SMTPException").exists()
    assert not reminders.due(at=now() + timedelta(days=365)).exists()
    assert "교육 0개, 샘플 신청 0건, 메일 발송 내역 0건" in output.getvalue()


def test_seed_demo_backfills_missing_history_for_existing_demo_applications():
    # Given existing demo applications in a full course and one with an edited recipient.
    call_command("seed_demo", stdout=StringIO())
    full = Course.objects.get(slug="service-prototype-clinic").applications.get()
    edited = Application.objects.get(email="digital-project-lab-1@example.invalid")
    full.reminders.all().delete()
    edited.reminders.all().delete()
    Application.objects.filter(pk=edited.pk).update(email="edited@example.com")

    # When the same command runs to backfill missing mail history.
    output = StringIO()
    call_command("seed_demo", stdout=output)

    # Then it fills only the missing demo history and keeps the existing applications.
    assert full.reminders.get().status == ReminderStatus.SENT
    assert not edited.reminders.exists()
    assert Application.objects.count() == 16
    assert ApplicationReminder.objects.count() == 15
    assert "교육 0개, 샘플 신청 0건, 메일 발송 내역 1건" in output.getvalue()


def test_seed_demo_preserves_existing_applications_and_capacity():
    # Given one occupied seat in a pre-existing course.
    call_command("seed_demo", stdout=StringIO())
    course = Course.objects.get(slug="service-prototype-clinic")
    course.applications.all().delete()
    existing, _ = Application.objects.submit(
        course_slug=course.slug, submission_id=uuid4(), name="기존 신청자",
        email="existing@example.com", address="기존 주소", contact_date=localdate(),
    )

    # When the demo command runs again.
    call_command("seed_demo", stdout=StringIO())

    # Then the existing registration remains and the capacity is respected.
    assert course.applications.get().pk == existing.pk
    assert Course.objects.get(pk=course.pk).capacity == 1


def test_seed_reset_recreates_only_demo_data_and_records_completion_after_receipt():
    # Given sample records, one edited sample, and a regular application.
    call_command("seed_demo", stdout=StringIO())
    regular_course = Course.objects.get(slug="ux-research-workshop")
    regular, _ = Application.objects.submit(
        course_slug=regular_course.slug,
        submission_id=uuid4(),
        name="기존 신청자",
        email="regular@example.com",
        address="기존 주소",
        contact_date=localdate(),
    )
    edited_sample = Application.objects.filter(
        email="digital-project-lab-1@example.invalid"
    ).get()
    edited_sample.email = "edited@example.com"
    edited_sample.save(update_fields=["email"])
    demo_course_id = edited_sample.course_id
    old_delivery = edited_sample.reminders.get()
    real_delivery = regular.reminders.get()

    # When the operator resets the demo dataset.
    output = StringIO()
    call_command("seed_demo", "--reset", stdout=output)

    # Then old sample data is replaced and the regular submission is preserved.
    assert not Application.objects.filter(pk=edited_sample.pk).exists()
    assert not Course.objects.filter(pk=demo_course_id).exists()
    assert not ApplicationReminder.objects.filter(pk=old_delivery.pk).exists()
    assert regular.reminders.get().pk == real_delivery.pk
    assert Application.objects.get(pk=regular.pk).email == "regular@example.com"
    assert Course.objects.filter(pk=regular_course.pk).exists()
    assert regular_course.applications.count() == 1
    assert Application.objects.filter(email="digital-project-lab-1@example.invalid").exists()
    completed = Application.objects.filter(status=ApplicationStatus.COMPLETED)
    assert completed.exists()
    assert not completed.filter(completed_at__isnull=True).exists()
    assert not completed.filter(completed_at__lte=F("created_at")).exists()
    assert "신청 16건 삭제" in output.getvalue()
