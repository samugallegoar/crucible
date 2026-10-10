"""Runs import-linter with UTF-8 output on every platform.

    uv run python -m tools.lint_imports        # the layering rule (docs/ARCHITECTURE.md)

`lint-imports` prints box-drawing characters. On a legacy Windows code page (cp1252/cp437)
its console library raises ``UnicodeEncodeError`` *before* reporting anything, so the contract
check looks broken when it is not. This wrapper starts the real tool with ``PYTHONUTF8=1`` and
passes its exit code (and any extra arguments) through; on Linux and macOS it is equivalent to
running ``uv run lint-imports`` directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    executable = Path(sys.executable).with_name(
        "lint-imports.exe" if os.name == "nt" else "lint-imports"
    )
    if not executable.is_file():
        sys.stderr.write(
            f"{executable} not found: install the dev dependencies with `uv sync` "
            "(import-linter is a dev dependency)\n"
        )
        return 2
    command = [str(executable), *(sys.argv[1:] if argv is None else argv)]
    return subprocess.run(command, env={**os.environ, "PYTHONUTF8": "1"}, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
