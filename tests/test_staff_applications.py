from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from eduflow.apps.applications.choices import ApplicationStatus
from eduflow.apps.applications.models import Application
from eduflow.apps.courses.models import Course


pytestmark = pytest.mark.django_db


@pytest.fixture
def course():
    return Course.objects.create(
        slug="staff-demo", title="운영 테스트 교육", tagline="신청 관리 테스트",
        is_published=True, capacity=1,
        application_deadline_at=timezone.now() + timedelta(days=1),
    )


@pytest.fixture
def application_form(course):
    return {
        "course_slug": course.slug,
        "submission_id": str(uuid4()),
        "name": "샘플 신청자",
        "email": "staff-flow@example.com",
        "address": "샘플 상세 주소",
        "contact_date": timezone.localdate().isoformat(),
    }


def _submit(course, day: int = 0, name: str = "테스트 신청자", email: str = "test@example.com"):
    application, _ = Application.objects.submit(
        course_slug=course.slug, submission_id=uuid4(), name=name, email=email,
        address="예시 주소", contact_date=timezone.localdate() + timedelta(days=day),
    )
    return application


def test_staff_list_shell_and_json_enforce_permissions(client, django_user_model, course):
    # Given an application and a staff account without view permission.
    application = _submit(course)
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    page = reverse("staff:application-list")
    api_url = reverse("api:v1:application-staff-results")

    # When anonymous and unauthorized clients access the shell and the API.
    anonymous = client.get(page)
    client.force_login(staff)
    unauthorized = (client.get(page), client.get(api_url))
    staff.user_permissions.add(Permission.objects.get(codename="view_application"))
    shell = client.get(page)
    listing = client.get(api_url)

    # Then only authorized clients get records, separately from the HTML shell.
    assert anonymous.status_code == 302 and reverse("staff:login") in anonymous.url
    assert all(response.status_code == 403 for response in unauthorized)
    assert shell.status_code == listing.status_code == 200
    html = shell.content.decode()
    assert application.email not in html and "staff.js" in html
    assert '<body class="staff-list-page">' in html
    assert '<h1 class="visually-hidden">신청 관리</h1>' in html
    record = listing.json()["results"][0]
    assert record["email"] == application.email and record["name"] == application.name
    assert "address" not in record and "no-store" in listing.headers["Cache-Control"]
    assert client.post(reverse("api:v1:application-staff-create"), {}).status_code == 403
    detail_url = reverse("api:v1:application-detail", args=[application.pk])
    assert client.patch(detail_url, {"name": "바꾼 이름"}, content_type="application/json").status_code == 403
    assert client.delete(detail_url).status_code == 403


def test_staff_crud_uses_api_and_keeps_course_and_receipt_readonly(
    admin_client, application_form, course,
):
    # Given one seat in the course.
    add = reverse("api:v1:application-staff-create")

    # When staff create, read, edit, and delete through the JSON API.
    created = admin_client.post(add, application_form, content_type="application/json")
    application = Application.objects.get()
    full = admin_client.post(
        add, {**application_form, "submission_id": str(uuid4())},
        content_type="application/json",
    )
    detail = reverse("api:v1:application-detail", args=[application.pk])
    data = admin_client.get(detail).json()
    edit_page = admin_client.get(reverse("staff:application-update", args=[application.pk]))
    updated = admin_client.patch(detail, {
        "id": str(uuid4()), "course": "other-course", "status": ApplicationStatus.COMPLETED,
    }, content_type="application/json")
    application.refresh_from_db()
    delete_page = admin_client.get(reverse("staff:application-delete", args=[application.pk]))
    assert Application.objects.filter(pk=application.pk).exists()
    deleted = admin_client.delete(detail)

    # Then normal intake rules apply and identity stays unchanged.
    assert created.status_code == 201
    assert full.status_code == 409 and full.json()["code"] == "COURSE_FULL"
    assert data["email"] == application_form["email"]
    assert data["address"] == application_form["address"]
    assert 'id="application-receipt" type="text" readonly' in edit_page.content.decode()
    assert 'id="application-course" type="text" readonly' in edit_page.content.decode()
    assert updated.status_code == 200 and updated.json()["status"] == "COMPLETED"
    assert application.course_id == course.pk and data["id"] == str(application.pk)
    assert delete_page.status_code == 200 and deleted.status_code == 204
    assert not Application.objects.exists()


def test_api_records_completion_time_only_on_transitions(admin_client, course, monkeypatch):
    # Given an application and controlled status transition timestamps.
    application = _submit(course)
    url = reverse("api:v1:application-detail", args=[application.pk])
    first = timezone.now().replace(microsecond=0)
    later = first + timedelta(minutes=15)
    clock = "eduflow.apps.applications.models.application.mixins.now"
    assert application.completed_at is None

    # When the operator completes the application, edits its name, then reopens it.
    monkeypatch.setattr(clock, lambda: first)
    completed = admin_client.patch(url, {"status": "COMPLETED"}, content_type="application/json")
    monkeypatch.setattr(clock, lambda: later)
    edited = admin_client.patch(url, {"name": "수정 이름"}, content_type="application/json")
    reopened = admin_client.patch(url, {"status": "IN_REVIEW"}, content_type="application/json")
    repeated = admin_client.patch(url, {"status": "COMPLETED"}, content_type="application/json")
    application.refresh_from_db()

    # Then only a new completion writes a new timestamp.
    assert all(response.status_code == 200 for response in (completed, edited, reopened, repeated))
    assert completed.json()["completed_at"] == edited.json()["completed_at"]
    assert reopened.json()["completed_at"] is None
    assert application.completed_at == later
    assert repeated.json()["completed_at"] == admin_client.get(url).json()["completed_at"]


def test_staff_api_rejects_closed_course(admin_client, course, application_form):
    # Given an expired course.
    course.application_deadline_at = timezone.now() - timedelta(seconds=1)
    course.save(update_fields=["application_deadline_at"])

    # When an operator tries to create an application.
    response = admin_client.post(
        reverse("api:v1:application-staff-create"), application_form,
        content_type="application/json",
    )

    # Then the API reports the deadline error and no record is saved.
    assert response.status_code == 409
    assert response.json()["code"] == "APPLICATION_DEADLINE_PASSED"
    assert not Application.objects.exists()


def test_staff_session_api_logs_in_and_out_with_csrf(django_user_model):
    # Given an operator and a browser with CSRF checking enabled.
    operator = django_user_model.objects.create_user(
        username="staff-login", password="test-only-password", is_staff=True,
    )
    operator.user_permissions.add(Permission.objects.get(codename="view_application"))
    browser = Client(enforce_csrf_checks=True)
    session = browser.get(reverse("api:v1:session-list"))
    headers = {"X-CSRFToken": session.json()["csrf_token"]}
    url = reverse("api:v1:session-sign-in")
    credentials = {"username": "staff-login", "password": "test-only-password"}

    # When the browser logs in and later logs out using the rotated CSRF token.
    denied = browser.post(url, credentials, content_type="application/json")
    login = browser.post(url, credentials, content_type="application/json", headers=headers)
    allowed = browser.get(reverse("staff:home"))
    new_headers = {"X-CSRFToken": login.json()["csrf_token"]}
    logout = browser.post(reverse("api:v1:session-sign-out"), {}, content_type="application/json", headers=new_headers)

    # Then login requires CSRF, creates a real session, and logout clears it.
    assert denied.status_code == 403 and login.status_code == 200
    assert allowed.status_code == 200 and logout.status_code == 204
    assert browser.get(reverse("staff:home")).status_code == 302
    assert browser.get("/admin/").status_code == 404


@override_settings(ENABLE_STAFF_UI=False)
def test_staff_shells_can_be_disabled_without_disabling_json(admin_client):
    # Given settings with staff screens disabled.
    from importlib import reload

    from django.urls import clear_url_caches

    from config import urls

    try:
        reload(urls)
        clear_url_caches()

        # When clients access the staff page and its JSON API.
        shell = admin_client.get("/staff/applications/")
        api_result = admin_client.get(reverse("api:v1:application-staff-results"))

        # Then the HTML route is absent and operator API access still works.
        assert shell.status_code == 404
        assert api_result.status_code == 200
    finally:
        with override_settings(ENABLE_STAFF_UI=True):
            reload(urls)
            clear_url_caches()


def test_staff_dashboard_points_to_shared_summary_api(admin_client, client, course):
    # Given a recorded application and an authorized operator.
    _submit(course)
    home = reverse("staff:home")

    # When the dashboard and its JSON summary are loaded.
    listing = admin_client.get(reverse("staff:application-list")).content.decode()
    dashboard = admin_client.get(home)
    summary = admin_client.get(reverse("api:v1:application-summary")).json()

    # Then the staff logo targets the dashboard and counts arrive via JSON.
    assert f'class="brand" href="{home}"' in listing
    assert '<body class="staff-list-page">' in dashboard.content.decode()
    assert "1건" not in dashboard.content.decode()
    assert summary["total"] == 1
    assert {item["status"]: item["total"] for item in summary["statuses"]} == {
        "RECEIVED": 1, "IN_REVIEW": 0, "COMPLETED": 0,
    }
    assert client.get(home).status_code == 302


def test_staff_searches_receipt_name_email_and_inclusive_contact_range(admin_client, course):
    # Given three applications with distinct names and dates.
    course.capacity = 3
    course.save(update_fields=["capacity"])
    selected = _submit(course, 0, "범위검색 대상", "unique-search@example.com")
    inside = _submit(course, 1, "범위검색 다른 이름", "inside@example.com")
    _submit(course, 2, "범위검색 바깥", "outside@example.com")
    url = reverse("api:v1:application-staff-results")
    today = timezone.localdate()

    # When staff search by receipt, name or email and then apply a date range.
    for term in (str(selected.pk), selected.pk.hex, str(selected.pk)[:12], " 대상 ", "UNIQUE-SEARCH"):
        response = admin_client.get(url, {"q": term})
        assert [item["id"] for item in response.json()["results"]] == [str(selected.pk)]
    result = admin_client.get(url, {
        "q": "범위검색", "contact_date_from": today.isoformat(),
        "contact_date_to": (today + timedelta(days=1)).isoformat(),
    })
    invalid = admin_client.get(url, {
        "contact_date_from": today.isoformat(),
        "contact_date_to": (today - timedelta(days=1)).isoformat(),
    })

    # Then both boundaries are included and invalid ranges are rejected.
    assert {item["id"] for item in result.json()["results"]} == {str(selected.pk), str(inside.pk)}
    assert invalid.status_code == 400 and "contact_date_to" in invalid.json()


def test_staff_search_paginates_json_results(admin_client, course):
    # Given more matching applications than fit on one page.
    course.capacity = 21
    course.save(update_fields=["capacity"])
    for index in range(21):
        _submit(course, name=f"page-search {index}", email=f"page-{index}@example.com")

    # When requesting page one with a search term.
    url = reverse("api:v1:application-staff-results")
    result = admin_client.get(url, {"q": "page-search"})

    # Then the next link preserves the query.
    data = result.json()
    assert data["count"] == 21 and len(data["results"]) == 20
    assert "/api/v1/applications/staff-results/?" in data["next"]
    assert "q=page-search" in data["next"] and "page=2" in data["next"]


@override_settings(CORS_ALLOWED_ORIGINS=["https://client.example"])
def test_token_client_can_use_protected_api_from_allowed_origin(client, django_user_model, course):
    # Given a staff token, an approved origin, and a saved application.
    operator = django_user_model.objects.create_user(username="integration", is_staff=True)
    operator.user_permissions.add(*Permission.objects.filter(
        content_type__app_label="applications",
        codename__in=["view_application", "change_application"],
    ))
    token = Token.objects.create(user=operator)
    application = _submit(course)
    path = reverse("api:v1:application-detail", args=[application.pk])
    headers = {"Origin": "https://client.example", "Authorization": f"Token {token.key}"}

    # When the outside client changes a record without a session cookie.
    response = client.patch(path, {"status": "COMPLETED"}, content_type="application/json", headers=headers)

    # Then the API authorizes the operation and returns its CORS header.
    assert response.status_code == 200
    assert response.json()["completed_at"]
    assert response.headers["Access-Control-Allow-Origin"] == "https://client.example"
