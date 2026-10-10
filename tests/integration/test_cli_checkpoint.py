"""crucible run --stop-at, --checkpoint, --resume, --checkpoint-every via main(argv) (ADR-0058)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.core.checkpoint import read_checkpoint
from examples.trend_demo.build_data import build_all

DETERMINISTIC = [
    "config.yaml",
    "equity.parquet",
    "fills.parquet",
    "ledger.parquet",
    "metrics.json",
    "orders.parquet",
    "trades.parquet",
]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli_ckpt_store")
    build_all(root)
    return root


def _config(
    tmp_path: Path, store: Path, *, live: bool = False, lookback: int | None = None
) -> Path:
    source = "config_live.yaml" if live else "config.yaml"
    raw = yaml.safe_load(Path(f"examples/trend_demo/{source}").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    if lookback is not None:
        raw["strategy"]["params"]["lookback"] = lookback
    path = tmp_path / f"cfg_{source}_{lookback}"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _experiment_dir(root: Path) -> Path:
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("EXP-")]
    assert len(dirs) == 1
    return dirs[0]


def _same(a: Path, b: Path) -> None:
    assert a.name == b.name
    for name in DETERMINISTIC:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def _run(config: Path, root: Path, *extra: str) -> int:
    return main(["run", str(config), "--artifacts", str(root), *extra])


def test_stop_at_writes_only_a_checkpoint_and_says_where(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, ckpt, root = _config(tmp_path, store), tmp_path / "c.json", tmp_path / "a"
    assert _run(config, root, "--stop-at", "2020-06-13", "--checkpoint", str(ckpt)) == 0
    out = capsys.readouterr().out
    assert f"checkpoint: {ckpt}" in out
    assert "boundary:" in out
    assert "EXP-" not in out  # no experiment was produced
    assert not root.exists()
    assert read_checkpoint(ckpt)[0]["boundary_ts"]  # a real checkpoint


def test_stop_then_resume_equals_the_uninterrupted_run(store: Path, tmp_path: Path) -> None:
    config, ckpt = _config(tmp_path, store), tmp_path / "c.json"
    assert _run(config, tmp_path / "whole") == 0
    assert (
        _run(config, tmp_path / "part", "--stop-at", "2021-03-10", "--checkpoint", str(ckpt)) == 0
    )
    assert _run(config, tmp_path / "res", "--resume", str(ckpt)) == 0
    _same(_experiment_dir(tmp_path / "whole"), _experiment_dir(tmp_path / "res"))


def test_a_chained_resume_can_stop_again(store: Path, tmp_path: Path) -> None:
    config, one, two = _config(tmp_path, store), tmp_path / "1.json", tmp_path / "2.json"
    assert _run(config, tmp_path / "w", "--stop-at", "2020-09-01", "--checkpoint", str(one)) == 0
    code = _run(
        config,
        tmp_path / "w",
        "--resume",
        str(one),
        "--stop-at",
        "2021-03-01",
        "--checkpoint",
        str(two),
    )
    assert code == 0
    assert _run(config, tmp_path / "res", "--resume", str(two)) == 0
    assert _run(config, tmp_path / "whole") == 0
    _same(_experiment_dir(tmp_path / "whole"), _experiment_dir(tmp_path / "res"))


def test_checkpoint_every_keeps_results_and_leaves_a_resumable_file(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, ckpt = _config(tmp_path, store), tmp_path / "live.json"
    assert _run(config, tmp_path / "plain") == 0
    code = _run(config, tmp_path / "per", "--checkpoint-every", "30d", "--checkpoint", str(ckpt))
    assert code == 0
    assert "report:" in capsys.readouterr().out  # a normal, complete run
    _same(_experiment_dir(tmp_path / "plain"), _experiment_dir(tmp_path / "per"))
    assert ckpt.exists()
    assert _run(config, tmp_path / "rec", "--resume", str(ckpt)) == 0
    _same(_experiment_dir(tmp_path / "plain"), _experiment_dir(tmp_path / "rec"))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--stop-at", "2020-06-01"], "--checkpoint"),
        (["--checkpoint", "{c}"], "--stop-at"),
        (["--checkpoint-every", "1d"], "--checkpoint"),
        (
            ["--stop-at", "2020-06-01", "--checkpoint-every", "1d", "--checkpoint", "{c}"],
            "combined",
        ),
        (["--checkpoint-every", "0d", "--checkpoint", "{c}"], "interval"),
        (["--checkpoint-every", "1mo", "--checkpoint", "{c}"], "interval"),
        (["--stop-at", "tomorrow", "--checkpoint", "{c}"], "cannot parse"),
        (["--stop-at", "2019-01-01", "--checkpoint", "{c}"], "start"),
        (["--stop-at", "2023-01-01", "--checkpoint", "{c}"], "end"),
        (["--stop-at", "2020-06-01", "--checkpoint", "{nodir}"], "directory"),
        (["--checkpoint-every", "1s", "--checkpoint", "{c}"], "100,000"),
        (["--checkpoint-every", "800d", "--checkpoint", "{c}"], "longer than the run"),
        (["--stop-at", "2020-06-01", "--checkpoint", ""], "empty"),
        (["--resume", ""], "empty"),
        (["--stop-at", "1700000000000000000", "--checkpoint", "{c}"], "not a raw integer"),
        (["--stop-at", "2020-06-01", "--checkpoint", "{dir}"], "is a directory"),
    ],
)
def test_every_bad_combination_is_refused_and_writes_nothing(
    store: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    message: str,
) -> None:
    config, ckpt, root = _config(tmp_path, store), tmp_path / "c.json", tmp_path / "a"
    args = [a.format(c=ckpt, nodir=tmp_path / "nodir" / "c.json", dir=tmp_path) for a in extra]
    assert _run(config, root, *args) == 1
    err = capsys.readouterr().err
    assert "refused:" in err
    assert message in err
    assert not ckpt.exists()
    assert not root.exists() or not any(root.iterdir())


def test_resuming_with_a_different_setup_is_refused_and_leaves_no_artifacts(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ckpt, root = tmp_path / "c.json", tmp_path / "a"
    assert (
        _run(_config(tmp_path, store), root, "--stop-at", "2021-03-10", "--checkpoint", str(ckpt))
        == 0
    )
    assert _run(_config(tmp_path, store, lookback=5), root, "--resume", str(ckpt)) == 1
    assert "setup" in capsys.readouterr().err
    assert not root.exists()


def test_a_missing_checkpoint_is_refused(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "a"
    assert _run(_config(tmp_path, store), root, "--resume", str(tmp_path / "nope.json")) == 1
    assert "refused:" in capsys.readouterr().err
    assert not root.exists()


def test_a_stop_at_or_before_the_checkpoint_boundary_is_refused(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, one, two = _config(tmp_path, store), tmp_path / "1.json", tmp_path / "2.json"
    assert _run(config, tmp_path / "a", "--stop-at", "2021-03-10", "--checkpoint", str(one)) == 0
    code = _run(
        config,
        tmp_path / "a",
        "--resume",
        str(one),
        "--stop-at",
        "2020-12-01",
        "--checkpoint",
        str(two),
    )
    assert code == 1
    assert "already past" in capsys.readouterr().err
    assert not two.exists()


def test_the_flags_are_refused_with_scenarios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # refused before the store is touched, so the example's own (unbuilt) data path is fine
    code = _run(
        Path("examples/momentum/config_level4.yaml"),
        tmp_path,
        "--stop-at",
        "2020-06-01",
        "--checkpoint",
        str(tmp_path / "c.json"),
    )
    assert code == 1
    assert "scenarios" in capsys.readouterr().err
    assert not (tmp_path / "c.json").exists()


@pytest.mark.parametrize("runtime", ["paper", "live"])
def test_stop_and_resume_work_for_the_paper_and_live_runtimes(
    store: Path, tmp_path: Path, runtime: str
) -> None:
    config = _config(tmp_path, store, live=runtime == "live")
    ckpt = tmp_path / "c.json"
    assert _run(config, tmp_path / "whole", "--runtime", runtime) == 0
    stop = ["--stop-at", "2021-03-10", "--checkpoint", str(ckpt)]
    assert _run(config, tmp_path / "part", "--runtime", runtime, *stop) == 0
    assert _run(config, tmp_path / "res", "--runtime", runtime, "--resume", str(ckpt)) == 0
    _same(_experiment_dir(tmp_path / "whole"), _experiment_dir(tmp_path / "res"))


def test_the_help_lists_the_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--stop-at", "--checkpoint", "--resume", "--checkpoint-every"):
        assert flag in out
