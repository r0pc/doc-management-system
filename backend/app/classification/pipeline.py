"""Classification cascade: rules -> ML (>= threshold else review) -> review.

This stage consumes extracted text inside the fixed worker pipeline
(scan_for_malware -> ... -> classify -> build_index); workers are the only
automated writer of classifications (#2). Level monotonicity authority is the
DB check_monotonic trigger (#8) — and since the Internal floor (#9) is the
minimum aggregate_level ever returns, this pipeline can never propose a
decrease. There is no LLM layer: ML failure/absence routes straight to human
review.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.classification.ml.loader import MlArtifact, predict_type
from app.classification.ml.prototypes import cosine_similarity
from app.classification.rules.registry import iter_recognizers
from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

DecidedBy = Literal["rules", "ml", "human"]

#: Invariant #11's ML cascade gate. It is a DEFAULT, not a constant: the only
#: evidence behind 0.85 today is a synthetic-only evaluation (metrics.real is
#: null — see ml/artifact_contract.md), so the number has to be recalibratable
#: against real labelled data without a code change.
DEFAULT_ML_THRESHOLD: Final[float] = 0.85
ML_THRESHOLD_ENV: Final[str] = "ML_CONFIDENCE_THRESHOLD"

DEFAULT_PROTOTYPE_THRESHOLD: Final[float] = 0.85
PROTOTYPE_THRESHOLD_ENV: Final[str] = "PROTOTYPE_CONFIDENCE_THRESHOLD"


def ml_threshold_from_env() -> float:
    """Cascade threshold from ``ML_CONFIDENCE_THRESHOLD``; default on anything odd.

    Read at the worker boundary (``app.workers.tasks``), never inside
    :func:`classify`, which stays pure. A missing, unparseable or out-of-range
    value falls back to :data:`DEFAULT_ML_THRESHOLD` with a warning — a typo in
    the environment must not silently disable the review gate.
    """
    raw = os.environ.get(ML_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_ML_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning("ml_threshold_unparseable value=%r; using %s", raw, DEFAULT_ML_THRESHOLD)
        return DEFAULT_ML_THRESHOLD
    if not 0.0 < value <= 1.0:
        logger.warning("ml_threshold_out_of_range value=%s; using %s", value, DEFAULT_ML_THRESHOLD)
        return DEFAULT_ML_THRESHOLD
    return value


def prototype_threshold_from_env() -> float:
    """Prototype cascade threshold from ``PROTOTYPE_CONFIDENCE_THRESHOLD``."""
    raw = os.environ.get(PROTOTYPE_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_PROTOTYPE_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "prototype_threshold_unparseable value=%r; using %s", raw, DEFAULT_PROTOTYPE_THRESHOLD
        )
        return DEFAULT_PROTOTYPE_THRESHOLD
    if not 0.0 < value <= 1.0:
        logger.warning(
            "prototype_threshold_out_of_range value=%s; using %s",
            value,
            DEFAULT_PROTOTYPE_THRESHOLD,
        )
        return DEFAULT_PROTOTYPE_THRESHOLD
    return value


@dataclass(frozen=True)
class ClassificationOutcome:
    """One classify() decision as recorded into classifications (append-only)."""

    decided_by: DecidedBy
    level_rank: int
    doc_type: uuid.UUID | str | None
    confidence: float
    findings: list[Finding]
    needs_review: bool


def classify(
    extracted_text: str,
    tax: Taxonomy,
    artifact: MlArtifact | None,
    *,
    ml_threshold: float = DEFAULT_ML_THRESHOLD,
    embedding: Sequence[float] | None = None,
    prototypes: Sequence[tuple[uuid.UUID, Sequence[float]]] = (),
    prototype_threshold: float = DEFAULT_PROTOTYPE_THRESHOLD,
) -> ClassificationOutcome:
    """Run the fixed cascade over extracted text.

    Rules scans feed findings (all placeholders this phase -> []); the level is
    aggregated by domain.policy with its Internal floor (#9). Prototypes match
    next (if embedding is present); otherwise a type decision needs ML
    confidence >= ml_threshold; anything less routes to human review with
    decided_by="rules" and confidence=0.0.
    """
    findings: list[Finding] = []
    for recognizer in iter_recognizers():
        findings.extend(recognizer.scan(extracted_text))
    level_rank = aggregate_level(findings, tax)

    if embedding is not None and prototypes:
        best_id: uuid.UUID | None = None
        best_score = 0.0
        for doc_type_id, centroid in prototypes:
            score = cosine_similarity(embedding, centroid)
            if score > best_score:
                best_id, best_score = doc_type_id, score
        if best_id is not None and best_score >= prototype_threshold:
            return ClassificationOutcome(
                # NOT "ml": a cosine similarity is not a calibrated probability
                # and must never be recorded as one (#11).
                decided_by="rules",
                level_rank=level_rank,
                doc_type=best_id,
                confidence=0.0,
                findings=findings,
                needs_review=False,
            )

    prediction = predict_type(artifact, extracted_text, embedding=embedding)
    if prediction is not None and prediction[1] >= ml_threshold:
        doc_type, confidence = prediction
        return ClassificationOutcome(
            decided_by="ml",
            level_rank=level_rank,
            doc_type=doc_type,
            confidence=confidence,
            findings=findings,
            needs_review=False,
        )
    return ClassificationOutcome(
        decided_by="rules",
        level_rank=level_rank,
        doc_type=None,
        confidence=0.0,
        findings=findings,
        needs_review=True,
    )
