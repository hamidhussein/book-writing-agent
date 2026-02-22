from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.books.models import SourceDocument
from apps.books.services.knowledge_base import index_source_document


class Command(BaseCommand):
    help = "Re-index all source documents so vector payloads include priority metadata."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=str, default="", help="Optional project UUID filter.")

    def handle(self, *args, **options):
        project_id = str(options.get("project_id", "")).strip()
        qs = SourceDocument.objects.select_related("project").all().order_by("created_at")
        if project_id:
            qs = qs.filter(project_id=project_id)

        total = 0
        indexed = 0
        for source in qs:
            total += 1
            stats = index_source_document(source)
            if int(stats.get("chunks_indexed", 0) or 0) > 0:
                indexed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Re-indexed {indexed}/{total} source document(s) with priority-aware payload."
            )
        )
