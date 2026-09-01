# Secure Document Management System

Self-hosted system that ingests PDF/DOCX/XLSX documents, classifies them by
**security level** (`Public → Internal → Confidential → Restricted`) and
**document type**, and serves them under two-axis access control (clearance rank
× department subtree) with a full audit trail. Classification is layered
(rules → ML → review) and runs entirely on-premise: document text never leaves
the deployment.

## Documentation

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | The 33 non-negotiable invariants, and how to work in this repo |
| [`Docs/invariants.md`](Docs/invariants.md) | Where each invariant is actually enforced in code |
| [`Docs/decisions.md`](Docs/decisions.md) | Deviations from the spec, and why |
| [`Docs/troubleshooting.md`](Docs/troubleshooting.md) | Startup refusals, stale containers, and other deliberate failures |
| [`PROGRESS.md`](PROGRESS.md) | Wave-by-wave build log and verification gates |
| `Docs/document-management-system-spec.pdf` | Design authority |

## Quickstart

```bash
cp .env.example .env          # REQUIRED, at the repo root; dev-safe defaults, never commit it
docker compose up -d          # postgres (55432), redis (6379), clamav (3310), minio (9000/9001)
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash
pip install ".[parsers,dev]"
alembic upgrade head          # core schema, monotonic trigger, RLS, taxonomy seed
uvicorn app.main:app --reload # dev API on 127.0.0.1:8000
```

On Windows `--reload` is not optional, and the API refuses to start without a
root `.env`. Both are deliberate — see
[troubleshooting](Docs/troubleshooting.md) for why.

## Signing in

The app opens on `/login`. There is no anonymous access and no automatic
session. Five demo accounts are seeded by migration `0003`, one per role,
covering all four security levels; they are listed on the login page itself, so
click one rather than typing.

| Email | Password | Role | Clearance | Department |
|---|---|---|---|---|
| `admin@example.test` | `demo-admin` | admin | 4 · Restricted | HQ |
| `officer@example.test` | `demo-officer` | security_officer | 4 · Restricted | HQ |
| `manager@example.test` | `demo-manager` | dept_manager | 3 · Confidential | HR |
| `employee@example.test` | `demo-employee` | employee | 2 · Internal | Engineering |
| `viewer@example.test` | `demo-viewer` | viewer | 1 · Public | Engineering |

Because access is two-axis, an account legitimately sees an **empty
repository** rather than an error when nothing clears both axes. Documents
belong to a *set* of departments and are visible to any of those subtrees, plus
the mandatory tenant root; an admin can re-assign them from the document drawer
or the selection toolbar. See [decisions](Docs/decisions.md) entry 14.

This is a dev shim, not an authentication system: `POST /v1/auth/login` is
mounted only when the API runs with `env=dev`, and `users` has no password
column in any environment. Production authenticates through OIDC — see
[decisions](Docs/decisions.md) entries 12 and 13.

## Commands

| Task | Command |
|---|---|
| Full stack (infra) | `docker compose up -d` |
| API (dev) | `uvicorn app.main:app --reload` |
| Worker (default queue) | `celery -A app.workers.celery_app worker -Q default -l info --pool=solo` |
| Worker (OCR queue) | `celery -A app.workers.celery_app worker -Q ocr -l info --pool=solo` |
| Migrations | `alembic upgrade head` |
| Backend unit tests | `pytest -q` |
| Integration tests (from host) | `CLAMAV_HOST=localhost pytest -m integration -v` |
| Lint / format | `ruff check . && ruff format --check .` |
| Strict typecheck | `mypy app` |
| ML toolkit tests | `cd ml && pytest tests -q` |
| End-to-end verification | `bash scripts/e2e.sh` |
| E2E browser suite | `cd frontend && npm run test:e2e` |

The browser suite needs a live stack. Rebuild first if the backend changed —
`docker compose build api worker worker-ocr && docker compose up -d` — otherwise
it tests a stale image.

## Architecture

FastAPI + Pydantic · Celery/Redis · PostgreSQL 16 (`pgvector`) · MinIO · ClamAV ·
React 18 + TypeScript + Vite + TanStack Query + Tailwind.

- **API** (`app/api/v1/`) — strict Pydantic schemas, RFC 7807 problem envelopes, JWT/OIDC auth.
- **Domain** (`app/domain/policy.py`) — pure two-axis authorization and monotonic max-wins aggregation; no framework or ORM dependencies.
- **Database** — RLS across every tenant table, append-only `classifications`, and a `trg_check_monotonic` trigger that refuses automated downgrades.
- **Storage** — pluggable backend (local HMAC-signed dev presigning, MinIO/S3 in production) with `PrimaryBlobGuard` immutability.
- **Extraction** — MIME sniffed from magic bytes via `puremagic` (extensions ignored), then PyMuPDF / `python-docx` / `openpyxl`.
- **Classification** — structural PII recognisers (Luhn / CNIC / IBAN validators plus ±50-char context windows), a calibrated scikit-learn cascade, and human review for everything below threshold.
- **Workers** — Celery on Redis with `default`/`ocr` queue separation, a `processing_jobs` journal around every stage, and ClamAV INSTREAM scanning.
- **Search** — hybrid keyword (`ts_rank`) + vector (pgvector cosine) with the permission filter inside *both* arms before Reciprocal Rank Fusion (k=60). With no encoder available the vector arm returns zero rows and search degrades to keyword-only rather than failing.
