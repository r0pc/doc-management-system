# Secure Document Management System

Self-hosted system that ingests PDF/DOCX/XLSX documents, classifies them by **security level** (`Public → Internal → Confidential → Restricted`) and **document type**, and serves them under two-axis access control (clearance rank × department subtree) with a full audit trail. Classification is layered (rules → ML → review) and runs entirely on-premise: document text never leaves the deployment.

Design authority: `Docs/document-management-system-spec.pdf`. Agent instructions and non-negotiable invariants: [`AGENTS.md`](AGENTS.md). Tracking & handoff: [`PROGRESS.md`](PROGRESS.md).

---

## Quickstart

```bash
cp .env.example .env          # dev-safe defaults; never commit .env
docker compose up -d          # postgres (55432), redis (6379), clamav (3310), minio (9000/9001)
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows git-bash
pip install ".[parsers,dev]"
alembic upgrade head          # apply core schema, monotonic trigger, RLS, taxonomy seed
uvicorn app.main:app --reload # start dev API on 127.0.0.1:8000
```

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
| Integration tests | `pytest -m integration -v` |
| Lint / format | `ruff check . && ruff format --check .` |
| Strict typecheck | `mypy app` |
| ML toolkit tests | `cd ml && pytest tests -q` |
| End-to-end verification | `bash scripts/e2e.sh` |

---

## Architecture & Stack

- **API Layer**: FastAPI 0.141+ with strict Pydantic schemas, RFC 7807 problem envelopes, and JWT/OIDC authentication (`app/api/v1/`).
- **Domain Layer**: Pure functional security policy (`app/domain/policy.py`) implementing two-axis authorization and monotonic max-wins aggregation; zero framework/ORM dependencies.
- **Database**: PostgreSQL 16 with `pgvector`, Row-Level Security (RLS) across all tenant tables, append-only `classifications` history, and database-level `trg_check_monotonic` trigger.
- **Storage Subsystem**: Pluggable storage engine (Local with HMAC-signed dev presigning, MinIO/S3 in production) with strict `PrimaryBlobGuard` immutability controls.
- **Extraction Pipeline**: MIME sniffing via `puremagic` (extensions ignored), structural parsing (PyMuPDF, `python-docx`, `openpyxl`), and OCR routing.
- **Classification Engine**: Structural PII recognizers with Luhn / CNIC / IBAN validation and ±50 char context window scoring, calibrated scikit-learn ML cascade (`CalibratedClassifierCV`), and human review queue routing.
- **Workers & Tasks**: Celery on Redis with strict queue separation (`default` vs `ocr`), transactional stage journaling (`processing_jobs`), and real-time ClamAV INSTREAM socket scanning.
- **Search**: Hybrid search with visibility predicates embedded *inside* both keyword and vector arms prior to Reciprocal Rank Fusion ($k=60$).

---

## Invariant Enforcement Matrix (All 33 Invariants)

| Invariant | Rule Summary | Enforcing Layer & Code Seams |
|:---|:---|:---|
| **#1** | API does not touch object storage on write path; browser PUTs to presigned URL | `app/api/v1/uploads.py` (`POST /uploads` intent signs quarantine PUT URL; `complete_upload` verifies intent and enqueues worker). |
| **#2** | Workers are only automated writer of classifications; API records human reclassification only | `app/workers/tasks.py:classify` is the sole automated writer (`decided_by='rules'/'ml'`). API routes write `decided_by='human'`. |
| **#3** | Fixed pipeline order (`scan → extract → keywords → embed → classify → index`) | `app/workers/tasks.py:process_upload_chain` defines the Celery canvas chain in exact sequence. |
| **#4** | `processing_jobs` state journal around every stage; SQL-visible document status on failure | `app/workers/jobs.py:StageJournal` records before/after state transitions; failure triggers `mark_document_failed`. |
| **#5** | sha256 idempotency | Pipeline keyed on sha256; `_already_succeeded` checks state journal; `record_classification` SELECTs before INSERT. |
| **#6** | Single extraction & embedding pass reused by classification and search | `derived/{sha}/text.json` written once by `extract_text`; downstream stages read cached derived JSON. |
| **#7** | Identity validated against cached JWKS, no per-request IdP round-trips | `app/security/auth.py:OidcJwksVerifier` uses cached `PyJWKClient` with algorithm confusion defenses (`HS*` rejected in prod). |
| **#8** | `check_monotonic` trigger: automated cannot lower, human lowering audited | `alembic/versions/0002_security_hardening.py` (`trg_check_monotonic`); human overrides audited in `access_log`. |
| **#9** | Nothing matched defaults to `Internal` floor, never `Public` | `app/domain/policy.py:aggregate_level` and SQL coalesce enforce `DEFAULT_FLOOR_RANK = 2` (`Internal`). |
| **#10** | Recogniser is pattern + structural validator + context words (±50 chars) | `app/classification/rules/recognizers.py`, `app/classification/rules/base.py` & `score_with_context` window helper. |
| **#11** | Calibrated ML probabilities; cascade thresholds (ML ≥ 0.85, else review) | `app/classification/ml/loader.py` enforces `CalibratedClassifierCV` artifact contract v1; `classify` routes to review. |
| **#12** | `findings` stores character offsets only, never matched sensitive text | `Finding` model, DB schema, and API wire models carry `(char_start, char_end, page_no, score)` only. |
| **#13** | Never train on held-out evaluation set | `ml/export_training_data.py` & `ml/train_classifier.py` enforce strict train/val/eval segregation. |
| **#14** | Per-class recall on highest security label tracked near 1.0 | `ml/artifact_contract.md` specifies per-class evaluation requirements. |
| **#15** | Object key is never an authorization boundary; permissions on `documents` row | `blobs` table carries no tenant/permission columns; authorization resolved exclusively via `DocumentView`. |
| **#16** | Primary bucket objects immutable; edits are new blobs + versions | `app/storage/base.py:PrimaryBlobGuard` mixin rejects deletes/overwrites (`ImmutableKeyError`, `BlobExistsError`). |
| **#17** | Content split: Confidential/Restricted stream through API with Range; Public/Internal redirect to ≤120s presign | `app/api/v1/documents.py:get_document_content` streams bytes with HTTP 206 support for high clearance; redirects (303) for low clearance. |
| **#18** | Preview and download are separate permissions and separate endpoints | `Action.PREVIEW` (findings) vs `Action.DOWNLOAD` (content) separated in `app/domain/models.py` and API routes. |
| **#19** | Sniff MIME type; never trust file extensions | `app/extraction/sniff.py` inspects magic bytes and ZIP container structure via `puremagic`. |
| **#20** | No classification fields on `documents` beyond `current_classification_id`; append-only | `classifications` table is strictly append-only; `documents` holds only foreign key pointer. |
| **#21** | Classification references `version_id`, not just `document_id` | `classifications.version_id` FK enforced and populated on every classification write. |
| **#22** | `current_classification_id` is `DEFERRABLE INITIALLY DEFERRED` | Circular FK declared deferrable in migration `0001_core_schema.py`. |
| **#23** | `security_levels.rank` is a separate unique column, not PK | Surrogate UUID PK used; `rank` is a separate indexed unique column. |
| **#24** | `access_log` never cascades; app role holds no `UPDATE`/`DELETE` grant | Migration `0002_security_hardening.py` revokes `UPDATE`/`DELETE` grants on `access_log` from `docmgmt_app`. |
| **#25** | Access gated on clearance rank and department subtree | `app/domain/policy.py:can_access` enforces clearance $\ge$ rank AND department $\in$ visible subtrees. |
| **#26** | Tenant scoping enforced by Row-Level Security | Migration `0002_security_hardening.py` enables and forces RLS via `app.tenant_id` session GUC. |
| **#27** | Permission filter inside both keyword and vector search subqueries pre-ranking | `app/search/hybrid.py:build_visible_candidates` embeds access filter in both search arms prior to ranking. |
| **#28** | Snippets and facet counts derive from already-filtered candidate set | `app/search/hybrid.py` groups facets and extracts snippets only over the pre-filtered candidate subquery. |
| **#29** | Fusion is Reciprocal Rank Fusion ($k=60$) | `app/search/hybrid.py:rrf_merge` implements pure RRF with default constant $k=60$. |
| **#30** | Audit writes happen in same transaction as action | `app/api/deps.py:record_audit` executed and committed within the active `AsyncSession` across all mutation endpoints. |
| **#31** | Cross-tenant 404 indistinguishable in body and timing; RFC 7807 problem JSON | `app/api/v1/errors.py:not_found()` returns uniform RFC 7807 response for nonexistent, foreign tenant, and denied rows. |
| **#32** | Cursor pagination only; no `OFFSET` | Keyset pagination `(created_at, id)` implemented across listing endpoints (`documents`, `review`, `audit`). |
| **#33** | Client-side permission checks are cosmetic; server-side enforcement | All endpoints enforce `deps.require(Action)` and server-side policy evaluation. |

---

## Deviations & Architectural Decisions Ledger

1. **LLM Tail Layer Omission**: In accordance with the phase requirements, the self-hosted LLM layer was omitted (`classification/llm/` deliberately not created). Any classification ambiguity or low ML confidence (< 0.85) routes directly to the human review queue (`decided_by ∈ {rules, ml, human}`).
2. **Real-time Events (`/v1/events`)**: Returns `501 Not Implemented` placeholder; full Server-Sent Events (SSE) stream deferred to Phase 2.
3. **Fail-Closed ClamAV Dev Gate**: `SCAN_ENABLED` may be toggled to `false` in `env="dev"` for hermetic unit testing, but `Settings.validate_runtime` strictly blocks startup if `env="prod"` and `scan_enabled=false`.
4. **Search Snippet Representation**: `document_text` stores PostgreSQL `tsvector` representations rather than plaintext to maintain zero plaintext persistence in secondary tables. Keyword headline extraction in search responses utilizes tsvector representation; raw text snippet store is slated for Phase 2.
5. **Search Keyset Pagination**: Keyset cursor pagination is deferred for the search endpoint because Reciprocal Rank Fusion scores across dynamic query terms do not provide monotonic tie-breakers without materializing candidate windows.
6. **PyMuPDF Dual Licensing**: PyMuPDF (AGPL / commercial dual-license) is isolated strictly behind `app/extraction/registry.py` and `app/extraction/pdf.py` for straightforward future substitution if needed.
