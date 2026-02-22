from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient

from apps.books.models import BookProject


class AuthOwnershipTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user_a = user_model.objects.create_user(username="owner_a", password="pass12345")
        self.user_b = user_model.objects.create_user(username="owner_b", password="pass12345")
        self.token_a = Token.objects.create(user=self.user_a)
        self.token_b = Token.objects.create(user=self.user_b)

        self.project_a = BookProject.objects.create(
            owner=self.user_a,
            title="A Book",
            genre="Non-fiction",
            target_audience="General readers",
            language="English",
            tone="Informative",
            target_word_count=3000,
        )
        self.project_b = BookProject.objects.create(
            owner=self.user_b,
            title="B Book",
            genre="Education",
            target_audience="Students",
            language="English",
            tone="Academic",
            target_word_count=3200,
        )

    def test_unauthenticated_requests_receive_401(self):
        client = APIClient()
        books_response = client.get("/api/books/projects/")
        runs_response = client.get("/api/agents/runs/")
        self.assertEqual(books_response.status_code, 401)
        self.assertEqual(runs_response.status_code, 401)

    def test_user_cannot_access_other_users_project(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_b.key}")
        response = self.client.get(f"/api/books/projects/{self.project_a.id}/")
        patch_response = self.client.patch(
            f"/api/books/projects/{self.project_a.id}/",
            {"title": "Unauthorized Edit"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(patch_response.status_code, 404)

    def test_agent_run_creation_rejects_foreign_project(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_b.key}")
        response = self.client.post(
            "/api/agents/runs/",
            {"project_id": str(self.project_a.id), "mode": "toc", "inputs": {}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id", response.data)

    def test_list_endpoints_are_owner_scoped(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")
        response = self.client.get("/api/books/projects/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.project_a.id), ids)
        self.assertNotIn(str(self.project_b.id), ids)
