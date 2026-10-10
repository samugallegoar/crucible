"""Generic OHLCV CSV importer (ADR-0052).

Files matched by the spec's glob are read in sorted order and mapped to
``BAR_SCHEMA``. Nothing is guessed: timestamps use the declared format and zone,
an ambiguous local time refuses, and every dropped or repaired row is counted.
"""

from __future__ import annotations

import datetime as dt
import glob
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.importers.common import clamp_ohlc, ohlc_violation, session_close_table
from crucible.data.importers.report import DatasetOutput, ImportReport, ImportResult

if TYPE_CHECKING:
    from crucible.data.importers.spec import OhlcvSpec

_NS_PER_S = 1_000_000_000
_PRICE_COLUMNS = ("open", "high", "low", "close")


def _blank_to_null(column: str) -> pl.Expr:
    stripped = pl.col(column).str.strip_chars()
    return pl.when(stripped.str.len_chars() == 0).then(None).otherwise(stripped)


def _read_file(path: str, spec: OhlcvSpec) -> pl.DataFrame:
    try:
        raw = pl.read_csv(path, separator=spec.delimiter, infer_schema=False)
    except (pl.exceptions.PolarsError, OSError) as exc:
        msg = f"cannot read {path} as CSV with delimiter {spec.delimiter!r}: {exc}"
        raise ConfigurationError(msg) from exc
    cols = spec.columns
    needed = [cols.timestamp, cols.open, cols.high, cols.low, cols.close]
    if cols.volume is not None:
        needed.append(cols.volume)
    if spec.symbol.column is not None:
        needed.append(spec.symbol.column)
    missing = [name for name in needed if name not in raw.columns]
    if missing:
        msg = f"{path}: missing column(s) {missing}; the file has {raw.columns}"
        raise ConfigurationError(msg)
    if spec.symbol.column is not None:
        symbol = _blank_to_null(spec.symbol.column).str.to_uppercase()
    elif spec.symbol.from_filename:
        symbol = pl.lit(Path(path).stem.upper())
    else:
        symbol = pl.lit((spec.symbol.fixed or "").upper())
    volume = _blank_to_null(cols.volume) if cols.volume is not None else pl.lit(None, pl.String)
    return raw.select(
        symbol=symbol,
        ts=_blank_to_null(cols.timestamp),
        open=_blank_to_null(cols.open),
        high=_blank_to_null(cols.high),
        low=_blank_to_null(cols.low),
        close=_blank_to_null(cols.close),
        volume=volume,
    )


def _numbers(frame: pl.DataFrame) -> pl.DataFrame:
    """Casts price/volume text to float; text that is present but not a number refuses."""
    for column in (*_PRICE_COLUMNS, "volume"):
        parsed = pl.col(column).cast(pl.Float64, strict=False)
        bad = frame.filter(pl.col(column).is_not_null() & parsed.is_null())
        if bad.height:
            msg = f"unparsable number in column {column!r}, e.g. {bad[column][0]!r}"
            raise ConfigurationError(msg)
        frame = frame.with_columns(
            pl.when(parsed.is_finite()).then(parsed).otherwise(None).alias(column)
        )
    return frame


def _timestamps(frame: pl.DataFrame, spec: OhlcvSpec) -> pl.DataFrame:
    """Adds ``local`` (naive) and ``utc`` (aware UTC) datetimes from the declared format/zone."""
    naive = pl.col("ts").str.to_datetime(format=spec.timestamp.format, strict=False)
    frame = frame.with_columns(local=naive)
    bad = frame.filter(pl.col("ts").is_not_null() & pl.col("local").is_null())
    if bad.height:
        msg = (
            f"unparsable timestamp {bad['ts'][0]!r}; the declared format is "
            f"{spec.timestamp.format!r}"
        )
        raise ConfigurationError(msg)
    try:
        return frame.with_columns(
            utc=pl.col("local")
            .dt.replace_time_zone(spec.timestamp.timezone, ambiguous="raise", non_existent="raise")
            .dt.convert_time_zone("UTC")
        )
    except pl.exceptions.PolarsError as exc:
        msg = (
            f"an ambiguous or non-existent local time in zone {spec.timestamp.timezone!r} "
            f"(daylight-saving change): {exc}. Export the file in UTC or a zone without DST"
        )
        raise ConfigurationError(msg) from exc


def _session_close_ns(frame: pl.DataFrame, spec: OhlcvSpec) -> pl.DataFrame:
    dates = frame["local"].dt.date().drop_nulls()
    if dates.len() == 0:
        return frame.with_columns(event_time=pl.lit(None, pl.Int64))
    first, last = dates.min(), dates.max()
    assert isinstance(first, dt.date)
    assert isinstance(last, dt.date)
    table = session_close_table(first, last, spec.timestamp.calendar or "")
    return (
        frame.with_columns(day=pl.col("local").dt.date())
        .join(table, on="day", how="left")
        .rename({"close_ns": "event_time"})
        .drop("day")
    )


def import_ohlcv(spec: OhlcvSpec) -> ImportResult:
    """Reads the spec's files into a bar frame.

    ``event_time`` is the bar close in UTC ns (knowable only once the bar has closed);
    ``available_at`` adds ``feed_latency_s``. Rows are never silently changed: drops
    and repairs are counted and bounded by ``rows.max_dropped_fraction``.
    """
    files = sorted(glob.glob(spec.input))
    if not files:
        msg = f"input glob {spec.input!r} matched no files"
        raise ConfigurationError(msg)
    frame = pl.concat([_read_file(path, spec) for path in files], how="vertical")
    rows_read = frame.height
    if rows_read == 0:
        msg = f"{spec.input!r} matched {len(files)} file(s) with no data rows (only headers?)"
        raise ConfigurationError(msg)
    dropped: dict[str, int] = {}
    repaired: dict[str, int] = {}

    frame = _numbers(frame)
    negative = frame.filter(pl.col("volume") < 0)
    if negative.height:
        msg = (
            f"{negative.height} row(s) with negative volume, e.g. {negative['volume'][0]!r} for "
            f"{negative['symbol'][0]!r}; volume cannot be negative, fix the source"
        )
        raise ConfigurationError(msg)
    frame = _timestamps(frame, spec)

    incomplete = pl.any_horizontal(
        pl.col("local").is_null(),
        pl.col("symbol").is_null(),
        *[pl.col(c).is_null() for c in _PRICE_COLUMNS],
    )
    n_incomplete = frame.filter(incomplete).height
    if n_incomplete:
        if spec.rows.on_incomplete == "refuse":
            example = frame.filter(incomplete).row(0, named=True)
            msg = (
                f"{n_incomplete} incomplete row(s) (missing timestamp, symbol or price), "
                f"e.g. {example}"
            )
            raise ConfigurationError(msg)
        dropped["incomplete"] = n_incomplete
        frame = frame.filter(~incomplete)

    meaning = spec.timestamp.meaning
    if meaning == "bar_open":
        interval = spec.timestamp.interval or ""
        # Calendar units (d, w, mo) are added in the file's zone so a daylight-saving day is
        # 23 or 25 hours long; converting to UTC first would close the bar an hour early.
        frame = frame.with_columns(
            event_time=pl.col("local")
            .dt.replace_time_zone(spec.timestamp.timezone)
            .dt.offset_by(interval)
            .dt.convert_time_zone("UTC")
            .dt.epoch("ns")
        )
    elif meaning == "bar_close":
        frame = frame.with_columns(event_time=pl.col("utc").dt.epoch("ns"))
    else:
        frame = _session_close_ns(frame, spec)
        n_missing = frame.filter(pl.col("event_time").is_null()).height
        if n_missing:
            dropped["not_a_session"] = n_missing
            frame = frame.filter(pl.col("event_time").is_not_null())

    blank_volume = 0
    n_blank_volume = frame.filter(pl.col("volume").is_null()).height
    if n_blank_volume and spec.columns.volume is not None:  # no volume column means zero by design
        blank_volume = n_blank_volume
    frame = frame.with_columns(
        volume=pl.col("volume").fill_null(0.0),
        available_at=pl.col("event_time") + spec.feed_latency_s * _NS_PER_S,
    )

    violation = ohlc_violation()
    n_violations = frame.filter(violation).height
    if n_violations and spec.rows.ohlc_repair == "clamp":
        repaired["ohlc_clamped"] = n_violations
        frame = clamp_ohlc(frame, violation)

    out = frame.select(list(BAR_SCHEMA))
    report = ImportReport(
        kind=spec.kind,
        dataset=spec.dataset,
        price_basis=spec.price_basis,
        files=len(files),
        rows_read=rows_read,
        rows_written={spec.dataset: out.height},
        dropped=dropped,
        repaired=repaired,
        extra={"symbols": out["symbol"].n_unique(), "volume_zeroed": blank_volume},
    )
    if report.problem_fraction() > spec.rows.max_dropped_fraction:
        msg = (
            f"{sum(dropped.values())} dropped and {sum(repaired.values())} repaired rows out of "
            f"{rows_read} exceed max_dropped_fraction={spec.rows.max_dropped_fraction}; inspect "
            f"the source (dropped={dropped}, repaired={repaired}) or raise the limit knowingly"
        )
        raise ConfigurationError(msg)
    calendar = spec.timestamp.calendar or spec.quality_calendar
    return ImportResult(
        datasets=(
            DatasetOutput(
                dataset=spec.dataset,
                frame=out,
                schema=BAR_SCHEMA,
                sort_keys=BAR_SORT_KEYS,
                check_bars=True,
                calendar=calendar,
                quality_skip=spec.quality_skip,
                quality_skip_reason=spec.quality_skip_reason,
            ),
        ),
        report=report,
    )
