"""ML wiring through the worker pipeline: one embedding pass, one doc_type FK.

Three properties this suite pins, all of which were silently broken before:

* **#6, embed once** — the encoder is invoked EXACTLY once per document. The
  embed stage's vector is persisted on the derived artifact and reused by both
  classify (as ``embedding=``) and index (into ``document_text.embedding``).
* **the prediction is not discarded** — ``outcome.doc_type`` survives the whole
  chain into ``record_classification``, and ``resolve_doc_type_id`` turns a
  model label into an existing ``doc_types`` row (never a new one).
* **a model fault is not an ingestion fault** — a head that raises still lets
  the chain finish, with the document routed to human review.

Fakes follow tests/workers/conftest.py: no DB, no ML stack, no network.
"""

import json
import uuid
from typing import Any

import pytest

from app.classification.ml.artifact import ArtifactManifest
from app.classification.ml.loader import MlArtifact
from app.classification.pipeline import ClassificationOutcome
from app.extraction.base import ExtractedDocument, PageText
from app.workers import jobs, tasks
from app.workers.scanning import ScanVerdict
from tests.workers.conftest import (
    DOC_ID,
    PAYLOAD,
    SHA256,
    VER_ID,
    quarantine_key_fixture,
    seed_quarantine,
)

DIM = 384
BODY = "Master service agreement between ACME and the vendor."


def _manifest() -> ArtifactManifest:
    return ArtifactManifest(
        schema_version=1,
        sklearn_version="1.5.2",
        embedding_model_id="BAAI/bge-small-en-v1.5",
        dim=DIM,
        labels={"doc_type": ["vendor_msa", "invoice"], "security_level": ["Internal"]},
        metrics={},
    )


class _LabelEncoder:
    def __init__(self) -> None:
        self.classes_ = ["invoice", "vendor_msa"]


class _Head:
    """Calibrated-head stand-in; records the feature matrix it was handed."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def predict_proba(self, features: Any) -> list[list[float]]:
        self.seen.append(features)
        return [[0.04, 0.96]]


class _RaisingHead:
    def predict_proba(self, features: Any) -> list[list[float]]:
        msg = "X has 384 features, but LogisticRegression is expecting 768"
        raise ValueError(msg)


class _CountingEncoder:
    """Counts forward passes; a second call over the same text is the bug (#6)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
        self.calls.extend(texts)
        return [[0.5] * DIM]


def _artifact(head: Any) -> MlArtifact:
    return MlArtifact(
        path=None,
        payload={"models": {"doc_type": {"model": head, "label_encoder": _LabelEncoder()}}},
        manifest=_manifest(),
    )


@pytest.fixture
def encoder(monkeypatch: pytest.MonkeyPatch) -> _CountingEncoder:
    fake = _CountingEncoder()
    monkeypatch.setattr("app.classification.ml.loader._get_encoder", lambda _model_id: fake)
    return fake


def _run_chain(pipeline: Any, monkeypatch: pytest.MonkeyPatch, head: Any) -> None:
    key = quarantine_key_fixture()
    seed_quarantine(pipeline.storage, key, PAYLOAD)
    monkeypatch.setattr(
        tasks,
        "extract_document",
        lambda _data: ExtractedDocument(
            text=BODY,
            pages=[PageText(page_no=1, text=BODY)],
            mime_sniffed="application/pdf",
            char_count=len(BODY),
            ocr_used=False,
        ),
    )
    monkeypatch.setattr(
        tasks, "clamd_scan", lambda *a, **kw: ScanVerdict(clean=True, signature=None)
    )
    monkeypatch.setattr(tasks, "_artifact", lambda: _artifact(head))
    tasks.process_upload_chain(str(DOC_ID), str(VER_ID), key)


def _outcome(pipeline: Any) -> ClassificationOutcome:
    inserted = pipeline.store.classification_inserts
    assert len(inserted) == 1
    outcome = inserted[0]["outcome"]
    assert isinstance(outcome, ClassificationOutcome)
    return outcome


# --- #6: exactly one forward pass, reused downstream ------------------------


def test_document_is_embedded_once_and_the_vector_is_reused(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    head = _Head()
    _run_chain(pipeline, monkeypatch, head)

    # ONE encode for the whole chain: embed computed it, classify reused it.
    assert encoder.calls == [BODY]
    assert head.seen == [[[0.5] * DIM]]


def test_embed_stage_persists_the_vector_on_the_derived_artifact(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    _run_chain(pipeline, monkeypatch, _Head())

    with pipeline.storage.open(f"docs-derived/{SHA256}/text.json") as handle:
        derived = json.loads(handle.read())
    assert derived["embedding"] == [0.5] * DIM


def test_index_stage_writes_the_same_vector_into_document_text(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    """The search arm ranks on the very vector classification consumed (#6)."""
    _run_chain(pipeline, monkeypatch, _Head())

    assert [upsert["embedding"] for upsert in pipeline.store.text_upserts] == [[0.5] * DIM]


def test_classify_falls_back_to_encoding_when_no_embedding_was_stored(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    """Fallback path: the embed stage never ran, so classify encodes on demand."""
    from app.classification.pipeline import classify
    from app.domain.taxonomy import Taxonomy

    head = _Head()
    outcome = classify(BODY, Taxonomy.default(), _artifact(head), embedding=None)

    assert encoder.calls == [BODY]
    assert outcome.doc_type == "vendor_msa"


def test_precomputed_vector_of_the_wrong_width_is_re_encoded(
    monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    """A 768-d vector came from a different model; it cannot feed a 384-d head."""
    from app.classification.ml.loader import predict_type

    head = _Head()
    result = predict_type(_artifact(head), BODY, embedding=[0.1] * 768)

    assert result == ("vendor_msa", 0.96)
    assert encoder.calls == [BODY]


# --- the predicted label reaches persistence --------------------------------


def test_predicted_doc_type_survives_the_chain_into_record_classification(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    _run_chain(pipeline, monkeypatch, _Head())

    outcome = _outcome(pipeline)
    assert outcome.decided_by == "ml"
    assert outcome.doc_type == "vendor_msa"
    assert outcome.needs_review is False


# --- a model fault must not fail ingestion ----------------------------------


def test_a_raising_head_routes_to_review_without_failing_the_chain(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch, encoder: _CountingEncoder
) -> None:
    _run_chain(pipeline, monkeypatch, _RaisingHead())

    assert pipeline.journal.stages_in_state("succeeded") == [
        "scan",
        "extract",
        "keywords",
        "embed",
        "classify",
        "index",
    ]
    assert pipeline.journal.failures() == {}
    outcome = _outcome(pipeline)
    assert outcome.decided_by == "rules"
    assert outcome.doc_type is None
    assert outcome.needs_review is True
    assert pipeline.store.ready_documents == [DOC_ID]


# --- resolve_doc_type_id: existing rows only --------------------------------


class _FakeResult:
    def __init__(self, value: uuid.UUID | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> uuid.UUID | None:
        return self._value


class _FakeSession:
    """Session stand-in returning one canned row id for any SELECT."""

    def __init__(self, value: uuid.UUID | None) -> None:
        self._value = value
        self.executed = 0

    def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._value)


def test_known_label_resolves_to_the_existing_doc_types_row() -> None:
    row_id = uuid.UUID(int=0xB01)
    session = _FakeSession(row_id)

    assert jobs.resolve_doc_type_id(session, "vendor_msa") == row_id  # type: ignore[arg-type]
    assert session.executed == 1


def test_no_prediction_never_touches_the_taxonomy() -> None:
    session = _FakeSession(uuid.UUID(int=1))

    assert jobs.resolve_doc_type_id(session, None) is None  # type: ignore[arg-type]
    assert session.executed == 0


def test_unknown_label_is_null_plus_a_log_line_not_a_new_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession(uuid.UUID(int=1))

    with caplog.at_level("WARNING", logger="app.workers.jobs"):
        assert jobs.resolve_doc_type_id(session, "klingon_memo") is None  # type: ignore[arg-type]

    assert session.executed == 0  # no lookup, and above all no INSERT
    assert any("doc_type_label_unknown" in record.getMessage() for record in caplog.records)


def test_label_with_no_seeded_row_is_null_plus_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "HR Letter" is a real model label with no row in migration 0003's seed."""
    session = _FakeSession(None)

    with caplog.at_level("WARNING", logger="app.workers.jobs"):
        assert jobs.resolve_doc_type_id(session, "hr_letter") is None  # type: ignore[arg-type]

    messages = [record.getMessage() for record in caplog.records]
    assert any("doc_type_row_absent" in message for message in messages)
    assert any("HR Letter" in message for message in messages)
