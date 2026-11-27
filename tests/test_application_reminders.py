from datetime import time, timedelta
from smtplib import SMTPException
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils.timezone import localdate, now

from eduflow.apps.applications.choices import ApplicationStatus, ReminderStatus
from eduflow.apps.applications.models import Application, ApplicationReminder
from eduflow.apps.courses.models import Course
from eduflow.async_task.send_contact_reminder import send_contact_reminder
from eduflow.batch.dispatch_due_reminders import dispatch_due_reminders


pytestmark = pytest.mark.django_db


@pytest.fixture
def application():
    course = Course.objects.create(
        slug="reminder-course", title="안내 테스트 교육", tagline="안내",
        is_published=True, capacity=10, application_deadline_at=now() + timedelta(days=1),
    )
    return Application.objects.submit(
        course_slug=course.slug, submission_id=uuid4(), name="신청자",
        email="learner@example.com", address="예시 주소", contact_date=localdate(),
    )[0]


def test_submission_creates_one_reminder_at_9_kst_and_excludes_dummy_email(application):
    # Given one submitted application.
    first = application.reminders.get()

    # When the same submission retries and a reserved demo address applies.
    replay, created = Application.objects.submit(
        course_slug=application.course.slug, submission_id=application.submission_id,
        name=application.name, email=application.email, address=application.address,
        contact_date=application.contact_date,
    )
    demo, _ = Application.objects.submit(
        course_slug=application.course.slug, submission_id=uuid4(), name="예시",
        email="demo@example.invalid", address="샘플 주소", contact_date=localdate(),
    )

    # Then the same reservation is retained, at 9 KST, and no demo reminder is queued.
    assert not created and replay.pk == application.pk
    assert application.reminders.get().pk == first.pk
    scheduled = first.scheduled_at.astimezone(ZoneInfo("Asia/Seoul"))
    assert scheduled.date() == application.contact_date and scheduled.time() == time(9)
    assert first.status == ReminderStatus.PENDING
    assert first.next_attempt_at == first.scheduled_at
    assert not demo.reminders.exists()


def test_api_reschedules_cancels_reopens_and_deletes_reminder(admin_client, application):
    # Given a pending reminder and a staff account.
    original = application.reminders.get()
    endpoint = reverse("api:v1:application-detail", args=[application.pk])
    new_date = application.contact_date + timedelta(days=2)

    # When staff change the date, complete the application, then reopen it.
    changed = admin_client.patch(
        endpoint, {"contact_date": new_date.isoformat()}, content_type="application/json",
    )
    replacement = application.reminders.get(status=ReminderStatus.PENDING)
    completed = admin_client.patch(
        endpoint, {"status": ApplicationStatus.COMPLETED}, content_type="application/json",
    )
    reopened = admin_client.patch(
        endpoint, {"status": ApplicationStatus.IN_REVIEW}, content_type="application/json",
    )

    # Then old reservations are canceled, reopening re-reserves, and deletion removes them.
    assert changed.status_code == completed.status_code == reopened.status_code == 200
    original.refresh_from_db()
    replacement.refresh_from_db()
    assert original.status == replacement.status == ReminderStatus.CANCELLED
    active = application.reminders.get(status=ReminderStatus.PENDING)
    assert active.scheduled_at.astimezone(ZoneInfo("Asia/Seoul")).date() == new_date
    assert admin_client.delete(endpoint).status_code == 204
    assert not ApplicationReminder.objects.filter(application=application).exists()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_worker_sends_only_due_reminder_once(application, monkeypatch):
    # Given a reminder with controlled time and a local mail backend.
    reminder = application.reminders.get()
    before = reminder.scheduled_at - timedelta(seconds=1)
    monkeypatch.setattr("eduflow.batch.dispatch_due_reminders.now", lambda: before)
    enqueued = []
    monkeypatch.setattr(send_contact_reminder, "delay", enqueued.append)

    # When Beat scans before and at the due time, then the worker receives duplicate jobs.
    assert dispatch_due_reminders.run() == 0
    monkeypatch.setattr(
        "eduflow.batch.dispatch_due_reminders.now", lambda: reminder.scheduled_at,
    )
    monkeypatch.setattr(
        "eduflow.async_task.send_contact_reminder.now", lambda: reminder.scheduled_at,
    )
    assert dispatch_due_reminders.run() == 1
    assert enqueued == [str(reminder.pk)]
    assert send_contact_reminder.run(enqueued[0])
    assert not send_contact_reminder.run(enqueued[0])

    # Then mail is requested once and the provider acceptance is recorded.
    reminder.refresh_from_db()
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [application.email]
    assert "안내 테스트 교육" in mail.outbox[0].body
    assert reminder.status == ReminderStatus.SENT and reminder.sent_at == reminder.scheduled_at
    assert reminder.attempt_count == 1 and reminder.claim_token is None


def test_smtp_failures_back_off_then_stop(application, monkeypatch):
    # Given a due message and a backend raising failures with recipient-like details.
    reminder = application.reminders.get()
    clock = reminder.scheduled_at
    monkeypatch.setattr("eduflow.async_task.send_contact_reminder.now", lambda: clock)

    def fail(*args, **kwargs):
        raise SMTPException("private-recipient@example.com")

    monkeypatch.setattr("eduflow.async_task.send_contact_reminder.send_mail", fail)

    # When the worker retries at the available times.
    for attempt in (1, 2, 3):
        assert not send_contact_reminder.run(str(reminder.pk))
        reminder.refresh_from_db()
        assert reminder.attempt_count == attempt
        if attempt < 3:
            assert reminder.status == ReminderStatus.PENDING
            assert reminder.next_attempt_at == clock + timedelta(minutes=5 * attempt)
            assert not send_contact_reminder.run(str(reminder.pk))
            clock = reminder.next_attempt_at

    # Then retry stops after the limit, and only the sanitized error code is stored.
    assert reminder.status == ReminderStatus.FAILED
    assert reminder.next_attempt_at is None and reminder.claim_token is None
    assert reminder.last_error_code == "SMTPException"
    assert dispatch_due_reminders.run() == 0


def test_expired_lease_can_be_reclaimed_and_old_worker_cannot_finish(application):
    # Given a worker that claimed a due reminder and then stopped.
    scheduled = application.reminders.get()
    manager = ApplicationReminder.objects
    previous = manager.claim(scheduled.pk, at=scheduled.scheduled_at)
    assert previous is not None
    assert manager.claim(scheduled.pk, at=scheduled.scheduled_at) is None

    # When its lease expires and a replacement claims the reminder.
    replacement = manager.claim(scheduled.pk, at=previous.lease_expires_at)

    # Then only the replacement can complete the action.
    assert replacement is not None and replacement.claim_token != previous.claim_token
    assert not manager.record_sent(previous, at=previous.lease_expires_at)
    assert manager.record_sent(replacement, at=previous.lease_expires_at)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_worker_reads_recipient_from_each_application(application, monkeypatch):
    # Given two reservations for applications with different email addresses.
    first = application.reminders.get()
    second_application, _ = Application.objects.submit(
        course_slug=application.course.slug, submission_id=uuid4(), name="다른 신청자",
        email="other@example.com", address="예시 주소", contact_date=application.contact_date,
    )
    second = second_application.reminders.get()
    monkeypatch.setattr(
        "eduflow.async_task.send_contact_reminder.now", lambda: first.scheduled_at,
    )

    # When each due reminder is sent.
    assert send_contact_reminder.run(str(first.pk))
    assert send_contact_reminder.run(str(second.pk))

    # Then each message is addressed only to the associated application email.
    assert [message.to for message in mail.outbox] == [[application.email], ["other@example.com"]]


def test_staff_mail_log_enforces_permissions_and_filters(client, django_user_model, application):
    # Given an application with a failed delivery and a canceled reservation.
    failed = application.reminders.get()
    ApplicationReminder.objects.filter(pk=failed.pk).update(
        status=ReminderStatus.FAILED, next_attempt_at=None,
        attempt_count=3, last_error_code="SMTPException",
    )
    ApplicationReminder.objects.create(
        application=application, scheduled_at=failed.scheduled_at - timedelta(days=1),
        status=ReminderStatus.CANCELLED,
    )
    staff = django_user_model.objects.create_user(username="mail-operator", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_application"))
    page = reverse("staff:mail-delivery-list")
    endpoint = reverse("api:v1:application-reminder-list")

    # When the operator gains the separate mail log permission and searches the records.
    assert client.get(page).status_code == 302
    assert client.get(endpoint).status_code == 403
    client.force_login(staff)
    assert client.get(page).status_code == client.get(endpoint).status_code == 403
    assert client.get(reverse("staff:mail-delivery-detail", args=[failed.pk])).status_code == 403
    assert client.get(reverse("api:v1:application-reminder-detail", args=[failed.pk])).status_code == 403
    detail = client.get(reverse("api:v1:application-detail", args=[application.pk]))
    assert detail.status_code == 200 and detail.json()["latest_mail_delivery"] is None
    staff.user_permissions.add(Permission.objects.get(codename="view_applicationreminder"))
    shell = client.get(page)
    listing = client.get(endpoint, {"q": str(application.pk), "status": ReminderStatus.FAILED})

    # Then the matching record is available through the read-only API and omitted from the shell.
    assert shell.status_code == listing.status_code == 200
    assert f'href="{page}" aria-current="page">메일 발송 내역</a>' in shell.content.decode()
    assert application.email not in shell.content.decode()
    assert "no-store" in listing.headers["Cache-Control"]
    assert client.get(endpoint).json()["count"] == 2
    assert listing.json()["count"] == 1
    record = listing.json()["results"][0]
    assert record["id"] == str(failed.pk)
    assert record["application_id"] == str(application.pk)
    assert record["current_recipient_email"] == application.email
    assert record["attempt_count"] == 3 and record["last_error_code"] == "SMTPException"
    assert "claim_token" not in record and "address" not in record
    assert client.get(endpoint, {"q": application.email}).json()["count"] == 2
    assert client.get(endpoint, {"status": "UNKNOWN"}).status_code == 400
    assert client.post(endpoint, {}).status_code == 405


def test_sent_mail_is_listed_and_linked_from_application_detail(admin_client, application):
    # Given a canceled reservation and a newer record accepted by the mail backend.
    canceled = application.reminders.get()
    application.reminders.filter(pk=canceled.pk).update(
        status=ReminderStatus.CANCELLED, next_attempt_at=None,
    )
    scheduled_at = canceled.scheduled_at - timedelta(days=1)
    sent = ApplicationReminder.objects.create(
        application=application, scheduled_at=scheduled_at, sent_at=scheduled_at,
        status=ReminderStatus.SENT, attempt_count=1,
    )
    application_url = reverse("api:v1:application-detail", args=[application.pk])
    list_url = reverse("api:v1:application-reminder-list")
    detail_url = reverse("api:v1:application-reminder-detail", args=[sent.pk])

    # When an operator views the application, the completed list, and the sent record.
    application_data = admin_client.get(application_url).json()
    completed = admin_client.get(list_url, {"status": ReminderStatus.SENT}).json()
    detail = admin_client.get(detail_url)
    shell = admin_client.get(reverse("staff:mail-delivery-detail", args=[sent.pk]))

    # Then all views identify the same sent record and report its success.
    assert application_data["latest_mail_delivery"] == {
        "id": str(sent.pk), "status": ReminderStatus.SENT, "status_label": "발송 완료",
    }
    assert detail.status_code == shell.status_code == 200
    assert detail.json() == completed["results"][0]
    assert detail.json()["application_id"] == str(application.pk)
    assert detail.json()["sent_at"] is not None
    assert 'data-staff-page="mail-delivery-detail"' in shell.content.decode()
