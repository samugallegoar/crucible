"""Makes sure the bars a one-step backtest needs are in the store (ADR-0068).

One dataset per (provider, symbols, window, interval, price basis). The name is derived from those
inputs, so asking for the same thing twice reuses the stored dataset and is offline and byte-for-
byte the same data, while a different window is a different dataset (a strategy then sees exactly
the bars of its window and never pre-window history it would not have had at the start).

This module is an I/O boundary: it may read the wall clock (to refuse an ``end`` in the future)
and the network (through the provider). Nothing after it does.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.types import DatasetId
from crucible.data.importers.build import write_import_result
from crucible.data.providers.cache import RawCache
from crucible.data.providers.errors import (
    ProviderNetworkError,
    ProviderRateLimitError,
)
from crucible.data.providers.fetch import fetch_dataset
from crucible.data.providers.registry import build_provider
from crucible.data.providers.settings import ProviderSettings
from crucible.data.store import ParquetDataStore

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.product.home import Home

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")
MAX_SYMBOLS = 25


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """The dataset a run reads and where it came from."""

    dataset: str
    store: str
    content_hash: str
    rows: int
    provider: str
    price_basis: str
    interval: str
    source: str
    fetched_now: bool
    repaired: dict[str, int]
    warnings: tuple[str, ...]


def normalize_symbols(symbols: str | list[str]) -> list[str]:
    """Upper-cased, de-duplicated, sorted tickers; refuses what cannot be a ticker."""
    items = symbols.replace(";", ",").split(",") if isinstance(symbols, str) else list(symbols)
    names = sorted({s.strip().upper() for s in items if s.strip()})
    if not names:
        msg = "no symbols given; pass at least one ticker, for example symbols: SPY or SPY,QQQ"
        raise ConfigurationError(msg)
    if len(names) > MAX_SYMBOLS:
        msg = (
            f"{len(names)} symbols given; one backtest takes at most {MAX_SYMBOLS}. Split them "
            "into several runs"
        )
        raise ConfigurationError(msg)
    for name in names:
        if not _SYMBOL.match(name):
            msg = (
                f"{name!r} does not look like a ticker. Use the market symbol such as SPY, AAPL "
                "or BRK-B (letters, digits and . - only)"
            )
            raise ConfigurationError(msg)
    return names


def parse_day(text: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        msg = f"{label} must be a date like 2015-01-01, got {text!r}"
        raise ConfigurationError(msg) from None


def dataset_name(
    provider: str, symbols: list[str], start: dt.date, end: dt.date, interval: str, basis: str
) -> str:
    joined = "-".join(
        s.lower().replace(".", "_").replace("^", "_").replace("=", "_") for s in symbols
    )
    if len(joined) > 60:
        import hashlib

        joined = hashlib.sha256(",".join(symbols).encode()).hexdigest()[:16]
    return f"px_{provider}_{joined}_{start:%Y%m%d}_{end:%Y%m%d}_{interval}_{basis[:3]}"


def ensure_dataset(
    home: Home,
    *,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
    provider: str | None = None,
    price_basis: str = "adjusted",
    interval: str = "1d",
    calendar: str = "XNYS",
    offline: bool = False,
    refresh: bool = False,
    today: dt.date | None = None,
) -> DatasetInfo:
    """The dataset for this request: reused if stored, fetched otherwise (never if ``offline``).

    Refuses an ``end`` that is not in the past, because a window that still has an unfinished
    session would make the same request return different data tomorrow."""
    settings = ProviderSettings.load()
    name_of_provider = provider or settings.default_provider()
    today = today or dt.datetime.now(dt.UTC).date()
    if start >= end:
        msg = f"start {start} must be before end {end}"
        raise ConfigurationError(msg)
    if end >= today:
        msg = (
            f"end {end} is not in the past (today is {today}, and today's session may not have "
            f"closed). Use an end date of {today - dt.timedelta(days=1)} or earlier, so the "
            "same request always returns the same data"
        )
        raise ConfigurationError(msg)
    name = dataset_name(name_of_provider, symbols, start, end, interval, price_basis)
    store = ParquetDataStore(home.data)
    try:
        manifest = store.manifest(DatasetId(name))
    except CrucibleError:
        manifest = None
    if manifest is not None and not refresh:
        return DatasetInfo(
            dataset=name,
            store=str(home.data),
            content_hash=manifest.content_hash,
            rows=manifest.row_count,
            provider=name_of_provider,
            price_basis=price_basis,
            interval=interval,
            source=manifest.source,
            fetched_now=False,
            **_report_details(home.data / name),
        )
    if offline:
        msg = (
            f"no stored data for {', '.join(symbols)} from {start} to {end} and offline mode is "
            "on, so nothing can be downloaded. Run once without --offline (or offline: false) "
            "while connected; later runs of the same request then work offline"
        )
        raise ConfigurationError(msg)
    cache = RawCache(home.cache, refresh=refresh)
    adapter = build_provider(
        name_of_provider,
        settings,
        calendar=calendar,
        ohlc_repair="clamp_rounding",
        cache=cache,
    )
    try:
        result = fetch_dataset(
            adapter,
            symbols=symbols,
            start=start,
            end=end,
            interval=interval,
            price_basis=price_basis,
            dataset=name,
            calendar=calendar,
        )
    except ProviderNetworkError as exc:
        msg = (
            f"{exc}. Crucible could not reach {name_of_provider}; check the internet connection "
            "and try again. If a stored dataset for this exact request exists the run works "
            "offline"
        )
        raise ProviderNetworkError(msg) from None
    except ProviderRateLimitError as exc:
        msg = (
            f"{exc}. {name_of_provider} is limiting requests; wait a few minutes and run the "
            "same request again (answers already fetched are cached and are not requested twice)"
        )
        raise ProviderRateLimitError(msg) from None
    manifest = write_import_result(result, home.data)[0]
    return DatasetInfo(
        dataset=name,
        store=str(home.data),
        content_hash=manifest.content_hash,
        rows=manifest.row_count,
        provider=name_of_provider,
        price_basis=price_basis,
        interval=interval,
        source=manifest.source,
        fetched_now=True,
        **_report_details(home.data / name),
    )


def _report_details(dataset_dir: Path) -> dict[str, Any]:
    """``repaired`` counts and ``warnings`` (a symbol that starts late or stops early) from the
    import report stored beside the dataset."""
    try:
        report = json.loads((dataset_dir / "import_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"repaired": {}, "warnings": ()}
    extra = report.get("extra", {})
    warnings = tuple(
        f"{key.split(':', 1)[-1]} has no bars "
        f"{'before' if key.startswith('late_start') else 'after'} {value}"
        for key, value in sorted(extra.items())
        if key.startswith(("late_start:", "early_end:"))
    )
    return {
        "repaired": {str(k): int(v) for k, v in report.get("repaired", {}).items()},
        "warnings": warnings,
    }
