"""Hand-computed tests of the effective-trials estimator (C6b, ADR-0104 decision 3).

Every expected number here is worked out by hand from ``d = sqrt((1 - rho) / 2)`` and the stop rule
``merge while the smallest mean inter-cluster distance <= d* = sqrt((1 - rho*) / 2)``, never by
running the estimator and recording what it said:

- a 3-candidate matrix with one correlated pair: 2 clusters, and the pair that merges is the one
  whose mean distance is under the threshold;
- a tie: two pairs at exactly the same distance, which the lexicographic rule resolves without
  changing the partition;
- a CHAIN, where average linkage and single linkage differ: at ``rho* = 0.68`` average linkage keeps
  two clusters while single linkage would give one, so the test pins the linkage down;
- all-independent (``N_eff = n``) and all-identical (``N_eff = 1``) matrices, the two ends;
- the threshold sensitivity table and its direction (``N_eff`` is non-increasing as ``rho*``
  decreases);
- the refusals: a matrix that is not a correlation matrix (non-symmetric, off the unit diagonal,
  ``|rho| > 1``, NaN) and the empty family.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError, InvariantViolation
from crucible.validation.effective_trials import (
    DEFAULT_RHO_THRESHOLD,
    DISTANCE_FORMULA,
    ESTIMATOR_ASSESSMENT,
    ESTIMATOR_NOTE,
    SENSITIVITY_THRESHOLDS,
    average_linkage_clusters,
    correlation_distance,
    estimate_effective_trials,
    threshold_distance,
    unavailable_effective_trials,
)


def _matrix(rows: list[list[float]]) -> np.ndarray:
    return np.asarray(rows, dtype=np.float64)


def test_distance_is_the_adr_formula() -> None:
    # rho = 1 -> 0, rho = 0 -> sqrt(1/2), rho = -1 -> 1; d* is the same function of the threshold
    assert correlation_distance(1.0) == 0.0
    assert correlation_distance(0.0) == pytest.approx(math.sqrt(0.5))
    assert correlation_distance(-1.0) == pytest.approx(1.0)
    assert threshold_distance(0.5) == pytest.approx(math.sqrt(0.25))
    assert threshold_distance(0.9) == pytest.approx(math.sqrt(0.05))
    assert DEFAULT_RHO_THRESHOLD == 0.5


def test_one_correlated_pair_merges_and_the_independent_one_does_not() -> None:
    # d(a, b) = sqrt((1 - 0.9) / 2) = 0.2236 <= d*(0.5) = 0.5 -> a and b merge
    # d(a, c) = d(b, c) = sqrt((1 - 0) / 2) = 0.7071 > 0.5 -> c stays alone
    # 2 clusters, hand-counted.
    result = estimate_effective_trials(
        ("a", "b", "c"),
        _matrix([[1.0, 0.9, 0.0], [0.9, 1.0, 0.0], [0.0, 0.0, 1.0]]),
    )
    assert result.status == "ok"
    assert result.effective_trials == 2
    assert result.clusters == (("a", "b"), ("c",))
    assert result.reasons == ()


def test_a_tie_merges_the_lexicographically_smallest_pair() -> None:
    # d(a, b) = d(c, d) = sqrt((1 - 0.9) / 2) = 0.2236 (the minimum, twice), every other pair
    # 0.7071: both tied pairs are under d*(0.5) and merge, so the partition is ((a, b), (c, d)).
    # The rule decides WHICH pair merges first, which this hand-count does not depend on -- the
    # determinism it buys is covered by the permutation property in the property tests.
    result = estimate_effective_trials(
        ("a", "b", "c", "d"),
        _matrix(
            [
                [1.0, 0.9, 0.0, 0.0],
                [0.9, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.9],
                [0.0, 0.0, 0.9, 1.0],
            ]
        ),
    )
    assert result.effective_trials == 2
    assert result.clusters == (("a", "b"), ("c", "d"))


def test_a_chain_is_clustered_by_average_and_not_by_single_linkage() -> None:
    # a-b = b-c = 0.9, a-c = 0.0. Distances: ab = bc = 0.2236, ac = 0.7071.
    # 1st step: min = 0.2236 <= d*, merge a-b (average linkage takes the same pair as single).
    # 2nd step: mean distance {a,b} -> c = (0.7071 + 0.2236) / 2 = 0.4654.
    #   rho* = 0.68 -> d* = sqrt(0.16) = 0.4: 0.4654 > 0.4, STOP -> 2 clusters.
    #   rho* = 0.5  -> d* = 0.5:        0.4654 <= 0.5, merge -> 1 cluster.
    # SINGLE linkage would use the minimum (0.2236) at the second step and merge at rho* = 0.68 too,
    # giving 1 cluster: this matrix is where the two linkages disagree, and the test pins average.
    chain = _matrix([[1.0, 0.9, 0.0], [0.9, 1.0, 0.9], [0.0, 0.9, 1.0]])
    strict = average_linkage_clusters(("a", "b", "c"), chain, rho_threshold=0.68)
    loose = average_linkage_clusters(("a", "b", "c"), chain, rho_threshold=0.5)
    assert strict == (("a", "b"), ("c",))
    assert loose == (("a", "b", "c"),)


def test_all_independent_series_are_one_cluster_each() -> None:
    # every off-diagonal 0 -> every distance sqrt(1/2) = 0.7071, which exceeds every threshold below
    # 1: no merge, so N_eff = n. This is the upper end of the estimate.
    result = estimate_effective_trials(
        ("a", "b", "c", "d"), np.eye(4, dtype=np.float64), rho_threshold=0.9
    )
    assert result.effective_trials == 4
    assert result.clusters == (("a",), ("b",), ("c",), ("d",))


def test_all_identical_series_are_one_cluster() -> None:
    # every off-diagonal 1 -> every distance 0 -> everything merges at any threshold: N_eff = 1,
    # the lower end of the estimate.
    identical = np.ones((3, 3), dtype=np.float64)
    result = estimate_effective_trials(("a", "b", "c"), identical)
    assert result.effective_trials == 1
    assert result.clusters == (("a", "b", "c"),)


def test_the_sensitivity_table_covers_the_four_thresholds_and_moves_the_right_way() -> None:
    # a-b = 0.95 (d = 0.1581), a-c = 0.45 (d = 0.5244), b-c = 0.45.
    # rho* = 0.9 -> d* = 0.2236: only a-b merges                       -> 2 clusters
    # rho* = 0.7 -> d* = 0.3873: only a-b merges                       -> 2 clusters
    # rho* = 0.5 -> d* = 0.5:    a-b merges, then {a,b}-c = 0.5244 > 0.5 -> 2 clusters
    # rho* = 0.3 -> d* = 0.5916: a-b merges, {a,b}-c = 0.5244 <= 0.5916 -> 1 cluster
    result = estimate_effective_trials(
        ("a", "b", "c"),
        _matrix([[1.0, 0.95, 0.45], [0.95, 1.0, 0.45], [0.45, 0.45, 1.0]]),
    )
    assert result.effective_trials == 2
    assert tuple(result.sensitivity) == ("0.3", "0.5", "0.7", "0.9")
    assert tuple(float(key) for key in result.sensitivity) == SENSITIVITY_THRESHOLDS
    counts = {key: int(entry["effective_trials"]) for key, entry in result.sensitivity.items()}
    assert counts == {"0.3": 1, "0.5": 2, "0.7": 2, "0.9": 2}
    # the table is monotone: walking rho* DOWN from 0.9 to 0.3, N_eff never grows
    descending = sorted(SENSITIVITY_THRESHOLDS, reverse=True)
    ordered = [counts[f"{value:g}"] for value in descending]
    assert ordered == sorted(ordered, reverse=True)
    # the 0.5 row of the table is the headline (default threshold) result
    assert result.sensitivity["0.5"]["clusters"] == [list(cluster) for cluster in result.clusters]


def test_the_method_record_names_what_the_estimate_is_and_how_it_was_made() -> None:
    result = estimate_effective_trials(("a", "b"), _matrix([[1.0, 0.99], [0.99, 1.0]]))
    method = result.method
    assert method["linkage"] == "average"
    assert method["distance"] == DISTANCE_FORMULA
    assert method["threshold"] == DEFAULT_RHO_THRESHOLD
    assert method["candidate_ids"] == ["a", "b"]
    assert method["assessment"] == ESTIMATOR_ASSESSMENT == "estimator"
    assert (
        method["note"]
        == ESTIMATOR_NOTE
        == ("threshold-dependent; not a count of independent hypotheses")
    )
    assert result.record()["assessment"] == "estimator"
    assert result.record()["note"] == ESTIMATOR_NOTE


def test_an_unavailable_estimate_carries_reasons_and_no_number() -> None:
    result = unavailable_effective_trials(("a", "b"), ["a / b: insufficient_overlap"])
    assert result.status == "unavailable"
    assert result.available is False
    assert result.effective_trials is None
    assert result.clusters == ()
    assert result.sensitivity == {}
    assert result.reasons == ("a / b: insufficient_overlap",)
    record = result.record()
    assert record["status"] == "unavailable"
    assert record["effective_trials"] is None
    # a reason is mandatory: an unavailable estimate never looks like a silent zero
    with pytest.raises(ConfigurationError, match="at least one reason"):
        unavailable_effective_trials(("a",), [])


@pytest.mark.parametrize(
    ("corr", "match"),
    [
        ([[1.0, 0.5], [0.5, 0.999]], "diagonal"),
        ([[1.0, 0.5], [0.4, 1.0]], "not symmetric"),
        ([[1.0, 1.5], [1.5, 1.0]], "outside"),
        ([[1.0, float("nan")], [float("nan"), 1.0]], "non-finite"),
    ],
)
def test_a_matrix_that_is_not_a_correlation_matrix_is_refused(
    corr: list[list[float]], match: str
) -> None:
    with pytest.raises(InvariantViolation, match=match):
        estimate_effective_trials(("a", "b"), _matrix(corr))


def test_the_shape_and_the_ids_are_checked() -> None:
    with pytest.raises(ConfigurationError, match="n x n"):
        estimate_effective_trials(("a", "b"), np.eye(3, dtype=np.float64))
    with pytest.raises(ConfigurationError, match="repeat"):
        estimate_effective_trials(("a", "a"), np.eye(2, dtype=np.float64))
    with pytest.raises(ConfigurationError, match="at least one candidate"):
        estimate_effective_trials((), np.zeros((0, 0), dtype=np.float64))
    with pytest.raises(ConfigurationError, match="not a correlation"):
        estimate_effective_trials(("a",), np.eye(1), rho_threshold=1.5)
