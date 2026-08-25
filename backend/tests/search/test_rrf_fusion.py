"""Truth-table tests for reciprocal-rank fusion (#29).

Pure math: no DB, no seams, no mocks. Every expected score below is
hand-computed with k=60: an arm hit at 1-based rank r contributes 1/(60+r).
"""

import uuid

import pytest

from app.search.hybrid import VersionHit, rrf_merge


def hit(n: int) -> VersionHit:
    return VersionHit(version_id=uuid.UUID(int=n), document_id=uuid.UUID(int=n + 1000))


def test_overlap_case_merges_scores_across_arms() -> None:
    kw = [hit(1), hit(2), hit(3)]
    vec = [hit(2), hit(4)]

    fused = rrf_merge(kw, vec)

    # v2: 1/61 + 1/62 (both arms) > v1: 1/61 > v4: 1/62 > v3: 1/63.
    assert [f.hit.version_id for f in fused] == [
        uuid.UUID(int=2),
        uuid.UUID(int=1),
        uuid.UUID(int=4),
        uuid.UUID(int=3),
    ]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert fused[1].score == pytest.approx(1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)
    assert fused[3].score == pytest.approx(1 / 63)


def test_disjoint_arms_tie_and_break_lexicographically() -> None:
    # Each arm's FIRST hit carries rank 1 -> identical 1/61 contributions;
    # the score tie resolves to the lower version_id deterministically.
    fused = rrf_merge([hit(2)], [hit(1)])

    assert [f.hit.version_id for f in fused] == [uuid.UUID(int=1), uuid.UUID(int=2)]
    assert fused[0].score == pytest.approx(1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)


def test_later_rank_within_one_arm_contributes_less() -> None:
    fused = rrf_merge([hit(1), hit(2)], [])

    assert [f.hit.version_id for f in fused] == [uuid.UUID(int=1), uuid.UUID(int=2)]
    assert fused[0].score == pytest.approx(1 / 61)
    assert fused[1].score == pytest.approx(1 / 62)


def test_score_tie_breaks_on_lexicographic_version_id() -> None:
    # kw rank 1 (1/61) ties vec rank 1 (1/61), and both rank-2 hits tie at
    # 1/62; each tie resolves to the lower version_id deterministically.
    fused = rrf_merge([hit(9), hit(2)], [hit(8), hit(1)])

    assert [f.hit.version_id for f in fused] == [
        uuid.UUID(int=8),
        uuid.UUID(int=9),
        uuid.UUID(int=1),
        uuid.UUID(int=2),
    ]


def test_limit_truncates_after_full_sort() -> None:
    fused = rrf_merge([hit(i) for i in range(5)], [], limit=2)

    assert [f.hit.version_id for f in fused] == [uuid.UUID(int=0), uuid.UUID(int=1)]


def test_empty_arms_yield_empty_fusion() -> None:
    assert rrf_merge([], []) == []


def test_k_parameter_changes_contributions() -> None:
    fused = rrf_merge([hit(1)], [], k=10)

    assert fused[0].score == pytest.approx(1 / 11)


def test_fusion_is_deterministic_for_identical_inputs() -> None:
    kw = [hit(3), hit(1), hit(2)]
    vec = [hit(2), hit(5)]

    assert rrf_merge(kw, vec) == rrf_merge(kw, vec)
