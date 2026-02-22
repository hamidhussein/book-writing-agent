from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.books.models import BookProject
from apps.books.services.pipeline import BookWorkflowService


class Command(BaseCommand):
    help = "Normalize project metadata_json into {user_concept, llm_runtime} zones."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=str, default="", help="Optional project UUID to normalize.")

    def handle(self, *args, **options):
        project_id = str(options.get("project_id", "")).strip()
        qs = BookProject.objects.all().order_by("created_at")
        if project_id:
            qs = qs.filter(id=project_id)

        workflow = BookWorkflowService()
        updated = 0
        for project in qs:
            existing = project.metadata_json if isinstance(project.metadata_json, dict) else {}
            llm_runtime = existing.get("llm_runtime", {}) if isinstance(existing.get("llm_runtime"), dict) else {}
            normalized = workflow._merge_project_metadata(project, llm_runtime)
            if normalized != existing:
                project.metadata_json = normalized
                project.save(update_fields=["metadata_json", "updated_at"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Normalized metadata for {updated} project(s)."))
