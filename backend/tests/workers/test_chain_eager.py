"""Eager end-to-end orchestration of the fixed six-stage chain (spec §7.3 / #3)."""

import json

import pytest
from celery.exceptions import Ignore

from app.extraction.base import ExtractedDocument, NeedsOcrError, PageText
from app.workers import tasks
from app.workers.scanning import ScanVerdict
from tests.workers.conftest import (
    DOC_ID,
    PAYLOAD,
    SHA256,
    TENANT_ID,
    VER_ID,
    make_ctx,
    quarantine_key_fixture,
    seed_quarantine,
)

EXPECTED_ORDER = ["scan", "extract", "keywords", "embed", "classify", "index"]


def _fake_extraction(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def fake_extract(data: bytes) -> ExtractedDocument:
        calls.append("extract")
        return ExtractedDocument(
            text="extracted body text",
            pages=[PageText(page_no=1, text="extracted body text")],
            mime_sniffed="application/pdf",
            char_count=19,
            ocr_used=False,
        )

    monkeypatch.setattr(tasks, "extract_document", fake_extract)


def test_chain_runs_stages_in_spec_order(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    extraction_calls: list[str] = []
    _fake_extraction(monkeypatch, extraction_calls)
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert pipeline.journal.stages_in_state("running") == EXPECTED_ORDER
    assert pipeline.journal.stages_in_state("succeeded") == EXPECTED_ORDER
    assert extraction_calls == ["extract"]
    assert len(pipeline.store.classification_inserts) == 1
    assert pipeline.store.ready_documents == [DOC_ID]


def test_clean_scan_promotes_to_primary_and_deletes_quarantine(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _fake_extraction(monkeypatch, [])
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    primary_key = f"docs-primary/{TENANT_ID}/{SHA256[:2]}/{SHA256}"
    with pipeline.storage.open(primary_key) as handle:
        assert handle.read() == PAYLOAD
    with pytest.raises(FileNotFoundError):
        pipeline.storage.open(key)
    assert len(pipeline.store.promotions) == 1
    promotion = pipeline.store.promotions[0]
    assert promotion["sha256"] == SHA256
    assert promotion["bucket_key"] == primary_key


def test_extract_writes_derived_text_json_once(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _fake_extraction(monkeypatch, [])
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    derived_key = f"docs-derived/{SHA256}/text.json"
    with pipeline.storage.open(derived_key) as handle:
        payload = json.loads(handle.read())
    assert payload["text"] == "extracted body text"
    assert payload["mime"] == "application/pdf"
    assert payload["char_count"] == 19
    assert payload["ocr_used"] is False


def test_needs_ocr_dispatches_ocr_task_and_halts_chain(pipeline, monkeypatch) -> None:
    """OCR handoff: dispatch to the ocr queue, journal skipped, raise Ignore.

    Driven at stage level: celery's EAGER canvas swallows Ignore and feeds the
    next link a None result, so chain-level halt semantics are only observable
    on real workers. The state-based prerequisite gate (tested below via
    build_index) is what keeps later stages inert in every mode.
    """
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)

    def fake_extract(data: bytes) -> ExtractedDocument:
        raise NeedsOcrError("pdf text layer empty or too thin")

    monkeypatch.setattr(tasks, "extract_document", fake_extract)
    pipeline.journal.succeed(VER_ID, "scan")  # arrive at extract with scan done

    ctx = make_ctx(key)
    with pytest.raises(Ignore):
        tasks.extract_text(ctx)

    assert pipeline.journal.skip_reasons() == {"extract": "needs_ocr"}
    assert ("queued", "ocr") in [(event, stage) for event, stage, _ in pipeline.journal.events]

    # Prerequisite gate: index refuses to run without an extract SUCCESS (#5).
    tasks.build_index(ctx)
    assert pipeline.store.text_upserts == []
    assert "index" not in pipeline.journal.stages_in_state("running")


def test_keywords_stage_reads_derived_text_not_broker_payload(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _fake_extraction(monkeypatch, [])
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert len(pipeline.store.keyword_writes) == 1
    terms = dict(pipeline.store.keyword_writes[0])
    assert terms.get("extracted") == 1.0
    assert terms.get("text") == 1.0


def test_embed_is_placeholder_noop_but_journaled(pipeline, monkeypatch) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    _fake_extraction(monkeypatch, [])
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )

    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)

    assert "embed" in pipeline.journal.stages_in_state("succeeded")
    # Contract: when no model is active, vector stays NULL (None).
    assert all(upsert.get("embedding") is None for upsert in pipeline.store.text_upserts)


def test_ctx_dict_shape_is_exactly_the_six_contract_keys() -> None:
    ctx = make_ctx(quarantine_key_fixture())
    assert set(ctx) == {"document_id", "version_id", "tenant_id", "sha256", "bucket", "key"}
    assert all(isinstance(value, str) for value in ctx.values())
