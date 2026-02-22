from __future__ import annotations

from celery import shared_task

from .models import Chapter
from .services.pipeline import BookWorkflowService


@shared_task
def reindex_chapter_memory(chapter_id: str) -> bool:
    service = BookWorkflowService()
    chapter = Chapter.objects.select_related("project").filter(id=chapter_id).first()
    if not chapter:
        return False
    indexed = service.vector_store.upsert_chapter_memory(
        project_id=str(chapter.project_id),
        chapter_number=chapter.number,
        title=chapter.title,
        content=chapter.content,
        summary=chapter.summary,
    )
    if indexed and not chapter.vector_indexed:
        chapter.vector_indexed = True
        chapter.save(update_fields=["vector_indexed", "updated_at"])
    return indexed
