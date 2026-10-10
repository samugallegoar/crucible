"""Synthetic single-symbol builder for the trend-following acceptance
demo (ADR-0024): genuine AR(1) serial autocorrelation in returns, not a
static per-symbol drift.

Contrast with ``examples.momentum``'s synthetic data: that generator
gives each symbol a *fixed* drift for the whole simulation -- a static
cross-sectional effect that ADR-0023 found survives every implemented
null test trivially (shuffle/GBM preserve each symbol's own marginal
mean; sign-flip is symmetric for a relative-ranking strategy). This
generator instead makes each bar's return causally depend on the
*previous* bar's return:

``r[0] = mu + eps[0]``
``r[t] = mu + phi * (r[t-1] - mu) + eps[t]``,  ``eps[t] ~ N(0, sigma_eps)``

``sigma_eps`` is chosen so the *unconditional* stdev of ``r`` is exactly
``SIGMA`` (the standard AR(1) variance identity:
``Var(r) = sigma_eps^2 / (1 - phi^2)``). A strategy that reads its own
trailing return sign (``examples.trend_demo.strategy.TrendFollower``)
has a genuine edge here that return-order shuffling destroys, because
shuffling breaks exactly the lag-1 dependency the signal relies on.

Bars follow ADR-0007 (``available_at = event_time``, zero feed latency)
and momentum's "no overnight gap" convention (``open[t] = close[t-1]``).
Deterministic: identical seed => identical dataset => identical manifest
hash. No corporate actions or universe dataset -- single symbol, never
delisted, so neither is needed (both are optional in ``DataConfig``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.types import DatasetId, to_timestamp_ns
from crucible.data.calendars import ExchangeCalendarAdapter
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.data.interfaces import DatasetManifest

BARS_DATASET = DatasetId("trend_demo_bars_v1")
SYMBOL = "TRENDY"
PHI = 0.35
"""AR(1) coefficient: a real, moderate positive serial correlation --
strong enough for a short-lookback trend follower to exploit robustly,
far below 1 (non-degenerate, stationary process)."""
MU = 0.0002
"""Small per-bar drift (~5%/year) -- deliberately not the source of the
edge on its own; a buy-and-hold strategy earns this same drift on
average regardless of shuffling (ADR-0023's point), so the acceptance
demonstration must show TrendFollower beating a shuffled null by more
than drift alone would explain."""
SIGMA = 0.012
"""Unconditional per-bar return stdev."""


def build_all(root: Path, seed: int = 20260918) -> dict[str, DatasetManifest]:
    """Builds the single bars dataset under ``root``."""
    start = to_timestamp_ns(datetime(2020, 1, 1, tzinfo=UTC))
    end = to_timestamp_ns(datetime(2021, 12, 31, 23, 59, tzinfo=UTC))
    calendar = ExchangeCalendarAdapter("XNYS", start=start, end=end)
    closes = calendar.session_closes(start, end)
    n = len(closes)

    rng = np.random.default_rng(seed)
    sigma_eps = SIGMA * float(np.sqrt(1.0 - PHI**2))
    eps = rng.normal(0.0, sigma_eps, size=n)
    r = np.empty(n)
    r[0] = MU + eps[0]
    for t in range(1, n):
        r[t] = MU + PHI * (r[t - 1] - MU) + eps[t]

    closes_px = 100.0 * np.cumprod(1.0 + r)
    opens_px = np.concatenate(([100.0], closes_px[:-1]))
    wick = np.abs(rng.standard_normal(n)) * 0.002
    highs = np.maximum(opens_px, closes_px) * (1.0 + wick)
    lows = np.minimum(opens_px, closes_px) * (1.0 - wick)
    volumes = 1e6 * (1.0 + rng.random(n))

    bars = pl.from_dicts(
        [
            {
                "symbol": SYMBOL,
                "event_time": int(closes[t]),
                "available_at": int(closes[t]),
                "open": float(opens_px[t]),
                "high": float(highs[t]),
                "low": float(lows[t]),
                "close": float(closes_px[t]),
                "volume": float(volumes[t]),
            }
            for t in range(n)
        ],
        schema=BAR_SCHEMA,
    )
    return {
        "bars": build_dataset(
            root,
            BARS_DATASET,
            bars,
            schema=BAR_SCHEMA,
            sort_keys=BAR_SORT_KEYS,
            source=f"synthetic AR(1) seed={seed} phi={PHI}",
        ),
    }


if __name__ == "__main__":
    from pathlib import Path as _Path

    manifests = build_all(_Path(__file__).parent / "data")
    for role, manifest in manifests.items():
        short_hash = manifest.content_hash[:12]
        print(f"{role}: {manifest.dataset} rows={manifest.row_count} hash={short_hash}")
