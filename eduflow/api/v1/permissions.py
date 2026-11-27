from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet


class CanViewApplications(BasePermission):
    def has_permission(self, request: Request, view: GenericViewSet) -> bool:
        return request.user.is_staff and request.user.has_perm("applications.view_application")


class CanViewApplicationReminders(CanViewApplications):
    def has_permission(self, request: Request, view: GenericViewSet) -> bool:
        return super().has_permission(request, view) and request.user.has_perm(
            "applications.view_applicationreminder"
        )


class CanExportApplications(CanViewApplications):
    def has_permission(self, request: Request, view: GenericViewSet) -> bool:
        return super().has_permission(request, view) and request.user.has_perm(
            "applications.export_application"
        )
