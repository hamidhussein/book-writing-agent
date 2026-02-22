from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AgentRunViewSet

router = DefaultRouter()
router.register("runs", AgentRunViewSet, basename="agent-run")

urlpatterns = [
    path("", include(router.urls)),
]
