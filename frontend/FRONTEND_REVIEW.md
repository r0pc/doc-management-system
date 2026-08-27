# Frontend Review — Secure Document Management System

**Reviewed**: 2026-08-27 · commit `0f75ad6` (branch `main`, clean tree)
**Scope**: `frontend/` — React 18 + TypeScript (strict) + Vite + Tailwind + TanStack Query
**Method**: full read of all 41 source files; every API call cross-checked field-by-field against the backend's Pydantic response models; gates re-run locally.

---

## 1. Verdict

The frontend is **a visually polished, well-structured shell that has never been run against the real API.**

The GitHub Primer design system, the dark/light theme provider, the layout and the component library are competently built and look right. Underneath, **the entire `src/api/` layer was hand-written from an imagined API contract that does not match the backend on a single non-trivial endpoint.** Field names, request payloads, one route path, the role vocabulary and the seeded tenant UUIDs are all wrong.

AGENTS.md states the rule that was skipped:

> If you changed any route or response model, **regenerate the OpenAPI client rather than hand-editing `frontend/src/api/`.**

The client was hand-authored instead. TypeScript cannot catch this because `api.get<T>()` is an unchecked cast over `response.json()` — so `tsc --noEmit` is clean while every page renders `undefined`.

| Dimension | Rating |
|---|---|
| Visual design / theming | Strong |
| Component structure & composition | Good |
| TypeScript config discipline | Good (strict, `noUnusedLocals`) |
| Actual type *safety* at the API boundary | **None** — unchecked casts |
| **API contract fidelity** | **Broken — 0 of 8 feature flows work** |
| Auth / persona wiring | **Broken** — wrong roles, wrong tenant UUIDs |
| Test coverage | **Negligible** — 12 trivial tests, 0 feature tests |
| Accessibility | Weak — hand-rolled dialogs, no focus management |
| Routing / URL state | Absent |

---

## 2. Verification Gates — Re-Run Independently

```
tsc --noEmit   → clean, 0 errors      ✅ (matches claim)
vitest run     → 12 passed / 4 files  ✅ (matches claim)
vite build     → dist/ generated      ✅ (matches claim)
```

The claims are accurate. They are also **not evidence of a working application** — see §4.

---

## 3. Critical Findings

### F-1 — Every API request or response shape is wrong

This is the central defect. Verified field-by-field against the backend's Pydantic models.

#### Responses the UI misreads

| Frontend expects (`src/api/types.ts`) | Backend actually returns | Visible result |
|---|---|---|
| `DocumentSummary.title` | `DocumentListItem.filename` | **Title column is blank on every row** |
| `.security_level_name` / `.security_level_rank` | `.level` (string, no rank) | `<LevelBadge>` renders empty for every document |
| `.doc_type_name` | `.doc_type` | Always shows "Unclassified" |
| `.byte_size` | *(not returned)* | `formatBytes(0)` → **"0 B" on every row** |
| `.tenant_id` / `.department_id` / `.mime_type` | *(not returned)* | `usePermissions` document checks are permanent no-ops |
| `ReviewQueueItem.id` | `.review_id` | **`POST /v1/review/undefined/resolve` → 422** |
| `.title` / `.suggested_level_name` / `.rule_confidence` / `.reasons` / `.status` | `.filename` / `.level` / `.confidence` / `.decided_by` / `.findings_count` | Review queue renders blank rows |
| `AccessLogOut.created_at` / `.ip_address` / `.details` | `.ts` / `.ip` / *(none)* | Audit timestamp and IP columns blank |
| `SearchResponse.query` / `.total` / `.facets.security_levels` | `.total_candidates` / `.facets.levels` | Facet panel and result count blank |
| `SearchResultItem.id` / `.title` / `.security_level_name` | `.version_id`+`.document_id` / `.filename` / `.level` | Search results render blank |
| `UploadIntentResponse.presigned_url` / `.expires_in_seconds` | `.presigned_put.url` / `.presigned_put.expires_at` | `putDirect(undefined, …)` |
| `DocTypeOut.slug` | *(not returned)* | Column blank |
| `SecurityLevelName = 'public' \| …` (lowercase) | Seeded as `'Public'`, `'Internal'`, … (capitalised) | Level string comparisons fail |

#### Requests the backend rejects

**Upload intent** — [UploadPage.tsx:58](frontend/src/features/upload/UploadPage.tsx#L58):
```ts
api.post('/v1/uploads', { title, department_id, mime_type, byte_size })
```
Backend `UploadIntentRequest` requires `{ filename, size_bytes, content_type }` — **all three required, none supplied.** → `400 request validation failed` on every attempt. **Uploading a document — the primary user journey — is 100% non-functional.**

**Reclassify** — [ReclassifyModal.tsx:40](frontend/src/features/documents/ReclassifyModal.tsx#L40):
```ts
api.post(`/v1/documents/${id}/reclassify`, { security_level_name, doc_type_name, reason })
```
The route is `POST /v1/documents/{id}/classification`. → **404.** The body is also wrong (`level_name`, `doc_type_id` expected; `doc_type_name` and `reason` are not fields the API accepts).

**Resolve review** — [ResolveReviewDialog.tsx:40](frontend/src/features/review/ResolveReviewDialog.tsx#L40):
```ts
api.post(`/v1/review/${item.id}/resolve`, { security_level_name, doc_type_name, resolution_notes })
```
`item.id` is `undefined` (backend sends `review_id`); the required `level_name` and `decision` fields are absent. → **422.**

**Filters that do nothing** — `DocumentsPage` sends `status` and `security_level`; `SearchPage` sends `security_level`; `App.tsx` sends `status`. None of these are query parameters the backend accepts (search wants `level`, not `security_level`), and FastAPI silently ignores unknown ones. **Every filter control in the UI is decorative.**

**Net effect**: of eight feature flows, exactly one — taxonomy list/create/delete — works, and only because `name` and `description` happen to match.

---

### F-2 — The dev JWT signing secret is hardcoded in shipped client code

[auth.tsx:152](frontend/src/api/auth.tsx#L152):

```ts
async function createDevJwt(persona: Persona, secret = 'dev-only-secret-change-me')
```

The browser mints its own HS256 tokens via `crypto.subtle` with **fully attacker-controlled claims** — `role`, `clearance_rank` and `tenant_id` are whatever the caller puts in the payload — signed with a secret that is (a) the backend's shipped `Settings.dev_jwt_secret` default and (b) embedded verbatim in the production bundle (confirmed present in `dist/assets/index-*.js`).

Chained with backend finding H-9 (`env` defaults to `"dev"`; `.env.example` misspells `OIDC_ISSUER` as `OIDC_ISSU`, so OIDC never activates), **any deployment that does not explicitly set `ENV=prod` grants full admin access to any tenant to anyone who opens DevTools.** The token expiry is 7 days (`86400 * 7`), versus the backend minter's 900 seconds.

The `<Can>`/`usePermissions` cosmetic-gating story (#33) is correct and well-implemented. This is a different problem: the client is a *token issuing authority*.

**Fix**: delete client-side minting. Fetch dev tokens from a dev-only backend endpoint (`mint_dev_token.py` already exists), or wire real OIDC. The secret must never be in the bundle.

---

### F-3 — The role vocabulary does not match the backend

| Frontend (`src/security/permissions.ts`) | Backend (`app/security/permissions.py`) |
|---|---|
| `admin` | `admin` ✅ |
| `compliance_officer` | — |
| `auditor` | — |
| `employee` | `employee` ✅ |
| — | `security_officer` |
| — | `dept_manager` |
| — | `viewer` |

`role_can` **fails closed on unknown roles**. So two of the five shipped dev personas — **Bob (Compliance Officer)** and **Dana (Internal Auditor)** — receive `403 insufficient role` on every single request, including the Audit page Dana exists to demonstrate.

The action vocabulary diverges too: the frontend defines `SEARCH` and `MANAGE_USERS`, which the backend does not have, and **omits `VIEW`**, which the backend requires for `/v1/documents`, `/v1/search` and `/v1/documents/{id}/jobs`. `<Can>` therefore gates on a permission model unrelated to the one being enforced — showing controls that will 403, and hiding controls the user is entitled to.

---

### F-4 — Persona tenant and department UUIDs do not exist in the database

`DEV_PERSONAS` uses:
```
tenantId:     00000000-0000-0000-0000-000000000001
departmentId: 00000000-0000-0000-0000-000000000010 / 0020 / 0099
```

Migration `0003_seed_taxonomy.py` seeds:
```
tenant:       c0000000-0000-0000-0000-000000000001
departments:  c0000000-0000-0000-0000-000000000011 / 0012 / 0013
```

**Zero overlap.** Consequences against a freshly migrated database:

- `enrich_visible_departments` finds no matching department → `visible_department_ids = ()` → the document list adds `WHERE department_id IS NULL` → **every list is empty**.
- If upload were fixed (F-1), `provision_actor` would `INSERT INTO users (tenant_id) VALUES ('0000…0001')` → **FK violation against `tenants.id`** → 500.

Even with F-1 and F-3 repaired, the app authenticates as a tenant that does not exist.

---

## 4. High-Severity Findings

### F-5 — Near-zero test coverage, and none of it touches the defects above

12 tests across 4 files: `utils.test.ts` (3), `Can.test.tsx` (3), `LevelBadge.test.tsx` (4), `ThemeProvider.test.tsx` (2).

**Zero tests** for: the API client, `auth.tsx`, upload, documents, review, search, audit, taxonomy, `DocumentDrawer`, or any mutation. A single MSW-backed test asserting the real upload payload shape would have caught F-1 immediately. The "12 passed" gate is technically true and materially uninformative.

### F-6 — The client-side content split is inverted and dead

[DocumentDrawer.tsx:59](frontend/src/features/documents/DocumentDrawer.tsx#L59):

```ts
const rank = doc.security_level_rank ?? 2;
const levelName = doc.security_level_name ? … : 'internal';
const isHighClearance = rank >= 3 || ['confidential','restricted'].includes(levelName);
```

Neither field is returned by the backend (F-1), so `rank` is always `2` and `levelName` is always `'internal'` → **the "presigned redirect" branch is taken for every document, including Restricted ones.** Server-side enforcement means no security consequence, but PROGRESS.md's claim that `DocumentDrawer.tsx` implements Invariants #17/#18 is not accurate.

The two branches are also functionally identical — both `fetch` → `.blob()` → object URL. `api.fetchDocumentContent` is documented as "supporting range streaming" and **sends no `Range` header and streams nothing**; it buffers the entire file in memory before triggering the download.

### F-7 — The presigned-redirect download path is broken by CORS in dev

For Public/Internal the backend answers `303` with an absolute `Location` of `http://localhost:8000/v1/dev-storage/…` (`LocalStorage.DEV_PRESIGN_BASE_URL`). The app runs on `:5173` behind the Vite `/v1` proxy, so `fetch` follows the redirect **cross-origin**. The backend registers no `CORSMiddleware` (verified: `grep add_middleware app/` returns nothing), so the browser blocks it.

Downloading a Public or Internal document therefore fails in the standard dev setup. This is a joint frontend/backend defect.

### F-8 — The review-count poll 403s for most roles, every 15 seconds, forever

[App.tsx:22](frontend/src/App.tsx#L22) polls `/v1/review` with `refetchInterval: 15000` and **no `enabled` guard**. That endpoint requires `Action.RESOLVE_REVIEW`, which backend-side only `admin`, `security_officer` and `dept_manager` hold. Any `employee` or `viewer` session generates a permanent 403 loop in the console and network tab.

It also passes `status: 'pending'` — not a parameter the endpoint accepts (the backend hardcodes `state == "pending"`).

### F-9 — No router; filter state violates the stated rule

There is no `react-router`. Navigation is `useState<NavTab>` in `App.tsx`. Consequences: no deep linking, no back-button, no shareable URL for a document or a search, full state loss on refresh.

AGENTS.md is explicit — *"filter state in URL params, not component state"* — and every filter in `DocumentsPage`, `SearchPage` and `AuditPage` is `useState`.

### F-10 — Pagination exists server-side and is unreachable client-side

Every list endpoint returns `next_cursor` (invariant #32 correctly implemented backend-side). **No page in the frontend renders a next/previous control or passes a `cursor` param.** `DocumentsPage` hardcodes `limit: 50`, `AuditPage` `limit: 50`, `ReviewPage` `limit`, `SearchPage` `limit: 25`. Beyond the first page, records are permanently invisible.

The `CursorPaginated<T> | T[]` union types throughout signal genuine uncertainty about the response shape rather than defensive design.

---

## 5. Medium-Severity Findings

| # | Finding | Detail |
|---|---|---|
| F-11 | **`any` used 11 times in a "no `any`" codebase** | AGENTS.md: *"TypeScript — strict mode; no `any`."* Present in `client.ts:85`, `types.ts:120`, `query-client.ts:8`, `ProblemAlert.tsx:4`, and as `useState<any>(null)` for error state in all five feature pages. `vite.config.ts` also ends in `as any`. |
| F-12 | **`@tanstack/react-table` is declared and never imported** | `grep -rn "react-table" src/` → 0 hits. Tables are hand-rolled in `components/ui/table.tsx`. AGENTS.md forbids adding a dependency without justification; this one adds ~40 kB and does nothing. |
| F-13 | **No shadcn/ui despite the stated stack** | No `@radix-ui/*` dependency. `dialog.tsx`, `tabs.tsx` etc. are hand-rolled — which is the direct cause of F-14. |
| F-14 | **Dialogs and the drawer are inaccessible** | `DocumentDrawer` is a `fixed inset-0` div with no `role="dialog"`, no `aria-modal`, no focus trap, no Escape handler, no focus restore on close. Same for `ReclassifyModal` and `ResolveReviewDialog`. Keyboard and screen-reader users cannot operate or escape them. |
| F-15 | **Token stored in `localStorage`** | XSS-exfiltratable, and persists across tabs and restarts. For a security-classification product, an in-memory token with a refresh flow (or `httpOnly` cookie) is the expected posture. |
| F-16 | **No ESLint or Prettier configuration** | No `.eslintrc*`, no `eslint.config.*`, no `.prettierrc`. `tsc` is the only static check. Nothing enforces F-11. |
| F-17 | **`logout()` leaves the app unusable** | Clears token and user; the auto-login `useEffect` has `[]` deps so it never re-fires. Every request 401s until the user manually picks a persona. |
| F-18 | **`localStorage.getItem('dms_auth_token')` read directly in `DocumentDrawer`** | Bypasses the `getAuthToken()` accessor in `client.ts`, duplicating the storage-key knowledge in two places. |
| F-19 | **Colours are hardcoded hex, not Tailwind tokens** | Every component repeats `text-[#1f2328] dark:text-[#e6edf3]`, `border-[#d0d7de] dark:border-[#30363d]` inline. `tailwind.config.js` exists but the Primer palette is not defined as theme tokens, so changing one colour means editing dozens of files. |
| F-20 | **Upload page has no client-side size cap** | `UPLOAD_MAX_BYTES` is 100 MB server-side. The UI lets the user select a 2 GB file and only fails after the whole PUT. |
| F-21 | **`department_id` picker is decorative** | Sent on upload intent; the backend ignores it entirely and uses `user.department_id` from the token. |
| F-22 | **No global error boundary, no 401 interceptor** | A thrown render error blanks the app. An expired token produces a per-query error alert on each page rather than a re-authentication prompt. |
| F-23 | **`vite.config.ts` is outside `tsconfig` `include`** | `include: ["src"]` means the config file — and its `as any` — is never typechecked. |
| F-24 | **`TableSkeleton rows={6} cols={6}` vs 7 real columns** | Cosmetic layout shift on load. |
| F-25 | **`DocumentStatus` type omits `'held'`** | The backend's `status_valid` check constraint permits `quarantined \| processing \| ready \| failed \| held`. A `held` document falls through the status-badge ternary into the amber "processing" style. |
| F-26 | **No loading/disabled state on destructive taxonomy delete** | `deleteDocTypeMutation` fires without confirmation; the 409 conflict responses the backend returns for referenced types surface as a generic alert. |

---

## 6. What Has Been Accomplished

Real work, worth keeping:

- **A coherent, attractive GitHub Primer design system** applied consistently across seven pages — canvas, border, typography and accent tokens are correct and the visual result is genuinely good.
- **A working theme provider** with system/light/dark, `localStorage` persistence, and the only two tests in the repo that assert real behaviour.
- **Sensible component composition** — `AppLayout` / `Navbar` / `Sidebar` / `UserSwitcher`, a small `ui/` primitive set with `class-variance-authority` variants, and shared `EmptyState` / `LoadingSkeleton` / `ProblemAlert` used uniformly.
- **`<Can>` and `usePermissions` are the correct shape for invariant #33** — clearly documented as cosmetic, with the server as the real boundary. The implementation is right; only the role table feeding it is wrong (F-3).
- **TanStack Query used properly** — no `useEffect` fetches anywhere, sensible `queryKey` structure, correct `invalidateQueries` after every mutation, and a `retry` predicate that correctly refuses to retry 401/403/404.
- **`putDirect` via `XMLHttpRequest` with real progress events** — the right primitive for direct-to-storage upload with a progress bar, and correctly omits the `Authorization` header per invariant #1.
- **Strict TypeScript configuration** — `strict`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`, path aliases. The config is right; it just cannot see past the `api.get<T>()` cast.
- **A `ProblemDetails` type and `ApiError` class** that correctly parse the backend's RFC 7807 envelope.
- **Vite dev proxy** correctly configured for `/v1` and `/healthz`.

---

## 7. What Remains

### Blocking — nothing works until these land
1. **Regenerate `src/api/types.ts` from the backend's OpenAPI schema** (`/openapi.json` is already served). This is the single highest-value change in the repo and resolves most of F-1 mechanically.
2. **Fix the three wrong request payloads and the one wrong route** — upload intent, reclassify (`/classification`, not `/reclassify`), resolve review (F-1).
3. **Align `Role` and `Action` with `app/security/permissions.py`** — five roles, eight actions, including `VIEW` (F-3).
4. **Correct the persona tenant/department UUIDs to the `c0000000-…` values seeded by migration 0003** (F-4).
5. **Remove client-side JWT minting**; source dev tokens from the backend (F-2).

### High
6. Add MSW-backed integration tests for each feature flow (F-5) — this is what prevents F-1 from recurring.
7. Add `react-router` and move filter/tab state into URL params (F-9).
8. Implement cursor pagination controls on all four list views (F-10).
9. Fix the download split to read `level`, and add real `Range` support or stop claiming it (F-6).
10. Add CORS on the backend (or make dev presigns same-origin) so Public/Internal downloads work (F-7).
11. Gate the review-count poll on the caller's permission (F-8).

### Medium
12. Add ESLint + Prettier; eliminate the 11 `any`s (F-11, F-16).
13. Adopt Radix primitives (or add focus-trap/Escape/ARIA by hand) for the drawer and both modals (F-13, F-14).
14. Move the Primer palette into `tailwind.config.js` as theme tokens (F-19).
15. Drop the unused `@tanstack/react-table` dependency, or use it (F-12).
16. Move the token out of `localStorage`; add a 401 interceptor and an error boundary (F-15, F-22).
17. Client-side upload size validation; fix or remove the department picker (F-20, F-21).

### Backlog (already tracked in PROGRESS.md)
18. Replace the 15s review polling with SSE once `/v1/events` stops returning 501.

---

## 8. The One Thing to Take Away

Every claim in PROGRESS.md §4 about the frontend enforcing Invariants #1, #8, #12, #17, #18, #27, #28, #29, #32 describes **code that was written with those invariants in mind and cannot execute**, because the request never reaches the endpoint or the response field it reads does not exist.

That gap is closable in roughly a day: generate the client from the live OpenAPI schema, fix four payloads and one route, correct five persona records, and align one permission table. The design work, the component library and the query architecture underneath are sound and do not need to be rebuilt — they need to be connected.
