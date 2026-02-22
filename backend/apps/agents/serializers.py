from __future__ import annotations

from rest_framework import serializers

from apps.books.models import BookProject

from .models import AgentRun, RunMode


class AgentRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRun
        fields = [
            "id",
            "trace_id",
            "project",
            "mode",
            "status",
            "input_payload",
            "output_payload",
            "timings_json",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


class AgentRunCreateSerializer(serializers.Serializer):
    project_id = serializers.UUIDField(required=True)
    mode = serializers.ChoiceField(choices=RunMode.choices)
    inputs = serializers.JSONField(required=False, default=dict)

    def validate_project_id(self, value):
        qs = BookProject.objects.filter(id=value)
        request = self.context.get("request")
        if request:
            qs = qs.filter(owner=request.user)
        if not qs.exists():
            raise serializers.ValidationError("Invalid project_id")
        return value

    def validate(self, attrs):
        mode = attrs["mode"]
        inputs = attrs.get("inputs", {}) or {}
        if mode == RunMode.REFINE_TOC and not str(inputs.get("feedback", "")).strip():
            raise serializers.ValidationError({"inputs.feedback": "feedback is required for refine_toc mode"})
        if mode == RunMode.CHAPTER and inputs.get("chapter_number") in (None, ""):
            raise serializers.ValidationError({"inputs.chapter_number": "chapter_number is required for chapter mode"})
        if mode == RunMode.EXPORT:
            fmt = str(inputs.get("export_format", "pdf")).strip().lower()
            if fmt not in {"pdf", "docx", "both"}:
                raise serializers.ValidationError({"inputs.export_format": "must be pdf | docx | both"})
        if mode == RunMode.PROFILE_ASSISTANT:
            if not str(inputs.get("message", "")).strip():
                raise serializers.ValidationError({"inputs.message": "message is required for profile_assistant mode"})
        return attrs
