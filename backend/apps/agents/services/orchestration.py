from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from apps.books.models import BookProject
from apps.books.services.pipeline import BookWorkflowService

from ..models import AgentRun, RunMode

logger = logging.getLogger(__name__)

_MIN_WORDS_BY_CHAPTER_LENGTH = {
    "short": 900,
    "medium": 1800,
    "long": 3000,
    "default": 1200,
}


class WorkflowState(TypedDict, total=False):
    run_id: str
    trace_id: str
    project: BookProject
    mode: str
    inputs: Dict[str, Any]
    output: Dict[str, Any]
    progress: Dict[str, Any]
    node_timings: Dict[str, int]
    fallback_stages: List[str]
    outline: Dict[str, Any]
    chapter_number: int
    target: Dict[str, Any]
    memory_context: List[str]
    knowledge_context: List[str]
    chapter_plan: Dict[str, Any]
    chapter_draft: Dict[str, Any]
    chapter_metadata: Dict[str, Any]
    chapter_next_steps: List[str]
    review_result: Dict[str, Any]
    revision_count: int
    max_revisions: int


class AgentOrchestrator:
    """
    LangGraph-based orchestration for run modes.

    Top-level graph routes by mode. Chapter mode executes an internal subgraph:
    retrieve -> plan -> draft -> review loop -> persist.
    """

    def __init__(self) -> None:
        self.workflow = BookWorkflowService()
        self.graph = self._build_graph()
        self.chapter_graph = self._build_chapter_graph()

    def execute(self, run: AgentRun) -> Dict[str, Any]:
        t0 = time.perf_counter()
        state: WorkflowState = {
            "run_id": str(run.id),
            "trace_id": str(run.trace_id),
            "project": run.project,
            "mode": str(run.mode).strip(),
            "inputs": run.input_payload or {},
            "fallback_stages": [],
            "progress": {"current_node": "", "node_status": {}, "completed_nodes": [], "revision_count": 0},
            "node_timings": {},
        }
        final_state = self.graph.invoke(state)
        result = final_state.get("output", {}) if isinstance(final_state, dict) else {}
        if not isinstance(result, dict) or not result:
            raise ValueError("LangGraph execution returned invalid output payload")

        fallback_stages = final_state.get("fallback_stages", [])
        if not isinstance(fallback_stages, list):
            fallback_stages = []
        if "fallback_stages" not in result:
            result["fallback_stages"] = fallback_stages
        if "used_fallback" not in result:
            result["used_fallback"] = bool(result.get("fallback_stages"))

        progress = final_state.get("progress", {})
        if isinstance(progress, dict):
            result["progress"] = progress

        node_timings = final_state.get("node_timings", {})
        if not isinstance(node_timings, dict):
            node_timings = {}

        timings = {
            "total_ms": int((time.perf_counter() - t0) * 1000),
            "nodes": {str(k): int(v) for k, v in node_timings.items()},
        }
        result["timings_ms"] = timings
        return result

    def _build_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("run_toc", self._node_toc)
        graph.add_node("run_refine_toc", self._node_refine_toc)
        graph.add_node("run_chapter", self._node_chapter)
        graph.add_node("run_export", self._node_export)
        graph.add_node("run_profile_assistant", self._node_profile_assistant)

        graph.add_conditional_edges(
            START,
            self._route_mode,
            {
                "toc": "run_toc",
                "refine_toc": "run_refine_toc",
                "chapter": "run_chapter",
                "export": "run_export",
                "profile_assistant": "run_profile_assistant",
            },
        )
        graph.add_edge("run_toc", END)
        graph.add_edge("run_refine_toc", END)
        graph.add_edge("run_chapter", END)
        graph.add_edge("run_export", END)
        graph.add_edge("run_profile_assistant", END)
        return graph.compile()

    def _build_chapter_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("chapter_node_retrieve_context", self._chapter_node_retrieve_context)
        graph.add_node("chapter_node_plan", self._chapter_node_plan)
        graph.add_node("chapter_node_draft", self._chapter_node_draft)
        graph.add_node("chapter_node_review", self._chapter_node_review)
        graph.add_node("chapter_node_persist", self._chapter_node_persist)

        graph.add_edge(START, "chapter_node_retrieve_context")
        graph.add_edge("chapter_node_retrieve_context", "chapter_node_plan")
        graph.add_edge("chapter_node_plan", "chapter_node_draft")
        graph.add_edge("chapter_node_draft", "chapter_node_review")
        graph.add_conditional_edges(
            "chapter_node_review",
            self._chapter_route_review,
            {
                "revise": "chapter_node_draft",
                "persist": "chapter_node_persist",
            },
        )
        graph.add_edge("chapter_node_persist", END)
        return graph.compile()

    def _route_mode(self, state: WorkflowState) -> str:
        mode = str(state.get("mode", "")).strip().lower()
        if mode in {RunMode.TOC, RunMode.REFINE_TOC, RunMode.CHAPTER, RunMode.EXPORT, RunMode.PROFILE_ASSISTANT}:
            return mode
        raise ValueError("mode must be one of: toc | refine_toc | chapter | export | profile_assistant")

    def _node_toc(self, state: WorkflowState) -> WorkflowState:
        return self._execute_workflow_node(state, node_name="run_toc", mode="toc")

    def _node_refine_toc(self, state: WorkflowState) -> WorkflowState:
        return self._execute_workflow_node(state, node_name="run_refine_toc", mode="refine_toc")

    def _node_export(self, state: WorkflowState) -> WorkflowState:
        return self._execute_workflow_node(state, node_name="run_export", mode="export")

    def _node_profile_assistant(self, state: WorkflowState) -> WorkflowState:
        return self._execute_workflow_node(state, node_name="run_profile_assistant", mode="profile_assistant")

    def _execute_workflow_node(self, state: WorkflowState, node_name: str, mode: str) -> WorkflowState:
        project = self._require_project(state)
        started = self._mark_node_start(state, node_name)
        t0 = time.perf_counter()
        try:
            output = self.workflow.execute_mode(project=project, mode=mode, inputs=state.get("inputs", {}))
        except Exception as exc:
            self._mark_node_error(
                {
                    **state,
                    "progress": started["progress"],
                    "node_timings": started["node_timings"],
                },
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        fallback_stages = self._merge_fallback_stages(state.get("fallback_stages", []), output)
        output = self._with_fallback_output(output, fallback_stages)
        ended = self._mark_node_end(
            {
                **state,
                "progress": started["progress"],
                "node_timings": started["node_timings"],
            },
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
        )
        return {
            "output": output,
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _node_chapter(self, state: WorkflowState) -> WorkflowState:
        started = self._mark_node_start(state, "run_chapter")
        t0 = time.perf_counter()
        chapter_state: WorkflowState = {
            "run_id": str(state.get("run_id", "")),
            "trace_id": str(state.get("trace_id", "")),
            "project": self._require_project(state),
            "inputs": state.get("inputs", {}),
            "revision_count": 0,
            "max_revisions": 2,
            "fallback_stages": list(state.get("fallback_stages", [])) if isinstance(state.get("fallback_stages"), list) else [],
            "progress": started["progress"],
            "node_timings": started["node_timings"],
        }
        try:
            final_state = self.chapter_graph.invoke(chapter_state)
        except Exception as exc:
            self._mark_node_error(
                {
                    **state,
                    "progress": started["progress"],
                    "node_timings": started["node_timings"],
                    "revision_count": int(chapter_state.get("revision_count", 0)),
                },
                node_name="run_chapter",
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        output = final_state.get("output", {}) if isinstance(final_state, dict) else {}
        if not isinstance(output, dict) or not output:
            self._mark_node_error(
                {
                    **state,
                    "progress": final_state.get("progress", started["progress"]) if isinstance(final_state, dict) else started["progress"],
                    "node_timings": final_state.get("node_timings", started["node_timings"]) if isinstance(final_state, dict) else started["node_timings"],
                    "revision_count": int(final_state.get("revision_count", 0)) if isinstance(final_state, dict) else 0,
                },
                node_name="run_chapter",
                error=ValueError("Chapter graph returned invalid output payload"),
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise ValueError("Chapter graph returned invalid output payload")
        fallback_stages = final_state.get("fallback_stages", [])
        if not isinstance(fallback_stages, list):
            fallback_stages = []
        output = self._with_fallback_output(output, fallback_stages)

        ended = self._mark_node_end(
            {
                **state,
                "progress": final_state.get("progress", started["progress"]),
                "node_timings": final_state.get("node_timings", started["node_timings"]),
                "revision_count": int(final_state.get("revision_count", 0)),
            },
            node_name="run_chapter",
            node_ms=int((time.perf_counter() - t0) * 1000),
            optional_meta={"revision_count": int(final_state.get("revision_count", 0))},
            revision_count=int(final_state.get("revision_count", 0)),
        )
        return {
            "output": output,
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
            "revision_count": int(final_state.get("revision_count", 0)),
        }

    def _chapter_node_retrieve_context(self, state: WorkflowState) -> WorkflowState:
        node_name = "chapter_retrieve_context"
        started = self._mark_node_start(state, node_name)
        t0 = time.perf_counter()
        project = self._require_project(state)
        try:
            chapter_ctx = self.workflow.prepare_chapter_context(project, state.get("inputs", {}))
        except Exception as exc:
            self._mark_node_error(
                {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        ended = self._mark_node_end(
            {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
        )
        return {
            "outline": chapter_ctx["outline"],
            "chapter_number": chapter_ctx["chapter_number"],
            "target": chapter_ctx["target"],
            "memory_context": chapter_ctx["memory_context"],
            "knowledge_context": chapter_ctx["knowledge_context"],
            "review_result": {},
            "revision_count": int(state.get("revision_count", 0)),
            "max_revisions": int(state.get("max_revisions", 2)),
            "fallback_stages": state.get("fallback_stages", []),
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _chapter_node_plan(self, state: WorkflowState) -> WorkflowState:
        node_name = "chapter_plan"
        started = self._mark_node_start(state, node_name)
        t0 = time.perf_counter()
        project = self._require_project(state)
        try:
            plan_payload = self.workflow.llm.plan_chapter(
                project=project,
                outline=state.get("outline", {}),
                chapter_number=int(state.get("chapter_number", 0)),
                memory_context=state.get("memory_context", []),
                knowledge_context=state.get("knowledge_context", []),
            )
        except Exception as exc:
            self._mark_node_error(
                {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        fallback_stages = self._merge_fallback_stages(state.get("fallback_stages", []), plan_payload)
        ended = self._mark_node_end(
            {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
            optional_meta={
                "used_fallback": bool(plan_payload.get("used_fallback")) if isinstance(plan_payload, dict) else False,
            },
        )
        return {
            "chapter_plan": plan_payload.get("plan", {}) if isinstance(plan_payload, dict) else {},
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _chapter_node_draft(self, state: WorkflowState) -> WorkflowState:
        node_name = "chapter_draft"
        started = self._mark_node_start(state, node_name)
        t0 = time.perf_counter()
        project = self._require_project(state)

        review_result = state.get("review_result", {})
        critique = ""
        if isinstance(review_result, dict):
            critique = str(review_result.get("critique", "")).strip()
        previous_draft = ""
        chapter_draft = state.get("chapter_draft", {})
        if isinstance(chapter_draft, dict):
            previous_draft = str(chapter_draft.get("content", "")).strip()

        try:
            draft_payload = self.workflow.llm.draft_or_revise_chapter(
                project=project,
                outline=state.get("outline", {}),
                chapter_number=int(state.get("chapter_number", 0)),
                chapter_plan=state.get("chapter_plan", {}),
                memory_context=state.get("memory_context", []),
                knowledge_context=state.get("knowledge_context", []),
                critique=critique,
                previous_draft=previous_draft,
            )
        except Exception as exc:
            self._mark_node_error(
                {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        revision_count = int(state.get("revision_count", 0))
        if critique:
            revision_count += 1
        fallback_stages = self._merge_fallback_stages(state.get("fallback_stages", []), draft_payload)

        ended = self._mark_node_end(
            {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
            optional_meta={
                "used_fallback": bool(draft_payload.get("used_fallback")) if isinstance(draft_payload, dict) else False,
            },
            revision_count=revision_count,
        )
        return {
            "chapter_draft": draft_payload.get("chapter", {}) if isinstance(draft_payload, dict) else {},
            "chapter_metadata": draft_payload.get("metadata", {}) if isinstance(draft_payload, dict) else {},
            "chapter_next_steps": draft_payload.get("next_steps", []) if isinstance(draft_payload, dict) else [],
            "revision_count": revision_count,
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _chapter_node_review(self, state: WorkflowState) -> WorkflowState:
        node_name = "chapter_review"
        started = self._mark_node_start(state, node_name)
        t0 = time.perf_counter()
        project = self._require_project(state)
        chapter_draft = state.get("chapter_draft", {})
        content = str(chapter_draft.get("content", "")).strip() if isinstance(chapter_draft, dict) else ""

        try:
            review_payload = self.workflow.llm.review_chapter(
                project=project,
                outline=state.get("outline", {}),
                chapter_number=int(state.get("chapter_number", 0)),
                chapter_plan=state.get("chapter_plan", {}),
                chapter_content=content,
                memory_context=state.get("memory_context", []),
                knowledge_context=state.get("knowledge_context", []),
            )
        except Exception as exc:
            self._mark_node_error(
                {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise

        review = review_payload.get("review", {}) if isinstance(review_payload, dict) else {}
        if not isinstance(review, dict):
            review = {}

        try:
            score = max(0, min(100, int(float(str(review.get("score", 0))))))
        except Exception:
            score = 0
        explicit_should_revise = bool(review.get("should_revise"))
        existing_issues = review.get("issues", [])
        issues: List[str] = [str(i).strip() for i in existing_issues if str(i).strip()] if isinstance(existing_issues, list) else []
        critique = str(review.get("critique", "")).strip()

        guardrail_issues, word_count, minimum_word_count = self._review_guardrails(project, content)
        for issue in guardrail_issues:
            if issue not in issues:
                issues.append(issue)
        guardrail_fail = bool(guardrail_issues)
        effective_should_revise = explicit_should_revise or score < 80 or guardrail_fail
        if effective_should_revise and not critique:
            critique = "Revise for stronger concept alignment, add depth, and improve section structure."

        review["score"] = score
        review["should_revise"] = explicit_should_revise
        review["effective_should_revise"] = effective_should_revise
        review["guardrail_fail"] = guardrail_fail
        review["guardrail_issues"] = guardrail_issues
        review["word_count"] = word_count
        review["minimum_word_count"] = minimum_word_count
        review["issues"] = issues
        review["critique"] = critique

        fallback_stages = self._merge_fallback_stages(state.get("fallback_stages", []), review_payload)
        ended = self._mark_node_end(
            {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
            optional_meta={
                "score": score,
                "effective_should_revise": effective_should_revise,
                "used_fallback": bool(review_payload.get("used_fallback")) if isinstance(review_payload, dict) else False,
            },
            revision_count=int(state.get("revision_count", 0)),
        )
        return {
            "review_result": review,
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _chapter_route_review(self, state: WorkflowState) -> str:
        review = state.get("review_result", {})
        if isinstance(review, dict):
            effective = bool(review.get("effective_should_revise"))
            if not effective:
                try:
                    score = max(0, min(100, int(float(str(review.get("score", 0))))))
                except Exception:
                    score = 0
                effective = bool(review.get("should_revise")) or score < 80 or bool(review.get("guardrail_fail"))
        else:
            effective = False

        revision_count = int(state.get("revision_count", 0))
        max_revisions = int(state.get("max_revisions", 2))
        if effective and revision_count < max_revisions:
            return "revise"
        return "persist"

    def _chapter_node_persist(self, state: WorkflowState) -> WorkflowState:
        node_name = "chapter_persist"
        started = self._mark_node_start(state, node_name, revision_count=int(state.get("revision_count", 0)))
        t0 = time.perf_counter()
        project = self._require_project(state)
        metadata = state.get("chapter_metadata", {})
        combined_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        combined_metadata["review"] = state.get("review_result", {})

        try:
            output = self.workflow.persist_chapter_result(
                project=project,
                outline=state.get("outline", {}),
                chapter_number=int(state.get("chapter_number", 0)),
                target=state.get("target", {}),
                chapter_data=state.get("chapter_draft", {}),
                metadata=combined_metadata,
                next_steps=state.get("chapter_next_steps", []),
            )
        except Exception as exc:
            self._mark_node_error(
                {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
                node_name=node_name,
                error=exc,
                node_ms=int((time.perf_counter() - t0) * 1000),
                revision_count=int(state.get("revision_count", 0)),
            )
            raise

        fallback_stages = list(state.get("fallback_stages", [])) if isinstance(state.get("fallback_stages"), list) else []
        output = self._with_fallback_output(output, fallback_stages)

        ended = self._mark_node_end(
            {**state, "progress": started["progress"], "node_timings": started["node_timings"]},
            node_name=node_name,
            node_ms=int((time.perf_counter() - t0) * 1000),
            optional_meta={"revision_count": int(state.get("revision_count", 0))},
            revision_count=int(state.get("revision_count", 0)),
        )
        return {
            "output": output,
            "fallback_stages": fallback_stages,
            "progress": ended["progress"],
            "node_timings": ended["node_timings"],
        }

    def _mark_node_start(
        self,
        state: WorkflowState,
        node_name: str,
        revision_count: int | None = None,
    ) -> Dict[str, Any]:
        progress = self._copy_progress(state)
        if revision_count is None:
            revision_count = int(state.get("revision_count", progress.get("revision_count", 0)))
        progress["current_node"] = node_name
        progress["node_status"][node_name] = "running"
        progress["revision_count"] = revision_count
        node_timings = self._copy_node_timings(state)
        self._persist_run_telemetry(
            run_id=str(state.get("run_id", "")),
            progress=progress,
            node_timings=node_timings,
        )
        return {"progress": progress, "node_timings": node_timings}

    def _mark_node_end(
        self,
        state: WorkflowState,
        node_name: str,
        node_ms: int,
        optional_meta: Dict[str, Any] | None = None,
        revision_count: int | None = None,
    ) -> Dict[str, Any]:
        progress = self._copy_progress(state)
        if revision_count is None:
            revision_count = int(state.get("revision_count", progress.get("revision_count", 0)))
        progress["current_node"] = node_name
        progress["node_status"][node_name] = "completed"
        completed = list(progress.get("completed_nodes", []))
        if node_name not in completed:
            completed.append(node_name)
        progress["completed_nodes"] = completed
        progress["revision_count"] = revision_count
        if optional_meta:
            node_meta = progress.get("node_meta", {})
            if not isinstance(node_meta, dict):
                node_meta = {}
            node_meta[node_name] = optional_meta
            progress["node_meta"] = node_meta

        node_timings = self._copy_node_timings(state)
        node_timings[f"{node_name}_ms"] = int(node_ms)
        self._persist_run_telemetry(
            run_id=str(state.get("run_id", "")),
            progress=progress,
            node_timings=node_timings,
        )
        return {"progress": progress, "node_timings": node_timings}

    def _mark_node_error(
        self,
        state: WorkflowState,
        node_name: str,
        error: Exception,
        node_ms: int | None = None,
        revision_count: int | None = None,
    ) -> Dict[str, Any]:
        progress = self._copy_progress(state)
        if revision_count is None:
            revision_count = int(state.get("revision_count", progress.get("revision_count", 0)))
        progress["current_node"] = node_name
        progress["node_status"][node_name] = "failed"
        progress["revision_count"] = revision_count
        progress["last_error"] = str(error)[:500]
        node_timings = self._copy_node_timings(state)
        if node_ms is not None:
            node_timings[f"{node_name}_ms"] = int(node_ms)
        self._persist_run_telemetry(
            run_id=str(state.get("run_id", "")),
            progress=progress,
            node_timings=node_timings,
        )
        logger.warning("Workflow node failed: %s", node_name, exc_info=True)
        return {"progress": progress, "node_timings": node_timings}

    def _persist_run_telemetry(self, run_id: str, progress: Dict[str, Any], node_timings: Dict[str, int]) -> None:
        if not run_id:
            return
        try:
            run = AgentRun.objects.filter(id=run_id).first()
            if run is None:
                return
            output_payload = run.output_payload if isinstance(run.output_payload, dict) else {}
            timings_json = run.timings_json if isinstance(run.timings_json, dict) else {}
            output_payload["progress"] = progress
            timings_nodes = timings_json.get("nodes", {})
            if not isinstance(timings_nodes, dict):
                timings_nodes = {}
            for key, value in node_timings.items():
                timings_nodes[str(key)] = int(value)
            timings_json["nodes"] = timings_nodes
            run.output_payload = output_payload
            run.timings_json = timings_json
            run.save(update_fields=["output_payload", "timings_json"])
        except Exception:
            logger.warning("Failed to persist run node telemetry", exc_info=True)

    def _copy_progress(self, state: WorkflowState) -> Dict[str, Any]:
        raw = state.get("progress", {})
        progress = dict(raw) if isinstance(raw, dict) else {}
        node_status = progress.get("node_status", {})
        progress["node_status"] = dict(node_status) if isinstance(node_status, dict) else {}
        completed_nodes = progress.get("completed_nodes", [])
        progress["completed_nodes"] = [str(node) for node in completed_nodes] if isinstance(completed_nodes, list) else []
        if "revision_count" not in progress:
            progress["revision_count"] = int(state.get("revision_count", 0))
        return progress

    def _copy_node_timings(self, state: WorkflowState) -> Dict[str, int]:
        raw = state.get("node_timings", {})
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, int] = {}
        for key, value in raw.items():
            try:
                out[str(key)] = int(value)
            except Exception:
                continue
        return out

    def _merge_fallback_stages(self, existing: Any, payload: Any) -> List[str]:
        stages: List[str] = []
        if isinstance(existing, list):
            for item in existing:
                text = str(item).strip()
                if text and text not in stages:
                    stages.append(text)
        if isinstance(payload, dict):
            payload_stages = payload.get("fallback_stages", [])
            if isinstance(payload_stages, list):
                for item in payload_stages:
                    text = str(item).strip()
                    if text and text not in stages:
                        stages.append(text)
            if bool(payload.get("used_fallback")):
                stage = str(payload.get("fallback_stage", "")).strip()
                if stage and stage not in stages:
                    stages.append(stage)
        return stages

    def _with_fallback_output(self, output: Any, fallback_stages: List[str]) -> Dict[str, Any]:
        out = dict(output) if isinstance(output, dict) else {}
        out["fallback_stages"] = list(fallback_stages)
        out["used_fallback"] = bool(fallback_stages)
        return out

    def _review_guardrails(self, project: BookProject, content: str) -> tuple[List[str], int, int]:
        text = str(content or "").strip()
        word_count = len([token for token in text.split() if token.strip()])
        minimum_word_count = self._minimum_word_count_for_project(project)
        issues: List[str] = []
        if not text:
            issues.append("Chapter content is empty.")
        if "## " not in text:
            issues.append("Chapter is missing at least one '##' section heading.")
        if word_count < minimum_word_count:
            issues.append(f"Chapter word count {word_count} is below minimum {minimum_word_count}.")
        return issues, word_count, minimum_word_count

    def _minimum_word_count_for_project(self, project: BookProject) -> int:
        profile = self._project_profile(project)
        chapter_length = str(profile.get("chapterLength", "")).strip().lower()
        key = "default"
        if "short" in chapter_length:
            key = "short"
        elif "medium" in chapter_length:
            key = "medium"
        elif "long" in chapter_length:
            key = "long"
        return _MIN_WORDS_BY_CHAPTER_LENGTH[key]

    def _project_profile(self, project: BookProject) -> Dict[str, Any]:
        metadata = project.metadata_json if isinstance(project.metadata_json, dict) else {}
        user_concept = metadata.get("user_concept", {})
        if isinstance(user_concept, dict):
            profile = user_concept.get("profile", {})
            if isinstance(profile, dict):
                return profile
        legacy_profile = metadata.get("profile", {})
        return legacy_profile if isinstance(legacy_profile, dict) else {}

    def _require_project(self, state: WorkflowState) -> BookProject:
        project = state.get("project")
        if not isinstance(project, BookProject):
            raise ValueError("project is required in workflow state")
        return project
