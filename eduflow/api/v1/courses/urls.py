from rest_framework.routers import SimpleRouter

from eduflow.api.v1.courses.views import CourseViewSet


router = SimpleRouter()
router.register("", CourseViewSet, basename="course")
urlpatterns = router.urls
