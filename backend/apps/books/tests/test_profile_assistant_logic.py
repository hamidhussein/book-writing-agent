from __future__ import annotations

from django.test import SimpleTestCase

from apps.books.services.llm import (
    LLMService,
    _missing_required_profile,
    _normalize_profile_value,
)


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

    def test_normalizer_trusts_valid_llm_next_field_even_if_not_first_missing(self):
        current_profile = _base_profile()
        current_profile.update({"title": "", "genre": "", "language": ""})
        payload = {
            "assistant_reply": "What genre fits best?",
            "field_updates": {},
            "next_field": "genre",
            "is_finalized": False,
            "missing_required": ["title", "genre", "language"],
        }

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="let us decide genre first",
            conversation=[],
        )

        self.assertEqual(normalized["next_field"], "genre")
        self.assertIn("genre", normalized["missing_required"])

    def test_normalizer_advances_when_model_points_to_field_just_captured(self):
        current_profile = _base_profile()
        current_profile.update({"title": "AI for Kids", "genre": "", "language": ""})
        payload = {
            "assistant_reply": "Great, education genre works. Next?",
            "field_updates": {"genre": "Education"},
            "next_field": "genre",
            "is_finalized": False,
            "missing_required": ["genre", "language"],
        }

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="education",
            conversation=[],
        )

        self.assertEqual(normalized["field_updates"].get("genre"), "Education")
        self.assertEqual(normalized["next_field"], "language")
        self.assertIn("language", normalized["missing_required"])
        self.assertNotIn("genre", normalized["missing_required"])

    def test_normalizer_maps_child_age_range_to_audience(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "Got it. What tone do you want?",
            "field_updates": {},
            "next_field": "tone",
            "is_finalized": False,
            "missing_required": ["title"],
        }

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="Around 10-14 years old for kids",
            conversation=[],
        )

        self.assertEqual(normalized["field_updates"].get("audience"), "Kids ages 10-14")
        self.assertEqual(normalized["field_updates"].get("audienceKnowledgeLevel"), "Complete Beginner")

    def test_normalizer_filters_meta_and_finalize_suggestions_when_required_missing(self):
        current_profile = _base_profile()
        payload = {
            "assistant_reply": "What AI concepts should the book cover?",
            "field_updates": {},
            "next_field": "customInstructions",
            "is_finalized": False,
            "missing_required": ["title"],
            "suggestions": [
                "Let's finalize the title",
                "Move on to chapter length",
                "AI basics and fun activities",
            ],
        }

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="help me decide topics",
            conversation=[],
        )

        self.assertIn("AI basics and fun activities", normalized["suggestions"])
        self.assertNotIn("Let's finalize the title", normalized["suggestions"])
        self.assertNotIn("Move on to chapter length", normalized["suggestions"])

    def test_optional_batch_is_deferred_in_early_conversation(self):
        current_profile = _base_profile()
        current_profile["title"] = "AI for Kids"
        payload = {
            "assistant_reply": "We can finalize now if you want.",
            "field_updates": {},
            "next_field": "",
            "is_finalized": False,
            "missing_required": [],
        }
        short_conversation = [
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "AI for Kids"},
            {"role": "assistant", "content": "Nice title."},
            {"role": "user", "content": "Thanks"},
        ]

        normalized = self.llm._normalize_assistant_payload(  # noqa: SLF001
            payload=payload,
            current_profile=current_profile,
            user_message="ok",
            conversation=short_conversation,
        )

        self.assertEqual(normalized["next_field"], "")
        self.assertIn("reply 'finalize'", normalized["assistant_reply"].lower())
        self.assertNotIn("optional details", normalized["assistant_reply"].lower())

    def test_normalize_profile_value_maps_vocabulary_and_tone_synonyms(self):
        self.assertEqual(_normalize_profile_value("vocabularyLevel", "basic"), "Simple")
        self.assertEqual(_normalize_profile_value("vocabularyLevel", "advanced"), "Technical")
        self.assertEqual(_normalize_profile_value("tone", "friendly"), "Conversational")
        self.assertEqual(_normalize_profile_value("tone", "educational"), "Informative")
