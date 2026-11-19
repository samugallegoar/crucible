"""Properties of the effective-trials estimator (C6b, ADR-0104 decision 3).

Hypothesis is derandomized (``derandomize=True``) and the examples are kept few and small: a
correlation matrix here is built from random factor loadings, which is the cheapest way to generate
a SYMMETRIC, unit-diagonal, positive-semidefinite matrix with entries in [-1, 1] -- the only kind
the estimator accepts. What the properties pin down:

1. the estimate is a count between 1 and n, and the clusters are a partition of the candidates,
   each sorted, with the clusters themselves sorted;
2. the count is MONOTONE in the threshold: ``N_eff`` is non-increasing as ``rho*`` decreases (a
   smaller threshold tolerates more dissimilarity, so it can only merge more);
3. a permutation of the candidates (ids and rows/columns together) gives the same clusters, so the
   answer cannot depend on the order a caller happened to list its candidates in -- the tie rule and
   the sorted output are what buy that;
4. the sensitivity table always covers the four ADR thresholds, and its ``0.5`` row equals the
   estimate at the default threshold;
5. the refusals hold for any generated shape: an entry outside [-1, 1] or a broken diagonal is never
   read as a correlation matrix.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from crucible.core.errors import InvariantViolation
from crucible.validation.effective_trials import (
    DEFAULT_RHO_THRESHOLD,
    SENSITIVITY_THRESHOLDS,
    estimate_effective_trials,
)

_PROPERTY_SETTINGS = settings(max_examples=20, derandomize=True, deadline=None)
_THRESHOLDS = st.sampled_from((-0.9, -0.3, 0.0, 0.3, 0.5, 0.7, 0.9))


def _correlation(loadings: list[list[float]]) -> np.ndarray:
    """The correlation matrix of a set of loading vectors (symmetric, unit diagonal, PSD).

    The generated loading vectors have different lengths (that is what makes the matrices vary), so
    each is padded with zeros to the longest: a zero loading on a factor nobody uses.
    """
    width = max(len(row) for row in loadings)
    matrix = np.asarray([row + [0.0] * (width - len(row)) for row in loadings], dtype=np.float64)
    gram = matrix @ matrix.T
    scale = np.sqrt(np.clip(np.diag(gram), 1e-12, None))
    corr = gram / np.outer(scale, scale)
    np.fill_diagonal(corr, 1.0)
    return np.clip(corr, -1.0, 1.0)


@st.composite
def _matrices(draw: st.DrawFn) -> tuple[tuple[str, ...], np.ndarray]:
    n = draw(st.integers(min_value=1, max_value=6))
    rows = [
        draw(
            st.lists(
                st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                min_size=1,
                max_size=3,
            )
        )
        for _ in range(n)
    ]
    return tuple(f"c{index}" for index in range(n)), _correlation(rows)


@_PROPERTY_SETTINGS
@given(pair=_matrices(), threshold=_THRESHOLDS)
def test_the_estimate_is_a_partition_and_a_count_within_the_candidates(
    pair: tuple[tuple[str, ...], np.ndarray], threshold: float
) -> None:
    ids, corr = pair
    result = estimate_effective_trials(ids, corr, rho_threshold=threshold)
    assert result.status == "ok"
    assert result.effective_trials is not None
    assert 1 <= result.effective_trials <= len(ids)
    assert result.effective_trials == len(result.clusters)
    for cluster in result.clusters:
        assert tuple(sorted(cluster)) == cluster, "members of a cluster are sorted"
        assert set(cluster) <= set(ids)
    flat = [member for cluster in result.clusters for member in cluster]
    assert sorted(flat) == sorted(ids), "the clusters partition the candidates exactly once each"
    assert list(result.clusters) == sorted(result.clusters), "the clusters themselves are sorted"


@_PROPERTY_SETTINGS
@given(pair=_matrices(), low=_THRESHOLDS, high=_THRESHOLDS)
def test_the_count_is_monotone_in_the_threshold(
    pair: tuple[tuple[str, ...], np.ndarray], low: float, high: float
) -> None:
    ids, corr = pair
    if low > high:
        low, high = high, low
    strict = estimate_effective_trials(ids, corr, rho_threshold=high)
    loose = estimate_effective_trials(ids, corr, rho_threshold=low)
    assert strict.effective_trials is not None
    assert loose.effective_trials is not None
    # a lower rho* is a larger d*, which can only merge more: N_eff(rho* low) <= N_eff(rho* high)
    assert loose.effective_trials <= strict.effective_trials


@_PROPERTY_SETTINGS
@given(pair=_matrices(), threshold=_THRESHOLDS)
def test_permuting_the_candidates_permutes_nothing(
    pair: tuple[tuple[str, ...], np.ndarray], threshold: float
) -> None:
    ids, corr = pair
    order = np.arange(len(ids))[::-1]  # the deterministic reverse permutation
    permuted_ids = tuple(ids[index] for index in order)
    permuted = corr[np.ix_(order, order)]
    plain = estimate_effective_trials(ids, corr, rho_threshold=threshold)
    shuffled = estimate_effective_trials(permuted_ids, permuted, rho_threshold=threshold)
    assert shuffled.clusters == plain.clusters


@_PROPERTY_SETTINGS
@given(pair=_matrices())
def test_the_sensitivity_table_is_complete_and_agrees_with_the_default(
    pair: tuple[tuple[str, ...], np.ndarray],
) -> None:
    ids, corr = pair
    result = estimate_effective_trials(ids, corr)
    assert tuple(float(key) for key in result.sensitivity) == SENSITIVITY_THRESHOLDS
    assert result.threshold == DEFAULT_RHO_THRESHOLD
    default_row = result.sensitivity[f"{DEFAULT_RHO_THRESHOLD:g}"]
    assert default_row["effective_trials"] == result.effective_trials
    assert default_row["clusters"] == [list(cluster) for cluster in result.clusters]
    for entry in result.sensitivity.values():
        assert 1 <= int(entry["effective_trials"]) <= len(ids)


@_PROPERTY_SETTINGS
@given(pair=_matrices(), bad=st.floats(min_value=1.0001, max_value=4.0))
def test_an_entry_outside_the_correlation_range_is_refused(
    pair: tuple[tuple[str, ...], np.ndarray], bad: float
) -> None:
    ids, corr = pair
    assume(len(ids) >= 2)  # a 1x1 matrix has no off-diagonal entry to break
    broken = corr.copy()
    broken[0, 1] = bad
    broken[1, 0] = bad
    with pytest.raises(InvariantViolation, match="outside"):
        estimate_effective_trials(ids, broken)


@_PROPERTY_SETTINGS
@given(pair=_matrices(), diagonal=st.floats(min_value=-1.0, max_value=0.99))
def test_a_diagonal_that_is_not_one_is_refused(
    pair: tuple[tuple[str, ...], np.ndarray], diagonal: float
) -> None:
    ids, corr = pair
    broken = corr.copy()
    broken[0, 0] = diagonal
    with pytest.raises(InvariantViolation, match="diagonal"):
        estimate_effective_trials(ids, broken)
