# Secure Document Management System

Self-hosted system that ingests PDF/DOCX/XLSX documents, classifies them by **security level** (`Public → Internal → Confidential → Restricted`) and **document type**, and serves them under two-axis access control (clearance rank × department subtree) with a full audit trail. Classification is layered (rules → ML → review) and runs entirely on-premise: document text never leaves the deployment.

Design authority: `Docs/document-management-system-spec.pdf`. Agent instructions and non-negotiable invariants: [`AGENTS.md`](AGENTS.md). Tracking & handoff: [`PROGRESS.md`](PROGRESS.md).

---

## Quickstart

```bash
cp .env.example .env          # REQUIRED, at the repo root; dev-safe defaults, never commit it
docker compose up -d          # postgres (55432), redis (6379), clamav (3310), minio (9000/9001)
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash
pip install ".[parsers,dev]"
alembic upgrade head          # apply core schema, monotonic trigger, RLS, taxonomy seed
uvicorn app.main:app --reload # start dev API on 127.0.0.1:8000
```

`.env` lives at the **repo root** and is found from there no matter which
directory you launch from — `app/config.py` anchors the lookup on its own
location, not the process CWD. A `backend/.env`, if present, overrides it.

**On Windows, `--reload` is not optional.** psycopg's async mode cannot run on
`ProactorEventLoop`, and uvicorn selects a compatible loop only when
`use_subprocess` is set (`--reload`, or `--workers > 1`). Without it the server
starts and then fails every database request. Startup now refuses outright with
that explanation rather than degrading to a 500 per request. Linux, macOS and
the Docker images are unaffected.

**If the API refuses to start**, read the error: `ENV` defaults to `prod`, and a
production process must prove it was configured (see the Production block in
`.env.example`). Without a root `.env` there is nothing to set `ENV=dev`, so
startup is refused by design rather than silently running a dev-shaped process
under production defaults.

---

## Signing in

The app opens on `/login`. There is no anonymous access and no automatic
session: every route redirects to the login page until you sign in, and the URL
you asked for is restored afterwards.

Five demo accounts are seeded by migration `0003`, one per role, covering all
four security levels. They are listed on the login page itself — click one to
sign in, or type the credentials.

| Email | Password | Role | Clearance | Department |
|---|---|---|---|---|
| `admin@example.test` | `demo-admin` | admin | 4 · Restricted | HQ |
| `officer@example.test` | `demo-officer` | security_officer | 4 · Restricted | HQ |
| `manager@example.test` | `demo-manager` | dept_manager | 3 · Confidential | HR |
| `employee@example.test` | `demo-employee` | employee | 2 · Internal | Engineering |
| `viewer@example.test` | `demo-viewer` | viewer | 1 · Public | Engineering |

Because access is two-axis, a lower-clearance account legitimately sees an
**empty repository** rather than an error — clearance rank and department
subtree are both applied server-side.

**This is a dev shim, not an authentication system.** `POST /v1/auth/login` is
mounted only when the API runs with `env=dev` and 404s otherwise; the
credentials are constants in `backend/app/security/demo_accounts.py`, published
by `GET /v1/auth/demo-accounts`; and `users` has no password column in any
environment. Production authenticates through OIDC (see the ledger below), at
which point this router is simply never mounted and the frontend's
`DEMO_LOGIN_ENABLED` is a compile-time `false` that drops the whole surface from
the bundle.

The demo accounts are also the **single source of the seeded identities**: the
token's `sub` is the seeded `oidc_sub`, so signing in binds to the seeded `users`
row instead of provisioning a duplicate beside it.

---

## Commands

| Task | Command |
|---|---|
| Full stack (infra) | `docker compose up -d` |
| API (dev) | `uvicorn app.main:app --reload` |
| Worker (default queue) | `celery -A app.workers.celery_app worker -Q default -l info --pool=solo` |
| Worker (OCR queue) | `celery -A app.workers.celery_app worker -Q ocr -l info --pool=solo` |
| Migrations | `alembic upgrade head` |
| Backend unit tests | `pytest -q` |
| Lint / format | `ruff check . && ruff format --check .` |
| Integration tests (from host) | `CLAMAV_HOST=localhost pytest -m integration -v` |
| Strict typecheck | `mypy app` |
| ML toolkit tests | `cd ml && pytest tests -q` |
| End-to-end verification | `bash scripts/e2e.sh` |
| E2E browser suite | `cd frontend && npm run test:e2e` (requires live stack; rebuild image first if backend changed: `docker compose build api worker worker-ocr && docker compose up -d`) |

---

## Architecture & Stack

- **API Layer**: FastAPI 0.141+ with strict Pydantic schemas, RFC 7807 problem envelopes, and JWT/OIDC authentication (`app/api/v1/`).
- **Domain Layer**: Pure functional security policy (`app/domain/policy.py`) implementing two-axis authorization and monotonic max-wins aggregation; zero framework/ORM dependencies.
- **Database**: PostgreSQL 16 with `pgvector`, Row-Level Security (RLS) across all tenant tables, append-only `classifications` history, and database-level `trg_check_monotonic` trigger.
- **Storage Subsystem**: Pluggable storage engine (Local with HMAC-signed dev presigning, MinIO/S3 in production) with strict `PrimaryBlobGuard` immutability controls.
- **Extraction Pipeline**: MIME sniffing via `puremagic` (extensions ignored), structural parsing (PyMuPDF, `python-docx`, `openpyxl`), and OCR routing.
- **Classification Engine**: Structural PII recognizers with Luhn / CNIC / IBAN validation and ±50 char context window scoring, calibrated scikit-learn ML cascade (`CalibratedClassifierCV`), and human review queue routing.
- **Workers & Tasks**: Celery on Redis with strict queue separation (`default` vs `ocr`), transactional stage journaling (`processing_jobs`), and real-time ClamAV INSTREAM socket scanning.
- **Search**: Hybrid search with visibility predicates embedded *inside* both keyword (`ts_rank`) and vector (pgvector cosine) arms prior to Reciprocal Rank Fusion ($k=60$). With no encoder available the vector arm yields zero rows and search degrades to keyword-only.

---

## Invariant Enforcement Matrix (All 33 Invariants)

| Invariant | Rule Summary | Enforcing Layer & Code Seams |
|:---|:---|:---|
| **#1** | API does not touch object storage on write path; browser PUTs to presigned URL | `app/api/v1/uploads.py` (`POST /uploads` intent signs quarantine PUT URL; `complete_upload` verifies intent and enqueues worker). |
| **#2** | Workers are only automated writer of classifications; API records human reclassification only | `app/workers/tasks.py:classify` is the sole automated writer (`decided_by='rules'/'ml'`). API routes write `decided_by='human'`. |
| **#3** | Fixed pipeline order (`scan → extract → keywords → embed → classify → index`) | `app/workers/tasks.py:process_upload_chain` defines the Celery canvas chain in exact sequence. |
| **#4** | `processing_jobs` state journal around every stage; SQL-visible document status on failure | Exhaustive stage failure taxonomy; `app/workers/jobs.py:StageJournal` records before/after state transitions with timestamps; unhandled failure triggers `mark_document_failed`. |
| **#5** | sha256 idempotency | Pipeline keyed on sha256; `_already_succeeded` checks state journal; `record_classification` SELECTs before INSERT. |
| **#6** | Single extraction & embedding pass reused by classification and search | `derived/{sha}/text.json` written once by `extract_text`; the embed stage stores its vector in that same artifact and `classify` reuses it via `predict_type(embedding=...)` rather than re-encoding. |
| **#7** | Identity validated against cached JWKS, no per-request IdP round-trips | `app/security/auth.py:OidcJwksVerifier` uses cached `PyJWKClient` with algorithm confusion defenses (`HS*` rejected in prod). Dev demo sign-in (`app/api/v1/auth.py`) mints a token for the same local `DevJWTVerifier` path and is mounted only under `env=dev`; it adds no verification path and never contacts an IdP. |
| **#8** | `check_monotonic` trigger: automated cannot lower, human lowering audited | `alembic/versions/0005_monotonic_audit_backfill.py` is the current trigger: any `decided_by <> 'human'` write below the document's CURRENT classification rank is refused, at any version. Human overrides audited in `access_log` with justification in `access_log.detail`. |
| **#9** | Nothing matched defaults to `Internal` floor, never `Public` | `app/domain/policy.py:aggregate_level` and SQL coalesce enforce `DEFAULT_FLOOR_RANK = 2` (`Internal`). |
| **#10** | Recogniser is pattern + structural validator + context words (±50 chars) | `app/classification/rules/recognizers.py`, `app/classification/rules/base.py`, `app/classification/rules/validators.py`, and `app/classification/rules/configured.py`. Custom tenant rules enforce required structural validators and ReDoS safety at `POST /v1/admin/detectors`. |
| **#11** | Calibrated ML probabilities; cascade thresholds (ML ≥ threshold, else review) | `app/classification/ml/loader.py` enforces `CalibratedClassifierCV` artifact contract v1 and degrades every prediction failure to review; threshold is `ML_CONFIDENCE_THRESHOLD` (default 0.85). Prototype cosine similarity is uncalibrated and records `decided_by='rules'` with `confidence=0.0`. |
| **#12** | `findings` stores character offsets only, never matched sensitive text | `Finding` model, DB schema, and API wire models carry `(char_start, char_end, page_no, score)` only. Admin preview (`POST /v1/admin/detectors/preview`) returns offset spans and scores only. |
| **#13** | Never train on held-out evaluation set | `ml/export_training_data.py` & `ml/train_classifier.py` enforce strict train/val/eval segregation. |
| **#14** | Per-class recall on highest security label tracked near 1.0 | `ml/artifact_contract.md` specifies per-class evaluation requirements; `load_artifact` warns when a manifest carries no real-slice metrics. |
| **#15** | Object key is never an authorization boundary; permissions on `documents` row | `blobs` table carries no tenant/permission columns; authorization resolved exclusively via `DocumentView`. |
| **#16** | Primary bucket objects immutable; edits are new blobs + versions | `app/storage/base.py:PrimaryBlobGuard` mixin rejects deletes/overwrites (`ImmutableKeyError`, `BlobExistsError`). |
| **#17** | Content split: Confidential/Restricted stream through API with Range; Public/Internal redirect to ≤120s presign | `app/api/v1/documents.py:get_document_content` streams bytes with HTTP 206 support for high clearance; redirects (303) for low clearance with its own clamped TTL (60–120s). Uploads have a separate TTL ceiling (60–900s). |
| **#18** | Preview and download are separate permissions and separate endpoints | `Action.PREVIEW` (`/view`, `/preview`) vs `Action.DOWNLOAD` (`/content`) separated in `app/domain/models.py` and API routes. |
| **#19** | Sniff MIME type; never trust file extensions | `app/extraction/sniff.py` inspects magic bytes and ZIP container structure via `puremagic`. |
| **#20** | No classification fields on `documents` beyond `current_classification_id`; append-only | `classifications` table is strictly append-only; `documents` holds only foreign key pointer. |
| **#21** | Classification references `version_id`, not just `document_id` | `classifications.version_id` FK enforced and populated on every classification write. |
| **#22** | `current_classification_id` is `DEFERRABLE INITIALLY DEFERRED` | Circular FK declared deferrable in migration `0001_core_schema.py`. |
| **#23** | `security_levels.rank` is a separate unique column, not PK | Surrogate UUID PK used; `rank` is a separate indexed unique column. |
| **#24** | `access_log` never cascades; app role holds no `UPDATE`/`DELETE` grant | Migration `0002_security_hardening.py` revokes `UPDATE`/`DELETE` grants on `access_log` from `docmgmt_app`. |
| **#25** | Access gated on clearance rank and department subtree | `app/domain/policy.py:can_access` enforces clearance $\ge$ rank AND department $\in$ visible subtrees. |
| **#26** | Tenant scoping enforced by Row-Level Security | Migration `0002_security_hardening.py` and `0006_admin_extensibility.py` enable and force RLS across tenant tables including `doc_types`, `doc_type_prototypes`, and `detector_rules` (global doc types visible to all tenants). |
| **#27** | Permission filter inside both keyword and vector search subqueries pre-ranking | `app/search/hybrid.py:build_visible_candidates` embeds access filter in both search arms prior to ranking. |
| **#28** | Snippets and facet counts derive from already-filtered candidate set | `app/search/hybrid.py` groups facets and extracts snippets only over the pre-filtered candidate subquery. |
| **#29** | Fusion is Reciprocal Rank Fusion ($k=60$) | `app/search/hybrid.py:rrf_merge` implements pure RRF with default constant $k=60$. The pgvector arm is live (`compose_vector_subquery`); only ranks are fused — cosine distance is never compared against `ts_rank`. |
| **#30** | Audit writes happen in same transaction as action | `app/api/deps.py:record_audit` executed and committed within the active `AsyncSession` across all mutation endpoints. |
| **#31** | Cross-tenant 404 indistinguishable in body and timing; RFC 7807 problem JSON | `app/api/v1/errors.py:not_found()` returns uniform RFC 7807 response for nonexistent, foreign tenant, and denied rows. Unpromoted blobs return 409 to authorized callers, which preserves parity by not leaking existence across tenant boundaries. |
| **#32** | Cursor pagination only; no `OFFSET` | Keyset pagination generalized in `app/db/pagination.py` to support arbitrary sort columns (`created_at`, `filename`, `status`, `level_rank`, `doc_type`) with keyset tie-breakers, nulls handling, and direction control without `OFFSET`. |
| **#33** | Client-side permission checks are cosmetic; server-side enforcement | All endpoints enforce `deps.require(Action)` and server-side policy evaluation. The `RequireAuth` route guard and the client-side token-expiry check are cosmetic in the same sense: they decide what is rendered, never what is served. |

---

## Deviations & Architectural Decisions Ledger

1. **LLM Tail Layer Omission**: In accordance with the phase requirements, the self-hosted LLM layer was omitted (`classification/llm/` deliberately not created). Any classification ambiguity or low ML confidence (< 0.85) routes directly to the human review queue (`decided_by ∈ {rules, ml, human}`).
2. **Prototype Cosine Similarity is Not a Calibrated Probability**: Few-shot document-type prototypes compute centroid vectors from ready document embeddings and match via cosine similarity (default $\ge 0.85$, overridable via `PROTOTYPE_CONFIDENCE_THRESHOLD`). Because cosine similarity is not calibrated per invariant #11, matches are attributed to `decided_by='rules'` with `confidence=0.0` rather than passing as an ML probability.
3. **Real-time Events (`/v1/events`)**: Returns `501 Not Implemented` placeholder; full Server-Sent Events (SSE) stream deferred.
4. **Fail-Closed ClamAV Dev Gate**: `SCAN_ENABLED` may be toggled to `false` in `env="dev"` for hermetic unit testing, but `Settings.validate_runtime` strictly blocks startup if `env="prod"` and `scan_enabled=false`.
5. **Search Snippet Representation**: `document_text` stores PostgreSQL `tsvector` representations rather than plaintext to maintain zero plaintext persistence in secondary tables. `_load_snippet_text` therefore returns `{}` and **every search result currently ships an empty snippet**; a raw-text snippet store is deferred.
6. **Search Keyset Pagination**: Keyset cursor pagination is deferred for the search endpoint because Reciprocal Rank Fusion scores across dynamic query terms do not provide monotonic tie-breakers without materializing candidate windows.
7. **ML Artifact Distribution**: the trained classifier (`model.joblib`) is gitignored and is NOT baked into the image; compose mounts `backend/var/models` read-only and points `MODEL_ARTIFACT_PATH` at it. An absent artifact is a normal state — the loader returns `None` and every document routes to human review. The *encoder* weights (`BAAI/bge-small-en-v1.5`) ARE baked in at build time, with `HF_HUB_OFFLINE=1` at runtime so a missing cache is a hard error rather than silent egress to huggingface.co (self-hosting invariant).
8. **PyMuPDF Dual Licensing**: PyMuPDF (AGPL / commercial dual-license) is isolated strictly behind `app/extraction/registry.py` and `app/extraction/pdf.py` for straightforward future substitution if needed.
9. **OCR Implementation Deferred**: True OCR processing is deferred; the pipeline currently marks documents requiring OCR as `held` instead of proceeding.
10. **Inline Document View & Preview**: The API exposes `/v1/documents/{id}/view` and `/v1/documents/{id}/preview` endpoints for inline browser rendering and plain-text preview respectively, complementing the `/content` download endpoint.
11. **Bulk Upload Batch Processing**: The API exposes `POST /v1/uploads/batch` returning atomic presigned upload intents per valid file, tracked under a single upload batch record.
12. **Demo Sign-in is a Dev Shim, Not an Auth System**: `POST /v1/auth/login` verifies a plaintext credential against constants in `app/security/demo_accounts.py` and mints the existing HS256 dev JWT. It is mounted only when `env=dev` (and every handler re-checks, so a mis-wired mount 404s rather than authenticating), the credentials are published by `GET /v1/auth/demo-accounts` and printed on the login page, and `users` has no password column in any environment. AGENTS.md:197 targets Keycloak/OIDC for production, where this router is never mounted and the frontend gate is a compile-time `false`. Login is **not** audited to `access_log`: the row would need a tenanted RLS session and an actor FK for a surface that cannot exist in production, so attempts are logged to the application logger (role and email domain only) instead.
13. **Demo Accounts Bind to the Seeded Users**: the login token's `sub` is the `oidc_sub` seeded by migration `0003`. This is load-bearing, not cosmetic — `provision_actor` upserts on `oidc_sub`, so a subject that does not match the seed does not fail, it silently provisions a *second* `users` row with a synthesised `…@oidc.local` email. The superseded persona shim did exactly that (`dev-admin_t1` vs `dev-admin`), leaving the five seeded users unused and accumulating duplicates. `tests/api/test_auth_login.py::TestSeedAlignment` parses the migration and asserts the two agree, because nothing at runtime surfaces the divergence.
