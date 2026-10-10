"""Which test modules are slow: read a ``pytest --durations=0`` log, print or write the list.

    uv run pytest -q --durations=0 > durations.log
    uv run python -m tools.slow_report durations.log                  # a table, slowest first
    uv run python -m tools.slow_report durations.log --write          # tests/slow_modules.txt

``tests/slow_modules.txt`` is read by ``tests/conftest.py``, which gives every test in a listed
module the ``slow`` marker. The marker only *selects*: a plain ``pytest`` still runs everything, and
``-m "not slow"`` (``python -m tools.check --fast``) is the opt-in fast tier. ``tests/golden`` and
``tests/lookahead`` are never listed (the invariants stay in the fast loop).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

LIST_FILE = Path("tests/slow_modules.txt")
DEFAULT_THRESHOLD_S = 3.0
EXEMPT_PREFIXES = ("tests/golden/", "tests/lookahead/", "tests/bench/")
_LINE = re.compile(r"^\s*([0-9.]+)s\s+(?:call|setup|teardown)\s+(\S+?)::")


def module_seconds(log_text: str) -> dict[str, float]:
    """Total seconds per test module (call, setup and teardown) in a durations log."""
    totals: dict[str, float] = defaultdict(float)
    for line in log_text.splitlines():
        match = _LINE.match(line)
        if match:
            totals[match.group(2).replace("\\", "/")] += float(match.group(1))
    return dict(totals)


def slow_modules(totals: dict[str, float], threshold: float) -> list[str]:
    """Modules at or above ``threshold`` seconds, excluding the exempt tiers, sorted by path."""
    return sorted(
        path
        for path, seconds in totals.items()
        if seconds >= threshold and not path.startswith(EXEMPT_PREFIXES)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.slow_report", description=__doc__)
    parser.add_argument("log", type=Path, help="output of `pytest --durations=0`")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_S)
    parser.add_argument("--write", action="store_true", help=f"write {LIST_FILE}")
    args = parser.parse_args(argv)
    totals = module_seconds(args.log.read_text(encoding="utf-8", errors="replace"))
    if not totals:
        print("no durations found: run pytest with --durations=0", file=sys.stderr)
        return 1
    chosen = slow_modules(totals, args.threshold)
    all_seconds = sum(totals.values())
    fast_seconds = all_seconds - sum(totals[m] for m in chosen)
    for path in sorted(chosen, key=lambda p: -totals[p]):
        print(f"{totals[path]:7.1f}s  {path}")
    print(
        f"\n{len(chosen)} slow modules (>= {args.threshold:g}s); measured test time "
        f"{all_seconds:.0f}s in total, {fast_seconds:.0f}s in the fast tier"
    )
    if args.write:
        LIST_FILE.write_text("\n".join(chosen) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {LIST_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
