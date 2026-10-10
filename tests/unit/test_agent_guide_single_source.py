"""The agent guide has one source: ``AGENT_GUIDE.md`` at the repository root.

The wheel ships that file as ``crucible/product/AGENT_GUIDE.md`` (a hatch force-include), and
``guide_text()`` reads the packaged resource when it exists and the root file otherwise. A second
tracked copy would be two sources of truth.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
GUIDE = ROOT / "AGENT_GUIDE.md"


def test_there_is_no_second_tracked_copy_of_the_guide() -> None:
    assert GUIDE.is_file()
    assert not (ROOT / "crucible" / "product" / "AGENT_GUIDE.md").exists(), (
        "the root AGENT_GUIDE.md is the only source; the wheel build copies it into the package"
    )


def test_the_wheel_force_include_maps_the_root_guide_into_the_package() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert include == {"AGENT_GUIDE.md": "crucible/product/AGENT_GUIDE.md"}


def test_guide_text_returns_the_root_file_in_a_source_checkout() -> None:
    from crucible.mcp_server.server import guide_text

    assert guide_text() == GUIDE.read_text(encoding="utf-8")


@pytest.mark.slow
def test_a_built_wheel_contains_the_guide_unchanged(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH; the force-include configuration is asserted above")
    done = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    (wheel,) = tmp_path.glob("crucible-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        packaged = archive.read("crucible/product/AGENT_GUIDE.md")
    assert packaged == GUIDE.read_bytes()
