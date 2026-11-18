"""The futures run's config, marks, daily ledger and metrics (ADR-0095), hand-computed.

Every expected number here is written out in the test, never read back from the engine. The
instrument is ES (tick 0.25, $50 a point, $12.50 a tick) with a $2.00 commission and the default
1-tick spread and 1-tick slippage, so a market fill costs $2.00 + (0.5 + 1) x $12.50 = $20.75 per
contract per side. Bars are minute bars on real Globex trade dates (2024-01-08, 2024-03-05 and
2024-03-06), and the OHLC marks are derived by hand from the marking policy in the module
docstring of ``crucible.experiments.futures_artifacts``.
"""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, InvariantViolation
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.cme_sessions import session_trade_dates
from crucible.data.continuous import calendar_for
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule, ExecutionPolicy, simulate_futures
from crucible.experiments.futures_artifacts import (
    FUTURES_DAILY_SCHEMA,
    FUTURES_FILLS_SCHEMA,
    FUTURES_MARKS_SCHEMA,
    MONEY,
    build_daily,
    build_fills,
    build_marks,
    build_metrics,
    build_rolls,
    check_daily_ledger,
)
from crucible.experiments.futures_config import (
    canonical_futures_yaml,
    futures_config_hash,
    futures_config_json_schema,
    load_futures_config,
    parse_futures_config,
)

_NS = 1_000_000_000
_MIN = 60 * _NS
ES = futures_spec("ES")
COSTS = CostSchedule(commission=Decimal("2.00"))
CAPITAL = Decimal("50000")
CALENDAR = calendar_for("ES")


# ---------------------------------------------------------------------------------------------
# fixtures and helpers


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def mapping(**overrides: object) -> dict[str, object]:
    """A valid futures-run config mapping, with ``overrides`` merged in by key path (``a.b``)."""
    base: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-sma-demo", "family": "es-intraday-sma"},
        "root": "ES",
        "datasets": {
            "execution": "es_1m_cont_v3",
            "signal": "es_1m_cont_ratio_v3",
            "rolls": "es_1m_rolls_v3",
            "raw": "es_1m_raw",
        },
        "window": {"start": "2024-03-04", "end": "2024-03-29"},
        "strategy": {
            "spec": {
                "entry": {"long": "close > sma(2)"},
                "exit": {"long": "close < sma(2)"},
            }
        },
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    out = copy.deepcopy(base)
    for path, value in overrides.items():
        parts = path.split(".")
        node: object = out
        for part in parts[:-1]:
            assert isinstance(node, dict)
            if part not in node:
                node[part] = {}
            node = node[part]
        assert isinstance(node, dict)
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return out


def bars(rows: list[tuple[int, tuple[float, float, float, float]]], contract: str = "ESH2024"):
    """Execution bars from ``(event_time ns, (open, high, low, close))``."""
    return pl.DataFrame(
        {
            "event_time": [t for t, _ in rows],
            "open": [prices[0] for _, prices in rows],
            "high": [prices[1] for _, prices in rows],
            "low": [prices[2] for _, prices in rows],
            "close": [prices[3] for _, prices in rows],
            "contract": [contract] * len(rows),
        }
    )


def dollars(values: list[int]) -> pl.Series:
    """Whole dollars as an exact ``Decimal(38, 6)`` money column (micro-dollars inside)."""
    return (pl.Series(values, dtype=pl.Int64) * 1_000_000).cast(pl.Decimal(38, 0)).cast(
        MONEY
    ) / 1_000_000


def no_rolls() -> pl.DataFrame:
    return pl.DataFrame(schema=ROLL_SCHEMA)


def simulate(execution: pl.DataFrame, targets: list[int]):
    frame = pl.DataFrame(
        {"event_time": execution["event_time"], "target": pl.Series(targets, dtype=pl.Int64)}
    )
    return simulate_futures(
        bars=execution,
        targets=frame,
        rolls=no_rolls(),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(),
    )


def marked(simulation, execution: pl.DataFrame) -> pl.DataFrame:
    """The marks of a simulation, with trade dates from the CME calendar."""
    days, on_schedule = session_trade_dates(CALENDAR, execution["event_time"].to_numpy(), 60)
    return build_marks(
        bars=simulation.bars,
        execution=execution,
        trade_dates=pl.Series(days),
        on_schedule=pl.Series(on_schedule),
        spec=ES,
    )


def usd(frame: pl.DataFrame, column: str) -> list[Decimal]:
    return [Decimal(value) for value in frame[column].to_list()]


# ---------------------------------------------------------------------------------------------
# 1. the config


def test_a_full_config_parses_and_resolves_its_fields() -> None:
    config = parse_futures_config(mapping())
    assert config.kind == "futures_run"
    assert config.root == "ES"
    assert config.run.family == "es-intraday-sma"
    assert config.window.start == dt.date(2024, 3, 4)
    assert config.capital == CAPITAL
    assert config.cost_schedule() == COSTS
    assert config.execution_policy() == ExecutionPolicy()
    assert config.session_policy().flat_by_close is False
    # the canonical YAML is what goes into the artifact, so it must carry the kind
    assert "kind: futures_run" in canonical_futures_yaml(config)
    assert "properties" in futures_config_json_schema()


def test_dataset_defaults_come_from_the_root() -> None:
    config = parse_futures_config(mapping(datasets=None))
    assert config.datasets.execution == "es_1m_cont_v3"
    assert config.datasets.signal == "es_1m_cont_ratio_v3"
    assert config.datasets.rolls == "es_1m_rolls_v3"
    assert config.datasets.raw == "es_1m_raw"


def test_an_unadjusted_default_signal_names_the_execution_series() -> None:
    config = parse_futures_config(mapping(datasets=None, **{"signal.input": "unadjusted"}))
    assert config.datasets.signal == config.datasets.execution == "es_1m_cont_v3"


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="broker"):
        parse_futures_config(mapping(broker="interactive-brokers"))


def test_the_trial_family_is_required() -> None:
    with pytest.raises(ConfigurationError, match="family"):
        parse_futures_config(mapping(**{"run.family": None}))


def test_spec_and_entrypoint_together_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="exactly one of spec"):
        parse_futures_config(mapping(**{"strategy.entrypoint": "examples.x:signal"}))


def test_no_strategy_source_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="got none"):
        parse_futures_config(mapping(**{"strategy.spec": None}))


def test_contracts_with_an_entrypoint_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="forbidden with an entrypoint"):
        parse_futures_config(
            mapping(**{"strategy.spec": None, "strategy.entrypoint": "examples.x:signal"})
        )


def test_contracts_are_required_for_a_spec() -> None:
    with pytest.raises(ConfigurationError, match="contracts is required"):
        parse_futures_config(mapping(contracts=None))


def test_an_unadjusted_signal_from_another_series_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="must be the series that executes"):
        parse_futures_config(mapping(**{"signal.input": "unadjusted"}))


def test_commission_is_required() -> None:
    with pytest.raises(ConfigurationError, match="commission"):
        parse_futures_config(mapping(costs={}))


def test_a_backwards_window_is_refused() -> None:
    with pytest.raises(ConfigurationError, match=r"before window.start"):
        parse_futures_config(mapping(**{"window.start": "2024-03-29", "window.end": "2024-03-04"}))


def test_an_unknown_root_is_refused_by_the_calendar_and_the_spec_table() -> None:
    with pytest.raises(ConfigurationError, match="no schedule for root"):
        parse_futures_config(mapping(root="ZZZ"))


def test_a_spec_path_is_loaded_relative_to_the_config_file_and_hashed_by_content(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sma.yaml"
    spec.write_text("entry:\n  long: close > sma(2)\nexit:\n  long: close < sma(2)\n", "utf-8")
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        "\n".join(
            [
                "kind: futures_run",
                "run: {name: es-sma-demo, family: es-intraday-sma}",
                "root: ES",
                "window: {start: 2024-03-04, end: 2024-03-29}",
                "strategy:",
                "  spec: sma.yaml",
                "contracts: 1",
                'capital: "50000"',
                'costs: {commission: "2.00"}',
                "",
            ]
        ),
        "utf-8",
    )
    first = load_futures_config(config_path)
    assert first.strategy.spec == {
        "entry": {"long": "close > sma(2)"},
        "exit": {"long": "close < sma(2)"},
    }
    assert first.strategy.spec is not None
    assert isinstance(first.strategy.spec, dict)
    # the config hash covers the spec CONTENT: editing the file changes it
    spec.write_text("entry:\n  long: close > sma(3)\nexit:\n  long: close < sma(3)\n", "utf-8")
    second = load_futures_config(config_path)
    assert second.strategy.spec != first.strategy.spec
    assert futures_config_hash(second) != futures_config_hash(first)


def test_a_missing_spec_file_names_the_resolved_path(tmp_path: Path) -> None:
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        "kind: futures_run\nroot: ES\nrun: {name: n, family: f}\n"
        "window: {start: 2024-03-04, end: 2024-03-29}\n"
        'strategy: {spec: nope.yaml}\ncontracts: 1\ncapital: "50000"\n'
        'costs: {commission: "2.00"}\n',
        "utf-8",
    )
    with pytest.raises(ConfigurationError, match=r"nope\.yaml"):
        load_futures_config(config_path)


# ---------------------------------------------------------------------------------------------
# 2. the marks


THREE = [
    (utc("2024-01-08 09:01"), (100.00, 101.00, 99.00, 100.00)),
    (utc("2024-01-08 09:02"), (100.50, 102.00, 100.00, 101.50)),
    (utc("2024-01-08 09:03"), (101.00, 101.25, 100.00, 100.75)),
]


def test_the_marks_are_one_row_per_bar_with_a_hand_computed_equity_path() -> None:
    execution = bars(THREE)
    # targets decided at each close: long from bar 1's close on (fills at bar 2's open 101.00)
    simulation = simulate(execution, [1, 1, 0])
    marks = marked(simulation, execution)

    assert marks.columns == list(FUTURES_MARKS_SCHEMA)
    assert marks["event_time"].to_list() == [t for t, _ in THREE]
    assert marks["position"].to_list() == [0, 1, 1]
    assert marks["contract"].to_list() == ["ESH2024"] * 3
    assert marks["on_schedule"].to_list() == [True] * 3
    # the close mark is the simulator's: bar 1 pays 20.75 and marks +50, bar 2 marks +12.50
    assert usd(marks, "equity_usd") == [Decimal(50000), Decimal("50029.25"), Decimal("49991.75")]
    assert usd(marks, "balance_usd") == [Decimal(50000), Decimal("49979.25"), Decimal("49979.25")]
    # bar 0: flat, so every candidate is the close mark
    # bar 1: p=1, close 101.50 -> 50029.25 + (100.00-101.50)*50 = 49954.25 (low)
    #                   50029.25 + (102.00-101.50)*50 = 50054.25 (high)
    #        cand_prev: q=0 -> 50000.00 both
    # bar 2: p=1, close 100.75 -> 49991.75 + (100.00-100.75)*50 = 49954.25
    #                   49991.75 + (101.25-100.75)*50 = 50016.75
    #        cand_prev: q=1, prev_close 101.50 -> 50029.25 + (100.00-101.50)*50 = 49954.25
    #                   50029.25 + (101.25-101.50)*50 = 50016.75
    assert usd(marks, "equity_low_usd") == [
        Decimal(50000),
        Decimal("49954.25"),
        Decimal("49954.25"),
    ]
    assert usd(marks, "equity_high_usd") == [
        Decimal(50000),
        Decimal("50054.25"),
        Decimal("50016.75"),
    ]
    # this bar's flows, not totals: one market fill at bar 1, nothing at bar 2
    assert usd(marks, "realized_usd") == [Decimal(0), Decimal(0), Decimal(0)]
    assert usd(marks, "costs_usd") == [Decimal(0), Decimal("20.75"), Decimal(0)]
    assert usd(marks, "unrealized_usd") == [Decimal(0), Decimal(50), Decimal("12.5")]


def test_a_contract_change_omits_the_carried_position_term() -> None:
    """Hand-built frames for the one case the simulator cannot produce alone: the OHLC series
    switches contract at bar 2, so the previous bar's position was in a DIFFERENT contract and
    its prices must not be carried into this bar's extremes."""
    execution = bars(
        [
            (utc("2024-01-08 09:01"), (100.00, 101.00, 99.00, 100.00)),
            (utc("2024-01-08 09:02"), (100.00, 101.00, 99.00, 100.00)),
            (utc("2024-01-08 09:03"), (100.00, 101.00, 99.00, 100.00)),
        ]
    )
    execution = execution.with_columns(pl.Series("contract", ["ESH2024", "ESH2024", "ESM2024"]))
    simulation = pl.DataFrame(
        {
            "event_time": execution["event_time"],
            "contract": ["ESH2024", "ESH2024", "ESM2024"],
            "position": [0, 1, 1],
            "realized_usd": dollars([0, 0, 0]),
            "costs_usd": dollars([0, 0, 0]),
            "balance_usd": dollars([50000, 50000, 50000]),
            "equity_usd": dollars([50000, 50000, 50000]),
            "unrealized_usd": dollars([0, 0, 0]),
        }
    )
    days, on_schedule = session_trade_dates(CALENDAR, execution["event_time"].to_numpy(), 60)
    marks = build_marks(
        bars=simulation,
        execution=execution,
        trade_dates=pl.Series(days),
        on_schedule=pl.Series(on_schedule),
        spec=ES,
    )
    # bar 2: p=1, close 100 -> 50000 + (99-100)*50 = 49950 (low), 50000 + (101-100)*50 = 50050
    # the carried-in candidate (q=1 against bar 1's close 100) would be the SAME numbers here,
    # so the exception is proven by the contract column, not by a different value
    assert marks["contract"].to_list() == ["ESH2024", "ESH2024", "ESM2024"]
    assert usd(marks, "equity_low_usd")[2] == Decimal(49950)
    assert usd(marks, "equity_high_usd")[2] == Decimal(50050)


def test_the_fills_carry_their_trade_date_and_the_position_after_them() -> None:
    execution = bars(THREE)
    simulation = simulate(execution, [1, 1, 0])
    marks = marked(simulation, execution)
    fills = build_fills(fills=simulation.fills, marks=marks)
    assert fills.columns == [
        "event_time",
        "fill_time",
        "contract",
        "kind",
        "quantity",
        "price",
        "realized_usd",
        "fees_usd",
        "spread_usd",
        "slippage_usd",
        "trade_date",
        "position_after",
    ]
    assert fills["quantity"].to_list() == [1]
    assert fills["position_after"].to_list() == [1]
    assert fills["trade_date"].to_list() == [dt.date(2024, 1, 8)]
    assert fills["fill_time"].to_list() == [int(execution["event_time"][1]) - _MIN]
    assert build_rolls(simulation.rolls).height == 0


# ---------------------------------------------------------------------------------------------
# 3. the daily ledger


TWO_DAYS = [
    (utc("2024-03-05 09:01"), (100.00, 101.00, 99.00, 100.00)),
    (utc("2024-03-05 09:02"), (100.50, 102.00, 100.00, 101.50)),
    (utc("2024-03-06 09:01"), (101.00, 101.25, 100.00, 100.75)),
    (utc("2024-03-06 09:02"), (100.25, 100.50, 100.00, 100.50)),
]


def _two_days() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    execution = bars(TWO_DAYS)
    simulation = simulate(execution, [1, 1, 0, 0])
    marks = marked(simulation, execution)
    fills = build_fills(fills=simulation.fills, marks=marks)
    daily = build_daily(
        marks=marks, bars=simulation.bars, fills=fills, calendar=CALENDAR, capital=CAPITAL
    )
    return marks, fills, daily


def test_the_daily_ledger_folds_two_hand_computed_trade_dates() -> None:
    marks, _fills, daily = _two_days()
    assert daily.columns == list(FUTURES_DAILY_SCHEMA)
    assert daily["trade_date"].to_list() == [dt.date(2024, 3, 5), dt.date(2024, 3, 6)]
    # the scheduled bounds are the calendar's, not the data's first and last bar
    first = CALENDAR.session(dt.date(2024, 3, 5))
    second = CALENDAR.session(dt.date(2024, 3, 6))
    assert daily["session_open_ns"].to_list() == [first.open_ns, second.open_ns]
    assert daily["session_close_ns"].to_list() == [first.close_ns, second.close_ns]
    assert daily["verified"].to_list() == [first.verified, second.verified]
    assert daily["bars"].to_list() == [2, 2]
    assert daily["first_bar_ns"].to_list() == [TWO_DAYS[0][0], TWO_DAYS[2][0]]
    assert daily["last_bar_ns"].to_list() == [TWO_DAYS[1][0], TWO_DAYS[3][0]]
    # day 1: bought 1 at 100.50 (bar 1's open), costs 20.75, close mark +50
    # day 2: sold 1 at 100.25 (bar 3's open), realized -12.50, costs 20.75
    assert usd(daily, "opening_balance_usd") == [Decimal(50000), Decimal("49979.25")]
    assert usd(daily, "closing_balance_usd") == [Decimal("49979.25"), Decimal(49946)]
    assert usd(daily, "opening_equity_usd") == [Decimal(50000), Decimal("50029.25")]
    assert usd(daily, "closing_equity_usd") == [Decimal("50029.25"), Decimal(49946)]
    assert usd(daily, "realized_usd") == [Decimal(0), Decimal("-12.5")]
    assert usd(daily, "fees_usd") == [Decimal(2), Decimal(2)]
    assert usd(daily, "spread_usd") == [Decimal("6.25"), Decimal("6.25")]
    assert usd(daily, "slippage_usd") == [Decimal("12.5"), Decimal("12.5")]
    assert usd(daily, "costs_usd") == [Decimal("20.75"), Decimal("20.75")]
    assert usd(daily, "unrealized_close_usd") == [Decimal(50), Decimal(0)]
    # day 1 marks: bar 0 flat (50000/50000), bar 1 49954.25 .. 50054.25
    # day 2 marks: bar 2 49954.25 .. 50016.75, bar 3 flat at 49946 with the carried-in
    #              49954.25 .. 49979.25 (equity_low stays the close 49946)
    assert usd(daily, "min_equity_usd") == [Decimal("49954.25"), Decimal(49946)]
    assert usd(daily, "max_equity_usd") == [Decimal("50054.25"), Decimal("50016.75")]
    assert daily["max_contracts"].to_list() == [1, 1]
    assert daily["fills"].to_list() == [1, 1]
    check_daily_ledger(daily, marks, CAPITAL)


def _tamper(daily: pl.DataFrame, column: str, row: int, amount: Decimal) -> pl.DataFrame:
    values = [Decimal(value) for value in daily[column].to_list()]
    values[row] += amount
    return daily.with_columns(
        pl.Series(column, values, dtype=MONEY).alias(column),
    )


def test_a_run_that_never_trades_has_empty_fills_and_a_flat_ledger() -> None:
    execution = bars(THREE)
    simulation = simulate(execution, [0, 0, 0])
    marks = marked(simulation, execution)
    fills = build_fills(fills=simulation.fills, marks=marks)
    assert fills.height == 0
    assert fills.columns == list(FUTURES_FILLS_SCHEMA)
    daily = build_daily(
        marks=marks, bars=simulation.bars, fills=fills, calendar=CALENDAR, capital=CAPITAL
    )
    assert daily["fills"].to_list() == [0]
    assert usd(daily, "opening_balance_usd") == usd(daily, "closing_balance_usd")
    check_daily_ledger(daily, marks, CAPITAL)


def test_the_daily_ledger_refuses_a_broken_identity_1() -> None:
    marks, _fills, daily = _two_days()
    with pytest.raises(InvariantViolation, match=r"closing_balance = opening_balance.*2024-03-05"):
        check_daily_ledger(_tamper(daily, "closing_balance_usd", 0, Decimal(1)), marks, CAPITAL)


def test_the_daily_ledger_refuses_a_broken_identity_2() -> None:
    marks, _fills, daily = _two_days()
    with pytest.raises(InvariantViolation, match=r"closing_equity = closing_balance.*2024-03-05"):
        check_daily_ledger(_tamper(daily, "unrealized_close_usd", 0, Decimal(5)), marks, CAPITAL)


def test_the_daily_ledger_refuses_a_broken_chain() -> None:
    marks, _fills, daily = _two_days()
    # day 2 opens 1 USD higher, its close moves with it and its unrealized close against it, so
    # only the opening-balance chain is broken
    broken = _tamper(daily, "opening_balance_usd", 1, Decimal(1))
    broken = _tamper(broken, "closing_balance_usd", 1, Decimal(1))
    broken = _tamper(broken, "unrealized_close_usd", 1, Decimal(-1))
    with pytest.raises(InvariantViolation, match=r"previous day's closing_balance.*2024-03-06"):
        check_daily_ledger(broken, marks, CAPITAL)


def test_the_daily_ledger_refuses_a_broken_equity_chain() -> None:
    marks, _fills, daily = _two_days()
    with pytest.raises(InvariantViolation, match=r"previous day's closing_equity.*2024-03-06"):
        check_daily_ledger(_tamper(daily, "opening_equity_usd", 1, Decimal(1)), marks, CAPITAL)


def test_the_daily_ledger_refuses_extremes_that_exclude_the_close() -> None:
    marks, _fills, daily = _two_days()
    with pytest.raises(
        InvariantViolation,
        match=r"min_equity <= closing_equity <= max_equity.*2024-03-05",
    ):
        check_daily_ledger(_tamper(daily, "min_equity_usd", 0, Decimal(5000)), marks, CAPITAL)


def test_the_daily_ledger_refuses_a_close_that_is_not_the_last_mark() -> None:
    marks, _fills, daily = _two_days()
    tampered_marks = _tamper(marks, "equity_usd", 3, Decimal("0.01"))
    with pytest.raises(InvariantViolation, match=r"last mark's equity_usd.*2024-03-06"):
        check_daily_ledger(daily, tampered_marks, CAPITAL)


def test_the_daily_ledger_refuses_a_day_row_written_twice() -> None:
    marks, _fills, daily = _two_days()
    # identity 7 (the summed flows equal the balance move) telescopes out of identity 3, so it
    # cannot fail on its own; what it backstops is a day row that is not in the chain at all --
    # a duplicated day row, whose opening balance is not the previous row's close
    duplicated = pl.concat([daily, daily.tail(1)]).select(list(FUTURES_DAILY_SCHEMA))
    with pytest.raises(InvariantViolation, match=r"previous day's closing_balance.*2024-03-06"):
        check_daily_ledger(duplicated, marks, CAPITAL)


def test_the_daily_flows_add_up_to_the_balance_move() -> None:
    marks, _fills, daily = _two_days()
    flows = sum(usd(daily, "realized_usd")) - sum(usd(daily, "costs_usd"))
    assert flows == usd(daily, "closing_balance_usd")[-1] - CAPITAL == Decimal(-54)
    check_daily_ledger(daily, marks, CAPITAL)


# ---------------------------------------------------------------------------------------------
# 4. the metrics


def test_the_metrics_are_descriptive_totals_only() -> None:
    marks, fills, daily = _two_days()
    metrics = build_metrics(
        marks=marks, daily=daily, fills=fills, rolls=no_rolls(), capital=CAPITAL
    )
    names = sorted(metrics)
    forbidden = ("sharpe", "return", "ratio", "edge")
    assert not [name for name in names if any(word in name for word in forbidden)]
    assert names == sorted(
        [
            "final_balance_usd",
            "final_equity_usd",
            "net_pnl_usd",
            "total_costs_usd",
            "fills",
            "rolls",
            "trade_dates",
            "max_contracts",
            "min_equity_usd",
            "max_intraday_drawdown_usd",
        ]
    )
    for entry in metrics.values():
        assert set(entry) == {"value", "ci_low", "ci_high"}
        assert entry["ci_low"] is None
        assert entry["ci_high"] is None
    assert metrics["final_balance_usd"]["value"] == 49946
    assert metrics["final_equity_usd"]["value"] == 49946
    assert metrics["net_pnl_usd"]["value"] == -54
    assert metrics["total_costs_usd"]["value"] == 41.5
    assert metrics["fills"]["value"] == 2
    assert metrics["rolls"]["value"] == 0
    assert metrics["trade_dates"]["value"] == 2
    assert metrics["max_contracts"]["value"] == 1
    assert metrics["min_equity_usd"]["value"] == 49946
    # running max of equity_high minus the bar's equity_low:
    # 0 (bar 0), 50054.25-49954.25 = 100 (bar 1), 50054.25-49954.25 = 100 (bar 2),
    # 50054.25-49946 = 108.25 (bar 3)
    assert metrics["max_intraday_drawdown_usd"]["value"] == 108.25
