from django.contrib import admin

from .models import AgentRun


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "mode", "status", "created_at", "finished_at")
    list_filter = ("status", "mode")
    search_fields = ("project__title", "error_message")
