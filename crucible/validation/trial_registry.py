"""DuckDB-backed TrialRegistry (ADR-0008, ADR-0014).

Persistent, append-only count of parameter evaluations per experiment
family. One trial = one distinct ``experiment_id`` (a pure function of
config + data hashes); re-recording the same experiment_id under the same
family does not inflate the count — it is the same evaluation, not a new
one. Deleting runs never decrements a family's count (ADR-0008).

``sharpe`` (per-period, NOT annualized — ADR-0015) is recorded alongside
each trial so DSR can estimate the cross-trial dispersion of Sharpe
estimates it needs (``docs/adr/0015-dsr-pbo.md``); it is optional purely
for API flexibility, not because a real caller should omit it.

``mode``/``start_ns``/``end_ns`` (ADR-0021) let
contamination flagging (``validation.contamination``) answer "did an
optimization-mode trial in this family already see this evaluation's data
window?" from the registry alone, without re-reading every past trial's
``manifest.json``/``config.yaml`` off the artifact store.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One row of a family's trial history (ADR-0038)
    -- the result-registry query surface."""

    experiment_id: str
    sharpe: float | None
    mode: str | None
    start_ns: int | None
    end_ns: int | None


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """One candidate a batch SUBMITTED, whether or not it computed a run (C5a).

    The ``trials`` table counts distinct evaluations; a batch's submissions count what the
    researcher actually asked for, including the candidates that turned out to be duplicates of
    another (status ``cached``) or that hit an existing run directory. C6 decides how submissions
    count toward ``total_trials``; until then this table is the record and ``trials`` stays
    unchanged (one row per distinct ``experiment_id``).
    """

    batch_id: str
    position: int
    family: str
    experiment_id: str
    structure_id: str
    parameterization_id: str
    candidate_name: str
    status: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    family VARCHAR NOT NULL,
    experiment_id VARCHAR NOT NULL,
    sharpe DOUBLE,
    mode VARCHAR,
    start_ns BIGINT,
    end_ns BIGINT,
    PRIMARY KEY (family, experiment_id)
);
ALTER TABLE trials ADD COLUMN IF NOT EXISTS period_ns BIGINT;
CREATE TABLE IF NOT EXISTS submissions (
    batch_id VARCHAR NOT NULL,
    position INTEGER NOT NULL,
    family VARCHAR NOT NULL,
    experiment_id VARCHAR NOT NULL,
    structure_id VARCHAR NOT NULL,
    parameterization_id VARCHAR NOT NULL,
    candidate_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    PRIMARY KEY (batch_id, position)
);
"""
# period_ns (ADR-0071): the trial's median spacing between equity marks, i.e. the return
# frequency its per-period Sharpe is measured at. Null for rows from before the column existed.
# submissions (Fathom C5a): every candidate a futures batch submitted, in submission order. It is
# ADDITIVE: the trials table keeps one row per distinct experiment_id, and the primary key makes
# re-running a batch a no-op instead of a duplicate.

FREQUENCY_TOLERANCE = 1.5
"""Two trials' return periods count as the same frequency when they differ by less than this
factor (daily marks on an exchange calendar and on 24/7 both have a median of one day)."""


def median_period_ns(timestamps: Sequence[int]) -> int | None:
    """Median spacing of sorted mark timestamps (UTC ns), or None with fewer than two marks."""
    ts = sorted(int(t) for t in timestamps)
    if len(ts) < 2:
        return None
    diffs = sorted(b - a for a, b in itertools.pairwise(ts))
    return int(diffs[len(diffs) // 2])


def frequency_mismatch(periods: Sequence[int]) -> str | None:
    """A reason DSR must not pool these trials, or None. Per-period Sharpe ratios measured at
    different return frequencies (daily vs weekly) are not comparable: their cross-trial
    dispersion, and so the deflation benchmark, would mean nothing (ADR-0071)."""
    known = [p for p in periods if p > 0]
    if len(known) < 2:
        return None
    if max(known) / min(known) < FREQUENCY_TOLERANCE:
        return None
    days = sorted({round(p / 86_400e9, 3) for p in known})
    return (
        "cannot compute DSR: the trials pooled here were measured at different return "
        f"frequencies (median periods of {days} days), so their per-period Sharpe ratios are "
        "not comparable. Put trials of different frequencies in different families"
    )


class DuckDBTrialRegistry:
    """Implements ``crucible.validation.interfaces.TrialRegistry``. One row
    per (family, experiment_id); the primary key makes recording the same
    trial twice a no-op rather than a double-count (and never overwrites
    that trial's stored ``sharpe``/``mode``/window).

    A batch's submissions live in their own table (one row per submitted candidate, keyed by
    ``(batch_id, position)``), so a researcher's submitted set is preserved even when two
    candidates deduplicate onto one evaluation."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)

    def record_trial(
        self,
        family: str,
        experiment_id: str,
        sharpe: float | None = None,
        mode: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
        period_ns: int | None = None,
    ) -> int:
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            conn.execute(
                "INSERT INTO trials "
                "(family, experiment_id, sharpe, mode, start_ns, end_ns, period_ns) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (family, experiment_id) DO NOTHING",
                [family, experiment_id, sharpe, mode, start_ns, end_ns, period_ns],
            )
            return self._count(conn, family)

    def trial_count(self, family: str) -> int:
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            return self._count(conn, family)

    # --- submissions (Fathom C5a) ----------------------------------------------------------

    def record_submission(
        self,
        batch_id: str,
        position: int,
        family: str,
        experiment_id: str,
        structure_id: str,
        parameterization_id: str,
        candidate_name: str,
        status: str,
    ) -> int:
        """Record one submitted candidate; returns the batch's submission count.

        ``(batch_id, position)`` is the key, so re-running a batch never duplicates a submission
        and never rewrites the status first recorded (a candidate that computed keeps
        ``computed``; the run it names is reused on a re-run).
        """
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            conn.execute(
                "INSERT INTO submissions (batch_id, position, family, experiment_id, "
                "structure_id, parameterization_id, candidate_name, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (batch_id, position) DO NOTHING",
                [
                    batch_id,
                    int(position),
                    family,
                    experiment_id,
                    structure_id,
                    parameterization_id,
                    candidate_name,
                    status,
                ],
            )
            row = conn.execute(
                "SELECT COUNT(*) FROM submissions WHERE batch_id = ?", [batch_id]
            ).fetchone()
            assert row is not None
            return int(row[0])

    def submissions(
        self, batch_id: str | None = None, family: str | None = None
    ) -> list[SubmissionRecord]:
        """Every recorded submission, in ``(batch_id, position)`` order: submission order, never
        an order a metric would impose."""
        clauses: list[str] = []
        params: list[object] = []
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if family is not None:
            clauses.append("family = ?")
            params.append(family)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            rows = conn.execute(
                "SELECT batch_id, position, family, experiment_id, structure_id, "
                f"parameterization_id, candidate_name, status FROM submissions {where} "
                "ORDER BY batch_id, position",
                params,
            ).fetchall()
        return [
            SubmissionRecord(
                batch_id=str(row[0]),
                position=int(row[1]),
                family=str(row[2]),
                experiment_id=str(row[3]),
                structure_id=str(row[4]),
                parameterization_id=str(row[5]),
                candidate_name=str(row[6]),
                status=str(row[7]),
            )
            for row in rows
        ]

    def submission_count(self, family: str) -> int:
        """How many candidates were submitted under ``family`` across every batch."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            row = conn.execute(
                "SELECT COUNT(*) FROM submissions WHERE family = ?", [family]
            ).fetchone()
            assert row is not None
            return int(row[0])

    def trial_sharpes(self, family: str) -> list[float]:
        """Per-period Sharpe of every distinct trial recorded for
        ``family`` that was given one (omits rows recorded with
        ``sharpe=None``)."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            rows = conn.execute(
                "SELECT sharpe FROM trials WHERE family = ? AND sharpe IS NOT NULL",
                [family],
            ).fetchall()
            return [float(row[0]) for row in rows]

    def trial_periods(self, family: str | None = None) -> list[int]:
        """Distinct recorded return periods (``period_ns``) of ``family``, or of the whole
        registry when ``family`` is None; trials without one are omitted (ADR-0071)."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            if family is None:
                rows = conn.execute(
                    "SELECT DISTINCT period_ns FROM trials WHERE period_ns IS NOT NULL "
                    "ORDER BY period_ns"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT period_ns FROM trials WHERE family = ? "
                    "AND period_ns IS NOT NULL ORDER BY period_ns",
                    [family],
                ).fetchall()
            return [int(row[0]) for row in rows]

    def total_trial_count(self) -> int:
        """Distinct experiments recorded in any family of this registry (ADR-0070): the whole
        search this registry has seen. An experiment recorded under two families counts once."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            row = conn.execute("SELECT COUNT(DISTINCT experiment_id) FROM trials").fetchone()
            return int(row[0]) if row else 0

    def all_trial_sharpes(self) -> list[float]:
        """Per-period Sharpe of every distinct experiment in any family that was given one,
        ordered by ``experiment_id`` (ADR-0070)."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            rows = conn.execute(
                "SELECT experiment_id, MAX(sharpe) FROM trials WHERE sharpe IS NOT NULL "
                "GROUP BY experiment_id ORDER BY experiment_id"
            ).fetchall()
            return [float(row[1]) for row in rows]

    def all_trials(self, family: str) -> list[TrialRecord]:
        """Every recorded trial for ``family``, ordered by ``experiment_id``
        (deterministic and reproducible -- DuckDB makes no ordering
        guarantee without an explicit ``ORDER BY``). The registry-query
        surface a ``crucible compare`` command reads from."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            rows = conn.execute(
                "SELECT experiment_id, sharpe, mode, start_ns, end_ns FROM trials "
                "WHERE family = ? ORDER BY experiment_id",
                [family],
            ).fetchall()
            return [
                TrialRecord(
                    experiment_id=str(row[0]),
                    sharpe=float(row[1]) if row[1] is not None else None,
                    mode=str(row[2]) if row[2] is not None else None,
                    start_ns=int(row[3]) if row[3] is not None else None,
                    end_ns=int(row[4]) if row[4] is not None else None,
                )
                for row in rows
            ]

    def overlapping_optimization_trials(
        self, family: str, start_ns: int, end_ns: int
    ) -> Sequence[str]:
        """``experiment_id``s of every ``mode="optimization"`` trial in
        ``family`` whose recorded ``[start_ns, end_ns)`` window overlaps
        the query window (half-open interval overlap: ``a.start < b.end
        AND a.end > b.start``). Rows recorded without a window (``mode``/
        ``start_ns``/``end_ns`` all ``None``) can never match."""
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            rows = conn.execute(
                "SELECT experiment_id FROM trials WHERE family = ? AND mode = 'optimization' "
                "AND start_ns IS NOT NULL AND end_ns IS NOT NULL "
                "AND start_ns < ? AND end_ns > ?",
                [family, end_ns, start_ns],
            ).fetchall()
            return [str(row[0]) for row in rows]

    @staticmethod
    def _count(conn: duckdb.DuckDBPyConnection, family: str) -> int:
        row = conn.execute("SELECT COUNT(*) FROM trials WHERE family = ?", [family]).fetchone()
        assert row is not None
        return int(row[0])
