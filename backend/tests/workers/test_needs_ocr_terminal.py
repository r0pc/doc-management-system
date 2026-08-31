"""A PDF needing OCR must reach a terminal state, not hang at 'processing'.

Real OCR is out of scope (no tesseract worker exists). 'held' is an allowed
documents.status value and means "stopped, awaiting a capability we lack".
"""

from __future__ import annotations

import uuid

import pytest

from app.extraction.base import NeedsOcrError
from app.workers import tasks


class _Journal:
    def __init__(self) -> None:
        self.job_id = uuid.uuid4()
        self.terminal: tuple[str, str] | None = None

    def mark_running(self, *a, **k):
        return self.job_id

    def mark_succeeded(self, *a, **k) -> None: ...
    def mark_failed(self, job_row_id, error) -> None:
        self.terminal = ("failed", error)

    def mark_skipped(self, job_row_id, reason) -> None:
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
