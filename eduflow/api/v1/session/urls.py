from rest_framework.routers import SimpleRouter

from eduflow.api.v1.session.views import SessionViewSet


router = SimpleRouter()
router.register("", SessionViewSet, basename="session")
urlpatterns = router.urls
