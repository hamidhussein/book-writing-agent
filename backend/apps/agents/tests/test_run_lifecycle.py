from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.agents.models import AgentRun, RunStatus
from apps.agents.services.orchestration import AgentOrchestrator
from apps.agents.tasks import execute_agent_run
from apps.books.models import BookProject


class RunLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="runner", password="pass12345")
        self.project = BookProject.objects.create(
            owner=self.user,
            title="Lifecycle Book",
            genre="Non-fiction",
            target_audience="General readers",
            language="English",
            tone="Informative",
            target_word_count=3000,
            metadata_json={
                "user_concept": {
                    "profile": {"tone": "Informative"},
                    "instruction_brief": "Teach clearly.",
                }
            },
        )

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.llm.LLMService._call_json")
    def test_toc_run_populates_outline_and_chapters(self, mock_call_json, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        mock_call_json.return_value = {
            "outline": {
                "synopsis": "A practical beginner guide.",
                "chapters": [
                    {
                        "number": 1,
                        "title": "Foundations",
                        "bullet_points": ["Core concepts", "Motivation", "Roadmap"],
                    },
                    {
                        "number": 2,
                        "title": "Execution",
                        "bullet_points": ["Workflow", "Examples", "Common mistakes"],
                    },
                ],
            },
            "metadata": {"estimated_word_count": 3000, "chapter_count": 2},
            "next_steps": ["Review outline"],
        }

        run = AgentRun(project=self.project, mode="toc", input_payload={})
        output = AgentOrchestrator().execute(run)

        self.project.refresh_from_db()
        self.assertEqual(output.get("status"), "success")
        self.assertIn("outline", output)
        self.assertTrue(self.project.outline_json.get("chapters"))
        self.assertEqual(self.project.chapters.count(), 2)
        self.assertIn("progress", output)
        self.assertIn("timings_ms", output)
        self.assertIn("nodes", output.get("timings_ms", {}))
        self.assertFalse(output.get("used_fallback"))
        self.assertEqual(output.get("fallback_stages"), [])

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.llm.LLMService._call_json")
    def test_toc_fallback_telemetry_is_surface_in_run_output(self, mock_call_json, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        mock_call_json.return_value = None

        run = AgentRun(project=self.project, mode="toc", input_payload={})
        output = AgentOrchestrator().execute(run)

        self.assertEqual(output.get("status"), "success")
        self.assertTrue(output.get("used_fallback"))
        self.assertIn("toc", output.get("fallback_stages", []))

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.llm.LLMService._call_json")
    def test_execute_agent_run_marks_status_completed(self, mock_call_json, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        mock_call_json.return_value = {
            "outline": {
                "synopsis": "A practical beginner guide.",
                "chapters": [
                    {
                        "number": 1,
                        "title": "Foundations",
                        "bullet_points": ["Core concepts", "Motivation", "Roadmap"],
                    },
                    {
                        "number": 2,
                        "title": "Execution",
                        "bullet_points": ["Workflow", "Examples", "Common mistakes"],
                    },
                ],
            },
            "metadata": {"estimated_word_count": 3000, "chapter_count": 2},
            "next_steps": ["Review outline"],
        }

        run = AgentRun.objects.create(project=self.project, mode="toc", status=RunStatus.QUEUED, input_payload={})
        result = execute_agent_run(str(run.id))

        run.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertTrue(run.output_payload.get("outline", {}).get("chapters"))
        self.assertEqual(self.project.chapters.count(), 2)
        self.assertIn("progress", run.output_payload)
        self.assertIn("nodes", run.timings_json)
        self.assertIn("run_toc_ms", run.timings_json.get("nodes", {}))
