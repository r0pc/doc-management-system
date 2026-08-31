# DMS Phase 0 + Phase 1 Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deployed stack work end to end — upload, process, view, download — with every failure visible in SQL and in the UI.

**Architecture:** Fix the deployment wiring first (nothing is verifiable while the running image disagrees with source), then repair the ingestion pipeline's failure handling, then the upload integrity checks, then the UI's ability to show what happened. Each defect gets a regression test that fails before the fix.

**Tech Stack:** FastAPI, Celery/Redis, PostgreSQL 16 + pgvector, SQLAlchemy 2 (async API / sync worker), Pydantic v2, React 18 + TypeScript strict, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-dms-repair-and-admin-extensibility-design.md`

## Global Constraints

- **Python >= 3.12** (`pyproject.toml`). PEP 758 bare `except A, B:` parses on the 3.14 dev host but SyntaxErrors on the 3.12 container base image — always parenthesise multi-type excepts.
- **TypeScript strict, no `any`.** Server state via TanStack Query, never `useEffect` fetches. Filter state in URL params.
- **Never log document text, extracted content, or matched identifier values.** Logs are structured JSON carrying ids, not contents (AGENTS.md safety rails).
- **Never weaken or skip a test to make a build pass.** Report the failure.
- **Invariant #1**: the API does not read or write object bytes on the write path. Completion may check metadata (existence, length) but must not read the body.
- **Invariant #4**: every stage writes its state transition to `processing_jobs` before and after running. Pipeline state must be answerable from SQL.
- **Invariant #31**: a 404 for another tenant's document is byte-identical and timing-identical to one for a nonexistent document. Error bodies never contain filenames.
- **Invariant #32**: cursor pagination only. No `OFFSET`.
- **Conventional commits**: `feat|fix|refactor|test|docs|chore(scope): summary`.
- **Backend test command**: `.venv/Scripts/python.exe -m pytest` from `backend/`.
- **Frontend test command**: `npm run test` from `frontend/`.
- **Do not add dependencies** beyond those named in this plan without justifying them in the summary.

---

## Task 1: Pin the storage root so a rebuild does not break storage

**Files:**
- Modify: `docker-compose.yml` (the `api`, `worker`, `worker-ocr` `environment:` blocks)
- Modify: `backend/app/main.py` (startup validation)
- Test: `backend/tests/test_storage_root_wiring.py` (create)

**Interfaces:**
- Consumes: `app.config.resolve_storage_root()` (already exists, returns `Path`), env var `DOCMGMT_LOCAL_STORAGE_ROOT` (already honoured by `tasks.py:171`; **not** yet honoured by `deps.py:59`).
- Produces: `app.config.resolve_storage_root()` becomes authoritative for both API and worker; `assert_storage_root_usable(settings) -> None` in `app/main.py`.

**Why:** `resolve_storage_root()` returns `_REPO_ROOT / "var" / "storage"`. In the container the package is at `/srv/app/app/`, so `_BACKEND_DIR=/srv/app` and `_REPO_ROOT=/srv`, giving `/srv/var/storage`. Compose mounts the shared volume at `/srv/app/var/storage`. Verified: `/srv/var/storage` does not exist. The running image predates this code, which is the only reason storage works today.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_storage_root_wiring.py
"""The compose mount and the resolved storage root must be the same path.

A mismatch is invisible until runtime: the worker writes the primary blob into
its own container layer and the API 404s every download.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_SERVICES = ("api", "worker", "worker-ocr")
_ENV_VAR = "DOCMGMT_LOCAL_STORAGE_ROOT"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_storage_volume_mount_matches_pinned_root() -> None:
    services = _compose()["services"]
    for name in _SERVICES:
        service = services[name]
        mounts = [v for v in service["volumes"] if v.startswith("storage-data:")]
        assert len(mounts) == 1, f"{name} must mount storage-data exactly once"
        mount_path = mounts[0].split(":", 1)[1]
        pinned = service["environment"][_ENV_VAR]
        assert pinned == mount_path, (
            f"{name}: {_ENV_VAR}={pinned!r} does not match volume mount {mount_path!r}"
        )


def test_every_storage_service_pins_the_root_explicitly() -> None:
    services = _compose()["services"]
    for name in _SERVICES:
        assert _ENV_VAR in services[name]["environment"], (
            f"{name} must pin {_ENV_VAR}; relying on resolve_storage_root() "
            "inside the container resolves to /srv/var/storage, not the volume"
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_storage_root_wiring.py -v`
Expected: FAIL — `KeyError: 'DOCMGMT_LOCAL_STORAGE_ROOT'`.

If `yaml` is missing, install it as a dev dependency (`pyyaml`) and note it in the summary.

- [ ] **Step 3: Pin the root in compose**

Add this line to the `environment:` block of **each** of `api`, `worker`, and `worker-ocr` in `docker-compose.yml`, next to `STORAGE_BACKEND: local`:

```yaml
      # Pinned, not derived. resolve_storage_root() anchors on the package
      # location, which inside the image is /srv/app/app -> /srv/var/storage,
      # while the shared volume is mounted at /srv/app/var/storage. Deriving it
      # silently splits the API's and worker's view of storage.
      DOCMGMT_LOCAL_STORAGE_ROOT: /srv/app/var/storage
```

- [ ] **Step 4: Make `deps.py` honour the same env var as the worker**

`app/workers/tasks.py:171` already reads `DOCMGMT_LOCAL_STORAGE_ROOT`, but `app/api/deps.py:59` does not — so API and worker can diverge. In `backend/app/api/deps.py`, replace:

```python
# Dev-only local-storage root anchored on repository root.
DEFAULT_LOCAL_STORAGE_ROOT: Final = resolve_storage_root()
```

with:

```python
# Dev-only local-storage root. Honours the same override the worker reads
# (tasks.py:_LOCAL_ROOT_ENV) so API and worker can never resolve different
# roots — a split root 404s every download with no error anywhere.
LOCAL_ROOT_ENV: Final = "DOCMGMT_LOCAL_STORAGE_ROOT"
DEFAULT_LOCAL_STORAGE_ROOT: Final = Path(
    os.environ.get(LOCAL_ROOT_ENV, str(resolve_storage_root()))
)
```

Add `import os` and `from pathlib import Path` to the imports if absent. Then in `app/workers/tasks.py`, replace the literal `_LOCAL_ROOT_ENV = "DOCMGMT_LOCAL_STORAGE_ROOT"` with an import of the shared constant so there is exactly one spelling:

```python
from app.api.deps import LOCAL_ROOT_ENV as _LOCAL_ROOT_ENV
```

If that import would create a cycle, instead move the constant to `app/config.py` and import it in both places.

- [ ] **Step 5: Add a fail-loud startup assertion**

In `backend/app/main.py`, inside the existing startup path (alongside `validate_runtime`), add:

```python
def assert_storage_root_usable(settings: Settings) -> None:
    """Refuse to start on an unusable local storage root.

    A missing or read-only root does not fail at startup on its own — it fails
    as a 404 on every download and a FileNotFoundError in every worker, hours
    later and far from the cause.
    """
    if settings.storage_backend != "local":
        return
    root = deps.DEFAULT_LOCAL_STORAGE_ROOT
    if not root.is_dir():
        msg = (
            f"local storage root {root} does not exist; set "
            f"{deps.LOCAL_ROOT_ENV} to the mounted volume path"
        )
        raise RuntimeError(msg)
    probe = root / ".write-probe"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        msg = f"local storage root {root} is not writable: {exc}"
        raise RuntimeError(msg) from exc
```

Call it from startup immediately after `validate_runtime`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_storage_root_wiring.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Run the full backend suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: previous baseline (609 passed, 3 skipped) plus 2 new passes, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml backend/app/api/deps.py backend/app/workers/tasks.py backend/app/main.py backend/tests/test_storage_root_wiring.py
git commit -m "fix(storage): pin local storage root to the mounted volume

resolve_storage_root() anchors on the package location, which resolves to
/srv/var/storage inside the image while the shared volume is mounted at
/srv/app/var/storage. Pin the root explicitly in compose for api/worker/
worker-ocr, honour the same override in deps.py that tasks.py already read,
and refuse startup on a missing or read-only root."
```

---

## Task 2: Prove the deployed route table matches source

**Files:**
- Test: `backend/tests/test_route_parity.py` (create)

**Interfaces:**
- Consumes: `app.main.app` (FastAPI instance).
- Produces: nothing consumed by later tasks; this is a standalone guard.

**Why:** `/v1/documents/{id}/view` and `/preview` exist in the working tree (`documents.py:697`, `:763`) but are absent from the running API, because compose builds from `./backend` with no bind-mount and no `--reload`. This test pins the routes the frontend depends on so their absence is a red test rather than a browser 404.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_route_parity.py
"""Pin the routes the frontend calls.

A stale image silently drops new routes; the browser sees an opaque 404 that
looks identical to a permission denial. This test makes that a red test.
"""

from __future__ import annotations

import pytest

from app.main import app

REQUIRED_ROUTES = [
    ("GET", "/v1/documents"),
    ("GET", "/v1/documents/{document_id}"),
    ("GET", "/v1/documents/{document_id}/content"),
    ("GET", "/v1/documents/{document_id}/view"),
    ("GET", "/v1/documents/{document_id}/preview"),
    ("GET", "/v1/documents/{document_id}/findings"),
    ("GET", "/v1/documents/{document_id}/jobs"),
    ("POST", "/v1/documents/{document_id}/classification"),
    ("POST", "/v1/uploads"),
    ("POST", "/v1/uploads/{upload_id}/complete"),
]


def _registered() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None:
            continue
        for method in methods:
            found.add((method, path))
    return found


@pytest.mark.parametrize(("method", "path"), REQUIRED_ROUTES)
def test_route_is_registered(method: str, path: str) -> None:
    assert (method, path) in _registered(), (
        f"{method} {path} is not registered. The frontend calls it; if this "
        "fails the deployed image is stale or the route was renamed."
    )
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_route_parity.py -v`
Expected: PASS against the working tree (the routes exist in source). It is the *deployed image* that lacks them — Step 3 closes that gap.

- [ ] **Step 3: Rebuild the stack and verify against the live API**

```bash
docker compose build api worker worker-ocr
docker compose up -d
```

Then confirm the routes are live:

```bash
curl -s http://localhost:8000/openapi.json | python -c "import json,sys; p=json.load(sys.stdin)['paths']; [print(k) for k in sorted(p) if 'documents' in k]"
```

Expected: the list now includes `/v1/documents/{document_id}/view` and `/v1/documents/{document_id}/preview`.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_route_parity.py
git commit -m "test(api): pin the route table the frontend depends on

A stale image drops new routes and the browser sees an opaque 404
indistinguishable from a permission denial."
```

---

## Task 3: Make the stage failure taxonomy exhaustive

**Files:**
- Modify: `backend/app/workers/tasks.py:446-495` (the `except` ladder in `_run_stage`)
- Test: `backend/tests/workers/test_stage_failure_taxonomy.py` (create)

**Interfaces:**
- Consumes: `journal.mark_failed(job_row_id, error)`, `mark_document_failed(sessions, document_id=...)` (both exist).
- Produces: `_run_stage` guarantees that every exit path writes a terminal `processing_jobs` state.

**Why:** The ladder handles 11 exception types. Anything else propagates out before `mark_succeeded`/`mark_failed`, pinning the job at `running` and the document at `processing` forever. `FileNotFoundError`, `NoResultFound`, `json.JSONDecodeError`, `SoftTimeLimitExceeded`, `pymupdf.FileDataError`, `zipfile.BadZipFile` and `openpyxl`'s `KeyError` are all reachable. Two production rows are in this state now. This violates invariant #4.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workers/test_stage_failure_taxonomy.py
"""#4: no exception may escape _run_stage without a terminal journal write."""

from __future__ import annotations

import json
import uuid
import zipfile

import pytest
from sqlalchemy.exc import NoResultFound

from app.workers import tasks


class _RecordingJournal:
    def __init__(self) -> None:
        self.job_id = uuid.uuid4()
        self.terminal: tuple[str, str] | None = None

    def mark_running(self, document_id, version_id, stage):  # noqa: ANN001, ARG002
        return self.job_id

    def mark_succeeded(self, job_row_id):  # noqa: ANN001, ARG002
        self.terminal = ("succeeded", "")

    def mark_failed(self, job_row_id, error):  # noqa: ANN001, ARG002
        self.terminal = ("failed", error)

    def mark_skipped(self, job_row_id, reason):  # noqa: ANN001, ARG002
        self.terminal = ("skipped", reason)


@pytest.fixture
def ctx() -> dict[str, str]:
    return {
        "document_id": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "key": "docs-quarantine/t/d",
    }


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> _RecordingJournal:
    recorder = _RecordingJournal()
    monkeypatch.setattr(tasks, "_journal", lambda: recorder)
    monkeypatch.setattr(tasks, "_already_succeeded", lambda *a, **k: False)
    monkeypatch.setattr(tasks, "_sessions", lambda: None)
    return recorder


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError(2, "No such file or directory"),
        NoResultFound("no row"),
        json.JSONDecodeError("bad", "", 0),
        zipfile.BadZipFile("not a zip"),
        KeyError("xl/workbook.xml"),
        OSError("disk gone"),
    ],
    ids=["file_not_found", "no_result", "bad_json", "bad_zip", "key_error", "os_error"],
)
def test_unlisted_exception_still_writes_a_terminal_state(
    exc: Exception,
    ctx: dict[str, str],
    journal: _RecordingJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marked: list[uuid.UUID] = []
    monkeypatch.setattr(
        tasks, "mark_document_failed", lambda _s, *, document_id: marked.append(document_id)
    )

    def body() -> None:
        raise exc

    with pytest.raises(type(exc)):
        tasks._run_stage("extract", ctx, body)

    assert journal.terminal is not None, (
        f"{type(exc).__name__} escaped _run_stage with the job still 'running' "
        "— the document is stranded at status='processing' forever (#4)"
    )
    assert journal.terminal[0] == "failed"
    assert marked == [uuid.UUID(ctx["document_id"])]


def test_failure_reason_never_contains_document_text(
    ctx: dict[str, str],
    journal: _RecordingJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "mark_document_failed", lambda _s, *, document_id: None)
    secret = "CNIC 61101-1234567-8 of Ayesha Khan"

    def body() -> None:
        raise RuntimeError(secret)

    with pytest.raises(RuntimeError):
        tasks._run_stage("extract", ctx, body)

    assert journal.terminal is not None
    assert secret not in journal.terminal[1], "exception text leaked into the journal"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_stage_failure_taxonomy.py -v`
Expected: the six parametrised cases FAIL with `AssertionError: ... escaped _run_stage`. `test_failure_reason_never_contains_document_text` passes already (the `RuntimeError` branch uses a fixed string) — keep it as a guard on the new catch-all.

- [ ] **Step 3: Add the terminal catch-all**

In `backend/app/workers/tasks.py`, immediately **after** the existing `except RuntimeError:` block and **before** `journal.mark_succeeded(job_row_id)`, insert:

```python
    except Exception as unexpected:
        # #4 backstop. The ladder above names every failure we can classify;
        # anything else still has to leave the pipeline answerable from SQL.
        # Without this, an unlisted exception unwinds past the journal and pins
        # the job at 'running' and the document at 'processing' forever.
        #
        # The reason is the exception TYPE only. Exception payloads routinely
        # carry document content (parser errors quote the offending bytes), and
        # the journal is read back into the UI — safety rail: never log or
        # persist document text.
        journal.mark_failed(job_row_id, f"unexpected {type(unexpected).__name__} in {stage}")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        logger.exception("stage_unexpected_failure", extra=_ids(stage, ctx))
        raise
```

Note the ordering constraint: this must come last, because `except Exception` would otherwise shadow every named handler above it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_stage_failure_taxonomy.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the worker suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/workers -q`
Expected: all pass. Pay attention to any test asserting that a specific exception propagates uncaught — it should still propagate (the catch-all re-raises).

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/tasks.py backend/tests/workers/test_stage_failure_taxonomy.py
git commit -m "fix(workers): make the stage failure taxonomy exhaustive (#4)

The except ladder named 11 types; FileNotFoundError, NoResultFound,
BadZipFile, JSONDecodeError, SoftTimeLimitExceeded and parser KeyErrors all
escaped before a terminal journal write, pinning the job at 'running' and the
document at 'processing' forever. Add a terminal catch-all that journals the
exception TYPE (never its payload, which can carry document text) and flips
the document to 'failed'."
```

---

## Task 4: Populate the stage timestamps that already exist

**Files:**
- Modify: `backend/app/workers/jobs.py:138-193` (`mark_running`, `mark_succeeded`, `mark_failed`, `mark_skipped`)
- Test: `backend/tests/workers/test_journal_timestamps.py` (create)

**Interfaces:**
- Consumes: `ProcessingJob.started_at`, `ProcessingJob.finished_at` (columns exist at `db/models.py:186-187`).
- Produces: journal writes populate both columns; the API already selects and serialises them (`documents.py:465-466`).

**Why:** The columns exist and are exposed by the API but no journal method writes them, so they are permanently `NULL`. Without them a hung stage is undetectable and the drawer's `finished_at ? ... : state` fallback is dead code.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workers/test_journal_timestamps.py
"""started_at/finished_at must be written; a hung stage is otherwise invisible."""

from __future__ import annotations

import uuid

import pytest

from app.workers.jobs import ProcessingJobsJournal


@pytest.fixture
def journal(sync_sessions) -> ProcessingJobsJournal:  # noqa: ANN001
    return ProcessingJobsJournal(sync_sessions)


def _job(sync_sessions, job_id: uuid.UUID):  # noqa: ANN001, ANN202
    from app.db.models import ProcessingJob

    with sync_sessions() as session:
        return session.get(ProcessingJob, job_id)


def test_mark_running_sets_started_at(sync_sessions, journal, seeded_version) -> None:  # noqa: ANN001
    job_id = journal.mark_running(seeded_version.document_id, seeded_version.id, "extract")
    row = _job(sync_sessions, job_id)
    assert row.started_at is not None
    assert row.finished_at is None


@pytest.mark.parametrize(
    ("method", "args"),
    [("mark_succeeded", ()), ("mark_failed", ("boom",)), ("mark_skipped", ("needs_ocr",))],
)
def test_terminal_writes_set_finished_at(
    sync_sessions, journal, seeded_version, method: str, args: tuple
) -> None:  # noqa: ANN001
    job_id = journal.mark_running(seeded_version.document_id, seeded_version.id, "extract")
    getattr(journal, method)(job_id, *args)
    row = _job(sync_sessions, job_id)
    assert row.finished_at is not None
    assert row.started_at is not None
    assert row.finished_at >= row.started_at
```

This test needs live Postgres. Place it under `tests/integration/` and mark it `@pytest.mark.integration` if the `sync_sessions` / `seeded_version` fixtures are only available there. Check `backend/tests/integration/conftest.py` for the existing fixture names and reuse them rather than inventing new ones; if the hermetic `tests/workers/` package already has a sqlite or fake-session harness, prefer that and drop the marker.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_journal_timestamps.py -v` (add `-m integration` if you placed it there)
Expected: FAIL — `assert None is not None`.

- [ ] **Step 3: Write the timestamps**

In `backend/app/workers/jobs.py`, add `from datetime import UTC, datetime` to the imports, then:

In `mark_running`'s `op`, the insert branch becomes:

```python
                row = ProcessingJob(
                    document_id=uuid.UUID(str(document_id)),
                    version_id=vid,
                    stage=stage,
                    state="running",
                    attempts=1,
                    started_at=datetime.now(UTC),
                )
```

and the update branch becomes:

```python
            session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(
                    state="running",
                    attempts=ProcessingJob.attempts + 1,
                    started_at=datetime.now(UTC),
                    finished_at=None,
                )
            )
```

Clearing `finished_at` on re-entry matters: a retried stage that kept a stale `finished_at` would read as complete.

Then add `finished_at=datetime.now(UTC)` to the `.values(...)` of `mark_succeeded`, `mark_failed`, and `mark_skipped`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_journal_timestamps.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/jobs.py backend/tests/workers/test_journal_timestamps.py
git commit -m "fix(workers): populate processing_jobs started_at/finished_at

The columns existed and were serialised by the API but no journal method ever
wrote them, so they were permanently NULL — a hung stage was undetectable and
the drawer's timestamp fallback was dead code."
```

---

## Task 5: Mark the document failed when retries are exhausted

**Files:**
- Modify: `backend/app/workers/tasks.py` (the `except TransientStorageError:` branch)
- Test: `backend/tests/workers/test_retry_exhaustion.py` (create)

**Interfaces:**
- Consumes: Celery's `self.request.retries` and each task's `max_retries=3`.
- Produces: `_run_stage` accepts an optional `attempt_is_final: bool` so the caller tells it whether another retry is coming.

**Why:** `tasks.py:489-491` journals the stage failed and re-raises for `autoretry_for` but deliberately skips `mark_document_failed`. After `max_retries=3` the chain dies leaving `processing_jobs.state='failed'` with `documents.status='processing'` — permanently inconsistent, and the list shows a yellow "processing" pill forever.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workers/test_retry_exhaustion.py
"""A transient failure that exhausts its retries must not leave 'processing'."""

from __future__ import annotations

import uuid

import pytest

from app.storage.base import TransientStorageError
from app.workers import tasks


class _Journal:
    def __init__(self) -> None:
        self.job_id = uuid.uuid4()
        self.terminal: tuple[str, str] | None = None

    def mark_running(self, *a, **k):  # noqa: ANN001, ANN201, ARG002
        return self.job_id

    def mark_succeeded(self, *a, **k) -> None: ...  # noqa: ANN001, ARG002
    def mark_failed(self, job_row_id, error) -> None:  # noqa: ANN001, ARG002
        self.terminal = ("failed", error)

    def mark_skipped(self, *a, **k) -> None: ...  # noqa: ANN001, ARG002


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> tuple[_Journal, list[uuid.UUID]]:
    journal = _Journal()
    marked: list[uuid.UUID] = []
    monkeypatch.setattr(tasks, "_journal", lambda: journal)
    monkeypatch.setattr(tasks, "_already_succeeded", lambda *a, **k: False)
    monkeypatch.setattr(tasks, "_sessions", lambda: None)
    monkeypatch.setattr(
        tasks, "mark_document_failed", lambda _s, *, document_id: marked.append(document_id)
    )
    return journal, marked


def _ctx() -> dict[str, str]:
    return {
        "document_id": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "key": "docs-quarantine/t/d",
    }


def _boom() -> None:
    raise TransientStorageError("clamd INSTREAM exchange failed")


def test_non_final_attempt_leaves_document_processing(wired) -> None:  # noqa: ANN001
    journal, marked = wired
    ctx = _ctx()
    with pytest.raises(TransientStorageError):
        tasks._run_stage("scan", ctx, _boom, attempt_is_final=False)
    assert journal.terminal == ("failed", "transient failure in scan; retry scheduled")
    assert marked == [], "a retry is still coming; do not flip the document yet"


def test_final_attempt_marks_document_failed(wired) -> None:  # noqa: ANN001
    journal, marked = wired
    ctx = _ctx()
    with pytest.raises(TransientStorageError):
        tasks._run_stage("scan", ctx, _boom, attempt_is_final=True)
    assert journal.terminal is not None
    assert journal.terminal[0] == "failed"
    assert "retries exhausted" in journal.terminal[1]
    assert marked == [uuid.UUID(ctx["document_id"])], (
        "retries are exhausted; the document must not stay at 'processing'"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_retry_exhaustion.py -v`
Expected: FAIL — `TypeError: _run_stage() got an unexpected keyword argument 'attempt_is_final'`.

- [ ] **Step 3: Add the parameter and branch**

Change the `_run_stage` signature in `backend/app/workers/tasks.py`:

```python
def _run_stage(
    stage: str,
    ctx: PipelineCtx,
    body: Callable[[], None],
    requires: tuple[str, ...] = (),
    *,
    attempt_is_final: bool = False,
) -> PipelineCtx:
```

Extend the docstring with:

```
    ``attempt_is_final`` tells this frame whether celery has another retry left.
    A transient failure mid-retry must NOT flip the document out of
    'processing' (the pipeline is still live), but the last attempt must, or
    the row is stranded at 'processing' with a 'failed' job beside it.
```

Replace the `except TransientStorageError:` block with:

```python
    except TransientStorageError:
        if attempt_is_final:
            journal.mark_failed(job_row_id, f"transient failure in {stage}; retries exhausted")
            mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        else:
            journal.mark_failed(job_row_id, f"transient failure in {stage}; retry scheduled")
        raise
```

- [ ] **Step 4: Pass the flag from the task wrappers**

Each stage task is bound (it uses `self` for `autoretry_for`). For every task that can raise `TransientStorageError` — at minimum `scan_for_malware` at `tasks.py:501-503` — pass the flag. The pattern:

```python
@celery_app.task(bind=True, autoretry_for=(TransientStorageError,), max_retries=3, ...)
def scan_for_malware(self, ctx: PipelineCtx) -> PipelineCtx:  # noqa: ANN001
    return _run_stage(
        "scan",
        ctx,
        lambda: _scan_body(ctx),
        attempt_is_final=self.request.retries >= self.max_retries,
    )
```

Read the existing decorator arguments before editing and preserve them exactly; only add `bind=True` if it is absent, and add `self` as the first parameter when you do.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/workers -q`
Expected: PASS, including the 2 new tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/tasks.py backend/tests/workers/test_retry_exhaustion.py
git commit -m "fix(workers): flip the document to failed when retries are exhausted

A transient failure journaled the stage failed and re-raised for autoretry but
never marked the document, so an exhausted retry chain left
processing_jobs.state='failed' beside documents.status='processing'."
```

---

## Task 6: Raise ClamAV's stream ceiling to match the upload cap

**Files:**
- Create: `docker/clamav/clamd.conf`
- Modify: `docker-compose.yml` (the `clamav` service)
- Test: `backend/tests/test_scan_limits.py` (create)

**Interfaces:**
- Consumes: `Settings.upload_max_bytes` (default `104857600`).
- Produces: nothing consumed by later tasks.

**Why:** Stock `clamav/clamav:latest` defaults `StreamMaxLength` to 25 MB with no override in compose, against a declared 100 MB upload ceiling. Any file in the 25-100 MB band aborts the INSTREAM exchange, producing `ScanError` then `TransientStorageError`, then three retries, then the Task 5 failed state. The declared ceiling and the scanner's real ceiling differ by 4x.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_scan_limits.py
"""clamd's StreamMaxLength must not be below the upload cap.

Below it, every file in the gap aborts the INSTREAM exchange and burns three
retries before failing — a size limit enforced by timeout instead of by 413.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAMD_CONF = _REPO_ROOT / "docker" / "clamav" / "clamd.conf"

_SUFFIX = {"K": 1024, "M": 1024**2, "G": 1024**3}


def _parse_size(text: str) -> int:
    match = re.fullmatch(r"(\d+)([KMG]?)", text.strip(), re.IGNORECASE)
    assert match, f"unparseable size: {text!r}"
    return int(match.group(1)) * _SUFFIX.get(match.group(2).upper(), 1)


def _directive(name: str) -> str:
    for line in _CLAMD_CONF.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name} "):
            return stripped.split(None, 1)[1]
    raise AssertionError(f"{name} not set in {_CLAMD_CONF}")


def test_stream_max_length_covers_the_upload_cap() -> None:
    cap = Settings(env="dev").upload_max_bytes
    assert _parse_size(_directive("StreamMaxLength")) >= cap


def test_max_file_size_covers_the_upload_cap() -> None:
    cap = Settings(env="dev").upload_max_bytes
    assert _parse_size(_directive("MaxFileSize")) >= cap
```

If `Settings(env="dev")` requires more arguments in this codebase, construct it the way `backend/tests/` already does elsewhere.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scan_limits.py -v`
Expected: FAIL — the file does not exist.

- [ ] **Step 3: Create the clamd config**

```conf
# docker/clamav/clamd.conf
# Stock clamd defaults StreamMaxLength to 25M. The app advertises a 100 MiB
# upload cap, so files in the 25-100 MiB band abort the INSTREAM exchange and
# surface as a transient scan failure plus three wasted retries — a size limit
# enforced by timeout rather than by a 413. Keep these >= UPLOAD_MAX_BYTES.
LogTime yes
Foreground yes
TCPSocket 3310
TCPAddr 0.0.0.0
StreamMaxLength 100M
MaxFileSize 100M
MaxScanSize 100M
```

- [ ] **Step 4: Mount it in compose**

In the `clamav` service in `docker-compose.yml`, add to `volumes:`:

```yaml
      - ./docker/clamav/clamd.conf:/etc/clamav/clamd.conf:ro
```

- [ ] **Step 5: Run the test and restart clamav**

```bash
.venv/Scripts/python.exe -m pytest tests/test_scan_limits.py -v
docker compose up -d --force-recreate clamav
docker compose logs clamav --tail 20
```

Expected: tests PASS; clamd starts and reports listening on 3310. If clamd refuses the config, check the image's expected config path (`/etc/clamav/clamd.conf`) with `docker compose exec clamav ls /etc/clamav/`.

- [ ] **Step 6: Commit**

```bash
git add docker/clamav/clamd.conf docker-compose.yml backend/tests/test_scan_limits.py
git commit -m "fix(scan): raise clamd StreamMaxLength to match the upload cap

Stock clamd caps INSTREAM at 25M against a declared 100 MiB upload ceiling, so
files in the gap aborted the scan and burned three retries before failing."
```

---

## Task 7: Give scanned PDFs a terminal state instead of hanging

**Files:**
- Modify: `backend/app/workers/tasks.py` (the `except NeedsOcrError:` branch)
- Modify: `backend/app/workers/jobs.py` (add `mark_document_held`)
- Test: `backend/tests/workers/test_needs_ocr_terminal.py` (create)

**Interfaces:**
- Consumes: `Document.status` CHECK constraint already permits `'held'` (`ck_documents_status_valid`: quarantined/processing/ready/failed/held).
- Produces: `mark_document_held(sessions: sessionmaker[Session], *, document_id: uuid.UUID) -> None` in `app/workers/jobs.py`.

**Why:** `pdf.py:51-52` raises `NeedsOcrError` for a PDF with under 20 characters of text; `_run_stage` journals `skipped` and raises `Ignore()`, and no OCR worker exists (`enqueue_ocr` only writes a queued row and logs). The document keeps `status='processing'` permanently. Real OCR stays out of scope — this task only makes the outcome honest and visible.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workers/test_needs_ocr_terminal.py
"""A PDF needing OCR must reach a terminal state, not hang at 'processing'.

Real OCR is out of scope (no tesseract worker exists). 'held' is an allowed
documents.status value and means "stopped, awaiting a capability we lack".
"""

from __future__ import annotations

import uuid

import pytest

from app.extraction.errors import NeedsOcrError
from app.workers import tasks


class _Journal:
    def __init__(self) -> None:
        self.job_id = uuid.uuid4()
        self.terminal: tuple[str, str] | None = None

    def mark_running(self, *a, **k):  # noqa: ANN001, ANN201, ARG002
        return self.job_id

    def mark_succeeded(self, *a, **k) -> None: ...  # noqa: ANN001, ARG002
    def mark_failed(self, job_row_id, error) -> None:  # noqa: ANN001, ARG002
        self.terminal = ("failed", error)

    def mark_skipped(self, job_row_id, reason) -> None:  # noqa: ANN001, ARG002
        self.terminal = ("skipped", reason)


def test_needs_ocr_marks_the_document_held(monkeypatch: pytest.MonkeyPatch) -> None:
    from celery.exceptions import Ignore

    journal = _Journal()
    held: list[uuid.UUID] = []
    monkeypatch.setattr(tasks, "_journal", lambda: journal)
    monkeypatch.setattr(tasks, "_already_succeeded", lambda *a, **k: False)
    monkeypatch.setattr(tasks, "_sessions", lambda: None)
    monkeypatch.setattr(
        tasks, "mark_document_held", lambda _s, *, document_id: held.append(document_id)
    )
    ctx = {
        "document_id": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "key": "docs-primary/t/ab/abc",
    }

    def body() -> None:
        raise NeedsOcrError("scanned pdf")

    with pytest.raises(Ignore):
        tasks._run_stage("extract", ctx, body)

    assert journal.terminal == ("skipped", "needs_ocr")
    assert held == [uuid.UUID(ctx["document_id"])], (
        "no OCR worker exists; leaving status='processing' hangs the row forever"
    )
```

Adjust the `NeedsOcrError` import path to wherever it is actually defined — check with `grep -rn "class NeedsOcrError" backend/app`.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/workers/test_needs_ocr_terminal.py -v`
Expected: FAIL — `AttributeError: module 'app.workers.tasks' has no attribute 'mark_document_held'`.

- [ ] **Step 3: Add `mark_document_held`**

In `backend/app/workers/jobs.py`, next to `mark_document_failed`:

```python
def mark_document_held(sessions: sessionmaker[Session], *, document_id: uuid.UUID) -> None:
    """Terminal 'held' flip for a document blocked on a capability we lack.

    'held' is distinct from 'failed': the document is intact and will process
    once the missing capability (today: OCR) exists. Without this flip the row
    sits at 'processing' forever with no worker that will ever pick it up (#4).
    """
    with sessions() as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(status="held"))
```

- [ ] **Step 4: Use it in the OCR branch**

Import it in `tasks.py` alongside `mark_document_failed`, then replace:

```python
    except NeedsOcrError:
        journal.mark_skipped(job_row_id, "needs_tesseract")
        raise Ignore() from None
```

with:

```python
    except NeedsOcrError:
        # No OCR worker exists (enqueue_ocr only journals a queued row). Leaving
        # the document at 'processing' hangs it forever with nothing that will
        # ever pick it up, so give it the terminal 'held' state instead.
        journal.mark_skipped(job_row_id, "needs_ocr")
        mark_document_held(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise Ignore() from None
```

- [ ] **Step 5: Surface `held` in the frontend status styling**

In `frontend/src/features/documents/DocumentsPage.tsx`, the status pill currently branches `ready` / `failed` / else. Add a `held` branch styled like a warning (amber) with the label `held`, and make sure the Status filter's option list includes it. Locate the existing ternary near `doc.status === 'ready'` and extend it.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/workers -q` and `cd ../frontend && npm run test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/workers/jobs.py backend/app/workers/tasks.py backend/tests/workers/test_needs_ocr_terminal.py frontend/src/features/documents/DocumentsPage.tsx
git commit -m "fix(workers): mark OCR-needing documents 'held' instead of hanging

pdf.py raises NeedsOcrError for scanned PDFs and the chain halts, but no OCR
worker exists, so the row sat at 'processing' forever. 'held' is already an
allowed status and says: intact, blocked on a capability we lack."
```

---

## Task 8: Make `complete_upload` verify what its docstring claims

**Files:**
- Modify: `backend/app/api/v1/uploads.py:236-295`
- Modify: `backend/app/storage/base.py` (add a `stat` capability if absent)
- Test: `backend/tests/api/test_upload_completion_checks.py` (create)

**Interfaces:**
- Consumes: `Storage.stat(key) -> ObjectStat | None` — add it to the `Storage` protocol if it does not exist, implemented as `os.stat` in `LocalStorage` and `head_object` in `S3Storage`.
- Produces: `complete_upload` raises 409 when the quarantine object is missing or its length disagrees with the declared size.

**Why:** `uploads.py:236-295` performs no existence check, no size re-check, no MIME sniff and no hash, despite its docstring (`uploads.py:6-27`) claiming all four. `CompleteRequest.size_bytes` is accepted from the browser and discarded. A client can complete an upload it never PUT; the chain then fires, `_read_object` raises `FileNotFoundError`, and before Task 3 that stranded the document silently.

Sniffing and hashing stay in the worker — invariant #1 forbids the API reading bytes on the write path. This task checks **metadata only**.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_upload_completion_checks.py
"""Completion must verify the object landed and is the size that was declared.

Invariant #1 keeps the API off the bytes, so these are metadata checks only:
existence and length, never a read.
"""

from __future__ import annotations

import uuid

from starlette.status import HTTP_409_CONFLICT


def test_complete_rejects_when_no_object_was_ever_put(client_factory, fake_storage) -> None:  # noqa: ANN001
    fake_storage.objects.clear()
    client, upload_id = client_factory.with_quarantined_document()
    response = client.post(f"/v1/uploads/{upload_id}/complete", json={"size_bytes": 10})
    assert response.status_code == HTTP_409_CONFLICT
    body = response.json()
    assert "did not arrive" in body["detail"]


def test_complete_rejects_a_size_mismatch(client_factory, fake_storage) -> None:  # noqa: ANN001
    client, upload_id, key = client_factory.with_quarantined_document(return_key=True)
    fake_storage.objects[key] = b"x" * 10
    response = client.post(f"/v1/uploads/{upload_id}/complete", json={"size_bytes": 999})
    assert response.status_code == HTTP_409_CONFLICT
    assert "size" in response.json()["detail"]


def test_complete_accepts_a_matching_object(client_factory, fake_storage) -> None:  # noqa: ANN001
    client, upload_id, key = client_factory.with_quarantined_document(return_key=True)
    fake_storage.objects[key] = b"x" * 10
    response = client.post(f"/v1/uploads/{upload_id}/complete", json={"size_bytes": 10})
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_complete_never_reads_the_body(client_factory, fake_storage) -> None:  # noqa: ANN001
    """#1: the API signs and records intent; it does not touch the bytes."""
    client, upload_id, key = client_factory.with_quarantined_document(return_key=True)
    fake_storage.objects[key] = b"x" * 10
    client.post(f"/v1/uploads/{upload_id}/complete", json={"size_bytes": 10})
    assert fake_storage.open_calls == [], "completion read the object body (#1 violation)"
```

Read `backend/tests/api/conftest.py` first and reuse its existing storage fake and client factory rather than inventing `fake_storage` / `client_factory.with_quarantined_document`. Extend the existing fixtures if they lack an object map or an `open_calls` spy; match the established naming.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_upload_completion_checks.py -v`
Expected: FAIL — completion currently returns 200 regardless.

- [ ] **Step 3: Add a metadata-only `stat` to the storage protocol**

In `backend/app/storage/base.py`:

```python
@dataclass(frozen=True)
class ObjectStat:
    """Metadata about a stored object. Deliberately carries no bytes (#1)."""

    size_bytes: int
```

Add to the `Storage` protocol:

```python
    def stat(self, key: str) -> ObjectStat | None:
        """Size of the object at ``key``, or None if it does not exist.

        Metadata only: the API calls this on the write path, where invariant #1
        forbids reading the body.
        """
        ...
```

In `LocalStorage`:

```python
    def stat(self, key: str) -> ObjectStat | None:
        path = self._resolve(key)
        if not path.is_file():
            return None
        return ObjectStat(size_bytes=path.stat().st_size)
```

In `S3Storage`:

```python
    def stat(self, key: str) -> ObjectStat | None:
        from botocore.exceptions import ClientError

        try:
            head = self._client.head_object(Bucket=self._bucket_for(key), Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return ObjectStat(size_bytes=int(head["ContentLength"]))
```

- [ ] **Step 4: Enforce the checks in `complete_upload`**

In `backend/app/api/v1/uploads.py`, immediately after the `if doc.status != "quarantined":` guard and **before** `_provision_actor`, insert:

```python
        # #1 keeps the API off the bytes, so verify metadata only. Without this
        # a client can complete an upload it never PUT: the chain fires, the
        # worker cannot find the object, and the document strands.
        quarantine = storage.stat(quarantine_key(doc.tenant_id, doc.id))
        if quarantine is None:
            raise HTTPException(
                HTTP_409_CONFLICT, "upload did not arrive; the object was never stored"
            )
        if payload is not None and payload.size_bytes is not None:
            if quarantine.size_bytes != payload.size_bytes:
                raise HTTPException(
                    HTTP_409_CONFLICT,
                    "stored object size does not match the declared size",
                )
        if quarantine.size_bytes > settings.upload_max_bytes:
            raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "stored object exceeds upload cap")
```

Import `quarantine_key` from `app.storage.keys` and `HTTP_413_CONTENT_TOO_LARGE` from `starlette.status` if not already imported. Note this makes `payload` and `settings` load-bearing — they were previously unused parameters.

Update the module docstring at `uploads.py:6-27` so it describes what the code now actually does: existence and size are checked here; sniffing and hashing happen in the worker.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: PASS. `tests/api/test_uploads.py:3-4` advertises MIME sniffing and sha256 derivation at this layer — correct that docstring to match reality rather than adding the behaviour.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/uploads.py backend/app/storage/base.py backend/app/storage/local.py backend/app/storage/s3.py backend/tests/api/test_upload_completion_checks.py backend/tests/api/test_uploads.py
git commit -m "fix(uploads): verify the object landed before enqueueing the chain

complete_upload did none of the four things its docstring claimed and ignored
the size_bytes the browser sent, so a client could complete an upload it never
PUT. Add a metadata-only Storage.stat and check existence and length; sniffing
and hashing stay in the worker per invariant #1."
```

---

## Task 9: Enforce the size cap in object storage itself

**Files:**
- Modify: `backend/app/storage/s3.py` (`presign_put`)
- Modify: `backend/app/api/v1/uploads.py` (pass the cap through)
- Test: `backend/tests/storage/test_presign_size_limit.py` (create)

**Interfaces:**
- Consumes: `Settings.upload_max_bytes`.
- Produces: `Storage.presign_put(key, ttl, *, content_type, max_bytes: int)` — the `max_bytes` keyword is new and required.

**Why:** `s3.py:138-148` presigns with only Bucket/Key/ContentType. There is no nginx and no uvicorn body limit. The 100 MB ceiling is enforced only against a client-supplied integer (`uploads.py:198`) and a client-side JS check — both trivially bypassed. Storage itself must reject an oversized body.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/storage/test_presign_size_limit.py
"""The presigned upload credential must carry a size ceiling.

Without it the only enforcement is a client-supplied integer and a JS check,
so any client can PUT an object of any size into the quarantine bucket.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.storage.s3 import S3Storage


def _storage() -> tuple[S3Storage, MagicMock]:
    client = MagicMock()
    client.generate_presigned_post.return_value = {"url": "http://minio/b", "fields": {}}
    return S3Storage(client, bucket_prefix="docs"), client


def test_presign_put_pins_a_content_length_range() -> None:
    storage, client = _storage()
    storage.presign_put("docs-quarantine/t/d", 120, content_type="application/pdf", max_bytes=1024)
    conditions = client.generate_presigned_post.call_args.kwargs["Conditions"]
    assert ["content-length-range", 1, 1024] in conditions


def test_presign_put_requires_max_bytes() -> None:
    storage, _ = _storage()
    try:
        storage.presign_put("k", 120, content_type="application/pdf")  # type: ignore[call-arg]
    except TypeError:
        return
    raise AssertionError("max_bytes must be required, not optional")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_presign_size_limit.py -v`
Expected: FAIL — `presign_put()` has no `max_bytes` parameter.

- [ ] **Step 3: Switch `presign_put` to a presigned POST with a size condition**

`generate_presigned_url` cannot express a size condition; `generate_presigned_post` can. In `backend/app/storage/s3.py`:

```python
    def presign_put(
        self, key: str, ttl: int, *, content_type: str, max_bytes: int
    ) -> PresignedUpload:
        """Presigned direct upload with a storage-enforced size ceiling.

        A presigned PUT URL cannot express a size limit, so this issues a
        presigned POST policy instead: content-length-range is evaluated by the
        storage service, which is the only enforcement a client cannot bypass.
        """
        signed = self._client.generate_presigned_post(
            Bucket=self._bucket_for(key),
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=clamp_upload_presign_ttl(ttl),
        )
        return PresignedUpload(url=signed["url"], fields=signed["fields"])
```

Define `PresignedUpload` as a frozen dataclass with `url: str` and `fields: dict[str, str]` in `app/storage/base.py`, and add the matching signature to the `Storage` protocol. `clamp_upload_presign_ttl` arrives in Task 12 — until then use `clamp_presign_ttl`.

**This changes the upload wire format from PUT to POST.** The frontend's `putDirect` must send `multipart/form-data` with the returned `fields` plus the file last. Update `frontend/src/api/client.ts` and the intent response model together, and update `frontend/src/features/upload/UploadPage.test.tsx:210`, which pins the request shape.

If that frontend change is too large to land atomically here, keep `LocalStorage` (the dev default) on the existing PUT path and gate the POST form on `storage_backend == "minio"`; the Task 8 completion check is then the enforcement in dev. Note whichever you chose in the commit message.

- [ ] **Step 4: Pass the cap from the intent route**

In `backend/app/api/v1/uploads.py`, where `presign_put` is called (around line 214), add `max_bytes=settings.upload_max_bytes`.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/storage tests/api -q` and `cd ../frontend && npm run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/storage/ backend/app/api/v1/uploads.py backend/tests/storage/test_presign_size_limit.py frontend/src/api/client.ts frontend/src/features/upload/
git commit -m "fix(uploads): enforce the size cap in object storage

The presign carried no content-length-range, so the 100 MiB ceiling was
enforced only against a client-supplied integer and a JS check. Issue a
presigned POST policy whose content-length-range the storage service itself
evaluates."
```

---

## Task 10: Bind the HTTP method into the dev presign signature

**Files:**
- Modify: `backend/app/storage/local.py:152-171`
- Modify: `backend/app/api/v1/dev_storage.py` (both routes)
- Test: `backend/tests/storage/test_presign_method_binding.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `LocalStorage.presign(key, ttl, *, filename, method="GET")` and `verify_presign(key, expires, sig, *, method, now=None)`.

**Why:** `local.py:152-171` signs `f"{key}:{expires}"`, and `get_dev_object` and `put_dev_object` share one verifier. A URL minted for download is a valid upload credential for the same key, and vice-versa. Dev-only, but it is a signature that does not cover what it authorises.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/storage/test_presign_method_binding.py
"""A download credential must not authorise an upload.

presign signed key:expires only, and one verifier served both routes, so a GET
URL was a valid PUT credential for the same key.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path) -> LocalStorage:  # noqa: ANN001
    return LocalStorage(tmp_path, signing_secret="s" * 32, bucket_prefix="docs")


def _sig_and_expiry(url: str) -> tuple[str, int]:
    query = parse_qs(urlparse(url).query)
    return query["sig"][0], int(query["expires"][0])


def test_get_credential_does_not_verify_for_put(storage: LocalStorage) -> None:
    url = storage.presign("docs-primary/t/ab/abc", 120, filename="x.pdf", method="GET")
    sig, expires = _sig_and_expiry(url)
    assert storage.verify_presign("docs-primary/t/ab/abc", expires, sig, method="GET")
    assert not storage.verify_presign("docs-primary/t/ab/abc", expires, sig, method="PUT")


def test_put_credential_does_not_verify_for_get(storage: LocalStorage) -> None:
    url = storage.presign("docs-quarantine/t/d", 120, filename="x.pdf", method="PUT")
    sig, expires = _sig_and_expiry(url)
    assert storage.verify_presign("docs-quarantine/t/d", expires, sig, method="PUT")
    assert not storage.verify_presign("docs-quarantine/t/d", expires, sig, method="GET")


def test_expired_credential_is_rejected(storage: LocalStorage) -> None:
    url = storage.presign("docs-primary/t/ab/abc", 120, filename="x.pdf", method="GET")
    sig, expires = _sig_and_expiry(url)
    assert not storage.verify_presign(
        "docs-primary/t/ab/abc", expires, sig, method="GET", now=time.time() + 10_000
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_presign_method_binding.py -v`
Expected: FAIL — `presign()` has no `method` parameter.

- [ ] **Step 3: Bind the method into both sides**

In `backend/app/storage/local.py`:

```python
    def presign(self, key: str, ttl: int, *, filename: str, method: str = "GET") -> str:
        """Dev HMAC URL. The method is signed: a GET credential is not a PUT one."""
        expires = int(time.time()) + clamp_presign_ttl(ttl)
        signature = self._sign(key, expires, method)
        encoded_name = quote(filename, safe="")
        return (
            f"{DEV_PRESIGN_BASE_URL}{quote(key, safe='')}"
            f"?expires={expires}&sig={signature}&filename={encoded_name}"
        )

    def _sign(self, key: str, expires: int, method: str) -> str:
        payload = f"{method.upper()}:{key}:{int(expires)}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify_presign(
        self, key: str, expires: int, sig: str, *, method: str, now: float | None = None
    ) -> bool:
        """Constant-time check of a dev presign; False once expired."""
        current = time.time() if now is None else now
        if expires <= current:
            return False
        return hmac.compare_digest(self._sign(key, expires, method), sig)
```

- [ ] **Step 4: Pass the method from both dev-storage routes**

In `backend/app/api/v1/dev_storage.py`, the GET handler passes `method="GET"` and the PUT handler passes `method="PUT"` to `verify_presign`.

- [ ] **Step 5: Update the intent route's fallback**

`uploads.py:214-218` falls through to `storage.presign(...)` when `presign_put` is absent (which is the case for `LocalStorage`). That fallback must now pass `method="PUT"`, or every dev upload breaks. Find it and add the argument.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/storage tests/api -q`
Expected: PASS. Any existing test calling `verify_presign` positionally needs the new keyword.

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage/local.py backend/app/api/v1/dev_storage.py backend/app/api/v1/uploads.py backend/tests/storage/test_presign_method_binding.py
git commit -m "fix(storage): sign the HTTP method into the dev presign

presign signed key:expires and both dev-storage routes shared one verifier, so
a download URL was a valid upload credential for the same key."
```

---

## Task 11: Report duplicate content at completion

**Files:**
- Modify: `backend/app/api/v1/uploads.py` (`complete_upload` response model)
- Test: `backend/tests/api/test_upload_dedup.py` (create)

**Interfaces:**
- Consumes: `Blob.sha256` (PK), `DocumentVersion.blob_sha256`.
- Produces: `CompleteResponse` gains `duplicate_of: uuid.UUID | None`.

**Why:** Two rows share sha256 `42e5684cb2`. Dedup is deferred to `promote_blob_record`, i.e. after the duplicate has been fully re-uploaded and re-scanned. The blob-level dedup is correct and stays; what is missing is telling the user their document already exists.

Note: the API cannot compute the sha here (invariant #1 forbids reading the bytes). So this reports the duplicate **after** the worker promotes, via the existing document detail route, rather than at completion.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_upload_dedup.py
"""Surface an existing document with identical content.

The API cannot hash at completion (#1 keeps it off the bytes), so the duplicate
is reported on the document detail route once the worker has promoted the blob.
"""

from __future__ import annotations

import uuid


def test_detail_reports_a_sibling_with_the_same_content(client_factory, monkeypatch) -> None:  # noqa: ANN001
    from app.api.v1 import documents

    sibling = uuid.uuid4()
    monkeypatch.setattr(documents, "_fetch_content_siblings", lambda *a, **k: [sibling])
    client, doc_id = client_factory.with_ready_document()
    body = client.get(f"/v1/documents/{doc_id}").json()
    assert body["duplicate_of"] == [str(sibling)]


def test_detail_reports_no_duplicates_for_unique_content(client_factory, monkeypatch) -> None:  # noqa: ANN001
    from app.api.v1 import documents

    monkeypatch.setattr(documents, "_fetch_content_siblings", lambda *a, **k: [])
    client, doc_id = client_factory.with_ready_document()
    assert client.get(f"/v1/documents/{doc_id}").json()["duplicate_of"] == []
```

Reuse the existing `client_factory` from `tests/api/conftest.py`; add a `with_ready_document` helper there if absent, following the established fixture style.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_upload_dedup.py -v`
Expected: FAIL — `_fetch_content_siblings` does not exist.

- [ ] **Step 3: Add the seam and the field**

In `backend/app/api/v1/documents.py`, add a module-level seam function (matching the `_fetch_*` pattern the test suite monkeypatches):

```python
async def _fetch_content_siblings(
    session: AsyncSession, document_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[uuid.UUID]:
    """Other visible documents in this tenant sharing this document's bytes.

    Content dedup already happens at the blob layer; this only tells the user
    the duplicate exists. Scoped to the tenant and to non-deleted rows, so it
    reveals nothing the list endpoint would not (#15: the object key is never
    an authorization boundary — permission lives on the documents row).
    """
    this_sha = (
        select(DocumentVersion.blob_sha256)
        .where(DocumentVersion.document_id == document_id)
        .scalar_subquery()
    )
    stmt = (
        select(Document.id)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            DocumentVersion.blob_sha256 == this_sha,
            DocumentVersion.blob_sha256.is_not(None),
            Document.id != document_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())
```

Add `duplicate_of: list[uuid.UUID] = []` to the `DocumentListItem` (or the detail response model used by `get_document`) and populate it in the handler.

- [ ] **Step 4: Show it in the drawer**

In `frontend/src/features/documents/DocumentDrawer.tsx`, when `duplicate_of` is non-empty, render an informational banner: `This content is identical to N other document(s) in your tenant.` Add `duplicate_of: string[]` to the matching type in `frontend/src/api/types.ts`.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q` and `cd ../frontend && npm run typecheck && npm run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/documents.py backend/tests/api/test_upload_dedup.py frontend/src/
git commit -m "feat(documents): surface documents with identical content

Blob-level dedup already happened, but nothing told the user their upload
duplicated an existing document. Reported on the detail route after promotion,
since #1 keeps the API off the bytes at completion."
```

---

## Task 12: Give uploads their own presign TTL

**Files:**
- Modify: `backend/app/storage/base.py:15-30`
- Modify: `backend/app/config.py`
- Test: `backend/tests/storage/test_upload_ttl.py` (create)

**Interfaces:**
- Consumes: new setting `upload_presign_ttl_seconds: int = 900`.
- Produces: `clamp_upload_presign_ttl(ttl: int) -> int` clamped to `[300, 3600]`, alongside the unchanged `clamp_presign_ttl` for downloads.

**Why:** `clamp_presign_ttl` pins TTL to [60,120] seconds and is shared with downloads. A 100 MB single-shot upload on a slow link cannot finish inside 120 s, and there is no retry (Task 16), so the whole transfer is lost with a 403. The download clamp is correct per invariant #17 and must not move.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/storage/test_upload_ttl.py
"""Uploads need a longer presign window than downloads.

#17 pins download presigns to 60-120s. A 100 MiB single-shot upload cannot
finish in 120s, and there is no resume — the transfer is simply lost.
"""

from __future__ import annotations

import pytest

from app.storage.base import clamp_presign_ttl, clamp_upload_presign_ttl


def test_download_clamp_is_unchanged() -> None:
    assert clamp_presign_ttl(10) == 60
    assert clamp_presign_ttl(90) == 90
    assert clamp_presign_ttl(9999) == 120


@pytest.mark.parametrize(("given", "expected"), [(1, 300), (900, 900), (99999, 3600)])
def test_upload_clamp_allows_a_longer_window(given: int, expected: int) -> None:
    assert clamp_upload_presign_ttl(given) == expected


def test_upload_window_is_never_shorter_than_the_download_window() -> None:
    assert clamp_upload_presign_ttl(60) >= clamp_presign_ttl(120)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_upload_ttl.py -v`
Expected: FAIL — `ImportError: cannot import name 'clamp_upload_presign_ttl'`.

- [ ] **Step 3: Add the upload clamp**

In `backend/app/storage/base.py`, beside the existing download bounds:

```python
# Uploads get their own window. #17's 60-120s ceiling exists so a leaked
# DOWNLOAD URL expires fast; it is not a statement about how long a client
# needs to push 100 MiB. Sharing one clamp made large uploads unfinishable.
UPLOAD_PRESIGN_TTL_MIN: Final = 300
UPLOAD_PRESIGN_TTL_MAX: Final = 3600


def clamp_upload_presign_ttl(ttl: int) -> int:
    """Clamp an upload presign TTL to [300, 3600] seconds."""
    return max(UPLOAD_PRESIGN_TTL_MIN, min(ttl, UPLOAD_PRESIGN_TTL_MAX))
```

- [ ] **Step 4: Add the setting and use it**

In `backend/app/config.py`, next to the existing presign TTL setting:

```python
    upload_presign_ttl_seconds: int = 900
```

Apply the same `field_validator` clamping pattern the existing presign TTL uses (see `config.py:99-103`), but with `clamp_upload_presign_ttl`. Then in `uploads.py`, pass `settings.upload_presign_ttl_seconds` where the intent route currently passes the download TTL, and make `S3Storage.presign_put` use `clamp_upload_presign_ttl`.

Leave `LocalStorage.presign`'s download path on `clamp_presign_ttl`; only the `method="PUT"` case should use the upload clamp.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/storage tests/api -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/storage/base.py backend/app/config.py backend/app/api/v1/uploads.py backend/tests/storage/test_upload_ttl.py
git commit -m "fix(uploads): give uploads a longer presign window than downloads

#17's 60-120s clamp protects a leaked download URL; applying it to uploads made
a 100 MiB transfer unfinishable on a slow link, with no resume."
```

---

## Task 13: Apply the status and level filters server-side

**Files:**
- Modify: `backend/app/api/v1/documents.py:308-363` (`_fetch_document_page`) and `:556-569` (`list_documents`)
- Test: `backend/tests/api/test_document_filters.py` (create)

**Interfaces:**
- Consumes: `Document.status`, `SecurityLevel.name`.
- Produces: `_fetch_document_page(session, user, after, limit_plus_one, *, status: str | None = None, level: str | None = None)`.

**Why:** The UI sends `status` and `security_level` (`DocumentsPage.tsx:55-60`); `list_documents` declares only `limit` and `cursor`, and FastAPI discards unknown query params without error. Selecting "Failed" returns the unfiltered list — visible in the user's own screenshot. This defeats the one workflow an operator uses to find failed uploads.

The filter must go **inside** the keyset query, before pagination — filtering after the page is cut would return short pages and leak counts.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_document_filters.py
"""status / security_level must filter, and must do so inside the query.

Filtering after the page is cut yields short pages and leaks how many rows the
caller could not see.
"""

from __future__ import annotations

import pytest
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY


def test_status_filter_reaches_the_query(client_factory, captured_page_args) -> None:  # noqa: ANN001
    client = client_factory()
    client.get("/v1/documents?status=failed")
    assert captured_page_args["status"] == "failed"


def test_level_filter_reaches_the_query(client_factory, captured_page_args) -> None:  # noqa: ANN001
    client = client_factory()
    client.get("/v1/documents?security_level=confidential")
    assert captured_page_args["level"] == "confidential"


def test_absent_filters_are_none(client_factory, captured_page_args) -> None:  # noqa: ANN001
    client = client_factory()
    client.get("/v1/documents")
    assert captured_page_args["status"] is None
    assert captured_page_args["level"] is None


@pytest.mark.parametrize("bad", ["deleted", "'; DROP TABLE documents;--", "READY"])
def test_unknown_status_is_rejected_not_ignored(client_factory, bad: str) -> None:  # noqa: ANN001
    """A silently ignored filter is how this bug shipped. Reject instead."""
    client = client_factory()
    assert client.get(f"/v1/documents?status={bad}").status_code == HTTP_422_UNPROCESSABLE_ENTITY
```

Add a `captured_page_args` fixture to `tests/api/conftest.py` that monkeypatches `documents._fetch_document_page` and records its keyword arguments, following the existing seam-patching style.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_document_filters.py -v`
Expected: FAIL — `KeyError: 'status'`; the unknown-status case returns 200.

- [ ] **Step 3: Add validated query parameters**

In `backend/app/api/v1/documents.py`, define the allowed values near the top:

```python
DOCUMENT_STATUSES: Final = ("quarantined", "processing", "ready", "failed", "held")
```

These mirror `ck_documents_status_valid`. Then change the route signature:

```python
@router.get("", response_model=DocumentPage)
async def list_documents(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None),
    status: Literal[DOCUMENT_STATUSES] | None = Query(default=None),  # type: ignore[valid-type]
    security_level: LevelName | None = Query(default=None),
) -> DocumentPage:
    after = decode_cursor(cursor) if cursor is not None else None
    async with sessions(user.tenant_id) as session:
        rows = await _fetch_document_page(
            session, user, after, limit + 1, status=status, level=security_level
        )
```

If `Literal[DOCUMENT_STATUSES]` does not typecheck under mypy strict, spell the literal out explicitly: `Literal["quarantined", "processing", "ready", "failed", "held"]`. Reuse the existing `LevelName` type used elsewhere in this module for the level.

- [ ] **Step 4: Apply the filters inside the query**

In `_fetch_document_page`, add the parameters and apply them **before** `.limit(...)`:

```python
async def _fetch_document_page(
    session: AsyncSession,
    user: UserCtx,
    after: tuple[datetime, uuid.UUID] | None,
    limit_plus_one: int,
    *,
    status: str | None = None,
    level: str | None = None,
) -> list[DocumentListItem]:
```

and after the existing department predicate:

```python
    # Inside the query, before the limit. Filtering the page after it is cut
    # returns short pages and leaks the count of rows the caller cannot see.
    if status is not None:
        stmt = stmt.where(Document.status == status)
    if level is not None:
        stmt = stmt.where(func.lower(SecurityLevel.name) == level.lower())
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: PASS.

- [ ] **Step 6: Verify against the live stack**

```bash
docker compose build api && docker compose up -d api
```

Open the documents page, set Status to "Failed", and confirm only failed rows appear.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/documents.py backend/tests/api/ frontend/src/features/documents/DocumentsPage.tsx
git commit -m "fix(documents): apply the status and level filters server-side

The UI sent status/security_level and FastAPI silently discarded them, so
'Status: Failed' returned the unfiltered list. Applied inside the keyset query
before pagination; an unknown value is now a 422 rather than ignored."
```

---

## Task 14: Distinguish "still processing" from "not found"

**Files:**
- Modify: `backend/app/api/v1/documents.py:629-712` (`download_document_content`, `view_document_content`)
- Test: `backend/tests/api/test_content_not_ready.py` (create)

**Interfaces:**
- Consumes: `_denied(view, user, action)`, `DocumentView.blob_key`, `DocumentView.status`.
- Produces: 409 for an authorised caller whose document has no promoted blob yet.

**Why:** Both byte routes return the canonical 404 when `blob_key is None` — the state of every document between completion and promotion. The user sees "Failed to download (404)" for a document they are looking at. Invariant #31 governs *cross-tenant* parity; it says nothing about a caller who has already passed the access check and can see the row in their own list.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_content_not_ready.py
"""An authorised caller gets 409 for an unpromoted blob; everyone else gets 404.

#31 requires cross-tenant and nonexistent 404s to be byte-identical. It does not
require lying to a caller who can already see the row in their own list.
"""

from __future__ import annotations

from starlette.status import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

ROUTES = ("content", "view")


def test_authorised_caller_gets_409_while_processing(client_factory, monkeypatch) -> None:  # noqa: ANN001
    from app.api.v1 import documents

    client, doc_id = client_factory.with_document(blob_key=None, status="processing")
    for route in ROUTES:
        response = client.get(f"/v1/documents/{doc_id}/{route}")
        assert response.status_code == HTTP_409_CONFLICT, route
        assert response.json()["detail"] == "document is still processing"


def test_held_document_reports_its_own_state(client_factory) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_document(blob_key=None, status="held")
    body = client.get(f"/v1/documents/{doc_id}/content").json()
    assert "held" in body["detail"]


def test_cross_tenant_404_is_byte_identical_to_nonexistent(client_factory) -> None:  # noqa: ANN001
    """#31 parity must survive this change."""
    import uuid

    client = client_factory(tenant="outsider")
    foreign = client_factory.foreign_document_id()
    a = client.get(f"/v1/documents/{foreign}/content")
    b = client.get(f"/v1/documents/{uuid.uuid4()}/content")
    assert a.status_code == b.status_code == HTTP_404_NOT_FOUND
    assert a.content == b.content
```

Extend `tests/api/conftest.py`'s factory with `with_document(blob_key=..., status=...)` and `foreign_document_id()` if absent, matching the existing style.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_content_not_ready.py -v`
Expected: FAIL — the first two return 404. The third should already pass; if it does not, stop and fix the parity regression before continuing.

- [ ] **Step 3: Add a shared not-ready guard**

In `backend/app/api/v1/documents.py`, add near `_denied`:

```python
_NOT_READY_DETAIL: Final = {
    "processing": "document is still processing",
    "quarantined": "document is still processing",
    "held": "document is held awaiting OCR, which is not yet available",
    "failed": "document processing failed; see the pipeline journal",
}


def _not_ready(view: DocumentView) -> HTTPException | None:
    """409 for an authorised caller whose bytes are not promoted yet.

    #31 governs cross-tenant parity: a foreign or nonexistent document must
    still 404 identically. This branch is only reached AFTER _denied() has
    passed, so the caller can already see this row in their own list — telling
    them it is processing reveals nothing new, and the opaque 404 was
    indistinguishable from a permission denial.
    """
    if view.blob_key is not None:
        return None
    detail = _NOT_READY_DETAIL.get(view.status, "document content is not available yet")
    return HTTPException(HTTP_409_CONFLICT, detail)
```

- [ ] **Step 4: Use it in both routes**

In `download_document_content` and `view_document_content`, replace the `if view.blob_key is None: return not_found()` branch with:

```python
        problem = _not_ready(view)
        if problem is not None:
            raise problem
```

Leave the preceding `if _denied(...) or view is None: return not_found()` exactly as it is — that is the invariant #31 path.

Confirm `DocumentView` carries `status`; if `_fetch_document_view` does not select it, add it to both the SELECT list and the dataclass, keeping the positional order aligned (the row is unpacked positionally at `documents.py:409`).

- [ ] **Step 5: Handle 409 in the client**

In `frontend/src/api/client.ts`, `fetchDocumentContent` and `fetchDocumentView` should surface the 409 `detail` rather than a generic failure, so the drawer shows "document is still processing".

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q` and `cd ../frontend && npm run test`
Expected: PASS, including every existing cross-tenant parity test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/documents.py backend/tests/api/test_content_not_ready.py frontend/src/api/client.ts
git commit -m "fix(documents): 409 for an unpromoted blob instead of an opaque 404

Every document between completion and promotion returned the canonical 404, so
a user looking at their own row saw 'Failed to download (404)'. Cross-tenant and
nonexistent 404 parity (#31) is unchanged and still asserted."
```

---

## Task 15: Show the failure reason and keep the drawer live

**Files:**
- Modify: `frontend/src/features/documents/DocumentDrawer.tsx:351-388`
- Modify: `frontend/src/features/documents/DocumentsPage.tsx`
- Test: `frontend/src/features/documents/DocumentDrawer.test.tsx` (extend)

**Interfaces:**
- Consumes: `JobOut.error`, `JobOut.attempts`, `JobOut.started_at`, `JobOut.finished_at` (all already serialised by the API).
- Produces: nothing consumed by later tasks.

**Why:** Two defects with one cause — the UI has the information and discards it. `JobOut.error` is selected, typed and returned, but the journal renders only a colour dot, stage name and timestamp; a red "failed" badge never says why. And no query sets `refetchInterval`, so after the 1.2 s post-upload redirect the user watches a static "processing" pill forever with no way to tell working from stranded.

- [ ] **Step 1: Write the failing tests**

```tsx
// append to frontend/src/features/documents/DocumentDrawer.test.tsx
describe('DocumentDrawer — failure visibility', () => {
  it('renders the journal error reason for a failed stage', async () => {
    renderDrawer({
      jobs: [
        { stage: 'scan', state: 'succeeded', error: null, attempts: 1,
          started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:01Z' },
        { stage: 'extract', state: 'failed', error: 'unsupported or malformed content',
          attempts: 1, started_at: '2026-08-31T10:00:01Z', finished_at: '2026-08-31T10:00:02Z' },
      ],
    });
    expect(await screen.findByText('unsupported or malformed content')).toBeInTheDocument();
  });

  it('shows the attempt count when a stage was retried', async () => {
    renderDrawer({
      jobs: [{ stage: 'scan', state: 'failed', error: 'transient failure in scan; retries exhausted',
               attempts: 3, started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:05Z' }],
    });
    expect(await screen.findByText(/3 attempts/i)).toBeInTheDocument();
  });

  it('does not render an error row for a clean journal', async () => {
    renderDrawer({
      jobs: [{ stage: 'scan', state: 'succeeded', error: null, attempts: 1,
               started_at: '2026-08-31T10:00:00Z', finished_at: '2026-08-31T10:00:01Z' }],
    });
    expect(screen.queryByTestId('job-error')).not.toBeInTheDocument();
  });
});
```

Match `renderDrawer` to the helper the existing tests in this file already use; if they build props inline, follow that shape instead.

- [ ] **Step 2: Run to verify they fail**

Run: `npm run test -- DocumentDrawer`
Expected: FAIL — the error text is not in the document.

- [ ] **Step 3: Render the reason and attempts**

In `DocumentDrawer.tsx`, inside the journal row map (around line 357-388), after the stage name and state, add:

```tsx
{j.error && (
  <p
    data-testid="job-error"
    className="mt-1 text-[11px] text-[#cf222e] dark:text-[#f85149] break-words"
  >
    {j.error}
  </p>
)}
{j.attempts > 1 && (
  <span className="text-[10px] text-[#656d76] dark:text-[#848d97]">
    {j.attempts} attempts
  </span>
)}
```

Confirm `error` and `attempts` exist on the job type in `frontend/src/api/types.ts`; add them if the type omits them.

- [ ] **Step 4: Poll while a document is non-terminal**

In `DocumentDrawer.tsx`, give the document and jobs queries a conditional interval:

```tsx
const TERMINAL_STATUSES = ['ready', 'failed', 'held'] as const;

const isTerminal = (status: string | undefined): boolean =>
  status !== undefined && (TERMINAL_STATUSES as readonly string[]).includes(status);

// ...in each useQuery for the document and its jobs:
  refetchInterval: (query) =>
    isTerminal(query.state.data?.status) ? false : 3000,
```

Apply the same pattern in `DocumentsPage.tsx`: poll the list every 5 s while any row is non-terminal, and stop once all are terminal. Do not poll unconditionally — a settled list must go quiet.

- [ ] **Step 5: Run the tests**

Run: `npm run typecheck && npm run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/documents/ frontend/src/api/types.ts
git commit -m "fix(ui): show the pipeline failure reason and poll while processing

processing_jobs.error was fetched, typed and returned, then discarded by the
renderer, so a red 'failed' badge never said why. Nothing polled either, so the
user watched a static 'processing' pill with no way to tell working from stuck."
```

---

## Task 16: Make the upload XHR always settle, and cancellable

**Files:**
- Modify: `frontend/src/api/client.ts:212-251` (`putDirect`)
- Modify: `frontend/src/features/upload/UploadPage.tsx`
- Test: `frontend/src/api/client.test.ts` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `putDirect(url, file, contentType, onProgress?, signal?: AbortSignal)`.

**Why:** `putDirect` wires `onload` and `onerror` only — no `timeout`, `ontimeout`, `onabort`, `AbortController`. An aborted transfer (tab throttling, proxy teardown) leaves the promise permanently unsettled: `uploadStage` stays `'uploading'`, the submit button stays disabled, and no error ever appears. There is also no way to cancel a 100 MB transfer started by mistake.

- [ ] **Step 1: Write the failing tests**

```ts
// append to frontend/src/api/client.test.ts
describe('putDirect — settlement', () => {
  it('rejects when the transfer is aborted', async () => {
    const controller = new AbortController();
    const promise = api.putDirect('http://storage/x', new Blob(['x']), 'text/plain', undefined, controller.signal);
    controller.abort();
    await expect(promise).rejects.toThrow(/cancell?ed/i);
  });

  it('rejects when the transfer times out', async () => {
    // MockXhr is the harness this file already uses for putDirect tests.
    const promise = api.putDirect('http://storage/x', new Blob(['x']), 'text/plain');
    MockXhr.last.triggerTimeout();
    await expect(promise).rejects.toThrow(/timed out/i);
  });

  it('sets a non-zero timeout so a stalled transfer cannot hang forever', () => {
    void api.putDirect('http://storage/x', new Blob(['x']), 'text/plain');
    expect(MockXhr.last.timeout).toBeGreaterThan(0);
  });
});
```

Read the existing `client.test.ts` first and reuse whatever XHR stub it already installs; if there is none, add a minimal one rather than pulling in a mocking library.

- [ ] **Step 2: Run to verify they fail**

Run: `npm run test -- client`
Expected: FAIL — `putDirect` takes 4 arguments and never settles on abort.

- [ ] **Step 3: Add timeout, abort and cancellation**

In `frontend/src/api/client.ts`, replace the body of `putDirect`:

```ts
  putDirect: async (
    url: string,
    file: Blob | ArrayBuffer,
    contentType: string,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url, true);
      // Invariant #1: the bytes go browser -> object storage. No Authorization
      // header and no cookies are attached here — the presigned URL IS the
      // credential, and adding a second one would leak the session to the
      // storage host and break the signature on strict S3 implementations.
      xhr.withCredentials = false;
      xhr.setRequestHeader('Content-Type', contentType);
      // Without a timeout an XHR that is torn down (tab throttling, a proxy
      // dropping the socket) fires no event at all: the promise never settles,
      // the submit button stays disabled, and the user sees no error ever.
      xhr.timeout = UPLOAD_TIMEOUT_MS;

      const detach = () => signal?.removeEventListener('abort', onAbort);
      const onAbort = () => xhr.abort();

      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            onProgress(Math.round((e.loaded / e.total) * 100));
          }
        };
      }

      xhr.onload = () => {
        detach();
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new ApiError(xhr.status, `Storage upload failed with status ${xhr.status}`));
        }
      };
      xhr.onerror = () => {
        detach();
        reject(new ApiError(0, 'Storage upload network error'));
      };
      xhr.ontimeout = () => {
        detach();
        reject(new ApiError(0, 'Storage upload timed out'));
      };
      xhr.onabort = () => {
        detach();
        reject(new ApiError(0, 'Upload cancelled'));
      };

      if (signal?.aborted) {
        reject(new ApiError(0, 'Upload cancelled'));
        return;
      }
      signal?.addEventListener('abort', onAbort, { once: true });
      xhr.send(file instanceof Blob ? file : new Blob([file]));
    });
  },
```

Define near the top of the file:

```ts
// Generous: a 100 MiB upload on a slow link is legitimate. This exists to bound
// a transfer that has stopped making progress, not to police slow ones.
const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;
```

- [ ] **Step 4: Wire a cancel button**

In `UploadPage.tsx`, hold an `AbortController` in a ref for the active upload, pass its `signal` to `putDirect`, and render a Cancel button while `uploadStage === 'uploading'` that calls `controller.abort()`. In the existing catch-all that resets to `idle`, show "Upload cancelled" rather than an error for the abort case.

- [ ] **Step 5: Run the tests**

Run: `npm run typecheck && npm run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/features/upload/UploadPage.tsx
git commit -m "fix(upload): make putDirect always settle, and add cancellation

The XHR wired only onload/onerror, so an aborted transfer left the promise
pending forever with the submit button disabled and no error shown. Add a
timeout, abort/timeout handlers, AbortSignal support and a Cancel button."
```

---

## Task 17: Correct the upload form and remove the decorative chrome

**Files:**
- Modify: `frontend/src/features/upload/UploadPage.tsx:161-179`, `:186`, `:198`, `:205`
- Modify: `frontend/src/components/layout/Navbar.tsx:16-40`
- Modify: `backend/app/extraction/sniff.py:45-53`
- Test: `frontend/src/features/upload/UploadPage.test.tsx` (extend), `backend/tests/extraction/test_sniff.py` (extend)

**Interfaces:**
- Consumes: `MIME_TEXT` (already exported from `sniff.py`).
- Produces: nothing consumed by later tasks.

**Why:** Three unrelated-looking corrections that are all "the UI says something untrue". The "Target Department UUID" input is `required`, is seeded from the persona, and is **never sent** — the server uses the token's `department_id`, so editing it silently does nothing and an empty persona department blocks submission entirely. `.txt` is fully supported by the backend but absent from the picker. And you asked for the version pill, tagline and "Airgapped & Self-Hosted" badge to go.

`_is_plain_text` is folded in here because it is the same file as the `.txt` work: it decodes the *entire* payload to answer a boolean (100 MB allocated twice) and its NUL guard only inspects the first 1 KiB.

- [ ] **Step 1: Write the failing tests**

```tsx
// append to frontend/src/features/upload/UploadPage.test.tsx
it('does not render a department input', () => {
  render(<UploadPage />, { wrapper });
  expect(screen.queryByLabelText(/department/i)).not.toBeInTheDocument();
});

it('accepts .txt in the file picker', () => {
  render(<UploadPage />, { wrapper });
  const input = screen.getByTestId('file-input') as HTMLInputElement;
  expect(input.accept).toContain('.txt');
});
```

```python
# append to backend/tests/extraction/test_sniff.py
def test_plain_text_check_does_not_decode_the_whole_payload() -> None:
    """A 100 MiB object must not be fully decoded to answer a boolean."""
    from app.extraction.sniff import _is_plain_text

    payload = b"a" * (8 * 1024 * 1024)
    assert _is_plain_text(payload) is True


def test_binary_with_late_nul_bytes_is_not_plain_text() -> None:
    """The NUL guard inspected only the first 1 KiB, so late NULs slipped past."""
    from app.extraction.sniff import _is_plain_text

    assert _is_plain_text(b"a" * 4096 + b"\x00" + b"a" * 16) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm run test -- UploadPage` and `.venv/Scripts/python.exe -m pytest tests/extraction/test_sniff.py -v`
Expected: the department test FAILS (the input exists), the `.txt` test FAILS, and the late-NUL test FAILS.

- [ ] **Step 3: Remove the department field**

Delete the "Target Department UUID" form group from `UploadPage.tsx:161-179` and the persona-sync effect at `:38-42` that seeds it, plus the now-unused state. Do not add it to the request — the server derives the department from the token, and sending a client-chosen one would be an access-control decision made by the client.

- [ ] **Step 4: Add `.txt` to the picker**

At `UploadPage.tsx:198` extend `accept` to include `.txt`; at `:186` change the label to `Document File (.pdf, .docx, .xlsx, .txt)`; at `:205` change the helper text to `PDF, DOCX, XLSX, or TXT up to 100 MiB`.

- [ ] **Step 5: Bound the plain-text check**

In `backend/app/extraction/sniff.py`:

```python
# Enough to classify, small enough not to allocate a second copy of a 100 MiB
# object just to answer a boolean.
_TEXT_PROBE_BYTES: Final = 64 * 1024


def _is_plain_text(data: bytes) -> bool:
    """Whether ``data`` looks like clean printable/whitespace text.

    Decides on a bounded prefix. The previous version decoded the entire
    payload and only checked the first 1 KiB for NUL bytes, so it both
    allocated a full second copy and missed binaries whose NULs start later.
    """
    if not data:
        return False
    probe = data[:_TEXT_PROBE_BYTES]
    if b"\x00" in probe:
        return False
    try:
        probe.decode("utf-8")
    except UnicodeDecodeError:
        # A multi-byte character may straddle the probe boundary; retry one
        # character short before concluding the bytes are not text.
        try:
            probe[:-4].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True
```

- [ ] **Step 6: Strip the navbar chrome**

In `frontend/src/components/layout/Navbar.tsx`, remove the `v1.0` `<span>`, the `Self-Hosted Classification & Multi-Tenant Access Control` `<p>`, and the whole "Airgapped & Self-Hosted" `<div>`. Drop `Sparkles` from the `lucide-react` import (keep `Shield`). Keep the `ThemeToggle` and the `devPersonasEnabled` switcher exactly as they are.

- [ ] **Step 7: Run the tests**

Run: `npm run typecheck && npm run test`, then `.venv/Scripts/python.exe -m pytest tests/extraction -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/upload/UploadPage.tsx frontend/src/features/upload/UploadPage.test.tsx frontend/src/components/layout/Navbar.tsx backend/app/extraction/sniff.py backend/tests/extraction/test_sniff.py
git commit -m "fix(ui): drop the decorative department field and chrome; accept .txt

The department input was required, seeded and never sent — the server uses the
token's department — so editing it did nothing and an empty persona blocked
submission. .txt is fully supported by the backend but was missing from the
picker. Also bound _is_plain_text's probe: it decoded the entire payload and
its NUL guard covered only the first 1 KiB."
```

---

## Task 18: Persist the reclassification justification

**Files:**
- Modify: `backend/app/api/v1/documents.py:164-166` (`ReclassifyRequest`), `:946-988`
- Test: `backend/tests/api/test_reclassify_justification.py` (create)

**Interfaces:**
- Consumes: `deps.record_audit(session, ..., action=...)`.
- Produces: `ReclassifyRequest.justification: str | None`.

**Why:** `ReclassifyModal.tsx` gates the downgrade button on a sufficient justification and sends it; `ReclassifyRequest` does not model the field, so Pydantic discards it and it is never persisted. The UI enforces a justification that goes nowhere — and invariant #8 requires that a human lowering a label is audited.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_reclassify_justification.py
"""#8: a human lowering a label is audited — including why.

The modal requires a justification and sends it; the request model dropped it.
"""

from __future__ import annotations


def test_justification_reaches_the_audit_row(client_factory, journal) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_ready_document(role="admin")
    client.post(
        f"/v1/documents/{doc_id}/classification",
        json={
            "level_name": "internal",
            "doc_type_id": None,
            "justification": "Reviewed with legal; contains no client identifiers.",
        },
    )
    entry = journal.entries[-1]
    assert entry.action == "reclassify.human"
    assert "Reviewed with legal" in (entry.detail or "")


def test_justification_is_optional_when_not_lowering(client_factory) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_ready_document(role="admin")
    response = client.post(
        f"/v1/documents/{doc_id}/classification",
        json={"level_name": "restricted", "doc_type_id": None},
    )
    assert response.status_code == 200


def test_overlong_justification_is_rejected(client_factory) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_ready_document(role="admin")
    response = client.post(
        f"/v1/documents/{doc_id}/classification",
        json={"level_name": "internal", "doc_type_id": None, "justification": "x" * 5000},
    )
    assert response.status_code == 422
```

Use the existing `journal` fixture from `tests/api/conftest.py` (it already spies on `deps.record_audit`). If `record_audit` has no free-text column, check `AccessLog`'s columns first — if there is genuinely nowhere to put it, add the column in a new migration and say so in the commit.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_reclassify_justification.py -v`
Expected: FAIL — the justification is absent from the audit entry.

- [ ] **Step 3: Model the field**

In `backend/app/api/v1/documents.py`:

```python
class ReclassifyRequest(BaseModel):
    level_name: LevelName
    doc_type_id: uuid.UUID | None = None
    # #8: a human lowering a label is audited. The modal already requires this
    # and sends it; the model dropped it silently, so the requirement the UI
    # enforced reached nothing.
    justification: str | None = Field(default=None, max_length=2000)
```

- [ ] **Step 4: Persist it**

In `reclassify_document`, pass the justification into the audit write in the same transaction as the classification insert (invariant #30):

```python
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=doc.id,
            actor_id=actor_id,
            action="reclassify.human",
            request=request,
            detail=payload.justification,
        )
```

Add a `detail: str | None = None` parameter to `deps.record_audit` and a corresponding nullable `detail` column on `access_log` via a new alembic migration. The migration must be reversible, and must not grant the app role `UPDATE`/`DELETE` on `access_log` (invariant #24).

- [ ] **Step 5: Remove the stale comment in the modal**

`ReclassifyModal.tsx:58-63` carries a comment explaining that the justification is dropped. Delete it — it is no longer true.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest -q` and `cd ../frontend && npm run test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/documents.py backend/app/api/deps.py backend/alembic/versions/ backend/tests/api/test_reclassify_justification.py frontend/src/features/documents/ReclassifyModal.tsx
git commit -m "fix(review): persist the reclassification justification (#8)

The modal gated the downgrade button on a justification and sent it; the
request model did not declare the field, so Pydantic discarded it. Model it,
add a nullable access_log.detail column, and write it in the same transaction
as the classification (#30)."
```

---

## Task 19: Verify end to end and update the docs

**Files:**
- Modify: `README.md`, `PROGRESS.md`, `backend/README.md`, `AGENTS.md`
- Test: full gate run

**Interfaces:**
- Consumes: everything above.
- Produces: a verified, documented baseline for Plan 2 (features).

- [ ] **Step 1: Run every gate and record the real output**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy app
.venv/Scripts/python.exe -m pytest -q
cd ../frontend && npm run typecheck && npm run test && npm run build
```

Record the verbatim tails. Do not claim a gate passed that you did not run.

- [ ] **Step 2: Rebuild and run the integration suite against live infra**

```bash
docker compose build && docker compose up -d
cd backend && CLAMAV_HOST=localhost .venv/Scripts/python.exe -m pytest -m integration -v
```

- [ ] **Step 3: Manually verify the reported symptoms are gone**

Walk the browser flow and confirm each:
1. Upload a PDF — it reaches `ready` without a manual refresh (Task 15 polling).
2. Click a ready document — "Open in Browser" renders it, "Download" saves it (Tasks 1, 2).
3. Upload an unsupported file (e.g. a `.pptx`) — it reaches `failed` **with a visible reason** (Tasks 3, 15).
4. Set Status to "Failed" — only failed rows are listed (Task 13).
5. Open a document mid-processing — the drawer says "still processing", not 404 (Task 14).
6. The navbar has no version pill, tagline or airgapped badge (Task 17).

- [ ] **Step 4: Reprocess or retire the stranded rows**

The two documents currently pinned at `processing` with `blob_sha256 = NULL` predate these fixes and will never self-heal — the fixes are forward-only. Either re-upload them and soft-delete the originals, or write a one-off script that re-enqueues their chains. Do not write an unscoped `UPDATE`; scope any statement by explicit document id.

- [ ] **Step 5: Update the documentation**

- `README.md`: correct the invariant matrix rows for #4 (the journal is now exhaustive), #17 (uploads have their own TTL) and #31 (the 409 not-ready branch and why it does not breach parity). Add `/view` and `/preview` to the endpoint list. Add a deviations-ledger entry for `held` as the terminal OCR state.
- `PROGRESS.md`: add a Wave 8 row summarising these repairs, replace the verification-gate block with the real output from Step 1, and add to the Phase-2 backlog: real OCR, the orphaned-intent sweeper, and worker memory tuning.
- `backend/README.md`: document `DOCMGMT_LOCAL_STORAGE_ROOT` and `UPLOAD_PRESIGN_TTL_SECONDS`, and the `docker/clamav/clamd.conf` mount.
- `AGENTS.md`: add `docker/clamav/` to the repository layout.

Be accurate about what is and is not fixed. OCR is still unimplemented; say so.

- [ ] **Step 6: Commit**

```bash
git add README.md PROGRESS.md backend/README.md AGENTS.md
git commit -m "docs: record the Phase 1 repairs and correct the invariant matrix

Wave 8: exhaustive stage failure taxonomy (#4), journal timestamps, upload
integrity checks, server-side filters, and the 409 not-ready branch. Phase-2
backlog updated: OCR, orphan sweeper, and worker memory tuning remain open."
```

---

## Plan Self-Review

**Spec coverage.** Every Phase 0 and Phase 1 item in the spec maps to a task: P0-1 → Task 1, P0-2 → Task 2, F1 → 3, F2 → 4, F3 → 5, F4 → 6, F5 → 7, F6 → 8, F7 → 9, F8 → 10, F9 → 11, F11 → 12, F12 → 13, F15 → 14, F13/F14 → 15, F10 → 16, F16/F17 + chrome → 17, F18 → 18, docs → 19. Spec sections 6 (features) and 7 (Playwright) are deliberately out of scope for this plan and are covered by Plan 2 and Plan 3.

**Known follow-ups this plan creates.**
- Task 9 changes the upload wire format from PUT to presigned POST when `storage_backend == "minio"`. If the executor takes the gated option, the dev (local) path keeps PUT and the two paths differ — Plan 3's Playwright suite must exercise whichever is configured.
- Task 18 adds an `access_log.detail` column. Confirm against invariant #24 that the migration grants no `UPDATE`/`DELETE` to `docmgmt_app`.
- Task 12's `clamp_upload_presign_ttl` is referenced by Task 9. If Task 9 lands first, it uses `clamp_presign_ttl` and Task 12 switches it — do not leave both.

**Type consistency.** `ObjectStat` (Task 8) is used only in Task 8. `PresignedUpload` (Task 9) is consumed by the frontend client in the same task. `mark_document_held` (Task 7) matches `mark_document_failed`'s existing signature shape (`sessions` positional, `document_id` keyword-only). `attempt_is_final` (Task 5) is keyword-only in both the signature and every call site. `_fetch_document_page`'s new `status` / `level` keywords (Task 13) match the names asserted in its test.
