from __future__ import annotations

import uuid

from django.db import models

from apps.books.models import BookProject


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class RunMode(models.TextChoices):
    TOC = "toc", "TOC"
    REFINE_TOC = "refine_toc", "Refine TOC"
    CHAPTER = "chapter", "Chapter"
    EXPORT = "export", "Export"
    PROFILE_ASSISTANT = "profile_assistant", "Profile Assistant"


class AgentRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trace_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    project = models.ForeignKey(BookProject, on_delete=models.CASCADE, related_name="runs")

    mode = models.CharField(max_length=32, choices=RunMode.choices)
    status = models.CharField(max_length=16, choices=RunStatus.choices, default=RunStatus.QUEUED)

    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    timings_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["project", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.mode} run for {self.project.title} ({self.status})"
