"""Position episodes from lagged weights and the engine's pnl frame (ADR-0061, ADR-0062).

Hand computation (one symbol X, ts 10..60, closes 100, 110, 99, 99, 108.9, 108.9, cash 1000):
weights  0, 1, 1, 0, -0.5, -0.5 give the equity 1000, 1100, 990, 990, 940.5, 940.5 and the gross
per-bar pnl 0, 100 (1000*1*0.10), -110 (1100*1*-0.10), 0, -49.5 (990*-0.5*0.10), 0.
Episode 1 is long and held over the bars at ts 20 and 30: entered at the close of the bar before
the first held bar (ts 10), exited at the close of the last held bar (ts 30); its pnl is
100 - 110 = -10 (equals 990 - 1000). The short at ts 50..60 is still open at the last bar, so it is
not a closed episode.
"""

from __future__ import annotations

import polars as pl
import pytest

from crucible.analytics.trades import EPISODE_SCHEMA, build_episodes


def _inputs(
    weights: list[float], closes: list[float], symbol: str = "X", initial: float = 1000.0
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(weights frame, pnl frame): pnl is prior equity * weight * return, compounded by hand."""
    ts = [10 * (i + 1) for i in range(len(closes))]
    frame = pl.DataFrame(
        {"ts": ts, "symbol": [symbol] * len(ts), "weight": [float(w) for w in weights]}
    )
    pnl_values: list[float] = []
    value = initial
    previous: float | None = None
    for w, c in zip(weights, closes, strict=True):
        ret = 0.0 if previous is None else c / previous - 1.0
        pnl_values.append(value * w * ret)
        value *= 1.0 + w * ret
        previous = c
    pnl = pl.DataFrame({"ts": ts, "symbol": [symbol] * len(ts), "pnl": pnl_values})
    return frame, pnl


def test_a_long_episode_is_closed_and_a_trailing_open_short_is_not() -> None:
    weights, pnl = _inputs([0, 1, 1, 0, -0.5, -0.5], [100, 110, 99, 99, 108.9, 108.9])
    out = build_episodes(weights, pnl)
    assert out.schema == pl.Schema(EPISODE_SCHEMA)
    assert out.height == 1
    row = out.row(0, named=True)
    assert (row["symbol"], row["side"]) == ("X", "long")
    assert (row["entry_ts"], row["exit_ts"], row["holding_ns"]) == (10, 30, 20)
    assert row["avg_abs_weight"] == pytest.approx(1.0)
    assert row["pnl"] == pytest.approx(-10.0)


def test_a_sign_flip_closes_one_episode_and_opens_the_next_at_the_same_bar() -> None:
    # weights 1, 1, -1, -1, 0, 0: the long is held over ts 10, 20 (no earlier bar, so it enters at
    # its own first ts 10); the short is held over ts 30, 40 and entered at ts 20, the close of the
    # last long bar; it closes at ts 40 because the weight at ts 50 is 0
    weights, pnl = _inputs([1, 1, -1, -1, 0, 0], [100, 101, 102, 101, 100, 100])
    out = build_episodes(weights, pnl).sort("entry_ts")
    assert [(r["side"], r["entry_ts"], r["exit_ts"]) for r in out.to_dicts()] == [
        ("long", 10, 20),
        ("short", 20, 40),
    ]


def test_a_change_of_size_inside_a_run_does_not_split_the_episode() -> None:
    weights, pnl = _inputs([0, 0.5, 1.0, 0.25, 0, 0], [100, 101, 102, 103, 104, 105])
    out = build_episodes(weights, pnl)
    assert out.height == 1
    assert out["avg_abs_weight"][0] == pytest.approx((0.5 + 1.0 + 0.25) / 3)


def test_all_flat_weights_give_an_empty_log_with_the_schema() -> None:
    weights, pnl = _inputs([0, 0, 0, 0], [100, 101, 102, 103])
    out = build_episodes(weights, pnl)
    assert out.height == 0
    assert out.schema == pl.Schema(EPISODE_SCHEMA)


def test_symbols_are_independent_and_the_log_is_sorted() -> None:
    wa, pa = _inputs([0, 1, 0, 0], [100, 101, 102, 103], symbol="A")
    wb, pb = _inputs([1, 0, 0, 0], [50, 51, 52, 53], symbol="B")
    out = build_episodes(pl.concat([wa, wb]), pl.concat([pa, pb]))
    # B is held on the first bar only (no earlier bar: entry = its own ts 10, exit ts 10);
    # A is held over ts 20 (entered at ts 10); sorted by exit_ts then symbol: B (10) before A (20)
    assert out.select("symbol", "entry_ts", "exit_ts").rows() == [("B", 10, 10), ("A", 10, 20)]


def test_the_episode_pnl_is_the_sum_of_the_pnl_frame_over_the_held_bars() -> None:
    # a pnl frame the engine could have produced for a foreign symbol (FX included): the episode
    # takes it as given instead of recomputing it from prices
    weights = pl.DataFrame(
        {"ts": [10, 20, 30, 40], "symbol": ["F"] * 4, "weight": [0.0, 1.0, 1.0, 0.0]}
    )
    pnl = pl.DataFrame(
        {"ts": [10, 20, 30, 40], "symbol": ["F"] * 4, "pnl": [0.0, 110.0, -111.0, -0.1]}
    )
    out = build_episodes(weights, pnl)
    assert out.height == 1
    assert out["pnl"][0] == pytest.approx(-1.0)  # 110 - 111 over the two held bars


def test_a_weight_that_is_only_float_dust_does_not_open_an_episode() -> None:
    weights, pnl = _inputs([0, 1e-17, 1e-17, 0, 1, 0], [100, 110, 99, 99, 108.9, 108.9])
    out = build_episodes(weights, pnl)
    assert out.height == 1  # only the real position at ts 50 counts
    assert out.row(0, named=True)["entry_ts"] == 40
