"""Provider registry and the base class every adapter derives from (ADR-0063)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA
from crucible.data.providers import registry
from crucible.data.providers.base import BarsProvider, ProviderInfo
from crucible.data.providers.cache import RawCache
from crucible.data.providers.settings import ProviderSettings


class _Fake(BarsProvider):
    info = ProviderInfo(
        name="fake",
        needs_key=False,
        env_var=None,
        intervals=("1d",),
        price_bases=("adjusted",),
        official=True,
        notes="test double",
    )

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.calls: list[tuple[str, dt.date, dt.date, str, str]] = []

    def _fetch_raw(
        self, symbol: str, start: dt.date, end: dt.date, interval: str, price_basis: str
    ) -> pl.DataFrame:
        self.calls.append((symbol, start, end, interval, price_basis))
        return pl.DataFrame(
            {
                "ts": [dt.date(2024, 1, 2)],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
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


@pytest.fixture
def fake_registered() -> Iterator[None]:
    registry.register("fake", lambda settings, **kwargs: _Fake(**kwargs))
    yield
    registry.unregister("fake")


def test_get_prices_returns_bar_schema(fake_registered: None) -> None:
    provider = registry.build_provider("fake", ProviderSettings.load(environ={}), calendar="XNYS")
    frame = provider.get_prices("aapl", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted")
    assert frame.schema == pl.Schema(BAR_SCHEMA)
    assert frame["symbol"].to_list() == ["AAPL"]


def test_an_unsupported_interval_or_basis_is_refused_with_the_supported_ones(
    fake_registered: None,
) -> None:
    provider = registry.build_provider("fake", ProviderSettings.load(environ={}), calendar="XNYS")
    with pytest.raises(ConfigurationError, match=r"interval '5m'.*1d"):
        provider.get_prices("X", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "5m", "adjusted")
    with pytest.raises(ConfigurationError, match=r"price_basis 'raw'.*adjusted"):
        provider.get_prices("X", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "raw")


def test_an_end_before_the_start_is_refused(fake_registered: None) -> None:
    provider = registry.build_provider("fake", ProviderSettings.load(environ={}), calendar="XNYS")
    with pytest.raises(ConfigurationError, match="start"):
        provider.get_prices("X", dt.date(2024, 2, 1), dt.date(2024, 1, 1), "1d", "adjusted")


def test_an_unknown_provider_lists_the_known_ones(fake_registered: None) -> None:
    with pytest.raises(ConfigurationError, match=r"'nope'.*fake"):
        registry.build_provider("nope", ProviderSettings.load(environ={}), calendar="XNYS")


def test_fetch_bars_reports_what_was_dropped(fake_registered: None) -> None:
    provider = registry.build_provider("fake", ProviderSettings.load(environ={}), calendar="XNYS")
    fetched = provider.fetch_bars("X", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted")
    assert fetched.frame.height == 1
    assert fetched.dropped == {}
    assert fetched.repaired == {}


def test_a_closed_range_is_fetched_once_through_the_cache(
    fake_registered: None, tmp_path: Path
) -> None:
    cache = RawCache(tmp_path, today=lambda: dt.date(2024, 6, 15))
    provider = registry.build_provider(
        "fake", ProviderSettings.load(environ={}), calendar="XNYS", cache=cache
    )
    args = ("X", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted")
    first = provider.get_prices(*args)
    second = provider.get_prices(*args)
    assert first.equals(second)
    assert len(provider.calls) == 1  # type: ignore[attr-defined]


def test_a_range_touching_today_is_fetched_every_time(
    fake_registered: None, tmp_path: Path
) -> None:
    cache = RawCache(tmp_path, today=lambda: dt.date(2024, 1, 31))
    provider = registry.build_provider(
        "fake", ProviderSettings.load(environ={}), calendar="XNYS", cache=cache
    )
    args = ("X", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted")
    provider.get_prices(*args)
    provider.get_prices(*args)
    assert len(provider.calls) == 2  # type: ignore[attr-defined]
