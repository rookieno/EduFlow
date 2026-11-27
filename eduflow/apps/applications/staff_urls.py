from collections.abc import Callable
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.urls import path, reverse
from django.views.decorators.cache import never_cache
from django.views.generic.base import TemplateView


def staff_page(
    template: str, permission: str = "view", *,
    extra_permission: str | None = None, **context: Any,
) -> Callable[..., HttpResponse]:
    page = TemplateView.as_view(template_name=template, extra_context=context)
    permissions = {"applications.view_application", f"applications.{permission}_application"}
    if extra_permission:
        permissions.add(extra_permission)

    @never_cache
    def render_page(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("staff:login"))
        if not user.is_staff or not user.has_perms(permissions):
            raise PermissionDenied
        return page(request, *args, **kwargs)

    return render_page


app_name = "staff"

urlpatterns = [
    path("", staff_page("staff/home.html"), name="home"),
    path("login/", never_cache(TemplateView.as_view(template_name="staff/login.html")), name="login"),
    path("applications/", staff_page("staff/applications.html"), name="application-list"),
    path(
        "mail-deliveries/",
        staff_page(
            "staff/mail_deliveries.html", extra_permission="applications.view_applicationreminder",
        ),
        name="mail-delivery-list",
    ),
    path(
        "mail-deliveries/<uuid:pk>/",
        staff_page(
            "staff/mail_delivery_detail.html",
            extra_permission="applications.view_applicationreminder",
        ),
        name="mail-delivery-detail",
    ),
    path(
        "applications/new/", staff_page("staff/application_form.html", "add", editing=False),
        name="application-create",
    ),
    path(
        "applications/<uuid:pk>/", staff_page("staff/application_detail.html"),
        name="application-detail",
    ),
    path(
        "applications/<uuid:pk>/edit/",
        staff_page("staff/application_form.html", "change", editing=True),
        name="application-update",
    ),
    path(
        "applications/<uuid:pk>/delete/", staff_page("staff/application_delete.html", "delete"),
        name="application-delete",
    ),
]
