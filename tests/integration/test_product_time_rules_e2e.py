"""Market-on-close, ``exit_at`` and ``time`` end to end through the one-step backtest (ADR-0074).

Each feature is its own class so a parallel run (``--dist loadscope``) can put the three backtests
on different workers (ADR-0075); the window is two months of hourly XNYS bars, enough for every
rule to act many times."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from crucible.core.types import TimestampNs
from crucible.data.calendars import get_trading_calendar
from crucible.product.backtest import run_backtest
from crucible.strategy_spec import load_spec
from tests.integration.test_product_backtest import request
from tests.integration.test_product_intraday import START, _hourly_home, _ns

WINDOW_END = dt.date(2021, 3, 1)
NEW_YORK = ZoneInfo("America/New_York")
MOC_SPEC = {
    "entry": {"long": "sma(5) crosses_above sma(12)"},
    "exit": {"long": "sma(5) crosses_below sma(12)"},
    "session": {"flat_by_close": True, "close_with": "market_on_close"},
}


def _closes() -> set[int]:
    s, e = TimestampNs(_ns(START)), TimestampNs(_ns(WINDOW_END) + 2 * 86_400 * 10**9)
    cal = get_trading_calendar("XNYS", start=s, end=e)
    return {int(c) for c in cal.session_closes(s, e)}


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
    home = _hourly_home(root, end=WINDOW_END)
    doc = run_backtest(
        request(
            home,
            spec=load_spec(spec),
            symbols=["TRENDY"],
            start=START.isoformat(),
            end=WINDOW_END.isoformat(),
            interval="1h",
            null_iterations=0,
            realism_check=realism,
        )
    )
    return doc, home.experiments


def _trades(doc: dict[str, object]) -> list[dict[str, object]]:
    trades = doc["trades"]
    assert isinstance(trades, list)
    assert trades, "the synthetic trend should make the rules trade"
    return [t for t in trades if isinstance(t, dict)]


@pytest.fixture(scope="class")
def moc_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Path]:
    return _run(tmp_path_factory.mktemp("moc"), MOC_SPEC, realism=True)


class TestMarketOnClose:
    def test_market_on_close_keeps_the_last_bar_on_the_headline(
        self, moc_run: tuple[dict[str, object], Path]
    ) -> None:
        doc, _ = moc_run
        trades = _trades(doc)
        closes = _closes()
        assert any(_ts(t["exit_time"]) in closes for t in trades), "some exit is at the close"
        for trade in trades:
            assert trade["entry_date"] == trade["exit_date"], f"held overnight: {trade}"

    def test_the_realism_rerun_fills_market_on_close_orders_at_the_close(
        self, moc_run: tuple[dict[str, object], Path]
    ) -> None:
        _, experiments = moc_run
        runs = [
            p.parent
            for p in experiments.glob("*/manifest.json")
            if json.loads(p.read_text(encoding="utf-8")).get("runtime") == "backtest"
        ]
        assert len(runs) == 1
        orders = pl.read_parquet(runs[0] / "orders.parquet")
        fills = pl.read_parquet(runs[0] / "fills.parquet")
        moc_ids = orders.filter(pl.col("type") == "market_on_close").get_column("order_id")
        moc_fills = fills.filter(pl.col("order_id").is_in(moc_ids.implode()))
        assert moc_fills.height > 0, "the event-driven run should have closed at the auction"
        closes = _closes()
        assert set(moc_fills.get_column("ts").to_list()) <= closes  # filled at session closes
        order = np.argsort(fills.get_column("ts").to_numpy(), kind="stable")
        signed = np.where(fills.get_column("side").to_numpy() == "buy", 1.0, -1.0) * (
            fills.get_column("qty").cast(pl.Float64).to_numpy()
        )
        held = np.cumsum(signed[order])
        ts = fills.get_column("ts").to_numpy()[order]
        for close in closes:
            position = held[ts <= close][-1] if np.any(ts <= close) else 0.0
            assert abs(position) < 1e-9, f"event-driven run held {position} at close ts={close}"


class TestExitAt:
    def test_exit_at_closes_positions_and_blocks_entries_from_that_time(
        self, tmp_path: Path
    ) -> None:
        spec = {
            "entry": {"long": "sma(5) crosses_above sma(12)"},
            "exit": {"long": "sma(5) crosses_below sma(12)"},
            "session": {"exit_at": "12:30"},
        }
        doc, _ = _run(tmp_path, spec, realism=False)
        for trade in _trades(doc):
            assert _local(trade["entry_time"]) < "12:30", f"entered after exit_at: {trade}"
            assert trade["entry_date"] == trade["exit_date"]
            assert _local(trade["exit_time"]) <= "12:30", f"held past exit_at: {trade}"


class TestTimeCondition:
    def test_a_time_condition_restricts_entries(self, tmp_path: Path) -> None:
        spec = {
            "entry": {"long": {"all": ["sma(5) crosses_above sma(12)", "time <= 11:30"]}},
            "exit": {"long": "sma(5) crosses_below sma(12)"},
        }
        doc, _ = _run(tmp_path, spec, realism=False)
        for trade in _trades(doc):
            assert _local(trade["entry_time"]) <= "11:30", f"entered after 11:30: {trade}"
