from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from django.conf import settings

from .llm import LLMService

logger = logging.getLogger(__name__)
PRIORITY_WEIGHT_MAP = {
    "primary": 5,
    "supporting": 3,
    "tone-only": 1,
}

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # pragma: no cover
    QdrantClient = None
    qmodels = None


class VectorMemoryStore:
    """
    Wrapper around Qdrant for chapter-level memory.
    Safe no-op behavior if Qdrant or embeddings are not configured.
    """

    def __init__(self, llm_service: LLMService) -> None:
        self.collection = settings.QDRANT_COLLECTION
        self._llm = llm_service
        self._client = None
        if QdrantClient is not None:
            try:
                self._client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY or None,
                    timeout=10.0,
                )
                self._ensure_collection()
            except Exception:
                logger.warning("Failed to initialize Qdrant client", exc_info=True)
                self._client = None

    def _ensure_collection(self) -> None:
        if not self._client or qmodels is None:
            return
        collections = self._client.get_collections().collections
        existing = {c.name for c in collections}
        if self.collection in existing:
            return
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(
                size=3072,
                distance=qmodels.Distance.COSINE,
            ),
        )

    def upsert_chapter_memory(
        self,
        project_id: str,
        chapter_number: int,
        title: str,
        content: str,
        summary: str,
    ) -> bool:
        if not self._client or qmodels is None:
            return False

        vector = self._llm.embed(f"{title}\n{summary}\n{content[:8000]}")
        if not vector:
            return False

        point_id = str(uuid.uuid4())
        payload = {
            "project_id": project_id,
            "memory_type": "chapter",
            "chapter_number": chapter_number,
            "title": title,
            "summary": summary,
            "content": content[:12000],
        }
        self._client.upsert(
            collection_name=self.collection,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        return True

    def upsert_source_memory(
        self,
        project_id: str,
        source_id: str,
        title: str,
        content: str,
        source_type: str = "note",
        source_priority_label: str = "supporting",
    ) -> dict:
        if not self._client or qmodels is None:
            return {"chunks_total": 0, "chunks_indexed": 0}

        chunks = self._chunk_text(content)
        if not chunks:
            return {"chunks_total": 0, "chunks_indexed": 0}
        priority_label = str(source_priority_label or "supporting").strip().lower()
        priority_weight = self._priority_to_weight(priority_label)

        points = []
        for idx, chunk in enumerate(chunks):
            vector = self._llm.embed(chunk)
            if not vector:
                continue
            payload = {
                "project_id": project_id,
                "memory_type": "kb",
                "source_id": source_id,
                "source_type": source_type,
                "source_priority_label": priority_label,
                "source_priority_weight": priority_weight,
                "title": title[:200],
                "chunk_index": idx,
                "content": chunk[:6000],
            }
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload,
                )
            )

        if points:
            self._client.upsert(
                collection_name=self.collection,
                points=points,
            )

        return {"chunks_total": len(chunks), "chunks_indexed": len(points)}

    def search_memory(self, project_id: str, query: str, limit: int = 5) -> List[str]:
        if not self._client or qmodels is None:
            return []

        vector = self._llm.embed(query)
        if not vector:
            return []

        search_result = self._client.search(
            collection_name=self.collection,
            query_vector=vector,
            query_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="project_id", match=qmodels.MatchValue(value=project_id))]
            ),
            limit=limit,
            with_payload=True,
        )

        memories: List[str] = []
        for point in search_result:
            payload = point.payload or {}
            title = str(payload.get("title", "")).strip()
            summary = str(payload.get("summary", "")).strip()
            text = str(payload.get("content", "")).strip()
            line = f"{title}\n{summary}\n{text[:500]}"
            memories.append(line.strip())
        return memories

    def search_knowledge_base(self, project_id: str, query: str, limit: int = 6) -> List[str]:
        if not self._client or qmodels is None:
            return []

        vector = self._llm.embed(query)
        if not vector:
            return []

        search_result = self._client.search(
            collection_name=self.collection,
            query_vector=vector,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="project_id", match=qmodels.MatchValue(value=project_id)),
                    qmodels.FieldCondition(key="memory_type", match=qmodels.MatchValue(value="kb")),
                ]
            ),
            limit=limit,
            with_payload=True,
        )

        ranked_items: List[Dict[str, Any]] = []
        for point in search_result:
            payload = point.payload or {}
            title = str(payload.get("title", "")).strip()
            source_type = str(payload.get("source_type", "")).strip()
            priority_label = str(payload.get("source_priority_label", "supporting")).strip().lower() or "supporting"
            priority_weight_raw = payload.get("source_priority_weight", self._priority_to_weight(priority_label))
            try:
                priority_weight = max(1, min(5, int(float(str(priority_weight_raw)))))
            except Exception:
                priority_weight = self._priority_to_weight(priority_label)
            text = str(payload.get("content", "")).strip()
            semantic_score = float(getattr(point, "score", 0.0) or 0.0)
            final_score = semantic_score * (1.0 + 0.2 * priority_weight)
            line = f"[{source_type}|{priority_label}] {title}\n{text[:700]}".strip()
            ranked_items.append({"final_score": final_score, "line": line})
        ranked_items.sort(key=lambda item: item["final_score"], reverse=True)
        return [item["line"] for item in ranked_items[:limit]]

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
        if not text:
            return []
        norm = " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()
        if not norm:
            return []
        if len(norm) <= chunk_size:
            return [norm]

        chunks: List[str] = []
        start = 0
        text_len = len(norm)
        while start < text_len:
            end = min(text_len, start + chunk_size)
            chunk = norm[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_len:
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _priority_to_weight(self, label: str) -> int:
        return PRIORITY_WEIGHT_MAP.get(str(label or "").strip().lower(), PRIORITY_WEIGHT_MAP["supporting"])
