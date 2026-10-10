"""Tiingo end-of-day adapter (ADR-0063), over stdlib ``urllib``.

Endpoint (Tiingo documentation, verified 2026-10-07):
``GET https://api.tiingo.com/tiingo/daily/<ticker>/prices?startDate&endDate&format=json&resampleFreq=daily``
with the header ``Authorization: Token <key>``. Each row carries ``date`` and the raw
``open high low close volume`` and the adjusted ``adjOpen adjHigh adjLow adjClose adjVolume``;
``price_basis`` picks the set. The key travels in a header only: never in the URL, an error
message, a cache key or a report.

Only daily bars are offered. Tiingo's IEX intraday endpoint does not document whether its
timestamps are a bar's start or end, or their time zone; guessing would risk look-ahead, so it is
not offered until that is confirmed. Free tier (Tiingo pricing page): 50 requests/hour, 1,000
requests/day, 500 unique symbols/month, 1 GB/month; those limits surface as rate-limit errors.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
from typing import TYPE_CHECKING, Any

import polars as pl

from crucible.data.providers.base import BarsProvider, ProviderInfo
from crucible.data.providers.errors import ProviderError
from crucible.data.providers.http import RetryPolicy, get_with_retry, urllib_transport

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from crucible.data.providers.http import HttpResponse
    from crucible.data.providers.settings import ApiKey, ProviderSettings

BASE_URL = "https://api.tiingo.com"
KEY_ENV = "TIINGO_API_KEY"

_FIELDS: dict[str, tuple[str, str, str, str, str]] = {
    "raw": ("open", "high", "low", "close", "volume"),
    "adjusted": ("adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume"),
}


class TiingoProvider(BarsProvider):
    info = ProviderInfo(
        name="tiingo",
        needs_key=True,
        env_var=KEY_ENV,
        intervals=("1d",),
        price_bases=("adjusted", "raw"),
        official=True,
        empty_hint=(
            "Check the ticker spelling and that your Tiingo account covers that date range."
        ),
        notes=(
            "Daily bars only; free account limits: 50 requests/hour, 1,000/day, 500 unique "
            "symbols/month."
        ),
    )

    def __init__(
        self,
        api_key: ApiKey,
        *,
        transport: Callable[[str, Mapping[str, str]], HttpResponse] | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key
        self._transport = transport if transport is not None else urllib_transport()
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep
        self._base_url = base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"TiingoProvider(calendar={self.calendar!r}, key=****)"

    def _fetch_raw(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
        interval: str,
        price_basis: str,
    ) -> pl.DataFrame:
        ticker = urllib.parse.quote(symbol.upper(), safe="")
        query = urllib.parse.urlencode(
            {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "format": "json",
                "resampleFreq": "daily",
            }
        )
        url = f"{self._base_url}/tiingo/daily/{ticker}/prices?{query}"
        headers = {
            "Authorization": f"Token {self._api_key.reveal()}",
            "Content-Type": "application/json",
            "User-Agent": "crucible-data-fetch",
        }
        response = get_with_retry(
            self._transport,
            url,
            headers,
            provider="tiingo",
            symbol=symbol.upper(),
            policy=self._retry,
            sleep=self._sleep,
        )
        return _parse(response.body, symbol.upper(), price_basis, start, end)


def _parse(
    body: bytes, symbol: str, price_basis: str, start: dt.date, end: dt.date
) -> pl.DataFrame:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        msg = (
            f"tiingo ({symbol}): the answer is not JSON (the service may be down or "
            "changed); try again later"
        )
        raise ProviderError(msg) from None
    if not isinstance(payload, list):
        detail = payload.get("detail") if isinstance(payload, dict) else None
        msg = (
            f"tiingo ({symbol}): unexpected answer "
            f"({'detail: ' + str(detail) if detail else type(payload).__name__}); the request "
            "was not accepted or the API changed"
        )
        raise ProviderError(msg)
    fields = _FIELDS[price_basis]
    columns: dict[str, list[Any]] = {
        name: [] for name in ("ts", "open", "high", "low", "close", "volume", "in_range")
    }
    for row in payload:
        missing = [
            name for name in ("date", *fields) if not isinstance(row, dict) or name not in row
        ]
        if missing:
            msg = (
                f"tiingo ({symbol}): a row lacks the field(s) {missing} that price_basis "
                f"{price_basis!r} needs; the API may have changed"
            )
            raise ProviderError(msg)
        day = dt.date.fromisoformat(str(row["date"])[:10])
        columns["ts"].append(day)
        columns["in_range"].append(start <= day <= end)
        for target, source in zip(("open", "high", "low", "close", "volume"), fields, strict=True):
            columns[target].append(row[source])
    return pl.DataFrame(
        columns,
        schema={
            "ts": pl.Date,
            "in_range": pl.Boolean,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def build(settings: ProviderSettings, **kwargs: Any) -> TiingoProvider:
    """Registry factory: needs ``TIINGO_API_KEY`` (a missing key explains how to get one)."""
    return TiingoProvider(settings.api_key(KEY_ENV, provider="tiingo"), **kwargs)
