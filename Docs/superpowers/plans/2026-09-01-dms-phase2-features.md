# DMS Phase 2 Features Implementation Plan

> **For agentic workers:** Implement this plan task-by-task, in order. Steps use checkbox (`- [ ]`) syntax for tracking. Each task ends with a commit. Do not batch tasks that touch the same file.

**Goal:** Add sorting, bulk upload (≤1 GB per batch), admin-trainable document-type classifiers, and admin-defined sensitive-data detectors — without breaking any of the 33 invariants in `AGENTS.md`.

**Architecture:** Sorting generalises the existing keyset cursor rather than adding `OFFSET`. Bulk upload reuses the existing per-file intent→upload→complete sequence at bounded concurrency. Classifiers use a few-shot embedding centroid computed from already-stored vectors — no retraining, no calibration claim. Detectors are DB-backed rows compiled into the existing `Recognizer` contract, which forces a structural validator per invariant #10.

**Tech Stack:** FastAPI, Celery/Redis, PostgreSQL 16 + pgvector, SQLAlchemy 2 (async API / sync worker), Pydantic v2, Alembic, React 18 + TypeScript strict, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-dms-repair-and-admin-extensibility-design.md` (sections 6.1–6.4). Read it — it records *why* each decision was made, and this plan argues from it.

**Predecessor:** `docs/superpowers/plans/2026-08-31-dms-phase1-repairs.md`, fully landed and verified. Do not start this plan until `git log` shows `db866b6` or later on the branch.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec and from `AGENTS.md`.

- **Python >= 3.12.** PEP 758 bare `except A, B:` parses on the 3.14 dev host but SyntaxErrors on the 3.12 container base image — always parenthesise multi-type excepts.
- **TypeScript strict, no `any`.** Server state via TanStack Query, never `useEffect` fetches. Filter and sort state in URL params, not component state.
- **Never log or persist document text, extracted content, or matched identifier values.** Findings carry offsets only.
- **Never disable, weaken, or skip a test to make a build pass.** Report the failure instead.
- **Invariant #1** — the API does not read or write object bytes on the write path.
- **Invariant #2** — workers are the only automated writer of classifications. Training a prototype writes no classification, so it may run in a request handler; re-classifying existing documents must go through a worker task.
- **Invariant #6** — one extraction pass and one embedding pass per document, reused by both classification and search. Never re-encode text that already has a stored vector.
- **Invariant #9** — nothing matched defaults to `Internal` (`DEFAULT_FLOOR_RANK = 2`), never `Public`.
- **Invariant #10** — a recogniser is a pattern **plus** a structural validator **plus** context words scored in a ±50 character window. A bare regex is not acceptable.
- **Invariant #11** — ML probabilities must be calibrated. Prototype cosine similarity is **not** a calibrated probability; never store it in a field that implies it is, and never label a prototype decision `decided_by="ml"`.
- **Invariant #12** — `findings` stores character offsets, never matched text.
- **Invariant #26** — tenant scoping is enforced by row-level security, not by remembering a `WHERE` clause.
- **Invariant #32** — cursor pagination only. No `OFFSET`, ever.
- **Invariant #33** — client-side permission checks are cosmetic; every new admin route is gated server-side.
- **Conventional commits**: `feat|fix|refactor|test|docs|chore(scope): summary`.
- **Backend commands** from `backend/`: `./.venv/Scripts/python.exe -m pytest -q`, `-m mypy app`, `-m ruff check .`, `-m ruff format --check .`
- **Frontend commands** from `frontend/`: `npm run typecheck`, `npm run test`, `npm run build`
- **Baseline at plan start: backend 660 passed / 3 skipped / 13 deselected; frontend 81 passed.** Every task must leave both suites green.
- **Do not add dependencies** beyond those this plan names without justifying them in the commit message.

## Verified current-state facts

These were read from the code on 2026-09-01. They are the ground this plan stands on — if any has drifted, stop and re-check before proceeding.

| Fact | Value |
|---|---|
| Alembic head | `d7d1c3d1c60b` — your new migration's `down_revision` |
| Cursor encoding | `base64(f"{created_at.isoformat()}\|{document_id}")`, `documents.py` |
| Page query ordering | `.order_by(Document.created_at.asc(), Document.id.asc())` |
| Keyset predicate | `tuple_(Document.created_at, Document.id) > after` |
| Page fn signature | `_fetch_document_page(session, user, after, limit_plus_one, *, status=None, level=None)` |
| Statuses | `DOCUMENT_STATUSES = ("quarantined","processing","ready","failed","held")` |
| Upload presign | `presign_put(key, ttl, *, content_type, max_bytes) -> PresignedUpload(url, fields)` |
| Upload transport | `putDirect(url, file, contentType, fields, onProgress?, signal?)` — POST+FormData when `fields` non-empty (S3/MinIO), PUT otherwise (LocalStorage dev). **Both paths must keep working.** |
| Object metadata | `Storage.stat(key) -> ObjectStat(size_bytes) \| None` |
| Cascade entry | `classify(extracted_text, tax, artifact, *, ml_threshold, embedding)` — **pure, no session** |
| Recogniser contract | `Recognizer` ABC: ClassVars `entity_type`/`pattern`/`context_words`; abstract `validate(match_text)->bool`, `scan(text)->list[Finding]` |
| Context scorer | `score_with_context(text, match_span, context_words, window=50, base=0.4, boost_to=0.9)` — pure, reuse it |
| Recogniser registry | `iter_recognizers()` — hardcoded four types, **no tenant argument** |
| Level aggregation | `Taxonomy(entity_rank: Mapping[str,int])`, `.rank_for(finding)` **raises on unknown entity_type** |
| Admin seam pattern | `admin.py` uses module-level `_fetch_*` / `_insert_*` functions that tests monkeypatch |

---

## Task 1: Generalise the cursor to carry sort field and direction

**Files:**
- Modify: `backend/app/api/v1/documents.py` (`encode_cursor`, `decode_cursor`)
- Test: `backend/tests/api/test_sort_cursor.py` (create)

**Interfaces:**
- Produces: `SortField` literal type; `encode_cursor(sort_field, direction, sort_value, document_id) -> str`; `decode_cursor(token) -> SortCursor` where `SortCursor` is a frozen dataclass carrying `field`, `direction`, `value`, `document_id`.

**Why:** The cursor currently encodes only `(created_at, id)`. If sort field or direction could change mid-walk, a client could skip or repeat rows. Encoding both *in the token* makes a page inseparable from the sort that produced it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_sort_cursor.py
"""The cursor must carry its own sort, so a page cannot change sort mid-walk."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.v1.documents import decode_cursor, encode_cursor


def test_roundtrip_preserves_field_direction_value_and_id() -> None:
    doc_id = uuid.uuid4()
    when = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)
    token = encode_cursor("created_at", "desc", when, doc_id)
    cur = decode_cursor(token)
    assert cur.field == "created_at"
    assert cur.direction == "desc"
    assert cur.value == when
    assert cur.document_id == doc_id


def test_roundtrip_supports_a_text_sort_value() -> None:
    doc_id = uuid.uuid4()
    token = encode_cursor("filename", "asc", "invoice.pdf", doc_id)
    cur = decode_cursor(token)
    assert cur.field == "filename"
    assert cur.value == "invoice.pdf"


def test_roundtrip_supports_a_null_sort_value() -> None:
    """Unclassified rows sort by a NULL doc_type; the cursor must survive it."""
    doc_id = uuid.uuid4()
    cur = decode_cursor(encode_cursor("doc_type", "asc", None, doc_id))
    assert cur.value is None
    assert cur.document_id == doc_id


@pytest.mark.parametrize(
    "bad",
    ["", "not-base64!!", "YWJj", "eyJmaWVsZCI6ICJvd25lciJ9"],
    ids=["empty", "not_b64", "b64_but_not_our_shape", "unknown_sort_field"],
)
def test_unusable_cursor_is_a_400_that_leaks_nothing(bad: str) -> None:
    with pytest.raises(HTTPException) as exc:
        decode_cursor(bad)
    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid cursor"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/api/test_sort_cursor.py -v`
Expected: FAIL — `encode_cursor()` takes 2 positional arguments.

- [ ] **Step 3: Implement**

In `backend/app/api/v1/documents.py`, replace `encode_cursor` / `decode_cursor`:

```python
SortField = Literal["created_at", "filename", "status", "level", "doc_type"]
SortDirection = Literal["asc", "desc"]

SORT_FIELDS: Final[tuple[str, ...]] = (
    "created_at",
    "filename",
    "status",
    "level",
    "doc_type",
)


@dataclass(frozen=True)
class SortCursor:
    """A keyset position: which sort produced it, and where it stopped.

    The sort travels INSIDE the token so a page cannot be interpreted under a
    different sort than the one that produced it — that would silently skip or
    repeat rows across a page boundary (#32).
    """

    field: str
    direction: str
    value: datetime | str | None
    document_id: uuid.UUID


def encode_cursor(
    sort_field: str,
    direction: str,
    sort_value: datetime | str | None,
    document_id: uuid.UUID,
) -> str:
    payload = {
        "f": sort_field,
        "d": direction,
        "v": sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value,
        "t": "dt" if isinstance(sort_value, datetime) else ("null" if sort_value is None else "s"),
        "i": str(document_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(token: str) -> SortCursor:
    # Broad except is deliberate: b64/json/isoformat/uuid failures all mean the
    # same thing — an unusable cursor — and none may leak decoder internals.
    try:
        raw = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        field, direction, kind = raw["f"], raw["d"], raw["t"]
        if field not in SORT_FIELDS or direction not in ("asc", "desc"):
            raise ValueError("unknown sort")
        value: datetime | str | None
        if kind == "dt":
            value = datetime.fromisoformat(raw["v"])
        elif kind == "null":
            value = None
        else:
            value = str(raw["v"])
        return SortCursor(field, direction, value, uuid.UUID(raw["i"]))
    except Exception as exc:
        raise HTTPException(HTTP_400_BAD_REQUEST, "invalid cursor") from exc
```

Add `import json` and `from dataclasses import dataclass` if absent. Keep the existing `HTTP_400_BAD_REQUEST` import.

- [ ] **Step 4: Run the test and the full suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/api/test_sort_cursor.py -v` then `-m pytest -q`
Expected: new tests PASS. **Existing `test_documents_list.py` cursor tests will now FAIL** — they call the old two-argument form. That is expected; Task 2 updates them. Do not proceed to commit until Task 2 is done if you prefer one green commit; otherwise commit both together at the end of Task 2.

- [ ] **Step 5: Do not commit yet** — Task 2 finishes this change. Commit at the end of Task 2.

---

## Task 2: Sort the document list by any column, keyset-safe

**Files:**
- Modify: `backend/app/api/v1/documents.py` (`_fetch_document_page`, `list_documents`)
- Modify: `backend/tests/api/test_documents_list.py` (cursor call sites)
- Test: `backend/tests/api/test_document_sorting.py` (create)
- Modify: `frontend/src/features/documents/DocumentsPage.tsx`, `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: `SortCursor`, `SORT_FIELDS` from Task 1.
- Produces: `GET /v1/documents?sort=<field>&direction=<asc|desc>` alongside existing `status` / `security_level` / `limit` / `cursor`.

**Why:** Invariant #32 forbids `OFFSET`, so each sortable column needs its own keyset tuple. `level` and `doc_type` come from `isouter` joins and are nullable — a raw tuple comparison against NULL yields NULL (not true/false), which **silently drops rows at page boundaries**. Every sort key must be `coalesce`d.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_document_sorting.py
"""Sorting must stay keyset-paginated (#32) and must not drop rows.

The dangerous case is a nullable sort column: `(NULL, id) > (value, id)` is
NULL, not false, so an uncoalesced keyset predicate silently drops every
unclassified row at a page boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

SORTABLE = ["created_at", "filename", "status", "level", "doc_type"]


@pytest.mark.parametrize("field", SORTABLE)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sort_params_reach_the_query(
    client: Any, captured_page_args: dict[str, Any], field: str, direction: str
) -> None:
    client.get(f"/v1/documents?sort={field}&direction={direction}")
    assert captured_page_args["sort_field"] == field
    assert captured_page_args["direction"] == direction


def test_sort_defaults_to_created_at_asc(client: Any, captured_page_args: dict[str, Any]) -> None:
    client.get("/v1/documents")
    assert captured_page_args["sort_field"] == "created_at"
    assert captured_page_args["direction"] == "asc"


@pytest.mark.parametrize("bad", ["owner", "size", "'; DROP TABLE documents;--"])
def test_unknown_sort_field_is_rejected(client: Any, bad: str) -> None:
    """A silently ignored sort is how the filter bug shipped. Reject instead."""
    assert client.get(f"/v1/documents?sort={bad}").status_code == 400


def test_cursor_carries_the_sort_and_is_rejected_under_a_different_one(client: Any) -> None:
    """A page cannot be re-interpreted under a sort it was not produced by."""
    from app.api.v1.documents import encode_cursor
    import uuid

    token = encode_cursor("filename", "asc", "a.pdf", uuid.uuid4())
    response = client.get(f"/v1/documents?sort=status&direction=asc&cursor={token}")
    assert response.status_code == 400
```

- [ ] **Step 2: Write the integration test that catches the NULL trap**

This one needs real Postgres. Put it in `backend/tests/integration/test_sort_pagination.py` and mark it `@pytest.mark.integration`.

```python
# backend/tests/integration/test_sort_pagination.py
"""Paging through a sort must return every row exactly once.

Seeds documents that are deliberately mixed: some classified, some not, so
`level` and `doc_type` are NULL for a subset. Walks every sort column in both
directions one page at a time and asserts the union of pages equals the
unpaginated set. An uncoalesced keyset predicate fails this and nothing else.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

SORTABLE = ["created_at", "filename", "status", "level", "doc_type"]


@pytest.mark.parametrize("field", SORTABLE)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_paging_a_sort_returns_every_row_exactly_once(
    seeded_mixed_documents, api_client, field: str, direction: str
) -> None:  # noqa: ANN001
    expected = {d.id for d in seeded_mixed_documents}
    seen: list[str] = []
    cursor = None
    for _ in range(50):  # generous bound; the set is small
        url = f"/v1/documents?sort={field}&direction={direction}&limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        body = api_client.get(url).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            break
    assert len(seen) == len(set(seen)), f"{field}/{direction} returned a duplicate row"
    assert {str(i) for i in expected} == set(seen), f"{field}/{direction} dropped rows"
```

Read `backend/tests/integration/conftest.py` for the existing fixture names and reuse them. Add a `seeded_mixed_documents` fixture that creates at least 7 documents where **at least 2 have no classification** (so `level` and `doc_type` are NULL) and at least two share a `created_at` value (so the `id` tiebreaker is exercised). If an `api_client` fixture does not exist, build one following the pattern already in that file.

- [ ] **Step 3: Run both to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/api/test_document_sorting.py -v`
Expected: FAIL — `captured_page_args` has no `sort_field`.

- [ ] **Step 4: Implement the sortable query**

In `backend/app/api/v1/documents.py`, add above `_fetch_document_page`:

```python
def _sort_expression(sort_field: str) -> Any:
    """The ORDER BY / keyset expression for a sort column.

    Nullable columns are coalesced to an explicit sentinel so unclassified rows
    sort predictably and — critically — so the keyset comparison is never NULL.
    `(NULL, id) > (value, id)` evaluates to NULL, not false, which silently
    DROPS those rows at a page boundary instead of ordering them (#32).

    level coalesces to DEFAULT_FLOOR_RANK because that is the rank an
    unclassified document is actually authorised at (#9) — sorting it anywhere
    else would disagree with how it is treated.
    """
    if sort_field == "created_at":
        return Document.created_at
    if sort_field == "filename":
        return Document.original_filename
    if sort_field == "status":
        return Document.status
    if sort_field == "level":
        return func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK)
    if sort_field == "doc_type":
        return func.coalesce(DocType.name, "")
    msg = f"unsortable field: {sort_field}"
    raise ValueError(msg)
```

Change the signature and the ordering/keyset block:

```python
async def _fetch_document_page(
    session: AsyncSession,
    user: UserCtx,
    after: SortCursor | None,
    limit_plus_one: int,
    *,
    status: str | None = None,
    level: str | None = None,
    sort_field: str = "created_at",
    direction: str = "asc",
) -> list[DocumentListItem]:
```

Replace the `.order_by(...)` call with:

```python
    sort_col = _sort_expression(sort_field)
    ascending = direction == "asc"
    order = (sort_col.asc(), Document.id.asc()) if ascending else (sort_col.desc(), Document.id.desc())
```

then apply `stmt = stmt.order_by(*order)` after the joins, and replace the `if after is not None:` block with:

```python
    if after is not None:
        # (sort_col, id) is a total order: id is the tiebreaker and is never
        # omitted, so two rows with an equal sort value still page correctly.
        anchor = (after.value if after.value is not None else _null_sentinel(sort_field))
        keyset = tuple_(sort_col, Document.id)
        stmt = stmt.where(keyset > (anchor, after.document_id) if ascending
                          else keyset < (anchor, after.document_id))
```

Add the sentinel helper next to `_sort_expression`:

```python
def _null_sentinel(sort_field: str) -> Any:
    """The value a NULL sort key was coalesced to, for cursor comparison."""
    return DEFAULT_FLOOR_RANK if sort_field == "level" else ""
```

Also select the sort value so the cursor can be built. Add `SecurityLevel.rank.label("level_rank")` to the SELECT list and carry it on `DocumentListItem` (or return it alongside — whichever matches how the row is unpacked; check the existing unpack before choosing).

- [ ] **Step 5: Wire the route**

```python
    sort: Literal[SORT_FIELDS] | None = Query(default=None),  # type: ignore[valid-type]
    direction: Literal["asc", "desc"] = Query(default="asc"),
```

In the body:

```python
    after = decode_cursor(cursor) if cursor is not None else None
    sort_field = sort or (after.field if after else "created_at")
    sort_dir = after.direction if after else direction
    if after is not None and sort is not None and (sort != after.field or direction != after.direction):
        raise HTTPException(HTTP_400_BAD_REQUEST, "invalid cursor")
```

and pass `sort_field=sort_field, direction=sort_dir` into `_fetch_document_page`. Build the next cursor from the last row's sort value:

```python
    next_cursor = (
        encode_cursor(sort_field, sort_dir, _sort_value_of(page[-1], sort_field), page[-1].id)
        if has_more and page
        else None
    )
```

Write `_sort_value_of(item, sort_field)` to read the matching attribute off the row.

- [ ] **Step 6: Update the existing cursor call sites**

`backend/tests/api/test_documents_list.py` calls `encode_cursor(created_at, id)`. Update every call to the four-argument form. Do **not** weaken any assertion — these tests pin real pagination behaviour.

- [ ] **Step 7: Frontend sort controls**

In `DocumentsPage.tsx`, make each of the five column headers a button that sets `sort` and `direction` in the URL search params (never component state), toggling direction when the same column is clicked twice, and resetting the cursor stack. Show an ascending/descending indicator on the active column. Pass both params through `client.ts`'s document-list call.

- [ ] **Step 8: Run all gates**

Run: `./.venv/Scripts/python.exe -m pytest -q`, `-m ruff check .`, `-m ruff format --check .`, `-m mypy app`, then `cd ../frontend && npm run typecheck && npm run test`
Expected: all green. Then run the integration test with a live stack:
`docker compose up -d && DATABASE_URL=postgresql+psycopg://docmgmt:docmgmt@localhost:5433/docmgmt ./.venv/Scripts/python.exe -m pytest -m integration -q`

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/v1/documents.py backend/tests/api/ backend/tests/integration/ frontend/src/
git commit -m "feat(documents): sortable document list on a keyset cursor (#32)

Generalises the cursor from (created_at, id) to (sort_value, id) plus the
sort field and direction, both encoded in the token so a page cannot be
re-interpreted under a different sort. Nullable join columns are coalesced:
an uncoalesced keyset predicate against NULL evaluates to NULL, not false,
and silently drops unclassified rows at page boundaries."
```

---

## Task 3: Accept and account for a bulk upload batch

**Files:**
- Modify: `backend/app/api/v1/uploads.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/api/test_batch_upload.py` (create)

**Interfaces:**
- Produces: `POST /v1/uploads/batch` accepting `{files: [{filename, size_bytes, content_type}], ...}` and returning one presigned upload per file plus a `batch_id`.
- Consumes: existing `create_upload_intent` internals, `Settings.upload_max_bytes`.

**Why:** The spec locks 1 GB per batch, 100 MB per file. The per-file cap is already enforced by `presign_put`'s `content-length-range` (Phase 1 Task 9). The batch cap is new and must be enforced server-side — a client-side sum is not enforcement.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_batch_upload.py
"""Batch cap is server-side. A client-side sum is not enforcement."""

from __future__ import annotations

from typing import Any

MB = 1024 * 1024
GB = 1024 * MB


def _files(*sizes: int) -> list[dict[str, Any]]:
    return [
        {"filename": f"doc{i}.pdf", "size_bytes": s, "content_type": "application/pdf"}
        for i, s in enumerate(sizes)
    ]


def test_batch_returns_one_presigned_upload_per_file(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(10, 20, 30)})
    assert response.status_code == 201
    body = response.json()
    assert len(body["uploads"]) == 3
    assert all(u["presigned_put"]["url"] for u in body["uploads"])
    assert len({u["upload_id"] for u in body["uploads"]}) == 3


def test_batch_total_over_one_gb_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(600 * MB, 600 * MB)})
    assert response.status_code == 413
    assert "batch" in response.json()["detail"].lower()


def test_single_file_over_the_per_file_cap_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(200 * MB)})
    assert response.status_code == 413


def test_empty_batch_is_rejected(client: Any) -> None:
    assert client.post("/v1/uploads/batch", json={"files": []}).status_code == 422


def test_batch_over_the_file_count_cap_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(*([1] * 501))})
    assert response.status_code == 422


def test_rejected_batch_creates_no_documents(client: Any, monkeypatch: Any) -> None:
    """A batch is all-or-nothing at intent time: no partial document rows."""
    inserted: list[Any] = []
    from app.api.v1 import uploads

    monkeypatch.setattr(uploads, "_insert_document", lambda *a, **k: inserted.append(a))
    client.post("/v1/uploads/batch", json={"files": _files(600 * MB, 600 * MB)})
    assert inserted == []
```

Adapt fixture names to `backend/tests/api/conftest.py`'s existing ones, and the `_insert_document` seam name to whatever `uploads.py` actually calls.

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/api/test_batch_upload.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`:

```python
    upload_batch_max_bytes: int = 1073741824  # 1 GiB total per batch
    upload_batch_max_files: int = 500
```

- [ ] **Step 4: Implement the route**

In `backend/app/api/v1/uploads.py`:

```python
class BatchFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1)
    content_type: str = Field(min_length=1)


class BatchUploadRequest(BaseModel):
    files: list[BatchFileRequest] = Field(min_length=1)


@router.post("/batch", status_code=201, response_model=BatchUploadResponse)
async def create_batch_upload_intent(
    request: Request,
    payload: BatchUploadRequest,
    user: UserCtx = Depends(deps.require(Action.UPLOAD)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
) -> BatchUploadResponse:
    """Sign one upload per file. Caps are checked BEFORE any row is written.

    All-or-nothing at intent time: a batch that breaches a cap creates no
    document rows at all, so a rejected batch leaves nothing to reconcile.
    """
    if len(payload.files) > settings.upload_batch_max_files:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            f"batch exceeds {settings.upload_batch_max_files} files",
        )
    for f in payload.files:
        if f.size_bytes > settings.upload_max_bytes:
            raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "a file exceeds the per-file cap")
    if sum(f.size_bytes for f in payload.files) > settings.upload_batch_max_bytes:
        raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "batch exceeds the total size cap")
    ...
```

Then, inside one transaction, create an intent per file by reusing the same helpers `create_upload_intent` calls (`_insert_document`, `_provision_actor`, `record_audit`, `storage.presign_put(..., max_bytes=settings.upload_max_bytes)`). Write one audit row per file with action `upload.init`, in the same transaction, then commit once (#30).

Define `BatchUploadResponse` with `batch_id: uuid.UUID` and `uploads: list[UploadIntentResponse]`.

- [ ] **Step 5: Run gates and commit**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m mypy app
git add backend/app/api/v1/uploads.py backend/app/config.py backend/tests/api/test_batch_upload.py
git commit -m "feat(uploads): batch upload intent with a server-enforced 1 GiB cap

Caps are checked before any document row is written, so a rejected batch
leaves nothing to reconcile. Per-file enforcement remains the presigned
POST content-length-range from Phase 1; the batch total is new."
```

---

## Task 4: Bulk upload UI with per-file progress and partial success

**Files:**
- Modify: `frontend/src/features/upload/UploadPage.tsx`
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`
- Test: `frontend/src/features/upload/UploadPage.test.tsx` (extend)

**Why:** One failed file must not abort the batch. Partial success is a first-class outcome, and the existing single-file path must keep working — including both transports (`fields` non-empty → POST; empty → PUT).

- [ ] **Step 1: Write the failing tests**

```tsx
// append to frontend/src/features/upload/UploadPage.test.tsx
describe('UploadPage — bulk upload', () => {
  it('accepts multiple files and lists each with its own row', async () => {
    render(<UploadPage />, { wrapper });
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    await userEvent.upload(input, [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
    ]);
    expect(await screen.findByText('a.pdf')).toBeInTheDocument();
    expect(await screen.findByText('b.pdf')).toBeInTheDocument();
  });

  it('blocks a batch whose total exceeds 1 GiB before contacting the API', async () => {
    const post = vi.spyOn(api, 'post');
    render(<UploadPage />, { wrapper });
    const big = () => new File([new ArrayBuffer(1)], 'big.pdf', { type: 'application/pdf' });
    // size is stubbed via Object.defineProperty in the existing helper
    await uploadFilesOfSize([600 * 1024 ** 2, 600 * 1024 ** 2]);
    expect(await screen.findByText(/exceeds/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('one failing file does not abort the rest of the batch', async () => {
    mockBatchWithOneFailure();
    render(<UploadPage />, { wrapper });
    await uploadTwoFiles();
    expect(await screen.findByTestId('file-status-a.pdf')).toHaveTextContent(/done/i);
    expect(await screen.findByTestId('file-status-b.pdf')).toHaveTextContent(/failed/i);
  });

  it('reports a partial-success summary', async () => {
    mockBatchWithOneFailure();
    render(<UploadPage />, { wrapper });
    await uploadTwoFiles();
    expect(await screen.findByText(/1 of 2 uploaded/i)).toBeInTheDocument();
  });
});
```

Match the helper names to what already exists in that file; add small local helpers rather than a mocking library.

- [ ] **Step 2: Implement**

- Add `multiple` to the file input; keep `accept` including `.txt`.
- Hold `files: {file, status, percent, error}[]` in state; render one row per file with its own progress bar and status.
- Validate client-side (per-file cap, batch total, file count) *before* calling the API, purely for fast feedback — the server remains the enforcement.
- Call `POST /v1/uploads/batch` once, then upload each file with bounded concurrency (**3 at a time**; more risks presign expiry on slow links).
- Pass each upload's `fields` through to `putDirect` so both transports keep working.
- On per-file failure, mark that row failed and continue; never throw out of the loop.
- Give each file its own `AbortController`; keep the existing cancel affordance and make it cancel the whole batch.
- Render a final summary: `N of M uploaded`, with the failures listed.

- [ ] **Step 3: Gates and commit**

```bash
cd frontend && npm run typecheck && npm run test && npm run build
git add frontend/src/
git commit -m "feat(upload): bulk upload with per-file progress and partial success

One failed file no longer aborts the batch. Client-side caps are fast
feedback only; the server-side batch cap is the enforcement. Both upload
transports (presigned POST for S3, PUT for local dev) are preserved."
```

---

## Task 5: Migration 0006 — tenant doc types, prototypes, detector rules

**Files:**
- Create: `backend/alembic/versions/0006_admin_extensibility.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/integration/test_migration_0006.py` (create, `@pytest.mark.integration`)

**Interfaces:**
- Produces: `doc_types.tenant_id` (nullable), tables `doc_type_prototypes` and `detector_rules`, both RLS-enabled and forced.
- `down_revision = "d7d1c3d1c60b"`.

**Why:** `doc_types` currently sits **outside RLS entirely** (see `0002`'s docstring). Adding a tenant column without a policy that admits `tenant_id IS NULL` would make every seeded global type invisible to every tenant — the single highest-risk change in this plan.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_migration_0006.py
"""0006 must not hide the global doc types it did not create.

doc_types was outside RLS. Adding tenant_id plus a naive policy would make
every seeded global type invisible to every tenant.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

TENANT_A = "c0000000-0000-0000-0000-000000000001"


def test_global_doc_types_remain_visible_under_rls(app_role_db) -> None:  # noqa: ANN001
    with app_role_db.begin() as conn:
        conn.execute(text("SET LOCAL app.tenant_id = :t"), {"t": TENANT_A})
        rows = conn.execute(text("SELECT count(*) FROM doc_types WHERE tenant_id IS NULL")).scalar()
    assert rows and rows > 0, "0006's RLS policy hid the seeded global doc types"


def test_tenant_cannot_see_another_tenants_doc_type(app_role_db) -> None:  # noqa: ANN001
    other = "c0000000-0000-0000-0000-0000000000ff"
    with app_role_db.begin() as conn:
        conn.execute(text("SET LOCAL app.tenant_id = :t"), {"t": TENANT_A})
        conn.execute(
            text(
                "INSERT INTO doc_types (id, parent_id, name, description, tenant_id) "
                "VALUES (gen_random_uuid(), NULL, 'ATenantType', '', :t)"
            ),
            {"t": TENANT_A},
        )
    with app_role_db.begin() as conn:
        conn.execute(text("SET LOCAL app.tenant_id = :t"), {"t": other})
        found = conn.execute(
            text("SELECT count(*) FROM doc_types WHERE name = 'ATenantType'")
        ).scalar()
    assert found == 0


@pytest.mark.parametrize("table", ["doc_type_prototypes", "detector_rules"])
def test_new_tables_have_rls_enabled_and_forced(db, table: str) -> None:  # noqa: ANN001
    with db.begin() as conn:
        row = conn.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
            {"t": table},
        ).one()
    assert row[0] is True, f"{table} does not have RLS enabled (#26)"
    assert row[1] is True, f"{table} does not FORCE RLS (#26)"


def test_prototype_requires_at_least_five_samples(app_role_db) -> None:  # noqa: ANN001
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with app_role_db.begin() as conn:
            conn.execute(text("SET LOCAL app.tenant_id = :t"), {"t": TENANT_A})
            conn.execute(
                text(
                    "INSERT INTO doc_type_prototypes "
                    "(id, tenant_id, doc_type_id, centroid_vector, sample_count) "
                    "SELECT gen_random_uuid(), :t, id, "
                    "array_fill(0.0::real, ARRAY[384])::vector, 4 FROM doc_types LIMIT 1"
                ),
                {"t": TENANT_A},
            )


def test_detector_rule_requires_a_validator(app_role_db) -> None:  # noqa: ANN001
    """#10: a bare regex is not an acceptable recogniser."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with app_role_db.begin() as conn:
            conn.execute(text("SET LOCAL app.tenant_id = :t"), {"t": TENANT_A})
            conn.execute(
                text(
                    "INSERT INTO detector_rules (id, tenant_id, entity_type, pattern, "
                    "validator_kind, context_words, level_rank, enabled) VALUES "
                    "(gen_random_uuid(), :t, 'x', 'y', NULL, ARRAY['a'], 3, true)"
                ),
                {"t": TENANT_A},
            )
```

Reuse `db` and `app_role_db` from `backend/tests/integration/conftest.py`.

- [ ] **Step 2: Run it to verify it fails**

Expected: FAIL — the tables do not exist.

- [ ] **Step 3: Write the migration**

`backend/alembic/versions/0006_admin_extensibility.py`, with `revision = "0006_admin_extensibility"` and `down_revision = "d7d1c3d1c60b"`. It must:

1. `ALTER TABLE doc_types ADD COLUMN tenant_id UUID NULL REFERENCES tenants(id) ON DELETE CASCADE`.
2. Enable + force RLS on `doc_types` with a policy that **admits NULL**:
   ```sql
   CREATE POLICY tenant_isolation ON doc_types FOR ALL TO docmgmt_app
   USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
   ```
3. Create `doc_type_prototypes(id, tenant_id, doc_type_id, centroid_vector vector(384) NOT NULL, sample_count INT NOT NULL CHECK (sample_count >= 5), created_at, updated_at)`, unique `(tenant_id, doc_type_id)`, an hnsw index on `centroid_vector vector_cosine_ops`, RLS enabled + forced with the standard tenant policy.
4. Create `detector_rules(id, tenant_id, entity_type TEXT NOT NULL, pattern TEXT NOT NULL, validator_kind TEXT NOT NULL, validator_config JSONB NOT NULL DEFAULT '{}', context_words TEXT[] NOT NULL, level_rank INT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT true, created_at)`, unique `(tenant_id, entity_type)`, `CHECK (cardinality(context_words) > 0)`, `CHECK (level_rank BETWEEN 1 AND 4)`, RLS enabled + forced.
5. Grant `SELECT, INSERT, UPDATE, DELETE` on both new tables to `docmgmt_app`. Do **not** touch `access_log` grants (#24).
6. Provide a real `downgrade()` that drops both tables, the policy, and the column.

Mirror the SQL style of `0002_security_hardening.py` exactly.

Add matching SQLAlchemy models to `backend/app/db/models.py` (`DocTypePrototype`, `DetectorRule`) and the `tenant_id` column on `DocType`.

- [ ] **Step 4: Apply and verify**

```bash
docker compose up -d postgres
cd backend && ./.venv/Scripts/python.exe -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://docmgmt:docmgmt@localhost:5433/docmgmt ./.venv/Scripts/python.exe -m pytest -m integration tests/integration/test_migration_0006.py -v
```

Then prove the downgrade works: `alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0006_admin_extensibility.py backend/app/db/models.py backend/tests/integration/test_migration_0006.py
git commit -m "feat(db): 0006 tenant doc types, prototypes, detector rules (#26)

doc_types was outside RLS; its new policy admits tenant_id IS NULL so the
seeded global types stay visible to every tenant. detector_rules makes
validator_kind NOT NULL at the schema level, so a bare regex cannot be
stored at all (#10)."
```

---

## Task 6: Train a doc-type prototype from 5–10 sample documents

**Files:**
- Create: `backend/app/classification/ml/prototypes.py`
- Modify: `backend/app/api/v1/admin.py`
- Test: `backend/tests/classification/test_prototypes.py` (create)

**Interfaces:**
- Produces: `compute_centroid(vectors: Sequence[Sequence[float]]) -> list[float]`; `POST /v1/admin/doc-types/{doc_type_id}/prototype` with body `{document_ids: [...]}`.

**Why:** 5–10 samples cannot calibrate a probability, so retraining would breach invariant #11. A normalised centroid over vectors the embed stage already stored is honest, costs one query, and re-encodes nothing (#6).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/classification/test_prototypes.py
"""Centroid maths, and the guards around it."""

from __future__ import annotations

import math

import pytest

from app.classification.ml.prototypes import MIN_SAMPLES, compute_centroid


def test_centroid_of_identical_vectors_is_that_unit_vector() -> None:
    vectors = [[3.0, 4.0]] * 5
    centroid = compute_centroid(vectors)
    assert math.isclose(centroid[0], 0.6, abs_tol=1e-6)
    assert math.isclose(centroid[1], 0.8, abs_tol=1e-6)


def test_centroid_is_l2_normalised() -> None:
    centroid = compute_centroid([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]] * 3)
    assert math.isclose(sum(c * c for c in centroid), 1.0, abs_tol=1e-6)


def test_fewer_than_min_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        compute_centroid([[1.0, 0.0]] * (MIN_SAMPLES - 1))


def test_all_zero_vectors_are_rejected_not_silently_normalised() -> None:
    """A zero centroid would match everything at cosine 0 — fail loud instead."""
    with pytest.raises(ValueError, match="degenerate"):
        compute_centroid([[0.0, 0.0]] * 5)


def test_mismatched_dimensions_are_rejected() -> None:
    with pytest.raises(ValueError, match="dimension"):
        compute_centroid([[1.0, 0.0]] * 4 + [[1.0, 0.0, 0.0]])
```

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `prototypes.py`**

```python
"""Few-shot doc-type prototypes: a normalised centroid over stored vectors.

This is NOT a calibrated classifier and must never be presented as one (#11).
It is a similarity signal: cosine distance to a centroid of admin-chosen
examples. Below threshold the cascade falls through to ML and then to review,
exactly as an absent artifact does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

MIN_SAMPLES: Final[int] = 5
MAX_SAMPLES: Final[int] = 10


def compute_centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    """L2-normalised mean of ``vectors``; raises on anything unusable."""
    if len(vectors) < MIN_SAMPLES:
        msg = f"need at least {MIN_SAMPLES} sample vectors, got {len(vectors)}"
        raise ValueError(msg)
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        msg = "sample vectors disagree on dimension"
        raise ValueError(msg)
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(c * c for c in mean))
    if norm == 0.0:
        # A zero centroid has cosine 0 to everything: it would match nothing,
        # or — depending on the comparison — everything. Neither is a signal.
        msg = "degenerate centroid: sample vectors cancel to zero"
        raise ValueError(msg)
    return [c / norm for c in mean]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine of two vectors; both are assumed L2-normalised by the caller."""
    return sum(x * y for x, y in zip(a, b, strict=True))
```

- [ ] **Step 4: Add the admin route**

In `admin.py`, following its existing `_fetch_*` / `_insert_*` seam style, add:

- `_fetch_sample_embeddings(session, tenant_id, document_ids) -> list[list[float]]` — selects `DocumentText.embedding` joined to `Document`, filtered to the tenant, non-NULL embeddings only.
- `_upsert_prototype(session, tenant_id, doc_type_id, centroid, sample_count) -> None`.
- `POST /doc-types/{doc_type_id}/prototype`, gated `deps.require(Action.MANAGE_TAXONOMY)`, that: validates 5 ≤ len(document_ids) ≤ 10 (422 otherwise); loads the embeddings; **rejects with 409 if any requested document has no stored embedding** (it has not finished processing — do not silently train on fewer samples); computes the centroid; upserts; writes an audit row `prototype.train` in the same transaction (#30); commits once.

Return `{doc_type_id, sample_count, dimension}`. Never return the centroid itself.

- [ ] **Step 5: Gates and commit**

```bash
git add backend/app/classification/ml/prototypes.py backend/app/api/v1/admin.py backend/tests/classification/test_prototypes.py
git commit -m "feat(classification): train doc-type prototypes from stored embeddings

A normalised centroid over vectors the embed stage already wrote — no
re-encoding (#6) and no calibration claim (#11). Rejects a degenerate
zero centroid and any sample whose embedding is not yet stored."
```

---

## Task 7: Match prototypes in the classification cascade

**Files:**
- Modify: `backend/app/classification/pipeline.py`
- Modify: `backend/app/workers/tasks.py` (`_classify_body`)
- Modify: `backend/app/workers/jobs.py` (prototype loading)
- Test: `backend/tests/classification/test_prototype_cascade.py` (create)

**Interfaces:**
- Consumes: `cosine_similarity`, `MIN_SAMPLES`.
- Produces: `classify(..., prototypes: Sequence[tuple[uuid.UUID, Sequence[float]]] = (), prototype_threshold: float = 0.85)`.

**Why:** `classify()` is pure by contract — no session, no ORM. Prototypes must therefore be **resolved at the task boundary and passed in**, never fetched inside. A prototype hit is `decided_by="rules"`, never `"ml"`, because it carries no calibrated probability (#11).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/classification/test_prototype_cascade.py
"""Prototypes run before the ML head and never claim to be calibrated."""

from __future__ import annotations

import uuid

from app.classification.pipeline import classify
from app.domain.taxonomy import Taxonomy

TYPE_A = uuid.uuid4()
VEC = [1.0, 0.0, 0.0]
NEAR = [0.99, 0.14, 0.0]
FAR = [0.0, 1.0, 0.0]


def test_a_close_prototype_decides_the_type() -> None:
    out = classify(
        "some text",
        Taxonomy.default(),
        None,
        embedding=NEAR,
        prototypes=[(TYPE_A, VEC)],
    )
    assert out.doc_type == TYPE_A
    assert out.needs_review is False


def test_a_prototype_hit_is_never_labelled_ml() -> None:
    """#11: cosine similarity is not a calibrated probability."""
    out = classify(
        "some text", Taxonomy.default(), None, embedding=NEAR, prototypes=[(TYPE_A, VEC)]
    )
    assert out.decided_by == "rules"


def test_a_distant_prototype_falls_through_to_review() -> None:
    out = classify(
        "some text", Taxonomy.default(), None, embedding=FAR, prototypes=[(TYPE_A, VEC)]
    )
    assert out.doc_type is None
    assert out.needs_review is True


def test_no_embedding_means_no_prototype_match() -> None:
    out = classify(
        "some text", Taxonomy.default(), None, embedding=None, prototypes=[(TYPE_A, VEC)]
    )
    assert out.doc_type is None


def test_the_closest_prototype_wins() -> None:
    type_b = uuid.uuid4()
    out = classify(
        "some text",
        Taxonomy.default(),
        None,
        embedding=NEAR,
        prototypes=[(type_b, FAR), (TYPE_A, VEC)],
    )
    assert out.doc_type == TYPE_A
```

- [ ] **Step 2: Run to verify it fails.** Expected: `classify()` has no `prototypes` parameter.

- [ ] **Step 3: Implement**

Add to `classify()`'s signature `prototypes: Sequence[tuple[uuid.UUID, Sequence[float]]] = ()` and `prototype_threshold: float = DEFAULT_PROTOTYPE_THRESHOLD` (define `DEFAULT_PROTOTYPE_THRESHOLD: Final = 0.85` beside `DEFAULT_ML_THRESHOLD`, and read `PROTOTYPE_CONFIDENCE_THRESHOLD` from env at the worker boundary the same way `ml_threshold_from_env` already does).

Insert **between** `aggregate_level(...)` and `predict_type(...)`:

```python
    if embedding is not None and prototypes:
        best_id, best_score = None, 0.0
        for doc_type_id, centroid in prototypes:
            score = cosine_similarity(embedding, centroid)
            if score > best_score:
                best_id, best_score = doc_type_id, score
        if best_id is not None and best_score >= prototype_threshold:
            return ClassificationOutcome(
                # NOT "ml": a cosine similarity is not a calibrated probability
                # and must never be recorded as one (#11).
                decided_by="rules",
                level_rank=level_rank,
                doc_type=best_id,
                confidence=0.0,
                findings=findings,
                needs_review=False,
            )
```

Note `confidence=0.0` — the `confidence` column means calibrated ML probability. Do not put a cosine there.

In `_classify_body` (`tasks.py`), load the tenant's prototypes via a new `jobs.py` helper `load_tenant_prototypes(sessions, tenant_id) -> list[tuple[uuid.UUID, list[float]]]` and pass them into `run_classification`.

- [ ] **Step 4: Gates and commit**

```bash
git add backend/app/classification/pipeline.py backend/app/workers/ backend/tests/classification/test_prototype_cascade.py
git commit -m "feat(classification): match tenant prototypes before the ML head

classify() stays pure — prototypes are resolved at the task boundary and
passed in. A prototype hit is decided_by='rules' with confidence=0.0: a
cosine similarity is not a calibrated probability (#11)."
```

---

## Task 8: A configurable recogniser that satisfies invariant #10

**Files:**
- Create: `backend/app/classification/rules/configured.py`
- Create: `backend/app/classification/rules/validators.py`
- Test: `backend/tests/classification/test_configured_recognizer.py` (create)

**Interfaces:**
- Produces: `VALIDATORS: dict[str, Callable[[str, dict], bool]]`; `ConfiguredRecognizer(entity_type, pattern, context_words, validator_kind, validator_config)` implementing the `Recognizer` ABC.

**Why:** Invariant #10 requires pattern **plus** structural validator **plus** context words. The existing `score_with_context` is already pure and generic — reuse it rather than reimplementing scoring.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/classification/test_configured_recognizer.py
"""#10: pattern + structural validator + context words. Never a bare regex."""

from __future__ import annotations

import pytest

from app.classification.rules.configured import ConfiguredRecognizer
from app.classification.rules.validators import VALIDATORS

KEY = "AKIA" + "J" * 16


def _rec(**over: object) -> ConfiguredRecognizer:
    base = dict(
        entity_type="company_api_key",
        pattern=r"\bAKIA[0-9A-Z]{16}\b",
        context_words=["aws", "secret", "credential"],
        validator_kind="prefix_charset",
        validator_config={"prefix": "AKIA", "length": 20, "charset": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    )
    base.update(over)
    return ConfiguredRecognizer(**base)  # type: ignore[arg-type]


def test_a_validated_match_produces_an_offset_only_finding() -> None:
    text = f"the aws secret is {KEY} rotate it"
    findings = _rec().scan(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.entity_type == "company_api_key"
    assert text[f.char_start : f.char_end] == KEY
    assert not hasattr(f, "text") and not hasattr(f, "value")  # #12


def test_context_words_raise_the_score() -> None:
    near = _rec().scan(f"aws secret credential {KEY}")[0]
    far = _rec().scan(f"unrelated prose {KEY} more prose")[0]
    assert near.score > far.score


def test_a_match_failing_the_validator_is_dropped() -> None:
    assert _rec().scan("AKIAJJJJ toolong not a key") == []


def test_an_unknown_validator_kind_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown validator"):
        _rec(validator_kind="handwave")


def test_empty_context_words_are_rejected_at_construction() -> None:
    """#10 is not satisfiable without context words."""
    with pytest.raises(ValueError, match="context words"):
        _rec(context_words=[])


@pytest.mark.parametrize("kind", ["luhn", "mod97", "entropy", "prefix_charset"])
def test_every_advertised_validator_exists(kind: str) -> None:
    assert kind in VALIDATORS


def test_entropy_validator_separates_random_from_english() -> None:
    high = VALIDATORS["entropy"]("f3Kq9zXm2WpL7vB4nR8t", {"min_bits_per_char": 3.0})
    low = VALIDATORS["entropy"]("aaaaaaaaaaaaaaaaaaaa", {"min_bits_per_char": 3.0})
    assert high is True
    assert low is False
```

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the validators**

`validators.py` exposes `VALIDATORS: dict[str, Callable[[str, dict[str, Any]], bool]]` with:
- `luhn` — reuse the existing implementation from `recognizers.py`; do not duplicate the algorithm, import it.
- `mod97` — IBAN-style checksum.
- `entropy` — Shannon entropy per character over the match; config `{"min_bits_per_char": float}`.
- `prefix_charset` — config `{"prefix": str, "length": int, "charset": str}`.
- `checksum_suffix` — config `{"algorithm": "sha256", "length": int}` for company-specific schemes.

Each returns `bool` and must not raise on odd input.

- [ ] **Step 4: Implement `ConfiguredRecognizer`**

It subclasses `Recognizer`. Because the ABC declares `entity_type`/`pattern`/`context_words` as **ClassVars** but these are per-instance here, set them as instance attributes in `__init__` and confirm `mypy` is satisfied — if the ClassVar declaration blocks that, widen the ABC's annotations rather than duplicating the class.

`__init__` validates: non-empty `context_words`, known `validator_kind`, and a compilable pattern. `scan()` iterates `self.pattern.finditer(text)`, calls `validate()` per match, and builds findings via the existing `build_finding()` helper with `score_with_context(text, span, self.context_words)`.

- [ ] **Step 5: Gates and commit**

```bash
git add backend/app/classification/rules/configured.py backend/app/classification/rules/validators.py backend/tests/classification/test_configured_recognizer.py
git commit -m "feat(classification): configurable recogniser with required validator (#10)

Reuses the existing score_with_context window and build_finding offset
guard. A recogniser cannot be constructed without a known structural
validator and at least one context word."
```

---

## Task 9: Per-tenant taxonomy, from one source of truth

**Files:**
- Modify: `backend/app/domain/taxonomy.py`
- Modify: `backend/app/classification/rules/registry.py`
- Modify: `backend/app/api/v1/documents.py` (`_contributed_level`)
- Modify: `backend/app/workers/tasks.py` (`_classify_body`)
- Test: `backend/tests/domain/test_tenant_taxonomy.py` (create)

**Why:** **This is the hard blocker.** `Taxonomy.rank_for()` raises `ValueError` on an unknown `entity_type`, so the first custom detector to match would crash `aggregate_level` and fail the document. `Taxonomy` already accepts an `entity_rank` Mapping, so per-tenant construction is a small change — but the entity→level table is currently duplicated in `documents.py:_contributed_level`, and a custom type would silently render as "Internal" there. Both must read from one source.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/domain/test_tenant_taxonomy.py
"""A custom detector must not crash level aggregation."""

from __future__ import annotations

import pytest

from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy


def _finding(entity_type: str) -> Finding:
    return Finding(entity_type=entity_type, rule_id="r", page_no=1, char_start=0, char_end=4, score=0.9)


def test_custom_entity_type_aggregates_instead_of_raising() -> None:
    tax = Taxonomy.for_tenant({"company_api_key": 4})
    assert aggregate_level([_finding("company_api_key")], tax) == 4


def test_builtin_entity_types_are_still_present_for_a_tenant() -> None:
    tax = Taxonomy.for_tenant({"company_api_key": 4})
    assert aggregate_level([_finding("cnic")], tax) == 3


def test_a_tenant_rule_cannot_lower_a_builtin_rank() -> None:
    """Custom rules extend the table; they must not weaken the spec ranks."""
    tax = Taxonomy.for_tenant({"card_number": 1})
    assert aggregate_level([_finding("card_number")], tax) == 4


def test_a_genuinely_unknown_type_still_fails_loud() -> None:
    tax = Taxonomy.for_tenant({})
    with pytest.raises(ValueError, match="unknown entity_type"):
        tax.rank_for(_finding("never_registered"))
```

- [ ] **Step 2: Run to verify it fails.** Expected: `Taxonomy` has no `for_tenant`.

- [ ] **Step 3: Implement**

```python
    @classmethod
    def for_tenant(cls, custom_ranks: Mapping[str, int]) -> Taxonomy:
        """Spec ranks extended with a tenant's custom detector ranks.

        Custom entries EXTEND the table; they never lower a spec rank. Without
        this, the first custom detector to match raises out of rank_for and
        fails the whole document (#4 would journal it, but the finding is lost).
        """
        merged = dict(_SPEC_ENTITY_RANKS)
        for entity_type, rank in custom_ranks.items():
            merged[entity_type] = max(rank, merged.get(entity_type, 0))
        return cls(entity_rank=merged)
```

Add `build_recognizers_for_tenant(custom_rules) -> dict[str, Recognizer]` and `iter_recognizers_for_tenant(custom_rules)` to `registry.py`, returning the builtin four plus a `ConfiguredRecognizer` per enabled rule. Keep the existing no-arg functions working (delegate with an empty rule list) so nothing else breaks.

Replace `documents.py:_contributed_level`'s hardcoded `if` chain with a lookup against the same rank table, mapping rank → level name, so a custom entity type reports its real contributed level instead of "Internal".

In `_classify_body`, build the taxonomy from the tenant's detector rows instead of `Taxonomy.default()`.

- [ ] **Step 4: Gates and commit**

```bash
git add backend/app/domain/taxonomy.py backend/app/classification/rules/registry.py backend/app/api/v1/documents.py backend/app/workers/tasks.py backend/tests/domain/test_tenant_taxonomy.py
git commit -m "feat(classification): per-tenant taxonomy for custom detectors

rank_for() raised on unknown entity types, so the first custom detector
match would have crashed aggregation. Custom ranks now extend the spec
table without being able to lower a builtin rank, and the API's duplicate
entity-to-level table reads from the same source."
```

---

## Task 10: Detector rules admin API with a ReDoS guard

**Files:**
- Modify: `backend/app/api/v1/admin.py`
- Create: `backend/app/classification/rules/safety.py`
- Test: `backend/tests/api/test_detector_admin.py` (create)

**Interfaces:**
- Produces: `GET|POST /v1/admin/detectors`, `PATCH|DELETE /v1/admin/detectors/{id}`, `POST /v1/admin/detectors/preview`.
- Produces: `assert_pattern_safe(pattern: str) -> None`.

**Why:** Admin-supplied regexes run in the worker over full document text, and Python's `re` has no timeout. A catastrophically backtracking pattern would hang a worker indefinitely.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_detector_admin.py
"""Admin detector CRUD, gated and ReDoS-guarded."""

from __future__ import annotations

from typing import Any

import pytest

from app.classification.rules.safety import PatternUnsafeError, assert_pattern_safe

GOOD = {
    "entity_type": "company_api_key",
    "pattern": r"\bAKIA[0-9A-Z]{16}\b",
    "context_words": ["aws", "secret"],
    "validator_kind": "prefix_charset",
    "validator_config": {"prefix": "AKIA", "length": 20, "charset": "A-Z0-9"},
    "level_rank": 4,
}


@pytest.mark.parametrize(
    "evil",
    [r"(a+)+$", r"(a|a)*$", r"(.*a){20}", r"([a-zA-Z]+)*$"],
    ids=["nested_plus", "alt_overlap", "repeated_group", "nested_star"],
)
def test_catastrophic_patterns_are_refused(evil: str) -> None:
    with pytest.raises(PatternUnsafeError):
        assert_pattern_safe(evil)


@pytest.mark.parametrize("safe", [r"\bAKIA[0-9A-Z]{16}\b", r"\d{5}-\d{7}-\d", r"sk_live_[a-z0-9]{24}"])
def test_reasonable_patterns_are_allowed(safe: str) -> None:
    assert_pattern_safe(safe)


def test_create_requires_manage_taxonomy(client_factory: Any) -> None:
    viewer = client_factory(role="viewer")
    assert viewer.post("/v1/admin/detectors", json=GOOD).status_code == 403


def test_create_rejects_a_rule_without_a_validator(client_factory: Any) -> None:
    """#10 at the API boundary, not only in the schema."""
    admin = client_factory(role="admin")
    bad = {**GOOD}
    del bad["validator_kind"]
    assert admin.post("/v1/admin/detectors", json=bad).status_code == 422


def test_create_rejects_empty_context_words(client_factory: Any) -> None:
    admin = client_factory(role="admin")
    assert admin.post("/v1/admin/detectors", json={**GOOD, "context_words": []}).status_code == 422


def test_create_rejects_an_unsafe_pattern(client_factory: Any) -> None:
    admin = client_factory(role="admin")
    response = admin.post("/v1/admin/detectors", json={**GOOD, "pattern": r"(a+)+$"})
    assert response.status_code == 422
    assert "pattern" in response.json()["detail"].lower()


def test_preview_returns_offsets_never_matched_text(client_factory: Any) -> None:
    """#12 holds even in an admin preview."""
    admin = client_factory(role="admin")
    body = admin.post(
        "/v1/admin/detectors/preview",
        json={**GOOD, "sample_text": "aws secret AKIA" + "J" * 16},
    ).json()
    assert body["matches"][0]["char_start"] >= 0
    serialised = str(body)
    assert "AKIAJ" not in serialised
```

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError` on `safety`.

- [ ] **Step 3: Implement the guard**

`safety.py` defines `PatternUnsafeError(ValueError)` and `assert_pattern_safe(pattern)`. It must:
1. Compile the pattern (a compile error is unsafe).
2. Reject structural red flags by AST/text inspection: a quantifier applied to a group that itself contains an unbounded quantifier (`(a+)+`, `(a*)*`, `([a-z]+)*`), alternations with overlapping branches under a quantifier, and nesting depth over a small bound.
3. Cap pattern length (e.g. 512 chars) and total quantifier count.
4. Run a timing canary: match against a pathological input (`"a" * 40 + "!"`) under a wall-clock budget (e.g. 100 ms) and reject if exceeded.

Also enforce a per-document time budget at scan time in `ConfiguredRecognizer.scan`, failing the stage loudly rather than hanging it. Note in the code comment that Python's `re` cannot be interrupted mid-match, so the canary is a filter, not a guarantee.

- [ ] **Step 4: Implement the routes**

Following `admin.py`'s existing seam style, all gated `deps.require(Action.MANAGE_TAXONOMY)`, each mutation writing an audit row (`detector.create` / `detector.update` / `detector.delete`) in the same transaction (#30). The preview route compiles the rule in memory, scans the supplied sample, and returns **offsets and scores only** — never the matched substrings (#12).

- [ ] **Step 5: Gates and commit**

```bash
git add backend/app/api/v1/admin.py backend/app/classification/rules/safety.py backend/tests/api/test_detector_admin.py
git commit -m "feat(admin): detector rule CRUD with a ReDoS guard

Admin patterns run in the worker over full document text and Python's re
cannot be interrupted mid-match, so unsafe constructs are refused at save
time and scanning runs under a per-document budget. Preview returns
offsets only (#12)."
```

---

## Task 11: Admin UI for classifiers and detectors

**Files:**
- Modify: `frontend/src/features/admin/TaxonomyPage.tsx`
- Create: `frontend/src/features/admin/PrototypeTrainer.tsx`, `frontend/src/features/admin/DetectorRules.tsx`
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`
- Test: `frontend/src/features/admin/DetectorRules.test.tsx` (create)

**Why:** The admin page currently offers only doc-type list/create/delete, and its create form does not even expose `parent_id`. Both new features need a surface.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/admin/DetectorRules.test.tsx
describe('DetectorRules — invariant #10 in the form', () => {
  it('disables save until a validator is chosen', async () => {
    render(<DetectorRules />, { wrapper });
    await fillPattern('\\bAKIA[0-9A-Z]{16}\\b');
    await fillContextWords('aws, secret');
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
    await chooseValidator('prefix_charset');
    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
  });

  it('disables save with no context words', async () => {
    render(<DetectorRules />, { wrapper });
    await fillPattern('\\bAKIA[0-9A-Z]{16}\\b');
    await chooseValidator('prefix_charset');
    await fillContextWords('');
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });

  it('shows preview matches as offsets, never the matched text', async () => {
    mockPreview({ matches: [{ char_start: 11, char_end: 31, score: 0.9 }] });
    render(<DetectorRules />, { wrapper });
    await runPreview('aws secret AKIAJJJJJJJJJJJJJJJJ');
    expect(await screen.findByText(/11–31/)).toBeInTheDocument();
    expect(screen.queryByText(/AKIAJ/)).not.toBeInTheDocument();
  });

  it('surfaces a server pattern rejection', async () => {
    mockCreateRejects(422, 'pattern is not safe to run');
    render(<DetectorRules />, { wrapper });
    await fillValidRuleAndSave();
    expect(await screen.findByText(/not safe to run/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

`PrototypeTrainer.tsx`: pick a doc type, then select 5–10 **ready** documents (the picker must exclude non-ready ones — their embeddings do not exist yet), submit, and show `sample_count` and dimension on success. Surface the 409 for a document with no embedding as a clear message.

`DetectorRules.tsx`: a guided builder — pattern, context words (chips), validator kind (select, **required**), validator config fields that change with the chosen kind, target level, and enabled toggle. Save stays disabled until invariant #10's three parts are all present. A "Preview" action posts sample text and renders offset ranges and scores only.

Add both as tabs on `TaxonomyPage.tsx`, gated with `<Can action={Action.MANAGE_TAXONOMY}>` — cosmetic only (#33); the server is the enforcement.

- [ ] **Step 3: Gates and commit**

```bash
cd frontend && npm run typecheck && npm run test && npm run build
git add frontend/src/
git commit -m "feat(admin): prototype trainer and detector rule builder

The detector form cannot save without a pattern, context words, AND a
structural validator (#10). Preview renders offsets only (#12). Document
picker excludes non-ready documents, whose embeddings do not exist yet."
```

---

## Task 12: End-to-end verification and documentation

**Files:** `README.md`, `PROGRESS.md`, `AGENTS.md`, `backend/README.md`, `ml/ML_IMPLEMENTATION_PLAN.md`

- [ ] **Step 1: Run every gate and record verbatim output**

```bash
cd backend
./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m ruff format --check .
./.venv/Scripts/python.exe -m mypy app
./.venv/Scripts/python.exe -m pytest -q
docker compose up -d
DATABASE_URL=postgresql+psycopg://docmgmt:docmgmt@localhost:5433/docmgmt ./.venv/Scripts/python.exe -m pytest -m integration -q
cd ../frontend && npm run typecheck && npm run test && npm run build
```

Do not claim a gate passed that you did not run.

- [ ] **Step 2: Verify against the rebuilt live stack**

```bash
docker compose build api worker worker-ocr && docker compose up -d
```

The image must be rebuilt or none of this is live. Then walk it manually:
1. Sort by each column, page past the boundary, confirm no duplicate or missing rows — especially with unclassified documents present.
2. Bulk upload 5 files including one deliberately corrupt; confirm partial success and per-file status.
3. Train a prototype from 5 ready documents; upload a sixth of that kind; confirm it receives the type with `decided_by='rules'`.
4. Add a detector for a fake company API key; upload a document containing one; confirm the level escalates and findings carry offsets only.
5. Confirm a viewer role sees neither admin tab and gets 403 from both new endpoints directly.

- [ ] **Step 3: Update documentation**

- `README.md`: add the new endpoints; extend the invariant matrix rows for #10, #11, #26 and #32 to name the new enforcement points; add a deviations entry stating plainly that **prototype similarity is not a calibrated probability** and is recorded as `decided_by='rules'` with `confidence=0.0`.
- `PROGRESS.md`: add a Wave 9 row, the verbatim gate output from Step 1, and move the completed items out of the Phase-2 backlog.
- `AGENTS.md`: add the new modules to the repository layout.
- `ml/ML_IMPLEMENTATION_PLAN.md`: mark section 5 implemented and correct its stale migration number (it claims 0005; the real one is 0006).

- [ ] **Step 4: Commit**

```bash
git add README.md PROGRESS.md AGENTS.md backend/README.md ml/ML_IMPLEMENTATION_PLAN.md
git commit -m "docs: record Phase 2 features and their invariant enforcement points"
```

---

## Verification checklist for the reviewer

Whoever verifies this plan's execution should confirm, independently of any summary:

1. `git log` shows a commit per task, and `git status` is clean of plan-relevant files. **Run the gates with the working tree stashed** — Phase 1 shipped a branch whose committed state failed 6 tests while the working tree passed.
2. `alembic downgrade -1 && alembic upgrade head` round-trips 0006 cleanly.
3. Seeded **global** doc types are still visible to a tenant after 0006 (the RLS trap).
4. Paging every sort column in both directions returns each row exactly once **with unclassified rows in the set**.
5. No prototype decision is recorded with `decided_by='ml'` or a non-zero `confidence`.
6. `POST /v1/admin/detectors` refuses `(a+)+$`.
7. Detector preview and stored findings contain offsets only — grep the responses for the matched substring.
8. A viewer role gets 403 from every new admin route.
