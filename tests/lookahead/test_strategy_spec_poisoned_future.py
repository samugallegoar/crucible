"""Poisoned-future harness for strategy specs (ADR-0067, AGENTS.md section 7).

Every template, and a spec using every indicator, goes through the compiled signal and the
vectorized engine; absurd prices injected after a cutoff must not change one score, weight or
equity value at or before it. A second check, the prefix property, shows the signal at bar ``t``
is the same whether or not later bars exist: the decision is a function of the past only.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy_spec import canonical_spec, parse_spec, spec_signal
from crucible.strategy_spec.templates import TEMPLATES
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

DAY = 86_400 * 1_000_000_000
DATASET = DatasetId("spec_bars")
EVERY_INDICATOR = {
    "direction": "long_short",
    "entry": {
        "long": {
            "all": [
                "rsi(7) < 45",
                {"any": ["roc(5) > -3", "close > bb_lower(10, 1.5)", "close > highest(5)"]},
            ]
        },
        "short": {"all": ["rsi(7) >= 45", "ema(5) crosses_below sma(12)"]},
    },
    "exit": {"long": "close < lowest(4)", "short": "sma(3, volume) > 1"},
    "risk": {"stop_loss_pct": 4, "take_profit_pct": 6, "max_holding_bars": 15},
}


def _bars(n: int = 300, seed: int = 11) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for symbol, drift in (("AAA", 0.0004), ("BBB", -0.0002)):
        close = 50.0 * np.cumprod(1.0 + rng.normal(drift, 0.015, n))
        for i in range(n):
            ts = 19_000 * DAY + i * DAY
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": ts,
                    "available_at": ts,
                    "open": float(close[i]),
                    "high": float(close[i]) * 1.01,
                    "low": float(close[i]) * 0.99,
                    "close": float(close[i]),
                    "volume": 1e6 + 1e4 * float(rng.random()),
                }
            )
    return pl.from_dicts(rows, schema=BAR_SCHEMA)


def _store(root: Path, bars: pl.DataFrame) -> ParquetDataStore:
    build_dataset(root, DATASET, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    return ParquetDataStore(root)


def _run(store: ParquetDataStore, spec: dict[str, object], end: int):  # type: ignore[no-untyped-def]
    return VectorizedBacktestEngine().run(
        VectorizedConfig(
            store=store,
            bars_dataset=DATASET,
            signal=spec_signal,
            params={"spec": canonical_spec(parse_spec(spec))},
            initial_cash=Decimal("100000"),
            realism_level=RealismLevel.FRICTIONLESS,
            start=TimestampNs(0),
            end=TimestampNs(end),
        )
    )


SPECS = {**{name: t.spec for name, t in TEMPLATES.items()}, "every_indicator": EVERY_INDICATOR}


@pytest.mark.lookahead
@pytest.mark.parametrize("name", sorted(SPECS))
def test_poisoning_the_future_changes_nothing_at_or_before_the_cutoff(
    name: str, tmp_path: Path
) -> None:
    bars = _bars()
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]
    end = int(bars.get_column("available_at").max())  # type: ignore[arg-type]
    poison = pl.col("available_at") > cutoff
    poisoned = bars.with_columns(
        [
            pl.when(poison).then(pl.col(c) * 1_000.0).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close", "volume")
        ]
    )
    clean = _run(_store(tmp_path / "clean", bars), SPECS[name], end)
    dirty = _run(_store(tmp_path / "dirty", poisoned), SPECS[name], end)
    for label in ("scores", "weights", "equity"):
        before = getattr(clean, label).filter(pl.col("ts") <= cutoff)
        after = getattr(dirty, label).filter(pl.col("ts") <= cutoff)
        assert before.equals(after), f"{name}.{label}: a value at or before the cutoff changed"


@pytest.mark.lookahead
@pytest.mark.parametrize("name", sorted(SPECS))
def test_the_signal_at_t_does_not_depend_on_bars_after_t(name: str) -> None:
    bars = _bars(n=160)
    spec = {"spec": canonical_spec(parse_spec(SPECS[name]))}
    full = spec_signal(bars.lazy(), spec).collect().sort(["symbol", "ts"])
    for keep in (40, 80, 120):
        cut_ts = 19_000 * DAY + (keep - 1) * DAY
        prefix = bars.filter(pl.col("event_time") <= cut_ts)
        short = spec_signal(prefix.lazy(), spec).collect().sort(["symbol", "ts"])
        assert short.equals(full.filter(pl.col("ts") <= cut_ts)), f"{name}: prefix {keep} differs"
