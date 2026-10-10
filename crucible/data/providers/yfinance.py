"""yfinance adapter (ADR-0063): UNOFFICIAL, may break or be rate-limited without notice.

yfinance scrapes Yahoo Finance. It needs no key but Yahoo can change its pages, block a client or
throttle at any time, so a failure here is not necessarily a bug in Crucible. The package is an
optional extra (``uv sync --extra yfinance``); without it this provider refuses with that command.

Facts (yfinance source, verified 2026-10-07): ``Ticker.history(start, end, interval, auto_adjust)``
takes ``start`` inclusive and ``end`` **exclusive**; the index is tz-aware in the exchange's time
zone, a daily bar stamped midnight local and an intraday bar at its start; intraday history is
limited (about 60 days). Yahoo's unadjusted ``Close`` is already **split-adjusted**, so a true raw
series does not exist here: only ``price_basis="adjusted"`` (``auto_adjust=True``, splits and
dividends) is offered, and ``raw`` is refused rather than mislabelled (AGENTS.md section 9).

The adapter never imports pandas: it reads the returned frame through ``index`` and column access.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING, Any

import polars as pl

from crucible.data.providers.base import BarsProvider, ProviderInfo
from crucible.data.providers.errors import (
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from crucible.data.providers.http import RetryPolicy, backoff_delay
from crucible.data.providers.normalize import parse_interval

if TYPE_CHECKING:
    from collections.abc import Callable

    from crucible.data.providers.settings import ProviderSettings

_PROGRAMMING_ERRORS = (TypeError, AttributeError, KeyError, ValueError, ImportError)

_UNOFFICIAL = (
    "yfinance is unofficial: it scrapes Yahoo Finance, so it can break, return gaps or be "
    "rate-limited without notice"
)


class YFinanceProvider(BarsProvider):
    info = ProviderInfo(
        name="yfinance",
        needs_key=False,
        env_var=None,
        intervals=("5m", "15m", "30m", "1h", "1d"),
        price_bases=("adjusted",),
        official=False,
        empty_hint=(
            "The ticker may be wrong or delisted, the range may be outside what Yahoo keeps "
            "(intraday is limited to about 60 days), or Yahoo may be rate-limiting this client "
            f"({_UNOFFICIAL}); try again later or use tiingo."
        ),
        notes=(
            f"{_UNOFFICIAL}. Yahoo's Close is already split-adjusted, so only adjusted prices "
            "(splits and dividends) are offered; use tiingo for raw prices. Intraday history "
            "is limited to roughly the last 60 days."
        ),
    )

    def __init__(
        self,
        *,
        history: Callable[..., Any] | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._history = history if history is not None else _default_history()
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep

    def _fetch_raw(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> pl.DataFrame:
        ticker = symbol.upper()
        frame = self._call(ticker, start=start, end=end + dt.timedelta(days=1), interval=interval)
        if frame is None or frame.empty:
            return _empty(interval)
        _, unit = parse_interval(interval)
        intraday = unit in {"m", "h"}
        stamps = [_stamp(ts, intraday=intraday) for ts in frame.index]
        local_days = [_local_date(ts) for ts in frame.index]
        columns = {
            name: [None if v is None else float(v) for v in frame[source].tolist()]
            for name, source in (
                ("open", "Open"),
                ("high", "High"),
                ("low", "Low"),
                ("close", "Close"),
                ("volume", "Volume"),
            )
        }
        out = {"ts": stamps, "in_range": [start <= d <= end for d in local_days]} | columns
        return pl.DataFrame(out, schema=_schema(intraday))

    def _call(self, ticker: str, *, start: dt.date, end: dt.date, interval: str) -> Any:
        """The history call with bounded retry on Yahoo's rate limit and on network failures."""
        last = ""
        limited = False
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                return self._history(
                    ticker, start=start, end=end, interval=interval, auto_adjust=True
                )
            except _PROGRAMMING_ERRORS as exc:
                msg = (
                    f"yfinance ({ticker}): the package failed with {type(exc).__name__}, which "
                    "points at a version mismatch rather than the network, so it is not retried. "
                    f"Try `uv sync --extra yfinance --upgrade-package yfinance`; {_UNOFFICIAL}"
                )
                raise ProviderError(msg) from None
            except Exception as exc:  # yfinance raises its own and requests' exception types
                name = type(exc).__name__
                limited = "RateLimit" in name or "TooManyRequests" in name
                last = name
            if attempt < self._retry.max_attempts:
                self._sleep(backoff_delay(self._retry, attempt))
        if limited:
            msg = (
                f"yfinance ({ticker}): Yahoo rate-limited the request on all "
                f"{self._retry.max_attempts} attempts. {_UNOFFICIAL}. Wait a few minutes and run "
                "the fetch again (cached symbols are kept), or fetch fewer symbols at a time"
            )
            raise ProviderRateLimitError(msg)
        msg = (
            f"yfinance ({ticker}): the request failed after {self._retry.max_attempts} attempts "
            f"({last}). Check your internet connection; {_UNOFFICIAL}"
        )
        raise ProviderNetworkError(msg)


def _stamp(ts: Any, *, intraday: bool) -> dt.date | dt.datetime:
    """A pandas Timestamp (or datetime) index entry: the **local** date for a daily bar, the UTC
    start instant for an intraday one."""
    moment = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if intraday:
        if moment.tzinfo is None:
            msg = "yfinance returned a naive intraday timestamp; its time zone is unknown"
            raise ProviderError(msg)
        return moment.astimezone(dt.UTC)  # type: ignore[no-any-return]
    return dt.date(moment.year, moment.month, moment.day)


def _local_date(ts: Any) -> dt.date:
    """The exchange-local calendar date of an index entry (what ``--start``/``--end`` mean)."""
    moment = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    return dt.date(moment.year, moment.month, moment.day)


def _schema(intraday: bool) -> dict[str, Any]:
    return {
        "ts": pl.Datetime("us", "UTC") if intraday else pl.Date,
        "in_range": pl.Boolean,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
    }


def _empty(interval: str) -> pl.DataFrame:
    _, unit = parse_interval(interval)
    return pl.DataFrame(schema=_schema(unit in {"m", "h"}))


def _default_history() -> Callable[..., Any]:
    try:
        import yfinance
    except ImportError:
        msg = (
            "the yfinance package is not installed; install it with `uv sync --extra yfinance` "
            "(it is optional so the core install stays small), or choose another provider with "
            "--provider tiingo"
        )
        raise ProviderUnavailableError(msg) from None

    def history(symbol: str, **kwargs: Any) -> Any:
        return yfinance.Ticker(symbol).history(actions=False, **kwargs)

    return history


def build(settings: ProviderSettings, **kwargs: Any) -> YFinanceProvider:
    """Registry factory: no key needed; the package is checked here so a missing install fails
    before any request."""
    return YFinanceProvider(**kwargs)
