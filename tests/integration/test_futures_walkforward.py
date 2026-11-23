"""A whole futures walk-forward, end to end (Fathom C5b, ADR-0101, acceptance).

The store is synthetic but conforming: one ES root, ONE contract (no roll), six Globex trade dates
(2024-03-05 .. 2024-03-12) of five minute bars each, and a price staircase that rises a point a bar
with a two-point dip on every fifth bar. That makes the candidates' behaviour hand-checkable:

- ``mom`` (long when the close rose) realizes a gain: in the training window it nets +46.25 USD and
  holds a position in 80% of the bars;
- ``mom-n1`` decides exactly the same thing with the delay written as a parameter (its own run),
  so the two tie on training net P&L;
- ``anti`` (the inverse side) nets -253.75 USD;
- ``quiet`` (a z-score threshold nothing reaches) never trades: net 0, in market 0% of the bars.

A fold's training window is two trade dates and its test window the next two, so the walk-forward
has two folds and no remainder. The ES tick is 0.25 points at $50 a point ($12.50 a tick) and the
commission is $2.00 a side, so one side of a market fill costs $2.00 + (0.5 + 1) x $12.50 = $20.75 -
which is also the terminal exit of one open contract, written out in the tests that read it.

What is under test: the selection happens inside the training window only, a constraint can exclude
the training leader, a tie goes to the earliest submission, a fold with no eligible candidate is
flat (not missing), the out-of-sample series is the CONCATENATED test windows with a costed
terminal exit at every fold boundary, the training numbers stay in the audit, no statistic appears,
and re-running reproduces every id.

``-m bench`` runs the shipped example against the real datasets of ``docs/data/glbx-futures-1m.md``
(skipped when absent) and checks the same identities on it.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_walkforward import (
    OOS_DAILY_SCHEMA,
    WALKFORWARD_SCHEMA_VERSION,
    load_futures_walkforward,
    run_futures_walkforward,
    walkforward_id,
)
from crucible.validation.trial_registry import DuckDBTrialRegistry

DAYS = (
    "2024-03-05",
    "2024-03-06",
    "2024-03-07",
    "2024-03-08",
    "2024-03-11",
    "2024-03-12",
)
WALLS = ("09:01", "09:02", "09:03", "09:04", "09:05")
CONTRACT = "ESM2024"
FAMILY = "es-walkforward"
BARS_PER_DAY = len(WALLS)
FILL_COST = Decimal("20.75")
"""One side of a market fill for one ES contract at $2.00 commission and the default 1-tick spread
and 1-tick slippage: $2.00 + (0.5 + 1) x $12.50. Also the terminal exit of one open contract."""

MOM = "if(close > delay(close, 1), 1, -1)"
MOM_N1 = "if(close > delay(close, $n:int[1,5]=1), 1, -1)"
ANTI = "if(close > delay(close, 1), -1, 1)"
QUIET = "if(ts_zscore(close, 2) > 10, 1, if(ts_zscore(close, 2) < -10, -1, 0))"

CANDIDATES = [
    {"name": "mom", "expression": MOM},
    {"name": "mom-n1", "expression": MOM_N1},
    {"name": "anti", "expression": ANTI},
    {"name": "quiet", "expression": QUIET},
]
DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "wf_id",
    "family",
    "base_config_hash",
    "fidelity",
    "scheme",
    "train_trade_dates",
    "test_trade_dates",
    "warmup_trade_dates",
    "constraints",
    "folds",
    "oos",
    "window_stability",
    "in_sample_audit",
    "unused_trade_dates",
    "terminal_exit",
    "trials",
    "verdict",
}
FOLD_KEYS = {"fold", "status", "train", "test", "selection", "selection_reason", "oos"}
EXAMPLE = Path("examples/futures/es_walkforward_screen.yaml")


# ---------------------------------------------------------------------------------------------
# the synthetic store


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def closes() -> list[float]:
    """A rising staircase with a two-point dip on every fifth bar: the momentum candidate's fuel."""
    return [
        4400.0 + float(index) - (2.0 if index % 5 == 0 and index > 0 else 0.0)
        for index in range(len(DAYS) * BARS_PER_DAY)
    ]


def _continuous(values: list[float]) -> pl.DataFrame:
    times = [utc(f"{day} {wall}") for day in DAYS for wall in WALLS]
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(values),
            "event_time": times,
            "available_at": [value + 1 for value in times],
            "open": [value - 0.25 for value in values],
            "high": [value + 0.5 for value in values],
            "low": [value - 0.5 for value in values],
            "close": values,
            "volume": [100.0] * len(values),
            "contract": [CONTRACT] * len(values),
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def build_walkforward_store(
    root: Path, *, poison_from: str | None = None, poison_factor: float = 1e6
) -> Path:
    """The four synthetic datasets under ``root``, without a roll (one contract throughout).

    ``poison_from``: a trade date at or after which every price is multiplied by ``poison_factor``,
    the absurd future the lookahead harness reads. The frame stays conforming (same schema, same
    rows), so a run on it answers "did anything after this date change the answer?"
    """
    values = closes()
    execution = _continuous(values)
    if poison_from is not None:
        cutoff = utc(f"{poison_from} 00:00")
        execution = execution.with_columns(
            pl.when(pl.col("event_time") >= cutoff)
            .then(pl.col(name) * poison_factor)
            .otherwise(pl.col(name))
            .alias(name)
            for name in ("open", "high", "low", "close")
        )
    # ratio_adjusted on a single contract is the unadjusted series (the ratio is 1)
    raw = execution.select(
        "symbol", "event_time", "available_at", "open", "high", "low", "close", "volume"
    )
    rolls = pl.DataFrame({name: pl.Series([], dtype=dtype) for name, dtype in ROLL_SCHEMA.items()})
    root.mkdir(parents=True, exist_ok=True)
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
        rolls,
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        raw,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=30;synthetic",
    )
    return root


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_walkforward_store(tmp_path_factory.mktemp("walkforward-store") / "store")


# ---------------------------------------------------------------------------------------------
# the walk-forward files


def base_config(directory: Path, **overrides: object) -> Path:
    """A futures-run base whose strategy is replaced per candidate."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-walkforward", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAYS[0], "end": DAYS[-1]},
        "strategy": {"expression": MOM},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    raw.update(overrides)
    path = directory / "base.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def walkforward_file(
    directory: Path,
    *,
    candidates: list[dict[str, object]] | None = None,
    constraints: dict[str, object] | None = None,
    **overrides: object,
) -> Path:
    """A walk-forward file on ``base.yaml``: two training and two test trade dates per fold."""
    base_config(directory)
    payload: dict[str, object] = {
        "kind": "futures_walkforward",
        "base": "base.yaml",
        "candidates": CANDIDATES if candidates is None else candidates,
        "train_trade_dates": 2,
        "test_trade_dates": 2,
        "scheme": "rolling",
        "constraints": constraints or {"max_intraday_drawdown_usd": "5000"},
    }
    payload.update(overrides)
    path = directory / "walkforward.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _document(path: Path, store: Path, artifacts: Path) -> dict[str, object]:
    return run_futures_walkforward(path, store_root=store, artifacts_root=artifacts).document


@pytest.fixture(scope="module")
def default_run(
    tmp_path_factory: pytest.TempPathFactory, store: Path
) -> tuple[Path, dict[str, object], Path]:
    """The reference walk-forward: four candidates, two folds, no extra constraint.

    Module-scoped because it is ten sealed runs (four candidates x two training folds, the two test
    runs and the registry records) and costs ~4 s: everything below only *reads* the document and
    the artifacts directory. The one test that re-runs the job takes a private copy first
    (``test_re_running_is_idempotent``), so no test sees another test's writes.
    """
    directory = tmp_path_factory.mktemp("walkforward-run")
    path = walkforward_file(directory)
    artifacts = directory / "artifacts"
    return path, _document(path, store, artifacts), artifacts


# ---------------------------------------------------------------------------------------------
# the document


def test_the_walk_forward_writes_its_two_files_and_seals_every_run(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, artifacts = default_run
    identifier = str(document["wf_id"])
    assert identifier.startswith("WFA-")
    assert len(identifier) == 4 + 16
    directory = artifacts / identifier
    assert sorted(path.name for path in directory.iterdir()) == [
        "oos_daily.parquet",
        "walkforward.json",
    ]
    assert set(document) == DOCUMENT_KEYS
    assert document["schema_version"] == WALKFORWARD_SCHEMA_VERSION == 1
    assert document["kind"] == "futures_walkforward"
    assert document["family"] == FAMILY
    assert len(str(document["base_config_hash"])) == 64
    assert document["scheme"] == "rolling"
    assert (document["train_trade_dates"], document["test_trade_dates"]) == (2, 2)
    assert document["warmup_trade_dates"] == 0
    assert document["constraints"]["max_intraday_drawdown_usd"] == "5000"
    # the file on disk is the document, written deterministically
    text = (directory / "walkforward.json").read_text(encoding="utf-8")
    on_disk = json.loads(text)
    assert on_disk == json.loads(json.dumps(document))
    assert text == json.dumps(on_disk, sort_keys=True, indent=2) + "\n"
    # every test run is sealed and verifies
    folds = document["folds"]
    assert isinstance(folds, list)
    for fold in folds:
        assert set(fold) == FOLD_KEYS
        run_id = fold["oos"]["run_id"]
        assert verify_artifact(artifacts / str(run_id)).startswith("ART-")
    oos = pl.read_parquet(directory / "oos_daily.parquet")
    assert dict(oos.schema) == OOS_DAILY_SCHEMA


def test_the_fold_geometry_is_the_base_window_s_trade_dates(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, _ = default_run
    folds = document["folds"]
    assert [(fold["fold"], fold["train"]["start"], fold["train"]["end"]) for fold in folds] == [
        (0, DAYS[0], DAYS[1]),
        (1, DAYS[2], DAYS[3]),
    ]
    assert [(fold["test"]["start"], fold["test"]["end"]) for fold in folds] == [
        (DAYS[2], DAYS[3]),
        (DAYS[4], DAYS[5]),
    ]
    assert [fold["train"]["trade_dates"] for fold in folds] == [2, 2]
    assert [fold["test"]["trade_dates"] for fold in folds] == [2, 2]
    # six trade dates, two folds of 2+2: nothing is left over
    assert document["unused_trade_dates"] == []
    # fold 1 trains on the dates immediately before its test window, one of which fold 0 tested on
    assert folds[1]["train"]["start"] == DAYS[2]


def test_the_selection_is_the_largest_training_net_pnl_among_the_eligible(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, _ = default_run
    audit = document["in_sample_audit"]
    assert isinstance(audit, dict)
    folds = document["folds"]
    for fold, audited in zip(folds, audit["folds"], strict=True):
        eligible = [entry for entry in audited["candidates"] if entry["eligible"]]
        best = max(entry["metrics"]["net_pnl_usd"]["value"] for entry in eligible)
        selected = fold["selection"]
        assert selected is not None
        winner = next(
            entry for entry in audited["candidates"] if entry["name"] == selected["candidate"]
        )
        assert winner["metrics"]["net_pnl_usd"]["value"] == best
        assert fold["status"] == "selected"
        assert "largest training net P&L" in fold["selection_reason"]
        assert "1 candidate(s) failed at least one constraint" not in fold["selection_reason"]
    # the staircase: mom and its parameterized twin lead, anti loses, quiet is flat
    first = audit["folds"][0]["candidates"]
    by_name = {entry["name"]: entry for entry in first}
    assert by_name["mom"]["metrics"]["net_pnl_usd"]["value"] == 46.25
    assert by_name["mom-n1"]["metrics"]["net_pnl_usd"]["value"] == 46.25
    assert by_name["anti"]["metrics"]["net_pnl_usd"]["value"] == -253.75
    assert by_name["quiet"]["metrics"]["net_pnl_usd"]["value"] == 0.0
    assert by_name["mom"]["time_in_market"]["value"] == 0.8
    assert by_name["quiet"]["time_in_market"]["value"] == 0.0
    # submission order is preserved in the audit, never sorted by a metric
    assert [entry["position"] for entry in first] == [0, 1, 2, 3]
    assert [entry["name"] for entry in first] == ["mom", "mom-n1", "anti", "quiet"]


def test_a_constraint_excludes_the_training_leader(tmp_path: Path, store: Path) -> None:
    # mom leads on training net P&L (+46.25) but its intraday equity dips to 49,966.75; the floor
    # happens to exclude it (net_pnl is a flow), so the flat candidate is selected instead
    path = walkforward_file(
        tmp_path,
        candidates=[{"name": "mom", "expression": MOM}, {"name": "quiet", "expression": QUIET}],
        constraints={"max_intraday_drawdown_usd": "5000", "min_equity_usd": "50000"},
    )
    document = _document(path, store, tmp_path / "artifacts")
    audited = document["in_sample_audit"]["folds"][0]["candidates"]
    by_name = {entry["name"]: entry for entry in audited}
    assert by_name["mom"]["metrics"]["net_pnl_usd"]["value"] == 46.25
    assert by_name["mom"]["metrics"]["min_equity_usd"]["value"] == 49966.75
    assert by_name["mom"]["eligible"] is False
    assert by_name["mom"]["violations"] == ["min_equity_usd: 49966.75 < 50000.0"]
    assert by_name["quiet"]["eligible"] is True
    fold = document["folds"][0]
    assert fold["selection"] == {"candidate": "quiet", "position": 1}
    assert "failed at least one constraint" in fold["selection_reason"]
    # the excluded leader is not selected, even though its training net P&L is the larger number
    assert fold["oos"]["candidate"] == "quiet"


def test_a_tie_goes_to_the_earliest_submission(tmp_path: Path, store: Path) -> None:
    # the two candidates decide the same thing (one writes the delay window as a parameter), so
    # their training net P&L ties exactly and the earlier position wins
    path = walkforward_file(
        tmp_path,
        candidates=[
            {"name": "mom-n1", "expression": MOM_N1},
            {"name": "mom", "expression": MOM},
        ],
    )
    document = _document(path, store, tmp_path / "artifacts")
    fold = document["folds"][0]
    assert fold["selection"] == {"candidate": "mom-n1", "position": 0}
    assert "tie" in fold["selection_reason"]
    nets = [
        entry["metrics"]["net_pnl_usd"]["value"]
        for entry in document["in_sample_audit"]["folds"][0]["candidates"]
    ]
    assert nets[0] == nets[1]  # the tie the rule broke


def test_a_fold_with_no_eligible_candidate_is_flat(tmp_path: Path, store: Path) -> None:
    # both candidates trade, so a cap of 0 fills excludes every one of them
    path = walkforward_file(
        tmp_path,
        candidates=[{"name": "mom", "expression": MOM}, {"name": "anti", "expression": ANTI}],
        constraints={"max_intraday_drawdown_usd": "5000", "max_fills": 0},
    )
    artifacts = tmp_path / "artifacts"
    document = _document(path, store, artifacts)
    for fold in document["folds"]:
        assert fold["status"] == "no_eligible_candidate"
        assert fold["selection"] is None
        assert fold["selection_reason"].startswith("no eligible candidate")
        oos = fold["oos"]
        assert oos["candidate"] is None
        assert oos["run_id"] is None
        assert oos["net_pnl_usd"]["value"] == 0.0
        assert oos["costs_usd"]["value"] == 0.0
        assert oos["fills"]["value"] == 0.0
        assert oos["terminal_exit_cost_usd"]["value"] == 0.0
    frame = pl.read_parquet(artifacts / str(document["wf_id"]) / "oos_daily.parquet")
    # one row per test trade date, all zero, and the chain never moves away from the capital
    assert frame.height == 4
    assert frame["net_pnl_usd"].to_list() == [Decimal(0)] * 4
    assert frame["closing_equity_usd"].to_list() == [Decimal(50000)] * 4
    assert frame["candidate"].to_list() == [None] * 4
    assert frame["run_id"].to_list() == [None] * 4
    assert document["oos"]["net_pnl_usd"]["value"] == 0.0
    assert document["oos"]["folds_with_selection"]["value"] == 0.0
    assert document["window_stability"]["folds_flat"] == 2
    # the audit still holds the training runs that made the decision
    trained = document["in_sample_audit"]["folds"][0]["candidates"]
    assert [entry["eligible"] for entry in trained] == [False, False]
    assert trained[0]["violations"] == ["max_fills: 3.0 > 0.0"]


def test_the_oos_rows_are_only_the_test_windows(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, artifacts = default_run
    frame = pl.read_parquet(artifacts / str(document["wf_id"]) / "oos_daily.parquet")
    folds = document["folds"]
    assert frame["trade_date"].to_list() == [
        dt.date.fromisoformat(str(day))
        for fold in folds
        for day in (fold["test"]["start"], fold["test"]["end"])
    ]
    # each fold's rows are exactly its own test window, in fold order
    for fold in folds:
        rows = frame.filter(pl.col("fold") == fold["fold"])
        assert rows["trade_date"].to_list() == [
            dt.date.fromisoformat(str(fold["test"]["start"])),
            dt.date.fromisoformat(str(fold["test"]["end"])),
        ]
        assert rows["candidate"].unique().to_list() == [fold["selection"]["candidate"]]
    # no training-only trade date appears: the first fold's training dates are never OOS
    training_only = {str(folds[0]["train"]["start"]), str(folds[0]["train"]["end"])}
    assert training_only == {DAYS[0], DAYS[1]}
    oos_dates = {day.isoformat() for day in frame["trade_date"].to_list()}
    assert not (training_only & oos_dates)


def test_the_concatenated_chain_adds_up(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, artifacts = default_run
    frame = pl.read_parquet(artifacts / str(document["wf_id"]) / "oos_daily.parquet")
    capital = Decimal("50000")
    # the chain starts at the base capital, and every row is the previous close plus its own P&L
    previous = capital
    for net, costs, closing in zip(
        frame["net_pnl_usd"].to_list(),
        frame["costs_usd"].to_list(),
        frame["closing_equity_usd"].to_list(),
        strict=True,
    ):
        assert closing == previous + net
        assert costs >= 0
        previous = closing
    # a fold's OOS net P&L is its rows' net, and a fold ends at capital + every fold's net so far
    running = capital
    for fold in document["folds"]:
        rows = frame.filter(pl.col("fold") == fold["fold"])
        assert sum(rows["net_pnl_usd"].to_list(), Decimal(0)) == Decimal(
            str(fold["oos"]["net_pnl_usd"]["value"])
        )
        running += Decimal(str(fold["oos"]["net_pnl_usd"]["value"]))
        assert rows["closing_equity_usd"].to_list()[-1] == running
    # the OOS summary is the sums of those rows, and nothing else
    summary = document["oos"]
    assert summary["net_pnl_usd"]["value"] == float(sum(frame["net_pnl_usd"].to_list(), Decimal(0)))
    assert summary["total_costs_usd"]["value"] == float(
        sum(frame["costs_usd"].to_list(), Decimal(0))
    )
    assert summary["fills"]["value"] == int(frame["fills"].sum())
    assert summary["trade_dates"]["value"] == frame.height
    assert summary["folds_with_selection"]["value"] == 2
    # the staircase only ever rises, so the concatenated drawdown is zero
    assert summary["max_drawdown_usd"]["value"] == 0.0


def test_the_terminal_exit_is_one_side_of_the_full_cost(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, _ = default_run
    for fold in document["folds"]:
        oos = fold["oos"]
        # one open contract at the fold's last bar, charged one side (hand-computed above)
        assert oos["open_contracts_at_last_bar"] == 1
        assert oos["terminal_exit_cost_usd"]["value"] == float(FILL_COST) == 20.75
    # the exit is booked on the fold's last trade date, inside that row's costs
    assert document["folds"][0]["oos"]["costs_usd"]["value"] == 124.5  # 20.75 + (83.00 + 20.75)
    assert "terminal exit" in str(document["terminal_exit"])


def test_no_training_result_is_presented_as_out_of_sample(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, artifacts = default_run
    # the OOS block carries the five descriptive series metrics plus the C6a statistics block,
    # which is computed on THIS series alone (ADR-0103 decision 7)
    oos = document["oos"]
    assert set(oos) == {
        "net_pnl_usd",
        "total_costs_usd",
        "fills",
        "trade_dates",
        "max_drawdown_usd",
        "folds_with_selection",
        "statistics",
    }
    for name in (
        "net_pnl_usd",
        "total_costs_usd",
        "fills",
        "trade_dates",
        "max_drawdown_usd",
        "folds_with_selection",
    ):
        entry = oos[name]
        assert set(entry) == {
            "value",
            "ci_low",
            "ci_high",
            "assessment",
            "unit",
        }
        assert entry["assessment"] == "descriptive"
        assert entry["ci_low"] is None
        assert entry["ci_high"] is None
    statistics = oos["statistics"]
    assert set(statistics["metrics"]) == {
        "sharpe_per_period",
        "sharpe_annualized",
        "mean_daily_return",
        "psr",
        "dsr",
        "ic_mean",
    }
    assert statistics["trials"]["total_trials"] >= 1
    # the OOS series is four trade dates of a walk-forward chain, so the per-period Sharpe is
    # computed from it and NOT from any training run
    daily = pl.read_parquet(artifacts / str(document["wf_id"]) / "oos_daily.parquet")
    assert daily.height == 4
    assert statistics["observations"] == daily.height
    # every training run is in the audit, marked in_sample, and nowhere else
    audit = document["in_sample_audit"]
    assert audit["note"].startswith("training results")
    for fold in audit["folds"]:
        for entry in fold["candidates"]:
            assert entry["in_sample"] is True
            assert entry["run_id"] not in json.dumps(
                {k: v for k, v in document.items() if k != "in_sample_audit"}
            )
            for name, metric in entry["metrics"].items():
                assert metric["assessment"] in ("descriptive", "inferential")
                if metric["assessment"] == "descriptive":
                    assert metric["ci_low"] is None
                    assert metric["ci_high"] is None
                if name not in entry["statistics"]:
                    # everything outside the C6a statistics is a descriptive total or count, plus
                    # the C6b supplementary deflation (ADR-0104), which is inferential and is not
                    # one of the C6a statistics
                    expected = "inferential" if name == "dsr_effective_trials" else "descriptive"
                    assert metric["assessment"] == expected
            # the training run's own statistics are audit-only, marked in_sample like the rest
            assert set(entry["statistics"]) == {
                "sharpe_per_period",
                "sharpe_annualized",
                "mean_daily_return",
                "psr",
                "dsr",
                "ic_mean",
            }
    # the fold's OOS block names only test-run data
    for fold in document["folds"]:
        assert set(fold["oos"]) == {
            "candidate",
            "run_id",
            "artifact_id",
            "net_pnl_usd",
            "costs_usd",
            "fills",
            "terminal_exit_cost_usd",
            "open_contracts_at_last_bar",
            "time_in_market",
        }
    # the statistics live in exactly two places: oos.statistics (the OOS series) and the training
    # audit. Nothing else in the document states a statistic.
    outside = {
        key: value for key, value in document.items() if key not in ("verdict", "in_sample_audit")
    }
    assert "sharpe_per_period" in outside["oos"]["statistics"]["metrics"]
    for key in ("window_stability", "folds", "unused_trade_dates"):
        assert "sharpe" not in json.dumps(outside[key]).lower()


def test_the_verdict_is_not_assessed(default_run: tuple[Path, dict[str, object], Path]) -> None:
    _, document, _ = default_run
    verdict = document["verdict"]
    assert verdict["verdict_level"] is None
    assert verdict["verdict_reason"]["code"] == "robustness_not_assessed"
    assert verdict["verdict_reason"]["assessed_by"] == ["C7"]
    assert verdict["vocabulary"] == ["some_evidence", "not_conclusive", "no_edge_detected"]


def test_the_window_stability_lists_the_folds_and_counts_their_signs(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, _ = default_run
    stability = document["window_stability"]
    nets = [fold["oos"]["net_pnl_usd"]["value"] for fold in document["folds"]]
    assert [entry["value"] for entry in stability["fold_oos_net_pnl_usd"]] == nets
    assert stability["folds_positive"] + stability["folds_negative"] + stability["folds_flat"] == 2
    # the staircase makes both folds positive; no statistic is reported
    assert stability["folds_positive"] == 2
    assert stability["folds_negative"] == 0
    assert stability["folds_flat"] == 0


def test_the_trials_and_the_submissions_are_recorded_once(
    default_run: tuple[Path, dict[str, object], Path],
) -> None:
    _, document, artifacts = default_run
    identifier = str(document["wf_id"])
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    submissions = registry.submissions(batch_id=identifier)
    # one submission per (fold, candidate), in fold order, position = fold * K + candidate
    assert [record.position for record in submissions] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert [record.candidate_name for record in submissions] == [
        "mom",
        "mom-n1",
        "anti",
        "quiet",
    ] * 2
    assert {record.status for record in submissions} == {"computed"}
    # every test run registered its trial too: 8 training runs and 2 test runs of one family
    assert registry.trial_count(FAMILY) == 10


def test_re_running_is_idempotent(
    default_run: tuple[Path, dict[str, object], Path], store: Path, tmp_path: Path
) -> None:
    path, document, shared = default_run
    # a private copy of the artifacts root: this test re-runs the job, and the module-scoped
    # reference run above must stay exactly as the other tests read it
    artifacts = tmp_path / "artifacts"
    shutil.copytree(shared, artifacts)
    first_oos = (artifacts / str(document["wf_id"]) / "oos_daily.parquet").read_bytes()
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    submissions_before = registry.submissions(batch_id=str(document["wf_id"]))
    trials_before = registry.trial_count(FAMILY)

    second = run_futures_walkforward(path, store_root=store, artifacts_root=artifacts)
    assert second.wf_id == document["wf_id"]
    assert second.document["folds"] == document["folds"]
    assert second.document["oos"] == document["oos"]
    assert second.document["window_stability"] == document["window_stability"]
    assert (artifacts / second.wf_id / "oos_daily.parquet").read_bytes() == first_oos
    # every run was reused
    statuses = {
        entry["status"]
        for fold in second.document["in_sample_audit"]["folds"]
        for entry in fold["candidates"]
    }
    assert statuses == {"cached"}
    # nothing was submitted or counted twice
    assert registry.submissions(batch_id=second.wf_id) == submissions_before
    # 8 training submissions + the 2 test runs (standalone runs, ADR-0103 decision 4)
    assert registry.submission_count(FAMILY) == 8 + 2 == 10
    assert registry.trial_count(FAMILY) == trials_before == 10


# ---------------------------------------------------------------------------------------------
# the CLI and the schema


def test_the_cli_json_equals_the_document(
    tmp_path: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = walkforward_file(tmp_path)
    artifacts = tmp_path / "artifacts"
    argv = ["futures", "walkforward", "--config", str(path), "--store", str(store)]
    argv += ["--artifacts", str(artifacts), "--json"]
    assert main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    on_disk = json.loads(
        (artifacts / printed["wf_id"] / "walkforward.json").read_text(encoding="utf-8")
    )
    assert printed == on_disk
    assert printed["kind"] == "futures_walkforward"


def test_the_cli_text_rendering_lists_the_folds(
    tmp_path: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = walkforward_file(tmp_path)
    argv = ["futures", "walkforward", "--config", str(path), "--store", str(store)]
    argv += ["--artifacts", str(tmp_path / "artifacts")]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "walk-forward: WFA-" in out
    assert "folds:        2" in out
    assert "selected" in out
    assert "OOS:          net" in out
    assert "Verdict: not assessed" in out
    assert out.index(DAYS[2]) < out.index(DAYS[4])


def test_the_schema_kind_prints_its_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--kind", "futures-walkforward"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "FuturesWalkForwardFile"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "kind",
        "base",
        "candidates",
        "train_trade_dates",
        "test_trade_dates",
        "scheme",
        "warmup_trade_dates",
        "constraints",
        "pbo",
    }
    constraints = schema["$defs"]["FuturesWalkForwardConstraints"]
    assert constraints["additionalProperties"] is False
    assert constraints["required"] == ["max_intraday_drawdown_usd"]


def test_the_shipped_example_is_a_valid_walk_forward() -> None:
    loaded = load_futures_walkforward(EXAMPLE)
    assert loaded.file.scheme == "rolling"
    assert (loaded.file.train_trade_dates, loaded.file.test_trade_dates) == (20, 10)
    assert loaded.warmup_trade_dates == 5
    assert [candidate.name for candidate in loaded.candidates] == ["z60", "z120", "z240"]
    assert loaded.file.constraints.max_intraday_drawdown_usd == Decimal("5000")
    assert loaded.base.window.start == dt.date(2024, 1, 2)
    assert loaded.base.window.end == dt.date(2024, 6, 28)
    assert loaded.base.fidelity.preset == "screen"
    assert loaded.base.run.family == "examples-es-walkforward"
    assert walkforward_id(loaded.base, loaded.file).startswith("WFA-")


# ---------------------------------------------------------------------------------------------
# the shipped example, on the real store


@pytest.mark.bench
def test_the_shipped_example_runs_on_the_real_store(tmp_path: Path) -> None:
    raw = os.environ.get("CRUCIBLE_DATA_STORE")
    if not raw:
        pytest.skip("set CRUCIBLE_DATA_STORE to run the example against the real datasets")
    store = Path(raw)
    if not (store / "es_1m_cont_v3" / "manifest.json").is_file():
        pytest.skip(f"{store} does not hold es_1m_cont_v3 (see docs/data/glbx-futures-1m.md)")

    artifacts = tmp_path / "artifacts"
    result = run_futures_walkforward(EXAMPLE, store_root=store, artifacts_root=artifacts)
    document = result.document
    folds = document["folds"]
    assert len(folds) >= 1
    # the folds cover disjoint test windows in date order, and the remainder is reported
    window_test = [fold["test"]["start"] for fold in folds]
    assert window_test == sorted(window_test)
    for earlier, later in itertools.pairwise(folds):
        assert earlier["test"]["end"] < later["test"]["start"]
    assert document["train_trade_dates"] == 20
    assert document["test_trade_dates"] == 10
    assert document["warmup_trade_dates"] == 5

    frame = pl.read_parquet(result.walkforward_dir / "oos_daily.parquet")
    assert dict(frame.schema) == OOS_DAILY_SCHEMA
    capital = Decimal("50000")
    previous = capital
    for net, closing in zip(
        frame["net_pnl_usd"].to_list(),
        frame["closing_equity_usd"].to_list(),
        strict=True,
    ):
        assert closing == previous + net
        previous = closing
    summary = document["oos"]
    assert summary["net_pnl_usd"]["value"] == float(sum(frame["net_pnl_usd"].to_list(), Decimal(0)))
    assert summary["total_costs_usd"]["value"] == float(
        sum(frame["costs_usd"].to_list(), Decimal(0))
    )
    assert summary["fills"]["value"] == int(frame["fills"].sum())
    assert summary["trade_dates"]["value"] == frame.height
    # every fold that selected charged a terminal exit, and its last row carries it
    for fold in folds:
        if fold["selection"] is None:
            continue
        costs = Decimal(str(fold["oos"]["costs_usd"]["value"]))
        terminal = Decimal(str(fold["oos"]["terminal_exit_cost_usd"]["value"]))
        assert terminal == Decimal(str(fold["oos"]["open_contracts_at_last_bar"])) * Decimal(
            "2.00"
        )  # commission_only screen: the fees only, one side
        assert costs >= terminal
        assert verify_artifact(artifacts / str(fold["oos"]["run_id"])).startswith("ART-")
    # every metric is descriptive with null intervals and the verdict is not assessed
    for entry in summary.values():
        assert entry["assessment"] == "descriptive"
        assert entry["ci_low"] is None
    assert document["verdict"]["verdict_reason"]["code"] == "not_assessed"
