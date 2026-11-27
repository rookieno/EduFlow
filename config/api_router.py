from django.urls import include, path


app_name = "api"

urlpatterns = [
    path(
        "v1/",
        include(
            (
                [
                    path("applications/", include("eduflow.api.v1.applications.urls")),
                    path("courses/", include("eduflow.api.v1.courses.urls")),
                    path("session/", include("eduflow.api.v1.session.urls")),
                ],
                "v1",
            )
        ),
    ),
]
