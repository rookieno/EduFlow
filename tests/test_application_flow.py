from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from eduflow.apps.applications.choices import ApplicationStatus
from eduflow.apps.applications.models import Application
from eduflow.apps.courses.models import Course


pytestmark = pytest.mark.django_db


@pytest.fixture
def course():
    return Course.objects.create(
        slug="design-lab",
        title="디자인 랩",
        tagline="아이디어를 실습합니다.",
        curriculum=["문제 정의", "프로토타입"],
        course_image="https://example.com/course.png",
        course_image_alt="디자인 실습 사진",
        is_published=True,
        capacity=1,
        application_deadline_at=timezone.now() + timedelta(days=2),
    )


@pytest.fixture
def payload(course):
    return {
        "course_slug": course.slug,
        "submission_id": str(uuid4()),
        "name": "테스트 신청자",
        "email": "learner@example.com",
        "address": "서울시",
        "contact_date": timezone.localdate().isoformat(),
    }


@pytest.fixture
def browser(course):
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("api:v1:session-list"))
    return client


def test_public_course_pages_render_shells_but_api_serves_course(client, course):
    # Given a published course with a representative image.
    url = reverse("course-detail", args=[course.slug])
    api_url = reverse("api:v1:course-detail", args=[course.slug])

    # When visitors load the page and the corresponding API.
    shell = client.get(url)
    result = client.get(api_url)

    # Then only the JSON response contains the course data.
    assert shell.status_code == result.status_code == 200
    assert "public.js" in shell.content.decode()
    assert course.title not in shell.content.decode()
    data = result.json()
    assert data["title"] == course.title
    assert data["curriculum"] == course.curriculum
    assert data["image"] == {"url": course.course_image, "alt": course.course_image_alt}
    assert data["intake"]["code"] == "OPEN"


def test_course_catalog_excludes_unpublished_courses_and_describes_missing_image(client, course):
    # Given published and unpublished courses without custom artwork.
    missing = Course.objects.create(
        slug="no-image", title="이미지 없는 교육", tagline="기본 이미지 확인",
        is_published=True, capacity=2, application_deadline_at=course.application_deadline_at,
    )
    draft = Course.objects.create(
        slug="private-course", title="비공개 교육", tagline="미공개",
        capacity=2, application_deadline_at=course.application_deadline_at,
    )

    # When the JSON catalog and unpublished detail are requested.
    response = client.get(reverse("api:v1:course-list"))
    private = client.get(reverse("api:v1:course-detail", args=[draft.slug]))

    # Then only published courses are returned and the client receives null for missing artwork.
    results = {item["slug"]: item for item in response.json()["results"]}
    assert set(results) == {missing.slug, course.slug}
    assert results[missing.slug]["image"] is None
    assert private.status_code == 404


def test_demo_course_api_uses_its_bundled_cover(client, course):
    # Given a matching sample course without a configured image.
    course.slug = "digital-project-lab"
    course.course_image = ""
    course.save(update_fields=["slug", "course_image"])

    # When catalog and detail data are fetched.
    catalog = client.get(reverse("api:v1:course-list")).json()["results"][0]
    detail = client.get(reverse("api:v1:course-detail", args=[course.slug])).json()

    # Then both responses provide the same absolute cover URL and Korean alt text.
    assert catalog["image"] == detail["image"]
    assert detail["image"]["url"].endswith("/static/courses/digital-project-lab.webp")
    assert "노트북의 프로토타입" in detail["image"]["alt"]


def test_ajax_submission_and_replay_share_one_application(browser, payload):
    # Given CSRF 쿠키와 제출 식별자가 준비되어 있다.
    url = reverse("api:v1:application-list")
    headers = {"X-CSRFToken": browser.cookies["csrftoken"].value}

    # When 최초 요청과 동일한 Ajax 요청을 다시 보낸다.
    created = browser.post(url, payload, content_type="application/json", headers=headers)
    replay = browser.post(url, payload, content_type="application/json", headers=headers)
    conflict = browser.post(
        url, {**payload, "name": "변경"}, content_type="application/json", headers=headers
    )

    # Then 접수번호를 재사용하고 다른 내용의 재사용은 거부된다.
    assert created.status_code == 201
    assert replay.status_code == 200 and replay.json() == created.json()
    assert conflict.status_code == 409 and conflict.json()["code"] == "SUBMISSION_CONFLICT"
    assert Application.objects.count() == 1
    assert set(created.json()) == {"id", "status"}


def test_anonymous_post_requires_csrf(browser, payload):
    # Given 익명 브라우저는 쿠키만 가지고 CSRF 헤더를 보내지 않는다.
    url = reverse("api:v1:application-list")

    # When 공개 신청 API로 POST 한다.
    response = browser.post(url, payload, content_type="application/json")

    # Then 접수가 차단되고 레코드는 생성되지 않는다.
    assert response.status_code == 403
    assert not Application.objects.exists()


def test_external_client_can_submit_json_without_browser_session(client, course, payload):
    # Given an integration client with no browser state.
    url = reverse("api:v1:application-list")

    # When it submits an application as JSON and retrieves the HTML shell.
    response = client.post(url, payload, content_type="application/json")
    shell = client.get(reverse("course-apply", args=[course.slug]))

    # Then the API accepts the form while the shell contains no application identifiers.
    assert response.status_code == 201
    assert Application.objects.count() == 1
    assert response.json()["id"] not in shell.content.decode()
    assert "접수번호" not in shell.content.decode()


def test_past_contact_date_returns_field_error(browser, payload):
    # Given 신청 데이터의 연락 가능 날짜가 어제다.
    payload["contact_date"] = (timezone.localdate() - timedelta(days=1)).isoformat()

    # When Ajax 신청을 보낸다.
    response = browser.post(
        reverse("api:v1:application-list"), payload, content_type="application/json",
        headers={"X-CSRFToken": browser.cookies["csrftoken"].value},
    )

    # Then 날짜 오류를 반환하고 신청을 만들지 않는다.
    assert response.status_code == 400
    assert "contact_date" in response.json()["errors"]
    assert not Application.objects.exists()


def test_deadline_blocks_new_submissions(browser, course, payload):
    # Given 신청 화면을 연 뒤 접수 마감 시각이 된다.
    course.application_deadline_at = timezone.now()
    course.save(update_fields=["application_deadline_at"])

    # When 소개를 다시 열고, 기존 화면에서 새 신청을 보낸다.
    landing = browser.get(reverse("api:v1:course-detail", args=[course.slug]))
    response = browser.post(
        reverse("api:v1:application-list"), payload, content_type="application/json",
        headers={"X-CSRFToken": browser.cookies["csrftoken"].value},
    )

    # Then 화면과 API가 같은 이유로 접수를 막는다.
    assert landing.json()["intake"] == {
        "label": "신청 기간 종료", "code": "APPLICATION_DEADLINE_PASSED",
    }
    assert response.status_code == 409
    assert response.json()["code"] == "APPLICATION_DEADLINE_PASSED"
    assert not course.applications.exists()


def test_public_intake_remains_open_when_pending_applications_reach_capacity(browser, course, payload):
    # Given 교육 정원과 같은 수의 신청이 이미 접수됐다.
    url = reverse("api:v1:application-list")
    headers = {"X-CSRFToken": browser.cookies["csrftoken"].value}
    first = browser.post(url, payload, content_type="application/json", headers=headers)
    assert first.status_code == 201
    assert course.applications.count() == course.capacity

    # When 교육 상세를 조회하고 다른 제출 식별자로 신청한다.
    landing = browser.get(reverse("api:v1:course-detail", args=[course.slug]))
    second = browser.post(
        url, {**payload, "submission_id": str(uuid4())}, content_type="application/json",
        headers=headers,
    )

    # Then 상세에서도 접수 가능으로 표시되며 추가 신청이 저장된다.
    assert landing.json()["capacity"] == 1
    assert landing.json()["intake"]["code"] == "OPEN"
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert course.applications.count() == 2


def test_public_intake_closes_at_completed_capacity_and_reopens(browser, admin_client, course, payload):
    # Given a pending application for a course with a capacity of one.
    submit_url = reverse("api:v1:application-list")
    headers = {"X-CSRFToken": browser.cookies["csrftoken"].value}
    first = browser.post(submit_url, payload, content_type="application/json", headers=headers)
    assert first.status_code == 201
    application_url = reverse("api:v1:application-detail", args=[first.json()["id"]])
    course_url = reverse("api:v1:course-detail", args=[course.slug])
    next_payload = {**payload, "submission_id": str(uuid4())}

    # When the operator completes the application, then moves it back to review.
    completed = admin_client.patch(
        application_url, {"status": ApplicationStatus.COMPLETED}, content_type="application/json",
    )
    full = browser.get(course_url)
    blocked = browser.post(submit_url, next_payload, content_type="application/json", headers=headers)
    replay = browser.post(submit_url, payload, content_type="application/json", headers=headers)
    reopened = admin_client.patch(
        application_url, {"status": ApplicationStatus.IN_REVIEW}, content_type="application/json",
    )
    open_course = browser.get(course_url)
    accepted = browser.post(submit_url, next_payload, content_type="application/json", headers=headers)

    # Then a full course blocks new applications until the completed count drops.
    assert completed.status_code == reopened.status_code == 200
    assert full.json()["intake"] == {"code": "COURSE_FULL", "label": "정원 마감"}
    assert blocked.status_code == 409
    assert blocked.json() == {"code": "COURSE_FULL", "message": "정원 마감"}
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    assert open_course.json()["intake"]["code"] == "OPEN"
    assert accepted.status_code == 201
    assert course.applications.count() == 2


def test_list_requires_permission_and_excludes_personal_fields(
    browser, course, payload, django_user_model,
):
    # Given 신청 한 건과 신청 조회 권한이 없는 직원 계정이 있다.
    Application.objects.submit(**{
        **payload, "submission_id": uuid4(), "contact_date": timezone.localdate(),
    })
    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    url = reverse("api:v1:application-list")

    # When 익명, 일반 직원, 조회 권한을 부여받은 직원이 차례대로 접근한다.
    anonymous = browser.get(url)
    browser.force_login(user)
    staff = browser.get(url)
    user.user_permissions.add(Permission.objects.get(codename="view_application"))
    allowed = browser.get(url, {"course": course.slug, "status": "RECEIVED"})

    # Then 권한 있는 직원만 개인정보가 제외된 페이지를 볼 수 있다.
    assert anonymous.status_code == staff.status_code == 403
    assert allowed.status_code == 200 and allowed.json()["count"] == 1
    assert set(allowed.json()["results"][0]) == {
        "id", "course", "status", "contact_date", "created_at",
    }


def test_api_list_searches_by_email_and_one_sided_contact_date(admin_client, course):
    # Given a recorded application and an authorized operator.
    date = timezone.localdate() + timedelta(days=1)
    application, _ = Application.objects.submit(
        course_slug=course.slug, submission_id=uuid4(), name="API 검색 대상",
        email="api-date@example.com", address="예시 주소", contact_date=date,
    )
    url = reverse("api:v1:application-list")

    # When filtering by an email fragment with only an upper bound.
    result = admin_client.get(url, {"q": "API-DATE", "contact_date_to": date.isoformat()})
    excluded = admin_client.get(url, {
        "q": str(application.pk), "contact_date_from": (date + timedelta(days=1)).isoformat(),
    })
    invalid = admin_client.get(url, {
        "contact_date_from": date.isoformat(),
        "contact_date_to": (date - timedelta(days=1)).isoformat(),
    })

    # Then the boundary is inclusive, out-of-range rows are excluded and invalid ranges fail.
    assert result.status_code == 200
    assert result.json()["results"][0]["id"] == str(application.pk)
    assert "email" not in result.json()["results"][0]
    assert excluded.json()["count"] == 0
    assert invalid.status_code == 400 and "contact_date_to" in invalid.json()


def test_public_submission_accepts_only_configured_cross_origin_browsers(
    client, payload, settings,
):
    # Given a frontend explicitly allowed to call the public API without cookies.
    settings.CORS_ALLOWED_ORIGINS = ["https://client.example"]
    browser = Client(enforce_csrf_checks=True)
    url = reverse("api:v1:application-list")

    # When unknown and approved origins submit the same payload.
    denied = browser.post(
        url, payload, content_type="application/json", headers={"Origin": "https://other.example"},
    )
    accepted = browser.post(
        url, payload, content_type="application/json", headers={"Origin": "https://client.example"},
    )

    # Then only the configured origin can submit without a CSRF cookie.
    assert denied.status_code == 403
    assert accepted.status_code == 201
    assert accepted.headers["Access-Control-Allow-Origin"] == "https://client.example"
    assert Application.objects.count() == 1
