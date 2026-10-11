"""Time-of-day rules (ADR-0073): ``session.flat_by_close`` and ``session.entry_window`` on intraday
bars, on the headline (vectorized) engine and on the event-driven realism re-run."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import TimestampNs
from crucible.data.calendars import get_trading_calendar
from crucible.product.backtest import run_backtest
from crucible.strategy_spec import load_spec, parse_spec
from crucible.strategy_spec.compile import session_masks
from tests.integration.test_product_backtest import request
from tests.integration.test_product_intraday import END, HOUR, START, _hourly_home, _ns

FLAT_SPEC = {
    "entry": {"long": "sma(5) crosses_above sma(12)"},
    "exit": {"long": "sma(5) crosses_below sma(12)"},
    "session": {"flat_by_close": True},
}
SESSION = {"calendar": "XNYS", "interval": "1h"}


def _closes(first: dt.date, last: dt.date) -> list[int]:
    s, e = TimestampNs(_ns(first)), TimestampNs(_ns(last) + 2 * 86_400 * 10**9)
    cal = get_trading_calendar("XNYS", start=s, end=e)
    return [int(c) for c in cal.session_closes(s, e)]


def _utc(y: int, m: int, d: int, hh: int, mm: int) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.UTC).timestamp() * 1e9)


# --- the masks -----------------------------------------------------------------------------


def test_flat_by_close_marks_the_last_two_hourly_bars_of_each_session() -> None:
    # 2021-01-04, New York winter time (UTC-5): bars end 10:30 ... 15:30, 16:00
    ends = [_utc(2021, 1, 4, h, m) for h, m in ((15, 30), (16, 30), (19, 30), (20, 30), (21, 0))]
    force, entry_ok = session_masks(parse_spec(FLAT_SPEC), np.asarray(ends), {"session": SESSION})
    assert force.tolist() == [False, False, False, True, True]  # 15:30 and 16:00 local
    assert entry_ok.tolist() == [True, True, True, False, False]


@pytest.mark.parametrize(
    ("month", "utc_hour"),
    [(1, 15), (7, 14)],  # 10:30 New York is 15:30 UTC in winter and 14:30 UTC in summer
    ids=["winter", "summer"],
)
def test_the_entry_window_is_read_in_exchange_time(month: int, utc_hour: int) -> None:
    spec = parse_spec(
        {
            "entry": {"long": "close > sma(3)"},
            "risk": {"max_holding_bars": 2},
            "session": {"entry_window": {"start": "10:30", "end": "10:30"}},
        }
    )
    day = 4 if month == 1 else 6  # 2021-01-04 and 2021-07-06 are sessions
    ends = np.asarray(
        [_utc(2021, month, day, utc_hour, 30), _utc(2021, month, day, utc_hour + 1, 30)]
    )
    _, entry_ok = session_masks(spec, ends, {"session": SESSION})
    assert entry_ok.tolist() == [True, False]


def test_session_rules_need_the_schedule_and_intraday_bars() -> None:
    spec = parse_spec(FLAT_SPEC)
    ends = np.asarray([_utc(2021, 1, 4, 21, 0)])
    with pytest.raises(ConfigurationError, match=r"params\.session"):
        session_masks(spec, ends, {})
    with pytest.raises(ConfigurationError, match="intraday"):
        session_masks(spec, ends, {"session": {"calendar": "XNYS", "interval": "1d"}})


@pytest.mark.parametrize(
    ("session", "match"),
    [
        ({}, "session is empty"),
        ({"entry_window": {"start": "9:30", "end": "10:00"}}, "not a time"),
        ({"entry_window": {"start": "15:00", "end": "10:00"}}, "cannot cross midnight"),
    ],
)
def test_malformed_session_rules_are_refused(session: dict[str, object], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        parse_spec({**FLAT_SPEC, "session": session})


def test_flat_by_close_is_a_way_out_for_an_entry_without_an_exit() -> None:
    parse_spec({"entry": {"long": "close > sma(5)"}, "session": {"flat_by_close": True}})


# --- end to end ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flat_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Path]:
    root = tmp_path_factory.mktemp("tod")
    home = _hourly_home(root)
    doc = run_backtest(
        request(
            home,
            spec=load_spec(FLAT_SPEC),
            symbols=["TRENDY"],
            start=START.isoformat(),
            end=END.isoformat(),
            interval="1h",
            null_iterations=0,
            realism_check=True,
        )
    )
    return doc, home.experiments


def test_the_headline_run_never_holds_across_a_close(
    flat_run: tuple[dict[str, object], Path],
) -> None:
    doc, _ = flat_run
    trades = doc["trades"]
    assert isinstance(trades, list)
    assert trades, "the synthetic trend should make the crossover trade"
    closes = _closes(START, END)
    for trade in trades:
        assert isinstance(trade, dict)
        assert trade["entry_date"] == trade["exit_date"], f"held overnight: {trade}"
        exit_ts = int(
            dt.datetime.strptime(str(trade["exit_time"]), "%Y-%m-%dT%H:%MZ")
            .replace(tzinfo=dt.UTC)
            .timestamp()
            * 1e9
        )
        close = next(c for c in closes if c >= exit_ts)
        assert exit_ts < close, f"exited at the close itself, not before it: {trade}"


def test_the_realism_rerun_is_flat_at_every_close(
    flat_run: tuple[dict[str, object], Path],
) -> None:
    _, experiments = flat_run
    event_runs = [
        p.parent
        for p in experiments.glob("*/manifest.json")
        if json.loads(p.read_text(encoding="utf-8")).get("runtime") == "backtest"
    ]
    assert len(event_runs) == 1
    fills = pl.read_parquet(event_runs[0] / "fills.parquet").sort("ts")
    assert fills.height > 0
    signed = (
        np.where(fills.get_column("side").to_numpy() == "buy", 1.0, -1.0)
        * fills.get_column("qty").cast(pl.Float64).to_numpy()
    )
    held = np.cumsum(signed)
    ts = fills.get_column("ts").to_numpy()
    for close in _closes(START, END):
        position = held[ts <= close][-1] if np.any(ts <= close) else 0.0
        assert abs(position) < 1e-9, f"event-driven run held {position} at close ts={close}"


def test_session_rules_on_daily_bars_are_refused(tmp_path: Path) -> None:
    from tests.integration.test_product_backtest import seed_home

    home = seed_home(tmp_path)
    with pytest.raises(ConfigurationError, match="need intraday bars"):
        run_backtest(request(home, spec=load_spec(FLAT_SPEC), null_iterations=0))


def test_the_explanation_says_flat_by_close() -> None:
    from crucible.strategy_spec import describe_spec

    lines = " ".join(describe_spec(parse_spec(FLAT_SPEC)))
    assert "flat by the close" in lines
    assert HOUR > 0


# --- market on close, exit_at and `time` end to end (ADR-0074) --------------------------------

from zoneinfo import ZoneInfo  # noqa: E402

NEW_YORK = ZoneInfo("America/New_York")


def _ts(stamp: object) -> int:
    return int(
        dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.UTC).timestamp() * 1e9
    )


def _local(stamp: object) -> str:
    return (
        dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%MZ")
        .replace(tzinfo=dt.UTC)
        .astimezone(NEW_YORK)
        .strftime("%H:%M")
    )


def _run(root: Path, spec: dict[str, object], *, realism: bool) -> tuple[dict[str, object], Path]:
    home = _hourly_home(root)
    doc = run_backtest(
        request(
            home,
            spec=load_spec(spec),
            symbols=["TRENDY"],
            start=START.isoformat(),
            end=END.isoformat(),
            interval="1h",
            null_iterations=0,
            realism_check=realism,
        )
    )
    return doc, home.experiments


def _event_run(experiments: Path) -> Path:
    runs = [
        p.parent
        for p in experiments.glob("*/manifest.json")
        if json.loads(p.read_text(encoding="utf-8")).get("runtime") == "backtest"
    ]
    assert len(runs) == 1
    return runs[0]


MOC_SPEC = {
    "entry": {"long": "sma(5) crosses_above sma(12)"},
    "exit": {"long": "sma(5) crosses_below sma(12)"},
    "session": {"flat_by_close": True, "close_with": "market_on_close"},
}


@pytest.fixture(scope="module")
def moc_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Path]:
    return _run(tmp_path_factory.mktemp("moc"), MOC_SPEC, realism=True)


def test_market_on_close_keeps_the_last_bar_on_the_headline(
    moc_run: tuple[dict[str, object], Path],
) -> None:
    doc, _ = moc_run
    trades = doc["trades"]
    assert isinstance(trades, list)
    assert trades
    closes = set(_closes(START, END))
    forced = [t for t in trades if isinstance(t, dict) and _ts(t["exit_time"]) in closes]
    assert forced, "some position should be carried to the close"
    for trade in trades:
        assert isinstance(trade, dict)
        assert trade["entry_date"] == trade["exit_date"], f"held overnight: {trade}"


def test_the_realism_rerun_fills_market_on_close_orders_at_the_close(
    moc_run: tuple[dict[str, object], Path],
) -> None:
    _, experiments = moc_run
    run = _event_run(experiments)
    orders = pl.read_parquet(run / "orders.parquet")
    fills = pl.read_parquet(run / "fills.parquet")
    moc_ids = orders.filter(pl.col("type") == "market_on_close").get_column("order_id")
    moc_fills = fills.filter(pl.col("order_id").is_in(moc_ids.implode()))
    assert moc_fills.height > 0, "the event-driven run should have closed at the auction"
    closes = set(_closes(START, END))
    assert set(moc_fills.get_column("ts").to_list()) <= closes  # filled at session closes only
    signed = (
        np.where(fills.get_column("side").to_numpy() == "buy", 1.0, -1.0)
        * fills.get_column("qty").cast(pl.Float64).to_numpy()
    )
    order = np.argsort(fills.get_column("ts").to_numpy(), kind="stable")
    held = np.cumsum(signed[order])
    ts = fills.get_column("ts").to_numpy()[order]
    for close in closes:
        position = held[ts <= close][-1] if np.any(ts <= close) else 0.0
        assert abs(position) < 1e-9, f"event-driven run held {position} at close ts={close}"


def test_exit_at_closes_positions_and_blocks_entries_from_that_time(tmp_path: Path) -> None:
    spec = {
        "entry": {"long": "sma(5) crosses_above sma(12)"},
        "exit": {"long": "sma(5) crosses_below sma(12)"},
        "session": {"exit_at": "12:30"},
    }
    doc, _ = _run(tmp_path, spec, realism=False)
    trades = doc["trades"]
    assert isinstance(trades, list)
    assert trades
    for trade in trades:
        assert isinstance(trade, dict)
        assert _local(trade["entry_time"]) < "12:30", f"entered after exit_at: {trade}"
        assert trade["entry_date"] == trade["exit_date"]
        assert _local(trade["exit_time"]) <= "12:30", f"held past exit_at: {trade}"


def test_a_time_condition_restricts_entries(tmp_path: Path) -> None:
    spec = {
        "entry": {"long": {"all": ["sma(5) crosses_above sma(12)", "time <= 11:30"]}},
        "exit": {"long": "sma(5) crosses_below sma(12)"},
    }
    doc, _ = _run(tmp_path, spec, realism=False)
    trades = doc["trades"]
    assert isinstance(trades, list)
    assert trades
    for trade in trades:
        assert isinstance(trade, dict)
        assert _local(trade["entry_time"]) <= "11:30", f"entered after 11:30: {trade}"
