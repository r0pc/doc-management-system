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

    def mark_running(self, document_id, version_id, stage):
        return self.job_id

    def mark_succeeded(self, job_row_id):
        self.terminal = ("succeeded", "")

    def mark_failed(self, job_row_id, error):
        self.terminal = ("failed", error)

    def mark_skipped(self, job_row_id, reason):
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
    secret = "CNIC 61101-1234567-8 of Ayesha Khan"  # noqa: S105 - synthetic document text, not a credential

    def body() -> None:
        raise RuntimeError(secret)

    with pytest.raises(RuntimeError):
        tasks._run_stage("extract", ctx, body)

    assert journal.terminal is not None
    assert secret not in journal.terminal[1], "exception text leaked into the journal"
