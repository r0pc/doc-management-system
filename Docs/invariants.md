# Invariant Enforcement Matrix

The 33 non-negotiable invariants from [`AGENTS.md`](../AGENTS.md), each mapped to
the code that enforces it. `AGENTS.md` states the rules; this table says where
they actually live, so a reviewer can check an invariant without reading the
whole codebase.

If you change one of these seams, update the row. A rule with no enforcing
code is the failure mode this table exists to make visible.

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
