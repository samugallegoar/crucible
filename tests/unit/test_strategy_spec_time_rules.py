"""Time rules in the strategy spec (ADR-0073, ADR-0074): market-on-close exits, ``exit_at`` and
``time`` inside conditions. Bars here are hourly XNYS bars on 2021-01-04 (New York winter time,
UTC-5): they end 10:30 ... 15:30 and 16:00 local, i.e. 15:30 ... 20:30 and 21:00 UTC."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.strategy_spec import describe_spec, parse_spec, spec_signal
from crucible.strategy_spec.compile import session_schedule

SESSION = {"calendar": "XNYS", "interval": "1h"}
LOCAL_ENDS = ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]


def _utc(hh: int, mm: int, day: int = 4, month: int = 1) -> int:
    return int(dt.datetime(2021, month, day, hh, mm, tzinfo=dt.UTC).timestamp() * 1e9)


def _session_ends(day: int = 4) -> np.ndarray:
    return np.asarray(
        [
            _utc(h, m, day)
            for h, m in ((15, 30), (16, 30), (17, 30), (18, 30), (19, 30), (20, 30), (21, 0))
        ]
    )


def _spec(session: dict[str, object] | None = None, entry: str = "close > sma(2)") -> object:
    raw: dict[str, object] = {"entry": {"long": entry}, "risk": {"max_holding_bars": 50}}
    if session is not None:
        raw["session"] = session
    return parse_spec(raw)


# --- market on close ---------------------------------------------------------------------------


def test_market_on_close_flattens_on_the_last_bar_and_targets_the_close_from_the_one_before() -> (
    None
):
    spec = _spec({"flat_by_close": True, "close_with": "market_on_close"})
    sched = session_schedule(spec, _session_ends(), {"session": SESSION})  # type: ignore[arg-type]
    assert sched.force_flat.tolist() == [False] * 6 + [True]  # only the 16:00 bar
    assert sched.entry_ok.tolist() == [True] * 6 + [False]
    close = _utc(21, 0)
    assert sched.moc_close.tolist() == [0] * 5 + [close, 0]  # the 15:30 bar targets the 16:00 close


def test_the_default_close_exits_one_bar_earlier_without_an_auction() -> None:
    spec = _spec({"flat_by_close": True})
    sched = session_schedule(spec, _session_ends(), {"session": SESSION})  # type: ignore[arg-type]
    assert sched.force_flat.tolist() == [False] * 5 + [True, True]
    assert not sched.moc_close.any()


def test_the_signal_marks_close_at_only_while_a_position_is_held() -> None:
    ends = _session_ends()
    bars = pl.DataFrame(
        {
            "symbol": ["X"] * 7,
            "event_time": ends,
            "open": [10.0, 11, 12, 13, 14, 15, 16],
            "high": [10.0, 11, 12, 13, 14, 15, 16],
            "low": [10.0, 11, 12, 13, 14, 15, 16],
            "close": [10.0, 11, 12, 13, 14, 15, 16],  # rising: close > sma(2) from bar 2
            "volume": [1.0] * 7,
        }
    )
    params = {
        "spec": {
            "entry": {"long": "close > sma(2)"},
            "session": {"flat_by_close": True, "close_with": "market_on_close"},
        },
        "session": SESSION,
    }
    out = spec_signal(bars.lazy(), params).collect().sort("ts")
    assert out.get_column("score").to_list() == [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
    assert out.get_column("close_at").to_list() == [None] * 5 + [_utc(21, 0), None]


def test_market_on_close_is_refused_on_a_24_7_market() -> None:
    spec = _spec({"flat_by_close": True, "close_with": "market_on_close"})
    with pytest.raises(ConfigurationError, match="closing auction"):
        session_schedule(
            spec,  # type: ignore[arg-type]
            np.asarray([_utc(1, 0), _utc(2, 0)]),
            {"session": {"calendar": "24/7", "interval": "1h"}},
        )


def test_close_with_needs_flat_by_close() -> None:
    with pytest.raises(ConfigurationError, match="only applies with flat_by_close"):
        _spec({"close_with": "market_on_close", "exit_at": "12:00"})


# --- exit_at -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exit_at", "first_flat"),
    [("12:30", 2), ("12:00", 2), ("12:31", 3), ("16:00", 6)],
)
def test_exit_at_flattens_from_the_first_bar_ending_at_or_after_it(
    exit_at: str, first_flat: int
) -> None:
    sched = session_schedule(
        _spec({"exit_at": exit_at}),  # type: ignore[arg-type]
        _session_ends(),
        {"session": SESSION},
    )
    expected = [i >= first_flat for i in range(7)]
    assert sched.force_flat.tolist() == expected
    assert sched.entry_ok.tolist() == [not e for e in expected]


def test_exit_at_reads_exchange_time_in_summer_too() -> None:
    # 2021-07-06, New York summer time (UTC-4): the bar ending 12:30 local is 16:30 UTC
    ends = np.asarray([_utc(h, 30, 6, month=7) for h in (14, 15, 16, 17)])  # 10:30-13:30 local
    sched = session_schedule(
        _spec({"exit_at": "12:30"}),  # type: ignore[arg-type]
        ends,
        {"session": SESSION},
    )
    assert sched.force_flat.tolist() == [False, False, True, True]


def test_exit_at_is_a_way_out_and_must_be_a_clock_time() -> None:
    parse_spec({"entry": {"long": "close > sma(5)"}, "session": {"exit_at": "15:00"}})
    with pytest.raises(ConfigurationError, match="not a time"):
        parse_spec({"entry": {"long": "close > sma(5)"}, "session": {"exit_at": "3pm"}})


# --- time inside conditions --------------------------------------------------------------------


def test_time_compares_with_a_clock_time_in_exchange_time() -> None:
    spec = _spec(entry="time <= 11:30")
    sched = session_schedule(spec, _session_ends(), {"session": SESSION})  # type: ignore[arg-type]
    assert sched.minutes.tolist() == [
        10 * 60 + 30,
        11 * 60 + 30,
        12 * 60 + 30,
        13 * 60 + 30,
        14 * 60 + 30,
        15 * 60 + 30,
        16 * 60,
    ]


def test_a_time_condition_gates_entries() -> None:
    ends = _session_ends()
    bars = pl.DataFrame(
        {
            "symbol": ["X"] * 7,
            "event_time": ends,
            "open": [1.0] * 7,
            "high": [1.0] * 7,
            "low": [1.0] * 7,
            "close": [1.0] * 7,
            "volume": [1.0] * 7,
        }
    )
    params = {
        "spec": {
            "entry": {"long": {"all": ["time >= 13:30", "time < 15:30"]}},
            "exit": {"long": "time >= 15:30"},
        },
        "session": SESSION,
    }
    out = spec_signal(bars.lazy(), params).collect().sort("ts")
    # in from the 13:30 bar, out on the 15:30 bar; a flat bar takes no entry on the same bar
    assert out.get_column("score").to_list() == [0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0]


@pytest.mark.parametrize(
    "condition",
    ["time crosses_above 10:30", "close > 10:30", "time > 30", "time > close"],
)
def test_time_misuse_is_refused(condition: str) -> None:
    with pytest.raises(ConfigurationError, match="time"):
        parse_spec({"entry": {"long": condition}, "risk": {"max_holding_bars": 3}})


def test_time_needs_the_schedule() -> None:
    bars = pl.DataFrame(
        {
            "symbol": ["X"],
            "event_time": [_utc(15, 30)],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        }
    )
    params = {"spec": {"entry": {"long": "time >= 10:30"}, "risk": {"max_holding_bars": 2}}}
    with pytest.raises(ConfigurationError, match=r"params\.session"):
        spec_signal(bars.lazy(), params).collect()


def test_the_explanation_names_every_time_rule() -> None:
    text = " ".join(
        describe_spec(
            parse_spec(
                {
                    "entry": {"long": {"all": ["rsi(14) < 30", "time >= 10:30"]}},
                    "session": {
                        "flat_by_close": True,
                        "close_with": "market_on_close",
                        "exit_at": "15:00",
                    },
                }
            )
        )
    )
    assert "the bar's end time is at or above 10:30 (exchange time)" in text
    assert "closing price" in text
    assert "15:00" in text
    assert LOCAL_ENDS[0] == "10:30"
