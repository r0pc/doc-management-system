"""Artifact manifest validation and loader behaviour without the ML stack.

sklearn/joblib are NOT installed on this host by design; every test here must
pass in that state. The loader treats an absent artifact file as a NORMAL phase
state (returns None), and any incompatible/corrupt artifact as logged-and-None —
never a crash. Hard errors block loading; sklearn-unavailable is a warning.
"""

import logging
from pathlib import Path

import pytest

from app.classification.ml.artifact import (
    DOC_TYPE_LABELS,
    EMBEDDING_MODEL_ID,
    EXPECTED_DIM,
    SCHEMA_VERSION,
    SECURITY_LEVEL_LABELS,
    ArtifactManifest,
    validate_manifest,
)
from app.classification.ml.loader import load_artifact, parse_manifest


def valid_manifest_dict() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sklearn_version": "1.5.2",
        "embedding_model_id": EMBEDDING_MODEL_ID,
        "dim": EXPECTED_DIM,
        "labels": {
            "doc_type": ["contract", "invoice"],
            "security_level": ["Confidential", "Internal"],
        },
        "metrics": {"doc_type": {"synthetic": None, "real": None}},
    }


def test_contract_constants_match_artifact_contract_md() -> None:
    assert SCHEMA_VERSION == 1
    assert EXPECTED_DIM == 384
    assert EMBEDDING_MODEL_ID == "BAAI/bge-small-en-v1.5"
    assert (
        frozenset(
            {
                "contract",
                "vendor_msa",
                "invoice",
                "hr_letter",
                "disciplinary_notice",
                "monthly_report",
                "policy_memo",
            }
        )
        == DOC_TYPE_LABELS
    )
    assert frozenset({"Public", "Internal", "Confidential", "Restricted"}) == SECURITY_LEVEL_LABELS


def test_parse_manifest_accepts_a_valid_payload() -> None:
    parsed = parse_manifest(valid_manifest_dict())
    assert isinstance(parsed, ArtifactManifest)
    assert parsed.dim == 384
    assert parsed.labels["doc_type"] == ["contract", "invoice"]


def test_parse_manifest_rejects_missing_fields() -> None:
    broken = valid_manifest_dict()
    del broken["dim"]
    with pytest.raises(Exception, match=r"ArtifactIncompatible|dim"):
        parse_manifest(broken)


# ---------------------------------------------------------------------------
# validate_manifest compatibility rules (artifact_contract.md rules 1-5).
# On this host sklearn is absent, so rule 2 degrades to a warning entry and an
# otherwise-valid manifest yields warnings only.
# ---------------------------------------------------------------------------


def hard_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if not e.startswith("warning:")]


def test_valid_manifest_yields_no_hard_errors_without_sklearn() -> None:
    errors = validate_manifest(parse_manifest(valid_manifest_dict()))
    assert hard_errors(errors) == []
    assert errors  # the sklearn-unavailable warning IS recorded
    assert all(e.startswith("warning: scikit-learn") for e in errors)


def test_wrong_dim_is_a_hard_error() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(update={"dim": 768})
    assert any("dim" in e for e in hard_errors(validate_manifest(broken)))


def test_labels_outside_taxonomy_are_hard_errors() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(
        update={"labels": {**manifest.labels, "doc_type": ["klingon_memo"]}}
    )
    errors = hard_errors(validate_manifest(broken))
    assert any("klingon_memo" in e for e in errors)


def test_unknown_label_group_is_a_hard_error() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(update={"labels": {**manifest.labels, "tone": ["formal"]}})
    assert any("tone" in e for e in hard_errors(validate_manifest(broken)))


def test_missing_label_group_is_a_hard_error() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(update={"labels": {"doc_type": manifest.labels["doc_type"]}})
    assert any("security_level" in e for e in hard_errors(validate_manifest(broken)))


def test_wrong_schema_version_is_a_hard_error() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(update={"schema_version": 2})
    assert any("schema_version" in e for e in hard_errors(validate_manifest(broken)))


def test_wrong_embedding_model_id_is_a_hard_error() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    broken = manifest.model_copy(update={"embedding_model_id": "hosted/api-model"})
    assert any("embedding_model_id" in e for e in hard_errors(validate_manifest(broken)))


def test_sklearn_major_minor_mismatch_is_pure_and_detectable() -> None:
    from app.classification.ml.artifact import _sklearn_major_minor

    assert _sklearn_major_minor("1.5.2") == ("1", "5")
    assert _sklearn_major_minor("1.5") == ("1", "5")
    assert _sklearn_major_minor("garbage") == ()


def test_custom_taxonomy_restricts_accepted_labels() -> None:
    manifest = parse_manifest(valid_manifest_dict())
    errors = hard_errors(
        validate_manifest(
            manifest, taxonomy_labels=(frozenset({"invoice"}), frozenset({"Internal"}))
        )
    )
    assert any("contract" in e for e in errors)
    assert any("Confidential" in e for e in errors)


# ---------------------------------------------------------------------------
# Loader behaviour on this host (no joblib): absent file -> None; existing but
# unloadable file -> logged-and-None, never raised.
# ---------------------------------------------------------------------------


def test_absent_artifact_file_is_a_normal_phase_state(tmp_path: Path) -> None:
    assert load_artifact(tmp_path / "model.joblib") is None


def test_unloadable_artifact_is_logged_and_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "model.joblib"
    target.write_bytes(b"not-a-joblib-payload")
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert load_artifact(target) is None
    assert any("model.joblib" in r.message for r in caplog.records)


def test_incompatible_manifest_is_logged_and_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A payload whose manifest fails validation must never load."""

    def fake_load(_path: Path) -> dict[str, object]:
        bad = valid_manifest_dict()
        bad["dim"] = 999
        return {"manifest": bad, "models": {}}

    monkeypatch.setattr("app.classification.ml.loader._joblib_load", fake_load)
    target = tmp_path / "model.joblib"
    target.write_bytes(b"stub")
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert load_artifact(target) is None
    assert any("dim" in r.message for r in caplog.records)


def test_compatible_payload_loads_into_ml_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"manifest": valid_manifest_dict(), "models": {"doc_type": {}, "security_level": {}}}
    monkeypatch.setattr("app.classification.ml.loader._joblib_load", lambda _path: payload)
    target = tmp_path / "model.joblib"
    target.write_bytes(b"stub")
    artifact = load_artifact(target)
    assert artifact is not None
    assert artifact.manifest.dim == 384
    assert artifact.payload == payload


def test_predict_type_returns_none_when_artifact_is_none() -> None:
    from app.classification.ml.loader import predict_type

    assert predict_type(None, "Sample document text") is None


def test_predict_type_with_mocked_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.classification.ml.loader import MlArtifact, predict_type

    class FakeEncoder:
        def encode(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
            return [[0.1] * 384]

    class FakeLabelEncoder:
        def __init__(self) -> None:
            self.classes_ = ["contract", "invoice"]

    class FakeModel:
        def predict_proba(self, _embeddings: object) -> list[list[float]]:
            return [[0.95, 0.05]]

    payload = {
        "manifest": valid_manifest_dict(),
        "models": {
            "doc_type": {
                "model": FakeModel(),
                "label_encoder": FakeLabelEncoder(),
            }
        },
    }
    artifact = MlArtifact(
        path=tmp_path / "model.joblib",
        payload=payload,
        manifest=parse_manifest(valid_manifest_dict()),
    )
    monkeypatch.setattr(
        "app.classification.ml.loader._get_encoder", lambda _model_id: FakeEncoder()
    )

    result = predict_type(artifact, "This is a contract agreement between Party A and Party B.")
    assert result is not None
    label, prob = result
    assert label == "contract"
    assert prob == 0.95
