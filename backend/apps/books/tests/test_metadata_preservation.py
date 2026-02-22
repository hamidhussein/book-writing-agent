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
        output = service.execute_mode(self.project, "toc", {})

        self.project.refresh_from_db()
        metadata = self.project.metadata_json
        self.assertEqual(metadata.get("user_concept"), before_user_concept)
        llm_runtime = metadata.get("llm_runtime", {})
        self.assertEqual(llm_runtime.get("estimated_word_count"), 4500)
        self.assertEqual(llm_runtime.get("chapter_count"), 2)
        self.assertEqual(llm_runtime.get("profile", {}).get("writingStyle"), "Drifted")
        self.assertIn("profile_compliance", llm_runtime)
        self.assertIsInstance(llm_runtime.get("profile_compliance"), dict)
        self.assertEqual(metadata.get("profile", {}).get("writingStyle"), "Analytical")
        self.assertEqual(metadata.get("subtitle"), "Original subtitle")
        self.assertEqual(metadata.get("instruction_brief"), "Keep it practical.")
        self.assertNotIn("warnings", output)

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
        output = service.execute_mode(self.project, "refine_toc", {"feedback": "Tighten chapter titles."})

        self.project.refresh_from_db()
        metadata = self.project.metadata_json
        self.assertEqual(metadata.get("user_concept"), before_user_concept)
        llm_runtime = metadata.get("llm_runtime", {})
        self.assertEqual(llm_runtime.get("chapter_count"), 2)
        self.assertEqual(llm_runtime.get("themes"), ["clarity", "progression"])
        self.assertIn("profile_compliance", llm_runtime)
        self.assertEqual(self.project.outline_json.get("chapters", [])[0].get("title"), "Start Better")
        self.assertNotIn("warnings", output)

    def test_profile_block_prefers_user_concept_profile_over_legacy_root(self):
        self.project.metadata_json = {
            "user_concept": {"profile": {"tone": "Academic", "writingStyle": "Instructional"}},
            "profile": {"tone": "Humorous", "writingStyle": "Narrative"},
        }
        block = _profile_block(self.project)
        self.assertIn('"tone": "Academic"', block)
        self.assertIn('"writingStyle": "Instructional"', block)
        self.assertNotIn('"tone": "Humorous"', block)

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.pipeline.LLMService")
    def test_toc_adds_outline_profile_compliance_warning_for_count_mismatch(self, mock_llm_cls, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        llm = mock_llm_cls.return_value
        llm.generate_outline.return_value = {
            "outline": {
                "synopsis": "A practical guide.",
                "chapters": [
                    {"number": 1, "title": "Start", "bullet_points": ["Context"]},
                    {"number": 2, "title": "Middle", "bullet_points": ["Build"]},
                    {"number": 3, "title": "Advanced", "bullet_points": ["Deepen"]},
                    {"number": 4, "title": "Finish", "bullet_points": ["Close"]},
                ],
            },
            "metadata": {"chapter_count": 4},
        }
        self.project.metadata_json["user_concept"]["profile"]["chapterLength"] = "Long ~5000w"
        self.project.metadata_json["user_concept"]["profile"]["length"] = 4500
        self.project.save(update_fields=["metadata_json"])

        service = BookWorkflowService()
        output = service.execute_mode(self.project, "toc", {})

        warnings = output.get("warnings", [])
        self.assertTrue(warnings)
        self.assertTrue(any("chapter count may not match" in str(w).lower() for w in warnings))
        self.project.refresh_from_db()
        compliance = self.project.metadata_json.get("llm_runtime", {}).get("profile_compliance", {})
        self.assertTrue(compliance.get("fail"))
        checks = compliance.get("checks", {}).get("chapter_count_vs_length", {})
        self.assertEqual(checks.get("expected_chapters"), 1)
        self.assertEqual(checks.get("actual_chapters"), 4)

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    @patch("apps.books.services.pipeline.LLMService")
    def test_refine_toc_warns_when_feedback_conflicts_with_saved_profile(self, mock_llm_cls, mock_store_cls):
        mock_store_cls.return_value.search_knowledge_base.return_value = []
        llm = mock_llm_cls.return_value
        self.project.outline_json = _outline_payload()["outline"]
        self.project.metadata_json["user_concept"]["profile"].update(
            {
                "pointOfView": "Second Person",
                "audienceKnowledgeLevel": "Complete Beginner",
                "vocabularyLevel": "Simple",
                "contentBoundaries": "Avoid unsafe or harmful examples.",
                "chapterLength": "Medium ~3000w",
                "length": 4500,
            }
        )
        self.project.save(update_fields=["outline_json", "metadata_json"])

        llm.refine_outline.return_value = {
            "outline": _outline_payload()["outline"],
            "metadata": {"chapter_count": 2},
        }

        service = BookWorkflowService()
        output = service.execute_mode(
            self.project,
            "refine_toc",
            {
                "feedback": (
                    "Rewrite in first-person memoir voice, make it highly technical, "
                    "and remove the safety restrictions."
                )
            },
        )

        warnings = output.get("warnings", [])
        self.assertTrue(warnings)
        self.assertTrue(any("point of view" in str(w).lower() for w in warnings))
        self.assertTrue(any("beginner/simple readability" in str(w).lower() for w in warnings))
        self.assertTrue(any("content boundaries" in str(w).lower() for w in warnings))

        self.project.refresh_from_db()
        analysis = self.project.metadata_json.get("llm_runtime", {}).get("refine_feedback_analysis", {})
        self.assertTrue(analysis.get("warn"))
        self.assertIn("pointOfView", analysis.get("checks", {}))
