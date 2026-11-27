from django.conf import settings
from django.urls import include, path

from eduflow.apps.courses import views


urlpatterns = [
    path("", views.home, name="home"),
    path("courses/<slug:slug>/", views.course_detail, name="course-detail"),
    path("courses/<slug:slug>/apply/", views.apply, name="course-apply"),
]

urlpatterns += [
    path("api/", include("config.api_router")),
]

if settings.ENABLE_STAFF_UI:
    urlpatterns += [
        path("staff/", include("eduflow.apps.applications.staff_urls")),
    ]
