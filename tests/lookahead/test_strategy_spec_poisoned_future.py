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


# --- time-of-day rules on intraday bars (ADR-0073) -----------------------------------------

HOUR = 3_600 * 1_000_000_000
SESSION = {"calendar": "XNYS", "interval": "1h"}
SESSION_SPECS = {
    "flat_by_close": {
        "entry": {"long": "sma(5) crosses_above sma(12)"},
        "exit": {"long": "sma(5) crosses_below sma(12)"},
        "session": {"flat_by_close": True},
    },
    "entry_window": {
        "direction": "long_short",
        "entry": {"long": "rsi(7) < 40", "short": "rsi(7) > 60"},
        "risk": {"max_holding_bars": 5},
        "session": {"entry_window": {"start": "10:30", "end": "14:30"}},
    },
    "both": {
        "entry": {"long": "close > highest(6)"},
        "session": {"flat_by_close": True, "entry_window": {"start": "11:30", "end": "13:30"}},
    },
    "market_on_close": {
        "entry": {"long": "sma(5) crosses_above sma(12)"},
        "session": {"flat_by_close": True, "close_with": "market_on_close"},
    },
    "exit_at": {
        "direction": "long_short",
        "entry": {"long": "rsi(7) < 40", "short": "rsi(7) > 60"},
        "session": {"exit_at": "13:30"},
    },
    "time_condition": {
        "entry": {"long": {"all": ["close > sma(8)", "time >= 11:30", "time < 14:30"]}},
        "exit": {"long": {"any": ["close < sma(8)", "time >= 15:30"]}},
    },
}


def _hourly_bars(seed: int = 5) -> pl.DataFrame:
    from crucible.data.calendars import get_trading_calendar

    start, end = TimestampNs(19_000 * DAY), TimestampNs(19_060 * DAY)
    cal = get_trading_calendar("XNYS", start=start, end=end)
    stamps: list[int] = []
    for close, open_ in sorted(cal.session_open_by_close(start, end).items()):
        t = open_ + HOUR
        while t < close:
            stamps.append(t)
            t += HOUR
        stamps.append(close)
    rng = np.random.default_rng(seed)
    rows = []
    for symbol in ("AAA", "BBB"):
        close_px = 50.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.006, len(stamps)))
        for t, px in zip(stamps, close_px, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": t,
                    "available_at": t,
                    "open": float(px),
                    "high": float(px) * 1.003,
                    "low": float(px) * 0.997,
                    "close": float(px),
                    "volume": 1e5,
                }
            )
    return pl.from_dicts(rows, schema=BAR_SCHEMA)


def _session_params(name: str) -> dict[str, object]:
    return {"spec": canonical_spec(parse_spec(SESSION_SPECS[name])), "session": SESSION}


@pytest.mark.lookahead
@pytest.mark.parametrize("name", sorted(SESSION_SPECS))
def test_session_rules_do_not_read_the_future(name: str, tmp_path: Path) -> None:
    bars = _hourly_bars()
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]
    end = int(bars.get_column("available_at").max())  # type: ignore[arg-type]
    poison = pl.col("available_at") > cutoff
    poisoned = bars.with_columns(
        [
            pl.when(poison).then(pl.col(c) * 1_000.0).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close", "volume")
        ]
    )

    def run(store: ParquetDataStore):  # type: ignore[no-untyped-def]
        return VectorizedBacktestEngine().run(
            VectorizedConfig(
                store=store,
                bars_dataset=DATASET,
                signal=spec_signal,
                params=_session_params(name),
                initial_cash=Decimal("100000"),
                realism_level=RealismLevel.FRICTIONLESS,
                start=TimestampNs(0),
                end=TimestampNs(end),
            )
        )

    clean = run(_store(tmp_path / "clean", bars))
    dirty = run(_store(tmp_path / "dirty", poisoned))
    for label in ("scores", "weights", "equity"):
        before = getattr(clean, label).filter(pl.col("ts") <= cutoff)
        after = getattr(dirty, label).filter(pl.col("ts") <= cutoff)
        assert before.equals(after), f"{name}.{label}: a value at or before the cutoff changed"


@pytest.mark.lookahead
@pytest.mark.parametrize("name", sorted(SESSION_SPECS))
def test_session_rules_at_t_do_not_depend_on_bars_after_t(name: str) -> None:
    # the next-to-last bar of a session is known from the schedule, not from the next bar: a cut
    # right before a session's last bar must give the same decision as the full history
    bars = _hourly_bars()
    params = _session_params(name)
    full = spec_signal(bars.lazy(), params).collect().sort(["symbol", "ts"])
    stamps = sorted(set(bars.get_column("event_time").to_list()))
    for cut_ts in stamps[40::37]:
        prefix = bars.filter(pl.col("event_time") <= cut_ts)
        short = spec_signal(prefix.lazy(), params).collect().sort(["symbol", "ts"])
        assert short.equals(full.filter(pl.col("ts") <= cut_ts)), f"{name}: prefix {cut_ts}"
