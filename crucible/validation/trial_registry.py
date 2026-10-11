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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    family VARCHAR NOT NULL,
    experiment_id VARCHAR NOT NULL,
    sharpe DOUBLE,
    mode VARCHAR,
    start_ns BIGINT,
    end_ns BIGINT,
    PRIMARY KEY (family, experiment_id)
)
"""


class DuckDBTrialRegistry:
    """Implements ``crucible.validation.interfaces.TrialRegistry``. One row
    per (family, experiment_id); the primary key makes recording the same
    trial twice a no-op rather than a double-count (and never overwrites
    that trial's stored ``sharpe``/``mode``/window)."""

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
    ) -> int:
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            conn.execute(
                "INSERT INTO trials (family, experiment_id, sharpe, mode, start_ns, end_ns) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (family, experiment_id) DO NOTHING",
                [family, experiment_id, sharpe, mode, start_ns, end_ns],
            )
            return self._count(conn, family)

    def trial_count(self, family: str) -> int:
        with duckdb.connect(str(self._path)) as conn:
            conn.execute(_SCHEMA)
            return self._count(conn, family)

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
