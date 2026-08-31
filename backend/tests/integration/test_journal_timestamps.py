"""started_at/finished_at must be written; a hung stage is otherwise invisible.

Requires live PostgreSQL: ``ProcessingJobsJournal`` issues PG-specific SQL
(via ``sync_sessions``/``seeded_version`` from ``tests/integration/conftest.py``)
that has no hermetic sqlite equivalent, so this lives here rather than in
``tests/workers/``.
"""

from __future__ import annotations

import uuid

import pytest

from app.workers.jobs import ProcessingJobsJournal

pytestmark = [pytest.mark.integration]


@pytest.fixture
def journal(sync_sessions) -> ProcessingJobsJournal:
    return ProcessingJobsJournal(sync_sessions)


def _job(sync_sessions, job_id: uuid.UUID):
    from app.db.models import ProcessingJob

    with sync_sessions() as session:
        return session.get(ProcessingJob, job_id)


def test_mark_running_sets_started_at(sync_sessions, journal, seeded_version) -> None:
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
) -> None:
    job_id = journal.mark_running(seeded_version.document_id, seeded_version.id, "extract")
    getattr(journal, method)(job_id, *args)
    row = _job(sync_sessions, job_id)
    assert row.finished_at is not None
    assert row.started_at is not None
    assert row.finished_at >= row.started_at


def test_mark_running_clears_stale_finished_at(sync_sessions, journal, seeded_version) -> None:
    """A retried stage must not read as complete while running (re-entry case)."""
    job_id = journal.mark_running(seeded_version.document_id, seeded_version.id, "extract")
    journal.mark_failed(job_id, "boom")
    row = _job(sync_sessions, job_id)
    assert row.finished_at is not None

    journal.mark_running(seeded_version.document_id, seeded_version.id, "extract")
    row = _job(sync_sessions, job_id)
    assert row.finished_at is None
    assert row.started_at is not None
