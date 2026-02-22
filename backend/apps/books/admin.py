from django.contrib import admin

from .models import BookProject, Chapter, SourceDocument


@admin.register(BookProject)
class BookProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "genre", "target_word_count", "status", "created_at")
    search_fields = ("title", "genre", "target_audience")
    list_filter = ("status", "genre", "language")


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("project", "number", "title", "status", "vector_indexed", "updated_at")
    search_fields = ("title", "project__title")
    list_filter = ("status", "vector_indexed")


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = ("project", "title", "source_type", "created_at")
    search_fields = ("title", "project__title", "content")
    list_filter = ("source_type",)
