from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse
from django.utils.timezone import localdate, now
from requests.exceptions import Timeout

from eduflow.apps.applications.models import Application
from eduflow.apps.courses.models import Course


pytestmark = pytest.mark.django_db


@pytest.fixture
def applications():
    course = Course.objects.create(
        slug="sheets-test", title="내보내기 테스트", tagline="교육 소개",
        is_published=True, capacity=2, application_deadline_at=now() + timedelta(days=1),
    )
    return tuple(
        Application.objects.submit(
            course_slug=course.slug, submission_id=uuid4(), name=name,
            email=email, address="내보내기 제외 주소", contact_date=localdate(),
        )[0]
        for name, email in (
            ("=1+1", "included@example.com"),
            ("다른 신청자", "excluded@example.com"),
        )
    )


def test_export_requires_staff_view_and_export_permissions(client, django_user_model):
    # Given a staff member who can only view applications.
    user = django_user_model.objects.create_user(username="sheets-operator", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_application"))
    endpoint = reverse("api:v1:application-export")

    # When anonymous users or view-only staff request an export.
    anonymous = client.post(endpoint)
    client.force_login(user)
    forbidden = client.post(endpoint)
    listing = client.get(reverse("staff:application-list"))

    # Then the API denies export and the list omits its button.
    assert anonymous.status_code == forbidden.status_code == 403
    assert listing.status_code == 200 and b"data-export>" not in listing.content


@override_settings(
    GOOGLE_SHEETS_SPREADSHEET_ID="training-doc-id",
    GOOGLE_APPLICATION_CREDENTIALS="/fake/service-account.json",
)
def test_export_uses_applied_filter_and_writes_plain_text(admin_client, applications):
    # Given an export target and two applicants, one with formula-like input.
    included, excluded = applications
    endpoint = reverse("api:v1:application-export")

    # When the operator exports with a receipt filter and a page number.
    with (
        patch("eduflow.apps.applications.google_sheets.Credentials") as credentials,
        patch("eduflow.apps.applications.google_sheets.AuthorizedSession") as session,
    ):
        google = session.return_value.__enter__.return_value
        exported = admin_client.post(endpoint + f"?q={included.pk}&page=9")
        google.post.assert_called_once()
        google.post.return_value.raise_for_status.assert_called_once()
        credentials.from_service_account_file.assert_called_once_with(
            "/fake/service-account.json",
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        request = google.post.call_args

    # Then a single batch creates a new tab containing only the selected row.
    assert exported.status_code == 201
    assert "no-store" in exported.headers["Cache-Control"]
    assert exported.json()["count"] == 1
    assert request.args == (
        "https://sheets.googleapis.com/v4/spreadsheets/training-doc-id:batchUpdate",
    )
    add_sheet, update_cells = request.kwargs["json"]["requests"]
    properties = add_sheet["addSheet"]["properties"]
    cells = update_cells["updateCells"]
    assert cells["start"]["sheetId"] == properties["sheetId"]
    assert exported.json()["sheet_url"].endswith(f"#gid={properties['sheetId']}")
    assert properties["gridProperties"] == {
        "rowCount": 2, "columnCount": 8, "frozenRowCount": 1,
    }
    assert cells["fields"] == "userEnteredValue"
    header, application = [
        [cell["userEnteredValue"]["stringValue"] for cell in row["values"]]
        for row in cells["rows"]
    ]
    assert header == ["접수번호", "교육", "이름", "이메일", "상태", "연락 가능일", "접수 시각", "완료 시각"]
    assert application[:4] == [str(included.pk), included.course.title, included.name, included.email]
    assert excluded.email not in application and included.address not in application
    assert application[6].endswith("+09:00")


@override_settings(
    GOOGLE_SHEETS_SPREADSHEET_ID="training-doc-id",
    GOOGLE_APPLICATION_CREDENTIALS="/fake/service-account.json",
)
def test_export_bounds_rows_and_reports_failed_google_requests(admin_client, applications, monkeypatch):
    # Given an export that is limited to one row and an unavailable Google API.
    endpoint = reverse("api:v1:application-export")
    monkeypatch.setattr(
        "eduflow.apps.applications.models.application.manager.MAX_SHEETS_APPLICATIONS", 1,
    )

    # When an operator attempts an unfiltered export, then selects just one record.
    with (
        patch("eduflow.apps.applications.google_sheets.Credentials") as credentials,
        patch("eduflow.apps.applications.google_sheets.AuthorizedSession") as session,
    ):
        google = session.return_value.__enter__.return_value
        google.post.side_effect = Timeout("external detail")
        over_limit = admin_client.post(endpoint)
        credentials.from_service_account_file.assert_not_called()
        google.post.assert_not_called()
        failed = admin_client.post(endpoint + f"?q={applications[0].pk}")
        google.post.assert_called_once()

    # Then excessive exports stay local and provider details remain private.
    assert over_limit.status_code == 400 and over_limit.json()["code"] == "EXPORT_LIMIT"
    assert failed.status_code == 502 and failed.json()["code"] == "SHEETS_EXPORT_FAILED"
    assert "external detail" not in failed.content.decode()


@override_settings(GOOGLE_SHEETS_SPREADSHEET_ID="", GOOGLE_APPLICATION_CREDENTIALS="")
def test_export_explains_missing_configuration(admin_client):
    # Given a superuser and no Sheets credentials.
    endpoint = reverse("api:v1:application-export")

    # When an authorized operator opens the menu and attempts an export.
    listing = admin_client.get(reverse("staff:application-list"))
    response = admin_client.post(endpoint)

    # Then the action is visible and reports the configuration requirement.
    assert b"data-export>" in listing.content
    assert response.status_code == 503 and response.json()["code"] == "SHEETS_NOT_CONFIGURED"
