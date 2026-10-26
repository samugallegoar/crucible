"""Code identity, provenance and the overwrite guard (ADR-0079).

Three properties, each of which used to fail silently:

1. Git provenance is resolved from the code's own checkout, not the process's working
   directory (a run started from another directory wrote ``commit=unknown``).
2. The lockfile hash is found the same way.
3. A finished experiment is not replaced by a run of different code just because the config
   and the data hash to the same id.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from crucible.core.errors import ExperimentError
from crucible.experiments import runner
from crucible.experiments.runner import _code_fingerprint, _git_provenance, _refuse_overwrite


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _checkout(root: Path) -> str:
    """A real one-commit git repository at ``root``; returns its HEAD commit."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "agent@example.invalid")
    _git(root, "config", "user.name", "audit")
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return _git(root, "rev-parse", "HEAD")


def test_provenance_follows_the_code_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    commit = _checkout(checkout)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the process cwd is NOT the checkout
    monkeypatch.setattr(runner, "_resolution_root", lambda: checkout)
    assert _git_provenance() == (commit, False)


def test_the_lockfile_is_found_from_the_code_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hashlib import sha256

    checkout = tmp_path / "checkout"
    _checkout(checkout)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(runner, "_resolution_root", lambda: checkout)
    assert runner._env_lock_hash() == sha256((checkout / "uv.lock").read_bytes()).hexdigest()


def test_the_code_fingerprint_changes_with_an_uncommitted_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    _checkout(checkout)
    monkeypatch.setattr(runner, "_resolution_root", lambda: checkout)
    before = _code_fingerprint()
    (checkout / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert _code_fingerprint() != before


def _write_manifest(root: Path, exp_id: str, **fields: object) -> Path:
    out_dir = root / exp_id
    out_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "experiment_id": exp_id,
        "commit": "a" * 40,
        "dirty": False,
        **fields,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out_dir


def test_a_run_of_the_same_code_may_replace_itself(tmp_path: Path) -> None:
    out_dir = _write_manifest(tmp_path, "EXP-1", code_fingerprint="abc")
    _refuse_overwrite(
        out_dir, commit="a" * 40, dirty=False, fingerprint="abc", overwrite=False
    )  # does not raise


def test_a_run_of_different_committed_code_is_refused(tmp_path: Path) -> None:
    out_dir = _write_manifest(tmp_path, "EXP-1", code_fingerprint="abc")
    with pytest.raises(ExperimentError, match="written by commit="):
        _refuse_overwrite(out_dir, commit="b" * 40, dirty=False, fingerprint="def", overwrite=False)
    assert (out_dir / "manifest.json").is_file()  # the earlier run is untouched


def test_an_uncommitted_edit_is_refused_even_with_the_same_commit(tmp_path: Path) -> None:
    """The commit alone cannot see a working-tree edit: the fingerprint must."""
    out_dir = _write_manifest(tmp_path, "EXP-1", code_fingerprint="abc")
    with pytest.raises(ExperimentError, match="different code fingerprint"):
        _refuse_overwrite(out_dir, commit="a" * 40, dirty=True, fingerprint="def", overwrite=False)


def test_overwrite_replaces_on_purpose(tmp_path: Path) -> None:
    out_dir = _write_manifest(tmp_path, "EXP-1", code_fingerprint="abc")
    _refuse_overwrite(out_dir, commit="c" * 40, dirty=True, fingerprint="def", overwrite=True)


def test_a_manifest_without_a_fingerprint_falls_back_to_commit_and_dirty(
    tmp_path: Path,
) -> None:
    """Artifacts written before ADR-0079 carry no code_fingerprint: commit + dirty is the best
    they can offer, so a same-commit rerun is still allowed."""
    out_dir = _write_manifest(tmp_path, "EXP-1")  # no code_fingerprint key
    _refuse_overwrite(
        out_dir, commit="a" * 40, dirty=False, fingerprint="whatever", overwrite=False
    )
    with pytest.raises(ExperimentError):
        _refuse_overwrite(out_dir, commit="b" * 40, dirty=True, fingerprint="x", overwrite=False)
