"""Classification cascade: rules -> ML (>= threshold else review) -> review.

This stage consumes extracted text inside the fixed worker pipeline
(scan_for_malware -> ... -> classify -> build_index); workers are the only
automated writer of classifications (#2). Level monotonicity authority is the
DB check_monotonic trigger (#8) — and since the Internal floor (#9) is the
minimum aggregate_level ever returns, this pipeline can never propose a
decrease. There is no LLM layer: ML failure/absence routes straight to human
review.
"""

from dataclasses import dataclass
from typing import Literal

from app.classification.ml.loader import MlArtifact, predict_type
from app.classification.rules.registry import iter_recognizers
from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy

DecidedBy = Literal["rules", "ml", "human"]


@dataclass(frozen=True)
class ClassificationOutcome:
    """One classify() decision as recorded into classifications (append-only)."""

    decided_by: DecidedBy
    level_rank: int
    doc_type: str | None
    confidence: float
    findings: list[Finding]
    needs_review: bool


def classify(
    extracted_text: str,
    tax: Taxonomy,
    artifact: MlArtifact | None,
    *,
    ml_threshold: float = 0.85,
) -> ClassificationOutcome:
    """Run the fixed cascade over extracted text.

    Rules scans feed findings (all placeholders this phase -> []); the level is
    aggregated by domain.policy with its Internal floor (#9). A type decision
    needs ML confidence >= ml_threshold; anything less — including the normal
    absent-artifact state — routes to human review with decided_by="rules" and
    confidence=0.0, because nothing machine-confident decided.
    """
    findings: list[Finding] = []
    for recognizer in iter_recognizers():
        findings.extend(recognizer.scan(extracted_text))
    level_rank = aggregate_level(findings, tax)

    prediction = predict_type(artifact, extracted_text)
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
