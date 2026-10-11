"""Makes sure the bars a one-step backtest needs are in the store (ADR-0068).

One dataset per (provider, symbols, window, interval, price basis, calendar). The calendar is part
of the identity because it changes the data: it decides each daily bar's ``event_time`` (the
session close) and which days are kept, so the same request under XNYS and 24/7 is two datasets
(ADR-0071). The name is derived from those inputs, so asking for the same thing twice reuses the
stored dataset and is offline and byte-for-byte the same data, while a different window is a
different dataset (a strategy then sees exactly the bars of its window and never pre-window history
it would not have had at the start).

A name match is not trusted on its own: ``request.json`` beside the dataset records the effective
request (every input above, the OHLC repair mode and the identity version), and a stored dataset is
reused only when that record matches the request. A dataset without a matching record is fetched
again (or refused offline). When a fetch replaces a stored dataset, the previous version is moved to
``<home>/archive/<dataset>/<content hash>/`` first, so a provider's later revision never silently
erases the data an earlier run used.

This module is an I/O boundary: it may read the wall clock (to refuse an ``end`` in the future)
and the network (through the provider). Nothing after it does.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.types import DatasetId
from crucible.data.calendars import ALWAYS_OPEN, canonical_calendar
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
IDENTITY_VERSION = 2
"""Version of the dataset identity (name + ``request.json``). 1: names without a calendar and no
request record (before ADR-0071); such datasets are never reused, the request is fetched again."""
OHLC_REPAIR = "clamp_rounding"
REQUEST_RECORD = "request.json"


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
    calendar: str = "XNYS"
    replaced_content_hash: str | None = None
    """Content hash of the stored version this fetch replaced (archived), if any."""


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
    provider: str,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
    interval: str,
    basis: str,
    calendar: str = "XNYS",
) -> str:
    """Deterministic name of the dataset for a request; the calendar enters in canonical form
    (``canonical_calendar``), so equivalent spellings share one name (ADR-0071)."""
    joined = "-".join(
        s.lower().replace(".", "_").replace("^", "_").replace("=", "_") for s in symbols
    )
    if len(joined) > 60:
        import hashlib

        joined = hashlib.sha256(",".join(symbols).encode()).hexdigest()[:16]
    cal = canonical_calendar(calendar)
    cal_token = "247" if cal == ALWAYS_OPEN else cal.lower()
    return f"px_{provider}_{joined}_{start:%Y%m%d}_{end:%Y%m%d}_{interval}_{basis[:3]}_{cal_token}"


def dataset_request(
    provider: str,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
    interval: str,
    basis: str,
    calendar: str = "XNYS",
) -> dict[str, object]:
    """The effective request a dataset was built for, as recorded in ``request.json``."""
    return {
        "identity_version": IDENTITY_VERSION,
        "provider": provider,
        "symbols": sorted(symbols),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "interval": interval,
        "price_basis": basis,
        "calendar": canonical_calendar(calendar),
        "ohlc_repair": OHLC_REPAIR,
    }


def write_request_record(dataset_dir: Path, request: dict[str, object]) -> None:
    """Writes ``request.json`` beside a dataset (deterministic bytes)."""
    (dataset_dir / REQUEST_RECORD).write_text(
        json.dumps(request, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def read_request_record(dataset_dir: Path) -> dict[str, object] | None:
    """The recorded request, or None when there is none (or it cannot be read)."""
    try:
        loaded = json.loads((dataset_dir / REQUEST_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


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
    calendar = canonical_calendar(calendar)
    name = dataset_name(name_of_provider, symbols, start, end, interval, price_basis, calendar)
    expected = dataset_request(
        name_of_provider, symbols, start, end, interval, price_basis, calendar
    )
    store = ParquetDataStore(home.data)
    try:
        manifest = store.manifest(DatasetId(name))
    except CrucibleError:
        manifest = None
    recorded = read_request_record(home.data / name) if manifest is not None else None
    compatible = recorded == expected
    if manifest is not None and compatible and not refresh:
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
            calendar=calendar,
            **_report_details(home.data / name),
        )
    if offline:
        if manifest is not None and not compatible:
            msg = (
                f"the stored dataset {name} was not built for this exact request (its "
                f"{REQUEST_RECORD} is missing or differs: calendar, interval, price basis or an "
                "older Crucible), and offline mode is on, so it cannot be fetched again. Run once "
                "without --offline to rebuild it"
            )
            raise ConfigurationError(msg)
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
        ohlc_repair=OHLC_REPAIR,
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
    replaced = _archive_previous(home, name, manifest)
    manifest = write_import_result(result, home.data)[0]
    write_request_record(home.data / name, expected)
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
        calendar=calendar,
        replaced_content_hash=replaced,
        **_report_details(home.data / name),
    )


def _archive_previous(home: Home, name: str, manifest: object) -> str | None:
    """Moves a stored dataset that a fetch is about to replace to
    ``<home>/archive/<name>/<content hash>/`` and returns that hash (ADR-0071)."""
    if manifest is None:
        return None
    content_hash = str(getattr(manifest, "content_hash", "unknown"))
    source = home.data / name
    target = home.root / "archive" / name / content_hash
    if target.exists():
        shutil.rmtree(source)  # the identical bytes are already archived
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    return content_hash


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
