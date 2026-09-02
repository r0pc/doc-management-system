"""Load/validate the Kaggle model artifact; the predict + embed seam.

Self-hosting (hard requirement): every model here is local. The encoder is
resolved by id through sentence-transformers, whose weights are pre-baked into
the image at BUILD time and read offline at runtime (``HF_HUB_OFFLINE=1``);
nothing dials a hosted inference API. See ml/artifact_contract.md §Deployment.

Failure policy — the contract this module owes every caller: an absent artifact
file is a NORMAL state (returns None); any incompatible, unloadable or
mis-predicting artifact is logged-and-None — NEVER a crash. A model problem
must never fail ingestion. With no usable prediction, predict_type returns None
and the pipeline routes to human review (ML failure/absence NEVER guesses).

Invariant #6 (embed once): :func:`embed_text` is the ONE forward pass over a
document body. The vector it produces is persisted on the derived artifact and
handed back into :func:`predict_type` via ``embedding=``; the encode-on-demand
path inside :func:`_predict_with_artifact` is a fallback for callers that have
no precomputed vector (e.g. a bare classify over freshly supplied text).
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from app.classification.ml.artifact import (
    EMBEDDING_MODEL_ID,
    ArtifactManifest,
    hard_errors,
    validate_manifest,
)

logger = logging.getLogger(__name__)

#: Contract §"How the backend loader consumes this" step 2: first 4000 chars.
EMBED_EXCERPT_CHARS: Final[int] = 4000

_METRIC_GROUPS: Final[tuple[str, str]] = ("doc_type", "security_level")


class ArtifactIncompatibleError(Exception):
    """A payload's manifest could not be parsed or failed compatibility."""


class MlUnavailableError(Exception):
    """The ML stack needed to predict is absent on this host / this phase."""


@dataclass(frozen=True)
class MlArtifact:
    """A loaded, manifest-validated artifact plus its raw joblib payload."""

    path: Path | None
    payload: dict[str, Any]
    manifest: ArtifactManifest


def parse_manifest(raw: object) -> ArtifactManifest:
    """Parse the manifest half of a payload; anything malformed fails loud."""
    try:
        return ArtifactManifest.model_validate(raw)
    except ValidationError as exc:
        raise ArtifactIncompatibleError(f"manifest failed schema validation: {exc}") from exc


def _joblib_load(path: Path) -> dict[str, Any]:
    """Lazy, guarded joblib.load — hosts without joblib degrade gracefully.

    joblib.load unpickles, i.e. it executes whatever the file says. That is
    acceptable here and ONLY here because the artifact is not user input: it is
    an operator-placed file mounted read-only into the deployment (see
    ml/artifact_contract.md §Deployment), inside the same trust boundary as the
    application image itself. Never point MODEL_ARTIFACT_PATH at a path any
    tenant can write to.
    """
    if importlib.util.find_spec("joblib") is None:
        raise MlUnavailableError("joblib is not installed on this host")
    joblib = importlib.import_module("joblib")
    loaded: object = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ArtifactIncompatibleError(
            f"artifact payload is {type(loaded).__name__}, expected a dict"
        )
    return loaded


def synthetic_only_groups(metrics: dict[str, object]) -> list[str]:
    """Metric groups whose ``real`` evaluation slice is absent (contract rule 5).

    ``metrics.real is null`` means the head was scored ONLY against generated
    documents. Per-class recall from a deterministic template generator measures
    template-fingerprint separability, not document semantics, so it satisfies
    invariant #14 vacuously and must never be read as production accuracy (#13).
    """
    missing: list[str] = []
    for group in _METRIC_GROUPS:
        slice_ = metrics.get(group)
        if not isinstance(slice_, dict) or slice_.get("real") is None:
            missing.append(group)
    return missing


def load_artifact(path: Path) -> MlArtifact | None:
    """Load + validate an artifact; None when absent or unusable (logged).

    Absent file is the normal phase state — debug only, never a warning. A
    loadable artifact that reports no real-slice evaluation loads, but WARNs:
    its headline metrics are synthetic-only and are not evidence of accuracy.
    """
    if not path.exists():
        logger.debug("artifact_absent path=%s", path.name)
        return None
    try:
        payload = _joblib_load(path)
        manifest = parse_manifest(payload.get("manifest"))
        errors = validate_manifest(manifest)
    except (ArtifactIncompatibleError, MlUnavailableError) as exc:
        logger.warning("artifact_unusable path=%s reason=%s", path.name, exc)
        return None
    blocking = hard_errors(errors)
    if blocking:
        logger.warning("artifact_incompatible path=%s errors=%s", path.name, "; ".join(blocking))
        return None
    unevaluated = synthetic_only_groups(manifest.metrics)
    if unevaluated:
        logger.warning(
            "artifact_metrics_synthetic_only path=%s groups=%s: metrics.real is null, so the "
            "reported per-class recall comes from generated documents alone. Treat it as a "
            "smoke test of the training loop, NOT as accuracy: hold-out evaluation on real "
            "labelled documents is still outstanding (invariants #13/#14).",
            path.name,
            ",".join(unevaluated),
        )
    return MlArtifact(path=path, payload=payload, manifest=manifest)


_ARTIFACT_CACHE: dict[Path, MlArtifact] = {}


def get_artifact(path: Path) -> MlArtifact | None:
    """Process-cached :func:`load_artifact` — a hot path may call this per item.

    Only SUCCESSFUL loads are cached: an artifact mounted after boot is picked
    up on the next call, while a validated one is never re-parsed. Caching a
    loaded artifact does mean a REPLACED file needs a process restart, which is
    the deliberate trade (an on-prem artifact swap is a deploy, not a hot edit).
    """
    cached = _ARTIFACT_CACHE.get(path)
    if cached is not None:
        return cached
    artifact = load_artifact(path)
    if artifact is not None:
        _ARTIFACT_CACHE[path] = artifact
    return artifact


def reset_artifact_cache() -> None:
    """Drop the process cache (tests, and any future artifact hot-reload)."""
    _ARTIFACT_CACHE.clear()


_ENCODER_CACHE: dict[str, Any] = {}


def _get_encoder(model_id: str) -> Any:
    if model_id not in _ENCODER_CACHE:
        if importlib.util.find_spec("sentence_transformers") is None:
            raise MlUnavailableError("sentence-transformers is not installed on this host")
        st_module = importlib.import_module("sentence_transformers")
        sentence_transformer_cls = st_module.SentenceTransformer
        _ENCODER_CACHE[model_id] = sentence_transformer_cls(model_id)
    return _ENCODER_CACHE[model_id]


def _encode(artifact: MlArtifact, text: str) -> Any:
    """One forward pass over the excerpt; returns the raw 2-D encoder output."""
    encoder = _get_encoder(artifact.manifest.embedding_model_id)
    return encoder.encode([text[:EMBED_EXCERPT_CHARS]], show_progress_bar=False)


def embed_text(artifact: MlArtifact | None, text: str) -> list[float] | None:
    """THE embedding pass (#6); None when no usable encoder. Never raises.

    The returned vector is persisted on the derived artifact and reused by both
    classification (``predict_type(..., embedding=...)``) and pgvector search.
    A second encode of the same text with the same model is a bug.
    """
    if artifact is None:
        return None
    try:
        return [float(value) for value in _encode(artifact, text)[0]]
    except MlUnavailableError as exc:
        logger.info("ml_embed_unavailable reason=%s", exc)
        return None
    except Exception as exc:  # broad by contract: an encoder fault must not fail ingestion
        logger.warning("ml_embed_failed error=%s reason=%s", type(exc).__name__, exc)
        return None


def embed_sample_text(text: str, model_id: str = EMBEDDING_MODEL_ID) -> list[float] | None:
    """Encode standalone sample text with the default sentence transformer."""
    try:
        encoder = _get_encoder(model_id)
        encoded = encoder.encode([text[:EMBED_EXCERPT_CHARS]], show_progress_bar=False)
        return [float(value) for value in encoded[0]]
    except MlUnavailableError as exc:
        logger.info("ml_sample_embed_unavailable reason=%s", exc)
        return None
    except Exception as exc:
        logger.warning("ml_sample_embed_failed error=%s reason=%s", type(exc).__name__, exc)
        return None


def predict_type(
    artifact: MlArtifact | None,
    text: str,
    *,
    embedding: Sequence[float] | None = None,
) -> tuple[str, float] | None:
    """Predict the document type; None means "no machine answer" -> review.

    Honours the module contract unconditionally: EVERY prediction failure —
    absent ML stack, malformed payload, sklearn blowing up on an unexpected
    feature shape — degrades to None and a log line. Nothing raised here may
    escape into the ingestion chain (a model problem must never fail ingestion).

    ``embedding`` is the vector already computed by :func:`embed_text` during
    the embed stage; supplying it satisfies invariant #6 (one pass reused by
    classification and search). Omitting it falls back to encoding on demand.
    """
    if artifact is None:
        return None
    try:
        return _predict_with_artifact(artifact, text, embedding)
    except MlUnavailableError as exc:
        logger.info("ml_predict_unavailable reason=%s", exc)
        return None
    except Exception as exc:  # broad by contract: logged-and-None, never a crash
        logger.warning("ml_predict_failed error=%s reason=%s", type(exc).__name__, exc)
        return None


def _features(artifact: MlArtifact, text: str, embedding: Sequence[float] | None) -> Any:
    """Feature matrix for the heads: the precomputed vector, else one encode.

    A precomputed vector of the wrong width came from a different embedding
    model than the artifact pins, so it cannot be fed to these heads; that case
    re-encodes (and says so) rather than degrading the whole prediction.
    """
    if embedding is not None:
        if len(embedding) == artifact.manifest.dim:
            return [list(embedding)]
        logger.warning(
            "ml_embedding_dim_mismatch expected=%d got=%d; re-encoding for prediction",
            artifact.manifest.dim,
            len(embedding),
        )
    return _encode(artifact, text)


def _predict_with_artifact(
    artifact: MlArtifact, text: str, embedding: Sequence[float] | None = None
) -> tuple[str, float]:
    """Run the doc_type calibrated head over the reused (or freshly cut) vector."""
    features = _features(artifact, text, embedding)

    models_dict = artifact.payload.get("models")
    if not isinstance(models_dict, dict) or "doc_type" not in models_dict:
        raise ArtifactIncompatibleError("models.doc_type missing from artifact payload")

    doc_type_entry = models_dict["doc_type"]
    model = doc_type_entry["model"]
    label_encoder = doc_type_entry["label_encoder"]

    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(features)[0]
        best_idx, best_prob = max(enumerate(probs), key=lambda pair: float(pair[1]))
        best_prob = float(best_prob)
    else:
        preds = model.predict(features)
        best_idx = int(preds[0])
        best_prob = 1.0

    classes = getattr(label_encoder, "classes_", None)
    if classes is not None:
        best_label = str(classes[best_idx])
    elif hasattr(label_encoder, "inverse_transform"):
        best_label = str(label_encoder.inverse_transform([best_idx])[0])
    else:
        best_label = str(best_idx)

    return best_label, best_prob
