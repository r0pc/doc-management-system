# Backend Review — Secure Document Management System

**Reviewed**: 2026-08-27 · commit `0f75ad6` (branch `main`, clean tree)
**Scope**: `backend/` (FastAPI + Celery + PostgreSQL 16 + Alembic), `docker-compose.yml`, `ml/`
**Method**: full read of all 61 source modules, all 3 migrations, compose/Dockerfile/entrypoint; gates re-run locally; live probe of the dev PostgreSQL role.

---

## 1. Verdict

The backend is a **well-architected, disciplined codebase with excellent structural hygiene and a small number of serious runtime defects**. Layering (pure `domain/` → `db/` → `api/`), the invariant documentation, the error envelope, and the storage abstraction are genuinely above average. Every quality gate the handoff claims does pass.

But there is a consistent pattern: **controls are proven in isolation and then not wired into the runtime path.** RLS is tested against a role the application never uses; the least-privilege grant is created and never adopted; the classification engine is fully specified and returns nothing; ClamAV is correctly implemented and pointed at the wrong host. The result is a system that looks complete at the module level and cannot complete a single upload in the shipped compose stack.

| Dimension | Rating |
|---|---|
| Architecture & layering | Strong |
| Code style / typing / lint discipline | Strong |
| Documentation-in-code | Strong (occasionally over-claims) |
| Test *count* | Strong (466 + 6 + 21) |
| Test *depth* (real SQL / real integration) | Weak |
| Runtime correctness (deployable stack) | **Broken** |
| Multi-tenant isolation as deployed | **Broken** |
| Core feature completeness (classification) | **Not implemented** |

---

## 2. Verification Gates — Re-Run Independently

All commands executed during this review, verbatim results:

```
pytest -q                    → 466 passed, 3 skipped, 7 deselected in 6.91s   ✅ (matches claim)
ruff check .                 → All checks passed!                             ✅ (matches claim)
mypy app                     → Success: no issues found in 61 source files    ✅ (matches claim)
ml/ pytest tests -q          → 21 passed in 6.17s                             ✅ (matches claim)
```

Integration suite (`-m integration`) not re-run — requires a live PG + ClamAV; it is deselected by default and was reported as 6 passed.

**The reported numbers are honest.** The caveat is what they cover — see §5.

---

## 3. Critical Findings

### C-1 — Row-Level Security is completely bypassed by the application's own DB role

**Severity: Critical · Invariant #26 not enforced at runtime**

Migration `0002_security_hardening.py` creates `docmgmt_app`, enables `ENABLE + FORCE ROW LEVEL SECURITY` on ten tables, and writes correct `tenant_isolation` policies. The integration test `tests/integration/test_rls.py` connects **as `docmgmt_app`** and proves the policies work.

The application does not use that role. `docker-compose.yml` and `.env.example` both wire:

```
DATABASE_URL=postgresql+psycopg://docmgmt:docmgmt@postgres:5432/docmgmt
```

`docmgmt` is `POSTGRES_USER`, created by the postgres image entrypoint as a **superuser**. Probed live during this review:

```
SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
→ ('docmgmt', True, True)
```

`rolbypassrls = True` means every policy is skipped for every application query, `FORCE` included. Migration `0003`'s own docstring states the mechanism — *"superusers bypass RLS entirely"* — so the behaviour was understood and simply not applied to the runtime configuration.

**Consequence.** Tenant isolation currently rests entirely on the explicit `WHERE Document.tenant_id == user.tenant_id` clauses in application code — precisely the "remembered WHERE clause" the invariant forbids. Those clauses are present in `list_documents`, `_fetch_review_page` and `build_visible_candidates`, so documents are still isolated. `_fetch_document_view` ([documents.py:239](backend/app/api/v1/documents.py#L239)) has **no tenant filter at all** and depends solely on the `can_access` post-check for isolation. That post-check is correct, so there is no live document leak — but the second layer of defence is absent everywhere.

**Fix**: provision `docmgmt_app` as the application login (grants already exist in `0002`), point `DATABASE_URL` at it, and add an integration test asserting `rolbypassrls = false` for the connected role.

---

### C-2 — Cross-tenant audit-log exposure

**Severity: Critical · Real data leak, independent of C-1**

`access_log` has no `tenant_id` column ([models.py:284](backend/app/db/models.py#L284)) and is deliberately excluded from RLS — `0002_security_hardening.py` states: *"keywords/document_text/security_levels/doc_types/access_log are global/shared and stay outside RLS."*

`_fetch_audit_page` ([audit.py:104](backend/app/api/v1/audit.py#L104)) builds its query with only three optional filters — `document_id`, `actor_id`, `action`. **There is no tenant predicate anywhere in the endpoint.**

Every other listing endpoint carries an explicit tenant filter. Audit is the sole exception, and it is the one endpoint that can never fall back on RLS because the table has no tenant column.

**Consequence**: any principal with `VIEW_AUDIT` (roles `admin`, `security_officer`) in *any* tenant can page the entire cluster-wide audit trail — every tenant's document UUIDs, actor UUIDs, action strings, client IPs and user agents. This holds whether or not C-1 is fixed.

**Fix**: add `tenant_id` to `access_log` (populated in `record_audit` from `UserCtx.tenant_id`), add it to `_TENANTED_TABLES` with a direct RLS policy, and add a `WHERE tenant_id = :caller_tenant` to `_fetch_audit_page`. Backfill is trivial via the `documents` join for existing rows.

---

### C-3 — The classification engine produces nothing

**Severity: Critical (functional) · Disclosed in PROGRESS.md, but understated**

All four recognisers in [recognizers.py](backend/app/classification/rules/recognizers.py) have real, correct, tested validators (Luhn, CNIC province digits, passport shape, PK-IBAN prefix) — and every single `scan()` body is:

```python
def scan(self, text: str) -> list[Finding]:
    # TODO(rules-phase-2): finditer over pattern, validate, emit Findings.
    return []
```

`predict_type` ([loader.py:98](backend/app/classification/ml/loader.py#L98)) always returns `None` (no artifact exists, no sentence-transformers installed).

Therefore, for **every document ever ingested**: `findings = []` → `aggregate_level([]) = DEFAULT_FLOOR_RANK` (Internal) → outcome is `decided_by="rules"`, `confidence=0.0`, `needs_review=True`.

Every document is labelled Internal and queued for human review. The two-output classification promise — security level *and* document type — is 0% functional. Document type is always `NULL`. This is the product's core value proposition and it is a stub. PROGRESS.md calls this "placeholders this phase"; the practical reading is that the system is a manual-classification tool with an automated review queue attached.

---

### C-4 — Malware scanning cannot reach ClamAV in the compose stack

**Severity: Critical · Deployment-breaking**

[scanning.py:27](backend/app/workers/scanning.py#L27):

```python
CLAMAV_HOST: Final = "127.0.0.1"
CLAMAV_PORT: Final = 3310
```

In `docker-compose.yml` the worker runs in its own container; `127.0.0.1` there is the worker itself, not the `clamav` service. `clamd_scan` raises `ScanError` → `TransientStorageError` → 3 autoretries → permanent stage failure.

Compounding: `SCAN_ENABLED: "true"` is set for all three services and `ENV` is unset (defaults `dev`), so `_scan_body` takes the *scanning* branch rather than the dev fail-open branch. **Every upload in the compose stack fails at stage 1.**

The module TODO acknowledges the constants should move to `Settings`; the value being `127.0.0.1` rather than `clamav` is the actual defect.

**Fix**: promote `clamav_host`/`clamav_port` to `Settings`; default `clamav`; set explicitly in compose.

---

### C-5 — Compose gives api and worker separate, unshared local storage

**Severity: Critical · Deployment-breaking**

Compose sets `STORAGE_BACKEND: local` for `api`, `worker` and `worker-ocr`. `LocalStorage` roots at the relative path `var/storage` under `WORKDIR /srv/app`. The only volume mounted into these services is `./backend/scripts:/srv/app/scripts:ro`.

There is **no shared volume for `var/storage`**. The API writes quarantine/primary bytes into its own container filesystem; the worker's `_read_object` then opens a path that does not exist in *its* filesystem → `FileNotFoundError`.

Even with C-4 fixed, the pipeline cannot read a single byte the API wrote.

**Fix**: either add a named volume mounted at `/srv/app/var/storage` in all three services, or (preferred) switch compose to `STORAGE_BACKEND: minio` — MinIO is already in the stack, healthy, and unused.

---

## 4. High-Severity Findings

### H-1 — Invariant #1 is violated: the API reads and writes object storage on the write path

`complete_upload` → `_ingest_bytes` ([uploads.py:147](backend/app/api/v1/uploads.py#L147)) does all of the following inside the request handler:

```python
with storage.open(key) as handle:
    data: bytes = handle.read()  # reads the whole quarantine object
...
storage.put(object_key, BytesIO(data), content_type=mime)  # writes to PRIMARY
```

Three separate problems:

1. **Invariant #1** says "The API does not touch object storage on the write path." It reads the full object *and* promotes it to the immutable primary bucket.
2. **Bytes reach the immutable primary bucket before the malware scan runs.** The pipeline order is `scan → …`, but the API has already promoted. Since primary objects are immutable (`ImmutableKeyError` on delete) and no purge path exists, **an infected blob is permanently resident in primary storage** the moment `complete` returns.
3. **Duplicated work.** `_promote_to_primary` ([tasks.py:227](backend/app/workers/tasks.py#L227)) re-reads, re-hashes, re-sniffs and re-puts the same bytes. The second `put` only survives because `PrimaryBlobGuard` treats byte-identical content as a no-op — the two promotions are silently racing on the same key.

Also: `handle.read()` loads up to `UPLOAD_MAX_BYTES` (100 MB default) into memory per concurrent request. A dozen concurrent completions is 1.2 GB of RSS — a trivial memory-exhaustion vector.

**Fix**: delete `_ingest_bytes`' promotion entirely. Let `complete` record intent + enqueue only; let the worker's scan stage own sniff → hash → promote → blob row, as `_promote_to_primary` already does.

---

### H-2 — `check_monotonic` compares against all history, not the current label

[0002_security_hardening.py:79](backend/alembic/versions/0002_security_hardening.py#L79):

```sql
WHERE prior.document_id = NEW.document_id
  AND candidate.rank < prior_level.rank
```

`prior` is *any* row in the document's classification history, not the current one. The trigger therefore blocks an automated insert whose rank is below the **historical maximum**, not below the **current** level.

Concrete failure: a human legitimately lowers Restricted → Internal (permitted, audited). A later re-classification — new version, retrained model, re-run — proposing Confidential is a *raise* relative to the current Internal label, but is rejected because a Restricted row exists in history. The document can never be automatically re-labelled again.

It also ignores `version_id` entirely, despite classifications being version-scoped (#21): a genuinely less-sensitive *new version* of a document can never be classified automatically.

**Fix**: compare `NEW.level_id` against the level of `documents.current_classification_id` (or the latest row for `NEW.version_id`), not against a `MAX` over all history.

---

### H-3 — Only malware failures flip `documents.status`; every other failure strands the row

`mark_document_failed` is called from exactly one branch in `_run_stage` — `except MalwareDetectedError` ([tasks.py:341](backend/app/workers/tasks.py#L341)). Every other terminal failure (`ShaMismatchError`, `BlobExistsError`, `UnknownMimeError`, `ValueError/TypeError`, `ParserUnavailable`, `IntegrityError`, exhausted `TransientStorageError` retries) journals `processing_jobs` and re-raises **without touching `documents.status`**.

Those documents sit at `status='processing'` forever. The UI shows a permanent spinner; `#4`'s promise that pipeline state is answerable from SQL holds only if you join `processing_jobs` — which the documents list does not.

The same happens on the OCR path: `enqueue_ocr` journals `queued` and logs, and Tesseract does not exist. Every scanned PDF becomes a permanent zombie.

**Fix**: call `mark_document_failed` from the generic terminal-failure path, not just the malware branch.

---

### H-4 — The claimed "reconciler" does not exist

[uploads.py:20](backend/app/api/v1/uploads.py#L20) documents the broker-failure policy: *"the API returns 503 but the committed state stays `processing`; a worker-side reconciler picks stranded rows up later."*

`grep -rn "reconcil\|stranded" app/` returns only those two comments. There is no reconciler task, no periodic beat schedule, no `celery_app.conf.beat_schedule`. Every 503'd upload is permanently stranded, exactly like H-3.

---

### H-5 — Taxonomy map and recogniser registry disagree — a latent hard crash

`Taxonomy._SPEC_ENTITY_RANKS` ([taxonomy.py:18](backend/app/domain/taxonomy.py#L18)) keys on:

```
card_number, cnic, salary_with_named_person, internal_email_domain, named_employee
```

`registry.ENTITY_TYPES` ([registry.py:20](backend/app/classification/rules/registry.py#L20)) declares:

```
bank_account, card_number, passport_number, cnic
```

Only two overlap. `Taxonomy.rank_for` deliberately fails loud on an unknown type:

```python
raise ValueError(f"unknown entity_type: {finding.entity_type!r}")
```

So the *first* moment C-3 is fixed and a `bank_account` or `passport_number` finding is emitted, `aggregate_level` raises → the classify stage fails → the document strands (H-3). Three taxonomy entries (`salary_with_named_person`, `internal_email_domain`, `named_employee`) have no recogniser and are dead.

This is currently masked only because `scan()` returns `[]`. It is a time bomb wired directly to the next feature to land.

---

### H-6 — Audit `actor_id` is inconsistent and usually NULL

Two different actor resolutions coexist:

- `uploads.py` calls `deps.provision_actor` → returns a real `users.id`.
- `documents.py`, `review.py`, `admin.py` call `_actor_uuid(user)` ([documents.py:561](backend/app/api/v1/documents.py#L561)) → `uuid.UUID(user.sub)`, returning `None` when the sub is not a UUID.

The frontend mints subs like `dev-admin_t1`. Those are not UUIDs, so **every download, findings read, jobs read, reclassify and taxonomy change audits with `actor_id = NULL`**, while uploads by the same person audit with a `users.id`. The audit trail cannot attribute actions to a person, and the `actor_id` filter on `GET /v1/audit` is unusable.

**Fix**: use `provision_actor` everywhere (it is already idempotent and returns `users.id`).

---

### H-7 — `Range` support covers only one of three header forms

[documents.py:180](backend/app/api/v1/documents.py#L180):

```python
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d+)")
```

matched with `fullmatch`. This rejects:

- `bytes=500-` (open-ended — **the most common form**, used by every browser video/PDF viewer and by `curl -C -`)
- `bytes=-500` (suffix)
- multi-range

All three fall through to `return None` and are served as a full `200`. Invariant #17 says range headers are honoured; in practice a resumed download silently restarts from byte 0. The `Accept-Ranges: bytes` header advertises full support.

---

### H-8 — Blocking network I/O inside the async event loop

`get_current_user` is `async` and calls `get_verifier().verify(token)` synchronously. For `OidcJwksVerifier` that reaches `PyJWKClient.get_signing_key_from_jwt`, which performs a **blocking `urllib` fetch** on a cache miss, with no `timeout` configured (PyJWT default 30 s).

A slow or hung Keycloak stalls the entire uvicorn event loop for up to 30 s per key-miss — all requests, not just authentication. Similarly `enrich_visible_departments` opens a **second, separate DB session per request** ([deps.py:81](backend/app/api/deps.py#L81)) outside the request's own session, doubling connection pressure on every dev-JWT call.

Also: the `except PyJWKClientError:` retry immediately re-calls the same method with no `refresh` flag — it is a duplicate call, not a cache refresh.

---

### H-9 — `.env.example` typo silently disables OIDC

```
OIDC_ISSU=
```

Should be `OIDC_ISSUER`. `Settings` is configured `extra="ignore"`, so `OIDC_ISSU` is discarded without warning, `oidc_issuer` stays `None`, and `get_verifier()` selects **`DevJWTVerifier`** whenever `env == "dev"`.

Chained with the shipped default `dev_jwt_secret = "dev-only-secret-change-me"` and `env` defaulting to `"dev"`, any deployment that follows `.env.example` and forgets `ENV=prod` accepts self-minted tokens with **arbitrary `role`, `clearance_rank` and `tenant_id` claims** — a complete authentication and authorisation bypass. The frontend already ships a working token minter for that exact secret (see the frontend report, F-2).

The `DevJWTVerifier` constructor guard (`env != "dev"` → RuntimeError) is good defence, but it is defeated by the default value of `env` itself.

---

## 5. Medium-Severity Findings

| # | Finding | Detail |
|---|---|---|
| M-1 | **The 466 hermetic tests exercise almost no SQL** | `tests/api/conftest.py` monkeypatches *every* data-access seam (`_fetch_document_page`, `_fetch_document_view`, `_fetch_audit_page`, `_fetch_review_page`, …) and injects a `_FakeSession` whose `execute` raises. Real SQL is covered only by the 6 integration tests. The visibility predicates, the keyset cursors and the facet queries are effectively untested against a real database. |
| M-2 | **Invariant #18 is only half-met** | Preview and download are separate *permissions* (`Action.PREVIEW` / `Action.DOWNLOAD`), but there is **one** content endpoint. `GET /{id}/content` requires `DOWNLOAD`; `PREVIEW` gates only `/findings`. There is no separate preview endpoint, so a preview-only role cannot preview anything. |
| M-3 | **`can_access` ignores its `action` argument** | [policy.py:24](backend/app/domain/policy.py#L24) takes `action: Action` and never reads it — the docstring admits "Every action is gated identically this phase." Document-level per-action policy does not exist; only the coarse role table differentiates. |
| M-4 | **Three containers race to run `alembic upgrade head`** | `api`, `worker` and `worker-ocr` all use `entrypoint-api.sh`, which runs migrations before exec. On a cold start all three race with no advisory lock. Alembic is not concurrency-safe here. |
| M-5 | **`requires-python = ">=3.11"` is wrong** | The code uses PEP 695 syntax (`class BaseRepository[ModelT: …]`, `def _require[T]`), which is a **3.12+** parser feature. Installing on 3.11 is an immediate `SyntaxError`. The Dockerfile pins 3.12; the dev venv is 3.14; ruff targets `py314`. Three different Python versions in play. |
| M-6 | **Container runs as root; no `USER` directive** | `backend/Dockerfile` never drops privileges. `curl` is installed "for the compose healthchecks" — compose defines **no** healthcheck for `api`/`worker`/`worker-ocr`, so it is an unused attack-surface package. |
| M-7 | **`scripts/` is not in the image** | Bind-mounted by compose with a `TODO(Dockerfile)`. The image alone cannot run the api or worker entrypoint. |
| M-8 | **No CORS, no security headers, no rate limiting, no request-size guard** | `grep add_middleware app/` returns nothing. No `CORSMiddleware`, no `TrustedHostMiddleware`, no HSTS/CSP/X-Content-Type-Options, no per-IP throttle on `POST /v1/uploads`. No Nginx service exists in compose to supply them either, despite AGENTS.md listing Nginx in the stack. |
| M-9 | **Search snippets are always empty strings** | `_load_snippet_text` ([hybrid.py:191](backend/app/search/hybrid.py#L191)) returns `{}` unconditionally — raw text is never persisted. Every `SearchHit.snippet` is `""`. |
| M-10 | **The vector arm returns zero rows by construction** | `compose_vector_subquery` ends in `.where(false())`. `embed` is a no-op task; `document_text.embedding` is always NULL. "Hybrid" search is keyword-only, and RRF fuses one arm with an empty one. |
| M-11 | **Search has no pagination at all** | Documented as a deliberate deferral (unstable RRF sort key, `OFFSET` banned by #32). Practical effect: results past `limit=50` are permanently unreachable. |
| M-12 | **Facets run two unbounded `GROUP BY`s over the full candidate set per search** | `facet_counts` + `doc_type_facet_counts` scan every visible document on every keystroke-triggered query. Combined with `SELECT DISTINCT` over a `tsvector` column in `build_visible_candidates`, this will not scale past a modest corpus. |
| M-13 | **`record_classification` can silently revert a human decision** | On the dedup path it takes `existing` (an automated classification for that version) and executes `UPDATE documents SET current_classification_id = existing`. If a human reclassification landed in between, that pointer move undoes it. Currently gated by `_already_succeeded`, but the SQL itself is unsafe. |
| M-14 | **`processing_jobs` has no unique constraint on `(version_id, stage)`** | The journal is get-or-created on that pair in application code. Two concurrent workers can create duplicate rows for the same stage. |
| M-15 | **Cross-tenant blob dedup points one tenant's document at another tenant's object key** | `_persist_ingest` reuses an existing `blobs` row on sha256 match. Tenant B uploading a file tenant A already has gets a version pointing at `docs-primary/<tenant-A-uuid>/…`. Consistent with #15 (keys are not authorisation boundaries) but a real data-residency and right-to-erasure problem: purging tenant A's objects breaks tenant B's documents. |
| M-16 | **Quarantine objects are never cleaned up on the skip path** | `_promote_to_primary` deletes the quarantine key only on the clean-scan branch. Dev fail-open, malware detection, and every failed stage leave the quarantine object resident forever. |
| M-17 | **`FileNotFoundError` is globally mapped to HTTP 404** | `_register(app, FileNotFoundError, _file_not_found_handler)`. Any unrelated missing file — a config, a certificate, a template — surfaces to the client as "document not found" instead of a 500, masking operational faults. |
| M-18 | **`build_storage` / `get_sync_sessions` / `get_verifier` are module-global singletons** | All ignore `settings` after first construction. Cross-test pollution risk and no way to reconfigure at runtime. |
| M-19 | **`replace_keywords` issues an N+1 SELECT per term** | 20 terms per document = 20 round-trips inside one transaction. `Keyword.idf` is hardcoded `0.0` and `document_keywords` is never read by search — the whole keywords stage currently produces write-only dead data. |
| M-20 | **`LocalStorage.presign` ignores `response-content-disposition`** | Invariant #17 requires disposition pinning on presigned URLs. `S3Storage.presign` does it correctly; `LocalStorage.presign` accepts `filename` "for protocol parity only" and drops it. The streaming path sets no `Content-Disposition` header either. |
| M-21 | **`LocalStorage` has no `presign_put`** | `create_upload_intent` falls back to `storage.presign(...)` — a **GET** URL — and `dev_storage.py` implements only `GET`. A browser PUT to that URL gets 405. The local backend cannot complete the upload flow it is the default for. |
| M-22 | **`dev_storage` router is mounted whenever `storage_backend == "local"` — the default** | It carries no auth dependency (HMAC only). A prod deployment that forgets `STORAGE_BACKEND=minio` exposes it. Its HMAC key is `dev_jwt_secret` — the same key used to sign identity tokens. Key reuse across two purposes. |
| M-23 | **`doc_types` and `security_levels` are global across tenants** | Any tenant's admin sees and mutates every tenant's taxonomy via `/v1/admin/doc-types`. Defensible per spec §6 (no tenant column), but it is a cross-tenant information and integrity leak in a multi-tenant product and should be an explicit, documented decision. |
| M-24 | **`_delete_doc_type` is TOCTOU** | Children and classification references are counted, then deleted, with no FK or lock in between. |
| M-25 | **No new-version upload path** | `_persist_ingest` hardcodes `version_no=1`. Invariant #16's "an edit is a new blob plus a new `document_versions` row" has no endpoint. Nor is there a delete/soft-delete endpoint, despite `deleted_at` being modelled and checked everywhere. |
| M-26 | **`_fetch_document_view` joins the blob through the *classification's* version** | An unclassified document (`current_classification_id IS NULL`) has `blob_key = None` → `GET /content` returns 404 even though the bytes exist. Content is unreachable until classification completes. |
| M-27 | **`X-Forwarded-For` is ignored in audit IPs** | `_client_ip` reads `request.client.host` only. Behind the Nginx that AGENTS.md specifies, every audit row records the proxy's IP. |
| M-28 | **Level-name casing is inconsistent across three layers** | `LevelName` StrEnum is lowercase (`"public"`); migration `0003` seeds `'Public'`; `artifact.SECURITY_LEVEL_LABELS` is capitalised. `_resolve_level_id` papers over it with `func.lower(...)`, which also defeats any index on `security_levels.name`. |
| M-29 | **`to_tsvector('english', …)` is hardcoded** | The ML corpus is `Faker('en_PK')` and the domain is Pakistani business documents. Mixed-language content will index poorly. |
| M-30 | **`db/repositories/` is an empty promise** | `BaseRepository` exists with no concrete subclasses. The stated rule "Do not return ORM rows past the repository layer" is honoured by hand-rolled dataclass projections in each router instead. `app/deps.py` is a 4-line dead placeholder duplicating `app/api/deps.py`. `app/security/audit.py`, listed in AGENTS.md's layout, does not exist. |
| M-31 | **`task_acks_late` / `task_reject_on_worker_lost` are unset** | A worker killed mid-stage loses the task silently; combined with H-3/H-4 the document strands. `--pool=solo` is set in compose (flagged dev-only) — single-threaded workers. |

---

## 6. Invariant Compliance — Verified vs. Claimed

The README asserts all 33 invariants are enforced. Independently verified:

| # | README claim | Verified state |
|:--:|---|---|
| 1 | API never touches storage on write path | ❌ **Violated** — `_ingest_bytes` reads quarantine and writes primary (H-1) |
| 2 | Workers sole automated classifier | ✅ Correct |
| 3 | Fixed pipeline order | ✅ Correct |
| 4 | `processing_jobs` around every stage | ⚠️ Journal correct; `documents.status` only updated on malware (H-3). README cites `jobs.py:StageJournal` — the class is `ProcessingJobsJournal` |
| 5 | sha256 idempotency | ✅ Correct |
| 6 | Extract/embed once | ⚠️ Text: yes. Bytes: read+sniffed+hashed twice (H-1). Embedding: never computed |
| 7 | Cached JWKS, no IdP round-trip | ⚠️ Cached, but blocking with no timeout; the "retry" is a no-op (H-8) |
| 8 | Monotonic trigger | ⚠️ Trigger exists but compares against all history, not current (H-2) |
| 9 | Internal floor | ✅ Correct — `DEFAULT_FLOOR_RANK` and SQL `COALESCE` both |
| 10 | Pattern + validator + ±50 context | ⚠️ All three parts written and tested; **no recogniser ever fires** (C-3) |
| 11 | Calibrated ML, ≥0.85 | ⚠️ Contract + threshold correct; no model exists |
| 12 | Offsets only, never text | ✅ Correct — enforced in model, schema, wire model and `build_finding` |
| 13 | Never train on held-out set | ✅ Gated in `ml/export_training_data.py` |
| 14 | Per-class recall on highest label | ✅ Specified in trainer + contract |
| 15 | Key is not an auth boundary | ✅ Correct |
| 16 | Primary immutable | ✅ `PrimaryBlobGuard` correct — but infected bytes land there first (H-1) |
| 17 | Split content, Range honoured, TTL 60–120 | ⚠️ Split ✅, TTL ✅; Range **partial** (H-7); disposition unpinned on local (M-20) |
| 18 | Preview and download separate endpoints | ❌ Separate *permissions*, one endpoint (M-2) |
| 19 | Sniff MIME | ✅ Correct — no filename crosses into `extraction/` |
| 20 | No classification fields on `documents` | ✅ Correct |
| 21 | Classification references `version_id` | ✅ Correct — but the trigger ignores it (H-2) |
| 22 | Deferrable circular FK | ✅ Correct |
| 23 | `rank` ≠ PK | ✅ Correct |
| 24 | `access_log` no cascade, no UPDATE/DELETE grant | ⚠️ Schema ✅; **grant is inert** — the app connects as superuser (C-1) |
| 25 | Two independent axes | ✅ Correct in `can_access` and in all three list queries |
| 26 | Tenant scoping by RLS | ❌ **Bypassed at runtime** (C-1) |
| 27 | Filter inside both arms pre-rank | ✅ Structurally correct — arms select *from* the candidate subquery |
| 28 | Facets from filtered set | ✅ Correct |
| 29 | RRF fusion | ✅ Correct, pure, unit-tested (one arm is empty) |
| 30 | Same-transaction audit | ✅ Correct |
| 31 | Indistinguishable cross-tenant 404 | ✅ Correct — single `not_found()`, no existence branch |
| 32 | Cursor only, no OFFSET | ✅ Correct on documents/review/audit; search has no pagination (M-11) |
| 33 | Server-side enforcement | ✅ Correct — `deps.require` on every route |

**Score: 19 clean · 10 partial · 4 violated.**

---

## 7. What Has Been Accomplished

Substantial and genuinely good work:

- **Clean layered architecture.** `domain/` is provably pure (there is a `test_purity.py` enforcing it), imported identically by API and workers. No worker-local policy copy exists.
- **16-table schema transcribed 1:1 from the spec**, with the hard parts done right: deferrable circular FK, rank-as-data, FK-less audit table, correct partial indexes, GIN + HNSW.
- **RFC 7807 error envelope** with a single byte-stable `not_found()` and no existence-dependent branching — a textbook implementation of #31.
- **Storage abstraction** with a shared `PrimaryBlobGuard` mixin, so immutability semantics cannot drift between the local and S3 backends. `RangeFile` is a careful piece of work.
- **Content-based MIME sniffing** with correct OOXML zip-member disambiguation, and a package-wide rule that no function accepts a filename.
- **Raw clamd INSTREAM client** over a plain socket — no dependency, fails closed on every unparseable response.
- **Pure RRF fusion** with deterministic tie-breaking, unit-tested against hand-computed truth tables.
- **Alg-confusion guard** in `OidcJwksVerifier` — `HS*` rejected *before* any key fetch.
- **`DevJWTVerifier` structurally forbidden outside dev** (constructor raises).
- **Full ML toolkit**: synthetic `Faker('en_PK')` corpus, double-gated real-text exporter, calibrated trainer, and a versioned artifact contract the loader actually enforces (schema version, embedding model id, dim, label-taxonomy membership).
- **All three quality gates green and honestly reported.** 466 + 6 + 21 tests, strict mypy over 61 files, ruff with an aggressive rule set — zero suppressions beyond four documented, justified `noqa`s.
- **Documentation-in-code is exceptional** — nearly every module docstring names the invariant it implements and explains *why* the shape was chosen. This is rare and worth preserving.

---

## 8. What Remains

### Blocking before the system runs at all
1. Point `DATABASE_URL` at `docmgmt_app`, not the superuser (C-1).
2. Add a tenant column + filter to `access_log` (C-2).
3. Fix `CLAMAV_HOST` → `Settings` field, default `clamav` (C-4).
4. Share `var/storage` across containers, or switch compose to MinIO (C-5).
5. Remove the API-side primary promotion (H-1).

### Blocking before the product does its job
6. Implement the four `scan()` bodies (C-3) — validators, patterns and the context scorer are already written and tested.
7. Reconcile `Taxonomy` with `registry.ENTITY_TYPES` **before** (6), or (6) will crash on first fire (H-5).
8. Fix `check_monotonic` to compare against the current label (H-2).
9. Call `mark_document_failed` on every terminal failure (H-3).
10. Write the reconciler that four comments already promise (H-4).

### Backlog (was already listed in PROGRESS.md, still accurate)
11. Train and deploy the calibrated classifier; wire `_predict_with_artifact`.
12. Implement Tesseract OCR on the `ocr` queue — currently every scanned PDF strands.
13. Implement embeddings so the vector arm and HNSW index become live.
14. Implement SSE for `/v1/events` (currently a 501 stub; the frontend polls).

### Not previously tracked — should be
15. Persist extracted text so search snippets stop being empty strings (M-9).
16. Add the preview endpoint that #18 requires (M-2).
17. Add version-upload and document-delete endpoints (M-25).
18. Add Nginx + Keycloak to compose; add CORS/security headers/rate limiting (M-8).
19. Widen `Range` parsing to open-ended and suffix forms (H-7).
20. Unify audit `actor_id` on `provision_actor` (H-6).
21. Fix `OIDC_ISSU` → `OIDC_ISSUER`; make `env` default to `prod` so dev is opt-in, not the fallback (H-9).
22. Bring the API tests down onto real SQL — the seam-mocking strategy has left the query layer largely unverified (M-1).
23. Fix `requires-python` to `>=3.12` and align dev/CI/container Python versions (M-5).
24. Run containers as non-root; drop unused `curl` (M-6).
25. Add an advisory lock (or a dedicated migrate job) so three containers stop racing on `alembic upgrade head` (M-4).

---

## 9. Recommended Sequence

| Phase | Work | Rationale |
|---|---|---|
| **0 — make it run** | C-4, C-5, H-1 | Nothing can be validated end-to-end until an upload completes in compose |
| **1 — close the leaks** | C-1, C-2, H-9 | These are live multi-tenant and authentication defects |
| **2 — stop stranding documents** | H-3, H-4, H-2 | Operability floor; every later feature depends on the pipeline terminating honestly |
| **3 — make it classify** | H-5 then C-3 | Order matters — H-5 first or C-3 crashes on first fire |
| **4 — completeness** | M-2, M-9, M-25, H-7, H-6 | Feature gaps that are individually small |
| **5 — hardening & scale** | M-1, M-8, M-4, M-6, M-12 | Test depth, edge hardening, query cost |
