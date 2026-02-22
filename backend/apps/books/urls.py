from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BookProjectViewSet, ChapterViewSet, SourceDocumentViewSet

router = DefaultRouter()
router.register("projects", BookProjectViewSet, basename="book-project")
router.register("chapters", ChapterViewSet, basename="chapter")
router.register("sources", SourceDocumentViewSet, basename="source-document")

urlpatterns = [
    path("", include(router.urls)),
]
