"""Polymarket CSV importer (ADR-0052): hand-computed on tiny contracts.

Contract slug btc-updown-5m-1000: window [1000, 1300). With bar_seconds=2 a snapshot
at second s falls in the bucket [2*floor(s/2), +2) and its bar closes at the bucket end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.importers.polymarket import import_polymarket
from crucible.data.importers.spec import PolymarketSpec

NS = 10**9
HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)


def _row(
    start: int,
    ts: int,
    up: tuple[str, str],
    down: tuple[str, str],
    btc: str = "100.0",
    winner: str = "Up",
) -> str:
    up_bid, up_ask = up
    down_bid, down_ask = down
    return (
        f"btc-updown-5m-{start},{start},{ts - start},{up_ask},{up_bid},{down_ask},{down_bid},"
        f"100.0,{btc},0.0,{ts},True,{winner}"
    )


def _spec(tmp_path: Path, lines: list[str], **over: Any) -> PolymarketSpec:
    (tmp_path / "pm.csv").write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    raw: dict[str, Any] = {
        "kind": "polymarket_csv",
        "dataset": "pm",
        "input": str(tmp_path / "pm.csv"),
        "bar_seconds": 2,
    }
    raw.update(over)
    return PolymarketSpec.model_validate(raw)


def _bars(result: Any, symbol: str) -> list[tuple[int, float, float, float, float]]:
    frame = result.datasets[0].frame.filter(result.datasets[0].frame["symbol"] == symbol)
    return [
        (r["event_time"], r["open"], r["high"], r["low"], r["close"])
        for r in frame.sort("event_time").to_dicts()
    ]


def _run(spec: PolymarketSpec, **kw: Any) -> Any:
    return import_polymarket(
        spec, start=kw.get("start"), end=kw.get("end"), max_contracts=kw.get("max_contracts")
    )


def test_snapshots_become_bid_ask_mid_bars_closing_at_the_bucket_end(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), "100.0"),
        _row(1000, 1101, ("0.48", "0.52"), ("0.48", "0.52"), "101.0"),
        _row(1000, 1103, ("0.60", "0.64"), ("0.36", "0.40"), "102.0"),
    ]
    result = _run(_spec(tmp_path, lines))
    up = _bars(result, "BTC5M-1000-UP")
    assert up[0] == pytest.approx((1102 * NS, 0.42, 0.50, 0.42, 0.50))
    assert up[1] == pytest.approx((1104 * NS, 0.62, 0.62, 0.62, 0.62))
    down = _bars(result, "BTC5M-1000-DOWN")
    assert down[0] == pytest.approx((1102 * NS, 0.58, 0.58, 0.50, 0.50))
    assert down[1] == pytest.approx((1104 * NS, 0.38, 0.38, 0.38, 0.38))
    spot = _bars(result, "BTCUSD")
    assert spot[0] == pytest.approx((1102 * NS, 100.0, 101.0, 100.0, 101.0))
    assert spot[1] == pytest.approx((1104 * NS, 102.0, 102.0, 102.0, 102.0))
    frame = result.datasets[0].frame
    assert frame["available_at"].to_list() == frame["event_time"].to_list()
    assert set(frame["volume"].to_list()) == {0.0}


def test_settlement_bars_and_delistings_follow_the_recorded_winner(tmp_path: Path) -> None:
    lines = [_row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), winner="Down")]
    result = _run(_spec(tmp_path, lines))
    end = 1300 * NS
    assert _bars(result, "BTC5M-1000-UP")[-1] == pytest.approx((end, 0.001, 0.001, 0.001, 0.001))
    assert _bars(result, "BTC5M-1000-DOWN")[-1] == pytest.approx((end, 1.0, 1.0, 1.0, 1.0))
    actions = result.datasets[1]
    assert actions.dataset == "pm_actions"
    rows = actions.frame.sort("symbol").to_dicts()
    assert [r["symbol"] for r in rows] == ["BTC5M-1000-DOWN", "BTC5M-1000-UP"]
    assert {r["action"] for r in rows} == {"delisting"}
    assert {r["effective_at"] for r in rows} == {end}
    assert {r["available_at"] for r in rows} == {end}
    assert {r["value"] for r in rows} == {None}
    assert {r["pay_at"] for r in rows} == {None}


def test_invalid_snapshots_are_dropped_by_reason_and_an_empty_bid_is_kept(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1000, 1101, ("0.70", "0.60"), ("0.56", "0.60")),  # crossed YES
        _row(1000, 1102, ("0", "0"), ("0.56", "0.60")),  # ask not positive
        _row(1000, 1103, ("", "0.50"), ("0.56", "0.60")),  # null bid
        _row(1000, 1104, ("0", "0.01"), ("0.56", "0.60")),  # empty bid side: mid 0.005
    ]
    result = _run(_spec(tmp_path, lines, bar_seconds=1, max_dropped_fraction=1.0))
    up = _bars(result, "BTC5M-1000-UP")
    assert [b[0] for b in up] == [1101 * NS, 1105 * NS, 1300 * NS]
    assert up[1][4] == pytest.approx(0.005)
    assert result.report.dropped == {
        "up_ask_not_positive": 1,
        "up_crossed": 1,
        "up_null": 1,
    }
    assert len(_bars(result, "BTC5M-1000-DOWN")) == 6  # five snapshots plus settlement


def test_a_contract_without_a_recorded_winner_is_dropped(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1300, 1400, ("0.40", "0.44"), ("0.56", "0.60"), winner=""),
    ]
    result = _run(_spec(tmp_path, lines, max_dropped_fraction=1.0))
    symbols = set(result.datasets[0].frame["symbol"].to_list())
    assert "BTC5M-1300-UP" not in symbols
    assert "BTC5M-1000-UP" in symbols
    assert result.report.extra["contracts_unresolved"] == 1
    assert result.report.dropped["unresolved_contract_rows"] == 1


def test_spot_bars_merge_across_contracts_and_skip_invalid_prices(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), "100.0"),
        _row(1000, 1101, ("0.40", "0.44"), ("0.56", "0.60"), ""),  # no spot price
        _row(1300, 1400, ("0.40", "0.44"), ("0.56", "0.60"), "105.0"),
    ]
    result = _run(_spec(tmp_path, lines, max_dropped_fraction=1.0))
    spot = _bars(result, "BTCUSD")
    assert [b[0] for b in spot] == [1102 * NS, 1402 * NS]
    assert result.report.dropped["spot_invalid"] == 1


def test_snapshots_outside_the_window_are_excluded_and_counted(tmp_path: Path) -> None:
    """ts 999 is before the window; ts 1299 falls in the bucket that closes at the window end
    (1300), so it could not be known before settlement; ts 1297 closes at 1298 and is kept."""
    lines = [
        _row(1000, 999, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1000, 1297, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1000, 1299, ("0.40", "0.44"), ("0.56", "0.60")),
    ]
    result = _run(_spec(tmp_path, lines, max_dropped_fraction=1.0))
    up = _bars(result, "BTC5M-1000-UP")
    assert [b[0] for b in up] == [1298 * NS, 1300 * NS]
    assert result.report.dropped["before_window"] == 1
    assert result.report.dropped["at_or_after_window_end"] == 1


def test_too_many_invalid_snapshots_refuse_the_import(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1000, 1101, ("0.70", "0.60"), ("0.56", "0.60")),
        _row(1000, 1102, ("0.70", "0.60"), ("0.56", "0.60")),
        _row(1000, 1103, ("0.70", "0.60"), ("0.56", "0.60")),
    ]
    with pytest.raises(ConfigurationError, match="max_dropped_fraction"):
        _run(_spec(tmp_path, lines, max_dropped_fraction=0.1))


def _three_contracts(tmp_path: Path, **over: Any) -> PolymarketSpec:
    lines = [_row(s, s + 100, ("0.40", "0.44"), ("0.56", "0.60")) for s in (1000, 1300, 1600)]
    return _spec(tmp_path, lines, **over)


def test_max_contracts_keeps_the_earliest_contracts(tmp_path: Path) -> None:
    result = _run(_three_contracts(tmp_path), max_contracts=2)
    symbols = set(result.datasets[0].frame["symbol"].to_list())
    assert {"BTC5M-1000-UP", "BTC5M-1300-UP"} <= symbols
    assert "BTC5M-1600-UP" not in symbols


def test_start_and_end_select_contracts_by_window_start(tmp_path: Path) -> None:
    result = _run(_three_contracts(tmp_path), start=1300 * NS, end=1600 * NS)
    symbols = set(result.datasets[0].frame["symbol"].to_list())
    assert "BTC5M-1300-UP" in symbols
    assert "BTC5M-1000-UP" not in symbols
    assert "BTC5M-1600-UP" not in symbols


def test_a_file_without_the_winner_column_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pm.csv").write_text(
        "slug,start_time,timestamp_log,ask_YES,bid_YES,ask_NO,bid_NO,btc_current\n"
        "btc-updown-5m-1000,1000,1100,0.44,0.40,0.60,0.56,100.0\n",
        encoding="utf-8",
    )
    spec = PolymarketSpec.model_validate(
        {"kind": "polymarket_csv", "dataset": "pm", "input": str(tmp_path / "pm.csv")}
    )
    with pytest.raises(ConfigurationError, match="winner"):
        _run(spec)


def test_a_nan_quote_is_dropped_and_counted_as_null(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1000, 1101, ("0.40", "nan"), ("0.56", "0.60")),
    ]
    result = _run(_spec(tmp_path, lines, bar_seconds=1, max_dropped_fraction=1.0))
    assert result.report.dropped == {"up_null": 1}
    up = _bars(result, "BTC5M-1000-UP")
    assert [b[0] for b in up] == [1101 * NS, 1300 * NS]


def test_conflicting_winners_inside_one_contract_are_refused(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), winner="Down"),
        _row(1000, 1102, ("0.40", "0.44"), ("0.56", "0.60"), winner="Up"),
    ]
    with pytest.raises(ConfigurationError, match="btc-updown-5m-1000"):
        _run(_spec(tmp_path, lines))


def test_an_import_where_no_contract_survives_is_refused(tmp_path: Path) -> None:
    lines = [_row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), winner="Yes")]
    with pytest.raises(ConfigurationError, match="no contract"):
        _run(_spec(tmp_path, lines))


def test_timestamps_in_milliseconds_leave_nothing_and_are_refused(tmp_path: Path) -> None:
    lines = [_row(1000, 1100000, ("0.40", "0.44"), ("0.56", "0.60"))]
    with pytest.raises(ConfigurationError, match="no snapshot"):
        _run(_spec(tmp_path, lines))


_QUOTES = ["bid_open", "ask_open", "bid_close", "ask_close"]


def _quotes(result: Any, symbol: str) -> list[tuple[Any, ...]]:
    frame = result.datasets[0].frame.filter(result.datasets[0].frame["symbol"] == symbol)
    return [tuple(r[c] for c in _QUOTES) for r in frame.sort("event_time").to_dicts()]


def test_contract_bars_carry_the_first_and_last_quote_of_each_bucket(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.38", "0.42"), ("0.56", "0.60")),
        _row(1000, 1101, ("0.41", "0.43"), ("0.48", "0.52")),
        _row(1000, 1103, ("0.60", "0.64"), ("0.36", "0.40")),
    ]
    result = _run(_spec(tmp_path, lines))
    up = _quotes(result, "BTC5M-1000-UP")
    # bucket (1100, 1102]: first quote 0.38/0.42, last 0.41/0.43; the bar's mids are unchanged
    assert up[0] == pytest.approx((0.38, 0.42, 0.41, 0.43))
    assert up[1] == pytest.approx((0.60, 0.64, 0.60, 0.64))
    assert _bars(result, "BTC5M-1000-UP")[0] == pytest.approx((1102 * NS, 0.40, 0.42, 0.40, 0.42))
    assert _quotes(result, "BTC5M-1000-DOWN")[0] == pytest.approx((0.56, 0.60, 0.48, 0.52))


def test_a_zero_bid_is_kept_in_the_quote_columns(tmp_path: Path) -> None:
    lines = [_row(1000, 1100, ("0", "0.05"), ("0.90", "0.95"))]
    result = _run(_spec(tmp_path, lines))
    assert _quotes(result, "BTC5M-1000-UP")[0] == pytest.approx((0.0, 0.05, 0.0, 0.05))


def test_settlement_bars_have_no_spread_and_spot_bars_no_quote(tmp_path: Path) -> None:
    lines = [_row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"), winner="Down")]
    result = _run(_spec(tmp_path, lines))
    assert _quotes(result, "BTC5M-1000-DOWN")[-1] == pytest.approx((1.0, 1.0, 1.0, 1.0))
    assert _quotes(result, "BTC5M-1000-UP")[-1] == pytest.approx((0.001, 0.001, 0.001, 0.001))
    assert _quotes(result, "BTCUSD") == [(None, None, None, None)]


def test_the_output_uses_the_quoted_schema_and_passes_the_quote_check(tmp_path: Path) -> None:
    import polars as pl

    from crucible.data.contracts import QUOTED_BAR_SCHEMA
    from crucible.data.quality import QuoteConsistency

    lines = [
        _row(1000, 1100, ("0.38", "0.42"), ("0.56", "0.60")),
        _row(1000, 1101, ("0", "0.05"), ("0.90", "0.95")),
    ]
    result = _run(_spec(tmp_path, lines))
    output = result.datasets[0]
    assert output.schema == QUOTED_BAR_SCHEMA
    assert list(output.frame.columns) == list(QUOTED_BAR_SCHEMA)
    QuoteConsistency().run(output.frame.lazy(), None)
    assert isinstance(output.frame, pl.DataFrame)


def test_a_snapshot_with_a_nan_or_missing_timestamp_is_dropped_and_counted(tmp_path: Path) -> None:
    good = _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"))
    nan = "btc-updown-5m-1000,1000,0,0.44,0.40,0.60,0.56,100.0,100.0,0.0,nan,True,Up"
    result = _run(_spec(tmp_path, [good, nan], max_dropped_fraction=1.0))
    assert result.report.dropped["invalid_ts"] == 1


def test_a_non_numeric_start_time_is_refused_with_the_slug(tmp_path: Path) -> None:
    bad = "btc-updown-5m-1000,soon,0,0.44,0.40,0.60,0.56,100.0,100.0,0.0,1100,True,Up"
    with pytest.raises(ConfigurationError, match=r"start_time.*btc-updown-5m-1000"):
        _run(_spec(tmp_path, [bad]))


def test_unresolved_rows_are_counted_only_inside_the_selected_window(tmp_path: Path) -> None:
    lines = [
        _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60")),
        _row(1300, 1400, ("0.40", "0.44"), ("0.56", "0.60"), winner=""),
        _row(1600, 1700, ("0.40", "0.44"), ("0.56", "0.60"), winner=""),
    ]
    result = _run(_spec(tmp_path, lines, max_dropped_fraction=1.0), start=1000 * NS, end=1300 * NS)
    assert result.report.dropped.get("unresolved_contract_rows", 0) == 0
    everything = _run(_spec(tmp_path, lines, max_dropped_fraction=1.0))
    assert everything.report.dropped["unresolved_contract_rows"] == 2


def test_tied_timestamps_give_the_same_bar_whatever_the_row_order(tmp_path: Path) -> None:
    one = _row(1000, 1100, ("0.40", "0.44"), ("0.56", "0.60"))
    two = _row(1000, 1100, ("0.48", "0.52"), ("0.48", "0.52"))
    first = _run(_spec(tmp_path, [one, two]))
    other = tmp_path / "other"
    other.mkdir()
    second = _run(_spec(other, [two, one]))
    assert (
        first.datasets[0]
        .frame.sort(["symbol", "event_time"])
        .equals(second.datasets[0].frame.sort(["symbol", "event_time"]))
    )
