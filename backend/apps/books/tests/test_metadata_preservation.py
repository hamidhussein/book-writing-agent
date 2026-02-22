from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.books.models import BookProject
from apps.books.services.llm import _profile_block
from apps.books.services.pipeline import BookWorkflowService


def _outline_payload() -> dict:
    return {
        "outline": {
            "synopsis": "A practical guide.",
            "chapters": [
                {"number": 1, "title": "Start", "bullet_points": ["Context", "Goal"]},
                {"number": 2, "title": "Build", "bullet_points": ["Steps", "Examples"]},
            ],
        }
    }


class MetadataPreservationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="meta_user", password="pass12345")
        self.project = BookProject.objects.create(
            owner=self.user,
            title="Original Title",
            genre="Education",
            target_audience="Beginners",
            language="English",
            tone="Instructional",
            target_word_count=4500,
            metadata_json={
                "user_concept": {
                    "title": "Original Title",
                    "genre": "Education",
                    "target_audience": "Beginners",
                    "language": "English",
                    "tone": "Instructional",
                    "target_word_count": 4500,
                    "subtitle": "Original subtitle",
                    "instruction_brief": "Keep it practical.",
                    "profile": {"writingStyle": "Analytical", "tone": "Instructional"},
                },
                "llm_runtime": {"chapter_count": 5},
                "profile": {"writingStyle": "Analytical", "tone": "Instructional"},
            },
        )

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.pipeline.LLMService")
    def test_toc_preserves_user_concept_and_updates_llm_runtime(self, mock_llm_cls, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        llm = mock_llm_cls.return_value
        payload = _outline_payload()
        payload["metadata"] = {
            "estimated_word_count": 4500,
            "chapter_count": 2,
            "profile": {"writingStyle": "Drifted"},
        }
        llm.generate_outline.return_value = payload

        service = BookWorkflowService()
        before_user_concept = deepcopy(self.project.metadata_json["user_concept"])
        service.execute_mode(self.project, "toc", {})

        self.project.refresh_from_db()
        metadata = self.project.metadata_json
        self.assertEqual(metadata.get("user_concept"), before_user_concept)
        self.assertEqual(metadata.get("llm_runtime"), payload["metadata"])
        self.assertEqual(metadata.get("profile", {}).get("writingStyle"), "Analytical")
        self.assertEqual(metadata.get("subtitle"), "Original subtitle")
        self.assertEqual(metadata.get("instruction_brief"), "Keep it practical.")

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.pipeline.LLMService")
    def test_refine_toc_preserves_user_concept_and_refreshes_llm_runtime(self, mock_llm_cls, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        llm = mock_llm_cls.return_value
        initial_outline = _outline_payload()["outline"]
        self.project.outline_json = initial_outline
        self.project.save(update_fields=["outline_json"])

        refine_payload = {
            "outline": {
                "synopsis": "Refined synopsis.",
                "chapters": [
                    {"number": 1, "title": "Start Better", "bullet_points": ["Context", "Sharper goal"]},
                    {"number": 2, "title": "Build Better", "bullet_points": ["Steps", "Case study"]},
                ],
            },
            "metadata": {"chapter_count": 2, "themes": ["clarity", "progression"]},
        }
        llm.refine_outline.return_value = refine_payload

        service = BookWorkflowService()
        before_user_concept = deepcopy(self.project.metadata_json["user_concept"])
        service.execute_mode(self.project, "refine_toc", {"feedback": "Tighten chapter titles."})

        self.project.refresh_from_db()
        metadata = self.project.metadata_json
        self.assertEqual(metadata.get("user_concept"), before_user_concept)
        self.assertEqual(metadata.get("llm_runtime"), refine_payload["metadata"])
        self.assertEqual(self.project.outline_json.get("chapters", [])[0].get("title"), "Start Better")

    def test_profile_block_prefers_user_concept_profile_over_legacy_root(self):
        self.project.metadata_json = {
            "user_concept": {"profile": {"tone": "Academic", "writingStyle": "Instructional"}},
            "profile": {"tone": "Humorous", "writingStyle": "Narrative"},
        }
        block = _profile_block(self.project)
        self.assertIn('"tone": "Academic"', block)
        self.assertIn('"writingStyle": "Instructional"', block)
        self.assertNotIn('"tone": "Humorous"', block)
