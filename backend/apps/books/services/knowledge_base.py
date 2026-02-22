from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Dict

from docx import Document

from ..models import SourceDocument
from .llm import LLMService
from .vector_store import VectorMemoryStore

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


SUPPORTED_KB_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".doc"}
MAX_KB_TEXT_CHARS = 500_000
logger = logging.getLogger(__name__)


def extract_knowledge_text(uploaded_file) -> Dict[str, str]:
    filename = getattr(uploaded_file, "name", "knowledge")
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_KB_EXTENSIONS:
        raise ValueError("Unsupported file type. Use .txt, .md, .pdf, .docx, or .doc")

    raw = uploaded_file.read()
    if not raw:
        raise ValueError("Uploaded file is empty")

    if ext in {".txt", ".md"}:
        text = _decode_text(raw)
    elif ext == ".pdf":
        text = _extract_pdf_text(raw)
    elif ext == ".docx":
        text = _extract_docx_text(raw)
    elif ext == ".doc":
        # Legacy .doc parsing is unreliable without external system tools.
        # We explicitly guide users to a modern format for robust extraction.
        raise ValueError("Legacy .doc is not supported reliably. Please convert to .docx and upload again.")
    else:  # pragma: no cover
        raise ValueError("Unsupported file type")

    text = _normalize_text(text)
    if not text:
        raise ValueError("Could not extract readable text from file")

    if len(text) > MAX_KB_TEXT_CHARS:
        text = text[:MAX_KB_TEXT_CHARS]

    source_type = ext.lstrip(".") or "note"
    return {
        "title": Path(filename).stem[:180] or "Knowledge Source",
        "source_type": source_type,
        "content": text,
        "file_name": filename,
    }


def index_source_document(source: SourceDocument) -> Dict[str, int]:
    try:
        llm = LLMService()
        vector_store = VectorMemoryStore(llm)
        raw_meta = source.metadata_json if isinstance(source.metadata_json, dict) else {}
        priority = str(raw_meta.get("priority", "supporting")).strip().lower() or "supporting"
        return vector_store.upsert_source_memory(
            project_id=str(source.project_id),
            source_id=str(source.id),
            title=source.title,
            content=source.content or "",
            source_type=source.source_type or "note",
            source_priority_label=priority,
        )
    except Exception:
        logger.warning("Failed to index source document in vector store", exc_info=True)
        return {"chunks_total": 0, "chunks_indexed": 0}


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_pdf_text(raw: bytes) -> str:
    if PdfReader is None:
        raise ValueError("PDF parsing dependency is unavailable. Install pypdf.")
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def _extract_docx_text(raw: bytes) -> str:
    document = Document(io.BytesIO(raw))
    blocks = []
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\u0000", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
