from __future__ import annotations

from typing import Any, Dict

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import BookProject, Chapter, SourceDocument
from .serializers import BookProjectSerializer, ChapterSerializer, SourceDocumentSerializer
from .services.knowledge_base import extract_knowledge_text, index_source_document
from .services.llm import LLMService


class BookProjectViewSet(viewsets.ModelViewSet):
    queryset = BookProject.objects.none()
    serializer_class = BookProjectSerializer
    llm = LLMService()

    def get_queryset(self):
        return (
            BookProject.objects.filter(owner=self.request.user)
            .prefetch_related("chapters", "sources")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get", "post"], url_path="chapters")
    def chapters(self, request, pk=None):
        project = self.get_object()
        if request.method == "GET":
            serializer = ChapterSerializer(project.chapters.all(), many=True)
            return Response(serializer.data)

        payload = request.data.copy()
        payload["project"] = str(project.id)
        serializer = ChapterSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(project=project)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="sources")
    def sources(self, request, pk=None):
        project = self.get_object()
        if request.method == "GET":
            serializer = SourceDocumentSerializer(project.sources.all(), many=True)
            return Response(serializer.data)

        payload = request.data.copy()
        payload["project"] = str(project.id)
        serializer = SourceDocumentSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        source = serializer.save(project=project)
        index_stats = index_source_document(source)
        data = SourceDocumentSerializer(source).data
        data["index_stats"] = index_stats
        return Response(data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="knowledge-upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def knowledge_upload(self, request, pk=None):
        project = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            extracted = extract_knowledge_text(upload)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        title = str(request.data.get("title", "")).strip() or extracted["title"]
        source = SourceDocument.objects.create(
            project=project,
            title=title[:200],
            source_type=extracted["source_type"],
            content=extracted["content"],
            metadata_json={
                "file_name": extracted.get("file_name", ""),
                "ingest": "upload",
                "priority": str(request.data.get("priority", "supporting")).strip().lower() or "supporting",
            },
        )
        index_stats = index_source_document(source)
        data = SourceDocumentSerializer(source).data
        data["index_stats"] = index_stats
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="profile-assistant")
    def profile_assistant(self, request, pk=None):
        project = self.get_object()
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response({"detail": "message is required"}, status=status.HTTP_400_BAD_REQUEST)

        current_profile = request.data.get("current_profile", {})
        if not isinstance(current_profile, dict):
            current_profile = {}
        conversation = request.data.get("conversation", [])
        if not isinstance(conversation, list):
            conversation = []

        payload = self.llm.assist_profile(
            project=project,
            current_profile=current_profile,
            conversation=conversation,
            user_message=message,
        )
        self._apply_profile_updates_if_finalized(project, payload)
        return Response(payload)

    def _apply_profile_updates_if_finalized(self, project: BookProject, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        if not bool(payload.get("is_finalized")):
            return

        updates = payload.get("field_updates", {})
        if not isinstance(updates, dict) or not updates:
            return

        project_updates: Dict[str, Any] = {}
        if isinstance(updates.get("title"), str) and updates["title"].strip():
            project_updates["title"] = updates["title"].strip()[:160]
        if isinstance(updates.get("genre"), str) and updates["genre"].strip():
            project_updates["genre"] = updates["genre"].strip()[:80]
        if isinstance(updates.get("audience"), str) and updates["audience"].strip():
            project_updates["target_audience"] = updates["audience"].strip()[:80]
        if isinstance(updates.get("language"), str) and updates["language"].strip():
            project_updates["language"] = updates["language"].strip()[:40]
        if isinstance(updates.get("tone"), str) and updates["tone"].strip():
            project_updates["tone"] = updates["tone"].strip()[:80]
        if "length" in updates:
            try:
                project_updates["target_word_count"] = max(300, int(float(str(updates["length"]).strip())))
            except Exception:
                pass

        raw_meta = project.metadata_json if isinstance(project.metadata_json, dict) else {}
        user_concept = raw_meta.get("user_concept", {})
        if not isinstance(user_concept, dict):
            user_concept = {}
        profile = user_concept.get("profile", {})
        if not isinstance(profile, dict):
            profile = {}
        profile.update({str(k): v for k, v in updates.items()})
        user_concept["profile"] = profile

        new_meta = dict(raw_meta)
        new_meta["user_concept"] = user_concept
        new_meta["profile"] = profile
        project_updates["metadata_json"] = new_meta

        if project_updates:
            for field, value in project_updates.items():
                setattr(project, field, value)
            project.save(update_fields=list(project_updates.keys()) + ["updated_at"])


class ChapterViewSet(viewsets.ModelViewSet):
    queryset = Chapter.objects.none()
    serializer_class = ChapterSerializer

    def get_queryset(self):
        qs = Chapter.objects.select_related("project").filter(project__owner=self.request.user)
        project_id = self.request.query_params.get("project_id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def perform_create(self, serializer):
        serializer.save()


class SourceDocumentViewSet(viewsets.ModelViewSet):
    queryset = SourceDocument.objects.none()
    serializer_class = SourceDocumentSerializer

    def get_queryset(self):
        qs = SourceDocument.objects.select_related("project").filter(project__owner=self.request.user)
        project_id = self.request.query_params.get("project_id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def perform_create(self, serializer):
        source = serializer.save()
        index_source_document(source)
