"""The default validation of a one-step backtest: a seeded shuffled-returns null test (ADR-0068).

The same rules are run on bars whose whole bar-to-bar moves have been randomly re-ordered
(``crucible.data.transforms.shuffle_bar_returns``: each bar's overnight gap, open-to-close
return, wicks and volume travel together): the multiset of close-to-close returns, and so the
long-run return, is unchanged; only the order is destroyed (ADR-0070). If the strategy's Sharpe
ratio is no better than what shuffled data produces, its timing has not been shown to matter.
It runs on the vectorized engine (milliseconds per shuffle), uses a throwaway store under the
home's scratch folder, and is deterministic: the generator is seeded from the experiment's seed.
Shuffles never count as trials (they never touch real market data, ADR-0019).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from crucible.analytics.metrics import simple_returns
from crucible.core.types import DatasetId, RealismLevel
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.data.transforms import shuffle_bar_returns
from crucible.validation.dsr import per_period_sharpe
from crucible.validation.null_tests import compare_to_null
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

if TYPE_CHECKING:
    import polars as pl

    from crucible.core.types import TimestampNs
    from crucible.vectorized.interfaces import SignalFunction

DEFAULT_ITERATIONS = 10_000
"""Shuffles per run (ADR-0078). The p-value is a Monte Carlo estimate with a standard error of
``sqrt(p (1 - p) / B)``: about 0.04 at B = 100, 0.004 at B = 10,000. Costs about 25-30 ms per
shuffle (a few minutes for ten years of daily bars); ``null_iterations`` lowers it."""


@dataclass(frozen=True, slots=True)
class NullTest:
    iterations: int
    real_sharpe_per_period: float
    null_median_per_period: float
    null_p95_per_period: float
    p_value: float
    exceedances: int
    """Shuffles whose Sharpe matched or beat the real one (``k``); ``p_value = (k+1)/(B+1)``."""
    invalid: int
    """Shuffles whose Sharpe was undefined; excluded from ``B`` (ADR-0070)."""


def shuffle_null_test(
    *,
    bars: pl.DataFrame,
    dataset: str,
    scratch: Path,
    signal: SignalFunction,
    params: dict[str, object],
    initial_cash: Decimal,
    realism_level: RealismLevel,
    start: TimestampNs,
    end: TimestampNs,
    slippage_bps: float,
    commission_bps: float,
    real_sharpe_per_period: float,
    seed: int,
    iterations: int = DEFAULT_ITERATIONS,
) -> NullTest:
    """Monte Carlo p-value ``(k + 1) / (B + 1)`` that a shuffled-data run matches or beats
    the real Sharpe (``crucible.validation.null_tests``). ``iterations`` >= 1; with fewer than
    19 the p-value cannot go below 0.05."""
    rng = np.random.default_rng(seed)
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="null-", dir=scratch))
    values: list[float] = []
    try:
        engine = VectorizedBacktestEngine()
        store = ParquetDataStore(work)
        for _ in range(iterations):
            shuffled = shuffle_bar_returns(bars, rng)
            build_dataset(
                work,
                DatasetId(dataset),
                shuffled,
                schema=BAR_SCHEMA,
                sort_keys=BAR_SORT_KEYS,
                source="null-test shuffle",
            )
            result = engine.run(
                VectorizedConfig(
                    store=store,
                    bars_dataset=DatasetId(dataset),
                    signal=signal,
                    params=params,
                    initial_cash=initial_cash,
                    realism_level=realism_level,
                    start=start,
                    end=end,
                    slippage_bps=slippage_bps,
                    commission_bps=commission_bps,
                )
            )
            values.append(per_period_sharpe(simple_returns(result.equity)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    outcome = compare_to_null(real_sharpe_per_period, values)
    array = np.asarray(values, dtype=np.float64)
    array = array[~np.isnan(array)]
    return NullTest(
        iterations=iterations,
        real_sharpe_per_period=real_sharpe_per_period,
        null_median_per_period=float(np.median(array)),
        null_p95_per_period=float(np.percentile(array, 95)),
        p_value=float(outcome.p_value if outcome.p_value is not None else 1.0),
        exceedances=outcome.n_exceedances,
        invalid=outcome.n_invalid,
    )
