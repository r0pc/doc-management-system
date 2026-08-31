"""A transient failure that exhausts its retries must not leave 'processing'."""

from __future__ import annotations

import uuid

import pytest

from app.workers import tasks
from app.workers.tasks import TransientStorageError


class _Journal:
    def __init__(self) -> None:
        self.job_id = uuid.uuid4()
        self.terminal: tuple[str, str] | None = None

    def mark_running(self, *a, **k):
        return self.job_id

    def mark_succeeded(self, *a, **k) -> None: ...
    def mark_failed(self, job_row_id, error) -> None:
        self.terminal = ("failed", error)

    def mark_skipped(self, *a, **k) -> None: ...


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


def test_non_final_attempt_leaves_document_processing(wired) -> None:
    journal, marked = wired
    ctx = _ctx()
    with pytest.raises(TransientStorageError):
        tasks._run_stage("scan", ctx, _boom, attempt_is_final=False)
    assert journal.terminal == ("failed", "transient failure in scan; retry scheduled")
    assert marked == [], "a retry is still coming; do not flip the document yet"


def test_final_attempt_marks_document_failed(wired) -> None:
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
