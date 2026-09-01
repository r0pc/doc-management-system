"""Few-shot doc-type prototypes: a normalised centroid over stored vectors.

This is NOT a calibrated classifier and must never be presented as one (#11).
It is a similarity signal: cosine distance to a centroid of admin-chosen
examples. Below threshold the cascade falls through to ML and then to review,
exactly as an absent artifact does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

MIN_SAMPLES: Final[int] = 5
MAX_SAMPLES: Final[int] = 10


def compute_centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    """L2-normalised mean of ``vectors``; raises on anything unusable."""
    if len(vectors) < MIN_SAMPLES:
        msg = f"need at least {MIN_SAMPLES} sample vectors, got {len(vectors)}"
        raise ValueError(msg)
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        msg = "sample vectors disagree on dimension"
        raise ValueError(msg)
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(c * c for c in mean))
    if norm == 0.0:
        # A zero centroid has cosine 0 to everything: it would match nothing,
        # or — depending on the comparison — everything. Neither is a signal.
        msg = "degenerate centroid: sample vectors cancel to zero"
        raise ValueError(msg)
    return [c / norm for c in mean]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine of two vectors; both are assumed L2-normalised by the caller."""
    return sum(x * y for x, y in zip(a, b, strict=True))
