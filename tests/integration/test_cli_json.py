"""``--json`` and ``--override`` end to end on the momentum example (ADR-0059)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.experiments.config import config_hash, load_config
from examples.momentum.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def _config(store: Path, dest: Path, *, mode: str = "optimization") -> Path:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    raw["experiment"]["mode"] = mode
    dest.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return dest


def test_run_json_carries_the_headline_set(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(store, tmp_path / "c.yaml")
    code = main(["run", str(config), "--artifacts", str(tmp_path / "a"), "--json"])
    assert code == 0
    doc = json.loads(capsys.readouterr().out)  # stdout is exactly one JSON document
    assert doc["experiment_id"].startswith("EXP-")
    assert {"realism_level", "trial_count", "dsr", "pbo", "config_hash"} <= set(doc["manifest"])
    assert doc["metrics"]
    for metric in doc["metrics"].values():
        assert set(metric) == {"value", "ci_low", "ci_high"}
    assert Path(doc["artifacts"], "manifest.json").is_file()


def test_override_changes_the_hash_and_the_stored_config(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(store, tmp_path / "c.yaml")
    base_hash = config_hash(load_config(config))
    assert main(
        ["run", str(config), "--artifacts", str(tmp_path / "a"), "--json",
         "--override", "strategy.params.lookback=33"]
    ) == 0  # fmt: skip
    doc = json.loads(capsys.readouterr().out)
    assert doc["manifest"]["config_hash"] != base_hash
    stored = yaml.safe_load(Path(doc["artifacts"], "config.yaml").read_text(encoding="utf-8"))
    assert stored["strategy"]["params"]["lookback"] == 33


def test_optimize_json_and_compare_json_agree(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(store, tmp_path / "c.yaml")
    family = yaml.safe_load(config.read_text(encoding="utf-8"))["experiment"]["family"]
    artifacts = str(tmp_path / "a")
    assert main(
        ["optimize", str(config), "--param", "lookback", "--values", "40,60,80",
         "--pbo-groups", "4", "--artifacts", artifacts, "--json"]
    ) == 0  # fmt: skip
    optimized = json.loads(capsys.readouterr().out)
    assert len(optimized["points"]) == 3
    assert {"pbo", "n_combinations", "n_trials", "n_tied_splits"} == set(optimized["pbo"])

    assert main(["compare", family, "--artifacts", artifacts, "--json"]) == 0
    compared = json.loads(capsys.readouterr().out)
    ids = {p["experiment_id"] for p in optimized["points"]}
    assert ids == {t["experiment_id"] for t in compared["trials"]}


def test_data_list_json(store: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "list", "--store", str(store), "--json"]) == 0
    datasets = json.loads(capsys.readouterr().out)["datasets"]
    assert datasets
    assert {"dataset", "rows", "content_hash", "source"} == set(datasets[0])
