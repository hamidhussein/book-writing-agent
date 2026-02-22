from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ProjectStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OUTLINED = "outlined", "Outlined"
    WRITING = "writing", "Writing"
    READY_TO_EXPORT = "ready_to_export", "Ready to Export"
    EXPORTED = "exported", "Exported"


class ChapterStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    GENERATED = "generated", "Generated"
    REVIEWED = "reviewed", "Reviewed"
    FINAL = "final", "Final"


class BookProject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="book_projects",
    )
    title = models.CharField(max_length=160)
    genre = models.CharField(max_length=80)
    target_audience = models.CharField(max_length=80, default="General readers")
    language = models.CharField(max_length=40, default="English")
    tone = models.CharField(max_length=80, default="Informative")
    target_word_count = models.PositiveIntegerField(default=3000)
    status = models.CharField(max_length=32, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT)

    outline_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.id})"


class Chapter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(BookProject, on_delete=models.CASCADE, related_name="chapters")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=ChapterStatus.choices, default=ChapterStatus.PENDING)
    vector_indexed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("project", "number")
        ordering = ["project", "number"]

    def __str__(self) -> str:
        return f"{self.project.title}: Chapter {self.number}"


class SourceDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(BookProject, on_delete=models.CASCADE, related_name="sources")
    title = models.CharField(max_length=200)
    source_type = models.CharField(max_length=32, default="note")
    content = models.TextField(blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.project.title}: {self.title}"
