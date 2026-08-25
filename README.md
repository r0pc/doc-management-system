# Secure Document Management System

Self-hosted system that ingests PDF/DOCX/XLSX documents, classifies them by **security level** (`Public → Internal → Confidential → Restricted`) and **document type**, and serves them under two-axis access control (clearance rank × department subtree) with a full audit trail. Classification is layered (rules → ML → self-hosted LLM tail) and runs entirely on-premise: document text never leaves the deployment.

Design authority: `Docs/documentmanagementsystemspec.pdf`. Agent instructions and non-negotiable invariants: [`AGENTS.md`](AGENTS.md).

## Quickstart

```bash
cp .env.example .env          # dev-safe defaults; never commit .env
docker compose up -d          # postgres, redis, minio, clamav (+ api/worker when built)
cd backend
python -m venv .venv && .venv/Scripts/python -m pip install ".[parsers,dev]"   # git-bash path style
```

> Database migrations arrive in Wave 2.A — `alembic upgrade head` has nothing to apply yet. The Alembic machinery itself is wired and functional.

## Commands

| Task | Command |
|---|---|
| Full stack | `docker compose up -d` |
| Infra only | `docker compose up -d postgres redis minio clamav` |
| API (dev) | `uvicorn app.main:app --reload` |
| Worker | `celery -A app.workers.celery_app worker -Q default -l info` |
| OCR worker | `celery -A app.workers.celery_app worker -Q ocr -l info` |
| Migration | `alembic revision --autogenerate -m "..."` then `alembic upgrade head` |
| Backend tests | `pytest -q` |
| Lint / format | `ruff check . && ruff format .` |
| Types | `mypy app` |
| Frontend dev | `npm run dev` (frontend arrives in a later wave) |

(Backend commands assume an activated `backend/.venv`; see [backend/README.md](backend/README.md).)

## Architecture

See `Docs/` for the authoritative spec. Stack summary:

- **API**: FastAPI + Pydantic, PostgreSQL 16 (`pgvector`), MinIO object storage, Keycloak/OIDC (dev JWT shim for now)
- **Workers**: Celery on Redis; pipeline `scan_for_malware → extract_text → extract_keywords → embed → classify → build_index`; OCR on its own queue/pool
- **Frontend** (later wave): React 18 + TypeScript + Vite + TanStack Query/Table + Tailwind/shadcn

## Status

Wave 0 scaffold complete:

- ✅ Backend package skeleton (`app/` tree), settings (`app/config.py`), health endpoint, Celery app placeholder with `default`/`ocr` queues
- ✅ Alembic skeleton (no migration files yet — Wave 2.A owns them)
- ✅ Dockerfile (one image → api / worker / worker-ocr via compose overrides) + compose stack with healthchecks
- ✅ Hermetic test suite (`pytest -q` needs no MinIO/Keycloak running)

Pending waves: domain models + migrations (2.A), storage/extraction/classification pipelines (1–3), API routers (2+), frontend (4+), search (5).

## Windows notes

- Developed/tested from **git-bash** on Windows 11; use forward-slash-safe paths.
- Compose workers use `--pool=solo` for dev simplicity; production uses prefork/gevent (see comment in `docker-compose.yml`).
- Host Python may be newer than the container's (`python:3.12-slim`); the local venv interpreter choice is recorded in [backend/README.md](backend/README.md).
