"""Docs that name a repository path must name one that exists.

An agent that follows `docs/foo/bar.md` from a page and finds nothing loses time and trust;
this guards the entry-point documents (AGENTS.md, the docs/ pages, the module pages, the
prompts, the tests guide) against stale or misspelled paths.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

_DOCS = [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "tests/README.md",
    "docs/ARCHITECTURE.md",
    "docs/COMPATIBILITY.md",
    "docs/CONVENTIONS.md",
    "docs/DEPENDENCIES.md",
    "docs/EXTENSION_POINTS.md",
    "docs/INVENTORY.md",
    "docs/SCHEMAS.md",
    "docs/TIMING.md",
    "docs/USAGE.md",
    "docs/WHERE_THINGS_GO.md",
    "docs/adr/README.md",
    *(p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "docs" / "modules").glob("*.md"))),
]

_ROOTS = ("docs/", "tests/", "crucible/", "examples/", "tools/", ".github/", ".claude/")
_TOP_FILES = (
    "pyproject.toml",
    "uv.lock",
    "AGENTS.md",
    "CLAUDE.md",
    "CHANGELOG.md",
    "README.md",
)


def _candidate(token: str) -> str | None:
    """A backticked token that is meant to be a repo path, cleaned of `::symbol` / `:line`."""
    if any(mark in token for mark in "*<>{}$ ()|") or token.startswith("http") or "NNNN" in token:
        return None
    token = re.sub(r"(::[\w.]+|:\d+(-\d+)?)$", "", token)
    if token in _TOP_FILES:
        return token
    if token.startswith(_ROOTS) and re.fullmatch(r"[\w./\-]+", token):
        return token
    return None


def _references(doc: str) -> list[str]:
    text = (ROOT / doc).read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # code blocks show layouts, not links
    found = re.findall(r"`([^`\n]+)`", text)
    paths = [c for t in found if (c := _candidate(t))]
    # markdown links: [label](relative/path.md#anchor)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        target = target.split("#", 1)[0]
        if target and not target.startswith(("http", "mailto:")):
            resolved = (ROOT / doc).parent / target
            paths.append(resolved.resolve().relative_to(ROOT.resolve()).as_posix())
    return sorted(set(paths))


def _exists(path: str) -> bool:
    """A named path is fine if it exists, or if ``.gitignore`` excludes it on purpose.

    A doc may legitimately name a personal, local-only file (``.claude/settings.local.json``,
    an experiment directory): it exists on the author's machine and never in a clean checkout,
    so requiring it would pass locally and fail in CI.
    """
    if (ROOT / path).exists():
        return True
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def test_a_git_ignored_local_path_is_not_a_dangling_reference() -> None:
    assert _exists("experiments/EXP-does-not-exist/config.yaml")  # ignored by .gitignore
    assert _exists(".claude/settings.local.json")
    assert not _exists("docs/adr/9999-does-not-exist.md")  # tracked area: really missing


@pytest.mark.parametrize("doc", [d for d in _DOCS if (ROOT / d).is_file()])
def test_paths_named_in_the_doc_exist(doc: str) -> None:
    missing = [p for p in _references(doc) if not _exists(p)]
    assert not missing, f"{doc} names paths that do not exist: {missing}"


def test_the_new_entry_point_docs_exist() -> None:
    absent = [d for d in _DOCS if d not in ("CLAUDE.md",) and not (ROOT / d).is_file()]
    assert not absent, f"expected documents are missing: {absent}"
