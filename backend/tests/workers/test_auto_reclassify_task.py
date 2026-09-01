"""Tests for the worker reclassify_document_task.

Exercises re-running classification on an existing document with the latest rules/prototypes.
Invariant #2: Workers are the automated classifier writer.
Invariant #4: Pipeline state answerable from processing_jobs journal.
Invariant #6: Extracted text and embeddings reused, never recomputed.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest

from app.classification.pipeline import ClassificationOutcome
from app.storage.keys import derived_key
from app.workers import tasks
from tests.workers.conftest import (
    DOC_ID,
    SHA256,
    TENANT_ID,
    VER_ID,
)


def test_reclassify_document_task_runs_classification_and_records(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed derived text JSON
    text_payload = json.dumps(
        {
            "text": "CONFIDENTIAL AGREEMENT",
            "pages": [{"page_no": 1, "text": "CONFIDENTIAL AGREEMENT"}],
            "mime": "application/pdf",
            "char_count": 22,
            "ocr_used": False,
            "embedding": [0.1] * 384,
        }
    ).encode("utf-8")
    pipeline.storage.put(
        derived_key(SHA256, "text.json"),
        io.BytesIO(text_payload),
        content_type="application/json",
    )

    recorded_outcomes: list[ClassificationOutcome] = []

    def fake_record(
        sessions: Any,
        *,
        document_id: uuid.UUID,
        version_id: uuid.UUID,
        outcome: ClassificationOutcome,
    ) -> uuid.UUID:
        recorded_outcomes.append(outcome)
        return uuid.uuid4()

    monkeypatch.setattr(tasks, "record_auto_reclassification", fake_record)

    tasks.reclassify_document_task(str(DOC_ID), str(VER_ID))

    assert len(recorded_outcomes) == 1
    assert pipeline.journal.stages_in_state("succeeded") == ["classify"]


def test_reclassify_document_task_fails_when_digest_missing(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "load_version_context", lambda _s, _d, _v: (TENANT_ID, None))

    with pytest.raises(ValueError, match="no content digest"):
        tasks.reclassify_document_task(str(DOC_ID), str(VER_ID))

    assert "classify" in pipeline.journal.failures()
