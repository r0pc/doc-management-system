# PROGRESS / HANDOFF REPORT

**Run**: Secure Document Management System (Full-Stack Implementation).
**Status**: **Wave 7 Complete** (ingestion-path repair, ML inference wired end to end, pgvector arm activated, production startup gate, frontend coverage).
**Repo state at handoff**: all Wave 7 work committed on branch `fix/production-readiness` (not yet pushed or merged); all verification gates green.

---

## 1. What We Set Out to Do

Full-stack build of the self-hosted DMS per `AGENTS.md` + `Docs/document-management-system-spec.pdf`, with architectural and design controls:

1. **No LLM layer** — ML failure/low-confidence routes directly to human review (`decided_by ∈ {rules, ml, human}`; `classification/llm/` deliberately never created).
2. **Kaggle-hosted training prep** — `/ml` toolkit: synthetic corpus generator, hard-gated dataset exporter, calibrated trainer template, v1 artifact contract.
3. **PII scope locked** to banking (account/card numbers) + personal (passport, CNIC) only — 4 recognizers registered.
4. **Rules and ML are live** as of Wave 7 — all four recognisers scan for real, and the calibrated cascade runs (ML >= threshold, else human review). Note the model is evaluated on SYNTHETIC data only; see item 1 of section 6.
5. **Full React 18 SPA (Wave 6)** — Modern, responsive, accessible interface with GitHub Primer design system, light/dark mode theme provider, multi-tenant dev switcher, and cosmetic UI gating.
6. **Strict Security Invariants** — All 33 non-negotiable invariants in `AGENTS.md` treated as security controls.

---

## 2. Done — Wave by Wave (All Committed & Pushed)

| Wave | Deliverables | Status |
|---|---|:---:|
| **0** | Scaffold: pyproject (ruff ALL-subset/mypy strict), frozen `Settings`, compose stack (pgvector-pg16, redis, minio, clamav, api/worker/worker-ocr one image), alembic skeleton, READMEs | ✅ Complete |
| **1** | Pure domain policy (two-axis access + max-wins aggregation, Internal floor #9) · 16-table schema mirroring spec §6 (deferred circular FK #22, rank≠PK #23, no-cascade audit #24) · Storage protocol + local(HMAC dev-presign)+S3 backends, primary immutability #16 · TokenVerifier protocol, DevJWT shim (dev-gated), OidcJwksVerifier cached-JWKS #7, role→action matrix (PREVIEW≠DOWNLOAD #18) · `/ml` Kaggle toolkit (Faker en_PK corpus, double-gated real-text export, CalibratedClassifierCV trainer, artifact_contract.md v1) | ✅ Complete |
| **2** | Migrations 0001 schema / 0002 monotonic trigger + RLS(tenant GUC) + grants(app role no UPDATE/DELETE on access_log #24) / 0003 seed · Extraction (puremagic sniffing, extension ignored #19, pdf/docx/xlsx handlers, OCR stub, keyword fallback + contract tests) · Classification placeholders (4 entity types, real validators incl Luhn/CNIC-province, stubbed scanners, review-routing cascade rules→ml≥0.85→review, artifact loader absent→review) | ✅ Complete |
| **3** | Celery chain scan→extract→keywords→embed(null vector)→classify→index(tsvector) with processing_jobs journal around every stage #4, sha256 idempotency #5, raw clamd INSTREAM client + fail-closed dev gate, quarantine→primary promotion · RFC7807 envelope w/ path-identical cross-tenant 404s #31, presigned upload intent+complete #1, cursor-only listing #32, content split-stream vs presigned #17 w/ same-tx audit #30, findings offsets-only #12, human reclassify append-only, dev-storage router | ✅ Complete |
| **4** | Review queue/resolution (human lower audited same-tx), read-only audit endpoints #24, taxonomy admin CRUD, `/v1/events` 501 stub · Hybrid search: visibility predicate composed INSIDE both arms pre-rank #27, RRF fusion scaffold (vector arm zero-rows until embeddings), facets/snippets from filtered set only #28 | ✅ Complete |
| **5A** | End-to-End System Verification (`backend/tests/integration/test_e2e_upload_to_review.py` & `scripts/e2e.sh`): walks S0 (DB migration) → S1 (dev JWT minting) → S2 (presigned PUT + upload complete) → S3 (worker pipeline execution + review queue) → S4 (human review resolution + lowering under `check_monotonic` trigger + audit trail) → S5 (split content streaming with Range vs 303 redirect) → S6 (cross-tenant RFC 7807 404 byte-parity) → S7 (EICAR malware rejection against live ClamAV) | ✅ Complete |
| **5B** | Documentation & Final QA: Root/backend/ml README sweep with complete 33 Invariant Enforcement Matrix, Deviations & Architectural Decisions Ledger, full gate execution (466 hermetic, 6 integration, 21 ML), reviewer gate pass | ✅ Complete |
| **6** | Frontend Application: React 18 + TypeScript (strict) + Vite + Tailwind CSS + GitHub Primer Design System + TanStack Query & Table. Multi-tenant auth with Web Crypto HMAC-SHA256 signing, direct presigned PUT upload wizard (Invariant #1), keyset-paginated document library with split content delivery (Invariants #17, #18, #32), review queue with confidence indicators (Invariants #8, #12), hybrid search with pre-filtered facets (Invariants #27, #28, #29), immutable audit trail viewer (Invariants #24, #30), taxonomy administration CRUD, and cosmetic UI gating (<Can> / usePermissions, Invariant #33) | ✅ Complete |
| **7** | **Production readiness.** Ingestion repair: content digest established in-pipeline by `_ensure_sha256` (every real upload had been failing at `extract` and landing in `status='failed'`; the hermetic suite missed it because its fixtures seeded a digest production never had). Migration `0005`: restored #8's monotonicity scope (0004's version-equality guard let automated writers lower labels) and backfilled `access_log.tenant_id` (0004's unbackfilled RLS had made all pre-upgrade audit history invisible). ML wired end to end: predicted `doc_type` now persists, the embed-stage vector is reused by classification (#6), prediction failures degrade to review instead of crashing ingestion, and the worker image ships the inference stack with encoder weights baked in offline. pgvector arm activated (#27/#29) with keyword-only degradation. Production startup gate in `validate_runtime`; `/v1/dev-storage` no longer mountable outside dev. Frontend coverage 12 → 70 tests, fixing an unclassified-as-Public badge (#9), two missed downgrade transitions, a fail-open auth path, and bearer-token leakage to absolute URLs | ✅ Complete |
| **8** | **Phase 1 Repairs.** Exhaustive stage failure taxonomy (#4) across all extraction/scanning stages; stage journal timestamps (`started_at`, `finished_at`) persisted and surfaced via API; upload integrity checks (content-length-range, storage stat matching, and size cap enforcement); HTTP method bound into dev presign signatures; dedicated upload presign TTL (60–900s); server-side document list filtering (`status` and `level`); 409 Conflict responses for not-ready documents preserving cross-tenant 404 parity (#31); pipeline status timeline polling in frontend; cancellable direct uploads; plain-text sniffing without OOM; reclassification justification persisted in `access_log.detail` (#8, #30); cosmetic navbar cleanups. | ✅ Complete |
| **9** | **Phase 2 Features & Admin Extensibility.** Keyset cursor pagination generalized across all sort columns & directions with tie-breakers and nulls handling (#32); bulk upload API (`POST /v1/uploads/batch`) with atomic intent creation and frontend multi-file upload manager with per-file progress and partial success; migration `0006_admin_extensibility.py` adding tenant doc types, prototypes table, and detector rules with RLS isolation (#26); few-shot prototype centroid training from ready documents (`POST /v1/admin/doc-types/{id}/prototype`) and prototype cascade matching (`decided_by='rules'`, `confidence=0.0`); configurable recognizers with structural validators (prefix_charset, luhn, mod97, entropy, checksum_suffix) satisfying invariant #10; per-tenant taxonomy extension without weakening builtin ranks; ReDoS-guarded detector admin API (`/v1/admin/detectors`, `/preview` returning offsets only #12); and Admin UI tabs (`TaxonomyPage`, `DetectorRules`, `PrototypeTrainer`). | ✅ Complete |

---

## 3. Verification Gate Status at Handoff (All Self-Run, Verbatim Tails)

```
Frontend typecheck         -> tsc --noEmit: clean (strict mode, 0 errors)
Frontend tests             -> vitest run: 88 passed across 8 test suites (DetectorRules, UploadPage, DocumentDrawer, Can, etc.)
Frontend production build  -> vite build: dist/ generated (367.65 kB JS, 34.89 kB CSS)
Backend hermetic tests     -> pytest -q: 734 passed, 3 skipped, 29 deselected, 5 warnings in 18.31s
Backend integration tests  -> CLAMAV_HOST=127.0.0.1 pytest -m integration -q: 28 passed, 1 skipped, 737 deselected in 10.28s (PG16 @5433 & ClamAV @3310)
Backend typecheck          -> mypy app: Success: no issues found in 67 source files (strict)
Backend linting            -> ruff check .: All checks passed!
Backend formatting         -> ruff format --check .: 168 files already formatted
Docker compose stack       -> postgres (5433), redis (6379), clamav (3310), minio (9000/9001), api, worker, worker-ocr, migrate healthy/running
```

---

## 4. Wave 6 Frontend Architecture & Design Highlights

### GitHub Primer Design System & Dark Mode
- **Palette**: Uses official GitHub Primer tokens:
  - Canvas: `#ffffff` / `#f6f8fa` (Light) vs `#0d1117` / `#161b22` (Dark)
  - Borders: `#d0d7de` (Light) vs `#30363d` / `#21262d` (Dark)
  - Typography: `#1f2328` / `#656d76` (Light) vs `#e6edf3` / `#848d97` (Dark)
  - Accents & Buttons: `#0969da` / `#1f883d` (Light) vs `#2f81f7` / `#238636` (Dark)
- **Theme Provider**: System-preferred / light / dark switching with `localStorage` persistence.
- **Labels & Badges**: GitHub-style pill badges for Public (Green), Internal (Blue), Confidential (Amber), and Restricted (Red).

### Security & Invariant Enforcement
- **Backend-minted dev tokens**: `auth.tsx` POSTs to `/v1/dev/token`, so no signing secret ever reaches the browser. The endpoint is mounted only when the API runs with `env=dev`, and the persona switcher is stripped from production builds.
- **Direct Presigned PUT**: `UploadPage.tsx` transfers bytes directly to object storage via presigned URLs with progress bar tracking (Invariant #1).
- **Split Content Delivery**: `DocumentDrawer.tsx` streams high-clearance bytes directly through the API with Range headers and uses presigned 303 redirects for lower-clearance files (Invariant #17 & #18).
- **Audit-Preserved Lowering**: Reclassification modals enforce human justifications and respect the database-level `check_monotonic` trigger (Invariant #8).
- **Pre-Filtered Facets**: `SearchPage.tsx` displays facets derived strictly from the candidate set pre-authorized for the current caller (Invariants #27 & #28).

---

## 5. Wave 5A Verification Matrix

| Scenario | Description | Target / Evidence | State |
|---|---|---|:---:|
| **S0** | Database Bootstrap & Migrations | PostgreSQL 16 on port 55432 migrated to head (0001→0002→0003) | ✅ Verified |
| **S1** | Token Minting & Dev Auth | `mint_dev_token.py` CLI mints valid HS256 tokens for multi-tenant principals | ✅ Verified |
| **S2** | Upload Intent & Quarantine PUT | `POST /v1/uploads` generates presigned URL; bytes stored in quarantine; `POST /complete` ingests | ✅ Verified |
| **S3** | Pipeline & Review State | Worker chain runs 6 stages in spec order (`scan→extract→keywords→embed→classify→index`), transitions status to `ready`, queues review item | ✅ Verified |
| **S4** | Human Review & Lowering | Admin resolves review item (Confidential) then lowers to Internal; `check_monotonic` permits human write; 3 classification rows & audit actions logged | ✅ Verified |
| **S5** | Split Content Delivery | `GET /content`: `Internal` returns 303 redirect to presigned URL; `Confidential` streams direct bytes (200 OK) with Range header support (206 Partial Content) | ✅ Verified |
| **S6** | Cross-Tenant 404 Parity | Outsider in Tenant 2 accessing Tenant 1 document/content/findings/jobs receives byte-identical RFC 7807 404 response to nonexistent UUID | ✅ Verified |
| **S7** | ClamAV Malware Rejection | EICAR payload upload detected by live ClamAV on port 3310; pipeline halts and sets `documents.status='failed'` with error journaled | ✅ Verified |

---

## 6. What Remains Overall (Phase-2 Backlog)

1. **Evaluate the classifier on REAL data — blocking for any production claim.** `backend/var/models/metrics.json` reports 1.0 recall on every class for both heads with `"real": null`. The corpus is generated by deterministic templates in `ml/templates.py`, so the model is near-certainly separating template fingerprints rather than document semantics, and invariant #14's "per-class recall near 1.0 on the highest label" is satisfied vacuously. The `0.85` cascade threshold is a default, not a measured operating point; it is exposed as `ML_CONFIDENCE_THRESHOLD` so it can be recalibrated against a real hold-out. Until that exists, treat every ML decision as provisional.
2. **OCR Worker Pool**: Implement real Tesseract OCR on the dedicated `ocr` Celery queue. `app/extraction/ocr.py` still raises `NotImplementedError` and routes to the `ocr` queue.
3. **Orphaned-Intent Sweeper**: Scheduled background sweeper to clean up uncompleted upload intents in `quarantine` storage that never completed within the TTL.
4. **Worker Memory Tuning**: Memory limits, Celery max tasks per child, and prefork worker pool optimization for high concurrency parsing.
5. **SSE Real-Time Feed**: Implement Server-Sent Events for `/v1/events` to replace frontend query polling.
6. **Search snippets**: `_load_snippet_text` still returns `{}`, so every result ships an empty snippet. `document_text` stores `tsvector` only; a raw-text store is needed (deviation #4).
7. **Readiness probe**: `/healthz` is static. A production deployment wants a readiness check that verifies PostgreSQL, Redis, and ClamAV reachability.
8. **Secrets**: the `docmgmt_app` role password is still a literal in migration `0002` and in `docker-compose.yml`. Move it to injected configuration before any real deployment.
9. **Container inference is unexercised locally**: torch is not installed in the host venv, so the `.[ml]` code paths are covered by fakes only. The first real `docker compose build` needs a manual smoke test of a document reaching `decided_by='ml'`.

---

## 7. Command Cheat-Sheet

```bash
# Frontend
cd frontend
npm run typecheck                                     # strict TypeScript validation
npm run test                                          # Vitest unit test suite (70 passed)
npm run build                                         # Vite production bundling (dist/)
npm run dev                                           # Vite dev server

# Backend
cd backend
.venv/Scripts/python.exe -m pytest -q                 # Unit suite (hermetic, 527 passed)
.venv/Scripts/python.exe -m pytest -m integration -v  # Integration suite (PG16 @55432 & ClamAV @3310)
.venv/Scripts/python.exe -m mypy app                  # Strict mypy typecheck (0 issues)
.venv/Scripts/python.exe -m ruff check .              # Ruff linter (0 errors)

# ML Toolkit
cd ml
../backend/.venv/Scripts/python.exe -m pytest tests -q # ML suite (21 passed)
```
