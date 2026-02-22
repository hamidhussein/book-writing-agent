from __future__ import annotations

from django.test import SimpleTestCase

from apps.books.services.llm import LLMService, _missing_required_profile


def _base_profile() -> dict:
    return {
        "title": "",
        "genre": "Non-fiction",
        "language": "English",
        "length": 3000,
        "publishingIntent": "Self-publish",
        "audience": "General readers",
        "audienceKnowledgeLevel": "Complete Beginner",
        "bookPurpose": "Teach a Skill",
        "tone": "Informative",
        "writingStyle": "Instructional",
        "pointOfView": "Second Person",
        "sentenceRhythm": "Mixed",
        "vocabularyLevel": "Intermediate",
        "chapterLength": "Medium ~3000w",
    }


class ProfileAssistantLogicTests(SimpleTestCase):
    def setUp(self):
        self.llm = LLMService()

    def test_missing_required_treats_placeholder_title_as_missing(self):
        profile = _base_profile()
        profile["title"] = "Untitled Project"

        missing = _missing_required_profile(profile)

        self.assertIn("title", missing)

    def test_normalizer_rejects_ungrounded_title_update(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "Captured.",
            "field_updates": {"title": "AI Launchpad for Kids"},
            "next_field": "",
            "is_finalized": False,
            "missing_required": [],
        }
        conversation = [{"role": "user", "content": "suggest me a good name"}]

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="suggest me a good name",
            conversation=conversation,
        )

        self.assertNotIn("title", normalized["field_updates"])
        self.assertIn("title", normalized["missing_required"])

    def test_normalizer_accepts_title_when_user_provides_it(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "Captured.",
            "field_updates": {"title": "AI Launchpad for Kids"},
            "next_field": "",
            "is_finalized": False,
            "missing_required": [],
        }
        conversation = [{"role": "user", "content": "Use the title AI Launchpad for Kids"}]

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="Use the title AI Launchpad for Kids",
            conversation=conversation,
        )

        self.assertEqual(normalized["field_updates"].get("title"), "AI Launchpad for Kids")
        self.assertNotIn("title", normalized["missing_required"])

    def test_normalizer_accepts_assistant_suggested_title_after_user_confirmation(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "Captured.",
            "field_updates": {"title": "AI Adventures for Kids"},
            "next_field": "",
            "is_finalized": False,
            "missing_required": [],
        }
        conversation = [
            {"role": "assistant", "content": "How about the title 'AI Adventures for Kids'?"},
            {"role": "user", "content": "this name is fine"},
        ]

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="this name is fine",
            conversation=conversation,
        )

        self.assertEqual(normalized["field_updates"].get("title"), "AI Adventures for Kids")
        self.assertNotIn("title", normalized["missing_required"])

    def test_normalizer_overrides_completion_reply_when_required_still_missing(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "All required fields are now filled. Would you like to finalize?",
            "field_updates": {},
            "next_field": "",
            "is_finalized": False,
            "missing_required": [],
        }

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="ok",
            conversation=[],
        )

        self.assertFalse(normalized["is_finalized"])
        self.assertIn("title", normalized["missing_required"])
        self.assertIn("book title", normalized["assistant_reply"].lower())
