from __future__ import annotations

import base64
import io
import re
from typing import Any, Dict, List

from django.utils import timezone

from ..models import BookProject, Chapter, ChapterStatus, ProjectStatus
from .llm import LLMService
from .vector_store import VectorMemoryStore


class BookWorkflowService:
    def __init__(self) -> None:
        self.llm = LLMService()
        self.vector_store = VectorMemoryStore(self.llm)

    def execute_mode(self, project: BookProject, mode: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if mode == "toc":
            return self._run_toc(project)
        if mode == "refine_toc":
            return self._run_refine_toc(project, inputs)
        if mode == "chapter":
            return self._run_chapter(project, inputs)
        if mode == "export":
            return self._run_export(project, inputs)
        if mode == "profile_assistant":
            return self._run_profile_assistant(project, inputs)
        raise ValueError("mode must be one of: toc | refine_toc | chapter | export | profile_assistant")

    def _run_toc(self, project: BookProject) -> Dict[str, Any]:
        kb_context = self.vector_store.search_knowledge_base(
            project_id=str(project.id),
            query=f"{project.title} {project.genre} {project.target_audience} book plan",
            limit=8,
        )
        payload = self.llm.generate_outline(project, knowledge_context=kb_context)
        outline = self._normalize_outline(payload.get("outline", {}))
        fallback_info = self._runtime_fallback_info(payload)

        project.outline_json = outline
        project.metadata_json = self._merge_project_metadata(project, payload.get("metadata", {}))
        project.status = ProjectStatus.OUTLINED
        project.updated_at = timezone.now()
        project.save(update_fields=["outline_json", "metadata_json", "status", "updated_at"])

        self._sync_chapters_from_outline(project, outline)

        return {
            "status": "success",
            "outline": outline,
            "metadata": project.metadata_json,
            "used_fallback": fallback_info["used_fallback"],
            "fallback_stages": fallback_info["fallback_stages"],
            "next_steps": payload.get(
                "next_steps",
                [
                    "Review the generated outline.",
                    "Refine the outline with targeted feedback.",
                    "Generate chapters one-by-one once approved.",
                ],
            ),
        }

    def _run_refine_toc(self, project: BookProject, inputs: Dict[str, Any]) -> Dict[str, Any]:
        feedback = str(inputs.get("feedback", "")).strip()
        if not feedback:
            raise ValueError("feedback is required for refine_toc mode")
        existing_outline = project.outline_json or {}
        kb_context = self.vector_store.search_knowledge_base(
            project_id=str(project.id),
            query=f"{project.title} outline refinement {feedback}",
            limit=8,
        )
        payload = self.llm.refine_outline(
            project,
            existing_outline,
            feedback,
            knowledge_context=kb_context,
        )
        outline = self._normalize_outline(payload.get("outline", {}))
        fallback_info = self._runtime_fallback_info(payload)

        project.outline_json = outline
        project.metadata_json = self._merge_project_metadata(project, payload.get("metadata", {}))
        project.status = ProjectStatus.OUTLINED
        project.updated_at = timezone.now()
        project.save(update_fields=["outline_json", "metadata_json", "status", "updated_at"])

        self._sync_chapters_from_outline(project, outline)

        return {
            "status": "success",
            "outline": outline,
            "metadata": project.metadata_json,
            "used_fallback": fallback_info["used_fallback"],
            "fallback_stages": fallback_info["fallback_stages"],
            "next_steps": payload.get(
                "next_steps",
                [
                    "Review the refined outline.",
                    "Generate the next chapter.",
                ],
            ),
        }

    def _run_profile_assistant(self, project: BookProject, inputs: Dict[str, Any]) -> Dict[str, Any]:
        message = str(inputs.get("message", "")).strip()
        current_profile = inputs.get("current_profile", {})
        if not isinstance(current_profile, dict):
            current_profile = {}
        conversation = inputs.get("conversation", [])
        if not isinstance(conversation, list):
            conversation = []

        payload = self.llm.assist_profile(
            project=project,
            current_profile=current_profile,
            conversation=conversation,
            user_message=message,
        )
        self._apply_profile_updates_if_finalized(project, payload)
        
        fallback_info = self._runtime_fallback_info(payload)
        return {
            "status": "success",
            "assistant_response": payload,
            "used_fallback": fallback_info["used_fallback"],
            "fallback_stages": fallback_info["fallback_stages"],
        }

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

    def _run_chapter(self, project: BookProject, inputs: Dict[str, Any]) -> Dict[str, Any]:
        chapter_ctx = self.prepare_chapter_context(project, inputs)
        payload = self.llm.generate_chapter(
            project,
            chapter_ctx["outline"],
            chapter_ctx["chapter_number"],
            memory_context=chapter_ctx["memory_context"],
            knowledge_context=chapter_ctx["knowledge_context"],
        )
        fallback_info = self._runtime_fallback_info(payload)
        return self.persist_chapter_result(
            project=project,
            outline=chapter_ctx["outline"],
            chapter_number=chapter_ctx["chapter_number"],
            target=chapter_ctx["target"],
            chapter_data=payload.get("chapter", {}),
            metadata=self._merge_dicts(payload.get("metadata", {}), fallback_info),
            next_steps=payload.get(
                "next_steps",
                ["Review the chapter and proceed to the next one."],
            ),
        )

    def prepare_chapter_context(self, project: BookProject, inputs: Dict[str, Any]) -> Dict[str, Any]:
        outline = self._normalize_outline(project.outline_json or {})
        if not outline.get("chapters"):
            raise ValueError("Project does not have an outline yet")

        chapter_number = self._to_int(inputs.get("chapter_number"), "chapter_number")
        target = next((c for c in outline["chapters"] if c["number"] == chapter_number), None)
        if not target:
            raise ValueError("chapter_number is outside outline range")

        memory_context = self.vector_store.search_memory(
            project_id=str(project.id),
            query=f"{project.title} chapter {chapter_number} continuity and style",
            limit=5,
        )
        knowledge_context = self.vector_store.search_knowledge_base(
            project_id=str(project.id),
            query=f"{project.title} chapter {chapter_number} facts references examples",
            limit=6,
        )

        return {
            "outline": outline,
            "chapter_number": chapter_number,
            "target": target,
            "memory_context": memory_context,
            "knowledge_context": knowledge_context,
        }

    def persist_chapter_result(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
        target: Dict[str, Any],
        chapter_data: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
        next_steps: List[str] | None = None,
    ) -> Dict[str, Any]:
        content = str(chapter_data.get("content", "")).strip()
        if not content:
            raise ValueError("Generated chapter content is empty")

        chapter, _ = Chapter.objects.update_or_create(
            project=project,
            number=chapter_number,
            defaults={
                "title": str(chapter_data.get("title") or target.get("title", "")).strip() or f"Chapter {chapter_number}",
                "content": content,
                "summary": str(chapter_data.get("summary", "")).strip(),
                "status": ChapterStatus.GENERATED,
            },
        )

        vector_indexed = self.vector_store.upsert_chapter_memory(
            project_id=str(project.id),
            chapter_number=chapter.number,
            title=chapter.title,
            content=chapter.content,
            summary=chapter.summary,
        )
        if vector_indexed and not chapter.vector_indexed:
            chapter.vector_indexed = True
            chapter.save(update_fields=["vector_indexed", "updated_at"])

        project.status = ProjectStatus.WRITING
        project.updated_at = timezone.now()
        project.save(update_fields=["status", "updated_at"])

        return {
            "status": "success",
            "outline": outline,
            "chapter": {
                "number": chapter.number,
                "title": chapter.title,
                "content": chapter.content,
                "summary": chapter.summary,
            },
            "metadata": metadata if isinstance(metadata, dict) else {},
            "next_steps": next_steps if isinstance(next_steps, list) and next_steps else ["Review the chapter and proceed to the next one."],
        }

    def _run_export(self, project: BookProject, inputs: Dict[str, Any]) -> Dict[str, Any]:
        outline = self._normalize_outline(project.outline_json or {})
        if not outline.get("chapters"):
            raise ValueError("Project does not have an outline yet")

        export_format = str(inputs.get("export_format", "pdf")).strip().lower()
        if export_format not in {"pdf", "docx", "both"}:
            raise ValueError("export_format must be one of: pdf | docx | both")

        chapters = list(project.chapters.all().order_by("number"))
        if not chapters:
            raise ValueError("No chapters found. Generate at least one chapter before export.")

        warnings: List[str] = []
        output: Dict[str, Any] = {
            "status": "success",
            "warnings": warnings,
            "used_fallback": False,
            "fallback_stages": [],
        }

        chapter_payload = [
            {"number": c.number, "title": c.title, "content": c.content, "summary": c.summary}
            for c in chapters
        ]

        if export_format in {"pdf", "both"}:
            pdf_bytes = self._render_pdf(project, outline, chapter_payload)
            output["pdf_base64"] = base64.b64encode(pdf_bytes).decode("utf-8")
            output["pdf_filename"] = f"{self._safe_file(project.title)}.pdf"

        if export_format in {"docx", "both"}:
            docx_bytes = self._render_docx(project, outline, chapter_payload)
            output["docx_base64"] = base64.b64encode(docx_bytes).decode("utf-8")
            output["docx_filename"] = f"{self._safe_file(project.title)}.docx"

        project.status = ProjectStatus.EXPORTED
        project.updated_at = timezone.now()
        project.save(update_fields=["status", "updated_at"])

        output["outline"] = outline
        output["next_steps"] = [
            "Download exported file(s).",
            "Review formatting in your editor.",
            "Publish or continue editing.",
        ]
        return output

    def _runtime_fallback_info(self, payload: Dict[str, Any] | Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"used_fallback": False, "fallback_stages": []}
        used_fallback = bool(payload.get("used_fallback"))
        stage = str(payload.get("fallback_stage", "")).strip()
        stages = [stage] if used_fallback and stage else []
        return {"used_fallback": used_fallback, "fallback_stages": stages}

    def _merge_dicts(self, left: Dict[str, Any] | Any, right: Dict[str, Any] | Any) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if isinstance(left, dict):
            out.update(left)
        if isinstance(right, dict):
            out.update(right)
        return out

    def _sync_chapters_from_outline(self, project: BookProject, outline: Dict[str, Any]) -> None:
        for chapter in outline.get("chapters", []):
            Chapter.objects.get_or_create(
                project=project,
                number=int(chapter["number"]),
                defaults={
                    "title": str(chapter["title"]).strip(),
                    "content": "",
                    "summary": "",
                    "status": ChapterStatus.PENDING,
                },
            )

    def _normalize_outline(self, outline: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(outline, dict):
            raise ValueError("outline must be an object")

        chapters = outline.get("chapters", [])
        if not isinstance(chapters, list) or not chapters:
            raise ValueError("outline.chapters must be a non-empty array")

        normalized = []
        expected = 1
        for chapter in chapters:
            if not isinstance(chapter, dict):
                raise ValueError("outline chapter must be an object")
            number = self._to_int(chapter.get("number"), "outline.chapter.number")
            if number != expected:
                raise ValueError("outline chapter numbers must be sequential starting at 1")
            title = str(chapter.get("title", "")).strip()
            if not title:
                raise ValueError(f"outline chapter {expected} missing title")
            bullet_points = chapter.get("bullet_points", [])
            if not isinstance(bullet_points, list):
                raise ValueError(f"outline chapter {expected} bullet_points must be an array")
            normalized.append(
                {
                    "number": number,
                    "title": title,
                    "bullet_points": [str(p).strip() for p in bullet_points if str(p).strip()],
                }
            )
            expected += 1

        synopsis = str(outline.get("synopsis", "")).strip()
        return {"synopsis": synopsis, "chapters": normalized}

    def _to_int(self, value: Any, field: str) -> int:
        if value is None or str(value).strip() == "":
            raise ValueError(f"{field} is required")
        try:
            return int(float(str(value).strip()))
        except Exception as exc:
            raise ValueError(f"{field} must be a valid integer") from exc

    def _render_pdf(self, project: BookProject, outline: Dict[str, Any], chapters: List[Dict[str, Any]]) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            topMargin=1 * inch,
            bottomMargin=1 * inch,
            leftMargin=1 * inch,
            rightMargin=1 * inch,
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("BookH1", parent=styles["Heading1"], spaceAfter=12)
        h2 = ParagraphStyle("BookH2", parent=styles["Heading2"], spaceAfter=10)
        body = ParagraphStyle("BookBody", parent=styles["BodyText"], leading=14, spaceAfter=8)

        story: List[Any] = []
        story.append(Spacer(1, 2 * inch))
        story.append(Paragraph(self._escape(project.title), styles["Title"]))
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(self._escape(f"{project.genre}  {project.language}  {project.tone}"), styles["Italic"]))
        story.append(PageBreak())

        story.append(Paragraph("Table of Contents", h1))
        for ch in outline.get("chapters", []):
            story.append(Paragraph(self._escape(f"Chapter {ch['number']}: {ch['title']}"), body))
        story.append(PageBreak())

        for ch in chapters:
            story.append(Paragraph(self._escape(f"Chapter {ch['number']}"), h2))
            story.append(Paragraph(self._escape(ch["title"]), h1))
            story.append(Spacer(1, 0.1 * inch))
            for block in self._split_blocks(ch["content"]):
                if block.startswith("# "):
                    story.append(Paragraph(self._escape(block[2:].strip()), h1))
                elif block.startswith("## "):
                    story.append(Paragraph(self._escape(block[3:].strip()), h2))
                else:
                    story.append(Paragraph(self._escape(block), body))
            story.append(PageBreak())

        doc.build(story)
        buf.seek(0)
        return buf.read()

    def _render_docx(self, project: BookProject, outline: Dict[str, Any], chapters: List[Dict[str, Any]]) -> bytes:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        document = Document()
        title_paragraph = document.add_paragraph()
        title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title_paragraph.add_run(project.title)
        run.bold = True
        run.font.size = Pt(26)

        sub = document.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub_run = sub.add_run(f"{project.genre}  {project.language}  {project.tone}")
        sub_run.italic = True
        document.add_page_break()

        document.add_heading("Table of Contents", level=1)
        for ch in outline.get("chapters", []):
            document.add_paragraph(f"Chapter {ch['number']}: {ch['title']}")
        document.add_page_break()

        for ch in chapters:
            document.add_heading(f"Chapter {ch['number']}: {ch['title']}", level=1)
            for block in self._split_blocks(ch["content"]):
                if block.startswith("# "):
                    document.add_heading(block[2:].strip(), level=1)
                elif block.startswith("## "):
                    document.add_heading(block[3:].strip(), level=2)
                else:
                    document.add_paragraph(block)
            document.add_page_break()

        out = io.BytesIO()
        document.save(out)
        out.seek(0)
        return out.read()

    def _split_blocks(self, text: str) -> List[str]:
        if not text:
            return []
        norm = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n\s*\n", norm)
        return [b.strip() for b in blocks if b.strip()]

    def _escape(self, value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _safe_file(self, title: str) -> str:
        sanitized = re.sub(r"[<>:\"/\\|?*]", "_", title).strip().strip(".")
        sanitized = sanitized.replace(" ", "_")
        return sanitized[:100] or "book"

    def _merge_project_metadata(self, project: BookProject, llm_metadata: Dict[str, Any] | Any) -> Dict[str, Any]:
        existing = project.metadata_json if isinstance(project.metadata_json, dict) else {}
        user_concept = self._build_user_concept_snapshot(project, existing)
        llm_runtime = llm_metadata if isinstance(llm_metadata, dict) else {}
        merged = dict(existing)
        merged["user_concept"] = user_concept
        merged["llm_runtime"] = llm_runtime
        if isinstance(user_concept.get("profile"), dict):
            merged["profile"] = user_concept["profile"]
        if "subtitle" in user_concept:
            merged["subtitle"] = user_concept["subtitle"]
        if "instruction_brief" in user_concept:
            merged["instruction_brief"] = user_concept["instruction_brief"]
        return merged

    def _build_user_concept_snapshot(self, project: BookProject, existing_meta: Dict[str, Any]) -> Dict[str, Any]:
        existing_user = existing_meta.get("user_concept", {})
        user_concept = dict(existing_user) if isinstance(existing_user, dict) else {}
        user_concept.setdefault("title", project.title)
        user_concept.setdefault("genre", project.genre)
        user_concept.setdefault("target_audience", project.target_audience)
        user_concept.setdefault("language", project.language)
        user_concept.setdefault("tone", project.tone)
        user_concept.setdefault("target_word_count", project.target_word_count)

        if not isinstance(user_concept.get("profile"), dict):
            legacy_profile = existing_meta.get("profile", {})
            user_concept["profile"] = legacy_profile if isinstance(legacy_profile, dict) else {}
        if "subtitle" not in user_concept and isinstance(existing_meta.get("subtitle"), str):
            user_concept["subtitle"] = existing_meta.get("subtitle", "")
        if "instruction_brief" not in user_concept and isinstance(existing_meta.get("instruction_brief"), str):
            user_concept["instruction_brief"] = existing_meta.get("instruction_brief", "")
        return user_concept
