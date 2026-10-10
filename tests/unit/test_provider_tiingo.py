"""The Tiingo adapter against a mocked transport (ADR-0063). No network.

Request and response shapes follow Tiingo's end-of-day documentation (verified 2026-10-07):
``GET /tiingo/daily/<ticker>/prices?startDate&endDate&format=json&resampleFreq=daily`` with the
header ``Authorization: Token <key>``; each row has ``date`` and the raw ``open high low close
volume`` plus the adjusted ``adjOpen adjHigh adjLow adjClose adjVolume``, ``divCash`` and
``splitFactor``.

Hand numbers: a 2-for-1 split makes every adjusted price half the raw one, so the raw close 101.0
is the adjusted close 50.5 (Jan 2) and 103.0 is 51.5 (Jan 3).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA
from crucible.data.providers import registry
from crucible.data.providers.cache import RawCache
from crucible.data.providers.errors import (
    EmptyDataError,
    MissingApiKeyError,
    ProviderAuthError,
    ProviderError,
    UnknownSymbolError,
)
from crucible.data.providers.http import HttpResponse, RetryPolicy
from crucible.data.providers.settings import ApiKey, ProviderSettings
from crucible.data.providers.tiingo import TiingoProvider

SECRET = "tk_live_0123456789abcdef"
ROWS = [
    {
        "date": "2024-01-02T00:00:00.000Z",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1000,
        "adjOpen": 50.0,
        "adjHigh": 51.0,
        "adjLow": 49.5,
        "adjClose": 50.5,
        "adjVolume": 2000,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
    {
        "date": "2024-01-03T00:00:00.000Z",
        "open": 101.0,
        "high": 104.0,
        "low": 100.0,
        "close": 103.0,
        "volume": 1200,
        "adjOpen": 50.5,
        "adjHigh": 52.0,
        "adjLow": 50.0,
        "adjClose": 51.5,
        "adjVolume": 2400,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
]


class _Transport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        self.calls.append((url, headers))
        return self.response


def _json(rows: object, status: int = 200) -> _Transport:
    return _Transport(HttpResponse(status, {}, json.dumps(rows).encode("utf-8")))


def _provider(transport: _Transport, **kwargs: object) -> TiingoProvider:
    return TiingoProvider(
        ApiKey(SECRET),
        transport=transport,
        retry=RetryPolicy(max_attempts=2, base_delay_s=0.0, max_delay_s=0.0),
        sleep=lambda _s: None,
        **kwargs,  # type: ignore[arg-type]
    )


ARGS = ("aapl", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d")


def test_adjusted_bars_use_the_adj_columns_and_close_at_the_session_close() -> None:
    frame = _provider(_json(ROWS)).get_prices(*ARGS, "adjusted")
    assert frame.schema == pl.Schema(BAR_SCHEMA)
    assert frame["symbol"].to_list() == ["AAPL", "AAPL"]
    assert frame["close"].to_list() == [50.5, 51.5]
    assert frame["open"].to_list() == [50.0, 50.5]
    assert frame["volume"].to_list() == [2000.0, 2400.0]
    # 2024-01-02 and 2024-01-03 NYSE sessions close at 21:00 UTC
    assert frame["event_time"].to_list() == [1704229200 * 10**9, 1704315600 * 10**9]


def test_raw_bars_use_the_unadjusted_columns() -> None:
    frame = _provider(_json(ROWS)).get_prices(*ARGS, "raw")
    assert frame["close"].to_list() == [101.0, 103.0]
    assert frame["volume"].to_list() == [1000.0, 1200.0]


def test_the_request_is_the_documented_one_and_the_key_is_in_a_header_only() -> None:
    transport = _json(ROWS)
    _provider(transport).get_prices(*ARGS, "adjusted")
    ((url, headers),) = transport.calls
    assert url.startswith("https://api.tiingo.com/tiingo/daily/AAPL/prices?")
    assert "startDate=2024-01-01" in url
    assert "endDate=2024-01-31" in url
    assert "format=json" in url
    assert "resampleFreq=daily" in url
    assert SECRET not in url
    assert headers["Authorization"] == f"Token {SECRET}"


def test_rows_outside_the_requested_range_are_ignored() -> None:
    frame = _provider(_json(ROWS)).get_prices(
        "X", dt.date(2024, 1, 3), dt.date(2024, 1, 3), "1d", "raw"
    )
    assert frame["close"].to_list() == [103.0]


def test_tiingo_offers_daily_bars_only_and_says_why() -> None:
    with pytest.raises(ConfigurationError, match=r"interval '5m'.*1d"):
        _provider(_json(ROWS)).get_prices(
            "X", dt.date(2024, 1, 1), dt.date(2024, 1, 2), "5m", "raw"
        )


def test_an_empty_answer_is_an_empty_data_error() -> None:
    with pytest.raises(EmptyDataError, match="AAPL"):
        _provider(_json([])).get_prices(*ARGS, "adjusted")


def test_a_rejected_key_is_an_auth_error_that_does_not_show_the_key() -> None:
    with pytest.raises(ProviderAuthError) as excinfo:
        _provider(_Transport(HttpResponse(401, {}, b'{"detail":"Invalid token."}'))).get_prices(
            *ARGS, "adjusted"
        )
    assert SECRET not in str(excinfo.value)
    assert "tiingo" in str(excinfo.value)


def test_an_unknown_ticker_is_an_unknown_symbol_error() -> None:
    with pytest.raises(UnknownSymbolError, match="AAPL"):
        _provider(_Transport(HttpResponse(404, {}, b""))).get_prices(*ARGS, "adjusted")


def test_a_body_that_is_not_the_documented_list_is_a_provider_error() -> None:
    for body in (b"<html>maintenance</html>", b'{"detail": "Error: something odd"}'):
        with pytest.raises(ProviderError, match="tiingo") as excinfo:
            _provider(_Transport(HttpResponse(200, {}, body))).get_prices(*ARGS, "adjusted")
        assert SECRET not in str(excinfo.value)


def test_a_row_without_the_expected_fields_is_named() -> None:
    broken = [{k: v for k, v in ROWS[0].items() if k != "adjClose"}]
    with pytest.raises(ProviderError, match="adjClose"):
        _provider(_json(broken)).get_prices(*ARGS, "adjusted")


def test_the_registry_builds_tiingo_from_settings_and_a_missing_key_explains_itself(
    tmp_path: Path,
) -> None:
    settings = ProviderSettings.load(environ={"TIINGO_API_KEY": SECRET}, dotenv_path=tmp_path / "x")
    provider = registry.build_provider("tiingo", settings, calendar="XNYS", transport=_json(ROWS))
    assert provider.info.name == "tiingo"
    empty = ProviderSettings.load(environ={}, dotenv_path=tmp_path / "x")
    with pytest.raises(MissingApiKeyError, match=r"TIINGO_API_KEY.*tiingo\.com"):
        registry.build_provider("tiingo", empty, calendar="XNYS")


def test_the_key_never_reaches_the_cache_or_the_provider_repr(tmp_path: Path) -> None:
    cache = RawCache(tmp_path, today=lambda: dt.date(2024, 6, 15))
    provider = _provider(_json(ROWS), cache=cache)
    provider.get_prices(*ARGS, "adjusted")
    for path in tmp_path.rglob("*"):
        assert SECRET not in path.name
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
    assert SECRET not in repr(provider)
    assert SECRET not in repr(vars(provider))


def test_the_info_states_the_free_tier_limits_and_both_price_bases() -> None:
    info = TiingoProvider.info
    assert info.needs_key
    assert info.env_var == "TIINGO_API_KEY"
    assert set(info.price_bases) == {"adjusted", "raw"}
    assert info.intervals == ("1d",)
    assert info.official
