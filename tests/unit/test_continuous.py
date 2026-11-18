"""The continuous futures builder (ADR-0086) on synthetic contracts with hand-chosen volumes."""

from __future__ import annotations

import datetime as dt
import math
from itertools import pairwise
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.continuous import (
    RollParams,
    build_continuous,
    build_continuous_datasets,
    calendar_for,
    dataset_names,
    trade_dates,
)
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    END_AT_OPEN,
    ROLL_SCHEMA,
)
from crucible.data.store import ParquetDataStore, build_dataset, price_basis_of

if TYPE_CHECKING:
    from pathlib import Path

_NS = 1_000_000_000
A, B, C = "ESH2024", "ESM2024", "ESU2024"  # consecutive quarterly contracts
_TRADE_DATES = [
    s.trade_date for s in calendar_for("ES").sessions(dt.date(2024, 1, 2), dt.date(2024, 3, 29))
]


def _day(i: int) -> dt.date:
    """The ``i``-th ES trade date from 2024-01-02 (weekends and holidays skipped)."""
    return _TRADE_DATES[i]


def trade_date_expr(_bar_seconds: int) -> pl.Expr:
    """The trade date of the synthetic bars here: all open at 09:00 CT on their own trade date,
    so it is the UTC date of the open (the calendar's own assignment is tested below)."""
    return pl.from_epoch(pl.col("event_time") - 60 * _NS, time_unit="ns").dt.date()


def _ns(day: dt.date, hour: int, minute: int) -> int:
    return (
        int(dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC).timestamp())
        * _NS
    )


def _session(
    contract: str, i: int, price: float, volume: float, minutes: tuple[int, ...] = (0, 1, 2)
) -> list[dict[str, object]]:
    """Bars of ``contract`` on session ``i``, opening at 15:00+m UTC (09:00 CT, the same date)."""
    rows: list[dict[str, object]] = []
    for m in minutes:
        close = _ns(_day(i), 15, m) + 60 * _NS
        p = price + 0.25 * m
        rows.append(
            {
                "symbol": contract,
                "event_time": close,
                "available_at": close,
                "open": p,
                "high": p + 0.5,
                "low": p - 0.25,
                "close": p + 0.25,
                "volume": volume,
            }
        )
    return rows


def _raw(plan: dict[str, dict[int, tuple[float, float]]]) -> pl.DataFrame:
    """``plan``: contract -> {session index: (base price, volume per bar)}."""
    rows = [
        row
        for contract, sessions in plan.items()
        for i, (price, volume) in sessions.items()
        for row in _session(contract, i, price, volume)
    ]
    return pl.DataFrame(rows, schema=BAR_SCHEMA)


def _two_contracts(
    *, lead_from: int = 6, a_last: int = 9, b_last: int = 12, a_volume: float = 100.0
) -> pl.DataFrame:
    """A runs sessions 0..a_last, B 0..b_last. B's volume exceeds A's from ``lead_from``."""
    return _raw(
        {
            A: dict.fromkeys(range(a_last + 1), (4700.0, a_volume)),
            B: {i: (4710.0, 150.0 if i >= lead_from else 10.0) for i in range(b_last + 1)},
        }
    )


def _held_by_session(frame: pl.DataFrame) -> dict[str, str]:
    """``{trade date: contract}``; must be a function, i.e. one contract per session."""
    pairs = (
        frame.with_columns(trade_date=trade_date_expr(60).cast(pl.String))
        .select("trade_date", "contract")
        .unique()
        .rows()
    )
    held = dict(pairs)
    assert len(held) == len(pairs), "a session printed bars from two contracts"
    return held


# ------------------------------------------------------------------ the trade date


@pytest.mark.parametrize(
    ("close_utc", "expected"),
    [
        # winter (CST, UTC-6): the evening session opens 23:00 UTC for the next trade date
        ((2024, 1, 2, 23, 1), "2024-01-03"),
        ((2024, 1, 3, 14, 31), "2024-01-03"),  # 08:30 CT, the same trade date
        ((2024, 1, 3, 22, 0), "2024-01-03"),  # 16:00 CT close of the session
        # summer (CDT, UTC-5): the evening session opens 22:00 UTC
        ((2024, 7, 2, 22, 1), "2024-07-03"),
        ((2024, 7, 3, 21, 0), "2024-07-03"),  # 16:00 CT close
    ],
)
def test_the_trade_date_follows_the_globex_session(
    close_utc: tuple[int, int, int, int, int], expected: str
) -> None:
    closed = dt.datetime(*close_utc, tzinfo=dt.UTC)
    times = pl.Series("event_time", [int(closed.timestamp()) * _NS])
    got = trade_dates(times, calendar_for("ES"), 60).cast(pl.String)[0]
    assert got == expected


# --------------------------------------------------------------------- the roll rule


def test_the_series_switches_the_session_after_the_successor_led() -> None:
    series = build_continuous(_two_contracts(), root="ES", params=RollParams(backstop_sessions=0))
    roll = series.rolls.row(0, named=True)
    # B first exceeds A on session 6; decided from session 6's volume, effective on session 7
    assert roll["from_contract"] == A
    assert roll["to_contract"] == B
    assert roll["effective_trade_date"] == str(_day(7))
    assert roll["reason"] == "volume"
    assert series.rolls.height == 1
    held = _held_by_session(series.unadjusted)
    assert [held[str(_day(i))] for i in range(13)] == [A] * 7 + [B] * 6  # B's last session is 12


def test_the_decision_uses_the_previous_session_never_the_current_one() -> None:
    """Session 6 is the first the successor leads; the series still holds A on session 6."""
    series = build_continuous(_two_contracts(), root="ES", params=RollParams(backstop_sessions=0))
    held = _held_by_session(series.unadjusted)
    assert held[str(_day(6))] == A
    assert held[str(_day(7))] == B


def test_the_threshold_scales_the_held_contracts_volume() -> None:
    # B has 150 against A's 100: it leads at x1.0 and x1.4 but not at x1.6
    assert (
        build_continuous(
            _two_contracts(), root="ES", params=RollParams(threshold=1.4, backstop_sessions=0)
        ).rolls.row(0, named=True)["reason"]
        == "volume"
    )
    late = build_continuous(
        _two_contracts(), root="ES", params=RollParams(threshold=1.6, backstop_sessions=0)
    ).rolls.row(0, named=True)
    assert late["reason"] == "expired"  # never led: A ran out of sessions


def test_rolls_are_one_way() -> None:
    """After the switch A's volume jumps back above B's; the series never goes back."""
    raw = pl.concat(
        [
            _two_contracts(),
            pl.DataFrame(_session(A, 8, 4700.0, 9_000.0), schema=BAR_SCHEMA),  # A booms again
        ]
    )
    # (session 8 of A now holds two row sets; keep one by dropping the original)
    raw = raw.filter(~((pl.col("symbol") == A) & (pl.col("volume") == 100.0) & _on(8)))
    series = build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))
    assert series.rolls.height == 1
    assert _held_by_session(series.unadjusted)[str(_day(8))] == B


def _on(i: int) -> pl.Expr:
    return trade_date_expr(60).cast(pl.String) == str(_day(i))


def test_the_backstop_keeps_the_series_out_of_the_final_session() -> None:
    never_leads = _two_contracts(lead_from=99)  # B never exceeds A
    one = build_continuous(never_leads, root="ES", params=RollParams(backstop_sessions=1))
    assert one.rolls.row(0, named=True)["effective_trade_date"] == str(_day(9))  # A's last session
    assert one.rolls.row(0, named=True)["reason"] == "backstop"
    assert _held_by_session(one.unadjusted)[str(_day(9))] == B
    two = build_continuous(never_leads, root="ES", params=RollParams(backstop_sessions=2))
    assert two.rolls.row(0, named=True)["effective_trade_date"] == str(_day(8))


def test_a_contract_still_trading_when_the_data_ends_has_no_backstop() -> None:
    """Regression: the real file ends mid-life of the front contract. Its last observed session is
    where the download stopped, not an expiry, so rolling out of it would be an invented roll."""
    raw = _raw(
        {
            A: dict.fromkeys(range(10), (4700.0, 100.0)),
            B: dict.fromkeys(range(10), (4710.0, 10.0)),  # both still trade on the last session
        }
    )
    series = build_continuous(raw, root="ES", params=RollParams(backstop_sessions=1))
    assert series.rolls.height == 0
    assert set(series.unadjusted["contract"]) == {A}


def test_without_a_backstop_an_expired_contract_is_replaced_the_session_after_its_last() -> None:
    series = build_continuous(
        _two_contracts(lead_from=99), root="ES", params=RollParams(backstop_sessions=0)
    )
    roll = series.rolls.row(0, named=True)
    assert roll["effective_trade_date"] == str(_day(10))
    assert roll["reason"] == "expired"


def test_the_volume_rule_wins_over_the_backstop_when_both_apply() -> None:
    series = build_continuous(_two_contracts(lead_from=8), root="ES")  # default backstop 1
    assert series.rolls.row(0, named=True)["reason"] == "volume"


def test_the_first_contract_is_the_one_with_the_most_volume_on_the_first_session() -> None:
    raw = _raw(
        {A: {0: (4700.0, 10.0), 1: (4700.0, 10.0)}, B: {0: (4710.0, 50.0), 1: (4710.0, 50.0)}}
    )
    series = build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))
    assert series.first_contract == B
    assert series.rolls.height == 0
    assert set(series.unadjusted["contract"]) == {B}


def test_a_chain_of_three_contracts_rolls_twice() -> None:
    plan = {
        A: {i: (4700.0, 100.0 if i < 4 else 5.0) for i in range(8)},
        B: {i: (4710.0, 5.0 if i < 3 else (200.0 if i < 9 else 5.0)) for i in range(12)},
        C: {i: (4725.0, 1.0 if i < 8 else 300.0) for i in range(14)},
    }
    series = build_continuous(_raw(plan), root="ES", params=RollParams(backstop_sessions=0))
    assert [r["to_contract"] for r in series.rolls.iter_rows(named=True)] == [B, C]
    held = _held_by_session(series.unadjusted)
    assert held[str(_day(0))] == A
    assert held[str(_day(13))] == C


# ----------------------------------------------------------- the ratio and the rolls table


def test_the_roll_row_records_what_the_ratio_was_computed_from() -> None:
    series = build_continuous(_two_contracts(), root="ES", params=RollParams(backstop_sessions=0))
    roll = series.rolls.row(0, named=True)
    # the last common minute of session 6: the third bar (minute 2), close = price + 0.25*2 + 0.25
    assert roll["from_price"] == pytest.approx(4700.0 + 0.75)
    assert roll["to_price"] == pytest.approx(4710.0 + 0.75)
    assert roll["ratio"] == pytest.approx(roll["to_price"] / roll["from_price"])
    assert roll["gap_points"] == pytest.approx(10.0)
    assert roll["reference_time"] == _ns(_day(6), 15, 2) + 60 * _NS
    # decided when the deciding session ended, and knowable then
    assert roll["event_time"] == roll["available_at"] == _ns(_day(6), 15, 2) + 60 * _NS
    assert roll["symbol"] == "ES"


def test_the_unadjusted_series_is_the_held_contracts_own_bars() -> None:
    raw = _two_contracts()
    series = build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))
    on = series.unadjusted
    held = _held_by_session(on)
    for contract, day in ((A, str(_day(3))), (B, str(_day(9)))):
        assert held[day] == contract
        mine = on.filter(trade_date_expr(60).cast(pl.String) == day).select(
            BAR_SCHEMA.keys() - {"symbol"} | set()
        )
        original = raw.filter(
            (pl.col("symbol") == contract) & (trade_date_expr(60).cast(pl.String) == day)
        ).select(mine.columns)
        assert mine.sort("event_time").equals(original.sort("event_time"))
    assert set(on["symbol"]) == {"ES"}
    assert dict(on.schema) == CONTINUOUS_BAR_SCHEMA


def test_earlier_bars_are_scaled_by_the_ratio_and_the_series_is_continuous_at_the_roll() -> None:
    series = build_continuous(_two_contracts(), root="ES", params=RollParams(backstop_sessions=0))
    ratio = series.rolls.row(0, named=True)["ratio"]
    plain, scaled = series.unadjusted, series.adjusted
    assert plain["event_time"].to_list() == scaled["event_time"].to_list()
    before = plain.filter(pl.col("contract") == A)
    after = plain.filter(pl.col("contract") == B)
    for column in ("open", "high", "low", "close"):
        got = scaled.filter(pl.col("contract") == A)[column].to_list()
        assert got == pytest.approx([x * ratio for x in before[column].to_list()], rel=1e-12)
        assert scaled.filter(pl.col("contract") == B)[column].to_list() == after[column].to_list()
    assert scaled["volume"].to_list() == plain["volume"].to_list()
    # at the reference minute the adjusted old close equals the new contract's close
    roll = series.rolls.row(0, named=True)
    old_close = scaled.filter(
        (pl.col("contract") == A) & (pl.col("event_time") == roll["reference_time"])
    )["close"][0]
    assert old_close == pytest.approx(roll["to_price"], rel=1e-12)


def test_percent_returns_inside_a_contract_survive_the_adjustment() -> None:
    series = build_continuous(_two_contracts(), root="ES", params=RollParams(backstop_sessions=0))
    for contract in (A, B):
        raw_close = series.unadjusted.filter(pl.col("contract") == contract)["close"].to_list()
        adj_close = series.adjusted.filter(pl.col("contract") == contract)["close"].to_list()
        raw_returns = [b / a - 1 for a, b in pairwise(raw_close)]
        adj_returns = [b / a - 1 for a, b in pairwise(adj_close)]
        assert adj_returns == pytest.approx(raw_returns, rel=1e-9, abs=1e-15)


def test_ratios_compound_backwards_over_every_later_roll() -> None:
    plan = {
        A: {i: (4700.0, 100.0 if i < 4 else 5.0) for i in range(8)},
        B: {i: (4750.0, 5.0 if i < 3 else (200.0 if i < 9 else 5.0)) for i in range(12)},
        C: {i: (4800.0, 1.0 if i < 8 else 300.0) for i in range(14)},
    }
    series = build_continuous(_raw(plan), root="ES", params=RollParams(backstop_sessions=0))
    r1, r2 = series.rolls["ratio"].to_list()
    first_open_raw = series.unadjusted.filter(pl.col("contract") == A)["open"][0]
    first_open_adj = series.adjusted.filter(pl.col("contract") == A)["open"][0]
    assert first_open_adj == pytest.approx(first_open_raw * r1 * r2, rel=1e-12)
    mid_raw = series.unadjusted.filter(pl.col("contract") == B)["close"][0]
    mid_adj = series.adjusted.filter(pl.col("contract") == B)["close"][0]
    assert mid_adj == pytest.approx(mid_raw * r2, rel=1e-12)
    last_raw = series.unadjusted.filter(pl.col("contract") == C)["close"].to_list()
    assert series.adjusted.filter(pl.col("contract") == C)["close"].to_list() == last_raw


def test_adjusted_prices_stay_positive_where_a_difference_adjustment_would_not() -> None:
    """Contract A trades at 100, B at 400: subtracting the 300 gap would send A negative."""
    plan = {
        A: dict.fromkeys(range(6), (100.0, 100.0)),
        B: {i: (400.0, 5.0 if i < 3 else 500.0) for i in range(9)},
    }
    series = build_continuous(_raw(plan), root="ES", params=RollParams(backstop_sessions=0))
    assert (series.adjusted["low"] > 0).all()
    assert (series.unadjusted["low"] > 0).all()


def test_a_reference_minute_is_searched_back_within_the_lookback() -> None:
    """On the deciding session the contracts share no minute; the session before has one."""
    a = [*_session(A, 4, 4700.0, 100.0), *_session(A, 5, 4701.0, 100.0, minutes=(0, 1))]
    a += [r for i in (0, 1, 2, 3) for r in _session(A, i, 4700.0, 100.0)]
    a += _session(A, 6, 4702.0, 100.0)
    b = [r for i in (0, 1, 2, 3, 4) for r in _session(B, i, 4710.0, 10.0)]
    b += _session(B, 5, 4711.0, 150.0, minutes=(5, 6))  # B leads on session 5, other minutes
    b += [r for i in (6, 7, 8) for r in _session(B, i, 4712.0, 150.0)]
    raw = pl.DataFrame([*a, *b], schema=BAR_SCHEMA)
    series = build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))
    roll = series.rolls.row(0, named=True)
    assert roll["effective_trade_date"] == str(_day(6))
    assert roll["reference_time"] == _ns(_day(4), 15, 2) + 60 * _NS  # session 4, not 5


def test_a_roll_whose_contracts_never_shared_a_minute_is_refused() -> None:
    a = [r for i in range(6) for r in _session(A, i, 4700.0, 100.0, minutes=(0,))]
    b = [
        r for i in range(9) for r in _session(B, i, 4710.0, 10.0 if i < 3 else 500.0, minutes=(5,))
    ]
    raw = pl.DataFrame([*a, *b], schema=BAR_SCHEMA)
    with pytest.raises(DataQualityError, match="never traded in the same minute"):
        build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))


# -------------------------------------------------------------------- refusals and shape


def test_a_missing_successor_that_would_stop_the_series_is_refused() -> None:
    """A (March) and C (September) but no B (June): the chain has a hole after A expires."""
    raw = _raw(
        {
            A: dict.fromkeys(range(6), (4700.0, 100.0)),
            C: dict.fromkeys(range(12), (4725.0, 10.0)),
        }
    )
    with pytest.raises(DataQualityError, match=r"successor .* is missing"):
        build_continuous(raw, root="ES", params=RollParams(backstop_sessions=0))


def test_a_symbol_that_is_not_a_contract_of_the_root_is_refused() -> None:
    raw = _raw({"NQH2024": {0: (17000.0, 10.0), 1: (17000.0, 10.0)}})
    with pytest.raises(ConfigurationError, match="not a ES contract name"):
        build_continuous(raw, root="ES")
    old_style = _raw({"ESH4": {0: (4700.0, 10.0)}})
    with pytest.raises(ConfigurationError, match="databento_dbn"):
        build_continuous(old_style, root="ES")


def test_empty_or_incomplete_raw_bars_are_refused() -> None:
    with pytest.raises(DataQualityError, match="empty"):
        build_continuous(pl.DataFrame(schema=BAR_SCHEMA), root="ES")
    with pytest.raises(DataQualityError, match="lack columns"):
        build_continuous(pl.DataFrame({"symbol": ["ESH2024"]}), root="ES")


@pytest.mark.parametrize(
    "kwargs",
    [{"threshold": 0.0}, {"threshold": -1.0}, {"backstop_sessions": -1}, {"bar_seconds": 0}],
)
def test_bad_parameters_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ConfigurationError):
        RollParams(**kwargs)  # type: ignore[arg-type]


def test_the_output_is_deterministic_and_well_formed() -> None:
    raw = _two_contracts()
    one = build_continuous(raw, root="ES")
    two = build_continuous(raw.sample(fraction=1.0, shuffle=True, seed=7), root="ES")
    assert one.unadjusted.equals(two.unadjusted)
    assert one.adjusted.equals(two.adjusted)
    assert one.rolls.equals(two.rolls)  # the input row order does not matter
    assert dict(one.rolls.schema) == ROLL_SCHEMA
    for frame in (one.unadjusted, one.adjusted):
        unique = frame.select("symbol", "event_time").unique().height
        assert unique == frame.height
        assert frame["event_time"].is_sorted()


def test_a_roll_decision_never_depends_on_sessions_after_it() -> None:
    """Causality: cut the data at session 8 (the roll was decided at 6): same roll, same bars.
    (Backstop off: it reads the contract's last observed session, a calendar fact, not a price.)"""
    params = RollParams(backstop_sessions=0)
    full = build_continuous(_two_contracts(), root="ES", params=params)
    cut_raw = _two_contracts().filter(trade_date_expr(60) <= _day(8))
    cut = build_continuous(cut_raw, root="ES", params=params)
    assert cut.rolls.equals(full.rolls)
    keep = full.unadjusted.filter(trade_date_expr(60) <= _day(8))
    assert cut.unadjusted.equals(keep)


def test_the_continuous_bar_schema_extends_the_bar_schema_by_the_contract() -> None:
    assert list(CONTINUOUS_BAR_SCHEMA)[:-1] == list(BAR_SCHEMA)
    assert list(CONTINUOUS_BAR_SCHEMA)[-1] == "contract"
    assert BAR_SORT_KEYS == ["available_at", "symbol", "event_time"]


# ---------------------------------------------------------------------------- the store


def test_the_datasets_are_written_with_their_price_basis_and_parameters(tmp_path: Path) -> None:
    store = tmp_path / "store"
    build_dataset(
        store,
        DatasetId("es_1m_raw"),
        _two_contracts(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento_dbn;price_basis=raw",
    )
    params = RollParams(backstop_sessions=1)
    series, manifests = build_continuous_datasets(
        store, "es", raw_dataset="es_1m_raw", params=params
    )
    assert [str(m.dataset) for m in manifests] == list(dataset_names("ES", params))
    assert dataset_names("ES", params) == ("es_1m_cont_v3", "es_1m_cont_ratio_v3", "es_1m_rolls_v3")
    plain, adjusted, rolls = manifests
    assert price_basis_of(plain) == "raw"
    assert price_basis_of(adjusted) == "adjusted"
    for manifest in manifests:
        assert "from=es_1m_raw@" in manifest.source
        assert "threshold=1.0;backstop_sessions=1;bar_seconds=60;chain_months=3" in manifest.source
        assert ";calendar=cme-equity-sessions-1@" in manifest.source
        assert manifest.source.endswith(";trimmed_rows=0")
    assert plain.row_count == series.unadjusted.height
    assert rolls.row_count == series.rolls.height
    read = ParquetDataStore(store).read(DatasetId("es_1m_rolls_v3"), TimestampNs(END_AT_OPEN))
    assert read.collect().height == series.rolls.height


def _nkd_with_pre_coverage_bars() -> tuple[pl.DataFrame, pl.DataFrame, int]:
    """NKD copies of the two contracts, plus 3 bars on 2012-11-16 (before NKD's calendar
    coverage, trade date 2012-11-19): ``(clean, with_early, early_rows)``."""
    clean = _two_contracts().with_columns(pl.col("symbol").str.replace("^ES", "NKD"))
    early = clean.head(3).with_columns(
        (
            pl.col("event_time") - pl.col("event_time").min() + _ns(dt.date(2012, 11, 16), 15, 1)
        ).alias("event_time")
    )
    early = early.with_columns(available_at=pl.col("event_time"))
    return clean, pl.concat([early, clean]), early.height


def test_bars_outside_the_session_calendar_are_refused() -> None:
    _, raw, _ = _nkd_with_pre_coverage_bars()
    with pytest.raises(DataQualityError, match=r"3 raw bars lie outside.*trim-to-calendar"):
        build_continuous(raw, root="NKD")


def test_trim_to_calendar_drops_and_counts_them(tmp_path: Path) -> None:
    clean, raw, early = _nkd_with_pre_coverage_bars()
    store = tmp_path / "store"
    build_dataset(
        store,
        DatasetId("nkd_1m_raw"),
        raw,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento_dbn;price_basis=raw",
    )
    series, manifests = build_continuous_datasets(
        store, "NKD", raw_dataset="nkd_1m_raw", trim_to_calendar=True
    )
    assert series.trimmed_rows == early
    assert all(m.source.endswith(f";trimmed_rows={early}") for m in manifests)
    assert series.unadjusted.equals(build_continuous(clean, root="NKD").unadjusted)


def test_a_rebuild_reproduces_the_content_hashes(tmp_path: Path) -> None:
    store = tmp_path / "store"
    build_dataset(
        store,
        DatasetId("es_1m_raw"),
        _two_contracts(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento_dbn;price_basis=raw",
    )
    first = build_continuous_datasets(store, "ES", raw_dataset="es_1m_raw")[1]
    second = build_continuous_datasets(store, "ES", raw_dataset="es_1m_raw")[1]
    assert [m.content_hash for m in first] == [m.content_hash for m in second]


def test_roll_parameters_make_a_different_dataset_identity(tmp_path: Path) -> None:
    assert RollParams(threshold=1.0).describe() != RollParams(threshold=1.5).describe()
    assert math.isclose(RollParams().threshold, 1.0)
