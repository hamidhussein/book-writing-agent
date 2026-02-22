from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/token/", obtain_auth_token),
    path("api/books/", include("apps.books.urls")),
    path("api/agents/", include("apps.agents.urls")),
]
