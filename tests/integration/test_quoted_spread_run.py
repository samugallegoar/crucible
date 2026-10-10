"""A ``quoted`` spread through the runner (ADR-0060).

Hand computation. One UP contract, 1-second bars at mid 0.40 (high == low == mid) with quotes
bid 0.38 / ask 0.42 at the open and the close. Level 2, zero latency, zero slippage and
commission. ``BuyCheapUp`` buys 100 on the first bar (close 0.40 < 0.45); the market order fills
on the next bar at its open 0.40 plus half the spread 0.02 = 0.42, so cash is 10000 - 42 = 9958.
With ``spread: none`` the same fill is at 0.40 (cash 9960).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS, QUOTED_BAR_SCHEMA
from crucible.data.store import build_dataset
from crucible.data.transforms import shuffle_bar_returns
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment

NS = 10**9
DATASET = "quoted_bars"
SYMBOL = "BTC5M-1000-UP"


def _frame(quotes: list[tuple[float | None, ...]] | None = None) -> pl.DataFrame:
    quotes = quotes or [(0.38, 0.42, 0.38, 0.42)] * 6
    times = [(1100 + 2 * i) * NS for i in range(6)]  # 6 bars: the report needs >= 3 returns
    return pl.DataFrame(
        {
            "symbol": [SYMBOL] * 6,
            "event_time": times,
            "available_at": times,
            "open": [0.40] * 6,
            "high": [0.40] * 6,
            "low": [0.40] * 6,
            "close": [0.40] * 6,
            "volume": [0.0] * 6,
            "bid_open": [q[0] for q in quotes],
            "ask_open": [q[1] for q in quotes],
            "bid_close": [q[2] for q in quotes],
            "ask_close": [q[3] for q in quotes],
        },
        schema_overrides={c: pl.Float64 for c in QUOTED_BAR_SCHEMA if "bid" in c or "ask" in c},
    )


def _store(root: Path, frame: pl.DataFrame, *, quoted: bool = True) -> None:
    build_dataset(
        root,
        DatasetId(DATASET),
        frame if quoted else frame.select(list(BAR_SCHEMA)),
        schema=QUOTED_BAR_SCHEMA if quoted else BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


def _config(root: Path, spread: dict[str, str]) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/real_data/polymarket_up.yaml").read_text(encoding="utf-8"))
    raw["experiment"]["realism_level"] = 2
    raw["data"].update({"store": str(root), "bars": DATASET})
    raw["data"].pop("corporate_actions")
    raw["execution"] = {"spread": spread, "slippage_bps": 0.0, "commission_bps": 0.0}
    raw["start"], raw["end"] = "1970-01-01", "1970-01-02"
    return ExperimentConfig.model_validate(raw)


def _fill_prices(artifacts: Path) -> list[float]:
    run_dir = next(p for p in artifacts.iterdir() if p.name.startswith("EXP-"))
    return pl.read_parquet(run_dir / "fills.parquet")["price"].to_list()


def test_a_quoted_run_costs_exactly_the_spread(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _store(root, _frame())
    quoted, plain = tmp_path / "quoted", tmp_path / "plain"
    run_experiment(_config(root, {"type": "quoted"}), quoted, record_trial=False)
    run_experiment(_config(root, {"type": "none"}), plain, record_trial=False)
    assert _fill_prices(quoted) == pytest.approx([0.42])  # 100 contracts: 10000 - 42 = 9958
    assert _fill_prices(plain) == pytest.approx([0.40])  # 10000 - 40 = 9960


def test_quoted_spread_refuses_a_store_without_quote_columns(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _store(root, _frame(), quoted=False)
    artifacts = tmp_path / "artifacts"
    with pytest.raises(ConfigurationError, match=r"bid_open.*crucible data build"):
        run_experiment(_config(root, {"type": "quoted"}), artifacts, record_trial=False)
    assert not artifacts.exists() or not any(artifacts.iterdir())


def test_quoted_spread_names_the_bar_that_has_no_quote(tmp_path: Path) -> None:
    root = tmp_path / "store"
    quotes: list[tuple[float | None, ...]] = [
        (0.38, 0.42, 0.38, 0.42),
        (None, None, None, None),  # the bar the order fills on
        (0.38, 0.42, 0.38, 0.42),
        (0.38, 0.42, 0.38, 0.42),
        (0.38, 0.42, 0.38, 0.42),
        (0.38, 0.42, 0.38, 0.42),
    ]
    _store(root, _frame(quotes))
    with pytest.raises(DataQualityError, match=rf"symbol {SYMBOL}"):
        run_experiment(_config(root, {"type": "quoted"}), tmp_path / "a", record_trial=False)


def test_null_test_transforms_drop_the_quotes_so_quoted_runs_refuse_there() -> None:
    """The null-test store is built with ``BAR_SCHEMA``: a shuffled series has no meaningful
    quotes, and the missing columns make the run-start refusal above apply."""
    shuffled = shuffle_bar_returns(
        _frame().with_columns(
            close=pl.Series([0.40, 0.41, 0.39, 0.40, 0.42, 0.41]),
            high=pl.Series([0.41, 0.42, 0.40, 0.41, 0.43, 0.42]),
            low=pl.Series([0.39, 0.40, 0.38, 0.39, 0.41, 0.40]),
        ),
        rng=np.random.default_rng(0),
    )
    assert "bid_open" not in shuffled.columns


@pytest.mark.parametrize("variant", ["shuffle", "sign_flip", "synthetic_gbm"])
def test_null_tests_refuse_a_quoted_spread_before_any_run_or_trial(
    tmp_path: Path, variant: str
) -> None:
    from crucible.experiments import null_tests

    root = tmp_path / "store"
    _store(root, _frame())
    artifacts = tmp_path / "artifacts"
    config = _config(root, {"type": "quoted"})
    rng = np.random.default_rng(0)
    calls = {
        "shuffle": lambda: null_tests.null_test_shuffle(config, 2, artifacts, rng),
        "sign_flip": lambda: null_tests.null_test_sign_flip(config, artifacts),
        "synthetic_gbm": lambda: null_tests.null_test_synthetic_gbm(config, 2, artifacts, rng),
    }
    with pytest.raises(ConfigurationError, match=r"null tests cannot run.*quoted"):
        calls[variant]()
    assert not artifacts.exists() or not any(artifacts.iterdir())  # no run, no trial store


def test_a_quoted_scenario_on_a_store_without_quotes_is_refused_before_the_base_run(
    tmp_path: Path,
) -> None:
    from crucible.experiments.runner import run_with_scenarios

    root = tmp_path / "store"
    _store(root, _frame(), quoted=False)
    config = _config(root, {"type": "none"})
    raw = config.model_dump(mode="python")
    raw["execution"]["scenarios"] = {"stress": {"spread": {"type": "quoted"}}}
    scenario_config = ExperimentConfig.model_validate(raw)
    artifacts = tmp_path / "artifacts"
    with pytest.raises(ConfigurationError, match="bid_open"):
        run_with_scenarios(scenario_config, artifacts)
    assert not artifacts.exists() or not any(artifacts.iterdir())  # the base run never started
