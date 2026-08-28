"""The loader's documented contract, exercised with fakes (no ML stack here).

Companion to test_artifact_loader.py, which covers manifest validation. This
file pins the three behaviours the inference wave added or repaired:

* **failure degradation** — EVERY prediction fault becomes None + a log line.
  A model problem must never fail ingestion; before this, an incompatible
  payload raised ArtifactIncompatibleError straight through ``classify`` and
  past ``_run_stage``'s (ValueError, TypeError) handler, killing the chain.
* **embed once (#6)** — ``embed_text`` is the single forward pass, and
  ``predict_type(embedding=...)`` reuses its vector instead of re-encoding.
* **metrics honesty (#13/#14)** — an artifact reporting no real evaluation
  slice still loads, but says so at WARNING.

sklearn/joblib/sentence-transformers are absent from this host by design; every
test here must pass in that state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from app.classification.ml import loader
from app.classification.ml.artifact import DOC_TYPE_LABELS, taxonomy_name_for_label
from app.classification.ml.loader import (
    EMBED_EXCERPT_CHARS,
    MlArtifact,
    embed_text,
    load_artifact,
    parse_manifest,
    predict_type,
    synthetic_only_groups,
)
from tests.classification.test_artifact_loader import valid_manifest_dict

DIM = 384


def real_slice() -> dict[str, object]:
    return {"support": 40, "per_class_recall": {"invoice": 0.9}, "restricted_recall": 1.0}


def fake_artifact(models: dict[str, object] | None = None) -> MlArtifact:
    return MlArtifact(
        path=None,
        payload={"models": models if models is not None else {}},
        manifest=parse_manifest(valid_manifest_dict()),
    )


class CountingEncoder:
    """Records every forward pass; a repeat over the same text is the bug (#6)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
        self.calls.extend(texts)
        return [[0.25] * DIM]


@pytest.fixture
def encoder(monkeypatch: pytest.MonkeyPatch) -> CountingEncoder:
    fake = CountingEncoder()
    monkeypatch.setattr(loader, "_get_encoder", lambda _model_id: fake)
    return fake


# --- label -> taxonomy name: a NAME translation, never a row factory --------


def test_every_model_label_maps_to_a_taxonomy_name() -> None:
    assert {label: taxonomy_name_for_label(label) for label in sorted(DOC_TYPE_LABELS)} == {
        "contract": "Contract",
        "disciplinary_notice": "Disciplinary Notice",
        "hr_letter": "HR Letter",
        "invoice": "Invoice",
        "monthly_report": "Monthly Report",
        "policy_memo": "Policy Memo",
        "vendor_msa": "Vendor MSA",
    }


def test_unknown_label_has_no_taxonomy_name() -> None:
    assert taxonomy_name_for_label("klingon_memo") is None


# --- metrics honesty --------------------------------------------------------


def _load_with_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metrics: dict[str, object]
) -> MlArtifact | None:
    manifest = valid_manifest_dict()
    manifest["metrics"] = metrics
    payload = {"manifest": manifest, "models": {"doc_type": {}, "security_level": {}}}
    monkeypatch.setattr(loader, "_joblib_load", lambda _path: payload)
    target = tmp_path / "model.joblib"
    target.write_bytes(b"stub")
    return load_artifact(target)


def test_synthetic_only_groups_flags_null_and_missing_real_slices() -> None:
    assert synthetic_only_groups({}) == ["doc_type", "security_level"]
    assert synthetic_only_groups(
        {"doc_type": {"synthetic": {}, "real": None}, "security_level": {"real": real_slice()}}
    ) == ["doc_type"]
    assert (
        synthetic_only_groups(
            {"doc_type": {"real": real_slice()}, "security_level": {"real": real_slice()}}
        )
        == []
    )


def test_artifact_without_a_real_slice_loads_but_warns_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    metrics: dict[str, object] = {
        "doc_type": {"synthetic": {"per_class_recall": {"invoice": 1.0}}, "real": None},
        "security_level": {"synthetic": {"restricted_recall": 1.0}, "real": None},
    }
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        artifact = _load_with_metrics(tmp_path, monkeypatch, metrics)

    # The artifact is usable; what is untrusted is its accuracy CLAIM.
    assert artifact is not None
    warned = [r.getMessage() for r in caplog.records if "artifact_metrics_synthetic_only" in r.msg]
    assert warned
    assert "doc_type,security_level" in warned[0]
    assert "NOT as accuracy" in warned[0]


def test_artifact_with_a_real_slice_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    metrics: dict[str, object] = {
        "doc_type": {"synthetic": {}, "real": real_slice()},
        "security_level": {"synthetic": {}, "real": real_slice()},
    }
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert _load_with_metrics(tmp_path, monkeypatch, metrics) is not None

    assert not [r for r in caplog.records if "artifact_metrics_synthetic_only" in r.msg]


def test_the_shipped_artifact_reports_no_real_evaluation() -> None:
    """Guards ml/artifact_contract.md's limitation section against the real file.

    If a future artifact ever ships a real slice this flips, and the contract's
    limitation section must be revisited rather than silently outliving it.
    """
    metrics_path = Path("var/models/metrics.json")
    if not metrics_path.exists():
        pytest.skip("no trained artifact in this checkout (backend/var is gitignored)")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert synthetic_only_groups(metrics) == ["doc_type", "security_level"]


# --- get_artifact process cache --------------------------------------------


def test_get_artifact_caches_successes_and_retries_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader.reset_artifact_cache()
    loads: list[Path] = []
    real_load = loader.load_artifact

    def counting_load(path: Path) -> MlArtifact | None:
        loads.append(path)
        return real_load(path)

    monkeypatch.setattr(
        loader,
        "_joblib_load",
        lambda _path: {"manifest": valid_manifest_dict(), "models": {"doc_type": {}}},
    )
    monkeypatch.setattr(loader, "load_artifact", counting_load)

    present = tmp_path / "model.joblib"
    present.write_bytes(b"stub")
    absent = tmp_path / "absent.joblib"

    assert loader.get_artifact(present) is not None
    assert loader.get_artifact(present) is not None
    assert loads == [present]  # second call served from the cache

    assert loader.get_artifact(absent) is None
    assert loader.get_artifact(absent) is None
    assert loads == [present, absent, absent]  # a miss is retried, never cached

    loader.reset_artifact_cache()


# --- embed_text: the single pass, and its degradations ----------------------


def test_embed_text_returns_none_without_an_artifact() -> None:
    assert embed_text(None, "body") is None


def test_embed_text_returns_none_when_the_encoder_is_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """This host ships no sentence-transformers: degrade, never raise."""
    with caplog.at_level(logging.INFO, logger="app.classification.ml.loader"):
        assert embed_text(fake_artifact(), "body") is None
    assert any("ml_embed_unavailable" in r.msg for r in caplog.records)


def test_embed_text_truncates_to_the_contract_excerpt(encoder: CountingEncoder) -> None:
    vector = embed_text(fake_artifact(), "x" * 9000)

    assert vector == [0.25] * DIM
    assert encoder.calls == ["x" * EMBED_EXCERPT_CHARS]


def test_embed_text_swallows_an_encoder_fault(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Exploding:
        def encode(self, *_a: object, **_kw: object) -> object:
            msg = "this build refused the tensor"
            raise RuntimeError(msg)

    monkeypatch.setattr(loader, "_get_encoder", lambda _model_id: Exploding())
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert embed_text(fake_artifact(), "body") is None
    assert any("ml_embed_failed" in r.msg for r in caplog.records)


# --- predict_type: every failure degrades to None ---------------------------


def test_predict_type_degrades_when_models_doc_type_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``_predict_with_artifact`` raises ArtifactIncompatibleError here.

    Uncaught, that escaped ``classify`` past ``_run_stage``'s (ValueError,
    TypeError) handler and failed the entire ingestion chain.
    """
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert predict_type(fake_artifact({}), "body", embedding=[0.1] * DIM) is None
    assert any("ml_predict_failed" in r.msg for r in caplog.records)


def test_predict_type_degrades_on_any_head_exception(caplog: pytest.LogCaptureFixture) -> None:
    class Exploding:
        def predict_proba(self, _features: object) -> object:
            msg = "X has 384 features, but LogisticRegression expected 768"
            raise ValueError(msg)

    artifact = fake_artifact({"doc_type": {"model": Exploding(), "label_encoder": None}})
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert predict_type(artifact, "body", embedding=[0.1] * DIM) is None
    assert any("ml_predict_failed" in r.msg for r in caplog.records)


def test_predict_type_degrades_on_a_malformed_head_entry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    artifact = fake_artifact({"doc_type": {"label_encoder": None}})  # no "model" key
    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert predict_type(artifact, "body", embedding=[0.1] * DIM) is None
    assert any("ml_predict_failed" in r.msg for r in caplog.records)


class _LabelEncoder:
    def __init__(self) -> None:
        self.classes_ = ["contract", "invoice"]


class _Head:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    def predict_proba(self, features: Any) -> list[list[float]]:
        self.seen.append(features)
        return [[0.02, 0.98]]


def test_predict_type_reuses_a_precomputed_embedding_without_encoding(
    encoder: CountingEncoder,
) -> None:
    head = _Head()
    artifact = fake_artifact({"doc_type": {"model": head, "label_encoder": _LabelEncoder()}})

    assert predict_type(artifact, "body", embedding=[0.75] * DIM) == ("invoice", 0.98)
    assert encoder.calls == []  # #6: the embed stage already paid for this pass
    assert head.seen == [[[0.75] * DIM]]


def test_predict_type_encodes_on_demand_when_no_vector_is_supplied(
    encoder: CountingEncoder,
) -> None:
    head = _Head()
    artifact = fake_artifact({"doc_type": {"model": head, "label_encoder": _LabelEncoder()}})

    assert predict_type(artifact, "body") == ("invoice", 0.98)
    assert encoder.calls == ["body"]


def test_a_wrong_width_vector_is_re_encoded_rather_than_fed_to_the_head(
    encoder: CountingEncoder, caplog: pytest.LogCaptureFixture
) -> None:
    """A 768-d vector came from a different model; the 384-d head cannot take it."""
    head = _Head()
    artifact = fake_artifact({"doc_type": {"model": head, "label_encoder": _LabelEncoder()}})

    with caplog.at_level(logging.WARNING, logger="app.classification.ml.loader"):
        assert predict_type(artifact, "body", embedding=[0.1] * 768) == ("invoice", 0.98)

    assert encoder.calls == ["body"]
    assert head.seen == [[[0.25] * DIM]]
    assert any("ml_embedding_dim_mismatch" in r.msg for r in caplog.records)
