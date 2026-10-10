"""The one-step backtest (ADR-0068) end to end, offline, on a synthetic dataset.

The dataset is placed in the home's store under the name the product derives from the request, so
``ensure_dataset`` finds it and never touches the network (the suite blocks the network anyway).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.analytics.trades import build_episodes
from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.product.backtest import BacktestRequest, run_backtest
from crucible.product.data import dataset_name, ensure_dataset
from crucible.product.home import Home, resolve_home
from crucible.strategy_spec import load_spec
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig
from examples.sma_cross.signal import sma_cross_signal
from examples.trend_demo.build_data import SYMBOL, build_all

START, END = dt.date(2020, 1, 1), dt.date(2021, 12, 30)
SPEC_FILE = Path("examples/sma_cross/spec.yaml")


def seed_home(root: Path) -> Home:
    """A home whose store holds the trend_demo bars under the product's own dataset name."""
    scratch = root / "_src"
    build_all(scratch)
    bars = pl.read_parquet(scratch / "trend_demo_bars_v1" / "data.parquet")
    home = resolve_home(root / "home")
    name = dataset_name("yfinance", [SYMBOL], START, END, "1d", "adjusted")
    build_dataset(
        home.data, DatasetId(name), bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t"
    )
    return home


def request(home: Home, **overrides: object) -> BacktestRequest:
    base = {
        "spec": load_spec(SPEC_FILE),
        "symbols": [SYMBOL],
        "start": START.isoformat(),
        "end": END.isoformat(),
        "capital": 100_000.0,
        "provider": "yfinance",
        "offline": True,
        "null_iterations": 20,
        "home": home.root,
    }
    base.update(overrides)
    return BacktestRequest(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Home:
    return seed_home(tmp_path_factory.mktemp("product"))


@pytest.fixture(scope="module")
def doc(home: Home) -> dict[str, object]:
    return run_backtest(request(home))


def test_the_document_has_everything_a_non_quant_needs(doc: dict[str, object]) -> None:
    assert doc["status"] == "ok"
    assert str(doc["experiment_id"]).startswith("EXP-")
    results = doc["results"]
    assert isinstance(results, dict)
    for side in ("strategy", "benchmark"):
        block = results[side]
        assert {"final_equity", "cagr_pct", "max_drawdown_pct", "sharpe", "sharpe_low"} <= set(
            block
        )
    validation = doc["validation"]
    assert isinstance(validation, dict)
    assert {"trial_count", "dsr", "realism_level", "null_test"} <= set(validation)
    assert validation["null_test"]["iterations"] == 20  # type: ignore[index]
    summary = doc["summary"]
    assert isinstance(summary, dict)
    assert summary["verdict_level"] in {"not_conclusive", "no_edge_detected", "some_evidence"}
    assert any(f["code"] == "single_instrument" for f in summary["flags"])
    assert doc["strategy_explained"]
    assert Path(str(doc["report"])).is_absolute()
    assert Path(str(doc["report"])).is_file()


def test_the_report_is_self_contained_and_shows_the_benchmark(doc: dict[str, object]) -> None:
    page = Path(str(doc["report"])).read_text(encoding="utf-8")
    assert page.count("<svg") == 2  # equity and drawdown, inline
    assert "Buy and hold" in page
    assert "Verdict" in page
    assert "<script" not in page
    assert "http://" not in page.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in page


def test_the_spec_reproduces_the_hand_written_signal_exactly(
    home: Home, doc: dict[str, object]
) -> None:
    """Compile-to-signal equivalence: ``spec.yaml`` and ``signal.py`` give the same equity."""
    store = ParquetDataStore(home.data)
    name = dataset_name("yfinance", [SYMBOL], START, END, "1d", "adjusted")
    config = request(home)
    runs = {}
    for label, signal, params in (
        ("hand", sma_cross_signal, {"fast": 10, "slow": 30}),
        (
            "spec",
            __import__("crucible.strategy_spec", fromlist=["spec_signal"]).spec_signal,
            {"spec": doc["strategy_spec"]},
        ),
    ):
        runs[label] = VectorizedBacktestEngine().run(
            VectorizedConfig(
                store=store,
                bars_dataset=DatasetId(name),
                signal=signal,
                params=params,
                initial_cash=Decimal("100000"),
                realism_level=RealismLevel.BASIC_FRICTION,
                start=TimestampNs(int(dt.datetime(2020, 1, 1, tzinfo=dt.UTC).timestamp() * 1e9)),
                end=TimestampNs(
                    int(dt.datetime(2021, 12, 30, 23, 59, 59, tzinfo=dt.UTC).timestamp() * 1e9)
                ),
                slippage_bps=1.0,
                commission_bps=0.5,
            )
        )
    assert config.spec is not None
    assert runs["hand"].equity.equals(runs["spec"].equity)
    assert runs["hand"].weights.equals(runs["spec"].weights)
    episodes = build_episodes(runs["spec"].weights, runs["spec"].pnl)
    results = doc["results"]
    assert isinstance(results, dict)
    assert results["strategy"]["n_trades"] == episodes.height  # type: ignore[index]
    final = float(runs["spec"].equity.get_column("equity")[-1])
    assert results["strategy"]["final_equity"] == pytest.approx(final, abs=0.01)  # type: ignore[index]


def test_the_same_request_gives_byte_identical_artifacts(home: Home, tmp_path: Path) -> None:
    first = run_backtest(request(home))
    first_bytes = (Path(str(first["artifacts"])) / "summary.json").read_bytes()
    again = run_backtest(request(home))
    assert again["experiment_id"] == first["experiment_id"]
    assert (Path(str(again["artifacts"])) / "summary.json").read_bytes() == first_bytes
    assert (Path(str(again["artifacts"])) / "summary.html").read_bytes() == (
        Path(str(first["artifacts"])) / "summary.html"
    ).read_bytes()


def test_a_second_variant_is_a_second_trial(home: Home) -> None:
    other = load_spec(
        {
            "entry": {"long": "sma(5) crosses_above sma(15)"},
            "exit": {"long": "sma(5) crosses_below sma(15)"},
        }
    )
    result = run_backtest(request(home, spec=other, null_iterations=0))
    validation = result["validation"]
    assert isinstance(validation, dict)
    assert validation["trial_count"] >= 2
    assert validation["null_test"] is None


def test_offline_with_no_stored_data_is_refused_with_the_fix(tmp_path: Path) -> None:
    empty = resolve_home(tmp_path / "empty")
    with pytest.raises(ConfigurationError, match="offline mode is on"):
        run_backtest(request(empty))


def test_an_end_date_that_is_not_in_the_past_is_refused(home: Home) -> None:
    with pytest.raises(ConfigurationError, match="not in the past"):
        ensure_dataset(
            home,
            symbols=["SPY"],
            start=dt.date(2020, 1, 1),
            end=dt.date(2020, 6, 1),
            today=dt.date(2020, 6, 1),
            provider="yfinance",
        )


def test_a_window_too_short_for_the_rules_is_refused(home: Home) -> None:
    with pytest.raises(ConfigurationError, match="too short"):
        run_backtest(request(home, start="2021-12-01", end="2021-12-20"))


def test_the_costs_are_in_the_result_and_change_it(home: Home) -> None:
    free = run_backtest(request(home, cost_preset="none", null_iterations=0))
    pricey = run_backtest(request(home, cost_preset="conservative", null_iterations=0))
    free_equity = free["results"]["strategy"]["final_equity"]  # type: ignore[index]
    pricey_equity = pricey["results"]["strategy"]["final_equity"]  # type: ignore[index]
    assert pricey_equity < free_equity
    assert free["request"]["costs"]["preset"] == "none"  # type: ignore[index]
    assert free["validation"]["realism_level"] == "FRICTIONLESS"  # type: ignore[index]


def test_the_cli_prints_one_json_document_and_lists_results(home: Home) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "crucible.cli.main",
            "backtest",
            "--spec",
            str(SPEC_FILE),
            "--symbols",
            SYMBOL,
            "--start",
            START.isoformat(),
            "--end",
            END.isoformat(),
            "--provider",
            "yfinance",
            "--offline",
            "--null-iterations",
            "5",
            "--home",
            str(home.root),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    document = json.loads(done.stdout)
    assert document["summary"]["headline"]
    listing = subprocess.run(
        [sys.executable, "-m", "crucible.cli.main", "results", "--home", str(home.root), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    ids = [r["experiment_id"] for r in json.loads(listing.stdout)["results"]]
    assert document["experiment_id"] in ids


def test_a_cli_refusal_is_one_json_error_with_the_fix() -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "crucible.cli.main",
            "backtest",
            "--entry",
            "rsi(14) < 30",
            "--symbols",
            "SPY",
            "--start",
            "2020-01-01",
            "--end",
            "2021-01-01",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 1
    error = json.loads(done.stdout)["error"]
    assert error["type"] == "ConfigurationError"
    assert "has no way out" in error["message"]


def test_the_spec_yaml_example_is_a_valid_spec() -> None:
    raw = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
    assert raw["entry"]["long"] == "sma(10) crosses_above sma(30)"
    assert np.isclose(load_spec(raw).sizing.weight, 1.0)


def test_the_realism_check_reruns_on_the_event_driven_engine_without_a_new_trial(
    home: Home,
) -> None:
    before = run_backtest(request(home, null_iterations=0))
    checked = run_backtest(request(home, null_iterations=0, realism_check=True))
    block = checked["validation"]["realism_check"]  # type: ignore[index]
    assert block["engine"] == "event-driven"
    assert block["realism_level"] == "SPREAD_LATENCY"
    assert block["experiment_id"] != checked["experiment_id"]
    # the headline run is the same run, and the check added no trial to its family
    assert checked["results"] == before["results"]
    assert checked["validation"]["trial_count"] == before["validation"]["trial_count"]  # type: ignore[index]
    assert any("realistic fills" in line for line in checked["summary"]["what_happened"])  # type: ignore[index]


def test_renaming_a_strategy_is_neither_a_new_experiment_nor_a_new_trial(home: Home) -> None:
    raw = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
    first = run_backtest(
        request(home, spec=load_spec({**raw, "name": "first name"}), null_iterations=0)
    )
    second = run_backtest(
        request(home, spec=load_spec({**raw, "name": "another name"}), null_iterations=0)
    )
    assert second["experiment_id"] == first["experiment_id"]
    assert second["validation"]["trial_count"] == first["validation"]["trial_count"]  # type: ignore[index]
    assert second["request"]["strategy_name"] == "another name"  # type: ignore[index]


def test_raw_prices_are_refused_because_the_flow_has_no_dividend_events(home: Home) -> None:
    with pytest.raises(ConfigurationError, match="silently drop dividends"):
        run_backtest(request(home, price_basis="raw"))
