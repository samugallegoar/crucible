"""A whole futures run driven by a DSL expression (ADR-0098): the artifact, its identity, the
manifest record, the CLI's check document and the config refusals.

The store is the synthetic ES store of ``tests/integration/test_futures_run_artifact.py`` (two
Globex trade dates, one contract switch), so the run is fast and every number comes from that
series. The expression is the DSL form of the shipped example: a z-score reversion whose score is
written with ``if`` and literal branches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.core.errors import ConfigurationError
from crucible.dsl import compile_expression
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import (
    FuturesRunConfig,
    futures_config_hash,
    load_futures_config,
    parse_futures_config,
)
from crucible.experiments.futures_document import FUTURES_DOCUMENT_SCHEMA_VERSION, futures_document
from crucible.experiments.futures_run import run_futures
from tests.integration.test_futures_run_artifact import build_store, mapping

if TYPE_CHECKING:
    from collections.abc import Mapping

EXPRESSION = "if(ts_zscore(close, $n:int[2,4]=3) < -0.5, 1, if(ts_zscore(close, $n) > 0.5, -1, 0))"
EXAMPLE = Path("examples/futures/es_zscore_reversion.yaml")
DATASETS = ("es_1m_cont_v3", "es_1m_cont_ratio_v3", "es_1m_rolls_v3", "es_1m_raw")


def expression_mapping(**overrides: object) -> dict[str, object]:
    """The synthetic store's config, with a DSL expression as the strategy source.

    An override of ``strategy.params`` keeps its bindings; the base config's spec is dropped.
    """
    config = mapping(**overrides)
    given = config.get("strategy")
    strategy: dict[str, object] = {"expression": EXPRESSION}
    if isinstance(given, dict) and "params" in given:
        strategy["params"] = given["params"]
    config["strategy"] = strategy
    return config


def expression_config(**overrides: object) -> FuturesRunConfig:
    return parse_futures_config(expression_mapping(**overrides))


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("store") / "store")


# ------------------------------------------------------------------------------------ the run


def test_a_run_with_an_expression_seals_and_records_the_definition(
    store: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(expression_config(), store_root=store, artifacts_root=artifacts)
    assert verify_artifact(result.run_dir) == result.artifact_id
    manifest: Mapping[str, object] = json.loads(
        (result.run_dir / "manifest.json").read_text("utf-8")
    )
    signal = manifest["signal"]
    assert isinstance(signal, dict)
    assert signal["strategy_kind"] == "dsl"
    assert signal["scale_invariance"]["static"] == "typed"
    assert signal["availability"]["result"] == "passed"
    described = signal["expression"]
    assert isinstance(described, dict)
    compiled = expression_config().strategy.compiled_signal("ratio_adjusted")
    assert described["compiled_id"] == compiled.compiled_id
    assert described["structure_id"] == compiled.structure_id
    assert described["parameterization_id"] == compiled.parameterization_id
    assert described["canonical_text"] == compiled.canonical_text
    assert described["warmup_bars"] == compiled.warmup_bars
    assert described["features"] == ["close"]

    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    assert marks.height == 10
    # the paths through futures_targets: the expression decides a side, contracts sizes it
    assert set(marks["position"].unique().to_list()) <= {-1, 0, 1}
    assert result.summary["trade_dates"] == 2


def test_the_same_config_and_data_reproduce_the_same_run_id(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    first = run_futures(expression_config(), store_root=store, artifacts_root=artifacts)
    second = run_futures(
        expression_config(), store_root=store, artifacts_root=artifacts, overwrite=True
    )
    assert first.run_id == second.run_id
    assert first.artifact_id == second.artifact_id
    assert first.trial_count == second.trial_count


def test_a_bound_parameter_changes_the_config_hash_and_the_compiled_id(
    store: Path, tmp_path: Path
) -> None:
    base = expression_config()
    rebound = expression_config(**{"strategy.params": {"n": 4}})
    assert futures_config_hash(base) != futures_config_hash(rebound)
    left = base.strategy.compiled_signal(base.signal.input)
    right = rebound.strategy.compiled_signal(rebound.signal.input)
    assert left.structure_id == right.structure_id
    assert left.compiled_id != right.compiled_id


def test_an_expression_run_prints_the_futures_document(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(expression_config(), store_root=store, artifacts_root=artifacts)
    document = futures_document(result.run_dir)
    assert document["schema_version"] == FUTURES_DOCUMENT_SCHEMA_VERSION
    assert all(metric["assessment"] == "descriptive" for metric in document["metrics"].values())


# ------------------------------------------------------------------------------- the CLI


def test_futures_check_prints_the_canonical_text_and_the_three_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "futures.yaml"
    path.write_text(yaml.safe_dump(expression_mapping()), encoding="utf-8")
    compiled = expression_config().strategy.compiled_signal("ratio_adjusted")

    assert main(["futures", "check", "--config", str(path), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["expression"]["canonical_text"] == compiled.canonical_text
    assert document["expression"]["structure_id"] == compiled.structure_id
    assert document["expression"]["parameterization_id"] == compiled.parameterization_id
    assert document["expression"]["compiled_id"] == compiled.compiled_id

    assert main(["futures", "check", "--config", str(path)]) == 0
    text = capsys.readouterr().out
    assert compiled.canonical_text in text
    assert compiled.structure_id in text
    assert compiled.parameterization_id in text
    assert compiled.compiled_id in text


# ------------------------------------------------------------------------------- refusals


def test_two_strategy_sources_are_refused() -> None:
    config = expression_mapping()
    strategy = config["strategy"]
    assert isinstance(strategy, dict)
    strategy["entrypoint"] = "some.module:function"
    with pytest.raises(ConfigurationError, match="exactly one of spec"):
        parse_futures_config(config)


def test_a_missing_contracts_is_refused_for_an_expression() -> None:
    with pytest.raises(ConfigurationError, match="contracts is required"):
        expression_config(contracts=None)


def test_an_unknown_parameter_name_is_refused_at_load() -> None:
    config = expression_mapping()
    config["strategy"] = {"expression": EXPRESSION, "params": {"window": 3}}
    with pytest.raises(ConfigurationError, match="unknown parameter"):
        parse_futures_config(config)


def test_a_non_numeric_parameter_is_refused_at_load() -> None:
    config = expression_mapping()
    config["strategy"] = {"expression": EXPRESSION, "params": {"n": "three"}}
    with pytest.raises(ConfigurationError, match="is not a number"):
        parse_futures_config(config)


def test_a_cross_sectional_rank_is_refused_because_a_futures_run_trades_one_root() -> None:
    config = expression_mapping()
    config["strategy"] = {"expression": "cs_rank(close / delay(close, 1))"}
    with pytest.raises(ConfigurationError, match="ranks across instruments"):
        parse_futures_config(config)
    # it compiles and evaluates fine as a library definition on a panel: the refusal is the run's
    compiled = compile_expression("cs_rank(close / delay(close, 1))", signal_input="unadjusted")
    assert "cs_rank" in compiled.canonical_text


def test_a_degree_one_score_is_refused_on_ratio_adjusted_input() -> None:
    config = expression_mapping()
    config["strategy"] = {"expression": "delta(close, 1)"}
    with pytest.raises(ConfigurationError, match="not scale invariant under ratio adjustment"):
        parse_futures_config(config)
    # the same expression is a valid score on the unadjusted series
    unadjusted = expression_mapping()
    unadjusted["strategy"] = {"expression": "delta(close, 1)"}
    unadjusted["signal"] = {"input": "unadjusted"}
    parse_futures_config(unadjusted)


def test_a_condition_expression_runs_as_long_while_true(store: Path, tmp_path: Path) -> None:
    config = expression_mapping()
    config["strategy"] = {"expression": "ts_zscore(close, 3) > 0.5"}
    result = run_futures(
        parse_futures_config(config), store_root=store, artifacts_root=tmp_path / "artifacts"
    )
    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    assert set(marks["position"].unique().to_list()) <= {0, 1}


# --------------------------------------------------------------------------------- the example


@pytest.mark.bench
def test_the_expression_example_runs_on_the_real_datasets(tmp_path: Path) -> None:
    """The real datasets of ``docs/data/glbx-futures-1m.md``; skips when the store lacks them.

    Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/integration/test_futures_run_expression.py
    """
    import os

    store_root = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
    missing = [name for name in DATASETS if not (store_root / name / "data.parquet").is_file()]
    if missing:
        pytest.skip(f"{missing} not built in {store_root}; see docs/data/glbx-futures-1m.md")
    config = load_futures_config(EXAMPLE)
    compiled = config.strategy.compiled_signal(config.signal.input)
    result = run_futures(config, store_root=store_root, artifacts_root=tmp_path / "artifacts")
    assert verify_artifact(result.run_dir) == result.artifact_id
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["signal"]["strategy_kind"] == "dsl"
    assert manifest["signal"]["expression"]["compiled_id"] == compiled.compiled_id
    assert manifest["signal"]["scale_invariance"]["static"] == "typed"
    document = futures_document(result.run_dir)
    # the null verdict document keeps its shape: a null level with a reason, descriptive metrics
    assert document["schema_version"] == FUTURES_DOCUMENT_SCHEMA_VERSION
    assert document["verdict"]["verdict_level"] is None
    assert document["verdict"]["verdict_reason"]["code"] == "not_assessed"
    assert all(metric["assessment"] == "descriptive" for metric in document["metrics"].values())
    print(
        "expression example:",
        {
            "run_id": result.run_id,
            "artifact_id": result.artifact_id,
            "fills": result.summary["fills"],
            "final_equity_usd": result.summary["final_equity_usd"],
            "compiled_id": compiled.compiled_id,
        },
    )
