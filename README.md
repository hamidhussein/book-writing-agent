# Agentic Book Writing Platform

Advanced book generation scaffold built with React + Django + Celery + Redis + Qdrant.

## Stack

- Frontend: React 19 + TypeScript + Vite
- Backend: Django 5 + Django REST Framework
- Background jobs: Celery
- Broker/result backend: Redis
- Vector database: Qdrant
- Primary relational database: SQLite (for now)
- Export: PDF (`reportlab`) and DOCX (`python-docx`)

## What It Does

The platform runs a mode-driven writing workflow:

- `toc`: generate a table of contents and synopsis
- `refine_toc`: refine outline from user feedback
- `chapter`: generate a specific chapter
- `export`: export generated manuscript as PDF, DOCX, or both

Runs can be executed asynchronously through Celery, or synchronously with `?sync=1` for local debugging.

It also supports a pre-generation Knowledge Base flow:

- Add manual knowledge notes per project
- Upload source files (`.txt`, `.md`, `.pdf`, `.docx`) before generating
- Source text is chunked, embedded, and indexed in Qdrant
- Retrieved knowledge is used during TOC/refine/chapter generation

API access is now token-authenticated and owner-scoped:

- Obtain token via `POST /api/auth/token/`
- Send `Authorization: Token <token>`
- Users can access only their own projects, chapters, sources, and runs

## Repository Layout

- `backend/`: Django API, agent orchestration, workflow services
- `frontend/`: React UI (`BookStudioPage`) for project setup and run controls
- `docker-compose.yml`: local services (`backend`, `worker`, `redis`, `qdrant`)

## Prerequisites

- Docker Desktop
- Python 3.12+
- Node.js 20+
- npm

## Quick Start (Recommended: Docker + Vite Frontend)

1. Prepare backend environment:

```bash
copy backend\.env.example backend\.env
```

2. Start backend stack:

```bash
docker compose up -d --build
```

3. Create an API token (one-time per user):

```bash
docker compose exec backend python manage.py shell -c "from django.contrib.auth import get_user_model; from rest_framework.authtoken.models import Token; User=get_user_model(); u,_=User.objects.get_or_create(username='dev'); u.set_password('devpass123'); u.save(); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

4. Start frontend in dev mode:

```bash
cd frontend
npm install
set VITE_API_BASE_URL=http://127.0.0.1:8010/api&&set VITE_API_TOKEN=PASTE_TOKEN_HERE&&npm run dev
```

5. Open the app:

- Frontend: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8010`
- Health: `http://127.0.0.1:8010/api/health/`

## Local Python Development (Without Docker Backend/Worker)

Use this if you want to run Django and Celery directly on your machine.

1. Start infra only:

```bash
docker compose up -d redis qdrant
```

2. Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Create token:

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model; from rest_framework.authtoken.models import Token; User=get_user_model(); u,_=User.objects.get_or_create(username='dev'); u.set_password('devpass123'); u.save(); t,_=Token.objects.get_or_create(user=u); print(t.key)"
```

3. Worker (new terminal):

```bash
cd backend
.venv\Scripts\activate
celery -A bookagent worker -l info
```

4. Frontend:

```bash
cd frontend
npm install
set VITE_API_BASE_URL=http://127.0.0.1:8000/api&&set VITE_API_TOKEN=PASTE_TOKEN_HERE&&npm run dev
```

## Environment Variables

Configured in `backend/.env`:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `CORS_ALLOW_ALL_ORIGINS`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `QDRANT_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_FAST_MODEL`
- `OPENAI_EMBED_MODEL`
- `BOOK_AGENT_JSON_RETRIES`
- `BOOK_AGENT_TIMEOUT_S`
- `VITE_API_TOKEN` (frontend, optional but required when auth is enabled)

Notes:

- Docker runtime values typically use service names:
  - `CELERY_BROKER_URL=redis://redis:6379/0`
  - `QDRANT_URL=http://qdrant:6333`
- Local runtime values usually use loopback:
  - `CELERY_BROKER_URL=redis://127.0.0.1:6379/0`
  - `QDRANT_URL=http://127.0.0.1:6333`

## API Endpoints

Base URL is `/api`.

- `GET /api/health/`
- `POST /api/auth/token/`
- `GET,POST /api/books/projects/`
- `GET,PATCH,DELETE /api/books/projects/{project_id}/`
- `GET,POST /api/books/projects/{project_id}/chapters/`
- `GET,POST /api/books/projects/{project_id}/sources/`
- `POST /api/books/projects/{project_id}/knowledge-upload/`
- `GET,POST /api/books/chapters/`
- `GET,PATCH,DELETE /api/books/chapters/{chapter_id}/`
- `GET,POST /api/books/sources/`
- `GET,PATCH,DELETE /api/books/sources/{source_id}/`
- `GET,POST /api/agents/runs/`
- `GET /api/agents/runs/{run_id}/`

Execution mode input:

- `mode`: one of `toc`, `refine_toc`, `chapter`, `export`
- `inputs` object:
  - `refine_toc`: `{ "feedback": "..." }`
  - `chapter`: `{ "chapter_number": 1 }`
  - `export`: `{ "export_format": "pdf" | "docx" | "both" }`

Knowledge upload payload:

- Multipart form with `file` (supported: `.txt`, `.md`, `.pdf`, `.docx`)
- Optional `title`
- Legacy `.doc` should be converted to `.docx` before upload

## Useful Commands

Start all services:

```bash
docker compose up -d --build
```

Check service state:

```bash
docker compose ps
```

Tail logs:

```bash
docker compose logs -f backend
docker compose logs -f worker
```

Stop stack:

```bash
docker compose down
```

Normalize legacy metadata to two-zone schema:

```bash
docker compose exec backend python manage.py normalize_metadata_zones
```

Reindex KB sources with priority payload:

```bash
docker compose exec backend python manage.py reindex_kb_priorities
```

Backfill owner for legacy projects:

```bash
docker compose exec backend python manage.py backfill_project_owners --username dev --confirm-single-owner
```

Important: only use this blanket command for confirmed single-owner legacy datasets.
For multi-user legacy data, use a user-mapping script instead of assigning all projects to one account.

## Troubleshooting

- Frontend can load but API calls fail:
  - Ensure `VITE_API_BASE_URL` points to the active backend (`8010` for Docker backend, `8000` for local backend).
- `401 Unauthorized` on API calls:
  - Generate a token via `POST /api/auth/token/` (or shell command above).
  - Set `VITE_API_TOKEN` and restart frontend dev server.
- `Connection refused` from backend to Redis/Qdrant:
  - Use `redis` / `qdrant` hostnames inside Docker.
  - Use `127.0.0.1` for local Python processes.
- No LLM key configured:
  - The workflow still runs with deterministic fallback outputs for development.
- Port conflicts:
  - If `8000` is used by another app, keep Docker mapping (`8010:8000`) and point frontend to `8010`.

## Security Note

- Do not commit real API keys.
- Keep secrets only in local `.env` files and rotate keys if exposed.
