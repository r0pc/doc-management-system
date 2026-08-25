"""Load/validate the Kaggle model artifact; the predict seam for the cascade.

Phase honesty: sklearn/joblib/sentence-transformers are absent from host venvs
by design. An absent artifact file is a NORMAL state (returns None); any
incompatible or unloadable artifact is logged-and-None — never a crash. With no
usable prediction, predict_type returns None and the pipeline routes to human
review (ML failure/absence NEVER guesses).
"""

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.classification.ml.artifact import ArtifactManifest, hard_errors, validate_manifest

logger = logging.getLogger(__name__)


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
    """Lazy, guarded joblib.load — hosts without joblib degrade gracefully."""
    if importlib.util.find_spec("joblib") is None:
        raise MlUnavailableError("joblib is not installed on this host")
    joblib = importlib.import_module("joblib")
    loaded: object = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ArtifactIncompatibleError(
            f"artifact payload is {type(loaded).__name__}, expected a dict"
        )
    return loaded


def load_artifact(path: Path) -> MlArtifact | None:
    """Load + validate an artifact; None when absent or unusable (logged).

    Absent file is the normal phase state — debug only, never a warning.
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
    return MlArtifact(path=path, payload=payload, manifest=manifest)


def predict_type(artifact: MlArtifact | None, text: str) -> tuple[str, float] | None:
    """Predict the document type; None means "no machine answer" -> review.

    Phase honesty: without the model server there is no prediction, so this
    ALWAYS returns None today. The seam is real — phase 3 fills
    _predict_with_artifact without touching any caller.
    """
    if artifact is None:
        return None
    try:
        return _predict_with_artifact(artifact, text)
    except MlUnavailableError as exc:
        logger.info("ml_predict_unavailable reason=%s", exc)
        return None


def _predict_with_artifact(artifact: MlArtifact, text: str) -> tuple[str, float]:
    """Encode + run both calibrated heads; raises MlUnavailableError until phase 3."""
    if importlib.util.find_spec("sentence_transformers") is None:
        raise MlUnavailableError("sentence-transformers is not installed on this host")
    # TODO(ml-phase-3): encode text[:4000] with artifact.manifest.embedding_model_id
    # (self-hosted weights only — self-hosting invariant), then run the doc_type
    # head + label encoder from artifact.payload["models"] and return (label, prob).
    raise MlUnavailableError("model server not wired until the ML wave")
