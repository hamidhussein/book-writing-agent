from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class OutlineChapter(TypedDict):
    number: int
    title: str
    bullet_points: List[str]


class OutlineObject(TypedDict):
    synopsis: str
    chapters: List[OutlineChapter]


class ChapterObject(TypedDict):
    number: int
    title: str
    content: str
    summary: str


class AgentPayload(TypedDict, total=False):
    status: str
    outline: OutlineObject
    chapter: ChapterObject
    metadata: Dict[str, Any]
    next_steps: List[str]
    warnings: List[str]
    errors: List[str]
    pdf_base64: str
    pdf_filename: str
    docx_base64: str
    docx_filename: str
