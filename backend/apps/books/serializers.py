from __future__ import annotations

from rest_framework import serializers

from .models import BookProject, Chapter, SourceDocument


class ChapterSerializer(serializers.ModelSerializer):
    def validate_project(self, value):
        request = self.context.get("request")
        if request and value.owner_id != request.user.id:
            raise serializers.ValidationError("Invalid project")
        return value

    class Meta:
        model = Chapter
        fields = [
            "id",
            "project",
            "number",
            "title",
            "content",
            "summary",
            "status",
            "vector_indexed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "vector_indexed"]


class SourceDocumentSerializer(serializers.ModelSerializer):
    def validate_project(self, value):
        request = self.context.get("request")
        if request and value.owner_id != request.user.id:
            raise serializers.ValidationError("Invalid project")
        return value

    class Meta:
        model = SourceDocument
        fields = [
            "id",
            "project",
            "title",
            "source_type",
            "content",
            "metadata_json",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class BookProjectSerializer(serializers.ModelSerializer):
    chapters = ChapterSerializer(many=True, read_only=True)
    sources = SourceDocumentSerializer(many=True, read_only=True)
    owner = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = BookProject
        fields = [
            "id",
            "owner",
            "title",
            "genre",
            "target_audience",
            "language",
            "tone",
            "target_word_count",
            "status",
            "outline_json",
            "metadata_json",
            "chapters",
            "sources",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "status"]
