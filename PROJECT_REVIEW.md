# Project Review — Secure Document Management System

**Reviewed**: 2026-08-27 · commit `0f75ad6` (branch `main`, clean tree)
**Scope**: full stack — `backend/`, `frontend/`, `ml/`, `docker-compose.yml`, migrations, docs
**Companion reports**: [`backend/BACKEND_REVIEW.md`](backend/BACKEND_REVIEW.md) · [`frontend/FRONTEND_REVIEW.md`](frontend/FRONTEND_REVIEW.md)
**Method**: complete read of all 102 source files across both stacks; every frontend API call diffed field-by-field against the backend's Pydantic models; all quality gates re-run locally; live probe of the dev PostgreSQL role privileges.

---

## 1. Executive Summary

This is a **carefully designed system that has been built module-by-module to a high standard and never assembled.**

The quality of the individual pieces is high and not in question. The domain layer is provably pure. The 16-table schema transcribes the spec exactly, including the awkward parts. The RFC 7807 envelope is a textbook implementation of indistinguishable cross-tenant 404s. The storage abstraction shares one immutability guard across both backends so semantics cannot drift. The ML toolkit has a versioned artifact contract the loader genuinely enforces. Documentation-in-code is exceptional — nearly every module names the invariant it implements and explains why the shape was chosen. Every quality gate the handoff claims does pass, and I re-ran all four to confirm.

The problem is systemic and it repeats at every seam:

> **Controls are implemented correctly, proven in isolation, and then not connected to the runtime path.**

- Row-level security is written correctly, tested correctly, and **bypassed** — because the application connects as a PostgreSQL superuser.
- The least-privilege role `docmgmt_app` is created by a migration and **never adopted** by any service.
- ClamAV's INSTREAM client is correct and **points at `127.0.0.1`**, which in the worker container is not ClamAV.
- Four PII recognisers have real validators, real patterns and a real context scorer — and **every `scan()` returns `[]`**.
- The frontend implements every invariant faithfully against **an API contract that does not exist**.

The result: **the compose stack cannot complete a single upload, and the frontend cannot successfully call a single non-trivial endpoint.**

None of this requires a redesign. The architecture is right. What is missing is the integration pass — and the integration testing that would have surfaced all of it on day one.

---

## 2. Health at a Glance

| Area | Built | Wired | Verified end-to-end |
|---|:--:|:--:|:--:|
| Domain policy & aggregation | ✅ | ✅ | ✅ |
| Database schema & migrations | ✅ | ✅ | ✅ |
| Row-level security | ✅ | ❌ | ⚠️ (as an unused role) |
| Storage abstraction (local + S3) | ✅ | ⚠️ | ⚠️ |
| Auth (dev JWT + OIDC/JWKS) | ✅ | ⚠️ | ⚠️ |
| API surface (7 routers, 15 endpoints) | ✅ | ✅ | ⚠️ (SQL mostly mocked) |
| Upload → quarantine → primary | ✅ | ❌ | ❌ |
| Malware scanning | ✅ | ❌ | ⚠️ (localhost only) |
| Worker pipeline (6 stages) | ✅ | ❌ | ⚠️ |
| Text extraction (pdf/docx/xlsx) | ✅ | ✅ | ✅ |
| **PII recognition / classification** | ❌ | ❌ | ❌ |
| ML model | ❌ | ❌ | ❌ |
| Embeddings / vector search | ❌ | ❌ | ❌ |
| Keyword search | ✅ | ✅ | ⚠️ (no snippets) |
| Audit trail | ✅ | ⚠️ | ❌ (cross-tenant leak) |
| OCR | ❌ | ❌ | ❌ |
| SSE / `/v1/events` | ❌ (501 stub) | — | — |
| Frontend UI shell & theming | ✅ | ✅ | ✅ |
| **Frontend ↔ backend contract** | ❌ | ❌ | ❌ |

---

## 3. Quality Gates — Independently Re-Run

Every gate claimed in `PROGRESS.md` §3 was re-run during this review. **All claims are honest.**

```
backend  pytest -q            → 466 passed, 3 skipped, 7 deselected (6.91s)   ✅
backend  ruff check .         → All checks passed!                            ✅
backend  mypy app             → Success: no issues found in 61 source files   ✅
ml       pytest tests -q      → 21 passed (6.17s)                             ✅
frontend tsc --noEmit         → clean, 0 errors                               ✅
frontend vitest run           → 12 passed / 4 files                           ✅
frontend vite build           → dist/ generated                               ✅
```

**But the gates measure the wrong thing.** Two structural reasons:

1. **`tests/api/conftest.py` monkeypatches every data-access seam** and injects a `_FakeSession` whose `execute()` raises. The 466 hermetic tests validate routing, permission gating, cursor encoding and the error envelope — and touch essentially **no real SQL**. Six integration tests cover the database.

2. **`api.get<T>()` is an unchecked cast** over `response.json()`. `tsc --noEmit` is clean while every page reads fields the backend does not send. TypeScript cannot see past the boundary.

A single MSW-backed frontend test asserting the real upload payload, and a single backend test asserting `rolbypassrls = false` for the connected role, would each have caught a Critical finding.

---

## 4. Critical Findings — Cross-Stack

Seven issues block the system from functioning. Five are backend/infrastructure, two are frontend, and two of them **compound across the stack**.

### CS-1 — Authentication bypass by default *(compounds across both stacks)*

Three independently benign facts combine into a complete auth bypass:

| Layer | Fact |
|---|---|
| `backend/app/config.py` | `env: Literal["dev","prod"] = "dev"` — dev is the **default**, not opt-in |
| `backend/app/config.py` | `dev_jwt_secret = "dev-only-secret-change-me"` — a real, shipped default |
| `.env.example` | `OIDC_ISSU=` — **typo**. `Settings` uses `extra="ignore"`, so it is silently discarded, `oidc_issuer` stays `None`, and `get_verifier()` selects `DevJWTVerifier` |
| `frontend/src/api/auth.tsx` | Mints HS256 tokens in-browser with **that exact secret**, with attacker-controlled `role`, `clearance_rank` and `tenant_id`, valid for 7 days. The secret is present in the built bundle |

Any deployment that follows `.env.example` and forgets `ENV=prod` grants **full admin access to any tenant to anyone who opens DevTools**. The `DevJWTVerifier` constructor guard (`env != "dev"` → `RuntimeError`) is good defence, defeated by the default value of `env` itself.

**Fix**: default `env` to `"prod"`; fix the `OIDC_ISSUER` typo; remove client-side minting (`backend/scripts/mint_dev_token.py` already exists for this); remove the shipped secret default and fail startup if unset in dev.

---

### CS-2 — Multi-tenant isolation is not enforced by the mechanism that is supposed to enforce it

Invariant #26 requires tenant scoping via RLS, *not* remembered `WHERE` clauses. Migration `0002` does this correctly: `ENABLE + FORCE ROW LEVEL SECURITY` on ten tables, `tenant_isolation` policies reading `app.tenant_id`, and `docmgmt_app` granted least privilege. `tests/integration/test_rls.py` connects **as `docmgmt_app`** and proves it works.

The application never uses that role. Probed live during this review:

```
SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
→ ('docmgmt', True, True)
```

`docmgmt` is `POSTGRES_USER` — a superuser created by the postgres image. **`rolbypassrls = True` skips every policy, `FORCE` included.** Migration `0003`'s own docstring states the mechanism; it was simply never applied to the runtime config.

Documents remain isolated only because the application *also* carries explicit tenant `WHERE` clauses — precisely what the invariant forbids relying on. Defence in depth is absent everywhere, and `_fetch_document_view` has **no tenant filter at all**, resting entirely on the `can_access` post-check.

---

### CS-3 — Cross-tenant audit-log exposure *(a live data leak, independent of CS-2)*

`access_log` has no `tenant_id` column and is deliberately excluded from RLS. `_fetch_audit_page` ([backend/app/api/v1/audit.py:104](backend/app/api/v1/audit.py#L104)) filters only on optional `document_id`, `actor_id` and `action` — **no tenant predicate anywhere in the endpoint.**

Every other listing endpoint carries an explicit tenant filter. Audit is the only exception, and the only one that can never fall back on RLS.

Any principal holding `VIEW_AUDIT` (`admin`, `security_officer`) in **any** tenant can page the entire cluster-wide audit trail: every tenant's document UUIDs, actor UUIDs, action strings, client IPs and user agents. This holds whether or not CS-2 is fixed.

---

### CS-4 — The compose stack cannot process an upload (three independent blockers)

1. **ClamAV is unreachable.** `CLAMAV_HOST = "127.0.0.1"` is a module constant; in the worker container that is the worker, not the `clamav` service. `SCAN_ENABLED: "true"` is set for all services, so the dev fail-open branch is not taken. Every upload fails at stage 1 after three retries.
2. **api and worker have unshared storage.** All three services set `STORAGE_BACKEND: local`; `LocalStorage` roots at `var/storage` under `WORKDIR /srv/app`; the only mounted volume is `./backend/scripts:ro`. The API writes bytes into its own container filesystem; the worker's `_read_object` opens a path that does not exist there. (MinIO is in the stack, healthy, and unused.)
3. **The local backend has no `presign_put`.** `create_upload_intent` falls back to a presigned **GET** URL, and `dev_storage.py` implements only `GET`. A browser PUT gets 405.

---

### CS-5 — Classification, the product's core value proposition, produces nothing

All four recognisers have correct, tested validators — Luhn, CNIC province digits, passport shape, PK-IBAN prefix — a real `score_with_context` ±50-character scorer, and `scan()` bodies that are:

```python
return []   # TODO(rules-phase-2)
```

`predict_type` always returns `None` (no artifact, no sentence-transformers). Therefore for **every document ever ingested**: `findings = []` → level = Internal floor → `decided_by="rules"`, `confidence=0.0`, `needs_review=True`, `doc_type=NULL`.

Every document is labelled Internal and queued for human review. `PROGRESS.md` calls this "placeholders this phase"; the accurate reading is that the system is currently **a manual-classification tool with an automated review queue attached**.

A **time bomb** sits behind this: `Taxonomy._SPEC_ENTITY_RANKS` keys on `{card_number, cnic, salary_with_named_person, internal_email_domain, named_employee}` while the registry declares `{bank_account, card_number, passport_number, cnic}`. `Taxonomy.rank_for` fails loud on unknown types. **The first moment a `bank_account` or `passport_number` finding is emitted, `aggregate_level` raises and the classify stage dies.** The taxonomy must be reconciled *before* the recognisers are implemented.

---

### CS-6 — Every frontend API call has the wrong shape *(frontend)*

The entire `src/api/` layer was hand-written from an imagined contract. AGENTS.md states the rule that was skipped: *"regenerate the OpenAPI client rather than hand-editing `frontend/src/api/`."*

Verified field-by-field. A representative sample:

| Frontend reads/sends | Backend actually has | Effect |
|---|---|---|
| `doc.title` | `filename` | Title column blank on every row |
| `doc.security_level_name` / `_rank` | `level` | Level badge blank everywhere |
| `doc.byte_size` | *(absent)* | "0 B" on every row |
| `item.id` (review) | `review_id` | `POST /v1/review/undefined/resolve` → 422 |
| `POST /v1/uploads {title, department_id, mime_type, byte_size}` | requires `{filename, size_bytes, content_type}` | **400 on every upload** |
| `POST /v1/documents/{id}/reclassify` | route is `/classification` | **404** |
| `intent.presigned_url` | `presigned_put.url` | `putDirect(undefined, …)` |
| `facets.security_levels` | `facets.levels` | Facet panel blank |

Of eight feature flows, **exactly one works** — taxonomy CRUD, and only because `name`/`description` coincide. Filter controls send parameters the API does not accept and are entirely decorative.

---

### CS-7 — The frontend authenticates as a tenant that does not exist *(frontend)*

`DEV_PERSONAS` uses tenant `00000000-0000-0000-0000-000000000001` and departments `…0010/0020/0099`. Migration `0003` seeds tenant `c0000000-0000-0000-0000-000000000001` and departments `c0000000-…-0011/0012/0013`. **Zero overlap.**

Against a freshly migrated database: `enrich_visible_departments` returns an empty subtree → every list is filtered to `department_id IS NULL` → **empty**. And if upload were fixed, `provision_actor` would violate the `users.tenant_id → tenants.id` foreign key → 500.

Compounding: the frontend's roles are `admin | compliance_officer | employee | auditor`; the backend's are `admin | security_officer | dept_manager | employee | viewer`. `role_can` fails closed, so **Bob (Compliance Officer) and Dana (Internal Auditor) get 403 on every request** — including the Audit page Dana exists to demonstrate.

---

## 5. High-Severity Findings — Summary

Full detail in the two companion reports. Consolidated:

**Backend**
- **H-1** Invariant #1 violated: `complete_upload` reads the full object into memory and writes to the immutable primary bucket **before the malware scan runs**. Infected bytes become permanently resident in primary storage (which has no delete path). Also duplicates the worker's promotion and is a 100 MB-per-request memory vector.
- **H-2** `check_monotonic` compares against *all* classification history, not the current label. After a legitimate human lowering, no automated re-classification is ever possible again. Ignores `version_id` despite #21.
- **H-3** `mark_document_failed` is called **only** on malware detection. Every other terminal failure — parse error, unknown MIME, integrity error, exhausted retries, OCR handoff — leaves `documents.status = 'processing'` forever.
- **H-4** The "worker-side reconciler" that `uploads.py` documents twice **does not exist**. Every 503'd upload is permanently stranded.
- **H-6** Audit `actor_id` is inconsistent: uploads use `provision_actor` (real `users.id`); everything else uses `_actor_uuid(user.sub)`, which returns `None` for the non-UUID subs the frontend mints. Most audit rows have a NULL actor.
- **H-7** `Range` parsing accepts only `bytes=a-b`. Open-ended `bytes=500-` — the form every browser sends — silently falls back to a full 200 while `Accept-Ranges` advertises support.
- **H-8** Blocking JWKS network I/O inside the async event loop, with no timeout (PyJWT default 30 s); the "cache refresh retry" is a duplicate call. `enrich_visible_departments` opens a second DB session per request.

**Frontend**
- **F-5** 12 tests, none covering any feature flow, the API client, auth, or any mutation.
- **F-6** The client-side content split reads fields that do not exist, so it takes the presigned branch for Restricted documents too; `fetchDocumentContent` sends no `Range` header despite documenting range streaming.
- **F-7** The presigned-redirect download is blocked by CORS in dev — the `303` `Location` is absolute `http://localhost:8000/…` and the backend registers **no CORS middleware**.
- **F-8** The review-count poll runs every 15 s with no permission guard: a permanent 403 loop for `employee`/`viewer` sessions.
- **F-9/F-10** No router, no URL state (AGENTS.md explicitly requires filter state in URL params), and no pagination controls anywhere — every list is capped at page one.

---

## 6. Notable Medium-Severity Themes

- **Test depth vs. test count.** 466 backend tests that mock every SQL seam; 12 frontend tests covering a badge and a theme toggle. The numbers are impressive and the coverage of the risky code is thin.
- **Documentation over-claims.** `README.md`'s 33-invariant matrix asserts full enforcement. Verified: **19 clean, 10 partial, 4 violated**. It also cites `jobs.py:StageJournal`, a class that does not exist (it is `ProcessingJobsJournal`). `PROGRESS.md` §4 credits the frontend with enforcing nine invariants through code that cannot execute.
- **Three Python versions in play.** `requires-python = ">=3.11"` is wrong — the code uses PEP 695 generics (3.12+) and would `SyntaxError` on 3.11. The Dockerfile pins 3.12; the dev venv is 3.14; ruff targets `py314`.
- **Infrastructure gaps.** No Nginx and no Keycloak in compose despite both being in the stated stack. No CORS, no security headers, no rate limiting, no request-size guard anywhere. Containers run as **root**. `scripts/` is bind-mounted rather than `COPY`d (`TODO(Dockerfile)`). All three containers race to run `alembic upgrade head` with no advisory lock.
- **Dead or write-only subsystems.** `document_keywords` is written every pipeline run and read by nothing (`Keyword.idf` is hardcoded `0.0`). Search snippets are always `""` (raw text is never persisted). The vector arm is `WHERE false()`. `@tanstack/react-table` is a declared dependency with zero imports. `db/repositories/` holds a base class with no subclasses; `app/deps.py` is a dead 4-line placeholder; `app/security/audit.py` (in AGENTS.md's layout) does not exist.
- **Feature gaps not previously tracked.** No preview endpoint (invariant #18 has separate *permissions* but one endpoint). No new-version upload path (`version_no` is hardcoded `1`, so #16's "an edit is a new blob plus a new version row" has no route). No delete/soft-delete endpoint despite `deleted_at` being modelled and checked everywhere. Search has no pagination at all.

---

## 7. What Has Been Accomplished

This deserves to be stated plainly, because the finding count above understates the quality of the work.

**Architecture and discipline**
- Clean layered separation with a **provably pure** `domain/` (enforced by `test_purity.py`), imported identically by API and workers. No worker-local policy copy exists anywhere.
- One codebase, one image, three entrypoints — exactly as specified.
- Strict mypy across 61 files and an aggressive ruff rule set, both clean, with only four documented and justified suppressions.

**Backend**
- 16-table schema transcribed 1:1 from the spec, getting the hard parts right: deferrable circular FK, rank-as-data-not-key, FK-less audit table, correct partial indexes, GIN + HNSW.
- RFC 7807 envelope with a single byte-stable `not_found()` and **no existence-dependent branching** — a textbook implementation of indistinguishable cross-tenant 404s.
- Storage abstraction with a shared `PrimaryBlobGuard` mixin, so immutability semantics cannot drift between local and S3. `RangeFile` is careful, correct work.
- Content-based MIME sniffing with correct OOXML zip-member disambiguation, and a package-wide rule that **no function in `extraction/` accepts a filename**.
- A raw clamd INSTREAM client over a plain socket — no dependency, fails closed on every unparseable response.
- Pure RRF fusion with deterministic tie-breaking, unit-tested against hand-computed truth tables.
- Alg-confusion guard rejecting `HS*` **before** any key fetch; `DevJWTVerifier` structurally forbidden outside dev by its constructor.
- Search visibility enforced **structurally** — both arms select *from* the candidate subquery, so the filter cannot be forgotten or applied post-fusion.

**ML**
- Synthetic `Faker('en_PK')` corpus generator, a double-gated real-text exporter enforcing invariant #13, a `CalibratedClassifierCV` trainer reporting per-class recall with `restricted_recall` called out separately (#14), and a versioned artifact contract the loader **genuinely enforces** — schema version, embedding model id, dimensionality, and label-taxonomy membership.

**Frontend**
- A coherent, attractive GitHub Primer design system applied consistently across seven pages.
- A working theme provider (system/light/dark, persisted) with the only two behaviour-asserting tests in the repo.
- TanStack Query used correctly throughout — no `useEffect` fetches, sensible key structure, correct invalidation, and a `retry` predicate that properly refuses 401/403/404.
- `<Can>` / `usePermissions` are the right shape for invariant #33, clearly documented as cosmetic. The implementation is correct; only the role table feeding it is wrong.
- `putDirect` via `XMLHttpRequest` with real progress events, correctly omitting `Authorization` per invariant #1.

**Documentation-in-code is exceptional.** Nearly every module docstring names the invariant it implements and explains why the shape was chosen. This is rare, it is the reason this review could be thorough, and it should be preserved.

---

## 8. What Remains — Prioritised Roadmap

### Phase 0 · Make it run *(nothing can be validated end-to-end until this lands)*
| | Task | Ref |
|---|---|---|
| 1 | Fix `CLAMAV_HOST` → `Settings` field, default `clamav` | CS-4 |
| 2 | Share `var/storage` across containers, or switch compose to the already-running MinIO | CS-4 |
| 3 | Remove the API-side primary promotion; let the worker's scan stage own promote | H-1 |
| 4 | Add `presign_put` + a `PUT` route to the local/dev storage backend (or use MinIO) | CS-4 |

### Phase 1 · Close the security holes
| | Task | Ref |
|---|---|---|
| 5 | Point `DATABASE_URL` at `docmgmt_app`; add an integration test asserting `rolbypassrls = false` | CS-2 |
| 6 | Add `tenant_id` to `access_log`, add an RLS policy, add the `WHERE` to `_fetch_audit_page` | CS-3 |
| 7 | Default `env` to `prod`; fix the `OIDC_ISSUER` typo; remove the shipped secret default | CS-1 |
| 8 | Remove client-side JWT minting; source dev tokens from `mint_dev_token.py` | CS-1 |

### Phase 2 · Reconnect the frontend *(roughly one day's work)*
| | Task | Ref |
|---|---|---|
| 9 | **Generate `src/api/types.ts` from `/openapi.json`** — resolves most of CS-6 mechanically | CS-6 |
| 10 | Fix three request payloads + one route path (upload, reclassify, resolve) | CS-6 |
| 11 | Align `Role`/`Action` with `app/security/permissions.py` (5 roles, 8 actions, incl. `VIEW`) | CS-7 |
| 12 | Correct persona tenant/department UUIDs to the seeded `c0000000-…` values | CS-7 |
| 13 | Add CORS middleware so the presigned-redirect download works | F-7 |

### Phase 3 · Stop stranding documents
| | Task | Ref |
|---|---|---|
| 14 | Call `mark_document_failed` on every terminal failure, not just malware | H-3 |
| 15 | Write the reconciler that four comments already promise | H-4 |
| 16 | Fix `check_monotonic` to compare against the **current** label, scoped to `version_id` | H-2 |

### Phase 4 · Make it classify *(order matters)*
| | Task | Ref |
|---|---|---|
| 17 | **Reconcile `Taxonomy` with `registry.ENTITY_TYPES` first** — otherwise 18 crashes on first fire | CS-5 |
| 18 | Implement the four `scan()` bodies (validators, patterns and scorer already exist and are tested) | CS-5 |
| 19 | Train and deploy the calibrated classifier; wire `_predict_with_artifact` | backlog |
| 20 | Implement Tesseract OCR on the `ocr` queue — today every scanned PDF strands permanently | backlog |
| 21 | Implement embeddings so the vector arm and the HNSW index become live | backlog |

### Phase 5 · Completeness
| | Task | Ref |
|---|---|---|
| 22 | Persist extracted text so search snippets stop being empty strings | M-9 |
| 23 | Add the separate preview endpoint invariant #18 requires | M-2 |
| 24 | Add version-upload and document-delete endpoints | M-25 |
| 25 | Widen `Range` parsing to open-ended and suffix forms | H-7 |
| 26 | Unify audit `actor_id` on `provision_actor` | H-6 |
| 27 | Add `react-router`, URL-param filter state, and cursor pagination controls | F-9, F-10 |
| 28 | Implement SSE for `/v1/events`; drop the 15 s polling | backlog |

### Phase 6 · Hardening and confidence
| | Task | Ref |
|---|---|---|
| 29 | **Bring the API tests down onto real SQL** — the seam-mocking strategy left the query layer largely unverified | M-1 |
| 30 | **Add MSW-backed frontend integration tests per feature flow** — this is what prevents CS-6 recurring | F-5 |
| 31 | Add Nginx + Keycloak to compose; add security headers and rate limiting | M-8 |
| 32 | Run containers non-root; drop unused `curl`; `COPY scripts/` into the image | M-6, M-7 |
| 33 | Add an advisory lock (or a dedicated migrate job) so three containers stop racing on `alembic upgrade head` | M-4 |
| 34 | Fix `requires-python` to `>=3.12`; align dev/CI/container Python versions | M-5 |
| 35 | Add ESLint + Prettier; remove the 11 `any`s; adopt Radix (or add focus-trap/ARIA) for dialogs | F-11, F-14, F-16 |
| 36 | Correct `README.md`'s invariant matrix and `PROGRESS.md`'s frontend claims to match reality | §6 |

---

## 9. The Single Most Valuable Change

**Write one end-to-end test that runs the real stack** — compose up, upload a real PDF through the API, wait for the pipeline, assert `status='ready'`, then fetch it back through the frontend's own API client.

`scripts/e2e.sh` and `tests/integration/test_e2e_upload_to_review.py` are close to this and were reported passing — but they run against a hand-tuned local environment, not the shipped compose stack, and they never exercise the frontend's client code. That single gap is why five Critical findings coexist with seven green quality gates.

Every one of CS-4, CS-5, CS-6 and CS-7 would have failed loudly on the first run of such a test.

---

## 10. Closing Assessment

The engineering judgement on display here is good. Choices like the deferred circular FK, the shared immutability guard, the structural search-filter composition, the byte-stable 404, the fail-closed clamd parser and the artifact-contract enforcement are the choices of someone who understood the problem. The invariant discipline in AGENTS.md is unusually well thought through, and the code honours its *intent* far more often than the finding count suggests.

What is missing is not skill or care. It is the assembly step — and the integration tests that would have forced it. The system was built as a set of correct components with the seams left as documented intentions, and those intentions were then reported as completions.

The path forward is short and mostly mechanical: **Phases 0–2 above are on the order of two to three days of focused work** and take the project from "does not run" to "demonstrably works end-to-end." Phase 4 then delivers the actual product promise — automatic classification — on top of validators and a scorer that are already written and tested.

Nothing here needs redesigning. It needs connecting, then proving.
