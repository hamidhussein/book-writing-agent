from __future__ import annotations

from dataclasses import dataclass

from django.test import TestCase

from apps.books.services import vector_store as vector_store_module
from apps.books.services.vector_store import VectorMemoryStore


class _DummyLLM:
    def embed(self, _text: str):
        return [0.1, 0.2, 0.3]


@dataclass
class _Hit:
    payload: dict
    score: float


class _InMemoryVectorClient:
    def __init__(self):
        self.points = []

    def upsert(self, collection_name, points):
        self.points.extend(points)

    def search(self, collection_name, query_vector, query_filter, limit, with_payload):
        must_conditions = list(getattr(query_filter, "must", []) or [])
        out = []
        for point in self.points:
            payload = getattr(point, "payload", {}) or {}
            if _payload_matches(payload, must_conditions):
                out.append(_Hit(payload=payload, score=0.91))
        return out[:limit]


class _StaticSearchClient:
    def __init__(self, hits):
        self.hits = list(hits)

    def search(self, collection_name, query_vector, query_filter, limit, with_payload):
        return self.hits[:limit]


def _payload_matches(payload, conditions):
    for cond in conditions:
        key = str(getattr(cond, "key", "")).strip()
        expected = getattr(getattr(cond, "match", None), "value", None)
        if payload.get(key) != expected:
            return False
    return True


class VectorRetrievalTests(TestCase):
    def setUp(self):
        if vector_store_module.qmodels is None:
            self.skipTest("qdrant-client models unavailable")

    def _make_store(self) -> VectorMemoryStore:
        store = VectorMemoryStore.__new__(VectorMemoryStore)
        store.collection = "test_collection"
        store._llm = _DummyLLM()
        store._client = _InMemoryVectorClient()
        return store

    def test_chapter_memory_roundtrip_returns_indexed_content(self):
        store = self._make_store()
        indexed = store.upsert_chapter_memory(
            project_id="p1",
            chapter_number=1,
            title="Chapter One",
            content="This chapter contains continuity details.",
            summary="Continuity summary.",
        )
        self.assertTrue(indexed)

        hits = store.search_memory(project_id="p1", query="continuity", limit=5)
        self.assertTrue(hits)
        self.assertIn("Chapter One", hits[0])
        self.assertIn("Continuity summary.", hits[0])

    def test_priority_rerank_promotes_primary_source(self):
        store = self._make_store()
        store._client = _StaticSearchClient(
            [
                _Hit(
                    payload={
                        "title": "Supporting Notes",
                        "source_type": "pdf",
                        "source_priority_label": "supporting",
                        "source_priority_weight": 3,
                        "content": "supporting facts",
                    },
                    score=0.82,
                ),
                _Hit(
                    payload={
                        "title": "Primary Guide",
                        "source_type": "pdf",
                        "source_priority_label": "primary",
                        "source_priority_weight": 5,
                        "content": "primary guidance",
                    },
                    score=0.74,
                ),
            ]
        )

        lines = store.search_knowledge_base(project_id="p1", query="guide", limit=2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("[pdf|primary] Primary Guide"))

    def test_missing_priority_payload_defaults_to_supporting(self):
        store = self._make_store()
        store._client = _StaticSearchClient(
            [
                _Hit(
                    payload={
                        "title": "Legacy Source",
                        "source_type": "txt",
                        "content": "legacy content",
                    },
                    score=0.5,
                )
            ]
        )
        lines = store.search_knowledge_base(project_id="p1", query="legacy", limit=1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("[txt|supporting] Legacy Source"))
