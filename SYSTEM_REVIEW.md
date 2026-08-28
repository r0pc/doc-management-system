# System Review — Secure Document Management System

**Date:** 2026-08-28
**Reviewed at:** `main` @ `4dbe90f` + uncommitted ML-wave working tree (10 modified files, 2 untracked)
**Method:** Independent read of the source tree plus live execution of every quality gate. Nothing in this report is taken from `PROGRESS.md`, `README.md`, or `PROJECT_REVIEW.md` on trust — where those documents disagree with observed behaviour, the observed behaviour is reported and the drift is noted.

---

## 0. Resolution Status (updated 2026-08-28, branch `fix/production-readiness`)

Everything below was written against `main` @ `4dbe90f`. The findings have since been worked; this section records what actually changed. **The body of the report is left as originally written** — it is the record of what was found, not a live status page.

| § | Finding | Status |
|:--|:--|:--|
| 4.1 | Every upload fails at `extract` | ✅ Fixed — `_ensure_sha256` in `tasks.py`, called from promotion *and* extract (promotion alone misses the dev scan-skip path). Types corrected so mypy can see it. |
| 4.2 | Integration suite red | ✅ Fixed — 7 passed, 1 skipped (was 5 failed / 1 passed). |
| 4.3 | `check_monotonic` weakened | ✅ Fixed — migration `0005` drops the version-equality guard, keeps 0004's current-classification scope. New regression test covers cross-version lowering. |
| 4.4 | `access_log` RLS, no backfill | ✅ Fixed — `0005` backfills from the owning document, parks unattributable rows under the nil UUID, sets `NOT NULL`. |
| 4.5 | Predicted `doc_type` discarded | ✅ Fixed — resolves against existing `doc_types` rows; never auto-creates taxonomy from model output. |
| 4.6 | ML deps in no environment | ✅ Fixed — image installs `.[ml]` with CPU-pinned torch; encoder weights baked in at build with `HF_HUB_OFFLINE=1`; artifact mounted read-only. |
| 4.7 | Double-encode breaks #6 | ✅ Fixed — embed-stage vector threaded into `predict_type`. |
| 4.8 | Prediction failure crashes ingestion | ✅ Fixed — every failure degrades to review, per the module's stated contract. |
| 4.9 | Metrics not trustworthy | ⚠️ **Open by necessity** — cannot be closed without real labelled data. Now surfaced: `load_artifact` warns on a manifest with no real slice, the threshold is configurable, and it is item 1 of the Phase-2 backlog. |
| 4.10 | `ruff format --check` failing | ✅ Fixed — 132 files formatted, gate clean. |
| 4.11 | Vector arm `WHERE false()` | ✅ Fixed — pgvector cosine arm live, degrades to keyword-only. Snippets remain empty (documented deviation #4). |
| 4.12 | Hardcoded app-role password | ⚠️ **Open** — still a literal in `0002` and compose. Phase-2 item 6. |
| 4.13 | Thin frontend coverage | ✅ Fixed — 12 → 70 tests, which exposed four real defects (see below). |
| 4.14 | Stray `install.cmd` | ✅ Removed. |
| 5 | Documentation drift | ✅ Fixed — `README.md` and `PROGRESS.md` reconciled with observed behaviour. |

**Additional defects found while fixing the above** (not in the original report):

- `main.py` mounted `/v1/dev-storage` on `storage_backend == "local"` **alone** — and that is the default. A production deployment that never set `STORAGE_BACKEND` exposed object read/write signed with an HMAC secret that is empty in prod. Now gated on `env == "dev"` as well.
- `LevelBadge` rendered an unclassified document as **Public** — its fallback chain ended in `'public'`, inverting invariant #9 in the UI.
- `isLoweringLevel` was a membership test over two hardcoded arrays, so `Restricted → Confidential` and `Internal → Public` triggered no downgrade warning and no justification prompt.
- `loginWithPersona` failed **open**: on a token-mint failure it kept `user` populated while `token` stayed null, rendering a full admin shell for a session with no credentials.
- The API client would send the bearer token to an absolute URL, so a presigned or attacker-supplied URL was handed the session credential.
- `test_monotonic_trigger`'s seed never set `documents.current_classification_id`, so the trigger short-circuited and the test passed against a **fully disarmed** trigger. My §4.3 diagnosis was incomplete: removing the version guard alone would not have made it pass.

**Gates now:** backend 527 passed · integration 7 passed · mypy clean (62 files) · ruff check + format clean · ML 21 passed · frontend 70 passed, tsc clean, build succeeds.

---

## 1. Executive Summary

The system is a genuinely well-architected piece of work. The domain layer is pure and framework-free, authorization is a single two-axis function used by both API and workers, the schema encodes its invariants at the database level (deferred FKs, RLS, an append-only classification history, a monotonicity trigger), and the search layer composes its visibility predicate *into* both ranking arms rather than filtering after the fact. The discipline visible in the committed code — invariant IDs cited at every enforcement seam, documented deviations rather than silent ones — is above the norm.

That architecture is currently sitting on top of a **broken ingestion path**. Verified live against the running compose stack: every real upload fails at the `extract` stage with a `TypeError` and lands in `documents.status = 'failed'`. The cause is a one-line omission introduced when migration `0004` made `document_versions.blob_sha256` nullable. The 465-test hermetic suite does not catch it because those tests seed the pipeline context with a real digest, so they exercise a state production never reaches.

Alongside that, the integration suite — the only layer that tests the system as a system — is **red on 5 of its 6 tests**, while `PROGRESS.md` reports it green. Three of those failures are direct consequences of migration `0004`, which was committed without re-running the suite it invalidated. One of them is a real weakening of a stated security invariant.

The in-flight ML wave is roughly half-wired: inference code exists and is unit-tested against fakes, but the required libraries are installed in no environment (host venv or container), the trained artifact is git-ignored, the predicted document type is discarded before it reaches the database, and the model's reported metrics — perfect recall on every class, synthetic data only — are not evidence of anything.

**Verdict: strong foundation, not currently functional end-to-end.** Section 4 lists the blocking defects; the top three are small, well-localised fixes.

---

## 2. Verified Gate Results

Every row below was executed during this review. Compare against the "all green" table in `PROGRESS.md` §3.

| Gate | Command | Claimed | **Observed** |
|---|---|---|---|
| Backend hermetic tests | `pytest -q` | 466 passed | ✅ **465 passed**, 3 skipped, 7 deselected |
| Backend integration tests | `pytest -m integration -v` | 6 passed | ❌ **5 failed, 1 passed, 1 skipped** |
| Backend typecheck | `mypy app` | 0 issues, 61 files | ✅ **0 issues, 62 files** (strict) |
| Backend lint | `ruff check .` | All passed | ✅ **All checks passed** |
| Backend format | `ruff format --check .` | *(listed in README as part of the gate)* | ❌ **13 files would be reformatted** |
| ML toolkit tests | `pytest tests -q` | 21 passed | ✅ **21 passed** |
| Frontend typecheck | `tsc --noEmit` | clean | ✅ **clean** |
| Frontend tests | `vitest run` | 12 passed / 4 files | ✅ **12 passed / 4 files** |
| Frontend build | `vite build` | 293 kB JS | ✅ **329.9 kB JS, 30.6 kB CSS, 47 s** |
| Compose stack | `docker ps` | 4 healthy | ✅ postgres:55432, redis:6379, clamav:3310, minio:9000/9001 all healthy |

### Integration failures in detail

```
FAILED test_access_log_grants.py::test_docmgmt_app_cannot_update_or_delete_access_log
FAILED test_e2e_upload_to_review.py::test_full_e2e_upload_to_review_lifecycle
FAILED test_e2e_upload_to_review.py::test_e2e_clamav_eicar_malware_rejection
FAILED test_migrations_roundtrip.py::test_upgrade_downgrade_upgrade_roundtrip
FAILED test_monotonic_trigger.py::test_automated_lowering_blocked_human_allowed_higher_allowed
```

Two of these (the e2e pair) additionally require `CLAMAV_HOST=localhost` to even reach their assertions — the default `clamav` resolves only inside the Docker network, and no `.env` exists. With that set, the EICAR test passes and the lifecycle test still fails on the ingestion bug below.

---

## 3. What Is Actually Built

**Scale:** 33 commits · 14,588 lines of backend Python (app + tests + migrations) · 3,977 lines of frontend TypeScript · 1,252 lines of ML tooling · 16 database tables · 21 HTTP routes · 4 migrations · 47 backend test modules / 325 test functions.

### Backend — `backend/app/` (62 modules, 6,299 lines)

| Layer | State | Notes |
|---|---|---|
| `domain/` | **Complete** | `policy.can_access` (two-axis: clearance rank × department subtree), `aggregate_level` (max-wins with count-aware CNIC escalation, Internal floor). Zero framework imports; a purity test enforces this. |
| `db/` | **Complete** | 16 tables. Deferred circular FK (`documents.current_classification_id`), `security_levels.rank` as a non-PK unique column, `access_log` with no cascades. |
| `alembic/` | **Complete, with a regression** | `0001` schema → `0002` monotonic trigger + RLS + grants → `0003` taxonomy seed → `0004` audit tenant isolation. See §4.3/§4.4. |
| `storage/` | **Complete** | Protocol + Local (HMAC dev presign) + S3 backends. `PrimaryBlobGuard` rejects overwrite and delete on the primary bucket. |
| `extraction/` | **Complete except OCR** | `puremagic` magic-byte sniffing (extensions ignored), PDF/DOCX/XLSX handlers, frequency-based keyword fallback. `ocr.py` raises `NotImplementedError` and routes to the `ocr` queue. |
| `classification/rules/` | **Complete** | All four recognizers have **real** `scan()` bodies — pattern + structural validator (Luhn, CNIC province digit, PK-IBAN shape) + ±50-char context scoring. |
| `classification/ml/` | **Partially wired (uncommitted)** | Artifact contract validation is solid. Inference newly implemented but cannot execute anywhere — see §4.6. |
| `workers/` | **Complete, currently broken** | Fixed 6-stage chain, `processing_jobs` journal around every stage, real clamd INSTREAM client, quarantine→primary promotion. See §4.1. |
| `api/v1/` | **Complete** | 21 routes. RFC 7807 envelopes, keyset pagination throughout, split content delivery (303 vs streamed 206), findings as offsets only, same-transaction audit. |
| `search/` | **Keyword-only** | Visibility predicate genuinely composed into both arms; RRF math is pure and unit-tested. Vector arm hard-disabled. See §4.8. |

### Frontend — `frontend/src/` (41 files, 3,977 lines)

React 18 + TypeScript strict + Vite + Tailwind, GitHub Primer palette, light/dark theme provider with `localStorage` persistence, TanStack Query. Seven feature areas: upload wizard (direct presigned PUT with progress), document library, document drawer with split content delivery, review queue, search with facets, audit viewer, taxonomy admin. Cosmetic permission gating via `<Can>` / `usePermissions`. Five dev personas across roles/clearances; tokens minted by the backend `/v1/dev/token` endpoint.

### ML — `ml/` (1,252 lines)

Synthetic corpus generator (Faker `en_PK`, 7 doc types), double-gated real-text exporter, `CalibratedClassifierCV` trainer, Kaggle notebook template, `artifact_contract.md` v1. A trained artifact exists locally at `backend/var/models/model.joblib` (164 kB) with `metrics.json`.

---

## 4. Findings, Ranked

### 4.1 🔴 BLOCKER — Every real upload fails at the `extract` stage

**Verified live.** `documents.status` goes to `failed`, not `ready`.

```
File "app/workers/tasks.py", line 279, in _extract_body
    _write_derived_json(ctx["sha256"], {...})
TypeError: expected string or bytes-like object, got 'NoneType'
```

The chain:

1. `uploads.py:158` inserts the version row with `blob_sha256=None` (the digest is not known at intent time).
2. Migration `0004` made that column nullable to allow it.
3. `jobs.py:load_version_context` returns that `None` — despite being annotated `-> tuple[uuid.UUID, str]`.
4. `process_upload_chain` puts it into `ctx["sha256"]`.
5. `_promote_to_primary` computes the real digest and **updates `ctx["key"]` but never `ctx["sha256"]`** (`tasks.py:239-240`).
6. `_extract_body` passes `None` into `derived_key()`, whose regex validator raises `TypeError`.
7. `_run_stage` catches `(ValueError, TypeError)`, journals "unsupported or malformed content", and marks the document failed — so the real cause is buried behind a misleading error string.

**Why 465 unit tests miss it:** `tests/workers/conftest.py:30` seeds `SHA256 = hashlib.sha256(PAYLOAD).hexdigest()` into the context. The tests never construct the `None` state that production always constructs.

**Fix** — one line, `backend/app/workers/tasks.py` after line 239:

```python
    _storage().delete(ctx["key"])
    ctx["key"] = key
    ctx["sha256"] = digest   # ← add: downstream stages key derived artifacts on this
```

Then tighten `load_version_context`'s return type to `tuple[uuid.UUID, str | None]` so the type system stops hiding this class of bug, and add a worker test whose context starts with `sha256=None`.

### 4.2 🔴 BLOCKER — Integration suite is red while documentation reports it green

`PROGRESS.md` §3 and §5 present the integration suite and all eight S0–S7 scenarios as verified. They are not, today. Three of the five failures trace to migration `0004`, committed in `9041c99` ("review changes fixed") without re-running the suite it invalidated.

This matters beyond the individual tests: the integration layer is the only place this system is tested *as a system*, and it is the layer whose green status is being cited as the release gate.

### 4.3 🔴 HIGH — Migration `0004` weakened the `check_monotonic` trigger

`test_monotonic_trigger` fails with `DID NOT RAISE` — an automated reclassification that lowers a security level is now **permitted** where it was previously blocked.

The `0002` trigger blocked any non-human insert whose rank was lower than *any* prior classification of the document. The `0004` rewrite only compares against the current classification **and only when `curr_version_id = NEW.version_id`**:

```sql
IF curr_version_id = NEW.version_id THEN
    ... IF new_rank < curr_rank THEN RAISE EXCEPTION ...
```

An automated writer producing a classification on a *different* version now bypasses the check entirely. Invariant #8 states the DB trigger is the authority for monotonicity; that authority is materially narrower than documented, and the change is undocumented in both the migration docstring and `README.md`.

**Decide explicitly:** if per-version monotonicity is the intended semantics, say so in the migration and update the test and the invariant matrix. If not, restore the document-scoped check.

### 4.4 🟠 HIGH — Migration `0004` adds RLS to `access_log` with no backfill

`0004` adds a nullable `tenant_id` to `access_log`, then enables `FORCE ROW LEVEL SECURITY` with `USING (tenant_id = current_setting('app.tenant_id')::uuid)`.

- **No backfill.** Every pre-existing audit row keeps `tenant_id = NULL` and becomes permanently invisible to `docmgmt_app` — audit history silently vanishes from `GET /v1/audit` on upgrade. For an append-only audit log this is the worst possible failure mode: no error, just missing rows.
- **`test_migrations_roundtrip` explicitly asserts `access_log must not carry RLS`** and now fails. Two parts of the codebase encode contradictory intentions about the same table.
- `test_access_log_grants` fails with `new row violates row-level security policy` because it inserts without binding the GUC.

The application path itself is fine — all 11 `record_audit` call sites pass a real `tenant_id`, and `bind_tenant` sets the GUC. But `record_audit`'s signature still accepts `tenant_id: uuid.UUID | None`, and a `None` would now be silently rejected by the `WITH CHECK` clause rather than caught. Tighten that type.

### 4.5 🟠 MEDIUM — ML: the predicted document type is thrown away

`jobs.py:291` hardcodes `doc_type_id=None` on every classification insert. `ClassificationOutcome.doc_type` carries the ML label all the way from `pipeline.classify` and is then dropped on the floor.

Consequence: even with a fully working model, `documents` never receives a document type, `DocType` joins in search resolve to `NULL`, and the `doc_type` facet is permanently `{"unknown": N}`. The entire ML wave produces no observable effect until this is wired to a `doc_types` lookup.

Related: the trained artifact contains a `security_level` head, but `pipeline.classify` only ever calls the `doc_type` head. Security level always comes from rules aggregation — which, with no PII present, is the Internal floor. Half the trained model is dead weight.

### 4.6 🟠 MEDIUM — The ML inference path cannot execute in any environment

Verified: `sentence_transformers`, `sklearn`, and `joblib` are **all absent** from `backend/.venv`.

- `backend/Dockerfile` runs `pip install ".[parsers]"` — the `ml` extra is never installed, so the containers can't either.
- The Dockerfile does not `COPY var/`, so `var/models/model.joblib` doesn't exist in the image.
- `backend/var/` is git-ignored (`.gitignore:21`), so the trained artifact exists **only on this machine** and is not reproducible from the repo.
- `MODEL_ARTIFACT_PATH` is not set in any compose service.

Net effect: `load_artifact` returns `None` everywhere, `predict_type` returns `None`, and 100% of documents route to human review — which is the correct fail-safe, but means the wired inference is currently unreachable code. Decide on artifact distribution (bake into image / mount a volume / object storage) before calling the ML wave done.

### 4.7 🟠 MEDIUM — The new embed stage double-encodes, violating invariant #6

Invariant #6 is "single extraction & embedding pass reused by classification and search." The uncommitted change breaks the second half:

- `_embed_body` (`tasks.py:301`) encodes `text[:4000]` and stores the vector in the derived JSON.
- `_classify_body` then calls `run_classification` → `predict_type` → `_predict_with_artifact`, which **encodes the same text again** via `_get_encoder(...).encode(...)`.

The stored embedding is never reused for classification. Two forward passes per document where the invariant mandates one. Fix by threading the already-computed vector into `classify` and giving `_predict_with_artifact` a pre-computed-embedding path.

Also in the same change: `_embed_body` wraps everything in `except Exception` and logs a warning, so an embedding failure is invisible except in logs. That is a defensible degradation policy, but it should be journaled as a `skipped` stage rather than a silent success.

### 4.8 🟠 MEDIUM — New ML code can crash the classify stage

`loader.py` opens with an explicit contract: *"any incompatible or unloadable artifact is logged-and-None — never a crash."*

The new `_predict_with_artifact` raises `ArtifactIncompatibleError` when `models.doc_type` is missing from the payload. `predict_type` catches only `MlUnavailableError`. So a malformed-but-loadable artifact propagates an exception out of `classify`, past `_run_stage`'s `(ValueError, TypeError)` handler, and fails the whole chain — the opposite of the documented behaviour.

Widen the `except` in `predict_type` to `(MlUnavailableError, ArtifactIncompatibleError)`, and consider a bare `except Exception` around the prediction so an unexpected sklearn error degrades to review rather than failing ingestion.

### 4.9 🟠 MEDIUM — The model's reported metrics are not evidence

`backend/var/models/metrics.json`:

```json
"doc_type":       { "real": null, "synthetic": { "per_class_recall": { ...all 1.0... }, "support": 600 } }
"security_level": { "real": null, "synthetic": { "per_class_recall": { ...all 1.0... }, "restricted_recall": 1.0 } }
```

Perfect recall on all 7 document types and all 3 security levels, with `real: null` on both — no real-document evaluation was performed at all. The corpus is generated by deterministic templates in `ml/templates.py`; a linear classifier over sentence embeddings is almost certainly separating template fingerprints, not document semantics. `restricted_recall: 1.0` satisfies invariant #14 vacuously.

This model should not be treated as validated. Before deployment it needs a held-out **real** slice, and the 0.85 cascade threshold needs calibration against that slice rather than against synthetic text where every probability saturates.

### 4.10 🟡 LOW — `ruff format --check` fails on 13 files

`README.md` lists `ruff check . && ruff format --check .` as the lint gate. The second half fails. Nine of the thirteen are committed files unaffected by the current WIP (`app/api/v1/documents.py`, `uploads.py`, `dev_auth.py`, `alembic/versions/0004_*.py`, and four test modules), so this drift predates the ML wave — the format check appears never to have been enforced in CI.

`ruff format .` resolves it; adding it to a pre-commit hook prevents recurrence.

### 4.11 🟡 LOW — "Hybrid" search is keyword-only, and activation is not a one-line swap

`compose_vector_subquery` ends in `.where(false())` — the vector arm returns zero rows by construction. Its docstring claims activation is "a predicate swap, not a redesign," but `build_visible_candidates` does not select `DocumentText.embedding` into the candidate subquery, so the column isn't available to rank on. Activation requires touching both functions plus the query-embedding path.

Separately, `_load_snippet_text` returns `{}` unconditionally, so **every search result ships an empty snippet**. This is documented as deviation #4 in `README.md`, but the frontend renders the field regardless.

### 4.12 🟡 LOW — Hardcoded application-role password

`alembic/versions/0002_security_hardening.py:114` — `CREATE ROLE docmgmt_app LOGIN PASSWORD 'docmgmt'` — with the same literal repeated in three `docker-compose.yml` services. The compose credential swap in the current WIP correctly moves `migrate` to the owner role and the app services to `docmgmt_app`, but the password is still a constant baked into a migration that runs in every environment.

### 4.13 🟡 LOW — Frontend test coverage is thin

12 tests across 4 files (`LevelBadge`, `ThemeProvider`, `Can`, `utils`) against 41 source files and 3,977 lines. Untested: the upload wizard and its presigned-PUT flow, `DocumentDrawer`'s split content delivery, the reclassify and review-resolve modals, search, audit, taxonomy admin, and the entire `api/client.ts` error/problem-details path.

The three tested units are the three least likely to break. The security-relevant frontend behaviour — that the upload path never routes bytes through the API, that high-clearance content streams while low-clearance redirects — has no coverage.

### 4.14 🟡 LOW — Stray file at the repository root

`install.cmd` (untracked, 8.3 kB) is the Claude Code Windows bootstrap installer. It has nothing to do with this project. Delete it.

---

## 5. Documentation Drift

`PROGRESS.md` and `README.md` are detailed and mostly excellent, but several statements no longer match the code. Since these documents are the handoff artifact, the drift is itself a defect.

| Claim | Location | Reality |
|---|---|---|
| Integration suite: 6 passed | `PROGRESS.md` §3 | 5 of 6 fail |
| All S0–S7 scenarios verified | `PROGRESS.md` §5 | S3/S4/S7 currently fail; S3 fails on §4.1 |
| Migrations `0001→0002→0003` | `PROGRESS.md` §5 (S0) | `0004` exists and is unmentioned anywhere in the docs |
| "Rules … are placeholders this phase", "stubbed scanners" | `PROGRESS.md` §1.4, `recognizers.py:5` | All four `scan()` bodies are fully implemented |
| "`auth.tsx` mints real HS256 tokens using `crypto.subtle`" | `PROGRESS.md` §4 | `auth.tsx:119` POSTs to the backend `/v1/dev/token`. (The current design is *better* — no secret in the browser — but the doc is wrong.) |
| "predict_type … ALWAYS returns None today" | `loader.py:88` docstring | No longer true after the WIP change |
| Invariant #11: "calibrated ML probabilities; ML ≥ 0.85" | `README.md` matrix | True in code, unreachable in practice (§4.6) |
| Invariant #6: single embedding pass reused | `README.md` matrix | Violated by the new embed stage (§4.7) |
| 466 backend tests | `PROGRESS.md` §3 | 465 |

---

## 6. Invariant Reality Check

Of the 33 invariants in `AGENTS.md`, most are genuinely enforced at a real seam — the enforcement matrix in `README.md` is not decoration. The following are the ones where enforcement is weaker than claimed:

| # | Invariant | Status |
|---|---|---|
| **#6** | Single extraction & embedding pass reused | ❌ Double-encode introduced by the WIP embed stage |
| **#8** | `check_monotonic`: automated cannot lower | ⚠️ Narrowed to same-version by `0004`; test fails |
| **#11** | Calibrated ML ≥ 0.85 else review | ⚠️ Code correct; unreachable — deps absent everywhere |
| **#14** | Per-class recall on highest label near 1.0 | ⚠️ Satisfied only on synthetic data; `real: null` |
| **#24** | `access_log` no cascade, no UPDATE/DELETE grant | ⚠️ Grants hold, but `0004` adds unbackfilled RLS; two tests now contradict each other |
| **#27/#29** | Permission filter in *both* arms, RRF fusion | ⚠️ Structurally correct, but the vector arm is `WHERE false()` — single-arm in practice |
| **#5** | sha256 idempotency | ❌ The digest never reaches the pipeline context (§4.1) |

Everything else — #1, #2, #3, #4, #7, #9, #10, #12, #13, #15–#23, #25, #26, #28, #30–#33 — holds at the seams cited in the enforcement matrix, as far as static review and the passing hermetic suite can establish.

---

## 7. Recommended Order of Work

**Before anything else — restore a working system (est. under a day):**

1. Add `ctx["sha256"] = digest` in `_promote_to_primary` (§4.1). Add a worker test starting from `sha256=None`.
2. Fix `load_version_context`'s return annotation to `tuple[uuid.UUID, str | None]`.
3. Resolve the `0004` contradictions (§4.3, §4.4): decide the intended `check_monotonic` semantics and the intended `access_log` RLS posture, update the migration and the two contradicting tests together, and add a `tenant_id` backfill.
4. Re-run `pytest -m integration` with `CLAMAV_HOST=localhost` and get it to 6/6. Then document that variable, or default `clamav_host` to `localhost` outside containers.
5. Run `ruff format .` and add it to CI.

**Then — make the ML wave real (est. several days):**

6. Wire `doc_type` through to `doc_type_id` in `record_classification` (§4.5).
7. Decide artifact distribution and add `sentence-transformers`/`scikit-learn`/`joblib` to the worker image; set `MODEL_ARTIFACT_PATH` in compose (§4.6).
8. Reuse the embed-stage vector in classification (§4.7).
9. Widen exception handling in `predict_type` (§4.8).
10. Evaluate on a real held-out slice and recalibrate the 0.85 threshold before trusting any prediction (§4.9).

**Then — close the gaps:**

11. Activate the vector arm (select `embedding` into candidates, add the query-embedding path) and land a snippet store (§4.11).
12. Move the `docmgmt_app` password out of the migration into configuration (§4.12).
13. Add frontend tests for the upload flow, content split, and API error handling (§4.13).
14. Delete `install.cmd`; refresh `PROGRESS.md` and `README.md` against §5.

---

## 8. What Is Worth Preserving

Worth saying plainly, because the findings above are all problems: the parts of this system that are done are done well.

- **The domain layer is genuinely pure.** `policy.py` and `models.py` import nothing but stdlib and each other, and there is a test that enforces it. Both the API and the workers make authorization decisions through the same function. That is rarer than it should be.
- **Invariants are enforced where they cannot be forgotten.** Monotonicity in a database trigger, tenant scoping in RLS, primary-blob immutability in a mixin that rejects the operation, the search visibility predicate composed into the arms rather than applied after. These are structural guarantees, not conventions.
- **Deviations are documented rather than hidden.** The six-item ledger in `README.md` — the omitted LLM tail, the `501` events stub, the deferred search pagination, the PyMuPDF licensing isolation — is honest engineering.
- **Strict `mypy` across 62 modules and a `ruff` config selecting `S`, `B`, `ASYNC`, and `T20`** is a real bar, and it is being met.

The gap between this architecture and a working system is small and concrete. It is mostly §4.1, §4.3, and §4.4.
