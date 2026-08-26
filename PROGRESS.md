# PROGRESS / HANDOFF REPORT

**Run**: Ultrawork build of the Secure Document Management System backend foundation.
**Interrupted**: 2026-08-26 ~14:15 PKT (laptop close) during **Wave 5A** (end-to-end verification).
**Repo state at handoff**: clean tree, 20 commits on top of `0f31baf init commit`, all gates green.

---

## 1. What we set out to do

Backend-first build of the self-hosted DMS per `AGENTS.md` + `Docs/document-management-system-spec.pdf`, with user amendments:

1. **No LLM layer** — ML failure/low-confidence routes directly to human review (`decided_by ∈ {rules, ml, human}`; `classification/llm/` deliberately never created).
2. **Kaggle-hosted training prep** — `/ml` toolkit: synthetic corpus generator, hard-gated dataset exporter, calibrated trainer template, v1 artifact contract.
3. **PII scope locked** to banking (account/card numbers) + personal (passport, CNIC) only — 4 recognizers registered.
4. **Rules + ML are placeholders this phase** (real validators, stubbed scanners routing to review); parsing / DB / uploads / workers / auth / policy fully built.
5. Small atomic conventional commits; READMEs updated throughout; security invariants treated as controls.

## 2. Done — wave by wave (all committed)

| Wave | Deliverables | Commits |
|---|---|---|
| 0 | Scaffold: pyproject (ruff ALL-subset/mypy strict), frozen `Settings`, compose stack (pgvector-pg16, redis, minio, clamav, api/worker/worker-ocr one image), alembic skeleton, READMEs | `eb85453` `07cb384` `149a913` |
| 1 | Pure domain policy (two-axis access + max-wins aggregation, Internal floor #9) · 16-table schema mirroring spec §6 (deferred circular FK #22, rank≠PK #23, no-cascade audit #24) · Storage protocol + local(HMAC dev-presign)+S3 backends, primary immutability #16 · TokenVerifier protocol, DevJWT shim (dev-gated), OidcJwksVerifier cached-JWKS #7, role→action matrix (PREVIEW≠DOWNLOAD #18) · `/ml` Kaggle toolkit (Faker en_PK corpus, double-gated real-text export, CalibratedClassifierCV trainer, artifact_contract.md v1) | `1cb9dee` `3df644d` `6075294` `08ddbcd` `ed85472` `2c429c5` |
| 2 | Migrations 0001 schema / 0002 monotonic trigger + RLS(tenant GUC) + grants(app role no UPDATE/DELETE on access_log #24) / 0003 seed · Extraction (puremagic sniffing, extension ignored #19, pdf/docx/xlsx handlers, OCR stub, keyword fallback + contract tests) · Classification placeholders (4 entity types, real validators incl Luhn/CNIC-province, stubbed scanners, review-routing cascade rules→ml≥0.85→review, artifact loader absent→review) | `5fbf0c4`(fix) `b81d4f4` `2eae135` `d648a99` `c6e32bb` |
| 3 | Celery chain scan→extract→keywords→embed(null vector)→classify→index(tsvector) with processing_jobs journal around every stage #4, sha256 idempotency #5, raw clamd INSTREAM client + fail-closed dev gate, quarantine→primary promotion · RFC7807 envelope w/ path-identical cross-tenant 404s #31, presigned upload intent+complete #1, cursor-only listing #32, content split-stream vs presigned #17 w/ same-tx audit #30, findings offsets-only #12, human reclassify append-only, dev-storage router | `3b0eb86` `8232f2d` |
| 4 | Review queue/resolution (human lower audited same-tx), read-only audit endpoints #24, taxonomy admin CRUD, `/v1/events` 501 stub · Hybrid search: visibility predicate composed INSIDE both arms pre-rank #27, RRF fusion scaffold (vector arm zero-rows until embeddings), facets/snippets from filtered set only #28 | `59a6458` `01965cf` |
| 5A (partial) | `mint_dev_token.py` minter (verified working) · malware-halt fix: chain failure now flips `documents.status='failed'` (#4 SQL-visible outcome) | `2f3f830` `7b8c530` |

### Gate status at handoff (all self-run, verbatim tails)

```
pytest -q                  → 466 passed, 3 skipped, 5 deselected   (unit; hermetic, no infra)
pytest -m integration      → 4 passed, 1 skipped                  (migration roundtrip, monotonic
                                                                   trigger, RLS isolation, grants;
                                                                   skip = MinIO-needing test)
mypy app                   → Success: no issues found in 61 source files (strict)
ruff check . && ruff format --check . → clean (125 files)
docker compose ps          → postgres/redis/minio/clamav all healthy
alembic roundtrip          → upgrade head → downgrade base → upgrade head proven on real PG
```

## 3. Environment facts & incidents fixed (do not re-trip these)

- **Host port 5432 is owned by a native Windows PostgreSQL 18 service** (`postgresql-x64-18`). Our container publishes on **55432** (`fix(compose)` commit). NEVER connect to 5432. Integration conftest default URL: `postgresql://docmgmt:docmgmt@localhost:55432/docmgmt`.
- A stale postgres volume once held a wrong init password → recreated fresh; if auth fails again after volume surgery, recreate volume then re-run `ALTER USER docmgmt PASSWORD 'docmgmt'`.
- Windows git-bash: no GNU `timeout`; use `curl --max-time`/python waits. Celery workers use `--pool=solo`.
- venv: `backend/.venv` (host Python 3.14.4; pymupdf/python-docx/openpyxl/puremagic/fpdf2/faker installed; sklearn/torch/spacy intentionally NOT installed — guarded lazy imports everywhere).
- Leftover QA container `dms-e2e`... removed; throwaway DB `dms_e2e` dropped; uvicorn on 8901 killed at handoff. Compose stack left UP and healthy.
- PyMuPDF is AGPL/commercial dual-licensed — flagged for sign-off if this ever ships commercially (swap seam = extraction registry).

## 4. Interrupted mid-flight: Wave 5A (end-to-end verification)

**Goal**: prove the whole system against real infra: fresh DB + migrations → minted dev tokens → presigned PUT upload of a real PDF → worker chain (eager or live) → review item → human raise then LOWER via resolve → audit rows + append-only classification history proof → content split (Confidential streams w/ Range+audit; Internal redirects to ≤120s presign) → cross-tenant 404 byte-parity across detail/content/findings/jobs → EICAR rejection against live ClamAV → teardown.

**Progress when interrupted** (agent was killed by laptop close, task id `bg_7315ca84`, session `ses_fc4b381d5ffeiMbS3Ozix55bsa`):

| Step | State |
|---|---|
| S0 bootstrap (fresh db + migrations) | ✅ done (`dms_e2e` existed; now dropped for cleanliness — recreate on resume) |
| S1 tokens (`backend/scripts/mint_dev_token.py`) | ✅ done, CLI verified, committed |
| S2 upload happy path (uvicorn was live on 127.0.0.1:8901) | 🟡 in progress — server was up and driving curl flows; uncommitted worker fix it produced suggests it reached/exercised the pipeline-halt path |
| S3 pipeline ready-state + review queue visibility | ❓ unknown |
| S4 human lower + audit + append-only proof | ❓ unknown |
| S5 content split (stream vs redirect, Range, audit counts) | ❓ unknown |
| S6 cross-tenant 404 parity | ❓ unknown |
| S7 EICAR vs ClamAV | ❓ unknown (its last visible code work was the malware-halt fix → likely here or in S2/S3) |
| S8 teardown | ✅ completed manually at handoff (PID killed, DB dropped, port free) |

**Not yet created**: root `scripts/e2e.sh`, `backend/tests/integration/test_e2e_upload_to_review.py`.

**One defect found & fixed so far** (committed `7b8c530`): malware-detected halt left documents stuck in `processing`; now flips to `failed` so pipeline state stays SQL-answerable (#4).

### To resume Wave 5A

Re-run an e2e agent with the original prompt essence, or execute manually:

```bash
cd backend
# 1. fresh db + migrations
docker exec doc-management-system-postgres-1 psql -U docmgmt -c "CREATE DATABASE dms_e2e"
.venv/Scripts/python.exe -c "<alembic programmatic upgrade pattern from tests/integration/conftest.py>"
# 2. tokens (three principals): admin@T1 c4/HQ, employee@T1 c2/Eng, outsider@T2 c4
.venv/Scripts/python.exe scripts/mint_dev_token.py --sub dev-admin --tenant <uuid> --role admin --clearance 4
# 3. boot API locally (port 8901, DATABASE_URL -> dms_e2e, STORAGE_BACKEND=local)
# 4. walk scenarios S2..S7 above with curl; assert every step's observable
# 5. deliver scripts/e2e.sh + tests/integration/test_e2e_upload_to_review.py (@pytest.mark.integration)
# 6. teardown: drop dms_e2e, kill uvicorn
```

Known friction points the agent was told to expect (verify when resuming): `deps.get_storage()` local root derivation, users-row auto-provision on first upload (oidc_sub lookup), review items only exist after classify stage runs (`needs_review=True` inserts them).

## 5. What remains overall

1. **Wave 5A completion** (above) → then commit e2e script + integration test.
2. **Wave 5B — docs & final QA**:
   - Root/backend/ml README sweep: invariant enforcement matrix (which layer enforces which of the 33), deviations ledger (LLM omitted; events=501; SCAN_ENABLED dev bypass fail-closed-in-prod; search snippet source gap — `document_text` stores no raw text so keyword arm uses `ts_headline(cast(tsv as text))` placeholder; search endpoint has no cursor — fused ranks unstable, deferred deliberately; PyMuPDF AGPL flag).
   - Run ALL gates honestly and paste outputs into the PR/handoff.
   - **Reviewer-gate pass** (triggered: >30 files, multi-hour run): spawn a high-rigor reviewer over goal/scenarios/evidence/diff; verify each criterion-cited concern; max two delta re-reviews.
3. **Phase-2 backlog** (explicitly out of scope this run, per user):
   - Wire real recognizer matching into the stubbed `scan()` bodies (validators + context-scoring helper already real and tested).
   - Real ML: drop Kaggle-produced `model.joblib` into the loader path (contract v1 already enforced); embeddings stage stops being a no-op; HNSW index backfill.
   - OCR (Tesseract wave) on its own queue; SSE events endpoint; MinIO-backed integration test enablement; search raw-text store for true snippets; frontend.

## 6. Cheat-sheet

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                 # unit suite (hermetic)
.venv/Scripts/python.exe -m pytest -m integration     # needs compose postgres @55432
.venv/Scripts/python.exe -m mypy app && python -m ruff check . && python -m ruff format --check .
docker compose up -d                                   # infra (postgres:55432, redis, minio:9000/9001, clamav:3310)
cd ../ml && ../backend/.venv/Scripts/python.exe -m pytest tests -q   # ml toolkit (21 passed)
```

Commit style: conventional, small atomic (`feat|fix|refactor|test|docs|chore(scope): summary`). Never commit `.env`/weights/real PII. Tests must stay runnable without MinIO/Keycloak.
