"""Structured JSON-lines run log (E8).

Log entries carry *simulation* time, never wall-clock — logging must not be a
side channel that breaks determinism. Entries accumulate in memory and are
written once, at the end of the run, into the artifact store.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from crucible.core import checkpoint as ckpt

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from crucible.core.interfaces import Clock


class RunLogger:
    """Collects structured entries; deterministic given identical runs."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: list[dict[str, object]] = []

    def log(self, level: str, msg: str, **fields: object) -> None:
        self._entries.append({"ts": int(self._clock.now), "level": level, "msg": msg, **fields})

    def info(self, msg: str, /, **fields: object) -> None:
        self.log("info", msg, **fields)

    def warning(self, msg: str, /, **fields: object) -> None:
        self.log("warning", msg, **fields)

    @property
    def entries(self) -> list[dict[str, object]]:
        return list(self._entries)

    def write(self, path: Path) -> None:
        lines = "".join(
            json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in self._entries
        )
        path.write_text(lines, encoding="utf-8", newline="\n")

    def snapshot(self) -> dict[str, object]:
        """Every log entry so far, in order."""
        return {"entries": [dict(entry) for entry in self._entries]}

    def restore(self, state: Mapping[str, object]) -> None:
        """Replaces the entries in place; the logger's clock reference is unchanged."""
        entries_list = ckpt.field_list(state, "entries")
        self._entries = [dict(ckpt.expect(entry, dict, "log entry")) for entry in entries_list]
