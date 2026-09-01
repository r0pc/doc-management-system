# backend/tests/classification/test_prototypes.py
"""Centroid maths, and the guards around it."""

from __future__ import annotations

import math

import pytest

from app.classification.ml.prototypes import MIN_SAMPLES, compute_centroid


def test_centroid_of_identical_vectors_is_that_unit_vector() -> None:
    vectors = [[3.0, 4.0]] * 5
    centroid = compute_centroid(vectors)
    assert math.isclose(centroid[0], 0.6, abs_tol=1e-6)
    assert math.isclose(centroid[1], 0.8, abs_tol=1e-6)


def test_centroid_is_l2_normalised() -> None:
    centroid = compute_centroid([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]] * 3)
    assert math.isclose(sum(c * c for c in centroid), 1.0, abs_tol=1e-6)


def test_fewer_than_min_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        compute_centroid([[1.0, 0.0]] * (MIN_SAMPLES - 1))


def test_all_zero_vectors_are_rejected_not_silently_normalised() -> None:
    """A zero centroid would match everything at cosine 0 — fail loud instead."""
    with pytest.raises(ValueError, match="degenerate"):
        compute_centroid([[0.0, 0.0]] * 5)


def test_mismatched_dimensions_are_rejected() -> None:
    with pytest.raises(ValueError, match="dimension"):
        compute_centroid([[1.0, 0.0]] * 4 + [[1.0, 0.0, 0.0]])
