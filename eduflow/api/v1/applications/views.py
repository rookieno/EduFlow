from typing import Any

from django.conf import settings
from django.db.models import Count, QuerySet
from django.db.transaction import atomic
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.mixins import (
    CreateModelMixin, DestroyModelMixin, ListModelMixin, RetrieveModelMixin, UpdateModelMixin,
)
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.status import (
    HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST, HTTP_502_BAD_GATEWAY,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.viewsets import GenericViewSet

from eduflow.api.v1.pagination import DefaultPagination
from eduflow.api.v1.permissions import (
    CanExportApplications, CanViewApplicationReminders, CanViewApplications,
)
from eduflow.apps.applications.choices import ApplicationStatus
from eduflow.apps.applications.exceptions import (
    IntakeClosed, SheetsExportLimitExceeded, SubmissionConflict,
)
from eduflow.apps.applications.models import Application, ApplicationReminder
from eduflow.apps.courses.choices import IntakeStatus
from eduflow.apps.courses.models import Course
from eduflow.modules.google_sheets.exceptions import (
    GoogleSheetConfigurationError,
    GoogleSheetRequestError,
)

from eduflow.api.v1.applications.serializers import (
    ApplicationFiltersSerializer,
    ApplicationListSerializer,
    ApplicationReminderFiltersSerializer,
    ApplicationSubmissionSerializer,
    ApplicationUpdateSerializer,
    StaffApplicationDetailSerializer,
    StaffApplicationListSerializer,
    StaffApplicationReminderSerializer,
)


@method_decorator(never_cache, name="dispatch")
class ApplicationViewSet(
    ListModelMixin, CreateModelMixin, RetrieveModelMixin, UpdateModelMixin,
    DestroyModelMixin, GenericViewSet,
):
    pagination_class = DefaultPagination
    serializer_class = ApplicationListSerializer
    permission_classes = [CanViewApplications]
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def get_permissions(self) -> list[BasePermission]:
        if self.action == "create":
            return [AllowAny()]
        return super().get_permissions()

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)
        permission = {
            "staff_create": "add",
            "update": "change",
            "partial_update": "change",
            "destroy": "delete",
        }.get(self.action)
        if permission and not request.user.has_perm(f"applications.{permission}_application"):
            raise PermissionDenied

    def get_serializer_class(self) -> type[BaseSerializer]:
        if self.action in {"create", "staff_create"}:
            return ApplicationSubmissionSerializer
        if self.action in {"update", "partial_update"}:
            return ApplicationUpdateSerializer
        if self.action == "retrieve":
            return StaffApplicationDetailSerializer
        return super().get_serializer_class()

    def get_queryset(self) -> QuerySet[Application]:
        applications = Application.objects.select_related("course")
        if self.action in {"update", "partial_update"}:
            return applications.select_for_update(of=("self",))
        if self.action not in {"list", "staff_results", "export"}:
            return applications

        filters = ApplicationFiltersSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        params = filters.validated_data.copy()
        if "course" in params:
            params["course__slug"] = params.pop("course")
        search = {
            key: params.pop(key)
            for key in ("q", "contact_date_from", "contact_date_to")
            if key in params
        }
        return applications.filter(**params).search(**search)

    @action(
        detail=False, methods=["get"], url_path="staff-results",
        serializer_class=StaffApplicationListSerializer,
    )
    def staff_results(self, request: Request) -> Response:
        return self.list(request)

    @action(
        detail=False, methods=["post"], url_path="export",
        permission_classes=[CanExportApplications],
    )
    def export(self, request: Request) -> Response:
        applications = self.get_queryset()
        try:
            result = Application.objects.export_to_google_sheets(applications)
        except SheetsExportLimitExceeded as exc:
            return Response(
                {"code": "EXPORT_LIMIT", "message": f"{exc.args[0]}건 이하로 검색 범위를 줄여 주세요."},
                status=HTTP_400_BAD_REQUEST,
            )
        except GoogleSheetConfigurationError:
            return Response(
                {"code": "SHEETS_NOT_CONFIGURED", "message": "Google Sheets 연동 설정을 확인해 주세요."},
                status=HTTP_503_SERVICE_UNAVAILABLE,
            )
        except GoogleSheetRequestError:
            return Response(
                {"code": "SHEETS_EXPORT_FAILED",
                 "message": "내보내기 결과를 확인하지 못했습니다. 대상 Google Sheets 문서를 확인해 주세요."},
                status=HTTP_502_BAD_GATEWAY,
            )
        return Response({"count": result.count, "sheet_url": result.sheet_url}, status=HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="staff-create")
    def staff_create(self, request: Request) -> Response:
        return self.create(request)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request: Request) -> Response:
        totals = dict(
            Application.objects.order_by().values("status").annotate(total=Count("pk"))
            .values_list("status", "total")
        )
        return Response({
            "total": sum(totals.values()),
            "statuses": [
                {"status": status, "label": label, "total": totals.get(status, 0)}
                for status, label in ApplicationStatus.choices
            ],
        })

    @atomic
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            StaffApplicationDetailSerializer(
                serializer.instance, context=self.get_serializer_context(),
            ).data
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        origin = request.headers.get("Origin")
        approved_cookie_free_client = origin in settings.CORS_ALLOWED_ORIGINS and not request.COOKIES
        browser_request = origin or request.COOKIES or any(
            header in request.headers for header in ("Sec-Fetch-Site", "Referer")
        )
        if not request.user.is_authenticated and browser_request and not approved_cookie_free_client:
            SessionAuthentication().enforce_csrf(request)
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            application, created = serializer.save()
        except ValidationError as exc:
            return Response({"code": "VALIDATION_ERROR", "errors": exc.detail}, status=400)
        except Course.DoesNotExist:
            return Response(
                {"code": "COURSE_NOT_FOUND", "message": "교육을 찾을 수 없습니다."},
                status=404,
            )
        except IntakeClosed as exc:
            if exc.status == IntakeStatus.UNPUBLISHED:
                return Response(
                    {"code": "COURSE_NOT_FOUND", "message": "교육을 찾을 수 없습니다."},
                    status=404,
                )
            return Response({"code": exc.status.value, "message": exc.status.label}, status=409)
        except SubmissionConflict:
            return Response(
                {"code": "SUBMISSION_CONFLICT", "message": "이미 사용한 제출 정보입니다."},
                status=409,
            )
        return Response(
            {"id": application.pk, "status": application.status},
            status=HTTP_201_CREATED if created else HTTP_200_OK,
        )


@method_decorator(never_cache, name="dispatch")
class ApplicationReminderViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    pagination_class = DefaultPagination
    permission_classes = [CanViewApplicationReminders]
    serializer_class = StaffApplicationReminderSerializer
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def get_queryset(self) -> QuerySet[ApplicationReminder]:
        reminders = ApplicationReminder.objects.select_related("application__course")
        if self.action != "list":
            return reminders
        filters = ApplicationReminderFiltersSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        params = filters.validated_data.copy()
        query = params.pop("q", "")
        reminders = reminders.filter(**params)
        if query:
            matches = Application.objects.search(q=query).values("pk")
            reminders = reminders.filter(application_id__in=matches)
        return reminders.order_by("-scheduled_at", "-created_at", "-pk")
