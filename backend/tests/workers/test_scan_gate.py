"""Scan gate: dev fail-open with loud journal + warning; prod fail-closed; verdicts."""

import pytest

from app.config import Settings
from app.extraction.base import ExtractedDocument, PageText
from app.workers import tasks
from app.workers.scanning import ScanVerdict
from tests.workers.conftest import (
    DOC_ID,
    PAYLOAD,
    VER_ID,
    quarantine_key_fixture,
    seed_quarantine,
)


def _wire_extraction(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def fake_extract(data: bytes) -> ExtractedDocument:
        calls.append("extract")
        return ExtractedDocument(
            text="body",
            pages=[PageText(page_no=1, text="body")],
            mime_sniffed="application/pdf",
            char_count=4,
            ocr_used=False,
        )

    monkeypatch.setattr(tasks, "extract_document", fake_extract)


def test_gate_off_in_dev_journals_skipped_and_continues(pipeline, monkeypatch, caplog) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    calls: list[str] = []
    _wire_extraction(monkeypatch, calls)
    monkeypatch.setattr(tasks, "_settings", lambda: Settings(env="dev", scan_enabled=False))

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert pipeline.journal.skip_reasons() == {"scan": "clamav_unavailable"}
    assert "clamav" in caplog.text.lower()
    assert calls == ["extract"]  # chain continued past the skipped scan stage


def test_gate_off_outside_dev_fails_closed(pipeline, monkeypatch) -> None:
    """D3: validate_runtime blocks prod startup with scan off; if config drifts
    post-startup the stage itself must refuse to continue unscanned."""
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    monkeypatch.setattr(tasks, "_settings", lambda: Settings(env="prod", scan_enabled=False))

    with pytest.raises(RuntimeError):
        tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert "scan" in pipeline.journal.stages_in_state("failed")


def test_infected_verdict_fails_stage_and_keeps_quarantine(pipeline, monkeypatch) -> None:
    from app.workers.tasks import MalwareDetectedError

    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    monkeypatch.setattr(
        tasks,
        "clamd_scan",
        lambda *a, **kw: ScanVerdict(clean=False, signature="Eicar-Test-Signature"),
    )

    with pytest.raises(MalwareDetectedError):
        tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    failures = pipeline.journal.failures()
    assert "Eicar-Test-Signature" in failures["scan"]
    assert "index" not in pipeline.journal.stages_in_state("running")
    with pipeline.storage.open(key) as handle:  # upload stays quarantined
        assert handle.read() == PAYLOAD


def test_clean_verdict_marks_scan_succeeded(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _wire_extraction(monkeypatch, [])
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert "scan" in pipeline.journal.stages_in_state("succeeded")


def test_clamav_socket_failure_is_transient_and_journaled(pipeline, monkeypatch) -> None:
    from celery.exceptions import Retry

    from app.workers.scanning import ScanError

    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)

    def down(*a: object, **kw: object) -> ScanVerdict:
        raise ScanError("clamd unreachable")

    monkeypatch.setattr(tasks, "clamd_scan", down)

    # Eager mode surfaces autoretry_for as celery.exceptions.Retry; the journal
    # must already record the failed attempt the retry will follow.
    with pytest.raises(Retry):
        tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert "scan" in pipeline.journal.stages_in_state("failed")
