# AGENTS.md

Instructions for any coding agent operating in this repository (Codex, Cursor, Jules, Copilot Workspace, Devin, or similar). Self-contained — do not assume you have read any other instruction file.

Nearest `AGENTS.md` wins for a given file. Explicit instructions from a human in the session override this file.

Design authority: `docs/documentmanagementsystemspec.pdf` (Secure Document Management System, v1.0). If this file and the spec conflict, follow the spec and flag the discrepancy in your summary.

---

## Project

Self-hosted system that ingests PDF/DOCX/XLSX documents, classifies them by **security level** and **document type**, and serves them under access control with a full audit trail.

Self-hosting is a hard requirement, not a preference. Document text may not leave the deployment. Do not introduce a hosted LLM, hosted embedding, or hosted OCR API under any framing — including "just for development."

Two independent outputs:

- **Security level** — `Public` → `Internal` → `Confidential` → `Restricted`. Combined by **maximum** across layers. Monotonic upward.
- **Document type** — hierarchical (`Contract › Vendor MSA`). Combined by **cascade**; first confident answer wins.

Stack: FastAPI + Pydantic + Celery/Redis + PostgreSQL 16 (`pgvector`) + MinIO + Keycloak (OIDC) + ClamAV + Nginx; React 18 + TypeScript + Vite + TanStack Query/Table + Tailwind/shadcn on the frontend. Classification uses spaCy + scikit-learn TF-IDF, Presidio recognisers, `sentence-transformers` + calibrated logistic regression, and a self-hosted LLM for the tail only.

---

## Setup

```bash
docker compose up -d          # proxy, api, worker, postgres, minio (+ keycloak, model server)
cp .env.example .env          # never commit .env
alembic upgrade head
```

Backend requires Python 3.11+. Frontend requires Node 20+.

## Commands

| Task | Command |
|---|---|
| API (dev) | `uvicorn app.main:app --reload` |
| Worker | `celery -A app.workers.celery_app worker -Q default -l info` |
| OCR worker | `celery -A app.workers.celery_app worker -Q ocr -l info` |
| Migration | `alembic revision --autogenerate -m "..."` then `alembic upgrade head` |
| Backend tests | `pytest -q` |
| Lint / format | `ruff check . && ruff format .` |
| Types | `mypy app` |
| Frontend dev | `npm run dev` |
| Frontend checks | `npm run typecheck && npm run test && npm run build` |

OCR runs on a **separate queue with its own pool**. A single multi-minute OCR job on a shared pool starves every other stage. Do not merge the queues.

Tests must pass without MinIO or Keycloak running — the filesystem storage backend and a stub token verifier cover local runs. If you add a test that needs live infrastructure, mark it and keep it out of the default suite.

---

## Before you finish

Run all of these and report results honestly. Do not claim a check passed if you did not run it.

```bash
ruff check . && mypy app && pytest -q
cd frontend && npm run typecheck && npm run test
```

If you changed any route or response model, regenerate the OpenAPI client rather than hand-editing `frontend/src/api/`.

---

## Repository layout

```
backend/app/
  api/v1/            uploads, documents, review, search, audit, admin
  domain/            policy.py (authorization + level aggregation), taxonomy.py, models.py
  db/                models.py (SQLAlchemy), repositories/, migrations/
  storage/           base.py (Protocol), s3.py, local.py
  extraction/        registry.py, pdf.py, docx.py, xlsx.py, ocr.py, keywords.py
  search/            hybrid.py, filters.py
  classification/    pipeline.py, rules/, ml/, llm/
  security/          auth.py, permissions.py, audit.py
  workers/           celery_app.py, tasks.py, jobs.py
frontend/src/
  api/ features/{documents,review,upload,audit,admin}/ components/ lib/
```

The API and the Celery worker are **one codebase and one image**, differing only in entrypoint. Both import `domain/`. Never create a worker-local copy of policy or classification logic.

---

## Non-negotiable invariants

Treat each of these as a security control. If a task appears to require violating one, **stop and report it** rather than implementing a workaround.

### Data flow

1. The API does not touch object storage on the write path. Browsers PUT directly via presigned URL; the API signs and records intent.
2. Workers are the only automated writer of classifications. Nothing classifies inside a request handler. The API may record a *human* reclassification only.
3. Pipeline order is fixed: `scan_for_malware → extract_text → extract_keywords → embed → classify → build_index`.
4. Every stage writes its state transition to `processing_jobs` before and after running. Pipeline state must be answerable from SQL.
5. Tasks are idempotent, keyed on blob sha256. A mid-chain retry must not create a duplicate classification row.
6. Keywords/entities are extracted once and embeddings computed once, then reused by both classification and search. A second pass over the same text with the same model is a bug.
7. Identity is validated against cached JWKS, not round-tripped to the identity provider per request.

### Classification

8. Security level never decreases automatically. The LLM layer may propose a type and may raise a level; it can never lower one. Only a human reviewer lowers a label, and that write is audited. Enforced by the `check_monotonic` database trigger — keep the trigger, do not move the check into application code alone.
9. Nothing matched defaults to `Internal`, never `Public`.
10. A recogniser is a pattern **plus** a structural validator **plus** context words scored in a ±50 character window. A bare regex is not acceptable.
11. ML probabilities must be calibrated (`CalibratedClassifierCV`). Cascade thresholds: ML ≥ 0.85, LLM ≥ 0.75, else route to review.
12. `findings` stores character offsets, never matched text. Do not copy sensitive identifiers into a second table.
13. Never train on the held-out evaluation set (150–200 hand-labelled documents, 50–100 of them real). Report synthetic and real accuracy separately.
14. Never report a single accuracy number for security level. Track per-class recall on the highest label and hold it near 1.0.

### Storage and access

15. The object key is never an authorisation boundary. Permission lives on the `documents` row. `blobs` carries no tenant and no permission.
16. Primary-bucket objects are never overwritten. An edit is a new blob plus a new `document_versions` row.
17. `Restricted` and `Confidential` bytes stream through the API (`GET /v1/documents/{id}/content`, range headers honoured, one audit row per response). Presigned URLs are only for `Internal` and `Public`, TTL 60–120s, with `response-content-disposition` pinned. Do not "optimise" the restricted path into a presigned redirect.
18. Preview and download are separate permissions and separate endpoints.
19. Sniff MIME type; never trust the file extension.

### Database

20. No classification fields on `documents` beyond `current_classification_id`. `classifications` is append-only.
21. A classification references `version_id`, not just `document_id`.
22. `current_classification_id` is `DEFERRABLE INITIALLY DEFERRED` (the FKs are mutually circular).
23. `security_levels.rank` is a separate column from the surrogate `id`. Never make rank the primary key.
24. `access_log` never cascades (`ON DELETE NO ACTION` or a bare uuid column). The application role holds no `UPDATE`/`DELETE` grant on it.
25. Access is gated on two independent axes: clearance rank and department subtree. Do not collapse them into one rank.
26. Tenant scoping is enforced by row-level security, not by remembering a `WHERE` clause.

### Search

27. The permission filter goes **inside both** the keyword and vector subqueries, before ranking and before fusion. Post-hoc filtering of a fused result set leaks via page length and hit counts.
28. Snippets and facet counts derive from the already-filtered candidate set. A count is information.
29. Fusion is reciprocal rank fusion. Do not weight `ts_rank` against cosine distance directly.

### API and client

30. Audit writes happen in the same transaction as the action they record — not middleware, not a background task.
31. A 404 for another tenant's document is indistinguishable from a 404 for a nonexistent one, in body and in timing. Error bodies never contain filenames. Centralised in `errors.py` (RFC 7807).
32. Cursor pagination only. No `OFFSET`.
33. Client-side permission checks are cosmetic. Gate UI through `<Can>` / `usePermissions()`, and never rely on them for security.

---

## Code style

**Python** — ruff for lint and format; type hints on all public functions; mypy clean. Pydantic models in `domain/models.py` for domain objects, SQLAlchemy rows confined to `db/`. Do not return ORM rows past the repository layer. `domain/policy.py` functions stay **pure** — no session, no request object — so the authorisation suite runs as a parametrised table with no fixtures.

**TypeScript** — strict mode; no `any`; server state through TanStack Query, not `useEffect` fetches; filter state in URL params, not component state.

**General** — prefer editing existing files to creating new ones. Do not add a top-level package or a dependency without justifying it in your summary. Do not add a second datastore, a search engine, or an ORM alternative.

---

## Testing expectations

- Any change to access control adds a case to the policy table test.
- Any new endpoint gets: a permission-check test, an audit-write test where applicable, and a cross-tenant 404 test.
- Any migration is reversible and reviewed against the database invariants above.
- Search changes get a test proving the permission filter runs pre-ranking (result counts must not vary with what the caller cannot see).

---

## Safety rails

- Never write real personal data into fixtures, seeds, or tests. Use `Faker('en_PK')` generators for synthetic identifiers.
- Never commit `.env`, credentials, bucket keys, or model weights.
- Never log document text, extracted content, or matched identifier values. Operational logs are structured JSON and carry ids, not contents.
- Never run destructive database commands against anything but a local container. No `DROP`, no `TRUNCATE`, no unscoped `DELETE` in a migration without an explicit human instruction.
- Do not disable, weaken, or skip a test to make a build pass. Report the failure instead.

---

## Commits and pull requests

- Conventional commits: `feat|fix|refactor|test|docs|chore(scope): summary`.
- One logical change per PR. Migrations travel with the code that needs them.
- PR description states: what changed, which invariants above it touches (if any), and which checks were run.
- Any change to sections marked non-negotiable requires explicit human sign-off called out in the PR description.

---

## Open decisions

- The tail-layer LLM is unchosen; keep `classification/llm/client.py` behind a narrow swappable interface.
- Auth: the spec targets Keycloak/OIDC while the architecture diagram shows plain JWT. JWT is acceptable as a dev shim, but claims must map cleanly onto OIDC tokens later.
- LayoutLMv3 only enters scope if scanned forms do.
- A single parsing entry point (Tika / `unstructured`) is a plausible future trade, not the current choice.
