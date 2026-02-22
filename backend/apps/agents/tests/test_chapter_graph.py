from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from apps.agents.models import AgentRun
from apps.agents.services.orchestration import AgentOrchestrator
from apps.books.models import BookProject


class _FakeLLM:
    def __init__(self) -> None:
        self.plan_calls = 0
        self.draft_calls = 0
        self.review_calls = 0

    def plan_chapter(self, **kwargs):
        self.plan_calls += 1
        return {
            "plan": {
                "chapter_number": kwargs["chapter_number"],
                "chapter_title": "Foundations",
                "objective": "Teach the core concept.",
                "sections": [{"heading": "Core", "purpose": "Explain basics", "evidence_or_example": "Simple case"}],
                "continuity_notes": [],
                "concept_alignment": "High",
            },
            "used_fallback": False,
            "fallback_stage": "",
        }

    def draft_or_revise_chapter(self, chapter_number, **_kwargs):
        self.draft_calls += 1
        return {
            "chapter": {
                "number": chapter_number,
                "title": "Foundations",
                "content": "# Foundations\n\nDraft body.",
                "summary": "Draft summary.",
            },
            "metadata": {"draft_call": self.draft_calls},
            "next_steps": ["Review"],
            "used_fallback": False,
            "fallback_stage": "",
        }

    def review_chapter(self, **_kwargs):
        self.review_calls += 1
        return {
            "review": {
                "score": 65,
                "should_revise": True,
                "issues": ["Needs more depth"],
                "critique": "Add stronger examples and continuity links.",
            },
            "used_fallback": False,
            "fallback_stage": "",
        }


class _HighScoreExplicitReviseLLM(_FakeLLM):
    def draft_or_revise_chapter(self, chapter_number, **_kwargs):
        self.draft_calls += 1
        long_text = "word " * 1300
        return {
            "chapter": {
                "number": chapter_number,
                "title": "Foundations",
                "content": f"# Foundations\n\n## Core Section\n\n{long_text}",
                "summary": "Draft summary.",
            },
            "metadata": {"draft_call": self.draft_calls},
            "next_steps": ["Review"],
            "used_fallback": False,
            "fallback_stage": "",
        }

    def review_chapter(self, **_kwargs):
        self.review_calls += 1
        return {
            "review": {
                "score": 95,
                "should_revise": True,
                "issues": [],
                "critique": "Tighten argument and examples.",
            },
            "used_fallback": False,
            "fallback_stage": "",
        }


class _GuardrailDrivenLLM(_FakeLLM):
    def draft_or_revise_chapter(self, chapter_number, **_kwargs):
        self.draft_calls += 1
        return {
            "chapter": {
                "number": chapter_number,
                "title": "Foundations",
                "content": "# Foundations\n\nVery short draft without required section markers.",
                "summary": "Short summary.",
            },
            "metadata": {"draft_call": self.draft_calls},
            "next_steps": ["Review"],
            "used_fallback": False,
            "fallback_stage": "",
        }

    def review_chapter(self, **_kwargs):
        self.review_calls += 1
        return {
            "review": {
                "score": 95,
                "should_revise": False,
                "issues": [],
                "critique": "",
            },
            "used_fallback": False,
            "fallback_stage": "",
        }


class _FallbackStageLLM(_FakeLLM):
    def plan_chapter(self, **kwargs):
        self.plan_calls += 1
        return {
            "plan": {
                "chapter_number": kwargs["chapter_number"],
                "chapter_title": "Foundations",
                "objective": "Teach the core concept.",
                "sections": [{"heading": "Core", "purpose": "Explain basics", "evidence_or_example": "Simple case"}],
                "continuity_notes": [],
                "concept_alignment": "High",
            },
            "used_fallback": True,
            "fallback_stage": "chapter_plan",
        }

    def draft_or_revise_chapter(self, chapter_number, **_kwargs):
        self.draft_calls += 1
        long_text = "word " * 1300
        return {
            "chapter": {
                "number": chapter_number,
                "title": "Foundations",
                "content": f"# Foundations\n\n## Section\n\n{long_text}",
                "summary": "Draft summary.",
            },
            "metadata": {"draft_call": self.draft_calls},
            "next_steps": ["Review"],
            "used_fallback": False,
            "fallback_stage": "",
        }

    def review_chapter(self, **_kwargs):
        self.review_calls += 1
        return {
            "review": {
                "score": 90,
                "should_revise": False,
                "issues": [],
                "critique": "",
            },
            "used_fallback": True,
            "fallback_stage": "chapter_review",
        }


class _ProfileComplianceDrivenLLM(_FakeLLM):
    def draft_or_revise_chapter(self, chapter_number, **_kwargs):
        self.draft_calls += 1
        # Intentionally avoids second-person pronouns to trigger POV compliance checks.
        long_text = ("students explore models and practice reasoning with guided examples. " * 170).strip()
        return {
            "chapter": {
                "number": chapter_number,
                "title": "Foundations",
                "content": f"# Foundations\n\n## Core Section\n\n{long_text}",
                "summary": "Draft summary.",
            },
            "metadata": {"draft_call": self.draft_calls},
            "next_steps": ["Review"],
            "used_fallback": False,
            "fallback_stage": "",
        }

    def review_chapter(self, **_kwargs):
        self.review_calls += 1
        return {
            "review": {
                "score": 95,
                "should_revise": False,
                "issues": [],
                "critique": "",
            },
            "used_fallback": False,
            "fallback_stage": "",
        }


class _FakeWorkflow:
    def __init__(self, llm=None) -> None:
        self.llm = llm or _FakeLLM()
        self.persist_calls = 0

    def prepare_chapter_context(self, _project, _inputs):
        return {
            "outline": {
                "synopsis": "Test",
                "chapters": [{"number": 1, "title": "Foundations", "bullet_points": ["Core idea"]}],
            },
            "chapter_number": 1,
            "target": {"number": 1, "title": "Foundations", "bullet_points": ["Core idea"]},
            "memory_context": ["prior continuity"],
            "knowledge_context": ["kb fact"],
        }

    def persist_chapter_result(
        self,
        *,
        project,
        outline,
        chapter_number,
        target,
        chapter_data,
        metadata,
        next_steps,
    ):
        self.persist_calls += 1
        return {
            "status": "success",
            "outline": outline,
            "chapter": {
                "number": chapter_number,
                "title": chapter_data.get("title") or target.get("title"),
                "content": chapter_data.get("content", ""),
                "summary": chapter_data.get("summary", ""),
            },
            "metadata": metadata,
            "next_steps": next_steps or ["Review"],
            "project_id": str(project.id),
        }


class ChapterGraphTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="graph_user", password="pass12345")
        self.project = BookProject.objects.create(
            owner=self.user,
            title="Graph Book",
            genre="Education",
            target_audience="Beginners",
            language="English",
            tone="Instructional",
            target_word_count=3000,
        )

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_review_loop_stops_after_max_two_revisions(self, _mock_store_cls):
        orchestrator = AgentOrchestrator()
        fake_workflow = _FakeWorkflow()
        orchestrator.workflow = fake_workflow

        run = AgentRun(project=self.project, mode="chapter", input_payload={"chapter_number": 1})
        output = orchestrator.execute(run)

        self.assertEqual(fake_workflow.llm.plan_calls, 1)
        self.assertEqual(fake_workflow.llm.draft_calls, 3)
        self.assertEqual(fake_workflow.llm.review_calls, 3)
        self.assertEqual(fake_workflow.persist_calls, 1)
        self.assertEqual(output.get("status"), "success")
        self.assertEqual(output.get("chapter", {}).get("number"), 1)
        self.assertIn("progress", output)
        self.assertIn("timings_ms", output)
        self.assertIn("run_chapter_ms", output.get("timings_ms", {}).get("nodes", {}))

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_explicit_should_revise_true_forces_revision_even_high_score(self, _mock_store_cls):
        orchestrator = AgentOrchestrator()
        fake_workflow = _FakeWorkflow(llm=_HighScoreExplicitReviseLLM())
        orchestrator.workflow = fake_workflow

        run = AgentRun(project=self.project, mode="chapter", input_payload={"chapter_number": 1})
        output = orchestrator.execute(run)

        self.assertEqual(fake_workflow.llm.draft_calls, 3)
        self.assertEqual(fake_workflow.llm.review_calls, 3)
        self.assertEqual(fake_workflow.persist_calls, 1)
        self.assertEqual(output.get("progress", {}).get("revision_count"), 2)

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_guardrails_trigger_revision_with_high_score_and_false_should_revise(self, _mock_store_cls):
        orchestrator = AgentOrchestrator()
        fake_workflow = _FakeWorkflow(llm=_GuardrailDrivenLLM())
        orchestrator.workflow = fake_workflow

        run = AgentRun(project=self.project, mode="chapter", input_payload={"chapter_number": 1})
        output = orchestrator.execute(run)

        self.assertEqual(fake_workflow.llm.draft_calls, 3)
        self.assertEqual(fake_workflow.llm.review_calls, 3)
        self.assertEqual(fake_workflow.persist_calls, 1)
        review_meta = output.get("metadata", {}).get("review", {})
        self.assertTrue(review_meta.get("guardrail_fail"))
        self.assertTrue(review_meta.get("effective_should_revise"))

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_fallback_stages_aggregate_from_chapter_nodes(self, _mock_store_cls):
        orchestrator = AgentOrchestrator()
        fake_workflow = _FakeWorkflow(llm=_FallbackStageLLM())
        orchestrator.workflow = fake_workflow

        run = AgentRun(project=self.project, mode="chapter", input_payload={"chapter_number": 1})
        output = orchestrator.execute(run)

        self.assertTrue(output.get("used_fallback"))
        self.assertEqual(output.get("fallback_stages"), ["chapter_plan", "chapter_review"])

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_profile_compliance_guardrails_trigger_revision_for_pov_drift(self, _mock_store_cls):
        self.project.metadata_json = {
            "user_concept": {
                "profile": {
                    "pointOfView": "Second Person",
                    "chapterLength": "Short ~1500w",
                }
            }
        }
        self.project.save(update_fields=["metadata_json"])

        orchestrator = AgentOrchestrator()
        fake_workflow = _FakeWorkflow(llm=_ProfileComplianceDrivenLLM())
        orchestrator.workflow = fake_workflow

        run = AgentRun(project=self.project, mode="chapter", input_payload={"chapter_number": 1})
        output = orchestrator.execute(run)

        self.assertEqual(fake_workflow.llm.draft_calls, 3)
        self.assertEqual(fake_workflow.llm.review_calls, 3)
        review_meta = output.get("metadata", {}).get("review", {})
        self.assertTrue(review_meta.get("profile_compliance_fail"))
        self.assertTrue(review_meta.get("guardrail_fail"))
        self.assertTrue(review_meta.get("effective_should_revise"))
        self.assertIn("profile_compliance", review_meta)
        issues = review_meta.get("profile_compliance_issues", [])
        self.assertTrue(any("second-person voice" in str(issue).lower() for issue in issues))

    @patch("apps.books.services.pipeline.VectorMemoryStore")
    def test_word_guardrails_allow_flexible_length_by_chapter_complexity(self, _mock_store_cls):
        self.project.metadata_json = {
            "user_concept": {
                "profile": {
                    "chapterLength": "Short ~1500w",
                }
            }
        }
        self.project.save(update_fields=["metadata_json"])

        orchestrator = AgentOrchestrator()
        target = {
            "number": 1,
            "title": "Complex Chapter",
            "bullet_points": [
                "Concept setup",
                "Core framework",
                "Worked example",
                "Counterexample",
                "Common mistakes",
                "Practice exercise",
            ],
        }
        content = "# Complex Chapter\n\n## Section\n\n" + ("word " * 2100)

        issues, word_count, minimum_word_count, guidance = orchestrator._review_guardrails(  # noqa: SLF001
            self.project,
            content,
            target=target,
        )

        self.assertGreater(word_count, 2000)  # heading tokens are included by the simple split-based counter
        self.assertLess(minimum_word_count, guidance["target"])
        self.assertEqual(guidance["bullet_count"], 6)
        self.assertFalse(any("below minimum" in issue.lower() for issue in issues))
        self.assertFalse(any("far above expected range" in issue.lower() for issue in issues))
