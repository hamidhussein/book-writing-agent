# Book Writing Agent - System Architecture and Runtime

This document describes the implemented architecture, runtime flow, data model, and operational behavior of the project as it exists in code.

## 1) Product Goal

Build an agentic book-writing studio where a user can:

1. Define concept and writing profile.
2. Generate and refine a full outline.
3. Generate chapters with continuity and retrieval grounding.
4. Iterate with review and revision loops.
5. Export manuscript to PDF/DOCX.

The system supports both:

1. Manual form-driven setup.
2. Chat-assisted profile capture with explicit finalize confirmation.

## 2) High-Level Architecture

The system has three layers:

1. Frontend Studio (`React + TypeScript + Vite + Tailwind`).
2. Backend API and orchestration (`Django + DRF + Celery + LangGraph`).
3. Storage and retrieval (`SQLite + Qdrant + Redis`).

Core services:

1. LLM generation service (`OpenAI` via Python SDK).
2. Vector memory service (`Qdrant`).
3. Background execution (`Celery` + `Redis`).

## 3) Repository Layout

1. `frontend/`: Studio UI and run orchestration client logic.
2. `backend/apps/books/`: Book domain models, APIs, LLM, retrieval, exports.
3. `backend/apps/agents/`: Agent runs, orchestration graph, async task execution.
4. `docker-compose.yml`: Local infra (backend, worker, redis, qdrant).

## 4) End-to-End Runtime Flow

### Step A: User edits concept/profile

1. UI state lives in `frontend/src/pages/BookStudioPage.tsx`.
2. State autosaves in browser localStorage (`book_agent_ui_state_v3`).
3. Before generation, frontend ensures a backend `BookProject` exists via create/patch.
4. Project metadata is sent in two-zone shape:
   1. `metadata_json.user_concept` (protected user snapshot).
   2. `metadata_json.llm_runtime` (mutable runtime zone).
5. Legacy mirrors are still included for compatibility:
   1. `metadata_json.profile`
   2. `metadata_json.subtitle`
   3. `metadata_json.instruction_brief`

### Step B: User triggers a run

1. Frontend posts `POST /api/agents/runs/` with:
   1. `project_id`
   2. `mode` (`toc`, `refine_toc`, `chapter`, `export`)
   3. `inputs`
2. Frontend currently defaults to sync execution (`?sync=1`) when `VITE_FORCE_SYNC_RUNS` is not set to `0`.
3. Backend creates an `AgentRun` in `queued`.
4. Backend execution path:
   1. Sync: request thread runs orchestration immediately.
   2. Async: Celery task `execute_agent_run` executes run.

### Step C: Run completion and polling

1. Frontend polls `GET /api/agents/runs/{id}/` while status is `queued` or `running`.
2. Poll interval: `1200ms`.
3. Timeout policy:
   1. Chapter mode: `480s`.
   2. Other modes: `240s`.
4. Header status card surfaces:
   1. Current stage (`output_payload.progress.current_node`).
   2. Revision count (`output_payload.progress.revision_count`).
   3. Fallback usage and stages.

### Step D: Legacy fallback

1. If async run endpoints return `404`, frontend attempts legacy execute endpoint fallback.
2. In current backend, the primary supported interface is `/api/agents/runs/*`.

## 5) LangGraph Orchestration

`AgentOrchestrator` is implemented as a real `StateGraph` with:

1. Top-level router graph by mode.
2. Dedicated chapter subgraph with revision loop.
3. Run-level telemetry writes per node.

### Workflow state

`WorkflowState` includes:

1. `run_id`, `trace_id`
2. `project`, `mode`, `inputs`
3. `output`
4. `progress` and `node_timings`
5. `fallback_stages`
6. Chapter-specific state:
   1. `outline`, `chapter_number`, `target`
   2. `memory_context`, `knowledge_context`
   3. `chapter_plan`, `chapter_draft`
   4. `review_result`
   5. `revision_count`, `max_revisions`

### Top-level graph

1. `START`
2. Conditional route by `mode`
3. Nodes:
   1. `run_toc`
   2. `run_refine_toc`
   3. `run_chapter`
   4. `run_export`
4. `END`

### Chapter subgraph

1. `chapter_retrieve_context`
2. `chapter_plan`
3. `chapter_draft`
4. `chapter_review`
5. Conditional edge:
   1. `revise` back to `chapter_draft`
   2. `persist` to `chapter_persist`
6. `chapter_persist`

### Review and revise policy

`effective_should_revise` is computed as:

1. `review.should_revise` OR
2. `score < 80` OR
3. `guardrail_fail`

Guardrails:

1. Empty chapter content.
2. Missing `##` section heading.
3. Minimum words by chapter length profile:
   1. short: `900`
   2. medium: `1800`
   3. long: `3000`
   4. default: `1200`

Revision ceiling:

1. `max_revisions = 2`.

Persist behavior:

1. Persist/index runs once after review passes or revision cap reached.

### Node telemetry

Orchestrator writes node telemetry to existing `AgentRun` fields:

1. `output_payload.progress`
2. `timings_json.nodes.<node>_ms`

Progress write failures are logged and do not fail generation.

## 6) Book Workflow Service

`BookWorkflowService` handles mode-specific domain logic.

### `toc`

1. Retrieve KB context.
2. Call `LLMService.generate_outline`.
3. Normalize outline shape.
4. Merge metadata using two-zone policy:
   1. preserve `user_concept`
   2. update `llm_runtime`
5. Save project and create/sync chapter rows.

### `refine_toc`

1. Validate feedback.
2. Retrieve KB context.
3. Call `LLMService.refine_outline`.
4. Normalize outline and merge metadata with same two-zone policy.
5. Save project and sync chapters.

### `chapter`

1. Validate project outline and chapter number.
2. Retrieve continuity memory and KB context.
3. Generate chapter draft payload.
4. Persist chapter content.
5. Index chapter memory back into vector store.

In chapter mode, orchestration now executes this through subnodes (retrieve/plan/draft/review/persist) instead of one opaque call.

### `export`

1. Validate outline and generated chapters.
2. Render PDF (`reportlab`) and/or DOCX (`python-docx`).
3. Return base64 payloads and filenames.
4. Mark project exported.

## 7) LLM Service Design

`LLMService` centralizes prompting, schema enforcement, and fallbacks.

Implemented methods:

1. `generate_outline`
2. `refine_outline`
3. `generate_chapter`
4. `plan_chapter`
5. `draft_or_revise_chapter`
6. `review_chapter`
7. `assist_profile`
8. `embed`

### Model policy

1. Primary generation: `OPENAI_MODEL`.
2. Planner/reviewer: `OPENAI_FAST_MODEL`.
3. Embeddings: `OPENAI_EMBED_MODEL`.
4. Image model config exists (`OPENAI_IMAGE_MODEL`) but is not currently part of the core writing pipeline flow.

### Reliability and fallback telemetry

On LLM failure/unavailability, deterministic fallbacks are returned with runtime markers:

1. `used_fallback: true|false`
2. `fallback_stage` (stage-local)
3. Orchestrator aggregates to run-level:
   1. `used_fallback`
   2. `fallback_stages[]`

### Assistant normalization safeguards

Profile assistant normalization includes:

1. Required field checks.
2. Finalize intent parsing.
3. Title validity checks (reject placeholders like `untitled`, `hi`, etc.).
4. Title grounding checks to avoid ungrounded title drift.
5. Finalize allowed only when all required fields are present.

## 8) Knowledge Base and Vector Retrieval

### Ingestion

Sources can be added as:

1. Manual text notes.
2. File uploads (`.txt`, `.md`, `.pdf`, `.docx`; `.doc` rejected with conversion guidance).

Flow:

1. Extract text.
2. Normalize text.
3. Chunk text.
4. Embed chunks.
5. Upsert as `memory_type = kb`.

### Priority-aware payload and rerank

Each KB chunk stores:

1. `source_priority_label`
2. `source_priority_weight`

Priority map:

1. `primary = 5`
2. `supporting = 3`
3. `tone-only = 1`
4. default = `supporting`

Retrieval rerank:

1. `final_score = semantic_score * (1 + 0.2 * priority_weight)`
2. Sort by `final_score` descending before context assembly.

### Memory types

1. `kb`: user-provided knowledge/reference chunks.
2. `chapter`: generated chapter continuity memory.

## 9) Profile Assistant and Concept Capture

### Backend behavior

`POST /api/books/projects/{id}/profile-assistant/`:

1. Returns:
   1. `assistant_reply`
   2. `field_updates`
   3. `next_field`
   4. `is_finalized`
   5. `missing_required`
2. Applies updates to project only when `is_finalized = true`.

### Frontend behavior

1. Assistant messages are conversational and step-focused.
2. Quick-choice chips are shown based on `next_field`.
3. User finalizes by typing `finalize`.
4. On finalize:
   1. Fields apply locally immediately.
   2. Background `ensureProject(...)` sync runs (non-blocking).

## 10) Security and Multi-User Isolation

### Authentication

1. `rest_framework.authtoken` enabled.
2. DRF defaults:
   1. `IsAuthenticated`
   2. `TokenAuthentication`
3. Token endpoint:
   1. `POST /api/auth/token/`

### Ownership model

1. `BookProject.owner` foreign key to `auth.User` (nullable for legacy rows).
2. Querysets are owner-scoped in books and agents viewsets.
3. Serializer validation prevents runs/chapters/sources against foreign projects.

## 11) Data Model

### `BookProject`

1. Identity + profile fields.
2. `owner`
3. `outline_json`
4. `metadata_json` (two-zone logical schema)
5. lifecycle status

### `Chapter`

1. `project`, `number`, `title`, `content`, `summary`
2. status
3. `vector_indexed`

### `SourceDocument`

1. `project`, `title`, `source_type`, `content`
2. `metadata_json` (includes ingest metadata + priority)

### `AgentRun`

1. `project`, `trace_id`, `mode`, `status`
2. `input_payload`, `output_payload`, `timings_json`, `error_message`
3. timestamps: created/started/finished

## 12) API Surface

### Health

1. `GET /api/health/`

### Auth

1. `POST /api/auth/token/`

### Books

1. `GET,POST /api/books/projects/`
2. `GET,PATCH,DELETE /api/books/projects/{id}/`
3. `GET,POST /api/books/projects/{id}/chapters/`
4. `GET,POST /api/books/projects/{id}/sources/`
5. `POST /api/books/projects/{id}/knowledge-upload/`
6. `POST /api/books/projects/{id}/profile-assistant/`
7. `GET,POST /api/books/chapters/`
8. `GET,PATCH,DELETE /api/books/chapters/{id}/`
9. `GET,POST /api/books/sources/`
10. `GET,PATCH,DELETE /api/books/sources/{id}/`

### Agents

1. `POST /api/agents/runs/`
2. `GET /api/agents/runs/`
3. `GET /api/agents/runs/{id}/`

## 13) Frontend Studio Behavior

Primary screens:

1. Concept
2. Outline
3. Drafting
4. Export

Implemented UX/runtime behavior:

1. TSX is source of truth (`noEmit: true`; generated JS/DTS twins removed).
2. API auth header from `VITE_API_TOKEN`.
3. Run status card shows transport, trace, stage, revision count, fallback markers.
4. Chapter run timeout extended to avoid premature timeout during review loops.
5. `Reset Studio` button:
   1. Clears local autosave.
   2. Attempts backend project delete if linked.
   3. Resets UI state to defaults.

## 14) Configuration

### Backend (`backend/.env`)

1. OpenAI:
   1. `OPENAI_API_KEY`
   2. `OPENAI_MODEL`
   3. `OPENAI_FAST_MODEL`
   4. `OPENAI_EMBED_MODEL`
   5. `OPENAI_IMAGE_MODEL`
2. Qdrant:
   1. `QDRANT_URL`
   2. `QDRANT_API_KEY`
   3. `QDRANT_COLLECTION`
3. Celery/Redis:
   1. `CELERY_BROKER_URL`
   2. `CELERY_RESULT_BACKEND`
4. Runtime:
   1. `DJANGO_DEBUG`
   2. `DJANGO_ALLOWED_HOSTS`
   3. `CORS_ALLOW_ALL_ORIGINS`

### Frontend (`frontend/.env*`)

1. `VITE_API_BASE_URL`
2. `VITE_API_TOKEN`
3. `VITE_FORCE_SYNC_RUNS` (optional; defaults to sync behavior when unset)

## 15) Maintenance Commands

One-time/maintenance commands:

1. `python manage.py normalize_metadata_zones`
2. `python manage.py reindex_kb_priorities`
3. `python manage.py backfill_project_owners --username <user> --confirm-single-owner`

Safety note:

1. `backfill_project_owners` is intended for confirmed single-owner legacy datasets.
2. Multi-user legacy datasets should use a mapping script instead of blanket assignment.

## 16) Test Coverage

Implemented regression coverage includes:

1. Metadata zone preservation and profile block precedence.
2. Profile assistant finalize/apply behavior.
3. Profile assistant title-grounding and finalize logic.
4. Priority-aware vector retrieval and legacy default handling.
5. Auth and ownership isolation.
6. LangGraph chapter loop behavior:
   1. threshold gating
   2. explicit `should_revise`
   3. guardrail-driven revisions
   4. max revision cap
   5. fallback stage aggregation
7. Run lifecycle status/output/timing persistence.

## 17) Current Improvement Targets

The core v2.1 hardening is implemented. Practical next targets:

1. Add run cancellation controls for long-running chapter runs.
2. Add push-based progress updates (SSE/WebSocket) to reduce polling latency.
3. Expand QA evaluator checks (citations/fact-consistency/style drift) before persist.
4. Add optional richer auth flows if product scope expands beyond token-based internal usage.

