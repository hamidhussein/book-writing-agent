from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from django.conf import settings

from ..models import BookProject

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


# ---------------------------------------------------------------------------
# Shared prompt fragments — single source of truth for schema definitions.
# Keeping these as module-level constants makes them easy to version, test,
# and reuse across methods without duplication.
# ---------------------------------------------------------------------------

_OUTLINE_SCHEMA = """{
  "outline": {
    "synopsis": "<compelling 2-3 paragraph synopsis that sells the book>",
    "chapters": [
      {
        "number": <int, sequential from 1>,
        "title": "<evocative, specific title — not 'Chapter 1'>",
        "bullet_points": [
          "<3-6 items: each a concrete, actionable beat — not vague summaries>"
        ]
      }
    ]
  },
  "metadata": {
    "estimated_word_count": <int>,
    "chapter_count": <int>,
    "pacing": "<slow-burn | moderate | fast-paced>",
    "themes": ["<thematic keyword>"]
  },
  "next_steps": ["<3-5 specific, prioritised editorial actions>"]
}"""

_CHAPTER_SCHEMA = """{
  "chapter": {
    "number": <int>,
    "title": "<chapter title>",
    "content": "<full chapter prose — use # for title, ## for sections, clear paragraph breaks>",
    "summary": "<1-2 sentences capturing the chapter's core narrative or argumentative contribution>"
  },
  "metadata": {
    "key_themes": ["<theme>"],
    "seo_keywords": ["<keyword>"]
  },
  "next_steps": ["<3-5 concrete actions for the next stage>"]
}"""

_CHAPTER_PLAN_SCHEMA = """{
  "plan": {
    "chapter_number": <int>,
    "chapter_title": "<resolved chapter title>",
    "objective": "<single sentence chapter objective>",
    "sections": [
      {
        "heading": "<section heading>",
        "purpose": "<purpose of this section>",
        "evidence_or_example": "<what evidence/example should appear>"
      }
    ],
    "continuity_notes": ["<what must stay consistent with previous chapters>"],
    "concept_alignment": "<how this chapter serves original user concept>",
    "rich_elements_plan": [
      {
        "type": "<table | code_block | quote | callout | flowchart | figure | list>",
        "section": "<which planned section should include it>",
        "purpose": "<why it improves clarity/teaching>",
        "required": <boolean>
      }
    ],
    "visual_specs": [
      {
        "type": "<figure | flowchart>",
        "placement_section": "<section heading where it appears>",
        "caption": "<short caption for export>",
        "prompt": "<visual generation prompt for DALL·E / image model or diagram renderer>"
      }
    ]
  }
}"""

_CHAPTER_REVIEW_SCHEMA = """{
  "review": {
    "score": <int, 0-100>,
    "should_revise": <boolean>,
    "issues": ["<specific issue>"],
    "critique": "<compact revision guidance if should_revise=true>"
  }
}"""

_PROFILE_ASSISTANT_SCHEMA = """{
  "assistant_reply": "<one concise response and one focused next question>",
  "field_updates": {
    "<field_name>": "<normalized value inferred from user conversation>"
  },
  "next_field": "<hidden routing signal: the most relevant missing field to ask next>",
  "is_finalized": <boolean>,
  "missing_required": ["<required field still missing>"],
  "suggestions": ["<2-3 short reply options the user might type next; generic and useful across topics; not questions>"]
}"""

_JSON_RULE = (
    "OUTPUT RULE: Return a single valid JSON object — no markdown fences, "
    "no prose before or after, no trailing commas, no comments."
)

_PROFILE_FIELD_ORDER = [
    # Natural conversational flow (not UI form order)
    "title",
    "audience",
    "audienceKnowledgeLevel",
    "culturalContext",
    "bookPurpose",
    "genre",
    "language",
    "tone",
    "writingStyle",
    "pointOfView",
    "ghostwritingMode",
    "sentenceRhythm",
    "vocabularyLevel",
    "chapterLength",
    "length",
    "pageFeel",
    "publishingIntent",
    # Optional / advanced details (prefer batching late in the conversation)
    "customInstructions",
    "contentBoundaries",
    "booksToEmulate",
    "styleReferencePassage",
    "frontMatter",
    "backMatter",
    "richElements",
    "subtitle",
    "primaryCta",
]

_REQUIRED_PROFILE_FIELDS = [
    "title",
    "genre",
    "language",
    "length",
    "publishingIntent",
    "audience",
    "audienceKnowledgeLevel",
    "bookPurpose",
    "tone",
    "writingStyle",
    "pointOfView",
    "sentenceRhythm",
    "vocabularyLevel",
    "chapterLength",
]

_OPTIONAL_PROFILE_FIELDS = [
    field for field in _PROFILE_FIELD_ORDER if field not in _REQUIRED_PROFILE_FIELDS
]

_LATE_OPTIONAL_BATCH_FIELDS = [
    "customInstructions",
    "contentBoundaries",
    "booksToEmulate",
    "styleReferencePassage",
    "frontMatter",
    "backMatter",
    "richElements",
    "subtitle",
    "primaryCta",
]

_PROFILE_CONVERSATION_GUIDANCE = (
    "Prefer a natural consultant-style flow rather than UI/form order. "
    "Suggested priority: title/topic -> audience + knowledge level -> purpose -> genre/language -> "
    "tone/style/POV -> rhythm/vocabulary -> chapter feel (short vs deep) + total word count together -> page feel -> publishing intent. "
    "Treat chapter length and total word count as linked decisions because together they imply an approximate chapter count. "
    "Treat many current form values as defaults unless the conversation clearly confirms them. "
    "Do not re-ask details the user already clearly provided in conversation or current form state. "
    "Once required details are covered, proactively offer finalize (or a short optional-details batch) instead of waiting for the user to guess the command. "
    "Optional items can be skipped and offered near the end as a short batch "
    "(subtitle/CTA, style references, boundaries, front/back matter, rich elements)."
)

_TITLE_PLACEHOLDER_VALUES = {
    "untitled",
    "untitled project",
    "my book",
    "book",
    "new book",
    "tbd",
    "na",
    "n a",
    "none",
    "hi",
    "hello",
    "hey",
}

_PROFILE_FORM_DEFAULTS: Dict[str, Any] = {
    "title": "",
    "subtitle": "",
    "genre": "Non-fiction",
    "audience": "General readers",
    "audienceKnowledgeLevel": "Complete Beginner",
    "culturalContext": "",
    "bookPurpose": "Teach a Skill",
    "primaryCta": "",
    "language": "English",
    "tone": "Informative",
    "writingStyle": "Instructional",
    "pointOfView": "Second Person",
    "sentenceRhythm": "Mixed",
    "vocabularyLevel": "Intermediate",
    "ghostwritingMode": False,
    "booksToEmulate": "",
    "styleReferencePassage": "",
    "customInstructions": "",
    "pageFeel": "Standard",
    "publishingIntent": "Self-publish",
    "chapterLength": "Medium ~3000w",
    "frontMatter": ["Introduction"],
    "backMatter": [],
    "richElements": ["Lists"],
    "contentBoundaries": "",
    "length": 3000,
}

_OPTIONAL_BATCH_MIN_CONVERSATION_TURNS = 6


class LLMService:
    """
    LLM adapter with deterministic fallbacks.

    If OpenAI is unavailable or the API call fails after all retries,
    every public method returns a structurally identical fallback dict so
    callers never need to branch on None.
    """

    def __init__(self) -> None:
        self.model = settings.OPENAI_MODEL
        self.fast_model = getattr(settings, "OPENAI_FAST_MODEL", self.model)
        self.image_model = getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.max_retries = settings.BOOK_AGENT_JSON_RETRIES
        self._client: Optional[OpenAI] = None
        if getattr(settings, "OPENAI_API_KEY", "") and OpenAI is not None:
            try:
                self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception:
                logger.warning("Failed to initialise OpenAI client", exc_info=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_outline(
        self,
        project: BookProject,
        knowledge_context: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Generate a full book outline from project metadata."""
        knowledge_text = "\n\n".join(knowledge_context or [])[:9000]
        recommended_chapters = max(6, min(14, project.target_word_count // 3000))

        system_prompt = _build_system_prompt(
            role=(
                "You are a senior book architect with a track record of structuring "
                "bestselling titles across fiction, narrative non-fiction, and reference genres."
            ),
            task=(
                "Produce a detailed, publication-ready book outline. "
                "Think step by step: (1) establish the book's core promise and audience payoff, "
                "(2) design a chapter arc that delivers on that promise with satisfying progression, "
                "(3) write bullet points that are specific enough for a ghostwriter to act on without further instruction."
            ),
            schema=_OUTLINE_SCHEMA,
        )

        user_prompt = _join(
            _book_header(project),
            _profile_block(project),
            f"Recommended chapter count: {recommended_chapters} "
            f"(scale to fit {project.target_word_count:,} words — adjust if the narrative demands it).",
            _section("Structural Guidelines", _OUTLINE_GUIDELINES),
            _knowledge_block(knowledge_text),
        )

        payload = self._call_json(system_prompt, user_prompt)
        if payload:
            return self._with_runtime_meta(payload, used_fallback=False)
        return self._with_runtime_meta(self._fallback_outline(project), used_fallback=True, fallback_stage="toc")

    def refine_outline(
        self,
        project: BookProject,
        existing_outline: Dict[str, Any],
        feedback: str,
        knowledge_context: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Apply editorial feedback to an existing outline."""
        knowledge_text = "\n\n".join(knowledge_context or [])[:9000]

        system_prompt = _build_system_prompt(
            role=(
                "You are a developmental editor who specialises in structural revision. "
                "You apply feedback with surgical precision — changing only what needs to change "
                "and justifying every structural decision against the book's core promise."
            ),
            task=(
                "Revise the supplied outline in light of the editorial feedback. "
                "Think step by step: (1) identify exactly what the feedback requires, "
                "(2) locate the affected chapters, (3) revise those sections while "
                "preserving the integrity of unaffected ones, "
                "(4) preserve non-negotiable brief constraints (audience, purpose, tone, boundaries) unless the feedback explicitly changes them, "
                "(5) renumber all chapters sequentially from 1."
            ),
            schema=_OUTLINE_SCHEMA,
        )

        user_prompt = _join(
            _book_header(project),
            _profile_block(project),
            _refine_non_negotiables_block(project),
            _section("Editorial Feedback", feedback),
            _section(
                "Existing Outline",
                json.dumps(existing_outline, ensure_ascii=False, indent=2),
            ),
            _section("Revision Guidelines", _REFINE_GUIDELINES),
            _knowledge_block(knowledge_text),
        )

        payload = self._call_json(system_prompt, user_prompt)
        if payload:
            return self._with_runtime_meta(payload, used_fallback=False)

        fallback = self._fallback_outline(project)
        fallback["outline"]["synopsis"] += " (Refined per feedback.)"
        return self._with_runtime_meta(fallback, used_fallback=True, fallback_stage="refine_toc")

    def generate_chapter(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
        memory_context: List[str] | None = None,
        knowledge_context: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Write a full chapter, grounded in the outline and prior context."""
        chapter_title = self._get_chapter_title(outline, chapter_number)
        chapter_points = self._get_chapter_points(outline, chapter_number)
        memory_text = "\n".join(memory_context or [])
        knowledge_text = "\n\n".join(knowledge_context or [])
        rich_elements_block = _rich_elements_preferences_block(project)

        system_prompt = _build_system_prompt(
            role=(
                f"You are a professional author writing a {project.genre} book "
                f"in a {project.tone} tone for {project.target_audience}. "
                "You write prose that is vivid, purposeful, and consistent with the "
                "established voice and chapter outline."
            ),
            task=(
                f"Write Chapter {chapter_number}: '{chapter_title}' in full. "
                "Think step by step: (1) re-read the chapter's bullet points and identify "
                "the single most important thing this chapter must achieve, "
                "(2) open with a hook that earns the reader's attention, "
                "(3) develop each bullet point into a full section, "
                "(4) close with a bridge that makes the reader want to continue."
            ),
            schema=_CHAPTER_SCHEMA,
        )

        bullet_block = (
            _section(
                f"Chapter {chapter_number} Bullet Points",
                "\n".join(f"- {p}" for p in chapter_points),
            )
            if chapter_points
            else ""
        )

        user_prompt = _join(
            f"Book: {project.title} | Language: {project.language}",
            _profile_block(project),
            _section("Full Outline (for continuity)", json.dumps(outline, ensure_ascii=False, indent=2)),
            bullet_block,
            rich_elements_block,
            _memory_block(memory_text),
            _knowledge_block(knowledge_text),
            _section("Writing Guidelines", _CHAPTER_GUIDELINES),
        )

        payload = self._call_json(system_prompt, user_prompt)
        if payload and isinstance(payload.get("chapter"), dict):
            chapter = payload["chapter"]
            chapter["number"] = chapter_number
            chapter.setdefault("title", chapter_title)
            if not chapter.get("summary"):
                chapter["summary"] = self._summarize(chapter.get("content", ""))
            payload = _augment_chapter_payload_rich_elements(
                payload=payload,
                project=project,
                chapter_plan=None,
            )
            return self._with_runtime_meta(payload, used_fallback=False)

        return self._with_runtime_meta(
            _augment_chapter_payload_rich_elements(
                payload=self._fallback_chapter(project, outline, chapter_number),
                project=project,
                chapter_plan=None,
            ),
            used_fallback=True,
            fallback_stage="chapter_draft",
        )

    def plan_chapter(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
        memory_context: List[str] | None = None,
        knowledge_context: List[str] | None = None,
    ) -> Dict[str, Any]:
        chapter_title = self._get_chapter_title(outline, chapter_number)
        chapter_points = self._get_chapter_points(outline, chapter_number)
        memory_text = "\n".join(memory_context or [])
        knowledge_text = "\n\n".join(knowledge_context or [])
        rich_elements_block = _rich_elements_preferences_block(project)

        system_prompt = _build_system_prompt(
            role=(
                "You are a chapter strategist. You design concise, execution-ready chapter plans "
                "that preserve the author's concept and maintain continuity."
            ),
            task=(
                f"Create a concrete writing plan for Chapter {chapter_number}: '{chapter_title}'. "
                "Use the outline, prior memory, and knowledge context. Keep it precise and actionable. "
                "If the brief requests rich elements (tables, code, quotes, callouts, figures, flowcharts), "
                "plan only the ones that genuinely improve this chapter. Do not force every selected element into every chapter. "
                "For figure/flowchart ideas, add visual_specs with caption + generation prompt."
            ),
            schema=_CHAPTER_PLAN_SCHEMA,
        )

        bullet_block = (
            _section(
                f"Chapter {chapter_number} Bullet Points",
                "\n".join(f"- {p}" for p in chapter_points),
            )
            if chapter_points
            else ""
        )

        user_prompt = _join(
            _book_header(project),
            _profile_block(project),
            _section("Full Outline", json.dumps(outline, ensure_ascii=False, indent=2)),
            bullet_block,
            rich_elements_block,
            _memory_block(memory_text),
            _knowledge_block(knowledge_text),
        )

        payload = self._call_json(system_prompt, user_prompt, model=self.fast_model, temperature=0.3)
        if payload and isinstance(payload.get("plan"), dict):
            payload["plan"] = _normalize_chapter_plan_rich_elements(payload.get("plan", {}))
            return self._with_runtime_meta(payload, used_fallback=False)

        requested_rich = _requested_rich_elements_from_project(project)
        return self._with_runtime_meta({
            "plan": {
                "chapter_number": chapter_number,
                "chapter_title": chapter_title,
                "objective": f"Deliver the key value of {chapter_title} clearly and progressively.",
                "sections": [{"heading": point[:80] or "Core Section", "purpose": "Expand this beat", "evidence_or_example": "Use a concrete example"} for point in (chapter_points or ["Core development"])],
                "continuity_notes": ["Maintain tone and continuity with previous chapters."],
                "concept_alignment": "Stay aligned to the original user concept and audience.",
                "rich_elements_plan": _fallback_rich_elements_plan(chapter_points, requested_rich),
                "visual_specs": _fallback_visual_specs_for_rich_elements(chapter_points, requested_rich),
            }
        }, used_fallback=True, fallback_stage="chapter_plan")

    def draft_or_revise_chapter(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
        chapter_plan: Dict[str, Any] | None,
        memory_context: List[str] | None = None,
        knowledge_context: List[str] | None = None,
        critique: str = "",
        previous_draft: str = "",
    ) -> Dict[str, Any]:
        chapter_title = self._get_chapter_title(outline, chapter_number)
        chapter_points = self._get_chapter_points(outline, chapter_number)
        memory_text = "\n".join(memory_context or [])
        knowledge_text = "\n\n".join(knowledge_context or [])
        normalized_plan = _normalize_chapter_plan_rich_elements(chapter_plan or {})
        plan_text = json.dumps(normalized_plan, ensure_ascii=False, indent=2)
        rich_elements_block = _rich_elements_preferences_block(project, chapter_plan=normalized_plan)

        system_prompt = _build_system_prompt(
            role=(
                f"You are a professional author writing a {project.genre} book in a {project.tone} tone for {project.target_audience}."
            ),
            task=(
                f"Write or revise Chapter {chapter_number}: '{chapter_title}' using the provided plan and critique. "
                "Keep structural integrity, concept fidelity, and narrative continuity."
            ),
            schema=_CHAPTER_SCHEMA,
        )

        bullet_block = (
            _section(
                f"Chapter {chapter_number} Bullet Points",
                "\n".join(f"- {p}" for p in chapter_points),
            )
            if chapter_points
            else ""
        )

        user_prompt = _join(
            f"Book: {project.title} | Language: {project.language}",
            _profile_block(project),
            _section("Full Outline (for continuity)", json.dumps(outline, ensure_ascii=False, indent=2)),
            bullet_block,
            _section("Chapter Plan", plan_text),
            rich_elements_block,
            _memory_block(memory_text),
            _knowledge_block(knowledge_text),
            _section("Revision Critique", critique),
            _section("Previous Draft (if revising)", previous_draft[:12000]),
            _section("Writing Guidelines", _CHAPTER_GUIDELINES),
        )

        payload = self._call_json(system_prompt, user_prompt)
        if payload and isinstance(payload.get("chapter"), dict):
            chapter = payload["chapter"]
            chapter["number"] = chapter_number
            chapter.setdefault("title", chapter_title)
            if not chapter.get("summary"):
                chapter["summary"] = self._summarize(chapter.get("content", ""))
            payload = _augment_chapter_payload_rich_elements(
                payload=payload,
                project=project,
                chapter_plan=normalized_plan,
            )
            return self._with_runtime_meta(payload, used_fallback=False)
        return self.generate_chapter(
            project,
            outline,
            chapter_number,
            memory_context=memory_context,
            knowledge_context=knowledge_context,
        )

    def review_chapter(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
        chapter_plan: Dict[str, Any] | None,
        chapter_content: str,
        memory_context: List[str] | None = None,
        knowledge_context: List[str] | None = None,
    ) -> Dict[str, Any]:
        chapter_title = self._get_chapter_title(outline, chapter_number)
        memory_text = "\n".join(memory_context or [])
        knowledge_text = "\n\n".join(knowledge_context or [])
        plan_text = json.dumps(chapter_plan or {}, ensure_ascii=False, indent=2)

        system_prompt = _build_system_prompt(
            role=(
                "You are a strict editorial QA reviewer. "
                "Evaluate chapter quality, concept alignment, and continuity."
            ),
            task=(
                f"Review Chapter {chapter_number}: '{chapter_title}'. "
                "Return a numeric quality score (0-100), concrete issues, and a concise critique."
            ),
            schema=_CHAPTER_REVIEW_SCHEMA,
        )

        user_prompt = _join(
            _book_header(project),
            _profile_block(project),
            _section("Full Outline", json.dumps(outline, ensure_ascii=False, indent=2)),
            _section("Chapter Plan", plan_text),
            _memory_block(memory_text),
            _knowledge_block(knowledge_text),
            _section("Chapter Draft", chapter_content[:18000]),
        )

        payload = self._call_json(system_prompt, user_prompt, model=self.fast_model, temperature=0.2)
        if payload and isinstance(payload.get("review"), dict):
            review = payload["review"]
            try:
                review["score"] = max(0, min(100, int(float(str(review.get("score", 0))))))
            except Exception:
                review["score"] = 0
            review["should_revise"] = bool(review.get("should_revise"))
            if not isinstance(review.get("issues"), list):
                review["issues"] = []
            review["critique"] = str(review.get("critique", "")).strip()
            return self._with_runtime_meta(payload, used_fallback=False)

        fallback_score = 82 if len(chapter_content.split()) >= 350 else 68
        should_revise = fallback_score < 80
        return self._with_runtime_meta({
            "review": {
                "score": fallback_score,
                "should_revise": should_revise,
                "issues": ["Chapter is too thin for publication quality."] if should_revise else [],
                "critique": "Increase depth, examples, and continuity links to prior chapters." if should_revise else "",
            }
        }, used_fallback=True, fallback_stage="chapter_review")

    def assist_profile(
        self,
        project: BookProject,
        current_profile: Dict[str, Any] | None,
        conversation: List[Dict[str, str]] | None,
        user_message: str,
    ) -> Dict[str, Any]:
        profile = current_profile if isinstance(current_profile, dict) else {}
        confirmed_profile, form_defaults = _split_profile_confirmed_and_defaults(profile)
        transcript_lines: List[str] = []
        for turn in (conversation or [])[-20:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "")).strip().lower()
            content = str(turn.get("content", "")).strip()
            if role in {"assistant", "user"} and content:
                transcript_lines.append(f"{role}: {content[:700]}")

        system_prompt = _build_system_prompt(
            role=(
                "You are a warm, conversational Book Brief Consultant. "
                "You help authors clarify their idea through natural conversation while quietly structuring a production-ready brief."
            ),
            task=(
                "Have a genuine conversation while building the book brief. "
                "Infer multiple fields from a single message when clearly implied, "
                "update only what you are confident about, and ask one natural follow-up question at a time. "
                "Only ask about Concept Studio form fields (or explain those fields when the user asks what they mean). "
                "Think step by step: (1) infer all confident details from the user's latest message, "
                "(2) update those fields, (3) choose the single most useful missing detail to ask next, "
                "(4) write a warm conversational reply that sounds human (not like a form), "
                "(5) provide 2-3 short likely user replies as suggestions. "
                "Do not use technical field names in the reply. "
                "Treat current form values as context (some may be defaults) and avoid re-asking what is already clear. "
                "Do not narrate default form values as if the user personally provided them. "
                "If the user gives an age range for children/teens, fold that into audience (and beginner level if appropriate). "
                "If the user asks something outside the book brief/form scope (general facts, coding help, etc.), politely redirect them back to the form. "
                "After the brief is finalized, treat repeated finalize messages as confirmation only; do not restart optional loops unless the user asks to edit a field. "
                "If required details are covered, you may offer a short optional-details batch before asking for finalize."
            ),
            schema=_PROFILE_ASSISTANT_SCHEMA,
        )

        user_prompt = _join(
            _book_header(project),
            _profile_block(project),
            _section("User-Confirmed Fields (current form values that differ from defaults)", json.dumps(confirmed_profile, ensure_ascii=False, indent=2)),
            _section(
                "Form Defaults (not confirmed by user — do not reference as user-provided; do not treat as touched)",
                json.dumps(form_defaults, ensure_ascii=False, indent=2),
            ),
            _section("Conversation Transcript", "\n".join(transcript_lines)),
            _section("Latest User Message", user_message),
            _section("Field Order", ", ".join(_PROFILE_FIELD_ORDER)),
            _section("Conversation Flow Guidance", _PROFILE_CONVERSATION_GUIDANCE),
            _section(
                "Validation Rules",
                (
                    f"Required fields: {', '.join(_REQUIRED_PROFILE_FIELDS)}.\n"
                    "Only include keys in field_updates when you are confident.\n"
                    "Infer multiple fields from one user message when strongly implied (e.g. audience + level + purpose).\n"
                    "Treat current form values as context; some may be defaults and not final user decisions.\n"
                    "Defaults do not count as user-confirmed and should not be narrated back as established facts.\n"
                    "Do not invent facts or names. Keep assistant_reply under 70 words.\n"
                    "Do not mention internal field names unless the user asks.\n"
                    "Suggestions must be short reply options the user might actually type next (not questions).\n"
                    "Each suggestion should be under 10 words.\n"
                    "Suggestions should directly answer your latest question, not propose workflow jumps.\n"
                    "Suggestions must be generic enough to stay useful regardless of topic (e.g. brainstorming, confirmation, preference statements).\n"
                    "Never guess the user's specific topic/content in suggestions.\n"
                    "If the user asks what a form field means (e.g. front matter), explain it clearly before continuing.\n"
                    "If the user sends only a form field label (e.g. 'Primary CTA After Reading'), treat it as a request for help on that field.\n"
                    "Do not answer general coding/helpdesk/world-knowledge questions in this assistant; redirect to book brief fields.\n"
                    "When required fields are complete and the user says keep defaults / happy with this / you decide, finalize.\n"
                    "If all required fields are present but the latest user message does not explicitly confirm finalize, "
                    "set is_finalized to false and ask for finalize confirmation."
                ),
            ),
        )

        payload = self._call_json(system_prompt, user_prompt)
        if payload:
            return self._normalize_assistant_payload(payload, profile, user_message, conversation or [])
        return self._fallback_profile_assistant(profile, user_message)

    def embed(self, text: str) -> Optional[List[float]]:
        if not self._client:
            return None
        try:
            response = self._client.embeddings.create(
                model=settings.OPENAI_EMBED_MODEL,
                input=text[:12000],
            )
            vec = response.data[0].embedding
            if isinstance(vec, list) and vec:
                return vec
        except Exception:
            logger.warning("Embedding call failed", exc_info=True)
        return None

    # ------------------------------------------------------------------
    # Private — API layer
    # ------------------------------------------------------------------

    def _call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> Optional[Dict[str, Any]]:
        if not self._client:
            return None

        model_name = (model or self.model).strip() or self.model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=model_name,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=messages,
                )
                content = response.choices[0].message.content or "{}"
                payload = json.loads(content)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                logger.warning("LLM JSON call failed (attempt %d)", attempt + 1, exc_info=True)

            # On failure: append a targeted repair instruction rather than
            # repeating the full prompt, which wastes context and tokens.
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return only the corrected JSON object. "
                    "No markdown, no explanation, no trailing commas."
                ),
            })
        return None

    def _with_runtime_meta(
        self,
        payload: Dict[str, Any] | Any,
        *,
        used_fallback: bool,
        fallback_stage: str = "",
    ) -> Dict[str, Any]:
        out = dict(payload) if isinstance(payload, dict) else {}
        out["used_fallback"] = bool(used_fallback)
        out["fallback_stage"] = str(fallback_stage).strip() if used_fallback else ""
        return out

    def _normalize_assistant_payload(
        self,
        payload: Dict[str, Any],
        current_profile: Dict[str, Any],
        user_message: str,
        conversation: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        raw_updates = payload.get("field_updates", {})
        if isinstance(raw_updates, dict):
            for key, value in raw_updates.items():
                field = str(key).strip()
                if field in _PROFILE_FIELD_ORDER:
                    updates[field] = _normalize_profile_value(field, value)

        updates = _sanitize_assistant_updates(
            updates=updates,
            current_profile=current_profile,
            user_message=user_message,
            conversation=conversation or [],
        )
        updates = _augment_assistant_updates_from_context(
            updates=updates,
            current_profile=current_profile,
            user_message=user_message,
        )
        updates = _repair_semantic_assistant_updates(updates)

        merged = dict(current_profile)
        merged.update(updates)
        optional_missing = _missing_optional_profile_fields(merged)
        conversation_turn_count = 0
        for turn in (conversation or []):
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "")).strip().lower()
            content = str(turn.get("content", "")).strip()
            if role in {"assistant", "user"} and content:
                conversation_turn_count += 1
        allow_optional_batch = conversation_turn_count >= _OPTIONAL_BATCH_MIN_CONVERSATION_TURNS

        raw_missing = payload.get("missing_required", [])
        computed_missing = _missing_required_profile(merged)
        computed_missing_set = set(computed_missing)
        model_missing: List[str] = []
        if isinstance(raw_missing, list):
            model_missing = [
                str(item).strip()
                for item in raw_missing
                if str(item).strip() in _REQUIRED_PROFILE_FIELDS and str(item).strip() in computed_missing_set
            ]
        missing_required = _ordered_unique_fields(model_missing + computed_missing)

        next_field_raw = str(payload.get("next_field", "")).strip()
        next_field = next_field_raw if next_field_raw in _PROFILE_FIELD_ORDER else ""
        reply = str(payload.get("assistant_reply", "")).strip()
        finalize_intent = _is_finalize_intent(user_message)
        defaults_acceptance_intent = _is_defaults_acceptance_intent(user_message)
        wants_more_optional_details = _wants_more_optional_details(user_message)
        explanation_field = _field_explanation_request_field(user_message)
        field_label_reference = _field_label_reference_field(user_message)
        pause_intent = _is_pause_or_rest_intent(user_message)
        off_topic_intent = _is_off_topic_or_out_of_scope(user_message)
        assistant_recently_finalized = _assistant_recently_finalized(conversation or [])
        
        # New logic: Don't hijack the reply or auto-finalize unless absolutely certain.
        # If the LLM explicitly said is_finalized, we respect it, but we still verify missing fields.
        llm_wants_finalize = bool(payload.get("is_finalized"))

        if explanation_field or field_label_reference:
            field_for_help = explanation_field or field_label_reference
            is_finalized = False
            if field_for_help in _PROFILE_FIELD_ORDER:
                next_field = field_for_help
            reply = _field_explanation_reply(field_for_help)
            raw_suggestions = payload.get("suggestions", [])
            suggestions = _normalize_assistant_suggestions(
                raw_suggestions=raw_suggestions,
                next_field=next_field,
                profile=merged,
                is_finalized=is_finalized,
            )
            suggestions = _filter_assistant_suggestions_for_context(
                suggestions=suggestions,
                next_field=next_field,
                missing_required=missing_required,
                profile=merged,
            )
            return {
                "assistant_reply": reply,
                "field_updates": updates,
                "next_field": next_field,
                "is_finalized": is_finalized,
                "missing_required": missing_required,
                "suggestions": suggestions,
            }

        if pause_intent:
            return {
                "assistant_reply": "Understood. Please rest. Your brief progress is saved, and you can come back later to continue or finalize.",
                "field_updates": updates,
                "next_field": "",
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": [],
            }

        if off_topic_intent:
            return {
                "assistant_reply": (
                    "I’m the Book Studio assistant, so I can only help with your book brief here. "
                    "If you want, tell me which form field you want to update (title, audience, tone, chapter length, etc.)."
                ),
                "field_updates": updates,
                "next_field": "",
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": [],
            }

        if missing_required:
            is_finalized = False
            if not next_field:
                next_field = _next_missing_required_field(merged) or missing_required[0]
            elif next_field not in _REQUIRED_PROFILE_FIELDS:
                # Keep required-field sequencing intact until the brief is complete.
                next_field = _next_missing_required_field(merged) or missing_required[0]
            elif next_field in updates and next_field not in missing_required:
                # Move forward when the model captured a field this turn but forgot to advance.
                next_field = _next_missing_required_field(merged) or next_field
            
            if finalize_intent:
                # User tried to finalize but we are missing stuff
                reply = f"Before finalizing, I still need one detail: {next_field}. {_question_for_field(next_field)}"
            elif _reply_claims_completion(reply):
                # Correct false completion claims when required fields are still missing.
                reply = _question_for_field(next_field)
            elif not reply:
                # No reply from LLM, use fallback question
                reply = _question_for_field(next_field)
            # Else: Keep LLM's own chatty reply.
        else:
            # Profile is "complete" (fully filled, potentially by defaults)
            if assistant_recently_finalized and (finalize_intent or defaults_acceptance_intent):
                is_finalized = True
                next_field = ""
                reply = "Your brief is already finalized. If you want changes, name a field to update and I’ll help."
            elif finalize_intent or llm_wants_finalize or defaults_acceptance_intent:
                is_finalized = True
                next_field = ""
                if not reply:
                    reply = "Great. I have applied your brief to the form. Please review and generate when ready."
            else:
                is_finalized = False
                if next_field and next_field not in optional_missing:
                    next_field = ""

                if optional_missing and allow_optional_batch:
                    if wants_more_optional_details:
                        next_field = _next_missing_optional_field(merged) or next_field or ""
                        if next_field:
                            reply = _question_for_field(next_field)
                        elif not reply or _reply_claims_completion(reply):
                            reply = _optional_batch_reply(optional_missing)
                    elif _reply_stuck_in_optional_loop(reply):
                        next_field = _next_missing_optional_field(merged) or next_field or ""
                        if next_field:
                            reply = _question_for_field(next_field)
                        else:
                            reply = _optional_batch_reply(optional_missing)
                    if not next_field:
                        next_field = _next_missing_optional_field(merged) or ""
                    if not reply or _reply_claims_completion(reply):
                        reply = _optional_batch_reply(optional_missing)
                else:
                    next_field = ""
                    # Only use the "I have captured all..." message if the LLM provided NO reply
                    # or if the LLM is stuck in a loop of completion claims.
                    if (
                        not reply
                        or _reply_claims_completion(reply)
                        or (optional_missing and not allow_optional_batch)
                    ):
                        reply = "I have captured all required details. If you agree, reply 'finalize' and I will apply them to the form."

        if _reply_uses_default_word_count_as_user_fact(reply, current_profile):
            if missing_required:
                reply = _question_for_field(next_field)
            elif not is_finalized:
                reply = "We can choose the total word count explicitly. What target word count do you want for the full book?"

        raw_suggestions = payload.get("suggestions", [])
        suggestions = _normalize_assistant_suggestions(
            raw_suggestions=raw_suggestions,
            next_field=next_field,
            profile=merged,
            is_finalized=is_finalized,
        )
        suggestions = _filter_assistant_suggestions_for_context(
            suggestions=suggestions,
            next_field=next_field,
            missing_required=missing_required,
            profile=merged,
        )

        return {
            "assistant_reply": reply,
            "field_updates": updates,
            "next_field": next_field,
            "is_finalized": is_finalized,
            "missing_required": missing_required,
            "suggestions": suggestions,
        }

    def _fallback_profile_assistant(self, current_profile: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        merged = dict(current_profile)
        missing_required = _missing_required_profile(merged)
        finalize_requested = _is_finalize_intent(user_message)
        defaults_acceptance = _is_defaults_acceptance_intent(user_message)
        explanation_field = _field_explanation_request_field(user_message)
        field_label_reference = _field_label_reference_field(user_message)
        pause_intent = _is_pause_or_rest_intent(user_message)
        off_topic_intent = _is_off_topic_or_out_of_scope(user_message)

        if explanation_field or field_label_reference:
            help_field = explanation_field or field_label_reference
            return {
                "assistant_reply": _field_explanation_reply(help_field),
                "field_updates": {},
                "next_field": help_field if help_field in _PROFILE_FIELD_ORDER else "",
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": _assistant_suggestion_fallback(help_field, merged),
            }

        if pause_intent:
            return {
                "assistant_reply": "Understood. Please rest. Your brief progress is saved, and you can continue later.",
                "field_updates": {},
                "next_field": "",
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": [],
            }

        if off_topic_intent:
            return {
                "assistant_reply": (
                    "I’m the Book Studio assistant, so I can help with your Concept Studio form fields only. "
                    "Tell me which field you want to update, and I’ll help."
                ),
                "field_updates": {},
                "next_field": "",
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": [],
            }

        if (finalize_requested or defaults_acceptance) and not missing_required:
            return {
                "assistant_reply": "Great. I have applied the brief to the form. Please review and generate when ready.",
                "field_updates": {},
                "next_field": "",
                "is_finalized": True,
                "missing_required": [],
                "suggestions": [],
            }
        if (finalize_requested or defaults_acceptance) and missing_required:
            next_field = _next_missing_required_field(merged) or missing_required[0]
            return {
                "assistant_reply": f"Before finalizing, I still need one detail: {next_field}. {_question_for_field(next_field)}",
                "field_updates": {},
                "next_field": next_field,
                "is_finalized": False,
                "missing_required": missing_required,
                "suggestions": _assistant_suggestion_fallback(next_field, merged),
            }

        if not missing_required:
            optional_missing = _missing_optional_profile_fields(merged)
            next_optional = _next_missing_optional_field(merged) or ""
            if optional_missing:
                if _wants_more_optional_details(user_message):
                    next_optional = _next_missing_optional_field(merged) or ""
                    return {
                        "assistant_reply": _question_for_field(next_optional) if next_optional else _optional_batch_reply(optional_missing),
                        "field_updates": {},
                        "next_field": next_optional,
                        "is_finalized": False,
                        "missing_required": [],
                        "suggestions": _assistant_suggestion_fallback(next_optional, merged),
                    }
                return {
                    "assistant_reply": _optional_batch_reply(optional_missing),
                    "field_updates": {},
                    "next_field": next_optional,
                    "is_finalized": False,
                    "missing_required": [],
                    "suggestions": _assistant_suggestion_fallback(next_optional, merged),
                }
            return {
                "assistant_reply": "I have all required details. If you agree, reply 'finalize' to apply them to the form.",
                "field_updates": {},
                "next_field": "",
                "is_finalized": False,
                "missing_required": [],
                "suggestions": ["yes finalize", "review first", "one more change"],
            }

        next_field = _next_missing_required_field(merged) or _next_missing_field(merged) or ""
        return {
            "assistant_reply": _question_for_field(next_field),
            "field_updates": {},
            "next_field": next_field,
            "is_finalized": False,
            "missing_required": missing_required,
            "suggestions": _assistant_suggestion_fallback(next_field, merged),
        }

    # ------------------------------------------------------------------
    # Private — fallbacks
    # ------------------------------------------------------------------

    def _fallback_outline(self, project: BookProject) -> Dict[str, Any]:
        chapter_count = max(6, min(14, max(1, project.target_word_count // 2500)))
        chapters = [
            {
                "number": i,
                "title": f"Chapter {i}: Core Idea {i}",
                "bullet_points": [
                    f"Purpose of chapter {i}",
                    f"Key argument or scene {i}",
                    f"Evidence or development path {i}",
                    f"Transition to chapter {i + 1}" if i < chapter_count else "Synthesis and close",
                ],
            }
            for i in range(1, chapter_count + 1)
        ]
        return {
            "outline": {
                "synopsis": (
                    f"'{project.title}' is a {project.genre.lower()} book "
                    f"for {project.target_audience.lower()} written in a {project.tone.lower()} tone."
                ),
                "chapters": chapters,
            },
            "metadata": {
                "estimated_word_count": project.target_word_count,
                "chapter_count": chapter_count,
                "pacing": "moderate",
                "themes": [project.genre, "clarity", "progression"],
            },
            "next_steps": [
                "Review and edit the generated outline.",
                "Run refine_outline with explicit feedback.",
                "Generate chapters sequentially.",
            ],
        }

    def _fallback_chapter(
        self,
        project: BookProject,
        outline: Dict[str, Any],
        chapter_number: int,
    ) -> Dict[str, Any]:
        chapter_title = self._get_chapter_title(outline, chapter_number)
        chapter_points = self._get_chapter_points(outline, chapter_number)
        bullet_lines = "\n".join(f"- {bp}" for bp in chapter_points) or "- Expand the central idea."
        content = "\n\n".join([
            f"# {chapter_title}",
            f"This chapter introduces {chapter_title} in a {project.tone.lower()} voice.",
            "## Development",
            bullet_lines,
            "## Closing",
            "This section reinforces the chapter objective and bridges to the next.",
        ])
        return {
            "chapter": {
                "number": chapter_number,
                "title": chapter_title,
                "content": content,
                "summary": self._summarize(content),
            },
            "metadata": {
                "key_themes": [project.genre, "narrative coherence"],
                "seo_keywords": [project.title, chapter_title],
            },
            "next_steps": [
                "Review chapter output.",
                "Regenerate with tighter feedback if needed.",
                "Proceed to the next chapter.",
            ],
        }

    # ------------------------------------------------------------------
    # Private — outline helpers
    # ------------------------------------------------------------------

    def _get_chapter_title(self, outline: Dict[str, Any], chapter_number: int) -> str:
        for chapter in outline.get("chapters", []) if isinstance(outline, dict) else []:
            if chapter.get("number") == chapter_number:
                title = str(chapter.get("title", "")).strip()
                if title:
                    return title
        return f"Chapter {chapter_number}"

    def _get_chapter_points(self, outline: Dict[str, Any], chapter_number: int) -> List[str]:
        for chapter in outline.get("chapters", []) if isinstance(outline, dict) else []:
            if chapter.get("number") == chapter_number:
                points = chapter.get("bullet_points", [])
                if isinstance(points, list):
                    return [str(p).strip() for p in points if str(p).strip()]
        return []

    def _summarize(self, content: str) -> str:
        sentence = content.replace("\n", " ").strip()
        return sentence[:217] + "..." if len(sentence) > 220 else sentence


# ---------------------------------------------------------------------------
# Prompt-building utilities
# Pure functions — stateless, independently testable, zero side-effects.
# ---------------------------------------------------------------------------

def _build_system_prompt(role: str, task: str, schema: str) -> str:
    """
    Assemble a structured system prompt with a consistent three-part layout:
    role identity → task instruction with chain-of-thought cue → output schema + JSON rule.

    Keeping role, task, and schema separate makes each independently editable
    and ensures the JSON rule always appears last, closest to the generation boundary.
    """
    return "\n\n".join([
        f"ROLE: {role}",
        f"TASK: {task}",
        f"OUTPUT SCHEMA:\n{schema}",
        _JSON_RULE,
    ])


def _book_header(project: BookProject) -> str:
    """Canonical block of book metadata — identical across all methods."""
    return (
        f"Title: {project.title}\n"
        f"Genre: {project.genre}\n"
        f"Target Audience: {project.target_audience}\n"
        f"Tone: {project.tone}\n"
        f"Language: {project.language}\n"
        f"Target Word Count: {project.target_word_count:,}"
    )


def _profile_block(project: BookProject) -> str:
    profile = _project_profile_dict(project)
    if not profile:
        return ""
    return _section("Advanced Book Profile", json.dumps(profile, ensure_ascii=False, indent=2))


def _project_profile_dict(project: BookProject) -> Dict[str, Any]:
    raw_meta = project.metadata_json if isinstance(project.metadata_json, dict) else {}
    user_concept = raw_meta.get("user_concept", {})
    profile: Dict[str, Any] = {}
    if isinstance(user_concept, dict) and isinstance(user_concept.get("profile"), dict):
        profile = user_concept.get("profile", {})
    elif isinstance(raw_meta.get("profile"), dict):
        profile = raw_meta.get("profile", {})
    return profile if isinstance(profile, dict) else {}


def _canonical_rich_element_type(value: Any) -> str:
    text = _normalize_for_match(str(value or ""))
    mapping = {
        "tables": "table",
        "table": "table",
        "flowcharts": "flowchart",
        "flowchart": "flowchart",
        "figures diagrams": "figure",
        "figure": "figure",
        "figures": "figure",
        "diagram": "figure",
        "diagrams": "figure",
        "callout boxes": "callout",
        "callout box": "callout",
        "callouts": "callout",
        "callout": "callout",
        "code blocks": "code_block",
        "code block": "code_block",
        "code": "code_block",
        "quotes": "quote",
        "quote": "quote",
        "lists": "list",
        "list": "list",
    }
    return mapping.get(text, "")


def _requested_rich_elements_from_project(project: BookProject) -> List[str]:
    profile = _project_profile_dict(project)
    raw = profile.get("richElements", [])
    items = raw if isinstance(raw, list) else []
    out: List[str] = []
    for item in items:
        canonical = _canonical_rich_element_type(item)
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def _normalize_chapter_plan_rich_elements(plan: Dict[str, Any] | Any) -> Dict[str, Any]:
    out = dict(plan) if isinstance(plan, dict) else {}

    normalized_rich_plan: List[Dict[str, Any]] = []
    raw_rich_plan = out.get("rich_elements_plan", [])
    if isinstance(raw_rich_plan, list):
        for item in raw_rich_plan:
            if not isinstance(item, dict):
                continue
            element_type = _canonical_rich_element_type(item.get("type"))
            if not element_type:
                continue
            normalized_rich_plan.append(
                {
                    "type": element_type,
                    "section": str(item.get("section", "")).strip(),
                    "purpose": str(item.get("purpose", "")).strip(),
                    "required": bool(item.get("required")),
                }
            )
    out["rich_elements_plan"] = normalized_rich_plan

    normalized_visual_specs: List[Dict[str, str]] = []
    raw_visual_specs = out.get("visual_specs", [])
    if isinstance(raw_visual_specs, list):
        for item in raw_visual_specs:
            if not isinstance(item, dict):
                continue
            visual_type = _canonical_rich_element_type(item.get("type"))
            if visual_type not in {"figure", "flowchart"}:
                continue
            normalized_visual_specs.append(
                {
                    "type": visual_type,
                    "placement_section": str(item.get("placement_section", "")).strip(),
                    "caption": str(item.get("caption", "")).strip(),
                    "prompt": str(item.get("prompt", "")).strip(),
                }
            )
    out["visual_specs"] = normalized_visual_specs
    return out


def _fallback_rich_elements_plan(chapter_points: List[str], requested_rich: List[str]) -> List[Dict[str, Any]]:
    if not requested_rich:
        return []
    section_hint = (chapter_points[0] if chapter_points else "Main development")[:120]
    plans: List[Dict[str, Any]] = []
    for element_type in requested_rich:
        if element_type in {"figure", "flowchart", "list"}:
            continue
        plans.append(
            {
                "type": element_type,
                "section": section_hint,
                "purpose": "Improve clarity and teaching value for this chapter.",
                "required": False,
            }
        )
        if len(plans) >= 2:
            break
    return plans


def _fallback_visual_specs_for_rich_elements(chapter_points: List[str], requested_rich: List[str]) -> List[Dict[str, str]]:
    if "figure" not in requested_rich and "flowchart" not in requested_rich:
        return []
    point = (chapter_points[0] if chapter_points else "core concept")[:140]
    specs: List[Dict[str, str]] = []
    if "figure" in requested_rich:
        specs.append(
            {
                "type": "figure",
                "placement_section": point,
                "caption": "Concept illustration",
                "prompt": f"Educational clean diagram-style illustration explaining {point} for beginners.",
            }
        )
    if "flowchart" in requested_rich:
        specs.append(
            {
                "type": "flowchart",
                "placement_section": point,
                "caption": "Process flow",
                "prompt": f"Flowchart showing the step-by-step process for {point} in a beginner-friendly way.",
            }
        )
    return specs


def _rich_elements_preferences_block(project: BookProject, chapter_plan: Dict[str, Any] | None = None) -> str:
    requested = _requested_rich_elements_from_project(project)
    if not requested:
        return _section(
            "Rich Elements",
            "No specific rich elements were requested. Use standard prose unless a table, code block, quote, or callout clearly improves understanding.",
        )

    lines = [
        f"Requested rich elements (use where relevant, not every chapter): {', '.join(requested)}.",
        "Formatting contract for export parsing:",
        "- code_block: fenced markdown with triple backticks",
        "- quote: markdown blockquote lines starting with '>'",
        "- callout: blockquote with marker like '> [!NOTE]' or '> [!TIP]'",
        "- table: markdown table syntax",
        "- figure placeholder: [FIGURE: short caption or placement note]",
        "- flowchart placeholder: [FLOWCHART: short caption or process note]",
        "- If a requested element is not useful in this chapter, omit it.",
    ]

    if isinstance(chapter_plan, dict):
        rich_plan = chapter_plan.get("rich_elements_plan", [])
        visual_specs = chapter_plan.get("visual_specs", [])
        if isinstance(rich_plan, list) and rich_plan:
            lines.append("Planned rich elements for this chapter:")
            lines.append(json.dumps({"rich_elements_plan": rich_plan, "visual_specs": visual_specs or []}, ensure_ascii=False, indent=2))

    return _section("Rich Elements Preferences", "\n".join(lines))


def _extract_visual_placeholders(content: str) -> List[Dict[str, str]]:
    placeholders: List[Dict[str, str]] = []
    pattern = re.compile(r"^\[(FIGURE|FLOWCHART)\s*:\s*(.+?)\]\s*$", flags=re.IGNORECASE | re.MULTILINE)
    for match in pattern.finditer(str(content or "")):
        placeholders.append(
            {
                "type": match.group(1).strip().lower(),
                "label": match.group(2).strip(),
                "placeholder": match.group(0).strip(),
            }
        )
    return placeholders


def _detect_rich_elements_in_content(content: str) -> List[str]:
    text = str(content or "")
    normalized = text.lower()
    used: List[str] = []

    def add(name: str) -> None:
        if name not in used:
            used.append(name)

    if "```" in text:
        add("code_block")
    if re.search(r"(?m)^\s*>\s+\S", text):
        add("quote")
    if re.search(r"(?m)^\s*>\s+\[\![A-Z]+\]", text):
        add("callout")
    if re.search(r"(?m)^\s*\|.+\|\s*$", text) and re.search(r"(?m)^\s*\|?\s*:?-{2,}", text):
        add("table")
    if re.search(r"(?m)^\s*[-*]\s+\S", text) or re.search(r"(?m)^\s*\d+\.\s+\S", text):
        add("list")
    if "[figure:" in normalized:
        add("figure")
    if "[flowchart:" in normalized:
        add("flowchart")
    return used


def _augment_chapter_payload_rich_elements(
    payload: Dict[str, Any] | Any,
    project: BookProject,
    chapter_plan: Dict[str, Any] | None,
) -> Dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {}
    chapter = out.get("chapter", {})
    if not isinstance(chapter, dict):
        return out

    content = str(chapter.get("content", "") or "")
    requested = _requested_rich_elements_from_project(project)
    used = _detect_rich_elements_in_content(content)
    placeholders = _extract_visual_placeholders(content)
    normalized_plan = _normalize_chapter_plan_rich_elements(chapter_plan or {})

    metadata = out.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    rich_meta = metadata.get("rich_elements", {})
    if not isinstance(rich_meta, dict):
        rich_meta = {}

    rich_meta["requested"] = requested
    rich_meta["used"] = used
    rich_meta["missing_requested"] = [element for element in requested if element not in used]
    rich_meta["visual_placeholders"] = placeholders

    rich_plan = normalized_plan.get("rich_elements_plan", []) if isinstance(normalized_plan, dict) else []
    visual_specs = normalized_plan.get("visual_specs", []) if isinstance(normalized_plan, dict) else []
    if isinstance(rich_plan, list) and rich_plan:
        rich_meta["plan"] = rich_plan
    if isinstance(visual_specs, list) and visual_specs:
        rich_meta["visual_specs"] = visual_specs
        rich_meta.setdefault("render_status", "placeholders_pending")

    metadata["rich_elements"] = rich_meta
    out["metadata"] = metadata
    return out


def _refine_non_negotiables_block(project: BookProject) -> str:
    profile = _project_profile_dict(project)
    if not profile:
        return ""

    fields = [
        ("audience", "Audience"),
        ("audienceKnowledgeLevel", "Audience Knowledge Level"),
        ("bookPurpose", "Book Purpose"),
        ("genre", "Genre"),
        ("language", "Language"),
        ("tone", "Tone"),
        ("writingStyle", "Writing Style"),
        ("pointOfView", "Point of View"),
        ("sentenceRhythm", "Sentence Rhythm"),
        ("vocabularyLevel", "Vocabulary Level"),
        ("chapterLength", "Chapter Length"),
        ("length", "Target Word Count"),
        ("contentBoundaries", "Content Boundaries"),
    ]

    lines: List[str] = []
    for key, label in fields:
        value = profile.get(key)
        if isinstance(value, str):
            if not value.strip():
                continue
            text_value = value.strip()
        elif isinstance(value, (int, float)):
            text_value = str(int(value)) if isinstance(value, bool) is False and float(value).is_integer() else str(value)
        elif isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if not cleaned:
                continue
            text_value = ", ".join(cleaned)
        elif isinstance(value, bool):
            text_value = "On" if value else "Off"
        else:
            continue
        lines.append(f"- {label}: {text_value}")

    if not lines:
        return ""

    lines.append("- Rule: Preserve these constraints unless the editorial feedback explicitly asks to change them.")
    if any(line.lower().startswith("- content boundaries:") for line in lines):
        lines.append("- Safety Rule: Never weaken or remove content boundaries unless the user clearly instructs it.")

    return _section("Non-Negotiable Brief Constraints", "\n".join(lines))


def _split_profile_confirmed_and_defaults(profile: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    confirmed: Dict[str, Any] = {}
    defaults: Dict[str, Any] = {}
    for key, value in profile.items():
        if key in _PROFILE_FORM_DEFAULTS and value == _PROFILE_FORM_DEFAULTS[key]:
            defaults[key] = value
        else:
            confirmed[key] = value
    return confirmed, defaults


def _normalize_profile_value(field: str, value: Any) -> Any:
    if field in {"frontMatter", "backMatter", "richElements"}:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return []
    if field == "ghostwritingMode":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "on"}
    if field == "length":
        try:
            return max(300, int(float(str(value).strip())))
        except Exception:
            return 3000
    if field == "vocabularyLevel":
        normalized = str(value).strip()
        mapped = {
            "basic": "Simple",
            "beginner": "Simple",
            "easy": "Simple",
            "simple": "Simple",
            "medium": "Intermediate",
            "moderate": "Intermediate",
            "intermediate": "Intermediate",
            "advanced": "Technical",
            "expert": "Technical",
            "technical": "Technical",
            "literary": "Literary",
        }.get(normalized.lower())
        return mapped or normalized
    if field == "tone":
        normalized = str(value).strip()
        mapped = {
            "friendly": "Conversational",
            "casual": "Conversational",
            "warm": "Conversational",
            "chatty": "Conversational",
            "educational": "Informative",
            "explanatory": "Informative",
            "clear": "Informative",
            "professional": "Formal",
            "serious": "Formal",
            "scholarly": "Academic",
            "motivational": "Inspirational",
            "encouraging": "Inspirational",
            "fun": "Humorous",
            "playful": "Humorous",
        }.get(normalized.lower())
        return mapped or normalized
    return str(value).strip()


def _sanitize_assistant_updates(
    updates: Dict[str, Any],
    current_profile: Dict[str, Any],
    user_message: str,
    conversation: List[Dict[str, str]],
) -> Dict[str, Any]:
    cleaned = dict(updates)
    if "title" not in cleaned:
        return cleaned

    current_title = str(current_profile.get("title", "")).strip()
    updated_title = str(cleaned.get("title", "")).strip()

    # Do not allow assistant-generated placeholders/greetings to satisfy title.
    if not _is_valid_profile_title(updated_title):
        logger.debug("Dropping assistant title update as placeholder/invalid: %r", updated_title)
        cleaned.pop("title", None)
        return cleaned

    # If title changed, require that it appears in user-provided text.
    if _normalize_for_match(updated_title) != _normalize_for_match(current_title):
        title_is_grounded = _title_grounded_in_user_input(updated_title, conversation, user_message)
        title_is_confirmed = (
            _is_affirmative_confirmation(user_message)
            and _assistant_recently_mentions_value(updated_title, conversation)
        )
        if title_is_confirmed:
            logger.debug("Accepting assistant-proposed title via user confirmation: %r", updated_title)
        if not (title_is_grounded or title_is_confirmed):
            logger.debug(
                "Dropping assistant title update as ungrounded (title=%r, user_message=%r)",
                updated_title,
                user_message,
            )
            cleaned.pop("title", None)
    return cleaned


def _augment_assistant_updates_from_context(
    updates: Dict[str, Any],
    current_profile: Dict[str, Any],
    user_message: str,
) -> Dict[str, Any]:
    """
    Preserve useful audience info when the user gives an age band (e.g. 10-14)
    but the model treats it as conversational context instead of a field update.
    """
    enriched = dict(updates)
    age_band = _extract_age_band(user_message)
    if not age_band:
        return enriched

    audience_current = str(enriched.get("audience") or current_profile.get("audience") or "").strip()
    context_text = f"{user_message} {audience_current}".lower()
    if not re.search(r"\b(kid|kids|child|children|teen|teens)\b", context_text):
        return enriched

    if "audience" not in enriched:
        if audience_current.lower() in {"general readers", "readers"}:
            enriched["audience"] = f"Kids ages {age_band}"
        elif audience_current and not re.search(r"\b\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\b", audience_current):
            if re.search(r"\b(kid|kids|child|children|teen|teens)\b", audience_current.lower()):
                enriched["audience"] = f"{audience_current} ages {age_band}"
        elif not audience_current:
            enriched["audience"] = f"Kids ages {age_band}"

    if "audienceKnowledgeLevel" not in enriched:
        current_level = str(current_profile.get("audienceKnowledgeLevel", "")).strip()
        if not current_level or current_level == "Complete Beginner":
            enriched["audienceKnowledgeLevel"] = "Complete Beginner"

    return enriched


def _repair_semantic_assistant_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Correct common LLM field-assignment mistakes (e.g. "instructional" saved as tone).
    """
    repaired = dict(updates)
    tone_value = str(repaired.get("tone", "")).strip()
    style_value = str(repaired.get("writingStyle", "")).strip()

    style_like_values = {"narrative", "analytical", "instructional", "lyrical", "journalistic"}
    tone_like_values = {
        "formal",
        "conversational",
        "inspirational",
        "academic",
        "humorous",
        "dark",
        "neutral",
        "informative",
    }

    if tone_value and tone_value.lower() in style_like_values and not style_value:
        repaired["writingStyle"] = tone_value.title() if tone_value.lower() != "instructional" else "Instructional"
        repaired.pop("tone", None)

    if style_value and style_value.lower() in tone_like_values and not tone_value:
        normalized = style_value.lower()
        repaired["tone"] = normalized.title() if normalized not in {"academic", "informative"} else ("Academic" if normalized == "academic" else "Informative")
        repaired.pop("writingStyle", None)

    return repaired


def _extract_age_band(text: str) -> str:
    match = re.search(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    start, end = match.group(1), match.group(2)
    return f"{start}-{end}"


def _is_finalize_intent(message: str) -> bool:
    text = " ".join(str(message or "").strip().lower().split())
    if not text:
        return False
    if any(token in text for token in ("don't", "do not", "not yet", "later", "wait", "hold")):
        return False
    if "finalize" in text or "finalise" in text:
        return True
    if "confirm" in text and ("final" in text or "brief" in text or "form" in text):
        return True
    if "approve" in text and ("final" in text or "brief" in text or "form" in text):
        return True
    if "yes" in text and ("final" in text or "confirm" in text):
        return True
    if "agree" in text and ("final" in text or "confirm" in text):
        return True
    return False


def _is_defaults_acceptance_intent(message: str) -> bool:
    text = _normalize_for_match(message)
    if not text:
        return False
    if any(token in text for token in ("dont", "do not", "not yet", "later", "wait", "hold")):
        return False
    phrases = (
        "keep default",
        "keep defaults",
        "use default",
        "use defaults",
        "you decide",
        "set it yourself",
        "set by yourself",
        "add by yourself",
        "add by your self",
        "im happy with this",
        "i am happy with this",
        "looks good",
        "sounds good",
        "that is fine",
        "thats fine",
        "this is enough",
        "good to go",
    )
    return any(phrase in text for phrase in phrases)


def _wants_more_optional_details(message: str) -> bool:
    text = _normalize_for_match(message)
    if not text:
        return False
    phrases = (
        "add more detail",
        "add more details",
        "more optional detail",
        "more optional details",
        "add optional details",
        "i want to add more details",
        "include more elements",
        "add more optional details",
    )
    return any(phrase in text for phrase in phrases)


def _is_pause_or_rest_intent(message: str) -> bool:
    text = _normalize_for_match(message)
    if not text:
        return False
    pause_phrases = (
        "i am ill",
        "im ill",
        "i am sick",
        "im sick",
        "need to rest",
        "i need to rest",
        "need a break",
        "i need a break",
        "talk later",
        "continue later",
        "lets continue later",
        "let s continue later",
    )
    return any(phrase in text for phrase in pause_phrases)


def _assistant_recently_finalized(conversation: List[Dict[str, str]]) -> bool:
    for turn in reversed(conversation[-12:]):
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role", "")).strip().lower() != "assistant":
            continue
        text = _normalize_for_match(str(turn.get("content", "")))
        if not text:
            continue
        if any(
            phrase in text
            for phrase in (
                "i have applied your brief to the form",
                "your brief is all set",
                "ive finalized the brief",
                "i ve finalized the brief",
                "all set ive finalized",
                "all set i ve finalized",
                "finalized the brief",
            )
        ):
            return True
    return False


def _is_off_topic_or_out_of_scope(message: str) -> bool:
    text = _normalize_for_match(message)
    if not text:
        return False

    # Stay in-scope for book-brief and form-field terms.
    in_scope_tokens = (
        "book",
        "title",
        "subtitle",
        "genre",
        "audience",
        "reader",
        "purpose",
        "tone",
        "style",
        "point of view",
        "vocabulary",
        "chapter",
        "word count",
        "publishing",
        "front matter",
        "back matter",
        "cta",
        "call to action",
        "reference books",
        "style reference",
        "content boundaries",
        "rich elements",
        "finalize",
        "finalise",
        "brief",
    )
    if any(token in text for token in in_scope_tokens):
        return False

    code_tokens = (
        "python code",
        "write code",
        "code to ",
        "print helo",
        "print hello",
        "javascript",
        "sql query",
        "html code",
    )
    fact_tokens = (
        "pm of",
        "prime minister",
        "president of",
        "capital of",
        "who is ",
        "weather ",
        "news ",
    )
    if any(token in text for token in code_tokens):
        return True
    if any(token in text for token in fact_tokens):
        return True

    return False


def _missing_required_profile(profile: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in _REQUIRED_PROFILE_FIELDS:
        value = profile.get(field)
        if field == "title":
            if not _is_valid_profile_title(value):
                missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
        elif isinstance(value, list) and not value:
            missing.append(field)
        elif value in (None, ""):
            missing.append(field)
    return missing


def _missing_optional_profile_fields(profile: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in _OPTIONAL_PROFILE_FIELDS:
        value = profile.get(field)
        if isinstance(value, str):
            if not value.strip():
                missing.append(field)
            continue
        if isinstance(value, list):
            if not value:
                missing.append(field)
            continue
        if value in (None, ""):
            missing.append(field)
    return missing


def _next_missing_required_field(profile: Dict[str, Any]) -> Optional[str]:
    for field in _PROFILE_FIELD_ORDER:
        if field not in _REQUIRED_PROFILE_FIELDS:
            continue
        value = profile.get(field)
        if field == "title":
            if not _is_valid_profile_title(value):
                return field
            continue
        if isinstance(value, str):
            if not value.strip():
                return field
            continue
        if isinstance(value, list):
            if not value:
                return field
            continue
        if value in (None, ""):
            return field
    return None


def _next_missing_optional_field(profile: Dict[str, Any]) -> Optional[str]:
    missing = set(_missing_optional_profile_fields(profile))
    for field in _LATE_OPTIONAL_BATCH_FIELDS:
        if field in missing:
            return field
    for field in _OPTIONAL_PROFILE_FIELDS:
        if field in missing:
            return field
    return None


def _optional_batch_reply(optional_missing: List[str]) -> str:
    missing = set(optional_missing)
    parts: List[str] = []
    if {"subtitle", "primaryCta"} & missing:
        parts.append("subtitle or reader call-to-action")
    if {"customInstructions", "contentBoundaries", "booksToEmulate", "styleReferencePassage"} & missing:
        parts.append("style/reference guidance")
    if {"frontMatter", "backMatter", "richElements"} & missing:
        parts.append("front/back matter and rich elements")
    if not parts:
        parts.append("optional details")
    if len(parts) == 1:
        detail_text = parts[0]
    elif len(parts) == 2:
        detail_text = f"{parts[0]} and {parts[1]}"
    else:
        detail_text = f"{parts[0]}, {parts[1]}, and {parts[2]}"
    return (
        "We have the core brief. Before finalizing, we can add a few optional details like "
        f"{detail_text}. Want to add any, or should I keep the defaults and finalize?"
    )


def _next_missing_field(profile: Dict[str, Any]) -> Optional[str]:
    for field in _PROFILE_FIELD_ORDER:
        value = profile.get(field)
        if field == "title":
            if not _is_valid_profile_title(value):
                return field
            continue
        if isinstance(value, str):
            if not value.strip():
                return field
            continue
        if isinstance(value, list):
            if not value:
                return field
            continue
        if value in (None, ""):
            return field
    return None


def _is_valid_profile_title(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = _normalize_for_match(text)
    if not normalized:
        return False
    return normalized not in _TITLE_PLACEHOLDER_VALUES


def _title_grounded_in_user_input(
    title: str,
    conversation: List[Dict[str, str]],
    user_message: str,
) -> bool:
    normalized_title = _normalize_for_match(title)
    if not normalized_title:
        return False
    user_text_parts: List[str] = []
    for turn in conversation[-20:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).strip().lower()
        if role != "user":
            continue
        content = str(turn.get("content", "")).strip()
        if content:
            user_text_parts.append(content)
    latest = str(user_message or "").strip()
    if latest:
        user_text_parts.append(latest)
    normalized_user_text = _normalize_for_match(" ".join(user_text_parts))
    return bool(normalized_user_text and normalized_title in normalized_user_text)


def _normalize_for_match(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(cleaned.split())


def _assistant_recently_mentions_value(value: str, conversation: List[Dict[str, str]]) -> bool:
    normalized_value = _normalize_for_match(value)
    if not normalized_value:
        return False
    for turn in reversed(conversation[-10:]):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).strip().lower()
        if role != "assistant":
            continue
        content = _normalize_for_match(str(turn.get("content", "")))
        if normalized_value and normalized_value in content:
            return True
    return False


def _is_affirmative_confirmation(message: str) -> bool:
    text = _normalize_for_match(message)
    if not text:
        return False
    if any(token in text for token in ("dont", "do not", "not", "later", "wait", "hold")):
        return False
    exact_yes = {
        "yes",
        "y",
        "ok",
        "okay",
        "fine",
        "great",
        "perfect",
        "thats great",
        "that s great",
        "this name is fine",
        "that name is fine",
        "looks good",
        "sounds good",
        "this is fine",
    }
    if text in exact_yes:
        return True
    if "yes" in text and any(token in text for token in ("title", "name", "good", "fine", "great")):
        return True
    if any(phrase in text for phrase in (
        "i like that title",
        "i like this title",
        "i love that title",
        "i love this title",
        "that title works",
        "this title works",
        "use that title",
        "keep that title",
        "i like that name",
        "that name works",
    )):
        return True
    if any(token in text for token in ("like", "love", "works", "perfect")) and any(token in text for token in ("title", "name")):
        return True
    return False


def _reply_claims_completion(reply: str) -> bool:
    text = _normalize_for_match(reply)
    if not text:
        return False
    completion_signals = (
        "all required",
        "ready to finalize",
        "would you like to finalize",
        "can finalize",
        "finalize the book details",
        "apply them to the form",
    )
    return any(signal in text for signal in completion_signals)


def _reply_stuck_in_optional_loop(reply: str) -> bool:
    text = _normalize_for_match(reply)
    if not text:
        return False
    return (
        "we have the core brief" in text
        and "optional details" in text
        and ("keep the defaults" in text or "finalize" in text)
    )


def _reply_uses_default_word_count_as_user_fact(reply: str, current_profile: Dict[str, Any]) -> bool:
    text = _normalize_for_match(reply)
    if not text:
        return False
    if "you mentioned" not in text and "you said" not in text:
        return False
    try:
        length = int(current_profile.get("length", 0))
    except Exception:
        return False
    if length != _PROFILE_FORM_DEFAULTS.get("length"):
        return False
    return ("word count" in text or "3000" in text or "3 000" in text)


def _ordered_unique_fields(fields: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for field in fields:
        name = str(field).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _normalize_assistant_suggestions(
    raw_suggestions: Any,
    next_field: str,
    profile: Dict[str, Any],
    is_finalized: bool,
) -> List[str]:
    if is_finalized:
        return []

    suggestions: List[str] = []
    if isinstance(raw_suggestions, list):
        for item in raw_suggestions:
            text = str(item).strip()
            if not text:
                continue
            # UI buttons should feel like natural reply continuations, not new questions.
            if text.endswith("?"):
                continue
            if len(text) > 60:
                continue
            if len(text.split()) > 10:
                continue
            if _looks_like_assumptive_content_guess(text):
                continue
            suggestions.append(text)

    suggestions = _ordered_unique_fields(suggestions)[:3]
    if suggestions:
        return suggestions
    return _assistant_suggestion_fallback(next_field, profile)


def _filter_assistant_suggestions_for_context(
    suggestions: List[str],
    next_field: str,
    missing_required: List[str],
    profile: Dict[str, Any],
) -> List[str]:
    if not suggestions:
        return suggestions

    filtered: List[str] = []
    for suggestion in suggestions:
        text = _normalize_for_match(suggestion)
        if not text:
            continue
        if missing_required and any(token in text for token in ("finalize", "finalise", "confirm", "apply")):
            continue
        if _looks_like_meta_workflow_suggestion(text):
            continue
        if "chapter length" in text and next_field != "chapterLength":
            continue
        filtered.append(suggestion)

    filtered = _ordered_unique_fields(filtered)[:3]
    if filtered:
        return filtered
    return _assistant_suggestion_fallback(next_field, profile)


def _looks_like_meta_workflow_suggestion(normalized_text: str) -> bool:
    prefixes = (
        "lets ",
        "let s ",
        "move on",
        "go to ",
        "next step",
        "discuss more",
        "talk more",
        "skip ",
    )
    return any(normalized_text.startswith(prefix) for prefix in prefixes)


def _looks_like_assumptive_content_guess(text: str) -> bool:
    normalized = _normalize_for_match(text)
    if not normalized:
        return False
    assumptive_prefixes = (
        "im focusing on",
        "i am focusing on",
        "my book is about",
        "its about",
        "it is about",
        "i want to write about",
        "i want this book to be about",
        "i am writing about",
    )
    return any(normalized.startswith(prefix) for prefix in assumptive_prefixes)


def _assistant_topic_seed(profile: Dict[str, Any]) -> str:
    source = " ".join([
        str(profile.get("title", "")),
        str(profile.get("subtitle", "")),
        str(profile.get("customInstructions", "")),
        str(profile.get("bookPurpose", "")),
    ])
    tokens = [
        t for t in re.findall(r"[a-zA-Z0-9]+", source.lower())
        if t not in {
            "the", "a", "an", "and", "for", "of", "to", "in", "on", "with",
            "book", "guide", "introduction", "complete", "practical",
        }
    ]
    ordered = _ordered_unique_fields(tokens)
    return " ".join(ordered[:4]) if ordered else "this topic"


def _assistant_suggestion_fallback(next_field: str, profile: Dict[str, Any]) -> List[str]:
    topic = _assistant_topic_seed(profile)
    audience = str(profile.get("audience", "")).strip() or "general readers"
    tone = str(profile.get("tone", "")).strip() or "clear"
    style = str(profile.get("writingStyle", "")).strip() or "practical"

    if next_field == "title":
        return [
            f"Suggest 3 title ideas for {topic}",
            "I have a working title but want better options",
            "Use a beginner-friendly title",
        ]
    if next_field == "subtitle":
        return [
            f"A beginner-friendly guide to {topic}",
            f"Practical strategies for {audience}",
            "No subtitle",
        ]
    if next_field == "audience":
        return [
            f"Beginners interested in {topic}",
            f"Students learning {topic}",
            "General readers",
        ]
    if next_field == "audienceKnowledgeLevel":
        return ["Complete Beginner", "Intermediate", "Expert"]
    if next_field == "genre":
        return ["Non-fiction", "Education", "Business"]
    if next_field == "language":
        return ["English", "Hindi", "Spanish"]
    if next_field == "bookPurpose":
        return ["Teach a Skill", "Establish Authority", "Tell a Story"]
    if next_field == "tone":
        return ["Informative", "Conversational", "Academic"]
    if next_field == "writingStyle":
        return [f"{style}", "Instructional", "Analytical"]
    if next_field == "pointOfView":
        return ["Second Person", "Third Person", "First Person"]
    if next_field == "sentenceRhythm":
        return ["Mixed", "Short & Punchy", "Long & Flowing"]
    if next_field == "vocabularyLevel":
        return ["Simple", "Intermediate", "Technical"]
    if next_field == "publishingIntent":
        return ["Self-publish", "Traditional", "Academic"]
    if next_field == "chapterLength":
        return ["Short ~1500w", "Medium ~3000w", "Long ~5000w"]
    if next_field == "culturalContext":
        return [
            "No specific cultural context",
            "Global modern audience",
            "Classroom / school context",
        ]
    if next_field == "primaryCta":
        return [
            f"Apply one {topic} idea this week",
            "Try a practical exercise",
            "No primary CTA",
        ]
    if next_field == "customInstructions":
        return [
            f"Teach {topic} in simple language",
            f"Use {tone.lower()} tone with examples",
            "Add exercises and chapter-end summaries",
        ]
    if next_field == "contentBoundaries":
        return [
            "Avoid jargon",
            "Avoid unsafe or harmful examples",
            "Avoid unverified claims",
        ]
    if next_field == "booksToEmulate":
        return [
            f"Suggest 3 books to emulate for {topic}",
            "No reference books",
            "Use a clear educational style",
        ]
    if next_field == "styleReferencePassage":
        return [
            "I will paste a sample paragraph next",
            "No style reference passage",
            f"Keep tone {tone.lower()}",
        ]
    if next_field == "length":
        return ["3000", "5000", "10000"]
    if next_field == "pageFeel":
        return ["Standard", "Pocket Guide", "Comprehensive Reference"]
    if next_field in {"frontMatter", "backMatter", "richElements"}:
        # Frontend renders controlled checkboxes for these based on next_field.
        return []
    return ["Tell me more", "Suggest options", "Use sensible defaults"]


def _field_aliases() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("frontMatter", ("front matter", "frontmatter")),
        ("backMatter", ("back matter", "backmatter")),
        ("primaryCta", ("primary cta", "primary cta after reading", "cta", "call to action")),
        ("booksToEmulate", ("reference books", "books to emulate")),
        ("styleReferencePassage", ("style reference passage", "style reference", "reference passage")),
        ("customInstructions", ("topics skills", "topics / skills", "topics and skills", "custom instructions")),
        ("contentBoundaries", ("content boundaries", "content boundaries optional", "boundaries")),
        ("chapterLength", ("chapter length",)),
        ("pageFeel", ("page feel",)),
        ("publishingIntent", ("publishing intent",)),
        ("audienceKnowledgeLevel", ("knowledge level", "audience knowledge level")),
        ("richElements", ("rich elements", "elements", "visual elements")),
    )


def _field_label_reference_field(message: str) -> str:
    text = _normalize_for_match(message)
    if not text:
        return ""
    # Used when users tap/paste a field label directly (without asking a full question).
    if len(text.split()) > 6:
        return ""
    for field, patterns in _field_aliases():
        for pattern in patterns:
            if text == pattern:
                return field
    return ""


def _field_explanation_request_field(message: str) -> str:
    text = _normalize_for_match(message)
    if not text:
        return ""
    if not any(token in text for token in ("what is", "what s", "means", "meaning", "explain", "define")):
        return ""

    for field, patterns in _field_aliases():
        for pattern in patterns:
            if pattern in text:
                return field
    return ""


def _field_explanation_reply(field: str) -> str:
    explanations = {
        "frontMatter": (
            "Front matter means the pages before Chapter 1, like a foreword, preface, or introduction. "
            "It sets context for the reader before the main content starts. "
            "Would you like to include just an Introduction, or add a Preface/Foreword too?"
        ),
        "backMatter": (
            "Back matter means the pages after the main chapters, such as a glossary, appendix, bibliography, or about the author. "
            "These help readers review terms, references, and extras. "
            "Would you like to choose any of those?"
        ),
        "primaryCta": (
            "Primary CTA means the main action you want readers to take after finishing the book, such as applying a method, trying an exercise, or using your framework. "
            "If you do not need one, we can leave it blank."
        ),
        "booksToEmulate": (
            "Reference Books means books whose structure or style you want the AI to learn from. "
            "Adding titles with author names gives a stronger style signal."
        ),
        "styleReferencePassage": (
            "Style Reference Passage is a short paragraph in the voice you want. "
            "It is one of the strongest style signals you can provide for tone and sentence flow."
        ),
        "customInstructions": (
            "Topics / Skills is where you list what the book should cover or teach, plus any must-have elements like examples, analogies, or code snippets."
        ),
        "contentBoundaries": (
            "Content Boundaries are limits the AI should respect, such as topics to avoid, unsafe content, or claims you do not want included."
        ),
        "chapterLength": (
            "Chapter Length controls how long each chapter should feel (short, medium, or long). "
            "Together with total word count, it affects the estimated number of chapters."
        ),
        "pageFeel": (
            "Page Feel is the overall reading depth and density, like a quick guide versus a comprehensive reference."
        ),
        "publishingIntent": (
            "Publishing Intent means how you plan to use the book, such as self-publishing, traditional publishing, corporate/internal use, or academic use."
        ),
        "audienceKnowledgeLevel": (
            "Audience Knowledge Level is how much your readers already know before starting, such as complete beginner, intermediate, or expert."
        ),
        "richElements": (
            "Rich Elements are extra content formats inside chapters, like tables, diagrams, callout boxes, code blocks, quotes, or lists."
        ),
    }
    return explanations.get(field, "That field controls how the book is generated. I can explain it and help you choose a good value.")


def _question_for_field(field: str) -> str:
    prompts = {
        "title": "What is your book title or working title?",
        "subtitle": "Do you want a subtitle? If yes, share a draft line.",
        "genre": "Which genre fits best for this book?",
        "language": "Which language should the book be written in?",
        "length": "What target word count are you aiming for?",
        "pageFeel": "Which page feel do you want: Pocket Guide, Standard, or Comprehensive Reference?",
        "publishingIntent": "What is the publishing intent: Self-publish, Traditional, Corporate/Internal, or Academic?",
        "audience": "Who is the exact target audience?",
        "audienceKnowledgeLevel": "What is their starting level: Beginner, Intermediate, or Expert?",
        "culturalContext": "Any cultural or geographic context to align with?",
        "bookPurpose": "What is the primary purpose: authority, teaching, story, service, or research?",
        "primaryCta": "What should readers do after finishing the book?",
        "tone": "Which tone should we use?",
        "writingStyle": "Which writing style should lead this book?",
        "pointOfView": "What point of view do you prefer?",
        "tense": "Which tense should the writing use: present, past, or timeless/as appropriate?",
        "sentenceRhythm": "Should sentence rhythm be short, long-flowing, or mixed?",
        "vocabularyLevel": "What vocabulary level should we maintain?",
        "ghostwritingMode": "Should ghostwriting mode be ON (author voice from personal experience)?",
        "booksToEmulate": "Any books to emulate? Up to three titles is enough.",
        "styleReferencePassage": "Paste a style reference passage if you want close voice matching.",
        "customInstructions": "Any custom instructions we should enforce during generation?",
        "chapterLength": "Preferred chapter length: short, medium, or long?",
        "frontMatter": "Which front matter should be included: Foreword, Preface, Introduction?",
        "backMatter": "Which back matter should be included: Glossary, Appendix, Bibliography, About the Author?",
        "richElements": "Which rich elements should appear: tables, diagrams, callouts, code, quotes, lists?",
        "contentBoundaries": "Any content boundaries or topics to avoid?",
    }
    return prompts.get(field, "Share the next detail and I will map it into your brief.")


def _section(heading: str, body: str) -> str:
    """Wrap a block of text with a clear heading — omit if body is empty."""
    body = body.strip()
    return f"### {heading}\n{body}" if body else ""


def _knowledge_block(text: str) -> str:
    return _section(
        "Reference Material (draw on this where relevant — do not quote verbatim)",
        text,
    )


def _memory_block(text: str) -> str:
    return _section(
        "Prior Chapter Context (maintain continuity of voice, character, and argument)",
        text[:6000],
    )


def _join(*parts: str) -> str:
    """Join non-empty prompt sections with a consistent double newline."""
    return "\n\n".join(p for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# Guideline constants — separated from prompt assembly so they can be tuned
# independently without touching any method logic.
# ---------------------------------------------------------------------------

_OUTLINE_GUIDELINES = (
    "- Each bullet point must be specific enough for a ghostwriter to draft prose without follow-up questions.\n"
    "- Build a coherent narrative or argumentative arc: setup → development → resolution.\n"
    "- Match genre conventions: a thriller needs rising stakes; a how-to book needs progressive skill-building.\n"
    "- Avoid chapter titles like 'Introduction' or 'Conclusion' — every title should be evocative and content-specific.\n"
    "- Chapter count must reflect the target word count: ~2,500-3,500 words per chapter is a healthy target."
)

_REFINE_GUIDELINES = (
    "- Apply the feedback precisely and completely — partial application is a failure mode.\n"
    "- Do not alter chapters that the feedback does not address unless restructuring is essential for coherence.\n"
    "- If the feedback requires adding or removing chapters, renumber all chapters sequentially from 1.\n"
    "- The revised synopsis must reflect any structural changes made to the chapters."
)

_CHAPTER_GUIDELINES = (
    "- Use # for the chapter title and ## for section headings inside the content field.\n"
    "- Open with a hook — a scene, question, or provocation — before any exposition.\n"
    "- Each ## section should correspond to one bullet point from the outline.\n"
    "- Chapter length is a guideline, not an exact word target: let chapter importance, complexity, and examples determine depth.\n"
    "- It is normal for some chapters to be shorter bridge chapters and others to be longer anchor chapters.\n"
    "- If the brief requests rich elements, use them only where they genuinely improve clarity or instruction.\n"
    "- Use fenced markdown for code blocks, markdown tables for tables, and blockquotes for quotes/callouts.\n"
    "- Use placeholders like [FIGURE: ...] or [FLOWCHART: ...] for visuals so export can place generated assets later.\n"
    "- The closing paragraph must create forward momentum: a question, a reveal, or a consequence.\n"
    "- The summary field is for editorial use: capture the chapter's function in the book, not just its content."
)
