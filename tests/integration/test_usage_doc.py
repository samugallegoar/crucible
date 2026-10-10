"""Every ```python run block in docs/USAGE.md is executed, in order, in one namespace (against a
temporary artifact root), so the usage guide cannot drift from the API."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def test_the_usage_guide_snippets_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python run\n(.*?)```", text, re.S)
    assert len(blocks) >= 3, "docs/USAGE.md should carry runnable examples"
    monkeypatch.chdir(ROOT)  # the guide uses repo-relative example paths
    artifacts = tmp_path / "experiments"
    namespace: dict[str, Any] = {"__name__": "usage_doc"}
    for index, block in enumerate(blocks):
        code = block.replace('Path("experiments")', f"Path({str(artifacts)!r})")
        exec(compile(code, f"docs/USAGE.md block {index + 1}", "exec"), namespace)
    assert namespace["run"].experiment_id
    assert namespace["past"].experiment_id == namespace["run"].experiment_id
    assert namespace["table"].height == 2
