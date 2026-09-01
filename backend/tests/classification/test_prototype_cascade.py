# backend/tests/classification/test_prototype_cascade.py
"""Prototypes run before the ML head and never claim to be calibrated."""

from __future__ import annotations

import uuid

from app.classification.pipeline import classify
from app.domain.taxonomy import Taxonomy

TYPE_A = uuid.uuid4()
VEC = [1.0, 0.0, 0.0]
NEAR = [0.99, 0.14, 0.0]
FAR = [0.0, 1.0, 0.0]


def test_a_close_prototype_decides_the_type() -> None:
    out = classify(
        "some text",
        Taxonomy.default(),
        None,
        embedding=NEAR,
        prototypes=[(TYPE_A, VEC)],
    )
    assert out.doc_type == TYPE_A
    assert out.needs_review is False


def test_a_prototype_hit_is_never_labelled_ml() -> None:
    """#11: cosine similarity is not a calibrated probability."""
    out = classify(
        "some text", Taxonomy.default(), None, embedding=NEAR, prototypes=[(TYPE_A, VEC)]
    )
    assert out.decided_by == "rules"


def test_a_distant_prototype_falls_through_to_review() -> None:
    out = classify("some text", Taxonomy.default(), None, embedding=FAR, prototypes=[(TYPE_A, VEC)])
    assert out.doc_type is None
    assert out.needs_review is True


def test_no_embedding_means_no_prototype_match() -> None:
    out = classify(
        "some text", Taxonomy.default(), None, embedding=None, prototypes=[(TYPE_A, VEC)]
    )
    assert out.doc_type is None


def test_the_closest_prototype_wins() -> None:
    type_b = uuid.uuid4()
    out = classify(
        "some text",
        Taxonomy.default(),
        None,
        embedding=NEAR,
        prototypes=[(type_b, FAR), (TYPE_A, VEC)],
    )
    assert out.doc_type == TYPE_A
