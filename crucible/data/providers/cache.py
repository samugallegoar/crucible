"""A local cache of raw provider responses (ADR-0063).

Only a range that ended **before today** is cached: a provider's answer for closed days is stable,
and one touching today would freeze a half-finished bar. The key holds the request and the adapter
version, never a credential. This cache only saves downloads; reproducibility comes from the
dataset's content hash, not from here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class CacheKey:
    provider: str
    adapter_version: int
    symbol: str
    interval: str
    start: dt.date
    end: dt.date
    price_basis: str

    def digest(self) -> str:
        canonical = json.dumps(
            [
                self.provider,
                self.adapter_version,
                self.symbol.upper(),
                self.interval,
                self.start.isoformat(),
                self.end.isoformat(),
                self.price_basis,
            ]
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


_SETTLING = dt.timedelta(days=1)
"""A range ending yesterday is not cached either: a provider may not have published (or may still
correct) the last session's bar until the next day."""


class RawCache:
    """``root=None`` disables the cache; ``refresh=True`` ignores existing files and rewrites."""

    def __init__(
        self,
        root: Path | None,
        *,
        today: Callable[[], dt.date] = lambda: dt.datetime.now(dt.UTC).date(),
        refresh: bool = False,
    ) -> None:
        self._root = root
        self._today = today
        self._refresh = refresh

    def get_or_fetch(self, key: CacheKey, fetch: Callable[[], pl.DataFrame]) -> pl.DataFrame:
        if self._root is None or key.end >= self._today() - _SETTLING:
            return fetch()
        path = self._root / key.provider / f"{key.digest()}.parquet"
        if not self._refresh and path.is_file():
            try:
                return pl.read_parquet(path)
            except Exception:
                pass
        frame = fetch()
        if frame.height:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            os.close(descriptor)
            try:
                frame.write_parquet(name, compression="uncompressed")
                os.replace(name, path)
            finally:
                Path(name).unlink(missing_ok=True)
        return frame
