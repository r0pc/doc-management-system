# Design: DMS Repair + Admin Extensibility

**Date**: 2026-08-31
**Status**: Approved for planning
**Scope**: Repair the deployed ingestion/delivery path, then add sorting, bulk upload,
admin-trained doc-type classifiers, and admin-defined sensitive-data detectors.

---

## 1. Problem

The system passes 609 backend and 72 frontend tests while being visibly broken in the
browser. Documents strand in `Processing` forever, view/download returns 404, and the
list filters silently do nothing.

The tests pass because every suite is hermetic: `backend/tests/api/conftest.py`
monkeypatches the `_fetch_*` seams and injects a `_FakeSession` whose `execute` raises,
so handler logic is verified while the failing layer — storage paths, route
registration, deployment wiring — is mocked away. This is the same failure mode recorded
in `PROGRESS.md` Wave 7 ("the hermetic suite missed it because its fixtures seeded a
digest production never had"). No quantity of additional unit tests closes this gap.

---

## 2. Goals / Non-goals

**Goals**
- Deployed stack works end to end: upload → process → ready → view → download.
- Every failure is visible in SQL and in the UI, with a reason.
- Sorting, bulk upload (<= 1 GB/batch, <= 100 MB/file), admin classifiers, admin detectors.
- A test layer that would actually have caught today's bugs.

**Non-goals (deferred, tracked in PROGRESS.md section 6)**
- Real Tesseract OCR (the `ocr` queue stays unimplemented; scanned PDFs get a terminal
  `held` state with a reason instead of hanging).
- Worker memory tuning (document currently resident 2-3x during scan and promote).
- Orphaned-intent sweeper / reconciler.
- Server-Sent Events for `/v1/events` (polling is used instead).

---

## 3. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Bulk upload cap | 1 GB per batch, 100 MB per file | Keeps the existing single-shot presigned PUT per file. Avoids multipart/resumable machinery and its failure modes. |
| Classifier mechanism | Few-shot embedding centroid + auto-derived keyword rule | 5-10 samples cannot calibrate, so retraining would violate invariant #11 by claiming calibration it lacks. A prototype is an honest, distinct signal and reuses the existing embedding pass (#6). |
| Detector authoring | Guided builder, structural validator **required** | Invariant #10 forbids a bare regex. A pattern-only rule cannot be saved. |
| Sequencing | Fixes committed and verified first, then features | Keeps blame bisectable on a known-good base. |
| Fix scope | Symptoms + landmines + security holes | See section 4 and 5. |
| E2E harness | Playwright against the live compose stack | The only layer that catches deployment and frontend-wiring bugs. New devDependency, justified per AGENTS.md. |

---

## 4. Phase 0 — Deployment correctness

Blocking: nothing below is verifiable until the deployed image matches the source.

**P0-1 — Storage root regression (would break the next `docker compose build`).**
Uncommitted `backend/app/config.py:188-194` adds `resolve_storage_root()` returning
`_REPO_ROOT / "var" / "storage"`. In the container the package lives at `/srv/app/app/`,
so `_BACKEND_DIR=/srv/app` and `_REPO_ROOT=/srv`, resolving to `/srv/var/storage`.
Compose mounts the shared `storage-data` volume at `/srv/app/var/storage`. Verified:
`/srv/var/storage` does not exist. The running image predates this change, which is the
only reason storage currently works.

*Fix*: set `DOCMGMT_LOCAL_STORAGE_ROOT=/srv/app/var/storage` for `api`, `worker` and
`worker-ocr` (the env var is already honoured and takes precedence). Add a startup
assertion that the resolved root exists and is writable — fail loud, not per-request.
*Test*: assert the compose mount path and the resolved root agree.

**P0-2 — Stale image.** `/v1/documents/{id}/view` and `/preview` exist in the working
tree (`documents.py:697`, `:763`) but are absent from the running API. Rebuild, then
verify against the live stack.

---

## 5. Phase 1 — Repairs

Each item ships with a regression test that fails before the fix.

### 5.1 Pipeline observability (invariant #4)

**F1 — Exhaustive failure taxonomy.** `tasks.py:446-495` enumerates 11 exception types;
anything else escapes `_run_stage` before a terminal journal write, pinning the job at
`running` and the document at `processing`. Reachable escapes: `FileNotFoundError`,
`NoResultFound`, `json.JSONDecodeError`, `SoftTimeLimitExceeded`, `pymupdf.FileDataError`,
`zipfile.BadZipFile`, `openpyxl` `KeyError`, `OperationalError`.
*Fix*: a terminal `except Exception` that journals `failed` with a sanitised reason and
calls `mark_document_failed`. Never log document text (safety rail).

**F2 — Stage timestamps.** `processing_jobs.started_at` / `finished_at` exist
(`db/models.py:186-187`) and are exposed by the API but are never written by any
`ProcessingJobsJournal` method (`jobs.py:138-193`). Without them a hung stage is
undetectable. *Fix*: populate both.

**F3 — Exhausted retries strand documents.** `tasks.py:489-491` journals the stage failed
and re-raises for `autoretry_for` but deliberately skips `mark_document_failed`. After
`max_retries=3` the chain dies leaving `processing_jobs.state='failed'` with
`documents.status='processing'`. *Fix*: mark the document failed on final retry exhaustion.

**F4 — ClamAV stream ceiling.** Stock `clamav/clamav:latest` defaults `StreamMaxLength`
to 25 MB with no override in compose, against a declared 100 MB upload ceiling. Any file
in the 25-100 MB band aborts the stream, producing `ScanError` then
`TransientStorageError`, then 3 retries, then the F3 stranded state.
*Fix*: mount a `clamd.conf` raising `StreamMaxLength` to match `upload_max_bytes`, and
derive both from one source.

**F5 — Scanned PDFs.** `pdf.py:51-52` raises `NeedsOcrError`; `_run_stage` journals
`skipped` and raises `Ignore()`, and no OCR worker exists. *Fix*: terminal `held` status
(already permitted by `ck_documents_status_valid`) with reason `needs_ocr`. Real OCR
stays deferred.

### 5.2 Upload integrity

**F6 — `complete_upload` does none of what it claims.** `uploads.py:236-295` performs no
existence check, no size re-check, no MIME sniff and no hash, despite its docstring
(`uploads.py:6-27`) and its test docstring claiming all four. `CompleteRequest.size_bytes`
is accepted from the browser and discarded. A client can complete an upload it never PUT,
which then strands via F1.
*Fix*: verify the quarantine object exists and that its real length matches the declared
size; reject a mismatch with 409. Sniffing and hashing stay in the worker (invariant #1 —
the API must not read bytes on the write path), so completion checks metadata only.

**F7 — No server-side size cap on the real path.** `s3.py:138-148` presigns with only
Bucket/Key/ContentType — no `content-length-range`. There is no nginx and no uvicorn body
limit. The 100 MB ceiling is enforced only against a client-supplied integer
(`uploads.py:198`) and a client-side JS check. *Fix*: add `content-length-range` to the
presign policy so storage itself rejects oversized bodies.

**F8 — Presign does not sign the HTTP method.** `local.py:152-171` signs `key:expires`,
and `get_dev_object` and `put_dev_object` share one verifier, so a download URL is a valid
upload credential for the same key. Dev-only, but structural. *Fix*: bind the method into
the signed payload.

**F9 — Duplicate documents.** Two rows share sha256 `42e5684cb2`. Dedup is deferred to
`promote_blob_record`, i.e. after a duplicate has been fully re-uploaded and re-scanned.
*Fix*: surface an existing-content match at completion.

**F10 — XHR can never settle.** `client.ts:212-251` wires `onload` and `onerror` only —
no `timeout`, `ontimeout`, `onabort` or `AbortController`. An aborted transfer leaves
`uploadStage='uploading'` and the submit button disabled forever, with no cancel control.
*Fix*: timeout and abort handling, plus a cancel button.

**F11 — Upload presign TTL.** `clamp_presign_ttl` pins TTL to [60,120] seconds
(`storage/base.py:15-30`), shared with downloads. A 100 MB single-shot PUT can outlive it.
*Fix*: a separate, longer upload TTL knob. The download clamp is correct and stays.

### 5.3 Visibility

**F12 — Filters silently ignored.** The UI sends `status` and `security_level`
(`DocumentsPage.tsx:55-60`); `list_documents` (`documents.py:556-569`) declares only
`limit` and `cursor`, and FastAPI discards the rest. *Fix*: real server-side parameters
applied **inside** the keyset query, before pagination.

**F13 — Failure reason never rendered.** `JobOut.error` and `attempts` are selected,
serialised and returned; the drawer (`DocumentDrawer.tsx:357-388`) renders only a colour
dot, stage name and timestamp. *Fix*: render the reason and the attempt count.

**F14 — No polling.** Four `useQuery` calls with no `refetchInterval`, `staleTime: 30s`
and `refetchOnWindowFocus: false`. `/v1/events` is a 501 stub. *Fix*: poll while a
document is non-terminal; stop on `ready`, `failed` or `held`.

**F15 — 404 versus still-processing.** `documents.py:641-644` and `:709-712` return the
canonical 404 when `blob_key is None` — the state of every document between completion
and promotion. *Fix*: when the caller has already passed `_denied()`, return **409 Conflict**
with an RFC 7807 body whose `detail` names the current status (`processing`, `held`,
`failed`). 409 is already this codebase's "wrong state for this operation" code
(`uploads.py` uses it for a non-quarantined document), so no new convention is introduced.
This leaks nothing, because the caller can already see the row. Cross-tenant and denied
cases keep the byte-identical 404 (invariant #31), and a test asserts that parity holds.

**F16 — Decorative department field.** `UploadPage.tsx:161-179` renders a `required`
"Target Department UUID" input that is never sent; the server uses the token's
`department_id`. A persona with an empty department cannot submit at all. *Fix*: remove it.

**F17 — `.txt` unsupported in the picker.** The backend fully supports `text/plain`
(`registry.py:28`, the new `extraction/text.py`, `sniff.py:67-68`) but the picker
advertises PDF/DOCX/XLSX only. *Fix*: align the picker. Also cap `_is_plain_text`'s
decode, which currently decodes the entire payload to answer a boolean (`sniff.py:45-53`).

**F18 — Reclassify justification silently dropped.** `ReclassifyModal.tsx` sends
`justification`; `ReclassifyRequest` does not model it, so Pydantic discards it and it is
never persisted — despite it gating the downgrade UI. *Fix*: model it and persist it in
the audit row.

### 5.4 UI chrome removal

Remove the version pill, the tagline and the "Airgapped & Self-Hosted" badge from
`Navbar.tsx:22-36`.

---

## 6. Phase 2 — Features

### 6.1 Sorting (invariant #32: cursor only, no OFFSET)

Generalise the cursor from `(created_at, id)` to `(sort_key, id)` plus field and
direction, all encoded in the token so a page cannot change sort mid-walk.
Sortable columns: `filename`, `status`, `level_rank`, `doc_type`, `created_at`.

`level` and `doc_type` arrive through `isouter` joins and are nullable; a raw tuple
comparison drops rows at page boundaries. Every sort key is `coalesce`d to an explicit
sentinel so that unclassified rows sort **last in both directions** and are never dropped:
`level_rank` coalesces to `DEFAULT_FLOOR_RANK` (matching invariant #9's Internal floor,
so the sort agrees with how the row is actually authorised), and `doc_type` coalesces to
the empty string with `NULLS LAST` pinned explicitly rather than relying on the Postgres
default, which differs between `ASC` and `DESC`. The `(sort_col, id)` pair must be totally
ordered — `id` is the tiebreaker and is never omitted. A test walks every sort column
across a page boundary and asserts the union of pages equals the unpaginated set.

### 6.2 Bulk upload

<= 1 GB per batch and <= 100 MB per file, enforced client-side for immediate feedback and
server-side as the real gate (F7). Each file runs the existing intent, PUT and complete
sequence at bounded concurrency. Per-file progress and per-file failure; one failure does
not abort the batch. Partial success is a first-class outcome with a per-file result
summary. Invariant #1 is preserved — bytes still go browser to storage, never through the
API.

### 6.3 Admin-trained doc-type classifiers

A design for this already exists unimplemented at `ml/ML_IMPLEMENTATION_PLAN.md:141-226`;
it is adopted with corrections (its claimed migration number 0005 is already taken, so
this becomes 0006).

- **Schema**: `doc_type_prototypes(id, tenant_id, doc_type_id, centroid_vector vector(384),
  sample_count CHECK >= 5, created_at, updated_at)`, unique on `(tenant_id, doc_type_id)`,
  RLS enabled and forced. `doc_types` gains a nullable `tenant_id` (NULL means global) and
  a matching RLS policy — it is currently outside RLS entirely.
- **Training**: the admin selects 5-10 *already-processed* documents. Their embeddings
  already exist in `document_text.embedding`, so the centroid is a normalised mean with no
  re-encoding — invariant #6 holds. Fewer than 5 samples is rejected.
- **Inference**: in `pipeline.py`, cosine-match against tenant prototypes *before* the ML
  head. A cosine similarity at or above `PROTOTYPE_CONFIDENCE_THRESHOLD` (default `0.85`,
  exposed as an env setting alongside the existing `ML_CONFIDENCE_THRESHOLD`) yields that
  `doc_type_id` with `decided_by='rules'`; below it, the cascade falls through to ML and
  then to review. The default is a starting point, not a measured operating point — the
  same honest caveat that already applies to `ML_CONFIDENCE_THRESHOLD` per PROGRESS.md
  section 6.1. `classify()` stays pure — prototypes are passed in as resolved values,
  never fetched inside it.
- **Invariant #2**: training writes no classification, so it may run in a request handler.
  Re-classifying existing documents must go through a worker task.
- The prototype path returns a `doc_type_id` directly and never mints a `doc_types` row,
  bypassing the `DOC_TYPE_LABEL_TO_TAXONOMY_NAME` slug map and the `DOC_TYPE_LABELS`
  manifest allowlist.
- A discriminative-term rule is derived from the same samples and shown to the admin as
  editable, giving an explainable signal alongside the opaque centroid.

### 6.4 Admin-defined sensitive-data detectors

- **Schema**: `detector_rules(id, tenant_id, entity_type, pattern, validator_kind,
  validator_config, context_words, level_rank, enabled, created_at)`, RLS enabled and
  forced. `findings.rule_id` is already free-form text and needs no change.
- **Invariant #10** is enforced at the schema and in the form: `validator_kind` is NOT NULL
  and `context_words` is non-empty. Validators offered: Shannon entropy threshold,
  prefix + length + charset, Luhn, mod-97, custom checksum. A bare regex cannot be saved.
- **`ConfiguredRecognizer`** implements the existing `Recognizer` ABC
  (`rules/base.py:45-61`); `score_with_context` is already generic and is reused unchanged.
  `registry.py:28-41` gains a tenant-scoped variant — it is currently a hardcoded list.
- **Hard blocker addressed**: `Taxonomy.rank_for()` **raises** on an unknown `entity_type`
  (`domain/taxonomy.py:45-50`), so a custom detector would crash `aggregate_level` on its
  first hit. `Taxonomy` already accepts an `entity_rank` Mapping, so it is built per-tenant
  from DB rows instead of `Taxonomy.default()` at `tasks.py:390`.
- **Second hardcoded copy**: `documents.py:223-233` `_contributed_level()` duplicates the
  entity-to-level table in the API layer, so a custom type would silently render as
  "Internal". Both must be driven from one source.
- **ReDoS**: admin patterns run in the worker over full document text, and `re` has no
  timeout. Patterns are validated at save time (complexity lint, compile check, bounded
  match budget) and executed under a per-document time budget that fails the stage loudly
  rather than hanging it.
- **Invariant #12**: findings are constructed via `build_finding()`, which already fails
  loud if text is smuggled into an offset field. Matched text is never persisted.

---

## 7. Phase 3 — End-to-end tests

Playwright against the live compose stack, covering: upload, process, ready, view and
download; filter by status and by level; sort by each column across a page boundary; bulk
upload with one deliberately failing file (partial success); an admin training a classifier
from 5 samples and a new document receiving that type; an admin adding a detector and a
matching document being escalated with offsets-only findings.

Also added: an assertion that the deployed route table matches the source route table —
the specific check that would have caught the stale-image 404.

The existing hermetic suites are kept; they are fast and they guard logic. The Playwright
layer guards wiring. Neither substitutes for the other.

---

## 8. Invariants touched

| Invariant | Interaction |
|---|---|
| #1 API never touches bytes on write path | Preserved. Completion checks metadata only; bulk upload still PUTs browser to storage. |
| #2 Workers are the only automated classifier writer | Preserved. Prototype training writes no classification; re-classification goes through a worker. |
| #4 Journal around every stage | **Restored** — currently violated by the non-exhaustive taxonomy (F1). |
| #6 Single extraction/embedding pass | Preserved. Prototypes reuse stored embeddings. |
| #10 Pattern + validator + context words | Enforced at schema and form level for admin detectors. |
| #11 Calibrated ML probabilities | Untouched. Prototypes are a separate signal and make no calibration claim. |
| #12 Offsets only, never matched text | Preserved via `build_finding()`. |
| #17 / #18 Content split, preview separate from download | Preserved. F15 only distinguishes "not ready" for callers already authorised. |
| #26 RLS tenant scoping | Extended to `doc_types`, `doc_type_prototypes` and `detector_rules`. |
| #31 Cross-tenant 404 parity | Preserved. F15 changes only the authorised-caller case. |
| #32 Cursor pagination, no OFFSET | Preserved. Sorting extends the keyset tuple rather than adding OFFSET. |
| #33 Client checks cosmetic | Preserved. All new admin routes gated server-side on `MANAGE_TAXONOMY`. |

Any new `Action` enum member must be added to **both** `domain/models.py:85-96` and
`frontend/src/security/permissions.ts` — they are hand-mirrored with no codegen.

---

## 9. Risks

- **Migration 0006 touches RLS on `doc_types`**, which is currently outside RLS and is read
  by the seed migration. Adding a policy risks making global types invisible; the policy
  must admit `tenant_id IS NULL` for global rows.
- **Per-tenant `Taxonomy` construction** moves a pure-default call onto a DB read in the
  worker path. `classify()` must stay pure, so the taxonomy is resolved at the task boundary.
- **Playwright in CI** requires the compose stack. It is marked and kept out of the default
  `npm run test` so the fast suite stays hermetic, mirroring the backend's
  `-m "not integration"` convention.
- **Bulk upload concurrency** interacts with `--pool=solo` on the workers: many files land
  quickly and then process strictly serially. This is correctness-safe, but the UI must not
  imply parallel processing.

---

## 10. Documentation updates

`README.md` (invariant matrix rows for #4, #10, #26 and #32; new endpoints; deviations
ledger), `AGENTS.md` (repo layout for new modules), `PROGRESS.md` (Wave 8 entry,
verification gates, revised Phase-2 backlog), `backend/README.md`,
`frontend/FRONTEND_REVIEW.md`, and `ml/ML_IMPLEMENTATION_PLAN.md` (mark section 5
implemented and correct the migration number).
