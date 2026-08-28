"""Routing cascade table: rules -> ML (>= 0.85 else review) -> review.

This phase the rules layer produces no type decision (placeholder scans) and
the ML artifact is normally absent, so classify() must route to human review
with decided_by="rules", confidence=0.0. A confident ML prediction (>= threshold)
is the only path that sets decided_by="ml".
"""

from dataclasses import FrozenInstanceError

import pytest

from app.classification.ml.artifact import ArtifactManifest
from app.classification.ml.loader import MlArtifact
from app.classification.pipeline import (
    DEFAULT_ML_THRESHOLD,
    ML_THRESHOLD_ENV,
    ClassificationOutcome,
    classify,
    ml_threshold_from_env,
)
from app.domain.models import Finding
from app.domain.taxonomy import Taxonomy


def manifest() -> ArtifactManifest:
    return ArtifactManifest(
        schema_version=1,
        sklearn_version="0.0.0",
        embedding_model_id="BAAI/bge-small-en-v1.5",
        dim=384,
        labels={"doc_type": ["invoice"], "security_level": ["Internal"]},
        metrics={},
    )


def fake_artifact() -> MlArtifact:
    return MlArtifact(path=None, payload={}, manifest=manifest())


@pytest.fixture()
def no_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.classification.pipeline.predict_type", lambda *_, **__: None)


def test_outcome_is_frozen() -> None:
    outcome = ClassificationOutcome(
        decided_by="rules",
        level_rank=2,
        doc_type=None,
        confidence=0.0,
        findings=[],
        needs_review=True,
    )
    with pytest.raises(FrozenInstanceError, match="cannot assign to field"):
        outcome.decided_by = "ml"  # type: ignore[misc]


def test_absent_artifact_routes_to_review(no_ml: None) -> None:
    outcome = classify("some text", Taxonomy.default(), None)
    assert outcome.needs_review is True
    assert outcome.decided_by == "rules"
    assert outcome.confidence == 0.0
    assert outcome.doc_type is None
    assert outcome.findings == []
    assert outcome.level_rank == 2  # Internal floor (#9)


def test_sub_threshold_prediction_routes_to_review(
    monkeypatch: pytest.MonkeyPatch, no_ml: None
) -> None:
    monkeypatch.setattr(
        "app.classification.pipeline.predict_type", lambda *_, **__: ("invoice", 0.84)
    )
    outcome = classify("text", Taxonomy.default(), fake_artifact())
    assert outcome.needs_review is True
    assert outcome.decided_by == "rules"
    assert outcome.confidence == 0.0


def test_confident_prediction_decides_by_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.classification.pipeline.predict_type", lambda *_, **__: ("invoice", 0.86)
    )
    outcome = classify("text", Taxonomy.default(), fake_artifact())
    assert outcome.decided_by == "ml"
    assert outcome.doc_type == "invoice"
    assert outcome.confidence == pytest.approx(0.86)
    assert outcome.needs_review is False


def test_custom_threshold_gates_the_ml_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.classification.pipeline.predict_type", lambda *_, **__: ("invoice", 0.86)
    )
    outcome = classify("text", Taxonomy.default(), fake_artifact(), ml_threshold=0.90)
    assert outcome.needs_review is True
    assert outcome.decided_by == "rules"


def test_recognizer_findings_flow_into_the_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = Finding(
        entity_type="cnic",
        rule_id="cnic-shape",
        page_no=1,
        char_start=0,
        char_end=15,
        score=0.9,
    )
    monkeypatch.setattr(
        "app.classification.pipeline.iter_recognizers",
        lambda: iter(
            [type("R", (), {"scan": staticmethod(lambda _t: [finding])})()]  # type: ignore[abstract]
        ),
    )
    outcome = classify("text", Taxonomy.default(), None)
    assert outcome.findings == [finding]
    assert outcome.level_rank == 3  # single CNIC -> Confidential via domain policy


def test_classify_signature_rejects_positional_threshold(no_ml: None) -> None:
    with pytest.raises(TypeError):
        classify("text", Taxonomy.default(), None, 0.85)  # type: ignore[misc]


def test_classify_forwards_the_precomputed_embedding_to_the_ml_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#6: the embed stage's vector must reach predict_type, not be recomputed."""
    seen: dict[str, object] = {}

    def spy(artifact: object, text: str, *, embedding: object = None) -> tuple[str, float]:
        seen["embedding"] = embedding
        return ("invoice", 0.99)

    monkeypatch.setattr("app.classification.pipeline.predict_type", spy)
    classify("text", Taxonomy.default(), fake_artifact(), embedding=[0.5] * 384)

    assert seen["embedding"] == [0.5] * 384


# --- cascade threshold: a DEFAULT, recalibratable without a code change -----


def test_threshold_default_is_the_invariant_11_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ML_THRESHOLD_ENV, raising=False)
    assert DEFAULT_ML_THRESHOLD == 0.85
    assert ml_threshold_from_env() == 0.85


def test_threshold_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ML_THRESHOLD_ENV, "0.92")
    assert ml_threshold_from_env() == pytest.approx(0.92)


@pytest.mark.parametrize("raw", ["", "   ", "not-a-number", "0", "-0.5", "1.5"])
def test_threshold_falls_back_to_the_default_on_anything_odd(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A typo in the environment must never silently disable the review gate."""
    monkeypatch.setenv(ML_THRESHOLD_ENV, raw)
    assert ml_threshold_from_env() == DEFAULT_ML_THRESHOLD
