"""crucible promote through main(argv) (batch 3, ADR-0051)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.core.types import RealismLevel
from crucible.experiments.config import ExecutionConfig, load_config
from crucible.experiments.promotion import promote_config
from examples.trend_demo.build_data import build_all

_EXECUTION = {
    "spread": {"type": "static", "half_spread_bps": 25.0},
    "latency": {"type": "constant", "ms": 50.0},
    "slippage": {"type": "fixed_bps", "bps": 10.0},
}


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("promote_store")
    build_all(root)
    return root


@pytest.fixture
def files(store: Path, tmp_path: Path) -> tuple[Path, Path]:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    raw["data"]["store"] = str(store)
    config = tmp_path / "vectorized.yaml"
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    execution = tmp_path / "execution.yaml"
    execution.write_text(yaml.safe_dump(_EXECUTION), encoding="utf-8")
    return config, execution


def _expected(config: Path) -> object:
    return promote_config(
        load_config(config),
        target_realism_level=RealismLevel.SPREAD_LATENCY,
        execution=ExecutionConfig.model_validate(_EXECUTION),
        promotion_lookback=3,
    )


def _args(config: Path, execution: Path, *extra: str) -> list[str]:
    return [
        "promote",
        str(config),
        "--level",
        "2",
        "--lookback",
        "3",
        "--execution",
        str(execution),
        *extra,
    ]


def test_promote_writes_the_config_promote_config_builds(
    files: tuple[Path, Path], tmp_path: Path
) -> None:
    config, execution = files
    out = tmp_path / "promoted.yaml"
    assert main(_args(config, execution, "--out", str(out))) == 0
    assert load_config(out) == _expected(config)


def test_promote_without_out_prints_only_the_yaml(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config, execution = files
    assert main(_args(config, execution)) == 0
    printed = yaml.safe_load(capsys.readouterr().out)
    assert printed == _expected(config).model_dump(mode="json")  # type: ignore[attr-defined]


def test_promote_run_produces_artifacts(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, execution = files
    code = main(
        _args(
            config,
            execution,
            "--out",
            str(tmp_path / "p.yaml"),
            "--run",
            "--artifacts",
            str(tmp_path / "x"),
        )
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "EXP-" in out
    assert "report:" in out


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (("--level", "1"), "Level 2"),
        (("--level", "9"), "realism level"),
        (("--lookback", "0"), "lookback"),
    ],
)
def test_promote_refuses_bad_numbers(
    files: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    edit: tuple[str, str],
    message: str,
) -> None:
    config, execution = files
    argv = _args(config, execution)
    argv[argv.index(edit[0]) + 1] = edit[1]
    assert main(argv) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "does not exist"),
        ("- a\n- b\n", "mapping"),
        ("bogus: 1\n", "ExecutionConfig"),
    ],
)
def test_promote_refuses_a_bad_execution_file(
    files: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | None,
    message: str,
) -> None:
    config, _ = files
    bad = tmp_path / "bad_execution.yaml"
    if content is not None:
        bad.write_text(content, encoding="utf-8")
    assert main(_args(config, bad)) == 1
    assert message in capsys.readouterr().err


def test_promote_refuses_a_non_utf8_execution_file(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = files
    bad = tmp_path / "latin1.yaml"
    bad.write_bytes("spread: caf\xe9\n".encode("latin-1"))
    assert main(_args(config, bad)) == 1
    assert "UTF-8" in capsys.readouterr().err


def test_promote_refuses_an_out_directory_that_does_not_exist(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, execution = files
    assert main(_args(config, execution, "--out", str(tmp_path / "missing" / "p.yaml"))) == 1
    assert "does not exist" in capsys.readouterr().err


def test_promote_run_needs_out_so_stdout_stays_pure_yaml(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, execution = files
    argv = _args(config, execution, "--run", "--artifacts", str(tmp_path / "x"))
    assert main(argv) == 1
    assert "--run needs --out" in capsys.readouterr().err


def test_promote_json_with_out_names_the_file(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    config, execution = files
    out = tmp_path / "p.yaml"
    assert main(_args(config, execution, "--out", str(out), "--json")) == 0
    doc = json.loads(capsys.readouterr().out)  # stdout is exactly one JSON document
    assert doc == {"config": str(out), "run": None, "yaml": None}
    assert out.is_file()


def test_promote_json_without_out_carries_the_yaml(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    config, execution = files
    assert main(_args(config, execution, "--json")) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["config"] is None
    assert yaml.safe_load(doc["yaml"])["strategy"]["entrypoint"].endswith("PromotedSignalStrategy")


def test_promote_json_with_run_carries_the_headline_set(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    config, execution = files
    args = _args(
        config,
        execution,
        "--out",
        str(tmp_path / "p.yaml"),
        "--run",
        "--json",
        "--artifacts",
        str(tmp_path / "x"),
    )
    assert main(args) == 0
    run = json.loads(capsys.readouterr().out)["run"]
    assert run["experiment_id"].startswith("EXP-")
    assert {"realism_level", "trial_count", "dsr", "pbo"} <= set(run["manifest"])
    assert run["metrics"]


def test_promote_json_refusal_is_an_error_document(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    config, execution = files
    assert main(_args(config, execution, "--run", "--json")) == 1  # --run needs --out
    assert "--run needs --out" in json.loads(capsys.readouterr().out)["error"]["message"]
