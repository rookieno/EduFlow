from rest_framework.routers import SimpleRouter

from eduflow.api.v1.applications.views import ApplicationReminderViewSet, ApplicationViewSet


router = SimpleRouter()
router.register("", ApplicationViewSet, basename="application")
router.register("reminders", ApplicationReminderViewSet, basename="application-reminder")

urlpatterns = router.urls
