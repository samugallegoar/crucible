"""The raw-response cache: closed ranges are cached, ranges touching today are not (ADR-0063)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from crucible.data.providers.cache import CacheKey, RawCache

TODAY = dt.date(2024, 6, 15)


def _raw(close: float = 10.5) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [dt.date(2024, 1, 2)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [close],
            "volume": [100.0],
        },
        schema={
            "ts": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def _key(**over: object) -> CacheKey:
    base = {
        "provider": "tiingo",
        "adapter_version": 1,
        "symbol": "AAPL",
        "interval": "1d",
        "start": dt.date(2024, 1, 1),
        "end": dt.date(2024, 3, 31),
        "price_basis": "adjusted",
    }
    base.update(over)
    return CacheKey(**base)  # type: ignore[arg-type]


class _Counter:
    def __init__(self, frame: pl.DataFrame | None = None) -> None:
        self.calls = 0
        self._frame = frame if frame is not None else _raw()

    def __call__(self) -> pl.DataFrame:
        self.calls += 1
        return self._frame


def test_a_closed_range_is_fetched_once_then_served_from_disk(tmp_path: Path) -> None:
    cache = RawCache(tmp_path, today=lambda: TODAY)
    fetch = _Counter()
    first = cache.get_or_fetch(_key(), fetch)
    second = cache.get_or_fetch(_key(), fetch)
    assert fetch.calls == 1
    assert first.equals(second)
    assert len(list((tmp_path / "tiingo").glob("*.parquet"))) == 1


def test_every_request_field_is_part_of_the_key() -> None:
    base = _key()
    variants = [
        _key(provider="yfinance"),
        _key(adapter_version=2),
        _key(symbol="MSFT"),
        _key(interval="5m"),
        _key(start=dt.date(2024, 1, 2)),
        _key(end=dt.date(2024, 3, 30)),
        _key(price_basis="raw"),
    ]
    digests = {base.digest()} | {v.digest() for v in variants}
    assert len(digests) == 1 + len(variants)


def test_a_range_touching_today_is_never_cached(tmp_path: Path) -> None:
    cache = RawCache(tmp_path, today=lambda: TODAY)
    fetch = _Counter()
    key = _key(end=TODAY)
    cache.get_or_fetch(key, fetch)
    cache.get_or_fetch(key, fetch)
    assert fetch.calls == 2
    assert not (tmp_path / "tiingo").exists()


def test_refresh_bypasses_the_read_but_updates_the_file(tmp_path: Path) -> None:
    fetch_old, fetch_new = _Counter(_raw(10.5)), _Counter(_raw(12.0))
    RawCache(tmp_path, today=lambda: TODAY).get_or_fetch(_key(), fetch_old)
    refreshing = RawCache(tmp_path, today=lambda: TODAY, refresh=True)
    assert refreshing.get_or_fetch(_key(), fetch_new)["close"][0] == 12.0
    assert fetch_new.calls == 1
    after = RawCache(tmp_path, today=lambda: TODAY).get_or_fetch(_key(), fetch_old)
    assert after["close"][0] == 12.0


def test_an_empty_answer_is_not_cached(tmp_path: Path) -> None:
    cache = RawCache(tmp_path, today=lambda: TODAY)
    fetch = _Counter(_raw().clear())
    cache.get_or_fetch(_key(), fetch)
    cache.get_or_fetch(_key(), fetch)
    assert fetch.calls == 2


def test_a_corrupt_cache_file_is_refetched(tmp_path: Path) -> None:
    cache = RawCache(tmp_path, today=lambda: TODAY)
    fetch = _Counter()
    cache.get_or_fetch(_key(), fetch)
    (path,) = (tmp_path / "tiingo").glob("*.parquet")
    path.write_bytes(b"not parquet")
    assert cache.get_or_fetch(_key(), fetch).height == 1
    assert fetch.calls == 2


def test_a_disabled_cache_always_fetches_and_writes_nothing(tmp_path: Path) -> None:
    cache = RawCache(None, today=lambda: TODAY)
    fetch = _Counter()
    cache.get_or_fetch(_key(), fetch)
    cache.get_or_fetch(_key(), fetch)
    assert fetch.calls == 2
    assert list(tmp_path.iterdir()) == []


def test_yesterdays_range_is_not_cached_because_the_provider_may_not_have_published_it(
    tmp_path: Path,
) -> None:
    cache = RawCache(tmp_path, today=lambda: TODAY)
    fetch = _Counter()
    key = _key(end=TODAY - dt.timedelta(days=1))
    cache.get_or_fetch(key, fetch)
    cache.get_or_fetch(key, fetch)
    assert fetch.calls == 2
    older = _key(end=TODAY - dt.timedelta(days=2))
    cache.get_or_fetch(older, fetch)
    cache.get_or_fetch(older, fetch)
    assert fetch.calls == 3
