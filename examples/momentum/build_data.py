"""Synthetic universe builder for the momentum example.

Eight symbols, seeded GBM with heterogeneous drift, XNYS sessions over
2020-2021, one delisting (SYM7) about 60% of the way through. Deterministic:
identical seed ⇒ identical datasets ⇒ identical manifest hashes.

Bars follow ADR-0007: ``available_at = event_time`` (session close, zero feed
latency). Opens equal the previous close (no overnight gap model in the
generator — the fixture tests execution, not gap risk).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.types import DatasetId, to_timestamp_ns
from crucible.data.calendars import ExchangeCalendarAdapter
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
    END_AT_OPEN,
    UNIVERSE_SCHEMA,
    UNIVERSE_SORT_KEYS,
)
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.data.interfaces import DatasetManifest

BARS_DATASET = DatasetId("momentum_bars_v1")
ACTIONS_DATASET = DatasetId("momentum_ca_v1")
UNIVERSE_DATASET = DatasetId("momentum_universe_v1")

N_SYMBOLS = 8
DELISTED_SYMBOL = "SYM7"
ANNUAL_VOL = 0.20
TRADING_DAYS = 252.0


def build_all(root: Path, seed: int = 20260916) -> dict[str, DatasetManifest]:
    """Builds bars, corporate actions, and universe datasets under ``root``."""
    start = to_timestamp_ns(datetime(2020, 1, 1, tzinfo=UTC))
    end = to_timestamp_ns(datetime(2021, 12, 31, 23, 59, tzinfo=UTC))
    calendar = ExchangeCalendarAdapter("XNYS", start=start, end=end)
    closes = calendar.session_closes(start, end)
    n_sessions = len(closes)
    delist_index = int(n_sessions * 0.6)

    rng = np.random.default_rng(seed)
    drifts = np.linspace(-0.10, 0.30, N_SYMBOLS)  # annual drift per symbol
    rng.shuffle(drifts)

    rows: list[dict[str, object]] = []
    for i in range(N_SYMBOLS):
        symbol = f"SYM{i}"
        n = delist_index if symbol == DELISTED_SYMBOL else n_sessions
        z = rng.standard_normal(n)
        daily = drifts[i] / TRADING_DAYS + ANNUAL_VOL / np.sqrt(TRADING_DAYS) * z
        closes_px = 100.0 * np.cumprod(1.0 + daily)
        opens_px = np.concatenate(([100.0], closes_px[:-1]))
        wick = np.abs(rng.standard_normal(n)) * 0.002
        highs = np.maximum(opens_px, closes_px) * (1.0 + wick)
        lows = np.minimum(opens_px, closes_px) * (1.0 - wick)
        volumes = 1e6 * (1.0 + rng.random(n))
        for k in range(n):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": int(closes[k]),
                    "available_at": int(closes[k]),
                    "open": float(opens_px[k]),
                    "high": float(highs[k]),
                    "low": float(lows[k]),
                    "close": float(closes_px[k]),
                    "volume": float(volumes[k]),
                }
            )
    bars = pl.from_dicts(rows, schema=BAR_SCHEMA)

    delist_ts = int(closes[delist_index])  # first session close after the last bar
    actions = pl.DataFrame(
        {
            "symbol": [DELISTED_SYMBOL],
            "action": ["delisting"],
            "effective_at": [delist_ts],
            "event_time": [delist_ts],
            "available_at": [delist_ts],
            "value": [None],
            "pay_at": [None],  # unused for delisting (ADR-0026)
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    universe = pl.DataFrame(
        {
            "symbol": [f"SYM{i}" for i in range(N_SYMBOLS)],
            "start_at": [0] * N_SYMBOLS,
            "end_at": [
                delist_ts if f"SYM{i}" == DELISTED_SYMBOL else END_AT_OPEN for i in range(N_SYMBOLS)
            ],
            "reason": ["synthetic"] * N_SYMBOLS,
            "event_time": [0] * N_SYMBOLS,
            "available_at": [0] * N_SYMBOLS,
        }
    )

    return {
        "bars": build_dataset(
            root,
            BARS_DATASET,
            bars,
            schema=BAR_SCHEMA,
            sort_keys=BAR_SORT_KEYS,
            source=f"synthetic GBM seed={seed}",
        ),
        "corporate_actions": build_dataset(
            root,
            ACTIONS_DATASET,
            actions,
            schema=CORPORATE_ACTION_SCHEMA,
            sort_keys=CORPORATE_ACTION_SORT_KEYS,
            source=f"synthetic seed={seed}",
        ),
        "universe": build_dataset(
            root,
            UNIVERSE_DATASET,
            universe,
            schema=UNIVERSE_SCHEMA,
            sort_keys=UNIVERSE_SORT_KEYS,
            source=f"synthetic seed={seed}",
        ),
    }


if __name__ == "__main__":
    from pathlib import Path as _Path

    manifests = build_all(_Path(__file__).parent / "data")
    for role, manifest in manifests.items():
        short_hash = manifest.content_hash[:12]
        print(f"{role}: {manifest.dataset} rows={manifest.row_count} hash={short_hash}")
