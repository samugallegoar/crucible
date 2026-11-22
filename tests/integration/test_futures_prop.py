"""Prop evaluation over a futures run: the attempt classes, the statistics and the labels.

ADR-0107 sections 4-6 and 10-12, hand-checked on a synthetic store. The series is 16 ES Globex
trade dates of 2024-06 with two one-minute bars a day at a constant price inside each day, so the
mark-to-market P&L of an attempt is ``(P(end) - P(start)) * 50`` minus the commissions and nothing
else: spread and slippage are 0 in the config, and the ruleset's commission is $2.00 per side (one
contract, so $4.00 a round trip). The strategy is always long one contract, which makes every
start's path a known function of the daily price list::

    trade date   06-03 06-04 06-05 06-06 06-07 06-10 06-11 06-12 06-13 06-14 06-17 06-18 …
    price (pts)   4800  4830  4780  4780  4810  4760  4760  4790  4740  4740  4740  4740 …
    delta              +30   -50     0   +30   -50     0   +30   -50     0     0     0 …

The ruleset is one evaluation phase: a $2,000 static drawdown on intraday equity (a hard
``fail``) and a $1,000 profit target on the end-of-day equity (a ``pass``). A +30-point move is
$1,500 (over the target), a -50-point move is -$2,500 (through the drawdown) and a flat stretch
reaches neither.

Nothing here reads the real Crucible home, writes into the repository or touches a real dataset:
every store, home and artifacts root is a ``tmp_path``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError, VaultLockedError
from crucible.core.types import DatasetId
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.econ_events import ECON_EVENT_SCHEMA, ECON_EVENT_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import FuturesRunConfig, parse_futures_config
from crucible.experiments.futures_prop import (
    CONDITIONAL_PASS_PROBABILITY,
    PASS_PROBABILITY,
    RESULT_FILES,
    prop_block_length,
    run_prop_evaluation,
)
from crucible.experiments.futures_stats import bootstrap_seed
from crucible.prop.rules_schema import Instrument
from crucible.prop.ruleset import Attribution, PropRuleset, load_ruleset
from crucible.validation.trial_registry import DuckDBTrialRegistry

_COMPONENTS_ALL_IN = {
    name: {"status": "included", "evidence": "official_quote", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission whose four cost components are all inside it (synthetic, all-in)."""
_COMPONENTS_EXCLUDED = {
    name: {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission that excludes every component: each is charged on top (synthetic)."""
_COMPONENTS_UNKNOWN = {
    name: {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission whose four components the source does not state (synthetic)."""


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from crucible.experiments.futures_prop import PropEvaluationResult

NS = 1_000_000_000
ESH = "ESH2024"
DAYS = [
    dt.date(2024, 6, day) for day in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18, 20, 21, 24, 25)
]
"""Sixteen consecutive ES trade dates (2024-06-19 is Juneteenth: not a Globex trade date)."""

PRICES = [
    4800,
    4830,
    4780,
    4780,
    4810,
    4760,
    4760,
    4790,
    4740,
    4740,
    4740,
    4740,
    4740,
    4740,
    4740,
    4740,
]
"""The daily price of the series: +30 on four dates, -50 on three, flat on the rest."""

FAMILY = "prop-evaluation-test"


class AlwaysLong:
    """A ``FuturesSignalFunction`` that asks for one long contract on every bar (size 1)."""

    scale_invariant = True

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        del params
        return bars.select(
            pl.col("event_time").alias("ts"),
            pl.lit(1, dtype=pl.Int64).alias("score"),
        )


ALWAYS_LONG = AlwaysLong()
"""The entrypoint object: ``test_futures_prop:ALWAYS_LONG``."""


def ct_ns(day: dt.date, hour: int, minute: int) -> int:
    """UTC ns of a Chicago wall clock in June (CDT, UTC-5); the tests never rely on DST edges."""
    stamp = dt.datetime(day.year, day.month, day.day, hour + 5, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * NS


def _stamps() -> list[int]:
    """Three bars a day: 09:01 and 09:02 Chicago, then the bar that closes the scheduled session.

    The first two make a fill land inside its own trade date (a target decided at 09:01's close is
    filled at 09:02's open); the third ends at the session's scheduled close (16:00 Chicago), which
    is the causally known end of the rule-day (``PropAccountOverlay._rule_day_ended``), so the
    end-of-day tests and the firm's own time limit can fire.
    """
    out: list[int] = []
    for day in DAYS:
        out.extend([ct_ns(day, 9, 1), ct_ns(day, 9, 2), ct_ns(day, 16, 0)])
    return out


def _continuous() -> pl.DataFrame:
    stamps = _stamps()
    prices = [price for price in PRICES for _ in range(3)]
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(stamps),
            "event_time": stamps,
            # a bar's OHLC is known at its close: available_at == event_time (a +1 ns would put
            # the window's final bar past the run's read horizon and drop it)
            "available_at": stamps,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [100.0] * len(stamps),
            "contract": [ESH] * len(stamps),
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _raw(execution: pl.DataFrame) -> pl.DataFrame:
    return execution.select(list(BAR_SCHEMA))


def _event(
    event_id: str,
    event_type: str,
    *,
    event_time: int,
    time_known: bool,
    scheduled_local: str,
) -> dict[str, object]:
    """One row of the economic calendar in the shape ``build_econ_events`` writes."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "scheduled_local": scheduled_local,
        "timezone": "America/New_York",
        "event_time": event_time,
        "time_known": time_known,
        "scheduled_time_source": "bls_stated" if time_known else "not_stated",
        "status": "released",
        "actual_publication_date": dt.datetime.fromtimestamp(event_time // NS, dt.UTC)
        .date()
        .isoformat(),
        "unscheduled": False,
        "source_url": "https://www.bls.gov/schedule/2024/home.htm",
        "snapshot_sha256": "0" * 64,
        "available_at": event_time,
        "availability_basis": "schedule_publication_unknown",
        "record_sha256": "1" * 64,
        "dataset_version": 2,
    }


def _calendar_rows() -> pl.DataFrame:
    """A synthetic calendar: a monthly CPI release and a day-only FOMC press conference.

    The June CPI is placed at 09:01 Chicago on 2024-06-12, i.e. INSIDE the two bars of that trade
    date, so a five-minute news window blocks both of them; every other CPI row is at 07:30
    Chicago, outside the bars. A press conference gets no stated hour (``time_known: False``), which
    is what the real dataset says about it: its whole trade date is a reported coverage gap.

    Rows run from January to December 2024 for both types, so the calendar's covered intervals span
    the whole evaluation window (``crucible.data.econ_events.coverage_of`` measures coverage in
    contiguous months).
    """
    rows: list[dict[str, object]] = []
    for month in range(1, 13):
        day = dt.date(2024, month, 12)
        inside = month == 6
        rows.append(
            _event(
                f"CPI-2024{month:02d}12",
                "CPI",
                event_time=ct_ns(day, 9, 1) if inside else ct_ns(day, 7, 30),
                time_known=True,
                scheduled_local=f"2024-{month:02d}-12T08:30:00-04:00",
            )
        )
    for day in (dt.date(2024, 1, 31), dt.date(2024, 6, 13), dt.date(2024, 12, 18)):
        rows.append(
            _event(
                f"FOMC_PRESS_CONFERENCE-{day.strftime('%Y%m%d')}",
                "FOMC_PRESS_CONFERENCE",
                event_time=ct_ns(day, 0, 0) - 5 * 60 * 60 * NS,
                time_known=False,
                scheduled_local=f"{day.isoformat()}T00:00:00-04:00",
            )
        )
    return pl.DataFrame(rows, orient="row", schema=ECON_EVENT_SCHEMA)


def build_store(root: Path, *, exchange_fees: bool | None = None) -> Path:
    """The four synthetic futures datasets, the synthetic calendar and, on demand, a fee table."""
    root.mkdir(parents=True, exist_ok=True)
    execution = _continuous()
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        pl.DataFrame(schema=ROLL_SCHEMA),
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        _raw(execution),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=48;synthetic",
    )
    build_dataset(
        root,
        DatasetId("econ_events_v2"),
        _calendar_rows(),
        schema=ECON_EVENT_SCHEMA,
        sort_keys=ECON_EVENT_SORT_KEYS,
        source="synthetic calendar written by a prop test",
    )
    if exchange_fees is not None:
        _write_fee_table(root, exchange=exchange_fees)
    return root


def _fee_row(
    root: str,
    fee_type: str,
    amount: str,
    participant_type: str,
    covers: str,
    source_kind: str,
) -> dict:
    """One row of the exchange-fees contract, in the shape ``build_exchange_fees`` writes."""
    from crucible.data import exchange_fees as ef

    day = dt.date(2024, 1, 1)
    stamp = int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC).timestamp()) * NS
    row: dict[str, object] = {
        "root": root,
        "venue": ef.VENUE_OF[root],
        "fee_type": fee_type,
        "participant_type": participant_type,
        "covers": covers,
        "per_side_usd": amount,
        "effective_from": day,
        "effective_to": None,
        "source_kind": source_kind,
        "provided_by": "owner" if source_kind == ef.SOURCE_KIND_OWNER else None,
        "source_url": "https://example.invalid/synthetic-fees",
        "snapshot_sha256": "0" * 64,
        "quote": "SYNTHETIC TEST VALUE: a fee row invented for a test",
        "event_time": stamp,
        "available_at": stamp,
        "dataset_version": ef.DATASET_VERSION,
    }
    row["record_sha256"] = ef.record_sha256(row)
    return row


def _write_fee_table(root: Path, *, exchange: bool) -> None:
    """The exchange-fees dataset: NFA rows always, the exchange rows only when asked for."""
    from crucible.data import exchange_fees as ef

    rows = [
        _fee_row(name, "nfa", "0.02", ef.PARTICIPANT_TYPE_NFA, "nfa", ef.SOURCE_KIND_OFFICIAL)
        for name in ef.ROOTS
    ]
    if exchange:
        rows.extend(
            _fee_row(
                name,
                "exchange",
                "1.25",
                ef.PARTICIPANT_TYPE_EXCHANGE,
                "exchange;clearing",
                ef.SOURCE_KIND_OWNER,
            )
            for name in ef.ROOTS
        )
    build_dataset(
        root,
        ef.DATASET,
        pl.DataFrame(rows, orient="row", schema=ef.EXCHANGE_FEE_SCHEMA),
        schema=ef.EXCHANGE_FEE_SCHEMA,
        sort_keys=ef.EXCHANGE_FEE_SORT_KEYS,
        source="synthetic rows written by a prop test",
    )


def mapping(**overrides: object) -> dict[str, object]:
    """A valid futures-run config mapping for the synthetic store, with overrides by key path."""
    import copy

    base: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "prop-evaluation", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAYS[0].isoformat(), "end": DAYS[-1].isoformat()},
        "strategy": {"entrypoint": "test_futures_prop:ALWAYS_LONG"},
        "capital": "50000",
        "costs": {"commission": "2.00", "spread_ticks": "0", "slippage_ticks": "0"},
        "statistics": {"resamples": 200},
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


def config(**overrides: object) -> FuturesRunConfig:
    return parse_futures_config(mapping(**overrides))


def _source(*, synthetic: bool = True) -> dict[str, object]:
    return Attribution(
        url="https://example.invalid/synthetic-rules",
        quote="Synthetic rule value invented for a test, not a real firm's rule",
        snapshot_sha256="0" * 64,
        retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        synthetic=synthetic,
    ).model_dump(mode="json")


DRAWDOWN: dict[str, object] = {
    "kind": "static_drawdown",
    "rule_id": "loss_limit",
    "amount_usd": "2000",
    "basis": "equity",
    "evaluated": "intraday",
    "comparison": "<=",
    "action": "fail",
}
"""A $2,000 static drawdown on intraday equity: a -50-point move (-$2,500) is a hard fail."""

TARGET: dict[str, object] = {
    "kind": "profit_target",
    "rule_id": "target",
    "amount_usd": "1000",
    "basis": "equity",
    "evaluated": "eod",
    "comparison": ">=",
    "action": "promote_phase",
    "require_flat": False,
}
"""A $1,000 target on the end-of-day equity: a +30-point move (+$1,500) reaches it."""


def ruleset(
    rules: Sequence[Mapping[str, object]],
    pass_conditions: Sequence[Mapping[str, object]] = (),
    *,
    max_trading_days: int | None = None,
    commissions: Mapping[str, object] | None = None,
    fees: Sequence[Mapping[str, object]] = (),
    conflicts: Sequence[Mapping[str, object]] = (),
    extra_rules: Sequence[Mapping[str, object]] = (),
    synthetic: bool = True,
    effective_from: str = "2024-01-01",
) -> PropRuleset:
    """A synthetic single-phase evaluation ruleset over ES."""
    source = _source(synthetic=synthetic)
    declared = [dict(rule) for rule in (*rules, *pass_conditions, *extra_rules)]
    declared_fees = [dict(fee) for fee in fees]
    for fee in declared_fees:
        fee.setdefault("source", source)
    for rule in declared:
        rule.setdefault("source", source)
        rule.setdefault("evidence", "official_quote")
    phase_rules = [rule for rule in declared if rule.get("kind") not in _PASS_KINDS]
    phase_pass = [rule for rule in declared if rule.get("kind") in _PASS_KINDS]
    commission_table = (
        dict(commissions)
        if commissions is not None
        else {
            "status": "known",
            "components": _COMPONENTS_ALL_IN,
            "per_side_usd": {"ES": "2.00"},
            "platform": None,
            "source": source,
        }
    )
    return PropRuleset.model_validate(
        {
            "schema_version": 2,
            "ruleset_id": "synthetic-prop-evaluation",
            "version": 1,
            "firm": "SyntheticFirm A",
            "program": "Synthetic Evaluation",
            "account_size_usd": "50000",
            "as_of": "2024-01-01",
            "effective_from": effective_from,
            "instruments": [{"root": "ES", "contract_weight": "1"}],
            "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            "commissions": commission_table,
            "conflicts": [dict(conflict) for conflict in conflicts],
            "phases": [
                {
                    "phase_id": "evaluation",
                    "kind": "evaluation",
                    "starting_balance_usd": "50000",
                    "rules": phase_rules,
                    "pass_conditions": phase_pass,
                    "fees": declared_fees,
                    "max_trading_days": max_trading_days,
                }
            ],
        }
    )


_PASS_KINDS = {
    "profit_target",
    "min_trading_days",
    "consistency",
    "activity_requirement",
}


def write_ruleset(path: Path, ruleset_object: PropRuleset) -> Path:
    """Write a ruleset as the YAML a firm file has (the loader recomputes the same hash)."""
    document = json.loads(ruleset_object.model_dump_json())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8", newline="\n")
    return path


def write_cost_assumption(
    path: Path, *, covers: Sequence[str], amount: str = "0.77", root: str = "ES"
) -> Path:
    """A SYNTHETIC cost-assumption file pricing ``covers`` for one root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "name": "synthetic-owner-estimate",
        "description": "SYNTHETIC TEST VALUE: a cost estimate invented for a test",
        "provided_by": "owner",
        "status": "unverified",
        "evidence": "SYNTHETIC TEST VALUE: no document states this split",
        "amounts": {root: [{"covers": list(covers), "per_side_usd": amount}]},
    }
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8", newline="\n")
    return path


def evaluate(
    store: Path,
    artifacts: Path,
    *,
    rules: Sequence[Mapping[str, object]] = (DRAWDOWN,),
    pass_conditions: Sequence[Mapping[str, object]] = (TARGET,),
    horizon: int = 5,
    run_config: FuturesRunConfig | None = None,
    scenarios: str = "primary",
    **options: object,
) -> PropEvaluationResult:
    """One evaluation of a synthetic ruleset over the synthetic store."""
    ruleset_options = {
        key: value
        for key, value in options.items()
        if key not in ("cost_assumption", "fee_participant_type")
    }
    ruleset_file = write_ruleset(
        artifacts / "ruleset.yaml",
        ruleset(rules, pass_conditions, **ruleset_options),  # type: ignore[arg-type]
    )
    return run_prop_evaluation(
        run_config if run_config is not None else config(),
        ruleset_path=ruleset_file,
        horizon_trading_days=horizon,
        execution_mode="manual",
        scenarios=scenarios,
        cost_assumption=options.get("cost_assumption"),  # type: ignore[arg-type]
        fee_participant_type=options.get("fee_participant_type"),  # type: ignore[arg-type]
        store_root=store,
        artifacts_root=artifacts,
        overwrite=True,
    )


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("prop_store") / "store")


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


# --------------------------------------------------------------------------- 1. the outcome classes


def test_the_outcome_classes_and_the_bounds_are_the_hand_computed_ones(
    store: Path, artifacts: Path
) -> None:
    """16 starts, H = 5 trade dates, and one class per start, by the price list's arithmetic.

    ``p = 5 / 12 = 0.4166…`` (five passes over the twelve starts whose H trade dates fit in the
    data), ``p_low = 5 / 16 = 0.3125`` (the four censored starts counted as failures) and
    ``p_high = (5 + 4) / 16 = 0.5625`` (counted as passes). The block length is
    ``max(H=5, ceil(sqrt(12))=4) = 5``, ``n = 12 >= 2 * 5``, so the interval is available and its
    endpoints are the bootstrap's own percentile: the arithmetic above fixes the VALUE and the
    bounds, and the interval is asserted only for its reproducibility (below).

    Per start, the price list gives:

    - starts 06-03, 06-05, 06-06, 06-10, 06-11: a +30-point move within the horizon -> ``pass``;
    - starts 06-04, 06-07, 06-12: a -50-point move -> ``fail``;
    - starts 06-13 .. 06-18: flat through the horizon -> ``horizon``;
    - starts 06-20 .. 06-25: the data ends inside the horizon -> ``censored``.
    """
    result = evaluate(store, artifacts)
    summary = result.summary["scenarios"][0]
    assert summary["scenario_id"] == "primary"
    assert summary["scenario_label"] == "official_primary"
    assert summary["starts"] == 16
    assert summary["complete_starts"] == 12
    assert summary["counts"] == {
        "pass": 5,
        "fail": 3,
        "timeout": 0,
        "horizon": 4,
        "censored": 4,
    }
    probability = summary["probability"]
    assert probability["value"] == pytest.approx(5 / 12)
    assert probability["passes"] == 5
    assert probability["passes_complete"] == 5
    assert probability["bounds"] == {"low": pytest.approx(5 / 16), "high": pytest.approx(9 / 16)}
    assert probability["effective_independent_attempts"] == pytest.approx(12 / 5)

    # the start dates, the horizon ends and the classes, per row
    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    assert frame.height == 16
    assert frame["start_trade_date"].to_list() == DAYS
    assert frame["outcome"].to_list() == [
        "pass",  # 06-03: +30 -> +1,500 > 1,000
        "fail",  # 06-04: -50 -> -2,500 < -2,000
        "pass",  # 06-05: flat, then +30
        "pass",  # 06-06: +30
        "fail",  # 06-07: -50
        "pass",  # 06-10: flat, then +30
        "pass",  # 06-11: +30
        "fail",  # 06-12: -50
        "horizon",  # 06-13 .. 06-18 are flat
        "horizon",
        "horizon",
        "horizon",
        "censored",  # the data ends before d + H
        "censored",
        "censored",
        "censored",
    ]
    assert frame["complete"].to_list() == [True] * 12 + [False] * 4
    # a pass on 06-05 needed two trade dates (06-05 flat, 06-06 +30): the horizon starts at 06-05
    assert frame["horizon_end_trade_date"].to_list()[2] == dt.date(2024, 6, 11)
    # the 06-20 start's five H trade dates end on 06-26, which is past the data: censored, not short
    assert frame["horizon_end_trade_date"].to_list()[12] == dt.date(2024, 6, 26)
    assert frame["breached_rule"].to_list()[1] == "loss_limit"
    assert frame["breached_rule"].to_list()[0] is None
    # days to pass are measured from the attempt's OWN start, not from the data's first bar: the
    # 06-05 start passes at the close of 06-07, three trading days (06-05, 06-06, 06-07) and two
    # calendar days later. Its attempt window begins at bar 6, so an index measured from the data's
    # first bar would report nonsense (or a date read from the wrong bar).
    assert frame["days_to_pass_trading"].to_list()[0] == 2
    assert frame["days_to_pass_calendar"].to_list()[0] == 1
    assert frame["days_to_pass_trading"].to_list()[2] == 3
    assert frame["days_to_pass_calendar"].to_list()[2] == 2
    # the commissions are charged INSIDE the simulated account (they move its equity); the attempt
    # fee columns carry the ruleset's own fees, and this ruleset declares none
    assert frame["fees_usd"].to_list()[0] == Decimal("0.000000")
    assert frame["net_cash_usd"].to_list()[0] == Decimal("0.000000")
    assert frame["payouts_usd"].to_list()[0] == Decimal("0.000000")


def test_the_bootstrap_seed_comes_from_the_evaluation_id_and_the_statistic(
    store: Path, artifacts: Path
) -> None:
    """``bootstrap_seed(evaluation_id, statistic)`` is the recorded seed, not a global sequence."""
    result = evaluate(store, artifacts)
    summary = result.summary["scenarios"][0]
    records = summary["bootstrap"]
    assert set(records) == {"pass_probability", "mean_net_cash_usd"}
    for name, record in records.items():
        assert record["seed"] == bootstrap_seed(result.evaluation_id, name)
        assert record["observations"] == 12
        assert record["block_length"] == 5
        assert record["block_length_policy"] == "max(horizon_trading_days, ceil(sqrt(n)))"
        assert record["rng"] == "numpy.random.PCG64"
    assert prop_block_length(12, 5) == 5
    assert prop_block_length(400, 5) == 20  # ceil(sqrt(400)) = 20 > H
    assert prop_block_length(1, 20) == 20  # one block is always H trade dates long


def test_a_short_sequence_has_no_interval_and_says_why(store: Path, artifacts: Path) -> None:
    """H = 8 leaves 9 complete starts, fewer than two blocks of 8: ``unavailable``, with a reason.

    The nine starts 06-03 .. 06-13 have their eight H trade dates inside the data (06-03 + 7 trade
    dates = 06-12; 06-13 + 7 = 06-25), and 9 < 2 * 8 = 16, so no dispersion is reported.
    """
    result = evaluate(store, artifacts, horizon=8)
    summary = result.summary["scenarios"][0]
    assert summary["starts"] == 16
    assert summary["complete_starts"] == 9
    interval = summary["probability"]["interval"]
    assert interval["status"] == "unavailable"
    assert interval["low"] is None
    assert interval["high"] is None
    assert "fewer than two blocks of 8 trade dates" in interval["reason"]
    cash_interval = summary["cash"]["interval"]
    assert cash_interval["status"] == "unavailable"
    assert "fewer than two blocks" in cash_interval["reason"]


def test_the_firms_own_time_limit_is_a_timeout_not_a_horizon(store: Path, artifacts: Path) -> None:
    """A three-trading-day limit ends the flat starts as ``timeout`` instead of ``horizon``.

    The same price list, so the fails are unchanged. A start on trade date ``i`` times out on
    ``i + 2``: the four flat starts (06-13 .. 06-18) and 06-20 and 06-21 resolve that way (06-21 on
    the last bar of the data, 06-25), and the two tail starts 06-24 and 06-25 stay ``censored``
    (they need a third trade date the data does not have). A firm limit can therefore resolve an
    attempt whose H trade dates do not fit in the data -- such a start is still INCOMPLETE, because
    completeness is about H, not about resolution.

    Two of the five passes move too: the 06-05 and 06-10 starts reach their target at the CLOSE of
    their third trade date, and at that same close the time limit is tested BEFORE the pass
    conditions (ADR-0107 section 9's end-of-day order, and the pessimistic direction: a firm's own
    limit ending the phase wins). So ``pass`` goes 5 -> 3 (06-03, 06-06, 06-11, whose target is
    reached on their second trade date) and ``timeout`` 6 -> 8.
    """
    result = evaluate(
        store,
        artifacts,
        rules=[
            DRAWDOWN,
            {
                "kind": "time_limit",
                "rule_id": "limit",
                "max_trading_days": 3,
                "unit": "trading_days",
                "comparison": ">=",
                "action": "timeout",
            },
        ],
        max_trading_days=3,
    )
    summary = result.summary["scenarios"][0]
    assert summary["counts"] == {
        "pass": 3,
        "fail": 3,
        "timeout": 8,
        "horizon": 0,
        "censored": 2,
    }
    assert summary["probability"]["value"] == pytest.approx(3 / 12)
    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    # 06-05 and 06-10 reach the target at the close of their THIRD trade date, where the
    # firm's three-day limit is tested first: they time out instead of passing
    assert frame["outcome"].to_list()[:5] == ["pass", "fail", "timeout", "pass", "fail"]


def test_a_horizon_shorter_than_a_phase_limit_is_refused(store: Path, artifacts: Path) -> None:
    """H = 2 with a three-trading-day limit: the firm's limit could never fire, so it is refused."""
    ruleset_file = write_ruleset(
        artifacts / "ruleset.yaml",
        ruleset(
            [
                DRAWDOWN,
                {
                    "kind": "time_limit",
                    "rule_id": "limit",
                    "max_trading_days": 3,
                    "unit": "trading_days",
                    "comparison": ">=",
                    "action": "timeout",
                },
            ]
        ),
    )
    with pytest.raises(ConfigurationError, match="shorter than phase 'evaluation'"):
        run_prop_evaluation(
            config(),
            ruleset_path=ruleset_file,
            horizon_trading_days=2,
            execution_mode="manual",
            store_root=store,
            artifacts_root=artifacts,
        )
    assert not (artifacts / "summary.json").exists()


# ------------------------------------------------------------------------------- 2. the scenarios


CONFLICT: dict[str, object] = {
    "conflict_id": "loss_limit_amount",
    "rule_id": "loss_limit",
    "field": "amount_usd",
    "selected_value": "2000",
    "alternatives": [{"value": "3000", "source": _source()}],
    "selected_source": _source(),
    "rationale": "one page states $2,000 and another $3,000 for the same account",
    "applicability_checked": True,
}
"""A real conflict between two sources: the sensitivity scenario switches the drawdown to $3,000."""


def test_a_conflict_produces_two_scenario_rows_and_both_are_labelled(
    store: Path, artifacts: Path
) -> None:
    """``scenarios="all"`` simulates the primary and the alternative, and never as one result.

    Under the $3,000 drawdown of the alternative the 06-12 start stops failing: its entry at 4790
    loses 50 points (-$2,504 with the commission) and stays above -$3,000, so it runs flat to the
    horizon. The 06-04 and 06-07 starts still breach, because the always-long position rides the
    whole fall (-70 points = -$3,504 from 4830; -70 points from 4810): ``fail`` goes 3 -> 2 and
    ``horizon`` 4 -> 5. The two results differ, which is exactly why the sensitivity scenario is
    reported beside the primary rather than merged into it.
    """
    result = evaluate(store, artifacts, conflicts=[CONFLICT], scenarios="all")
    summaries = result.summary["scenarios"]
    assert [entry["scenario_id"] for entry in summaries] == ["primary", "loss_limit_amount#0"]
    assert [entry["scenario_label"] for entry in summaries] == [
        "official_primary",
        "alternative_sensitivity",
    ]
    assert [entry["ruleset_scenario_label"] for entry in summaries] == ["official", "sensitivity"]
    assert summaries[0]["counts"]["fail"] == 3
    assert summaries[0]["counts"]["horizon"] == 4
    assert summaries[1]["counts"]["fail"] == 2
    assert summaries[1]["counts"]["horizon"] == 5
    assert summaries[1]["conflict_id"] == "loss_limit_amount"

    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    assert frame.height == 32
    assert sorted(set(frame["scenario_id"].to_list())) == ["loss_limit_amount#0", "primary"]
    assert sorted(set(frame["scenario_label"].to_list())) == [
        "alternative_sensitivity",
        "official_primary",
    ]


def test_scenarios_primary_simulates_one_scenario_only(store: Path, artifacts: Path) -> None:
    """The default is the primary scenario: a conflict does not quietly add a second result."""
    result = evaluate(store, artifacts, conflicts=[CONFLICT])
    assert [entry["scenario_id"] for entry in result.summary["scenarios"]] == ["primary"]


# --------------------------------------------------------------------------------- 3. the labels


def _verified(store: Path, ruleset_file: Path) -> PropRuleset:
    """Sign the ruleset the way the owner does, so ``verified`` becomes true.

    The sidecar is what ``crucible prop confirm`` writes from a TTY; a test writes it directly with
    the same function, because the TTY requirement is the confirm command's, not the format's.
    """
    from crucible.prop.ruleset import write_verification_sidecar

    ruleset_object = load_ruleset(ruleset_file)
    write_verification_sidecar(
        ruleset_file,
        ruleset_object,
        confirmed_by="test owner",
        confirmation_note="a synthetic ruleset confirmed by a test",
    )
    return load_ruleset(ruleset_file)


def test_a_verified_and_fully_modeled_ruleset_earns_the_name_pass_probability(
    store: Path, artifacts: Path
) -> None:
    """Nothing qualifies the number: every rule modeled, verified, costed, calendar covered.

    Benefits are: the single phase with a drawdown and a target are modeled rules, the commission is
    known and all-in, the synthetic calendar covers the window with timed releases only after the
    CPI row of 06-12 (which is timed), and the data (June 2024) is inside the ruleset's effective
    period (from 2024-01-01). So the summary reports ``pass_probability`` with ``definitive: true``
    and no reasons -- the arithmetic is still 5/12, only the name of the number changes.
    """
    # a synthetic attribution can never verify (ADR-0107 section 7), so this one is declared as a
    # source a human read -- the URLs are example.invalid and nothing is fetched
    ruleset_file = write_ruleset(
        artifacts / "ruleset.yaml", ruleset([DRAWDOWN], [TARGET], synthetic=False)
    )
    _verified(store, ruleset_file)
    result = run_prop_evaluation(
        config(),
        ruleset_path=ruleset_file,
        horizon_trading_days=5,
        execution_mode="manual",
        store_root=store,
        artifacts_root=artifacts,
        overwrite=True,
    )
    probability = result.summary["scenarios"][0]["probability"]
    assert probability["field"] == PASS_PROBABILITY
    assert probability["definitive"] is True
    assert probability["reasons"] == []
    assert probability["value"] == pytest.approx(5 / 12)


def test_an_unverified_ruleset_reports_a_conditional_number(store: Path, artifacts: Path) -> None:
    """The same ruleset without its sidecar is `unverified`: the number is conditional, by name."""
    result = evaluate(store, artifacts)
    probability = result.summary["scenarios"][0]["probability"]
    assert probability["field"] == CONDITIONAL_PASS_PROBABILITY
    assert probability["definitive"] is False
    assert probability["reasons"] == ["the ruleset is unverified: only the owner can confirm it"]


BAN_AUTOMATION: dict[str, object] = {
    "kind": "compliance",
    "rule_id": "no_automated_trading",
    "restriction": "Automated or algorithmic trading is prohibited",
    "applies_to_execution": ["automated"],
    "materiality": "critical",
    "comparison": ">=",
    "action": "block",
}
"""A critical compliance rule: an automated strategy is practically ineligible."""


def test_a_mechanical_pass_under_a_compliance_blocker_is_never_a_practically_valid_pass(
    store: Path, artifacts: Path
) -> None:
    """Five mechanical passes, zero practically valid ones, in the same summary.

    ``execution_mode`` decides: the rule bans ``automated`` only, so an automated evaluation reports
    ``blocked_by_compliance`` with ``practically_valid_passes: 0`` and a reason, while a manual one
    is ``eligible`` with the same five passes. The mechanical outcome does not change in either.
    """
    ruleset_file = write_ruleset(
        artifacts / "ruleset.yaml", ruleset([DRAWDOWN, BAN_AUTOMATION], [TARGET])
    )
    automated = run_prop_evaluation(
        config(),
        ruleset_path=ruleset_file,
        horizon_trading_days=5,
        execution_mode="automated",
        store_root=store,
        artifacts_root=artifacts / "automated",
        overwrite=True,
    )
    blocked = automated.summary["scenarios"][0]
    assert blocked["counts"]["pass"] == 5
    assert blocked["practical_eligibility"]["status"] == "blocked_by_compliance"
    assert blocked["practical_eligibility"]["mechanical_passes"] == 5
    assert blocked["practical_eligibility"]["practically_valid_passes"] == 0
    assert "blocked by a critical compliance rule" in (blocked["practical_eligibility"]["reason"])
    assert blocked["probability"]["field"] == CONDITIONAL_PASS_PROBABILITY
    assert any("practically valid pass" in reason for reason in blocked["probability"]["reasons"])

    manual = run_prop_evaluation(
        config(),
        ruleset_path=ruleset_file,
        horizon_trading_days=5,
        execution_mode="manual",
        store_root=store,
        artifacts_root=artifacts / "manual",
        overwrite=True,
    )
    eligible = manual.summary["scenarios"][0]
    assert eligible["counts"]["pass"] == 5
    assert eligible["practical_eligibility"]["status"] == "eligible"
    assert eligible["practical_eligibility"]["practically_valid_passes"] == 5


def test_the_attempt_fees_are_reported_by_kind_and_apart_from_the_trading_pnl(
    store: Path, artifacts: Path
) -> None:
    """A $49 evaluation fee and a $10 monthly fee are the attempt's costs; the commission is not.

    ``fees_usd`` is the ruleset's own fee total (ADR-0107 section 10: activation, monthly and reset
    fees are reported separately in the net economic value), so it is 49 + 10 = 59 USD for every
    attempt of this window (one started calendar month), ``net_cash_usd`` is -59 with no payout, and
    the commission the account paid per fill lives in the simulated equity instead.
    """
    fees = [
        {
            "kind": "fee",
            "rule_id": "subscription",
            "fee_kind": "evaluation",
            "amount_usd": "49",
            "when": "at_start",
            "comparison": ">=",
            "action": "charge",
        },
        {
            "kind": "fee",
            "rule_id": "data_feed",
            "fee_kind": "monthly",
            "amount_usd": "10",
            "when": "per_month",
            "comparison": ">=",
            "action": "charge",
        },
    ]
    result = evaluate(store, artifacts, fees=fees)
    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    assert frame["fees_evaluation_usd"].to_list()[0] == Decimal("49.000000")
    assert frame["fees_monthly_usd"].to_list()[0] == Decimal("10.000000")
    assert frame["fees_activation_usd"].to_list()[0] == Decimal("0.000000")
    assert frame["fees_usd"].to_list()[0] == Decimal("59.000000")
    assert frame["net_cash_usd"].to_list()[0] == Decimal("-59.000000")
    funded = result.summary["scenarios"][0]["funded"]
    assert funded["passing_starts"] == 5
    assert Decimal(funded["fees_usd"]) == Decimal("295")  # five passes of 59 USD
    assert Decimal(funded["mean_net_cash_usd"]) == Decimal("-59")


# ---------------------------------------------------------------------------------- 4. the costs


def test_unknown_commissions_make_the_cash_unavailable_unless_a_named_assumption_lets_it(
    store: Path, artifacts: Path
) -> None:
    """An unknown commission is never zero: no cash number, or a number under a named assumption.

    The ruleset declares ``commissions.status: unknown`` with no table. The attempt still passes
    mechanically (nothing about the rules changed), but the mean net cash is ``unavailable`` with
    the reason; with ``cost_assumption="owner_statement_2026"`` the number exists and is labelled
    ``conditional``, and the same assumption is a reason on the probability.
    """
    unknown = {
        "status": "unknown",
        "components": _COMPONENTS_UNKNOWN,
        "platform": None,
        "source": _source(),
    }
    blind = evaluate(store, artifacts / "blind", commissions=unknown)
    cash = blind.summary["scenarios"][0]["cash"]
    assert cash["status"] == "unavailable"
    assert cash["mean_net_cash_usd"] is None
    assert cash["interval"]["status"] == "unavailable"
    assert any("cost is not known" in reason for reason in cash["reasons"])
    assert blind.summary["scenarios"][0]["counts"]["pass"] == 5
    assert blind.summary["cost_components"][0]["gaps"] == [
        "clearing",
        "commission",
        "exchange",
        "nfa",
        "other",
    ]

    # a cost-assumption FILE that prices every gap of the root the run trades
    assumption = write_cost_assumption(
        artifacts / "assumed" / "assumption.yaml",
        covers=("commission", "exchange", "clearing", "nfa", "other"),
    )
    assumed = run_prop_evaluation(
        config(),
        ruleset_path=write_ruleset(
            artifacts / "assumed" / "ruleset.yaml",
            ruleset([DRAWDOWN], [TARGET], commissions=unknown),
        ),
        horizon_trading_days=5,
        execution_mode="manual",
        cost_assumption=assumption,
        store_root=store,
        artifacts_root=artifacts / "assumed",
        overwrite=True,
    )
    cash = assumed.summary["scenarios"][0]["cash"]
    assert cash["status"] == "conditional"
    assert cash["mean_net_cash_usd"] is not None
    assert assumed.summary["scenarios"][0]["probability"]["field"] == (CONDITIONAL_PASS_PROBABILITY)
    # the cash status of the attempts is what the artifacts record, per start
    frame = pl.read_parquet(assumed.evaluation_dir / "attempts.parquet")
    assert set(frame["cash_estimate_status"].to_list()) == {"conditional"}
    assert set(frame["cost_assumption_sha256"].to_list()) == {
        hashlib.sha256(assumption.read_bytes()).hexdigest()
    }
    assert set(frame["cost_gaps"].to_list()) == {""}


def test_a_commission_that_excludes_exchange_fees_needs_the_table(tmp_path: Path) -> None:
    """A commission that excludes the exchange and regulatory fees is priced from the dataset.

    A store whose table holds only the NFA rows cannot price the exchange fee, so the attempt
    reports ``exchange fees unknown`` and the cash statistic is ``unavailable`` -- never the $0.02
    charge read as if it were the whole fee. The store whose table has the exchange rows prices it
    (0.02 + 1.25 = 1.27 per side) and the cash number is exact.
    """
    excluding = {
        "status": "known",
        "components": {
            "exchange": {
                "status": "excluded",
                "evidence": "official_quote",
                "text": "SYNTHETIC TEST VALUE",
            },
            "clearing": {
                "status": "unknown",
                "evidence": "not_stated",
                "text": "SYNTHETIC TEST VALUE",
            },
            "nfa": {
                "status": "excluded",
                "evidence": "official_quote",
                "text": "SYNTHETIC TEST VALUE",
            },
            "other": {
                "status": "unknown",
                "evidence": "not_stated",
                "text": "SYNTHETIC TEST VALUE",
            },
        },
        "per_side_usd": {"ES": "2.00"},
        "platform": None,
        "source": _source(),
    }
    # the participant type is a run parameter: without it an excluded component is refused
    with pytest.raises(ConfigurationError, match="fee_participant_type"):
        evaluate(
            build_store(tmp_path / "refuse", exchange_fees=True),
            tmp_path / "refused",
            commissions=excluding,
        )

    blind_store = build_store(tmp_path / "nfa_only", exchange_fees=False)
    blind = evaluate(
        blind_store,
        tmp_path / "blind",
        commissions=excluding,
        fee_participant_type="non_member_customer",
    )
    cash = blind.summary["scenarios"][0]["cash"]
    assert cash["status"] == "unavailable"
    assert any("no exchange row for ES" in reason for reason in cash["reasons"])
    frame = pl.read_parquet(blind.evaluation_dir / "attempts.parquet")
    assert set(frame["cash_estimate_status"].to_list()) == {"unavailable"}
    assert set(frame["exchange_status"].to_list()) == {"excluded_unpriced"}
    assert set(frame["nfa_usd"].to_list()) == {Decimal("0.020000")}

    priced_store = build_store(tmp_path / "priced", exchange_fees=True)
    priced = evaluate(
        priced_store,
        tmp_path / "priced_art",
        commissions=excluding,
        fee_participant_type="non_member_customer",
    )
    cash = priced.summary["scenarios"][0]["cash"]
    assert cash["status"] == "unavailable"  # clearing and other stay unknown
    assert priced.summary["exchange_fees"] is not None
    assert len(priced.summary["exchange_fees"]["content_hash"]) == 64
    frame = pl.read_parquet(priced.evaluation_dir / "attempts.parquet")
    assert set(frame["exchange_status"].to_list()) == {"excluded_priced"}
    assert set(frame["exchange_usd"].to_list()) == {Decimal("1.250000")}
    assert set(frame["fee_participant_type"].to_list()) == {"non_member_customer"}


# ----------------------------------------------------------------------------------- 5. the news


NEWS: dict[str, object] = {
    "kind": "news_restriction",
    "rule_id": "cpi_window",
    "event_types": ["CPI"],
    "instruments": ["ES"],
    # the window has to cover the whole trade date to block every entry in it, including the bar
    # that closes the session: pre 5 minutes and post 720 minutes (09:01 -> 21:01 Chicago)
    "pre_minutes": 5,
    "post_minutes": 720,
    "scope": "new_entries",
    "flatten": "none",
    "effect": "block",
    "comparison": ">=",
    "action": "block_entries",
}


def test_a_known_time_news_window_blocks_the_entry_inside_it(store: Path, artifacts: Path) -> None:
    """The June CPI is published at 09:01 Chicago, inside 2024-06-12's two bars.

    Without the news rule the start 06-12 enters at 4790 and the -50 points of 06-13 take it to
    -$2,504, a ``fail``. With it, the five minutes before and after the release block both bars, so
    no position is opened on 06-12; the strategy is long from 06-13 at 4740, a price that never
    moves again, and the same start becomes a ``horizon``. The window is exactly that: the 06-11
    start was already long at 09:02 on 06-11 (the scope is new entries only), keeps its position
    and still passes on the +30 of 06-12.
    """
    without = evaluate(store, artifacts / "without")
    before = pl.read_parquet(without.evaluation_dir / "attempts.parquet")
    row = before.filter(pl.col("start_trade_date") == dt.date(2024, 6, 12))
    assert row["outcome"].to_list() == ["fail"]

    with_news = evaluate(store, artifacts / "with", extra_rules=[NEWS])
    after = pl.read_parquet(with_news.evaluation_dir / "attempts.parquet")
    row = after.filter(pl.col("start_trade_date") == dt.date(2024, 6, 12))
    assert row["outcome"].to_list() == ["horizon"]
    # the 06-11 start is already positioned through the window and still passes
    row = after.filter(pl.col("start_trade_date") == dt.date(2024, 6, 11))
    assert row["outcome"].to_list() == ["pass"]


def test_an_event_with_no_stated_hour_is_reported_as_a_gap_not_as_no_news(
    store: Path, artifacts: Path
) -> None:
    """The FOMC press conference of 2024-06-13 has no stated hour: its whole trade date is a gap.

    The attempt that starts 06-12 covers it, so it reports ``news_coverage_gaps`` with the event id
    and the news rule is ``not_modeled`` for that attempt; the summary lists every unknown-time
    event of the window and the estimate is not complete.
    """
    rules = [dict(NEWS, rule_id="press_conference_window", event_types=["FOMC_PRESS_CONFERENCE"])]
    result = evaluate(store, artifacts, extra_rules=rules)
    news = result.summary["news"]
    assert "FOMC_PRESS_CONFERENCE-20240613" in news["unknown_time_events"]
    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    row = frame.filter(pl.col("start_trade_date") == dt.date(2024, 6, 12)).row(0, named=True)
    assert "FOMC_PRESS_CONFERENCE-20240613" in row["coverage_gaps"]
    assert row["coverage_gap_count"] == 1
    assert result.summary["scenarios"][0]["estimate_status"] != "complete"
    # the same ruleset without the unknown-time row in its window does not report the gap
    early = frame.filter(pl.col("start_trade_date") == dt.date(2024, 6, 3)).row(0, named=True)
    assert early["coverage_gap_count"] == 0


# ---------------------------------------------------------------------------------- 6. the vault


def test_a_window_reaching_the_vault_is_refused_before_any_read(tmp_path: Path) -> None:
    """A window that reaches 2025 is refused by name, before a dataset is opened.

    The store holds only the vault declaration: no bars, no calendar, nothing to read. A refusal
    that named a missing dataset instead would prove the guard ran too late; the message names the
    vault and the trade date it protects.
    """
    from crucible.data.vault import clear_guard_cache, declare_vault

    store = tmp_path / "store"
    store.mkdir()
    home = tmp_path / "home"
    declare_vault(
        store_root=store,
        home=home,
        universe=["ES"],
        start_trade_date=dt.date(2025, 1, 1),
        audit_ref="a throwaway vault declaration for a test",
    )
    clear_guard_cache()
    ruleset_file = write_ruleset(tmp_path / "ruleset.yaml", ruleset([DRAWDOWN], [TARGET]))
    reaching = config(**{"window.start": "2024-12-02", "window.end": "2025-01-31"})
    with pytest.raises(VaultLockedError) as caught:
        run_prop_evaluation(
            reaching,
            ruleset_path=ruleset_file,
            horizon_trading_days=5,
            execution_mode="manual",
            store_root=store,
            artifacts_root=tmp_path / "artifacts",
            home=home,
        )
    message = str(caught.value)
    assert "holdout vault" in message
    assert "2025-01-01" in message


# ------------------------------------------------------------------- 7. determinism and identity


def test_two_evaluations_are_byte_identical_and_the_artifact_is_sealed(
    store: Path, artifacts: Path
) -> None:
    """The same inputs produce the same bytes, the same id and a seal that verifies.

    Nothing reads the clock inside the simulation (``created_at`` is outside the digest), and every
    frame is written in a stable order, so the second run reproduces the first byte for byte and the
    ``seal_artifact`` digest still matches ``attempts.parquet`` and ``summary.json``.
    """
    first = evaluate(store, artifacts / "first")
    second = evaluate(store, artifacts / "second")
    assert first.evaluation_id == second.evaluation_id
    assert first.evaluation_id.startswith("PRP-")
    assert len(first.evaluation_id) == len("PRP-") + 16
    assert first.artifact_id == second.artifact_id
    assert first.evaluation_dir.name == first.evaluation_id
    for name in RESULT_FILES:
        assert (first.evaluation_dir / name).read_bytes() == (
            second.evaluation_dir / name
        ).read_bytes()
    assert verify_artifact(first.evaluation_dir) == first.artifact_id
    manifest = json.loads((first.evaluation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trial_recorded"] is False
    assert manifest["not_a_submission"].startswith("a prop evaluation evaluates an existing")
    assert (
        manifest["ruleset"]["ruleset_sha256"]
        == load_ruleset(first.evaluation_dir / "ruleset.yaml").ruleset_sha256
    )
    # the ruleset file is the bytes that were evaluated, not a re-rendering of them
    assert (first.evaluation_dir / "ruleset.yaml").read_bytes() == (
        artifacts / "first" / "ruleset.yaml"
    ).read_bytes()


def test_an_evaluation_records_no_trial_and_changes_no_count(store: Path, artifacts: Path) -> None:
    """A prop evaluation is not a submission: the family's trial counts do not move (ADR-0107 s6).

    ``run_futures`` records one trial for the same config; the two evaluations around it leave
    ``submission_count`` and ``total_trials`` exactly where the run put them.
    """
    from crucible.experiments.futures_run import run_futures

    registry_path = artifacts / "trial_registry.duckdb"
    run_futures(config(), store_root=store, artifacts_root=artifacts)
    registry = DuckDBTrialRegistry(registry_path)
    before = (registry.submission_count(FAMILY), registry.total_trials(FAMILY))
    assert before == (1, 1)
    evaluate(store, artifacts / "one")
    evaluate(store, artifacts / "two")
    registry = DuckDBTrialRegistry(registry_path)
    assert (registry.submission_count(FAMILY), registry.total_trials(FAMILY)) == before


def test_the_artifact_carries_the_candidate_link_the_horizon_and_the_datasets(
    store: Path, artifacts: Path
) -> None:
    """The manifest ties the evaluation to the candidate, the family, H and the exact datasets."""
    from crucible.experiments.futures_config import candidate_id

    result = evaluate(store, artifacts)
    manifest = json.loads((result.evaluation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "prop_evaluation"
    assert manifest["candidate_id"] == candidate_id(config())
    assert manifest["trial_family"] == FAMILY
    assert manifest["horizon"]["trading_days"] == 5
    assert manifest["execution_mode"] == "manual"
    assert manifest["payout_policy"] == "max_eligible"
    assert manifest["ruleset"]["ruleset_id"] == "synthetic-prop-evaluation"
    assert manifest["ruleset"]["unverified"] is True
    assert set(manifest["datasets"]) == {"execution", "signal", "rolls", "raw"}
    assert manifest["attempts"] == 16
    assert manifest["files"] == sorted(RESULT_FILES)
    assert result.summary["run_id"].startswith("FUT-")
    assert result.summary["not_a_submission"] is True


# ------------------------------------------------------------------------------------ 8. the CLI


def test_the_cli_writes_the_artifact_and_prints_the_summary(
    store: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``crucible futures prop`` runs the evaluation, prints the labels and honours ``--json``."""
    from crucible.cli.main import main

    ruleset_file = write_ruleset(artifacts / "ruleset.yaml", ruleset([DRAWDOWN], [TARGET]))
    config_file = artifacts / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(mapping(), sort_keys=True), encoding="utf-8", newline="\n"
    )
    code = main(
        [
            "futures",
            "prop",
            "--config",
            str(config_file),
            "--ruleset",
            str(ruleset_file),
            "--horizon",
            "5",
            "--execution-mode",
            "manual",
            "--store",
            str(store),
            "--artifacts",
            str(artifacts / "cli"),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "conditional_pass_probability: 0.4166666666666667" in printed
    assert "pass 5, fail 3, timeout 0, horizon 4, censored 4" in printed
    assert "Verdict: not assessed" in printed

    code = main(
        [
            "futures",
            "prop",
            "--config",
            str(config_file),
            "--ruleset",
            str(ruleset_file),
            "--horizon",
            "5",
            "--execution-mode",
            "manual",
            "--store",
            str(store),
            "--artifacts",
            str(artifacts / "cli"),
            "--overwrite",
            "--json",
        ]
    )
    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["kind"] == "prop_evaluation"
    assert document["scenarios"][0]["counts"]["pass"] == 5


def test_the_cli_refuses_a_payout_policy_it_does_not_implement(
    store: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An option outside the implemented set is refused by name, and nothing is run."""
    from crucible.cli.main import main

    ruleset_file = write_ruleset(artifacts / "ruleset.yaml", ruleset([DRAWDOWN], [TARGET]))
    config_file = artifacts / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(mapping(), sort_keys=True), encoding="utf-8", newline="\n"
    )
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "futures",
                "prop",
                "--config",
                str(config_file),
                "--ruleset",
                str(ruleset_file),
                "--horizon",
                "5",
                "--execution-mode",
                "manual",
                "--payout-policy",
                "sometimes",
                "--store",
                str(store),
                "--artifacts",
                str(artifacts / "cli"),
            ]
        )
    assert caught.value.code == 2  # argparse's own refusal, before any work
    assert "invalid choice" in capsys.readouterr().err


def test_the_evaluation_summary_has_a_json_schema() -> None:
    """``crucible schema --kind prop-evaluation`` is generated from the summary document model."""
    from crucible.experiments.futures_prop import prop_evaluation_json_schema

    schema = prop_evaluation_json_schema()
    assert schema["title"] == "PropEvaluationSummary"
    assert "probabil" in json.dumps(schema)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "scenarios" in properties


def test_a_datastore_without_the_calendar_is_refused_by_name(tmp_path: Path) -> None:
    """The economic calendar is an input: a store without it is refused, not treated as no news."""
    from crucible.core.errors import ExperimentError

    store = build_store(tmp_path / "store")
    (store / "econ_events_v2" / "manifest.json").unlink()
    ruleset_file = write_ruleset(tmp_path / "ruleset.yaml", ruleset([DRAWDOWN], [TARGET]))
    with pytest.raises(ExperimentError, match="econ_events_v2"):
        run_prop_evaluation(
            config(),
            ruleset_path=ruleset_file,
            horizon_trading_days=5,
            execution_mode="manual",
            store_root=store,
            artifacts_root=tmp_path / "artifacts",
        )


def test_a_ruleset_for_another_root_is_refused(store: Path, artifacts: Path) -> None:
    """The attempts replay ES bars: a ruleset whose instruments exclude ES cannot be applied."""
    other = ruleset([DRAWDOWN], [TARGET]).model_copy(
        update={"instruments": (Instrument(root="NQ", contract_weight=Decimal(1)),)}
    )
    ruleset_file = write_ruleset(artifacts / "ruleset.yaml", other)
    with pytest.raises(ConfigurationError, match="does not trade ES"):
        run_prop_evaluation(
            config(),
            ruleset_path=ruleset_file,
            horizon_trading_days=5,
            execution_mode="manual",
            store_root=store,
            artifacts_root=artifacts,
        )


def test_the_store_is_not_written_to(store: Path, artifacts: Path) -> None:
    """An evaluation reads the store and writes only under its artifacts root."""
    before = {
        path.relative_to(store): path.read_bytes()
        for path in sorted(store.rglob("*"))
        if path.is_file()
    }
    result = evaluate(store, artifacts)
    after = {
        path.relative_to(store): path.read_bytes()
        for path in sorted(store.rglob("*"))
        if path.is_file()
    }
    assert before == after
    assert result.evaluation_dir.parent == artifacts
    assert ParquetDataStore(store).manifest(DatasetId("econ_events_v2")).row_count > 0
