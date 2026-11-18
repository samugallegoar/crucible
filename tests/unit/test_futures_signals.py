"""The futures signal bridge (C3b): signed contract targets, scale invariance, alignment and the
CME session rules (ADR-0086, ADR-0091, ADR-0093).

Every expected target below is hand-computed from the synthetic series in the test: the closes are
strictly rising, so ``close > sma(3)`` (which is ``close > mean of the last three closes``) first
becomes true on the third bar and ``close < sma(3)`` false; nothing is read back from the engine.
The series are built on real ES Globex trade dates (2024-03-05 .. 2024-03-06, and 2023-01-17 for the
unverified session), two contracts (ESH2024 then ESM2024), and the ratio-adjusted series is the
unadjusted one times a factor per contract segment (1.01 for ESH2024, 1.0 from ESM2024 on)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.cme_session_table import TABLE_VERSION
from crucible.data.contracts import CONTINUOUS_BAR_SCHEMA
from crucible.experiments.futures_signals import (
    DatasetRef,
    FuturesSessionPolicy,
    futures_targets,
)
from crucible.strategy_spec.compile import spec_positions
from crucible.strategy_spec.models import StrategySpec, parse_spec

if TYPE_CHECKING:
    from collections.abc import Mapping

PRICES = ("open", "high", "low", "close")
ESH, ESM = "ESH2024", "ESM2024"
RATIO_FACTOR = {ESH: 1.01, ESM: 1.0}
EXEC_REF = DatasetRef("es_1m_cont_v3", "a" * 64, "raw", "none")
SIG_REF = DatasetRef("es_1m_cont_ratio_v3", "b" * 64, "adjusted", "ratio")
SECOND = 1_000_000_000


# --- the synthetic series ----------------------------------------------------------------------


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def bars(rows: list[tuple[str, str, float]]) -> pl.DataFrame:
    """Continuous bars from ``(Chicago wall clock of the bar's END, contract, close)``."""
    times = [utc(wall) for wall, _contract, _price in rows]
    closes = [price for _wall, _contract, price in rows]
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(rows),
            "event_time": times,
            # synthesized: close + 1 ns of latency; no test here reads it
            "available_at": [t + 1 for t in times],
            "open": closes,
            "high": [price + 0.25 for price in closes],
            "low": [price - 0.25 for price in closes],
            "close": closes,
            "volume": [100.0] * len(rows),
            "contract": [contract for _wall, contract, _price in rows],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def ratio_frame(execution: pl.DataFrame) -> pl.DataFrame:
    """The ratio-adjusted series: same rows, prices times the contract segment's factor."""
    factors = pl.Series([RATIO_FACTOR[c] for c in execution.get_column("contract")])
    return execution.with_columns([(pl.col(c) * factors).alias(c) for c in PRICES])


def spec(entry: str = "close > sma(3)", exit_: str = "close < sma(3)") -> StrategySpec:
    return parse_spec({"entry": {"long": entry}, "exit": {"long": exit_}})


def two_days() -> pl.DataFrame:
    """2024-03-05 09:01-09:05 on ESH2024 then 2024-03-06 09:01-09:05 on ESM2024, rising closes."""
    return bars(
        [
            ("2024-03-05 09:01", ESH, 4400.0),
            ("2024-03-05 09:02", ESH, 4410.0),
            ("2024-03-05 09:03", ESH, 4420.0),
            ("2024-03-05 09:04", ESH, 4430.0),
            ("2024-03-05 09:05", ESH, 4440.0),
            ("2024-03-06 09:01", ESM, 4405.0),
            ("2024-03-06 09:02", ESM, 4415.0),
            ("2024-03-06 09:03", ESM, 4425.0),
            ("2024-03-06 09:04", ESM, 4435.0),
            ("2024-03-06 09:05", ESM, 4445.0),
        ]
    )


def one_session(walls: list[str]) -> pl.DataFrame:
    """One rising session on trade date 2024-03-05 (all ESH2024), closes 4400, 4410, ..."""
    return bars([(f"2024-03-05 {wall}", ESH, 4400.0 + 10.0 * i) for i, wall in enumerate(walls)])


def targets(**kwargs: object) -> list[int]:
    """``futures_targets`` on the same unadjusted frame for both series (the plain case)."""
    execution = kwargs.pop("execution")
    assert isinstance(execution, pl.DataFrame)
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        signal_input="unadjusted",
        **kwargs,  # type: ignore[arg-type]
    )
    return result.targets.get_column("target").to_list()


# --- signal functions --------------------------------------------------------------------------


class FixedScores:
    """A ``FuturesSignalFunction`` with a hand-written score per bar, in bar order."""

    scale_invariant = True

    def __init__(self, values: list[float]) -> None:
        self._values = values

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        return bars.select(
            pl.col("event_time").alias("ts"),
            pl.Series("score", self._values, dtype=pl.Float64),
        ).lazy()


class UndeclaredScores(FixedScores):
    """The same function without the ``scale_invariant`` declaration."""

    scale_invariant = False


class RawScores:
    """Returns exactly the ``ts``/``score`` frame it was given (missing rows, nulls, floats)."""

    scale_invariant = True

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        return self._frame.lazy()


class ParamScores:
    """Scores ``params["score"]`` on every bar, to prove params reach the function."""

    scale_invariant = True

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        return bars.select(
            pl.col("event_time").alias("ts"),
            pl.lit(float(params["score"])).alias("score"),
        ).lazy()


class LevelLong:
    """Declares scale invariance but reads a price LEVEL: 1 while close > 4500, else 0."""

    scale_invariant = True

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        return bars.select(
            pl.col("event_time").alias("ts"),
            pl.when(pl.col("close") > 4500.0).then(1).otherwise(0).alias("score"),
        ).lazy()


# --- 1. the spec path on the ratio-adjusted series ---------------------------------------------


def test_spec_on_the_ratio_series_is_sized_in_contracts() -> None:
    execution = two_days()
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=ratio_frame(execution),
        execution_ref=EXEC_REF,
        signal_ref=SIG_REF,
        strategy=spec(),
        contracts=2,
    )
    # sma(3) is null on bars 0-1; 4420 > mean(4400, 4410, 4420) = 4410 -> long +1 -> 2 contracts;
    # 4405 < mean(4430, 4440, 4405) = 4425 on bar 5 -> flat; 4425 > mean(4405, 4415, 4425) -> long
    assert result.targets.get_column("target").to_list() == [0, 0, 2, 2, 2, 0, 0, 2, 2, 2]
    assert result.targets.columns == ["event_time", "target"]
    assert result.targets.schema["event_time"] == pl.Int64
    assert result.targets.schema["target"] == pl.Int64
    assert result.targets.get_column("event_time").to_list() == (
        execution.get_column("event_time").to_list()
    )
    assert result.on_schedule.to_list() == [True] * 10
    assert result.on_schedule.dtype == pl.Boolean


def test_the_record_states_both_datasets_the_alignment_and_the_calendar() -> None:
    execution = two_days()
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=ratio_frame(execution),
        execution_ref=EXEC_REF,
        signal_ref=SIG_REF,
        strategy=spec(),
        contracts=1,
    )
    record = result.record
    assert record["root"] == "ES"
    assert record["strategy_kind"] == "spec"
    assert record["signal_input"] == "ratio_adjusted"
    assert record["signal_dataset"] == {
        "dataset": "es_1m_cont_ratio_v3",
        "content_hash": "b" * 64,
        "price_basis": "adjusted",
        "adjustment": "ratio",
    }
    assert record["execution_dataset"] == {
        "dataset": "es_1m_cont_v3",
        "content_hash": "a" * 64,
        "price_basis": "raw",
        "adjustment": "none",
    }
    assert record["alignment"] == {
        "bars": 10,
        "first": "2024-03-05T15:01:00Z",
        "last": "2024-03-06T15:05:00Z",
    }
    assert record["scale_invariance"] == {
        "static": "passed",
        "declared": None,
        "empirical_factors": [16.0, 0.0625],
        "result": "identical",
    }
    calendar = record["session_calendar"]
    assert isinstance(calendar, dict)
    assert calendar["version"] == TABLE_VERSION
    sha = calendar["sha256"]
    assert isinstance(sha, str)
    assert len(sha) == 64
    assert record["session_rules"] == {
        "flat_by_close": False,
        "exit_at": None,
        "entry_window": None,
        "allow_unverified_sessions": False,
    }
    assert record["off_schedule_bars"] == 0
    assert record["unverified_sessions"] == []
    assert record["contracts"] == 1


def test_a_python_function_decides_contracts_itself() -> None:
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 7)])
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=ratio_frame(execution),
        execution_ref=EXEC_REF,
        signal_ref=SIG_REF,
        strategy=FixedScores([1.0, 2.0, 0.0, 2.0, 0.0, -1.0]),
        contracts=None,
    )
    assert result.targets.get_column("target").to_list() == [1, 2, 0, 2, 0, -1]
    assert result.record["strategy_kind"] == "python"
    assert result.record["scale_invariance"] == {
        "static": "passed",
        "declared": True,
        "empirical_factors": [16.0, 0.0625],
        "result": "identical",
    }
    assert result.record["contracts"] is None


def test_params_reach_the_signal_function() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=ParamScores(),
        contracts=None,
        params={"score": 3},
        signal_input="unadjusted",
    )
    assert result.targets.get_column("target").to_list() == [3, 3, 3]


# --- 2. what the futures path refuses (spec) ---------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "fragment"),
    [
        ({"risk": {"stop_loss_pct": 2.0}}, "percentage stops/targets are not accepted"),
        ({"risk": {"take_profit_pct": 3.0}}, "use the execution policy's stop_ticks"),
        ({"risk": {"max_holding_bars": 10}}, "risk.max_holding_bars \\(10 bars\\)"),
        ({"risk": {"stop_fill": "close"}}, "risk.stop_fill"),
        ({"sizing": {"type": "fixed_fraction", "fraction": 0.5}}, "the spec sets sizing"),
    ],
)
def test_a_spec_setting_that_the_futures_path_cannot_honour_is_refused(
    setting: dict[str, object], fragment: str
) -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    raw: dict[str, object] = {
        "entry": {"long": "close > sma(3)"},
        "exit": {"long": "close < sma(3)"},
        **setting,
    }
    with pytest.raises(ConfigurationError, match=fragment):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=parse_spec(raw),
            contracts=1,
            signal_input="unadjusted",
        )


def test_a_spec_with_a_time_operand_is_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    timed = parse_spec({"entry": {"long": "time < 10:30"}, "exit": {"long": "time >= 15:00"}})
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=timed,
            contracts=1,
            signal_input="unadjusted",
        )
    message = str(caught.value)
    assert "entry.long" in message
    assert "exit.long" in message
    assert "FuturesSessionPolicy" in message


def test_a_spec_with_a_session_block_is_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    with_session = parse_spec(
        {
            "entry": {"long": "close > sma(3)"},
            "exit": {"long": "close < sma(3)"},
            "session": {"flat_by_close": True},
        }
    )
    with pytest.raises(ConfigurationError, match="session block"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=with_session,
            contracts=1,
            signal_input="unadjusted",
        )


@pytest.mark.parametrize("contracts", [None, 0, -1, 1.5, True])
def test_a_spec_needs_a_whole_number_of_contracts(contracts: object) -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    with pytest.raises(ConfigurationError, match="whole number of contracts >= 1"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=spec(),
            contracts=contracts,  # type: ignore[arg-type]
            signal_input="unadjusted",
        )


# --- 3. scale invariance -----------------------------------------------------------------------


def test_a_price_level_on_the_ratio_series_is_refused_statically() -> None:
    execution = one_session(["09:01", "09:02", "09:03", "09:04"])
    level = parse_spec(
        {
            "entry": {"long": {"all": ["close > sma(3)", "close > 4500"]}},
            "exit": {"long": "close < sma(3)"},
        }
    )
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=ratio_frame(execution),
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=level,
            contracts=1,
        )
    message = str(caught.value)
    assert "`close > 4500`" in message
    assert "entry.long.all[1]" in message
    assert "ADR-0086, decision 8" in message
    assert "signal_input='unadjusted'" in message


def test_the_same_price_level_spec_is_accepted_on_the_unadjusted_series() -> None:
    execution = one_session(["09:01", "09:02", "09:03", "09:04"])
    level = parse_spec({"entry": {"long": "close > 4500"}, "exit": {"long": "close < 4500"}})
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=level,
        contracts=1,
        signal_input="unadjusted",
    )
    # no close is above 4500, so the spec never enters
    assert result.targets.get_column("target").to_list() == [0, 0, 0, 0]
    assert result.record["scale_invariance"] == {
        "static": "not_applicable",
        "declared": None,
        "empirical_factors": [],
        "result": "not_applicable",
    }


def test_a_python_function_without_the_declaration_is_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    with pytest.raises(ConfigurationError, match="does not declare scale_invariant = True"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=ratio_frame(execution),
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=UndeclaredScores([1.0, 1.0, 1.0]),
            contracts=None,
        )


def test_a_python_function_that_declares_invariance_but_reads_a_level_is_refused() -> None:
    # closes 4400-4420: not above 4500, but 16x them (70400-70720) is -> the empirical check catches
    execution = one_session(["09:01", "09:02", "09:03", "09:04"])
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=ratio_frame(execution),
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=LevelLong(),
            contracts=None,
        )
    message = str(caught.value)
    assert "not scale invariant" in message
    assert "by 16" in message
    # the first bar already differs: 0 contracts unadjusted, 1 once every price is multiplied
    assert "2024-03-05T15:01:00Z" in message
    assert "from 0 to 1 contracts" in message
    assert "signal_input='unadjusted'" in message


# --- 4. which series feeds the signal ----------------------------------------------------------


def test_an_adjusted_execution_dataset_is_refused() -> None:
    execution = one_session(["09:01", "09:02"])
    with pytest.raises(ConfigurationError, match="fills and P&L are computed on the contracts"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=SIG_REF,
            signal_ref=SIG_REF,
            strategy=spec(),
            contracts=1,
        )


@pytest.mark.parametrize(
    ("signal_input", "signal_ref", "fragment"),
    [
        ("ratio_adjusted", EXEC_REF, "pass the dataset built with the ratio adjustment"),
        ("unadjusted", SIG_REF, "pass the unadjusted continuous series as signal_ref"),
        ("forward_adjusted", SIG_REF, "is not a signal input"),
    ],
)
def test_a_mismatched_signal_input_is_refused(
    signal_input: str, signal_ref: DatasetRef, fragment: str
) -> None:
    execution = one_session(["09:01", "09:02"])
    with pytest.raises(ConfigurationError, match=fragment):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=signal_ref,
            strategy=spec(),
            contracts=1,
            signal_input=signal_input,  # type: ignore[arg-type]
        )


# --- 5. alignment ------------------------------------------------------------------------------


def test_a_shifted_event_time_is_refused_naming_the_row() -> None:
    execution = one_session(["09:01", "09:02", "09:03", "09:04"])
    signal = ratio_frame(execution)
    times = signal.get_column("event_time").to_list()
    times[1] += 30 * SECOND
    shifted = signal.with_columns(pl.Series("event_time", times, dtype=pl.Int64))
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=shifted,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=spec(),
            contracts=1,
        )
    message = str(caught.value)
    assert "at row 1" in message
    assert "2024-03-05T15:02:00Z" in message
    assert "2024-03-05T15:02:30Z" in message


def test_a_different_contract_on_one_row_is_refused_naming_the_row() -> None:
    execution = two_days()
    signal = ratio_frame(execution)
    contracts = signal.get_column("contract").to_list()
    contracts[6] = ESH
    mismatched = signal.with_columns(pl.Series("contract", contracts, dtype=pl.String))
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=mismatched,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=spec(),
            contracts=1,
        )
    message = str(caught.value)
    assert "at row 6" in message
    assert "'ESM2024'" in message
    assert "'ESH2024'" in message


def test_different_heights_are_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03", "09:04"])
    signal = ratio_frame(execution).head(3)
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=signal,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=spec(),
            contracts=1,
        )
    message = str(caught.value)
    assert "execution_bars has 4 rows" in message
    assert "signal_bars has 3" in message


def test_event_times_that_are_not_strictly_increasing_are_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    signal = ratio_frame(execution)
    times = signal.get_column("event_time").to_list()
    times[2] = times[1]
    duplicated = signal.with_columns(pl.Series("event_time", times, dtype=pl.Int64))
    with pytest.raises(ConfigurationError, match="not strictly increasing at row 1"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=duplicated,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=spec(),
            contracts=1,
        )


# --- 6. the CME session rules ------------------------------------------------------------------


def test_an_empty_series_is_refused() -> None:
    empty = one_session([])
    with pytest.raises(ConfigurationError, match="execution_bars is empty"):
        futures_targets(
            root="ES",
            execution_bars=empty,
            signal_bars=empty,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=spec(),
            contracts=1,
            signal_input="unadjusted",
        )


def test_flat_by_close_without_the_final_scheduled_bar_is_refused() -> None:
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)])
    with pytest.raises(DataQualityError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=spec(),
            contracts=1,
            signal_input="unadjusted",
            session=FuturesSessionPolicy(flat_by_close=True),
        )
    message = str(caught.value)
    assert "final scheduled bar is missing" in message
    assert "2024-03-05" in message
    assert "trim the window or fix the data" in message


def test_flat_by_close_makes_the_spec_flat_from_the_penultimate_bar() -> None:
    # the 2024 session runs 17:00 (Mar 4) to 16:00 CT, so the penultimate bar ends 15:59
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)] + ["15:59", "16:00"])
    assert targets(
        execution=execution,
        strategy=spec(),
        contracts=1,
        session=FuturesSessionPolicy(flat_by_close=True),
    ) == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0]


def test_exit_at_flattens_and_blocks_entries_from_its_bar() -> None:
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)])
    # long from 09:03; flat from the bar ending 09:05 and nothing opens afterwards
    assert targets(
        execution=execution,
        strategy=spec(),
        contracts=1,
        session=FuturesSessionPolicy(exit_at="09:05"),
    ) == [0, 0, 1, 1, 0, 0, 0, 0, 0, 0]


def test_an_unverified_session_is_refused_unless_allowed() -> None:
    # 2023-01-17 (MLK week) touches a window no transcribed source covers: verified=False
    execution = bars(
        [
            ("2023-01-17 09:01", ESH, 4400.0),
            ("2023-01-17 09:02", ESH, 4410.0),
            ("2023-01-17 09:03", ESH, 4420.0),
            ("2023-01-17 09:04", ESH, 4430.0),
        ]
    )
    with pytest.raises(DataQualityError) as caught:
        targets(execution=execution, strategy=spec(), contracts=1)
    message = str(caught.value)
    assert "2023-01-17" in message
    assert "allow_unverified_sessions=True" in message
    assert targets(
        execution=execution,
        strategy=spec(),
        contracts=1,
        session=FuturesSessionPolicy(allow_unverified_sessions=True),
    ) == [0, 0, 1, 1]


def test_the_entry_window_blocks_an_entry_the_spec_would_take() -> None:
    # sma(3) first has a value on the bar ending 09:03; a window ending 09:02 leaves nothing to open
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)])
    assert (
        targets(
            execution=execution,
            strategy=spec(),
            contracts=1,
            session=FuturesSessionPolicy(entry_window=("09:01", "09:02")),
        )
        == [0] * 10
    )
    assert targets(
        execution=execution,
        strategy=spec(),
        contracts=1,
        session=FuturesSessionPolicy(entry_window=("09:03", "09:05")),
    ) == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1]


def test_an_off_schedule_bar_carries_the_previous_target() -> None:
    # 16:01 CT is the print in the minute after the 16:00 close: no decision is taken there
    execution = bars(
        [
            ("2024-03-05 09:01", ESH, 4400.0),
            ("2024-03-05 09:02", ESH, 4410.0),
            ("2024-03-05 09:03", ESH, 4420.0),
            ("2024-03-05 09:04", ESH, 4430.0),
            ("2024-03-05 16:00", ESH, 4440.0),
            ("2024-03-05 16:01", ESH, 50.0),  # would exit, but the segment is closed
        ]
    )
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=spec(),
        contracts=1,
        signal_input="unadjusted",
    )
    assert result.on_schedule.to_list() == [True, True, True, True, True, False]
    assert result.targets.get_column("target").to_list() == [0, 0, 1, 1, 1, 1]
    assert result.record["off_schedule_bars"] == 1


def test_an_off_schedule_exit_does_not_leak_into_the_next_bar() -> None:
    # the 16:01 CT print is outside the segment: its close (50) satisfies `close < 4000`, but no
    # decision is taken there. The next on-schedule bar (09:01 the next day, 4950) is neither an
    # entry (`> 5000`) nor an exit (`< 4000`), so the position is still held -- it is not flat.
    execution = bars(
        [
            ("2024-03-05 09:01", ESH, 5100.0),
            ("2024-03-05 09:02", ESH, 5100.0),
            ("2024-03-05 09:03", ESH, 5100.0),
            ("2024-03-05 09:04", ESH, 5100.0),
            ("2024-03-05 16:01", ESH, 50.0),
            ("2024-03-06 09:01", ESH, 4950.0),
        ]
    )
    level = parse_spec({"entry": {"long": "close > 5000"}, "exit": {"long": "close < 4000"}})
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=level,
        contracts=1,
        signal_input="unadjusted",
    )
    assert result.on_schedule.to_list() == [True, True, True, True, False, True]
    assert result.targets.get_column("target").to_list() == [1, 1, 1, 1, 1, 1]


def test_the_python_path_only_reduces_outside_the_entry_window() -> None:
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)])
    # index 0 is inside the window: 3 contracts; index 1 reduces to 0 (allowed); index 2 wants 1
    # again, which would open a position outside the window, so it keeps the held 0
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=FixedScores([3.0, 0.0] + [1.0] * 8),
        contracts=None,
        signal_input="unadjusted",
        session=FuturesSessionPolicy(entry_window=("09:01", "09:01")),
    )
    assert result.targets.get_column("target").to_list() == [3, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def test_the_python_path_is_flat_by_close_too() -> None:
    execution = one_session([f"09:{minute:02d}" for minute in range(1, 11)] + ["15:59", "16:00"])
    result = futures_targets(
        root="ES",
        execution_bars=execution,
        signal_bars=execution,
        execution_ref=EXEC_REF,
        signal_ref=EXEC_REF,
        strategy=FixedScores([1.0] * 12),
        contracts=None,
        signal_input="unadjusted",
        session=FuturesSessionPolicy(flat_by_close=True),
    )
    assert result.targets.get_column("target").to_list() == [1] * 10 + [0, 0]


def test_a_session_policy_refuses_a_bad_clock() -> None:
    with pytest.raises(ConfigurationError, match=r"FuturesSessionPolicy\.exit_at"):
        FuturesSessionPolicy(exit_at="9:5")
    with pytest.raises(ConfigurationError, match=r"FuturesSessionPolicy\.entry_window end"):
        FuturesSessionPolicy(entry_window=("09:00", "25:00"))


# --- 7. the python score contract --------------------------------------------------------------


def test_a_non_integer_score_is_refused() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=FixedScores([1.0, 1.5, 0.0]),
            contracts=None,
            signal_input="unadjusted",
        )
    message = str(caught.value)
    assert "score=1.5" in message
    assert "not a whole number of contracts" in message
    assert "2024-03-05T15:02:00Z" in message


def test_a_missing_score_is_refused_naming_the_bar() -> None:
    execution = one_session(["09:01", "09:02", "09:03"])
    frame = pl.DataFrame(
        {"ts": execution.get_column("event_time").head(2), "score": [1.0, 0.0]},
        schema={"ts": pl.Int64(), "score": pl.Float64()},
    )
    with pytest.raises(ConfigurationError) as caught:
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=RawScores(frame),
            contracts=None,
            signal_input="unadjusted",
        )
    message = str(caught.value)
    assert "returned no score for the bar ending 2024-03-05T15:03:00Z" in message


@pytest.mark.parametrize(
    ("score", "fragment"),
    [
        (None, "returned a null score"),
        (float("nan"), "score=nan"),
        (float("inf"), "score=inf"),
    ],
)
def test_a_bad_score_value_is_refused(score: float | None, fragment: str) -> None:
    execution = one_session(["09:01", "09:02"])
    frame = pl.DataFrame(
        {
            "ts": execution.get_column("event_time"),
            "score": pl.Series([1.0, score], dtype=pl.Float64),
        },
        schema={"ts": pl.Int64(), "score": pl.Float64()},
    )
    with pytest.raises(ConfigurationError, match=fragment):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=RawScores(frame),
            contracts=None,
            signal_input="unadjusted",
        )


def test_a_score_frame_without_ts_is_refused() -> None:
    execution = one_session(["09:01", "09:02"])
    frame = pl.DataFrame({"score": [1.0, 1.0]})
    with pytest.raises(ConfigurationError, match="without \\['ts'\\]"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=RawScores(frame),
            contracts=None,
            signal_input="unadjusted",
        )


def test_a_python_function_cannot_also_be_given_contracts() -> None:
    execution = one_session(["09:01", "09:02"])
    with pytest.raises(ConfigurationError, match="already decides the size"):
        futures_targets(
            root="ES",
            execution_bars=execution,
            signal_bars=execution,
            execution_ref=EXEC_REF,
            signal_ref=EXEC_REF,
            strategy=FixedScores([1.0, 1.0]),
            contracts=2,
            signal_input="unadjusted",
        )


# --- 8. the compile wrapper (spec_positions) ----------------------------------------------------


def test_spec_positions_returns_the_sides_in_order() -> None:
    frame = one_session(["09:01", "09:02", "09:03", "09:04"])
    positions = spec_positions(spec(), frame)
    assert positions.dtype == np.int64
    assert positions.tolist() == [0, 0, 1, 1]


def test_spec_positions_honours_the_masks() -> None:
    frame = one_session(["09:01", "09:02", "09:03", "09:04"])
    positions = spec_positions(
        spec(),
        frame,
        entry_ok=np.asarray([True, True, False, False]),
        force_flat=np.asarray([False, False, False, True]),
    )
    assert positions.tolist() == [0, 0, 0, 0]


def test_spec_positions_freezes_a_bar_without_a_decision() -> None:
    level = parse_spec({"entry": {"long": "close > 5000"}, "exit": {"long": "close < 4000"}})
    frame = bars(
        [
            ("2024-03-05 09:01", ESH, 5100.0),
            ("2024-03-05 09:02", ESH, 5100.0),
            ("2024-03-05 09:03", ESH, 50.0),
            ("2024-03-05 09:04", ESH, 4910.0),
        ]
    )
    assert spec_positions(level, frame).tolist() == [1, 1, 0, 0]
    frozen = np.asarray([False, False, True, False])
    assert spec_positions(level, frame, frozen=frozen).tolist() == [1, 1, 1, 1]


def test_spec_positions_refuses_a_time_rule() -> None:
    frame = one_session(["09:01", "09:02", "09:03", "09:04"])
    timed = parse_spec({"entry": {"long": "time < 10:30"}, "exit": {"long": "time >= 15:00"}})
    with pytest.raises(ConfigurationError, match="FuturesSessionPolicy"):
        spec_positions(timed, frame)


def test_spec_positions_refuses_several_symbols() -> None:
    frame = one_session(["09:01", "09:02", "09:03"])
    other = frame.with_columns(pl.lit("NQ").alias("symbol"))
    with pytest.raises(ConfigurationError, match="one symbol per frame"):
        spec_positions(spec(), pl.concat([frame, other]))


def test_spec_positions_refuses_a_mask_of_the_wrong_length() -> None:
    frame = one_session(["09:01", "09:02", "09:03"])
    with pytest.raises(ConfigurationError, match="one mask value per bar"):
        spec_positions(spec(), frame, entry_ok=np.asarray([True, False]))
