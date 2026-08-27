"""Worker-suite fixtures: eager Celery, real LocalStorage, recording doubles.

Unit scope only: orchestration semantics are asserted against recording fakes
injected by monkeypatching task internals. Real-DB coverage of the SQL helpers
lives in the Wave 5 e2e suite (PG-specific types rule out sqlite here).
"""

import hashlib
import io
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.storage.local import LocalStorage
from app.workers import tasks
from app.workers.celery_app import celery_app

SECRET = b"worker-test-signing-key"
DOC_ID = uuid.UUID(int=0x11)
VER_ID = uuid.UUID(int=0x22)
TENANT_ID = uuid.UUID(int=0x33)
# Minimal PDF-magic payload: promotion sniffs MIME (#19), so test bytes must
# carry a signature puremagic recognises even though extraction is faked.
PAYLOAD = b"%PDF-1.4\n% quarantined-document-bytes\n%%EOF\n"
SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def make_ctx(key: str) -> dict[str, str]:
    """Canonical broker ctx dict (ids as strings; no text payloads)."""
    return {
        "document_id": str(DOC_ID),
        "version_id": str(VER_ID),
        "tenant_id": str(TENANT_ID),
        "sha256": SHA256,
        "bucket": "docs-quarantine",
        "key": key,
    }


class RecordingJournal:
    """In-memory double of app.workers.jobs.JobsJournal; records every write."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []  # (event, stage, detail)
        self._succeeded: set[tuple[str, str]] = set()
        self._jobs: dict[uuid.UUID, tuple[str, str]] = {}

    def stages_in_state(self, state: str) -> list[str]:
        return [stage for event, stage, _ in self.events if event == state]

    def skip_reasons(self) -> dict[str, str]:
        return {stage: detail for event, stage, detail in self.events if event == "skipped"}

    def failures(self) -> dict[str, str]:
        return {stage: detail for event, stage, detail in self.events if event == "failed"}

    def succeed(self, version_id: str, stage: str) -> None:
        """Preset a stage as already succeeded (mid-chain retry simulation)."""
        self._succeeded.add((str(version_id), stage))

    def has_succeeded(self, version_id: str | uuid.UUID, stage: str) -> bool:
        return (str(version_id), stage) in self._succeeded

    def mark_queued(self, version_id: str | uuid.UUID, stage: str) -> uuid.UUID:
        self.events.append(("queued", stage, ""))
        return uuid.uuid4()

    def mark_running(
        self, document_id: str | uuid.UUID, version_id: str | uuid.UUID, stage: str
    ) -> uuid.UUID:
        job_row_id = uuid.uuid4()
        self._jobs[job_row_id] = (str(version_id), stage)
        self.events.append(("running", stage, ""))
        return job_row_id

    def mark_succeeded(self, job_row_id: uuid.UUID) -> None:
        version_id, stage = self._jobs[job_row_id]
        self._succeeded.add((version_id, stage))
        self._log_terminal("succeeded")

    def mark_failed(self, job_row_id: uuid.UUID, error: str) -> None:
        self.events.append(("failed", self._last_running_stage(), error))

    def mark_skipped(self, job_row_id: uuid.UUID, reason: str) -> None:
        self.events.append(("skipped", self._last_running_stage(), reason))

    def _last_running_stage(self) -> str:
        running = [stage for event, stage, _ in self.events if event == "running"]
        if not running:
            msg = "mark_skipped/mark_failed without a prior mark_running"
            raise AssertionError(msg)
        return running[-1]

    def _log_terminal(self, state: str) -> None:
        self.events.append((state, self._last_running_stage(), ""))


class FakePipelineStore:
    """Recording replacement for the tasks-bound persistence helpers.

    Method names mirror the helper names imported into ``app.workers.tasks`` so
    ``install`` can swap them in one loop. ``record_classification`` mimics the
    real SELECT-before-INSERT get-or-create contract so tests can count actual
    inserts across repeated classify runs.
    """

    def __init__(self) -> None:
        self.loaded_contexts: list[uuid.UUID] = []
        self.promotions: list[dict[str, object]] = []
        self.keyword_writes: list[list[tuple[str, float]]] = []
        self.classification_inserts: list[dict[str, object]] = []
        self._classification_index: dict[tuple[str, str], uuid.UUID] = {}
        self.text_upserts: list[dict[str, object]] = []
        self.ready_documents: list[uuid.UUID] = []
        self.failed_documents: list[uuid.UUID] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "load_version_context",
            "promote_blob_record",
            "replace_keywords",
            "record_classification",
            "upsert_document_text",
            "mark_document_ready",
            "mark_document_failed",
        ):
            monkeypatch.setattr(tasks, name, getattr(self, name))

    def load_version_context(
        self, sessions: object, document_id: uuid.UUID, version_id: uuid.UUID
    ) -> tuple[uuid.UUID, str]:
        self.loaded_contexts.append(version_id)
        return TENANT_ID, SHA256

    def promote_blob_record(self, sessions: object, **kwargs: object) -> None:
        self.promotions.append(kwargs)

    def replace_keywords(
        self, sessions: object, *, document_id: object, terms: list[tuple[str, float]]
    ) -> int:
        self.keyword_writes.append(list(terms))
        return len(terms)

    def record_classification(self, sessions: object, **kwargs: object) -> uuid.UUID:
        key = (str(kwargs["document_id"]), str(kwargs["version_id"]))
        existing = self._classification_index.get(key)
        if existing is not None:
            return existing
        row_id = uuid.uuid4()
        self._classification_index[key] = row_id
        self.classification_inserts.append(dict(kwargs))
        return row_id

    def upsert_document_text(self, sessions: object, **kwargs: object) -> None:
        self.text_upserts.append(dict(kwargs))

    def mark_document_ready(self, sessions: object, document_id: uuid.UUID) -> None:
        self.ready_documents.append(document_id)

    def mark_document_failed(self, sessions: object, *, document_id: uuid.UUID) -> None:
        self.failed_documents.append(document_id)


@pytest.fixture
def eager_celery() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True
    celery_app.conf.task_eager_propagates = True


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage", signing_secret=SECRET)


@pytest.fixture
def journal() -> RecordingJournal:
    return RecordingJournal()


@pytest.fixture
def store() -> FakePipelineStore:
    return FakePipelineStore()


@pytest.fixture
def pipeline(
    monkeypatch: pytest.MonkeyPatch,
    eager_celery: None,
    storage: LocalStorage,
    journal: RecordingJournal,
    store: FakePipelineStore,
) -> SimpleNamespace:
    """Wire every task seam to recording doubles; settings default scan-on dev."""
    store.install(monkeypatch)
    monkeypatch.setattr(
        tasks, "_settings",
        lambda: Settings(
            env="dev", scan_enabled=True,
            dev_jwt_secret="test-secret-for-tests",  # noqa: S106
        ),
    )
    monkeypatch.setattr(tasks, "_storage", lambda: storage)
    monkeypatch.setattr(tasks, "_journal", lambda: journal)
    return SimpleNamespace(storage=storage, journal=journal, store=store)


def seed_quarantine(storage: LocalStorage, key: str, data: bytes) -> None:
    storage.put(key, io.BytesIO(data), content_type="application/octet-stream")


def quarantine_key_fixture() -> str:
    return f"docs-quarantine/{TENANT_ID}/{DOC_ID}"


@pytest.fixture
def caplog_info(caplog: pytest.LogCaptureFixture) -> Callable[[str], list[logging.LogRecord]]:
    def _records(fragment: str) -> list[logging.LogRecord]:
        return [r for r in caplog.records if fragment in r.getMessage()]

    return _records
