"""Vectorized vs. event-driven Level 1 results
agree within documented tolerance on the example strategy (ADR-0035).

``examples.trend_demo`` is the example strategy used: single symbol,
``rebalance_every: 1``, zero slippage/commission -- chosen specifically so
the only sources of divergence between the two engines are (a) the vectorized
engine's close-to-close return model vs. the event-driven engine's
next-bar-open fill (ADR-0010), which ADR-0035 shows are economically
equivalent bar-for-bar under this generator's no-overnight-gap convention,
and (b) the event-driven engine's integer-share rounding (``ROUND_DOWN`` in
``TrendFollower._rebalance``), a small, bounded, non-compounding drag with no
vectorized-side analogue (continuous weights). Both are named explicitly so
the tolerance below isn't a magic number.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from crucible.data.store import ParquetDataStore
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import assemble_engine
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig
from examples.trend_demo.build_data import BARS_DATASET, build_all
from examples.trend_demo.vectorized_signal import trend_follower_signal

RELATIVE_EQUITY_TOLERANCE = 0.02
"""2% -- measured divergence on this example is ~1.37% (ADR-0035), entirely
attributable to `TrendFollower`'s integer-share ``ROUND_DOWN`` sizing: ~500
daily rebalances each lose a fraction of a share's worth of notional, and
unlike a one-off effect this *does* compound (each rebalance re-truncates
from the then-current, already-slightly-reduced equity). The vectorized
path has no share-rounding at all (continuous weights), so this gap is a
real, understood, one-directional artifact of the event-driven engine's
own realism, not a vectorized-engine bug -- confirmed independently by the
exact long/flat decision-sequence match asserted above, which is what
actually exercises shift discipline. 2% stays far below the divergence a
genuine lookahead or timing bug would produce (the poison test in
``tests/lookahead/test_vectorized_poisoned_future.py`` is the harness that
specifically targets that failure mode)."""


def _event_driven_config(store_path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store_path)
    return ExperimentConfig.model_validate(raw)


def _is_long_at_each_bar(fill_rows: list[dict[str, object]], bar_ts: list[int]) -> list[bool]:
    """Reconstructs held-quantity sign at every bar timestamp from fills.
    A fill's ``ts`` is the *executing* bar's own timestamp (ADR-0010 point
    4), and under the no-overnight-gap data convention that bar's open
    equals the prior bar's close -- so a fill at ``ts`` captures that bar's
    entire close-to-close return, exactly like the vectorized weight used
    for that same ``ts`` (see module docstring)."""
    fills_by_ts: dict[int, float] = {}
    for row in fill_rows:
        ts = int(str(row["ts"]))
        signed = float(str(row["qty"])) * (1.0 if row["side"] == "buy" else -1.0)
        fills_by_ts[ts] = fills_by_ts.get(ts, 0.0) + signed

    result = []
    qty = 0.0
    for ts in bar_ts:
        qty += fills_by_ts.get(ts, 0.0)
        result.append(qty > 0.0)
    return result


def test_vectorized_and_event_driven_agree_on_the_trend_demo_example(
    tmp_path: Path,
) -> None:
    build_all(tmp_path)
    store = ParquetDataStore(tmp_path)
    ed_config = _event_driven_config(tmp_path)

    engine = assemble_engine(ed_config, store=store)
    ed_result = engine.run()

    vec_config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=trend_follower_signal,
        params={"lookback": ed_config.strategy.params["lookback"]},
        initial_cash=ed_config.initial_cash,
        realism_level=ed_config.experiment.realism_level,
        start=ed_config.start_ns,
        end=ed_config.end_ns,
        slippage_bps=ed_config.execution.slippage_bps,
        commission_bps=ed_config.execution.commission_bps,
    )
    vec_result = VectorizedBacktestEngine().run(vec_config)

    bar_ts = sorted(vec_result.weights.get_column("ts").to_list())
    event_driven_long = _is_long_at_each_bar(ed_result.fill_rows, bar_ts)
    vectorized_long = [
        w > 0.0 for w in vec_result.weights.sort("ts").get_column("weight").to_list()
    ]
    assert event_driven_long == vectorized_long, (
        "the two engines made different long/flat decisions on the same bar "
        "at least once -- shift discipline or timing semantics have diverged"
    )

    ed_equity = pl.DataFrame(ed_result.equity_rows).sort("ts").get_column("equity").to_list()[-1]
    vec_equity = vec_result.equity.sort("ts").get_column("equity").to_list()[-1]
    relative_diff = abs(ed_equity - vec_equity) / ed_equity
    assert relative_diff < RELATIVE_EQUITY_TOLERANCE, (
        f"final equity diverged by {relative_diff:.4%}, exceeding the documented "
        f"{RELATIVE_EQUITY_TOLERANCE:.0%} tolerance (event-driven={ed_equity}, "
        f"vectorized={vec_equity})"
    )
