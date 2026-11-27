from django.db.models import QuerySet
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import GenericViewSet

from eduflow.api.v1.pagination import DefaultPagination
from eduflow.api.v1.permissions import CanViewApplications
from eduflow.apps.courses.models import Course

from eduflow.api.v1.courses.serializers import (
    CourseDetailSerializer,
    CourseListSerializer,
    StaffCourseChoiceSerializer,
)


class CourseViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    lookup_field = "slug"
    pagination_class = DefaultPagination
    serializer_class = CourseListSerializer

    def get_queryset(self) -> QuerySet[Course]:
        courses = Course.objects.order_by("title", "slug")
        if self.action == "staff_choices":
            return courses
        return courses.filter(is_published=True)

    def get_serializer_class(self) -> type[BaseSerializer]:
        if self.action == "retrieve":
            return CourseDetailSerializer
        return super().get_serializer_class()

    @action(
        detail=False, methods=["get"], url_path="staff-choices",
        serializer_class=StaffCourseChoiceSerializer, permission_classes=[CanViewApplications],
    )
    def staff_choices(self, request: Request) -> Response:
        return self.list(request)
