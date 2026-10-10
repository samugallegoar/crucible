"""A hand-written vectorized SMA crossover: the reference ``spec.yaml`` must reproduce.

Long-only: enter when the fast simple moving average of the close crosses above the slow one,
exit when it crosses back below, hold in between. The score is the target weight (1.0 long, 0.0
flat) **decided at bar t's close**; the vectorized engine adds the single mandatory one-bar lag,
so this function adds none of its own (ADR-0067: the lag convention is stated once, in
``crucible/strategy_spec/compile.py``).

``tests/integration/test_sma_cross_spec.py`` asserts that compiling ``spec.yaml`` gives exactly
these scores, bar for bar.
"""

from __future__ import annotations

import numpy as np
import polars as pl


def sma_cross_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """``params``: ``fast`` (default 10) and ``slow`` (default 30), whole numbers, fast < slow."""
    fast = int(str(params.get("fast", 10)))
    slow = int(str(params.get("slow", 30)))
    if not 1 <= fast < slow:
        msg = f"need 1 <= fast < slow, got fast={fast}, slow={slow}"
        raise ValueError(msg)
    frame = (
        bars.select(["symbol", "event_time", "close"])
        .sort(["symbol", "event_time"])
        .with_columns(
            fast_ma=pl.col("close").rolling_mean(window_size=fast).over("symbol"),
            slow_ma=pl.col("close").rolling_mean(window_size=slow).over("symbol"),
        )
        .collect()
    )
    parts: list[pl.DataFrame] = []
    for symbol, group in frame.group_by("symbol", maintain_order=True):
        f = group.get_column("fast_ma").to_numpy()
        s = group.get_column("slow_ma").to_numpy()
        held = np.zeros(len(f))
        state = 0.0
        for i in range(1, len(f)):
            if np.isnan(f[i]) or np.isnan(s[i]) or np.isnan(f[i - 1]) or np.isnan(s[i - 1]):
                held[i] = state
                continue
            if f[i - 1] <= s[i - 1] and f[i] > s[i]:
                state = 1.0
            elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
                state = 0.0
            held[i] = state
        parts.append(
            pl.DataFrame(
                {
                    "ts": group.get_column("event_time"),
                    "symbol": [str(symbol[0])] * len(f),
                    "score": held,
                }
            )
        )
    return pl.concat(parts).lazy()
