from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.books.models import BookProject
from apps.books.services.llm import LLMService


class RefineNonNegotiablesPromptTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="refine_prompt_user", password="pass12345")
        self.project = BookProject.objects.create(
            owner=self.user,
            title="Prompt Test",
            genre="Education",
            target_audience="Beginners",
            language="English",
            tone="Informative",
            target_word_count=12000,
            metadata_json={
                "user_concept": {
                    "profile": {
                        "audience": "Kids ages 10-14",
                        "audienceKnowledgeLevel": "Complete Beginner",
                        "bookPurpose": "Teach a Skill",
                        "tone": "Informative",
                        "pointOfView": "Second Person",
                        "chapterLength": "Short ~1500w",
                        "length": 12000,
                        "contentBoundaries": "Avoid unsafe experimentation guidance.",
                    }
                }
            },
        )

    @patch.object(LLMService, "_call_json")
    def test_refine_outline_prompt_includes_non_negotiable_constraints_block(self, mock_call_json):
        mock_call_json.return_value = {
            "outline": {
                "synopsis": "Refined synopsis.",
                "chapters": [
                    {"number": 1, "title": "Start", "bullet_points": ["Context"]},
                    {"number": 2, "title": "Build", "bullet_points": ["Practice"]},
                ],
            }
        }
        service = LLMService()
        existing_outline = {
            "synopsis": "Original synopsis.",
            "chapters": [
                {"number": 1, "title": "Start", "bullet_points": ["Context"]},
                {"number": 2, "title": "Build", "bullet_points": ["Practice"]},
            ],
        }

        service.refine_outline(
            self.project,
            existing_outline,
            "Tighten the chapter titles and improve progression.",
            knowledge_context=[],
        )

        self.assertTrue(mock_call_json.called)
        system_prompt, user_prompt = mock_call_json.call_args.args[:2]
        self.assertIn("preserve non-negotiable brief constraints", system_prompt.lower())
        self.assertIn("Non-Negotiable Brief Constraints", user_prompt)
        self.assertIn("Audience: Kids ages 10-14", user_prompt)
        self.assertIn("Book Purpose: Teach a Skill", user_prompt)
        self.assertIn("Tone: Informative", user_prompt)
        self.assertIn("Point of View: Second Person", user_prompt)
        self.assertIn("Content Boundaries: Avoid unsafe experimentation guidance.", user_prompt)
        self.assertIn("Preserve these constraints unless the editorial feedback explicitly asks to change them", user_prompt)
