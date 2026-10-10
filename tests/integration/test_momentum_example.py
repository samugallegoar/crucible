"""The momentum example runs end-to-end: quality gate, engine, artifacts, report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import RunArtifacts, run_experiment
from examples.momentum.build_data import build_all


def _make_config(store: Path) -> dict[str, object]:
    raw = yaml.safe_load((Path("examples/momentum/config.yaml")).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return raw


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> RunArtifacts:
    store = tmp_path_factory.mktemp("data")
    build_all(store)
    config = ExperimentConfig.model_validate(_make_config(store))
    return run_experiment(config, tmp_path_factory.mktemp("artifacts"))


def test_artifact_store_is_complete(artifacts: RunArtifacts) -> None:
    expected = [
        "config.yaml",
        "manifest.json",
        "ledger.parquet",
        "orders.parquet",
        "fills.parquet",
        "trades.parquet",
        "equity.parquet",
        "metrics.json",
        "equity.svg",
        "report.html",
        "logs/run.jsonl",
    ]
    for name in expected:
        assert (artifacts.path / name).is_file(), f"missing artifact {name}"


def test_quality_gate_ran_and_manifest_records_provenance(
    artifacts: RunArtifacts,
) -> None:
    manifest = json.loads((artifacts.path / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["quality_checks_ran"]) == 5
    assert set(manifest["data_manifests"]) == {"bars", "corporate_actions", "universe"}
    assert manifest["realism_level"] == "BASIC_FRICTION"
    assert manifest["config_hash"]
    assert manifest["env_lock_hash"] != ""


def test_strategy_actually_traded(artifacts: RunArtifacts) -> None:
    import polars as pl

    fills = pl.read_parquet(artifacts.path / "fills.parquet")
    assert fills.height > 0
    # a base-currency equity run: USD, multiplier 1, FX 1 (ADR-0047)
    assert set(fills.get_column("currency").to_list()) == {"USD"}
    assert set(fills.get_column("multiplier").to_list()) == {"1"}
    assert set(fills.get_column("fx_to_base").to_list()) == {"1"}
    equity = pl.read_parquet(artifacts.path / "equity.parquet")
    assert equity.height > 400  # ~505 XNYS sessions in 2020-2021


def test_delisted_symbol_is_not_held_at_the_end(artifacts: RunArtifacts) -> None:
    import polars as pl

    ledger = pl.read_parquet(artifacts.path / "ledger.parquet")
    sym7 = ledger.filter(pl.col("symbol") == "SYM7")
    if sym7.height:  # if it was ever traded, its quantity must net to zero
        net = sum(float(q) for q in sym7.get_column("qty").to_list())
        assert net == 0.0


def test_report_contains_mandatory_header_and_uncertainty(
    artifacts: RunArtifacts,
) -> None:
    report = artifacts.report_path.read_text(encoding="utf-8")
    for needle in [
        "Provenance",
        "seed",
        "realism_level",
        "trial_family",
        "DSR: ",
        "benchmark_sharpe=",
        "PBO: not computed for a single run",
        "bootstrap CI",
    ]:
        assert needle in report
    assert "DSR: not computed" not in report  # DSR is computed for every run
    assert artifacts.metrics["sharpe"].ci_low is not None


def test_cli_report_rerenders(artifacts: RunArtifacts) -> None:
    code = main(["report", str(artifacts.experiment_id), "--artifacts", str(artifacts.path.parent)])
    assert code == 0


def test_cli_debug_steps_to_a_timestamp(
    artifacts: RunArtifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "debug",
            str(artifacts.experiment_id),
            "--at",
            "2020-06-01",
            "--artifacts",
            str(artifacts.path.parent),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "BarEvent" in out
    assert "state at ts<=" in out
    assert "cash(USD):" in out


def test_cli_debug_json_returns_state_and_the_last_events(
    artifacts: RunArtifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    code = main(
        [
            "debug",
            str(artifacts.experiment_id),
            "--at",
            "2020-06-01",
            "--artifacts",
            str(artifacts.path.parent),
            "--json",
        ]
    )
    assert code == 0
    doc = json.loads(capsys.readouterr().out)  # exactly one document: no event lines before it
    assert doc["experiment_id"] == str(artifacts.experiment_id)
    assert doc["events_total"] > 0
    assert 0 < len(doc["last_events"]) <= 20
    assert set(doc["last_events"][-1]) == {"ts", "seq", "kind", "symbol"}
    state = doc["state"]
    assert set(state) == {"cash", "positions", "orders"}
    assert state["cash"]["currency"] == "USD"
    assert isinstance(state["cash"]["amount"], str)  # Decimal: kept exact as text
    for order in state["orders"]:
        assert {"id", "symbol", "side", "type", "qty", "state", "filled_qty"} <= set(order)
        assert isinstance(order["why_not_filled"], list)
