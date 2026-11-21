"""Effective number of trials by average-linkage clustering of a correlation matrix (ADR-0104).

A family of ``n`` distinct candidates is deflated by ``n`` trials (C6a, ADR-0103). Correlated
candidates overstate that number: two variants that differ only in a window length are not two
independent hypotheses. This module estimates how many *effectively independent* trials a family
holds, from the candidates' pairwise return correlations, and nothing else.

The estimator (ADR-0104 decision 3, implemented from its formula: scipy stays forbidden,
``docs/DEPENDENCIES.md``):

- the distance between two candidates is ``d = sqrt((1 - rho) / 2)``, so ``rho = 1`` is distance 0
  (identical series) and ``rho = -1`` is distance 1 (perfectly opposed);
- clustering is agglomerative with **average linkage**: at each step the pair of clusters with the
  smallest MEAN inter-cluster distance merges (the mean over every member pair across the two
  clusters, not the closest and not the farthest pair);
- it stops when that smallest mean distance exceeds ``d* = sqrt((1 - rho*) / 2)``, the distance of
  the threshold ``rho*``; ``effective_trials`` is then the number of clusters left. With the
  default ``rho* = 0.5`` two candidates whose average correlation is at least 0.5 end up in one
  cluster;
- a tie for the smallest distance goes to the LEXICOGRAPHICALLY smallest pair of sorted member
  tuples, so the same matrix always gives the same clusters (no dependence on array position);
- ``1 <= effective_trials <= n`` always.

This is an ESTIMATOR, not a count of independent hypotheses (the owner's rule, ADR-0104): the
number depends on ``rho*``, so every result carries a sensitivity table for
``rho* in {0.3, 0.5, 0.7, 0.9}`` and is labelled ``assessment: "estimator"`` with the note
:data:`ESTIMATOR_NOTE`. As ``rho*`` decreases the threshold distance grows, more pairs may merge
and ``effective_trials`` is non-increasing; as ``rho*`` increases it is non-decreasing (a
monotone step function, tested in ``tests/property/test_effective_trials_props.py``).

A pair with no valid correlation is NOT a pair with ``rho = 0``: a caller that cannot correlate two
candidates builds :func:`unavailable_effective_trials` with the reasons instead, and the result is
``unavailable`` with no number. This module refuses a matrix that is not a correlation matrix
(non-symmetric, non-finite, off the unit diagonal, ``|rho| > 1``), so an incomplete matrix can
never be read as a complete one.

Timing: a pure function of the matrix. Nothing here reads a clock, a store or a registry, and
nothing here decides what DSR does with the number: the DSR stays the primary result (ADR-0104
decision 4) and this is supplementary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError, InvariantViolation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from numpy.typing import NDArray

DEFAULT_RHO_THRESHOLD = 0.5
"""The default ``rho*``: candidates whose average correlation is at least this merge (ADR-0104)."""

SENSITIVITY_THRESHOLDS: tuple[float, ...] = (0.3, 0.5, 0.7, 0.9)
"""The thresholds the sensitivity table always reports (ADR-0104 decision 3)."""

LINKAGE = "average"
"""The linkage the estimator uses: mean inter-cluster distance, never single or complete."""

DISTANCE_FORMULA = "d = sqrt((1 - rho) / 2)"
"""The distance between two candidates, recorded with every estimate."""

ESTIMATOR_NAME = "average_linkage"
"""The estimator's name, recorded with every estimate."""

ESTIMATOR_ASSESSMENT = "estimator"
"""The assessment label: this is an estimate, not a probability and not a count of hypotheses."""

ESTIMATOR_NOTE = "threshold-dependent; not a count of independent hypotheses"
"""The note that must travel with every estimate (ADR-0104, owner rule)."""

STATUSES: tuple[str, str] = ("ok", "unavailable")
"""The two statuses of :class:`EffectiveTrialsResult`."""

_SYMMETRY_TOLERANCE = 1e-12
"""How far a matrix may be from exactly symmetric or exactly unit-diagonal before it is refused
(the matrix is computed in float64; rounding is not a broken matrix)."""


def correlation_distance(rho: float) -> float:
    """``d = sqrt((1 - rho) / 2)``: the distance the estimator merges on.

    ``rho`` is a Pearson correlation, so a value outside ``[-1, 1]`` (beyond rounding) has no
    distance and is refused: a distance computed from it would be a number about nothing.
    """
    if not math.isfinite(rho) or abs(rho) > 1.0 + _SYMMETRY_TOLERANCE:
        msg = (
            f"rho = {rho!r} is not a correlation: d = sqrt((1 - rho) / 2) needs a finite value in "
            "[-1, 1]. A pair with no valid correlation makes the estimate unavailable; it is "
            "never replaced by 0"
        )
        raise InvariantViolation(msg)
    return math.sqrt(max(0.0, (1.0 - rho) / 2.0))


def threshold_distance(rho_threshold: float) -> float:
    """``d* = sqrt((1 - rho*) / 2)``: clustering stops when the smallest mean distance exceeds it.

    Two candidates whose average correlation is exactly ``rho*`` merge (the test is ``>``, not
    ``>=``), which is what "at least ``rho*``" means.
    """
    if not math.isfinite(rho_threshold) or not -1.0 <= rho_threshold <= 1.0:
        msg = (
            f"rho_threshold = {rho_threshold!r} is not a correlation: the threshold is a "
            "correlation in [-1, 1] (the default is 0.5)"
        )
        raise ConfigurationError(msg)
    return correlation_distance(rho_threshold)


def _validated_matrix(
    ids: Sequence[str], corr: NDArray[np.float64], rho_threshold: float
) -> NDArray[np.float64]:
    """``corr`` as a float64 ``n x n`` correlation matrix, or a refusal naming what is wrong.

    A matrix that is not square, does not match ``ids``, is not symmetric, has a non-unit
    diagonal, holds a non-finite value or a value outside ``[-1, 1]`` is refused: every one of
    those would silently change how many clusters the estimate has.
    """
    threshold_distance(rho_threshold)
    names = tuple(ids)
    if len(set(names)) != len(names):
        msg = (
            "the ids given to the effective-trials estimator repeat a name: a correlation matrix "
            "indexes one series per row, so two candidates cannot share an id"
        )
        raise ConfigurationError(msg)
    matrix = np.asarray(corr, dtype=np.float64)
    n = len(names)
    if matrix.ndim != 2 or matrix.shape != (n, n):
        msg = (
            f"the correlation matrix has shape {matrix.shape} for {n} id(s): the estimator "
            "needs an n x n matrix, one row and column per candidate"
        )
        raise ConfigurationError(msg)
    if n == 0:
        msg = (
            "the effective-trials estimator needs at least one candidate; an empty matrix has no "
            "clusters to count"
        )
        raise ConfigurationError(msg)
    if not np.all(np.isfinite(matrix)):
        bad = sorted({names[row] for row, _ in np.argwhere(~np.isfinite(matrix))})
        msg = (
            f"the correlation matrix has a non-finite entry for {bad}: a pair with no valid "
            "correlation makes the estimate unavailable, and it is never replaced by 0"
        )
        raise InvariantViolation(msg)
    if np.any(np.abs(matrix) > 1.0 + _SYMMETRY_TOLERANCE):
        msg = (
            "the correlation matrix holds an entry outside [-1, 1]: it is not a correlation "
            "matrix, so the distance d = sqrt((1 - rho) / 2) would describe nothing"
        )
        raise InvariantViolation(msg)
    if not np.allclose(matrix, matrix.T, rtol=0.0, atol=_SYMMETRY_TOLERANCE):
        msg = (
            "the correlation matrix is not symmetric: rho(a, b) must equal rho(b, a), or the "
            "clusters depend on the iteration order"
        )
        raise InvariantViolation(msg)
    diagonal = np.diag(matrix)
    if not np.allclose(diagonal, 1.0, rtol=0.0, atol=_SYMMETRY_TOLERANCE):
        msg = (
            f"the correlation matrix's diagonal is {diagonal.tolist()}: a series correlates "
            "perfectly with itself, so every diagonal entry must be 1"
        )
        raise InvariantViolation(msg)
    return matrix


def average_linkage_clusters(
    ids: Sequence[str], corr: NDArray[np.float64], *, rho_threshold: float
) -> tuple[tuple[str, ...], ...]:
    """The candidate clusters average linkage gives at ``rho_threshold`` (ADR-0104 decision 3).

    ``corr`` is the ``n x n`` Pearson correlation matrix of the candidates' return series (in the
    order of ``ids``), symmetric with a unit diagonal; a pair with no valid correlation never
    reaches this function (call :func:`unavailable_effective_trials` instead).

    At every step the pair of clusters with the smallest MEAN inter-cluster distance merges; a tie
    goes to the lexicographically smallest pair of sorted member tuples, so the result never
    depends on the order the pairs are visited in. The merge stops as soon as the smallest mean
    distance exceeds ``d* = sqrt((1 - rho*) / 2)``.

    Returns the clusters, each a tuple of the member ids in sorted order, and the clusters
    themselves sorted, so two calls on the same matrix give the same tuple.
    """
    names = tuple(ids)
    matrix = _validated_matrix(names, corr, rho_threshold)
    limit = threshold_distance(rho_threshold)
    distances = np.sqrt(np.clip((1.0 - matrix) / 2.0, 0.0, None))
    position = {name: index for index, name in enumerate(names)}
    clusters: list[tuple[str, ...]] = [(name,) for name in names]
    while len(clusters) > 1:
        best: tuple[float, tuple[str, ...], tuple[str, ...]] | None = None
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                a, b = clusters[left], clusters[right]
                total = 0.0
                for x in a:
                    for y in b:
                        total += float(distances[position[x], position[y]])
                mean = total / (len(a) * len(b))
                candidate = (mean, a, b)
                if best is None or candidate < best:
                    best = candidate
        assert best is not None  # len(clusters) > 1 guarantees a pair
        if best[0] > limit:
            break
        merged = tuple(sorted(best[1] + best[2]))
        clusters = [entry for entry in clusters if entry != best[1] and entry != best[2]]
        clusters.append(merged)
    return tuple(sorted(clusters))


def _threshold_key(rho_threshold: float) -> str:
    """The sensitivity table's key for a threshold (a JSON object key: ``"0.5"``, ``"0.3"``)."""
    return f"{rho_threshold:g}"


def _method_record(
    ids: Sequence[str], *, rho_threshold: float, min_overlap_trade_dates: int | None
) -> dict[str, object]:
    """What the estimate is and how it was made: the record ADR-0104 decision 3 requires."""
    return {
        "name": ESTIMATOR_NAME,
        "assessment": ESTIMATOR_ASSESSMENT,
        "note": ESTIMATOR_NOTE,
        "linkage": LINKAGE,
        "distance": DISTANCE_FORMULA,
        "threshold": rho_threshold,
        "threshold_distance": threshold_distance(rho_threshold),
        "threshold_rule": (
            "merge while the smallest mean inter-cluster distance <= sqrt((1 - threshold) / 2); "
            "stop when it exceeds it"
        ),
        "tie_rule": "lexicographically smallest pair of sorted member tuples",
        "min_overlap_trade_dates": min_overlap_trade_dates,
        "sensitivity_thresholds": list(SENSITIVITY_THRESHOLDS),
        "candidate_ids": list(ids),
    }


@dataclass(frozen=True, slots=True)
class EffectiveTrialsResult:
    """The estimate: the cluster count, its clusters, the sensitivity table and the method.

    ``status`` is ``ok`` with a number, or ``unavailable`` with the reasons and NO number: a pair
    whose correlation is unknown (too little overlap, incompatible artifacts, a constant series, a
    missing or unverified artifact) makes the whole estimate unavailable, and the count is never
    filled with 0 or 1 (ADR-0104 decision 2).

    ``sensitivity`` maps each threshold of :data:`SENSITIVITY_THRESHOLDS` to
    ``{"effective_trials": int, "clusters": [[id, ...], ...]}``; an unavailable estimate carries an
    empty table, because there is no matrix to cluster.
    """

    status: str
    effective_trials: int | None
    threshold: float
    clusters: tuple[tuple[str, ...], ...]
    sensitivity: Mapping[str, Mapping[str, object]]
    reasons: tuple[str, ...]
    method: Mapping[str, object]

    @property
    def available(self) -> bool:
        """Whether the estimate produced a number."""
        return self.status == "ok"

    def record(self) -> dict[str, object]:
        """The estimate as the report writes it: status, number, clusters, reasons and method."""
        return {
            "assessment": ESTIMATOR_ASSESSMENT,
            "note": ESTIMATOR_NOTE,
            "status": self.status,
            "effective_trials": self.effective_trials,
            "threshold": self.threshold,
            "clusters": [list(cluster) for cluster in self.clusters],
            "reasons": list(self.reasons),
            "method": dict(self.method),
        }


def estimate_effective_trials(
    ids: Sequence[str],
    corr: NDArray[np.float64],
    *,
    rho_threshold: float = DEFAULT_RHO_THRESHOLD,
) -> EffectiveTrialsResult:
    """Estimate the effective number of trials of a COMPLETE correlation matrix (ADR-0104).

    ``ids`` names the series each row and column of ``corr`` belongs to, ``rho_threshold`` is
    ``rho*``. Every pair of the matrix must hold a valid correlation: this function refuses an
    incomplete matrix instead of estimating from one, and a caller whose pairs are not all
    correlatable builds :func:`unavailable_effective_trials` with the reasons.

    ``1 <= effective_trials <= len(ids)`` is asserted (a cluster count outside that range would be
    a bug, not an estimate), and the sensitivity table for :data:`SENSITIVITY_THRESHOLDS` is
    always computed from the same matrix.
    """
    names = tuple(ids)
    matrix = _validated_matrix(names, corr, rho_threshold)
    clusters = average_linkage_clusters(names, matrix, rho_threshold=rho_threshold)
    sensitivity: dict[str, Mapping[str, object]] = {}
    for value in SENSITIVITY_THRESHOLDS:
        at_threshold = average_linkage_clusters(names, matrix, rho_threshold=value)
        sensitivity[_threshold_key(value)] = {
            "effective_trials": len(at_threshold),
            "clusters": [list(cluster) for cluster in at_threshold],
        }
    effective = len(clusters)
    if not 1 <= effective <= len(names):
        msg = (
            f"average linkage gave {effective} cluster(s) over {len(names)} candidate(s): the "
            "estimate is a cluster count between 1 and n, so the clustering or the matrix is wrong"
        )
        raise InvariantViolation(msg)
    return EffectiveTrialsResult(
        status="ok",
        effective_trials=effective,
        threshold=rho_threshold,
        clusters=clusters,
        sensitivity=sensitivity,
        reasons=(),
        method=_method_record(names, rho_threshold=rho_threshold, min_overlap_trade_dates=None),
    )


def unavailable_effective_trials(
    ids: Sequence[str],
    reasons: Sequence[str],
    *,
    rho_threshold: float = DEFAULT_RHO_THRESHOLD,
    min_overlap_trade_dates: int | None = None,
) -> EffectiveTrialsResult:
    """An estimate that cannot be made, with the reasons (ADR-0104 decision 2).

    Used when at least one pair of the family has no valid correlation: the result carries no
    number and no sensitivity table, because there is no complete matrix to cluster. ``reasons``
    must be non-empty (an unavailable estimate always says why).
    """
    if not reasons:
        msg = (
            "an unavailable effective-trials estimate must carry at least one reason: a number "
            "is missing for a stated cause, never silently"
        )
        raise ConfigurationError(msg)
    names = tuple(ids)
    return EffectiveTrialsResult(
        status="unavailable",
        effective_trials=None,
        threshold=rho_threshold,
        clusters=(),
        sensitivity={},
        reasons=tuple(reasons),
        method=_method_record(
            names, rho_threshold=rho_threshold, min_overlap_trade_dates=min_overlap_trade_dates
        ),
    )


__all__ = [
    "DEFAULT_RHO_THRESHOLD",
    "DISTANCE_FORMULA",
    "ESTIMATOR_ASSESSMENT",
    "ESTIMATOR_NAME",
    "ESTIMATOR_NOTE",
    "LINKAGE",
    "SENSITIVITY_THRESHOLDS",
    "STATUSES",
    "EffectiveTrialsResult",
    "average_linkage_clusters",
    "correlation_distance",
    "estimate_effective_trials",
    "threshold_distance",
    "unavailable_effective_trials",
]
