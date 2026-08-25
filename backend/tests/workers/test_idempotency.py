"""Idempotency (#5): state-based guards make mid-chain retries duplicate nothing."""

from app.workers import tasks
from app.workers.scanning import ScanVerdict
from tests.workers.conftest import (
    DOC_ID,
    PAYLOAD,
    VER_ID,
    make_ctx,
    quarantine_key_fixture,
    seed_quarantine,
)


def _wire_happy_chain(monkeypatch, pipeline) -> None:
    from app.extraction.base import ExtractedDocument, PageText

    monkeypatch.setattr(
        tasks,
        "extract_document",
        lambda data: ExtractedDocument(
            text="body text",
            pages=[PageText(page_no=1, text="body text")],
            mime_sniffed="application/pdf",
            char_count=9,
            ocr_used=False,
        ),
    )
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )


def test_succeeded_stage_short_circuits_without_reexecution(pipeline, monkeypatch) -> None:
    pipeline.journal.succeed(VER_ID, "extract")
    calls: list[bytes] = []

    def counting_extract(data: bytes) -> object:
        calls.append(data)
        raise AssertionError("must not re-extract")

    monkeypatch.setattr(tasks, "extract_document", counting_extract)

    ctx = make_ctx(quarantine_key_fixture())
    result = tasks.extract_text(ctx)

    assert result == ctx
    assert calls == []
    assert "running" not in [
        stage for event, stage, _ in pipeline.journal.events if event == "running"
    ]


def test_classify_twice_inserts_exactly_one_classification(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _wire_happy_chain(monkeypatch, pipeline)

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)
    first_count = len(pipeline.store.classification_inserts)

    # Simulate a mid-chain retry of the classify stage on a fresh journal view:
    # the state guard (has_succeeded) must short-circuit before any SQL runs.
    tasks.classify(make_ctx(key))

    assert first_count == 1
    assert len(pipeline.store.classification_inserts) == 1  # no second insert


def test_keywords_rerun_replaces_rows_instead_of_duplicating(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _wire_happy_chain(monkeypatch, pipeline)

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    # Force a second execution past the guard (retry that lost its journal read):
    pipeline.journal._succeeded.discard((str(VER_ID), "keywords"))
    tasks.extract_keywords(make_ctx(key))

    assert len(pipeline.store.keyword_writes) == 2
    assert pipeline.store.keyword_writes[0] == pipeline.store.keyword_writes[1]


def test_guard_is_state_based_not_offset_based(pipeline) -> None:
    """#5: the guard answers from processing_jobs.state, never from counters."""
    pipeline.journal.succeed(VER_ID, "classify")
    assert pipeline.journal.has_succeeded(VER_ID, "classify") is True
    assert pipeline.journal.has_succeeded(VER_ID, "index") is False


def test_sha256_mismatch_between_quarantine_and_ctx_fails_stage(pipeline, monkeypatch) -> None:
    from app.workers.tasks import ShaMismatchError

    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, b"different-bytes-entirely")
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    try:
        tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)
    except ShaMismatchError:
        pass
    else:
        msg = "expected ShaMismatchError"
        raise AssertionError(msg)

    failures = pipeline.journal.failures()
    assert "sha256" in failures["scan"]
    with pipeline.storage.open(key) as handle:  # not promoted, not deleted
        assert handle.read() == b"different-bytes-entirely"
