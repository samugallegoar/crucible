"""Fetch several symbols from a provider into one dataset (ADR-0063).

``fetch_dataset`` turns a provider's per-symbol bars into an ``ImportResult`` that
``importers.build.write_import_result`` checks (quality battery, size guard) and writes, exactly
like ``data build``. A run never calls a provider; this is the only place that does, and it runs
upstream of the store.

Failure policy: a symbol with no data, an unknown ticker or a network failure is collected and the
fetch continues; at the end it refuses (nothing is written) unless ``allow_partial`` is set, and
the message lists every failed symbol with its reason. A rejected key or a rate limit stops at
once, since every later symbol would fail the same way (symbols already fetched stay in the cache).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.importers.report import DatasetOutput, ImportReport, ImportResult
from crucible.data.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.data.providers.base import PriceProvider

_TOLERANCE = dt.timedelta(days=7)
"""A first bar later than this after ``start``, or a last bar earlier than this before ``end``, is
reported (a weekend or holiday run-in is not)."""


def fetch_dataset(
    provider: PriceProvider,
    *,
    symbols: Sequence[str],
    start: dt.date,
    end: dt.date,
    interval: str,
    price_basis: str,
    dataset: str,
    calendar: str,
    allow_partial: bool = False,
) -> ImportResult:
    """Bars of every symbol over ``[start, end]`` as one dataset, with a report that records the
    provider, the price basis and any symbol whose first bar is later than ``start``."""
    names = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not names:
        msg = "no symbols given; pass at least one ticker, e.g. --symbols AAPL,MSFT"
        raise ConfigurationError(msg)
    frames: list[pl.DataFrame] = []
    dropped: dict[str, int] = {}
    repaired: dict[str, int] = {}
    failed: dict[str, str] = {}
    for symbol in names:
        try:
            fetched = provider.fetch_bars(symbol, start, end, interval, price_basis)
        except (ProviderAuthError, ProviderRateLimitError):
            raise
        except ProviderError as exc:
            failed[symbol] = str(exc)
            continue
        frames.append(fetched.frame)
        for counts, extra in ((dropped, fetched.dropped), (repaired, fetched.repaired)):
            for reason, n in extra.items():
                counts[reason] = counts.get(reason, 0) + n
    if failed and not (allow_partial and frames):
        lines = "; ".join(f"{s}: {reason}" for s, reason in failed.items())
        msg = (
            f"{provider.info.name} could not supply {len(failed)} of {len(names)} symbol(s), so "
            f"nothing was written. {lines}. Fix or drop those symbols"
            + ("" if allow_partial else ", or pass --allow-partial to keep the rest")
        )
        raise ProviderError(msg)
    frame = pl.concat(frames).sort(BAR_SORT_KEYS)
    extra_info: dict[str, int | str] = {
        "provider": provider.info.name,
        "interval": interval,
        "symbols": ",".join(s for s in names if s not in failed),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    if failed:
        extra_info["failed_symbols"] = ",".join(failed)
    for symbol, (first, last) in _bar_date_bounds(frame).items():
        if first > start + _TOLERANCE:
            extra_info[f"late_start:{symbol}"] = first.isoformat()
        if last < end - _TOLERANCE:  # a delisting, a halted ticker or a provider that stops early
            extra_info[f"early_end:{symbol}"] = last.isoformat()
    written = frame.height
    report = ImportReport(
        kind=f"provider:{provider.info.name}",
        dataset=dataset,
        price_basis=price_basis,
        files=len(frames),
        rows_read=written + sum(dropped.values()),
        rows_written={dataset: written},
        dropped=dropped,
        repaired=repaired,
        extra=extra_info,
    )
    output = DatasetOutput(
        dataset=dataset,
        frame=frame,
        schema=dict(BAR_SCHEMA),
        sort_keys=list(BAR_SORT_KEYS),
        check_bars=True,
        calendar=calendar,
        quality_skip=(),
        quality_skip_reason="",
    )
    return ImportResult((output,), report)


def _bar_date_bounds(frame: pl.DataFrame) -> dict[str, tuple[dt.date, dt.date]]:
    bounds = frame.group_by("symbol").agg(
        pl.col("event_time").min().alias("first"), pl.col("event_time").max().alias("last")
    )

    def day(ns: object) -> dt.date:
        return dt.datetime.fromtimestamp(int(ns) / 1e9, dt.UTC).date()  # type: ignore[call-overload]

    return {
        str(row["symbol"]): (day(row["first"]), day(row["last"]))
        for row in bounds.iter_rows(named=True)
    }
