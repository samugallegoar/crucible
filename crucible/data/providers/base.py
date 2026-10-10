"""The provider interface and the base class every adapter derives from (ADR-0063).

``PriceProvider.get_prices`` is the whole contract the rest of the app sees: it returns bars in
``BAR_SCHEMA`` whatever the provider. An adapter only implements ``_fetch_raw`` (talk to the
provider, return the provider-neutral raw frame of ``normalize.py``); the base class validates the
request, applies the shared normalization and (later) the raw-response cache.
"""

from __future__ import annotations

import datetime as dt
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from crucible.core.errors import ConfigurationError
from crucible.data.providers.cache import CacheKey, RawCache
from crucible.data.providers.errors import EmptyDataError
from crucible.data.providers.normalize import Normalized, normalize_raw, parse_interval

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

PriceBasis = Literal["adjusted", "raw"]


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """What a provider offers: shown by ``crucible data fetch --help`` and the docs."""

    name: str
    needs_key: bool
    env_var: str | None
    intervals: tuple[str, ...]
    price_bases: tuple[str, ...]
    official: bool
    notes: str
    empty_hint: str = ""
    """Why an empty answer usually happens at this provider (shown in the error)."""
    version: int = 1
    """Bump when the adapter's output for the same request changes: it is part of the cache key."""


@dataclass(frozen=True, slots=True)
class FetchedBars:
    """Normalized bars plus what the normalization dropped or repaired (for the import report)."""

    frame: pl.DataFrame
    dropped: dict[str, int]
    repaired: dict[str, int]


class PriceProvider(Protocol):
    """Anything that can supply normalized bars. The rest of the app depends only on this."""

    info: ProviderInfo

    def get_prices(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> pl.DataFrame:
        """Bars of ``symbol`` over ``[start, end]`` (inclusive dates) in ``BAR_SCHEMA``: UTC ns,
        ``event_time`` = bar close, sorted, prices in the requested ``price_basis``."""
        ...

    def fetch_bars(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> FetchedBars:
        """Like :meth:`get_prices`, plus the counts the import report needs."""
        ...


class BarsProvider(ABC):
    """Shared behaviour of every adapter: validate, fetch raw, normalize."""

    info: ProviderInfo

    def __init__(
        self,
        *,
        calendar: str = "XNYS",
        feed_latency_s: int = 0,
        ohlc_repair: Literal["refuse", "clamp"] = "refuse",
        cache: RawCache | None = None,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.calendar = calendar
        self.feed_latency_s = feed_latency_s
        self.ohlc_repair = ohlc_repair
        self.cache = cache if cache is not None else RawCache(None)
        self._now_ns = now_ns  # the wall clock, read here at the I/O boundary only

    @abstractmethod
    def _fetch_raw(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> pl.DataFrame:
        """Ask the provider; return the raw frame described in ``normalize.py``."""

    def _validate(self, start: dt.date, end: dt.date, interval: str, price_basis: str) -> None:
        if end < start:
            msg = f"start {start} is after end {end}; give a range that ends on or after its start"
            raise ConfigurationError(msg)
        parse_interval(interval)
        if interval not in self.info.intervals:
            msg = (
                f"{self.info.name} does not offer interval {interval!r}; it offers: "
                f"{', '.join(self.info.intervals)}"
            )
            raise ConfigurationError(msg)
        if price_basis not in self.info.price_bases:
            msg = (
                f"{self.info.name} does not offer price_basis {price_basis!r}; it offers: "
                f"{', '.join(self.info.price_bases)}. {self.info.notes}"
            )
            raise ConfigurationError(msg)

    def fetch_bars(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> FetchedBars:
        self._validate(start, end, interval, price_basis)
        key = CacheKey(
            self.info.name,
            self.info.version,
            symbol,
            interval,
            start,
            end,
            price_basis,
        )
        raw = self.cache.get_or_fetch(
            key, lambda: self._fetch_raw(symbol, start, end, interval, price_basis)
        )
        if raw.height == 0:
            msg = (
                f"{self.info.name} returned no {interval} rows for {symbol.upper()} between "
                f"{start} and {end}. {self.info.empty_hint}"
            )
            raise EmptyDataError(msg)
        normalized: Normalized = normalize_raw(
            raw,
            symbol=symbol,
            interval=interval,
            calendar=self.calendar,
            feed_latency_s=self.feed_latency_s,
            ohlc_repair=self.ohlc_repair,
            now_ns=self._now_ns(),
        )
        return FetchedBars(normalized.frame, normalized.dropped, normalized.repaired)

    def get_prices(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> pl.DataFrame:
        return self.fetch_bars(symbol, start, end, interval, price_basis).frame
