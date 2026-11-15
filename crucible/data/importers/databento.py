"""Databento DBN importer for futures OHLCV bars (ADR-0085).

Reads a ``.dbn`` / ``.dbn.zst`` file of ``ohlcv-1s|1m|1h`` records and writes one raw dataset per
root (``ES``, ``NQ``, ...) in ``BAR_SCHEMA``, one symbol per *individual contract*
(``ESH2014``). Nothing is guessed and nothing is silently changed:

* **Timing.** Databento stamps a bar with its *open* (``ts_event``); ``event_time`` is the bar
  *close*, ``ts_event`` plus the schema's interval, and ``available_at`` adds ``feed_latency_s``.
  Using the open as the close would hand a strategy the bar one interval early (lookahead).
* **Spreads and other products** that a ``parent`` request returns (``ESH4-ESH5`` calendar
  spreads, products outside ``roots``) are dropped and counted, never mixed into an outright series.
* **Contract names are unique.** ``ESH4`` names two different contracts, 2014 and 2024; the symbol
  carries the four-digit expiry year, resolved from the dates of the file's own symbology.
* **Prices** are the contracts' own, unadjusted (``price_basis: raw``). Continuous series are built
  from them in a separate step.

The ``databento`` package (a Rust-backed decoder) is an optional extra, imported only here
(AGENTS.md §9); ``DbnSource`` is the seam tests use to supply bars without a DBN file.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.importers.common import clamp_ohlc, ohlc_violation
from crucible.data.importers.report import DatasetOutput, ImportReport, ImportResult

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from numpy.typing import NDArray

    from crucible.data.importers.spec import DatabentoSpec

_NS_PER_S = 1_000_000_000
_PRICE_SCALE = 1e9
_UNDEF_PRICE = np.iinfo(np.int64).max
"""DBN's marker for "no price" (``i64::MAX``): such a bar is incomplete and is dropped, counted."""

_INTERVAL_NS = {"ohlcv-1s": _NS_PER_S, "ohlcv-1m": 60 * _NS_PER_S, "ohlcv-1h": 3600 * _NS_PER_S}
"""The schemas this importer understands. ``ohlcv-1d`` is refused: Databento's daily bar is stamped
at the UTC day start and its "close" is not an exchange session close."""

_MONTH_CODES = "FGHJKMNQUVXZ"
_PRICES = ("open", "high", "low", "close")
_CHUNK = 2_000_000
_HASH_BLOCK = 1 << 20


class DbnSource(Protocol):
    """What the importer needs from a DBN file (the seam for tests)."""

    @property
    def dataset(self) -> str:
        """The DBN dataset code (``GLBX.MDP3``)."""
        ...

    @property
    def schema(self) -> str:
        """The DBN schema (``ohlcv-1m``)."""
        ...

    @property
    def mappings(self) -> Mapping[str, Sequence[Mapping[str, object]]]:
        """Raw symbol -> intervals ``{start_date, end_date, symbol}`` where ``symbol`` is the
        instrument id as text (DBN's own symbology section)."""
        ...

    def chunks(self, count: int) -> Iterator[NDArray[np.void]]:
        """Records in file order, ``count`` at a time, as a structured array with the fields
        ``instrument_id, ts_event, open, high, low, close, volume`` (fixed-point prices, 1e-9)."""
        ...


class _DatabentoSource:
    """The real adapter over ``databento.DBNStore`` (optional extra)."""

    def __init__(self, path: Path) -> None:
        try:
            import databento as db
        except ImportError:
            msg = (
                "importing a Databento DBN file needs the optional 'databento' package: run "
                "`uv sync --extra databento` (or `uv pip install databento`)"
            )
            raise ConfigurationError(msg) from None
        self._store = db.DBNStore.from_file(path)
        meta = self._store.metadata
        self._dataset = str(meta.dataset)
        self._schema = str(meta.schema)
        self._mappings: Mapping[str, Sequence[Mapping[str, object]]] = meta.mappings

    @property
    def dataset(self) -> str:
        return self._dataset

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def mappings(self) -> Mapping[str, Sequence[Mapping[str, object]]]:
        return self._mappings

    def chunks(self, count: int) -> Iterator[NDArray[np.void]]:
        yield from self._store.to_ndarray(count=count)


def _open(path: Path) -> DbnSource:
    return _DatabentoSource(path)


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, streamed (the input can be hundreds of megabytes)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class _Contracts:
    """The file's symbology as date intervals. Databento **reuses instrument ids over time** (an id
    can be a spread in one period and an outright in another), so an id means nothing without the
    date: ``table`` has one row per ``(instrument id, [start, end))`` with the contract ``symbol``
    and ``root`` (null for a spread or another product); ``names`` are the outright contracts."""

    table: pl.DataFrame
    names: frozenset[str]


def _expiry_year(digit: int, start_date: dt.date) -> int:
    """The year ending in ``digit`` that is on or after ``start_date.year`` and closest to it.

    A contract never expires before it is listed and none lives ten years, so the first listing
    date fixes the decade: ``ESH4`` first seen 2013-12 is 2014, first seen 2023-09 is 2024, and
    ``YMU7`` first seen 2026-09 is 2027. The *end* date cannot be used: a contract still trading
    when the download ended has its interval cut there (``YMU7`` ends 2026-11-11, before its
    2027 expiry)."""
    year = start_date.year
    return year + ((digit - year) % 10)


def _day_ns(day: dt.date) -> int:
    """00:00 UTC of ``day`` in nanoseconds (DBN symbology dates are UTC; ``end`` is exclusive)."""
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS_PER_S


def _contracts(source: DbnSource, roots: tuple[str, ...]) -> _Contracts:
    """Resolves the file's symbology into dated outright-contract intervals of ``roots``."""
    by_root = "|".join(sorted((re.escape(r) for r in roots), key=len, reverse=True))
    outright = re.compile(rf"^({by_root})([{_MONTH_CODES}])(\d)$")
    rows: list[tuple[int, int, int, str | None, str | None]] = []
    owner: dict[str, int] = {}
    for raw_symbol, intervals in source.mappings.items():
        match = outright.match(raw_symbol)
        for interval in intervals:
            instrument_id = int(str(interval["symbol"]))
            begin, end = interval["start_date"], interval["end_date"]
            if not isinstance(begin, dt.date) or not isinstance(end, dt.date):
                msg = f"symbology interval of {raw_symbol} has no start/end date: {interval}"
                raise ConfigurationError(msg)
            if match is None:
                rows.append((instrument_id, _day_ns(begin), _day_ns(end), None, None))
                continue
            root, month, digit = match.group(1), match.group(2), int(match.group(3))
            name = f"{root}{month}{_expiry_year(digit, begin)}"
            if owner.setdefault(name, instrument_id) != instrument_id:
                msg = (
                    f"contract {name} is claimed by instrument ids {owner[name]} and "
                    f"{instrument_id}; the year inferred from the symbology dates is ambiguous. "
                    "Inspect the file"
                )
                raise ConfigurationError(msg)
            rows.append((instrument_id, _day_ns(begin), _day_ns(end), name, root))
    table = pl.DataFrame(
        rows,
        schema={
            "instrument_id": pl.Int64,
            "start_ns": pl.Int64,
            "end_ns": pl.Int64,
            "symbol": pl.String,
            "root": pl.String,
        },
        orient="row",
    )
    return _Contracts(table, frozenset(owner))


def _chunk_frame(chunk: NDArray[np.void], interval_ns: int, latency_ns: int) -> pl.DataFrame:
    """One DBN chunk as a frame: ``event_time`` is the bar close, prices are decimal floats, and
    ``priced`` is false where any price is DBN's "undefined" marker.

    The fixed-point to float division is done here, in numpy, on purpose: Polars evaluates a
    division by a constant as a multiplication by its reciprocal, which is not correctly rounded
    (998.75 came out as 998.7500000000001); numpy's IEEE division gives the nearest double.
    """
    raw = {name: chunk[name].astype(np.int64) for name in _PRICES}
    priced = np.logical_and.reduce([values != _UNDEF_PRICE for values in raw.values()])
    return pl.DataFrame(
        {
            "instrument_id": chunk["instrument_id"].astype(np.int64),
            "event_time": chunk["ts_event"].astype(np.int64) + interval_ns,
            "priced": priced,
            **{
                name: np.where(priced, values, 0).astype(np.float64) / _PRICE_SCALE
                for name, values in raw.items()
            },
            "volume": chunk["volume"].astype(np.float64),
        }
    ).with_columns(available_at=pl.col("event_time") + latency_ns)


def import_databento(spec: DatabentoSpec, *, source: DbnSource | None = None) -> ImportResult:
    """Reads the spec's DBN file into one raw bar dataset per root.

    ``source`` replaces the file reader (tests). Drops and repairs are counted in the report and
    bounded by ``rows.max_dropped_fraction``; instrument ids outside ``roots`` or that are spreads
    count as ``other_instrument`` rows (expected: a ``parent`` request returns spreads).
    """
    path = Path(spec.input)
    sha = "not-checked"
    if source is None:
        if not path.is_file():
            msg = f"databento input {spec.input!r} does not exist"
            raise ConfigurationError(msg)
        if spec.expected_sha256 is not None:
            sha = file_sha256(path)
            if sha != spec.expected_sha256:
                msg = (
                    f"{spec.input} has sha256 {sha}, the spec expects {spec.expected_sha256}: the "
                    "file is not the one the provider delivered (truncated or modified). "
                    "Download it again, or fix expected_sha256 if the spec is wrong"
                )
                raise ConfigurationError(msg)
        source = _open(path)
    interval_ns = _INTERVAL_NS.get(source.schema)
    if interval_ns is None:
        msg = (
            f"databento schema {source.schema!r} is not supported; this importer reads "
            f"{', '.join(sorted(_INTERVAL_NS))} (a bar's close is open + the schema's interval)"
        )
        raise ConfigurationError(msg)
    roots = tuple(r.upper() for r in spec.roots)
    contracts = _contracts(source, roots)
    if not contracts.names:
        msg = (
            f"no outright contract of {list(roots)} in the file's symbology "
            f"({len(source.mappings)} symbols); check roots against the file's symbols"
        )
        raise ConfigurationError(msg)
    latency_ns = spec.feed_latency_s * _NS_PER_S
    per_root: dict[str, list[pl.DataFrame]] = {root: [] for root in roots}
    rows_read = other_rows = undefined = 0
    for chunk in source.chunks(_CHUNK):
        rows_read += len(chunk)
        frame = _chunk_frame(chunk, interval_ns, latency_ns)
        # an id is only meaningful on a date: keep the interval that contains the bar's open
        keyed = (
            frame.with_row_index("row")
            .join(contracts.table, on="instrument_id", how="inner")
            .filter(
                (pl.col("event_time") - interval_ns >= pl.col("start_ns"))
                & (pl.col("event_time") - interval_ns < pl.col("end_ns"))
            )
        )
        if keyed["row"].n_unique() != keyed.height:
            clash = keyed.filter(pl.col("row").is_duplicated()).row(0, named=True)
            msg = (
                f"instrument id {clash['instrument_id']} has overlapping symbology intervals at "
                f"ts {clash['event_time'] - interval_ns}; the file is inconsistent, re-download it"
            )
            raise ConfigurationError(msg)
        joined = keyed.filter(pl.col("symbol").is_not_null())
        other_rows += frame.height - joined.height
        bars = joined.filter(pl.col("priced"))
        undefined += joined.height - bars.height
        for (root,), part in bars.partition_by("root", as_dict=True, include_key=True).items():
            per_root[str(root)].append(part.select(list(BAR_SCHEMA)))
    if rows_read == 0:
        msg = f"{spec.input!r} holds no records"
        raise ConfigurationError(msg)

    dropped: dict[str, int] = {}
    if other_rows:
        dropped["other_instrument"] = other_rows
    if undefined:
        dropped["undefined_price"] = undefined
    repaired: dict[str, int] = {}
    outputs: list[DatasetOutput] = []
    rows_written: dict[str, int] = {}
    violations = 0
    for root in roots:
        if not per_root[root]:
            msg = (
                f"root {root} has no bars in {spec.input!r}; remove it from roots or check the file"
            )
            raise ConfigurationError(msg)
        frame = pl.concat(per_root[root]).sort(BAR_SORT_KEYS)
        n_bad = frame.filter(ohlc_violation()).height
        if n_bad and spec.rows.ohlc_repair == "clamp":
            violations += n_bad
            frame = clamp_ohlc(frame, ohlc_violation())
        name = spec.dataset.format(root=root.lower())
        rows_written[name] = frame.height
        outputs.append(
            DatasetOutput(
                dataset=name,
                frame=frame.select(list(BAR_SCHEMA)),
                schema=BAR_SCHEMA,
                sort_keys=BAR_SORT_KEYS,
                check_bars=True,
                calendar=spec.quality_calendar,
                quality_skip=spec.quality_skip,
                quality_skip_reason=spec.quality_skip_reason,
            )
        )
    if violations:
        repaired["ohlc_clamped"] = violations
    report = ImportReport(
        kind=spec.kind,
        dataset=spec.dataset,
        price_basis=spec.price_basis,
        files=1,
        rows_read=rows_read,
        rows_written=rows_written,
        dropped=dropped,
        repaired=repaired,
        extra={
            "contracts": len(contracts.names),
            "dbn_dataset": source.dataset,
            "dbn_schema": source.schema,
            "input_sha256": sha,
        },
    )
    # dropped spreads are expected from a `parent` request; they do not count against the limit
    unexpected = sum(v for k, v in dropped.items() if k != "other_instrument") + sum(
        repaired.values()
    )
    if rows_read and unexpected / rows_read > spec.rows.max_dropped_fraction:
        msg = (
            f"{unexpected} dropped and repaired rows out of {rows_read} exceed "
            f"max_dropped_fraction={spec.rows.max_dropped_fraction}; inspect the source "
            f"(dropped={dropped}, repaired={repaired}) or raise the limit knowingly"
        )
        raise ConfigurationError(msg)
    return ImportResult(datasets=tuple(outputs), report=report)
