"""crucible run --runtime and run-vectorized through main(argv) (batch 3, ADR-0051)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from examples.trend_demo.build_data import build_all

# Ubuntu CI only (ADR-0076): CLI wrapper over the runtimes, whose parity test_live_parity covers on
# every OS. Runs everywhere locally.
pytestmark = pytest.mark.single_os


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli_store")
    build_all(root)
    return root


def _write_config(
    tmp_path: Path, store: Path, source: str = "config.yaml", *, live: bool = False
) -> Path:
    raw = yaml.safe_load(Path(f"examples/trend_demo/{source}").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    if live:
        raw["live"] = {"enabled": True}
    path = tmp_path / f"cfg_{source}_{'live' if live else 'plain'}"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _experiment_dir(root: Path) -> Path:
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("EXP-")]
    assert len(dirs) == 1
    return dirs[0]


def test_run_with_the_paper_runtime_matches_the_backtest(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store)
    assert main(["run", str(config), "--artifacts", str(tmp_path / "a")]) == 0
    assert main(["run", str(config), "--runtime", "paper", "--artifacts", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert out.count("EXP-") >= 2
    a, b = _experiment_dir(tmp_path / "a"), _experiment_dir(tmp_path / "b")
    assert (a / "equity.parquet").read_bytes() == (b / "equity.parquet").read_bytes()
    manifest = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime"] == "paper"


def test_run_with_the_live_runtime_on_a_live_config(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store, live=True)
    assert main(["run", str(config), "--runtime", "live", "--artifacts", str(tmp_path / "x")]) == 0
    assert "report:" in capsys.readouterr().out
    manifest = json.loads(
        (_experiment_dir(tmp_path / "x") / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["runtime"] == "live"


def test_a_live_config_is_refused_without_the_live_runtime(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store, live=True)
    assert main(["run", str(config), "--artifacts", str(tmp_path / "x")]) == 1
    assert "--runtime live" in capsys.readouterr().err


def test_the_live_runtime_is_refused_without_the_flag(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store)
    assert main(["run", str(config), "--runtime", "live", "--artifacts", str(tmp_path)]) == 1
    assert "refused" in capsys.readouterr().err


def test_scenarios_are_refused_with_a_non_backtest_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # refused before the store is touched, so the example's own (unbuilt) data path is fine
    code = main(
        [
            "run",
            "examples/momentum/config_level4.yaml",
            "--runtime",
            "paper",
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "scenarios" in capsys.readouterr().err


def test_run_vectorized_writes_a_report(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store, "config_vectorized.yaml")
    assert main(["run-vectorized", str(config), "--artifacts", str(tmp_path / "v")]) == 0
    assert "report:" in capsys.readouterr().out
    assert (_experiment_dir(tmp_path / "v") / "report.html").is_file()


def test_run_vectorized_refuses_a_config_it_cannot_honor(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store, "config_vectorized.yaml", live=True)
    assert main(["run-vectorized", str(config), "--artifacts", str(tmp_path / "v")]) == 1
    assert "live" in capsys.readouterr().err


def test_debug_replays_a_live_run_through_the_venue(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, store, live=True)
    assert main(["run", str(config), "--runtime", "live", "--artifacts", str(tmp_path / "x")]) == 0
    capsys.readouterr()
    experiment = _experiment_dir(tmp_path / "x").name
    code = main(["debug", experiment, "--at", "2021-01-01", "--artifacts", str(tmp_path / "x")])
    out = capsys.readouterr().out
    assert code == 0
    assert "VenueFillEvent" in out, "a live replay must step the venue's fill events"
    assert "--- state at" in out
