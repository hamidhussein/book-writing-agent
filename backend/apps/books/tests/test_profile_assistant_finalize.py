from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from apps.books.models import BookProject
from apps.books.views import BookProjectViewSet


class ProfileAssistantFinalizeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assistant_user", password="pass12345")
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.project = BookProject.objects.create(
            owner=self.user,
            title="Draft Title",
            genre="Non-fiction",
            target_audience="General readers",
            language="English",
            tone="Informative",
            target_word_count=3000,
            metadata_json={},
        )
        self.url = f"/api/books/projects/{self.project.id}/profile-assistant/"

    def test_non_finalize_response_does_not_apply_field_updates(self):
        payload = {
            "assistant_reply": "Captured. Need one more detail.",
            "field_updates": {"title": "Should Not Apply", "genre": "Education"},
            "next_field": "audience",
            "is_finalized": False,
            "missing_required": ["audience"],
        }
        with patch.object(BookProjectViewSet.llm, "assist_profile", return_value=payload):
            response = self.client.post(self.url, {"message": "continue", "current_profile": {}}, format="json")

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "Draft Title")
        self.assertEqual(self.project.genre, "Non-fiction")

    def test_finalize_response_applies_project_and_profile_updates(self):
        payload = {
            "assistant_reply": "Finalized and applied.",
            "field_updates": {
                "title": "Applied Title",
                "genre": "Education",
                "audience": "University students",
                "language": "English",
                "tone": "Academic",
                "length": 4200,
                "writingStyle": "Instructional",
                "pointOfView": "Second Person",
            },
            "next_field": "",
            "is_finalized": True,
            "missing_required": [],
        }
        with patch.object(BookProjectViewSet.llm, "assist_profile", return_value=payload):
            response = self.client.post(self.url, {"message": "finalize", "current_profile": {}}, format="json")

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "Applied Title")
        self.assertEqual(self.project.genre, "Education")
        self.assertEqual(self.project.target_audience, "University students")
        self.assertEqual(self.project.tone, "Academic")
        self.assertEqual(self.project.target_word_count, 4200)
        user_profile = self.project.metadata_json.get("user_concept", {}).get("profile", {})
        self.assertEqual(user_profile.get("writingStyle"), "Instructional")
        self.assertEqual(user_profile.get("pointOfView"), "Second Person")

    def test_missing_required_prevents_finalization_updates(self):
        payload = {
            "assistant_reply": "Need more details before finalizing.",
            "field_updates": {"title": "Blocked Title"},
            "next_field": "genre",
            "is_finalized": False,
            "missing_required": ["genre"],
        }
        with patch.object(BookProjectViewSet.llm, "assist_profile", return_value=payload):
            response = self.client.post(self.url, {"message": "finalize", "current_profile": {}}, format="json")

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "Draft Title")
