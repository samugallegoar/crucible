"""Continuous futures series from raw per-contract bars (ADR-0086).

One rule, three outputs with the same timestamps:

* **unadjusted** -- each bar is the held contract's own bar (real traded prices, a ``contract``
  column); it jumps at every roll. The only series fills and money are computed on.
* **ratio-adjusted** -- every bar before a roll is multiplied by ``next / front`` taken at the last
  minute both contracts traded on the session before the switch, compounded backwards. Percent
  returns inside a contract are preserved and prices stay positive. Its *levels* depend on later
  rolls, so it is safe only for scale-invariant use (ADR-0086, decision 8).
* **rolls** -- one row per switch.

The roll rule is causal: the contract held on trade date ``d`` is a function of sessions before
``d`` and of the contracts' scheduled last trading session. Hold one contract; on ``d`` look only at
its successor in the quarterly chain; switch when the successor's volume on ``d-1`` exceeds
``threshold`` times the held contract's, or when the held contract is within ``backstop_sessions``
sessions of its last session (never hold a contract into its final session); never switch back.
The switch is effective from the first bar of ``d`` (the evening session opens an hour after
``d-1`` closes, so the decision is known before the first bar it governs).

Trade date: taken from the CME session calendar (``cme_sessions``, ADR-0091), never from a clock
rule: a bar belongs to the trade date whose scheduled segment holds it, and an off-schedule print
(the minute after a close) to the last session that opened before it. The 17:00 rule of ADR-0087
was wrong before 2012-11-19 (the session opened at 15:30) and on the Friday sessions booked to a
Monday trade date (ADR-0092). Bars outside the calendar's coverage are refused, or dropped and
counted when the caller asks for ``trim_to_calendar``.

Expiry: a contract's scheduled last trading session is taken as its last observed bar's trade
date (the exchange publishes it in advance; the specification, not the price, fixes it). An
approximation, exact for liquid contracts; a specification table replaces it later.

Nothing here reads the clock or a random generator; the result is a pure function of the raw bars
and the parameters.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import (
    SessionCalendar,
    coverage_span,
    session_trade_dates,
    table_summary,
)
from crucible.data.contracts import (
    BAR_SCHEMA,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    END_AT_OPEN,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.quality import run_quality_checks
from crucible.data.store import ParquetDataStore, build_dataset

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.data.interfaces import DatasetManifest

_NS_PER_S = 1_000_000_000
_MONTH_CODES = "FGHJKMNQUVXZ"
_PRICES = ("open", "high", "low", "close")
DATASET_VERSION = "v3"
"""Suffix of the continuous dataset ids; bumped when the builder's output changes (ADR-0087,
ADR-0092)."""


@dataclass(frozen=True, slots=True)
class RollParams:
    """The rule's parameters; they go in every output dataset's manifest ``source``."""

    threshold: float = 1.0
    """The successor must exceed ``threshold`` x the held contract's previous-session volume."""
    backstop_sessions: int = 1
    """Never hold a contract into its last ``backstop_sessions`` sessions' final one: 1 excludes the
    final session, 2 also the one before; 0 disables the backstop."""
    bar_seconds: int = 60
    """Bar length: ``event_time`` is the close, so the open is ``event_time - bar_seconds``."""
    chain_months: int = 3
    """Months between a contract and its successor (3: quarterly)."""
    max_reference_lookback: int = 5
    """Sessions to look back for a minute both contracts traded in, before refusing."""

    def __post_init__(self) -> None:
        if not self.threshold > 0:
            msg = f"threshold must be > 0, got {self.threshold}"
            raise ConfigurationError(msg)
        if self.backstop_sessions < 0:
            msg = f"backstop_sessions must be >= 0 (0 disables it), got {self.backstop_sessions}"
            raise ConfigurationError(msg)
        if self.bar_seconds < 1 or self.chain_months < 1 or self.max_reference_lookback < 1:
            msg = "bar_seconds, chain_months and max_reference_lookback must be >= 1"
            raise ConfigurationError(msg)

    def describe(self) -> str:
        """The parameters as ``key=value;...`` for a manifest ``source`` string."""
        return (
            f"rule=volume;threshold={self.threshold};backstop_sessions={self.backstop_sessions};"
            f"bar_seconds={self.bar_seconds};chain_months={self.chain_months}"
        )

    @property
    def interval_label(self) -> str:
        """``1m`` for 60 seconds, else ``<n>s``: the part of a dataset name that says the bar."""
        return (
            f"{self.bar_seconds // 60}m" if self.bar_seconds % 60 == 0 else f"{self.bar_seconds}s"
        )


@dataclass(frozen=True, slots=True)
class ContinuousSeries:
    """The three outputs of one root, plus what a report needs."""

    root: str
    unadjusted: pl.DataFrame
    adjusted: pl.DataFrame
    rolls: pl.DataFrame
    sessions: int
    first_contract: str
    calendar: str = ""
    """``<table version>@<sha256 prefix>`` of the session calendar that assigned the trade dates."""
    trimmed_rows: int = 0
    """Raw rows dropped because they precede the calendar's coverage (``trim_to_calendar``)."""

    def summary(self) -> dict[str, object]:
        """Counts for the CLI report: rolls by reason, bars, sessions."""
        reasons = self.rolls.group_by("reason").len().sort("reason").rows()
        return {
            "root": self.root,
            "bars": self.unadjusted.height,
            "sessions": self.sessions,
            "rolls": self.rolls.height,
            "rolls_by_reason": {str(reason): int(count) for reason, count in reasons},
            "first_contract": self.first_contract,
            "calendar": self.calendar,
            "trimmed_rows": self.trimmed_rows,
        }


def calendar_for(root: str) -> SessionCalendar:
    """The CME session calendar of ``root`` (ES, NQ, YM, RTY, NKD; ADR-0091)."""
    return SessionCalendar(cme_session_table(), root.upper())


def calendar_label(calendar: SessionCalendar) -> str:
    """``<table version>@<sha256 prefix>``: what a manifest records about the calendar used."""
    summary = table_summary(calendar.table)
    return f"{summary['version']}@{str(summary['sha256'])[:16]}"


def trade_dates(event_time: pl.Series, calendar: SessionCalendar, bar_seconds: int) -> pl.Series:
    """The Globex trade date (``pl.Date``) of each bar from its close ``event_time`` (UTC ns), in
    the input order (see the module docstring)."""
    unique = event_time.unique().sort()
    days, _ = session_trade_dates(calendar, unique.to_numpy(), bar_seconds)
    lookup = pl.DataFrame({"event_time": unique, "trade_date": pl.Series(days).cast(pl.Date)})
    out = pl.DataFrame({"event_time": event_time}).join(
        lookup, on="event_time", how="left", maintain_order="left"
    )
    return out["trade_date"]


def outside_calendar(
    event_time: pl.Series, calendar: SessionCalendar, bar_seconds: int
) -> pl.Series:
    """True for a bar (by its close) that lies outside the calendar's coverage."""
    first_open, last_close = coverage_span(calendar)
    start = event_time - bar_seconds * _NS_PER_S
    return (start < first_open) | (event_time > last_close)


def _key(symbol: str, root: str) -> int:
    """Expiry as months since year 0 (``ESH2024`` -> 2024 * 12 + 3); refuses a malformed name."""
    match = re.fullmatch(rf"{re.escape(root)}([{_MONTH_CODES}])(\d{{4}})", symbol)
    if match is None:
        msg = (
            f"symbol {symbol!r} is not a {root} contract name (<root><month code><4-digit year>, "
            "e.g. ESH2024); build the raw dataset with `kind: databento_dbn` (ADR-0085)"
        )
        raise ConfigurationError(msg)
    return int(match.group(2)) * 12 + _MONTH_CODES.index(match.group(1)) + 1


@dataclass(frozen=True, slots=True)
class _Switch:
    index: int  # session index the new contract is effective from
    front: str
    successor: str
    reason: str


def _plan(
    vol: dict[str, dict[dt.date, float]],
    last_date: dict[str, dt.date],
    keys: dict[str, int],
    dates: list[dt.date],
    params: RollParams,
) -> tuple[str, list[_Switch]]:
    """The state machine: the first contract and the switches, from sessions before each date."""
    by_key = {key: symbol for symbol, key in keys.items()}
    index = {date: i for i, date in enumerate(dates)}
    # ties go to the earliest expiry, so the choice does not depend on dict order
    ordered = sorted(vol, key=lambda s: keys[s])
    held = max(ordered, key=lambda s: vol[s].get(dates[0], 0.0))
    first = held
    switches: list[_Switch] = []
    for i in range(1, len(dates)):
        successor = by_key.get(keys[held] + params.chain_months)
        if successor is None:
            continue
        prev = dates[i - 1]
        succ_volume = vol[successor].get(prev, 0.0)
        led = succ_volume > 0 and succ_volume > params.threshold * vol[held].get(prev, 0.0)
        final = index[last_date[held]]
        # a contract still printing bars on the dataset's last session has no observed expiry (the
        # download simply ended): its "last session" is not a vencimiento, so no backstop applies
        live = final == len(dates) - 1
        backstop = (
            params.backstop_sessions > 0 and not live and final - i <= params.backstop_sessions - 1
        )
        expired = i > final
        if led:
            reason = "volume"
        elif backstop:
            reason = "backstop"
        elif expired:
            reason = "expired"
        else:
            continue
        switches.append(_Switch(i, held, successor, reason))
        held = successor
    return first, switches


def _reference(
    by_symbol: dict[str, pl.DataFrame],
    switch: _Switch,
    dates: list[dt.date],
    params: RollParams,
    root: str,
) -> tuple[int, float, float]:
    """The last minute both contracts traded on the session before the switch (or, if they never
    shared one, on the nearest earlier session within ``max_reference_lookback``): the close time,
    the old contract's close and the new one's. Refuses when there is none."""
    for back in range(1, params.max_reference_lookback + 1):
        j = switch.index - back
        if j < 0:
            break
        day = dates[j]
        old = by_symbol[switch.front].filter(pl.col("trade_date") == day)
        new = by_symbol[switch.successor].filter(pl.col("trade_date") == day)
        both = old.join(new, on="event_time", suffix="_new")
        if both.height:
            row = both.sort("event_time").row(-1, named=True)
            return int(row["event_time"]), float(row["close"]), float(row["close_new"])
    msg = (
        f"{root}: {switch.front} and {switch.successor} never traded in the same minute in the "
        f"{params.max_reference_lookback} session(s) before {dates[switch.index]}, so the roll "
        "ratio cannot be computed. Raise max_reference_lookback, or check that both contracts "
        "are in the raw dataset"
    )
    raise DataQualityError(msg)


def build_continuous(
    raw: pl.DataFrame,
    *,
    root: str,
    params: RollParams | None = None,
    calendar: SessionCalendar | None = None,
    trimmed_rows: int = 0,
) -> ContinuousSeries:
    """The continuous series of ``root`` from its raw per-contract bars (``BAR_SCHEMA``).

    Refuses a raw frame with no rows, a symbol that is not a ``root`` contract, a chain with a hole
    (a held contract past its last session with no successor), and a roll whose contracts never
    shared a traded minute, and bars outside the session calendar's coverage: each says what is
    wrong and how to fix it. ``calendar`` defaults to the CME table of ``root``; ``trimmed_rows``
    is recorded only (``build_continuous_datasets`` drops them).
    """
    params = params or RollParams()
    calendar = calendar or calendar_for(root)
    missing = [column for column in BAR_SCHEMA if column not in raw.columns]
    if missing:
        msg = f"raw bars for {root} lack columns {missing}; expected the BAR_SCHEMA columns"
        raise DataQualityError(msg)
    if raw.height == 0:
        msg = f"raw bars for {root} are empty; nothing to build a continuous series from"
        raise DataQualityError(msg)
    outside = int(outside_calendar(raw["event_time"], calendar, params.bar_seconds).sum())
    if outside:
        msg = (
            f"{root}: {outside} raw bars lie outside the CME session calendar "
            f"{calendar.table.version} coverage [{calendar.first}, {calendar.last}], so their "
            "trade dates are unknown. Source the missing schedule (ADR-0091), or build with "
            "trim_to_calendar (CLI --trim-to-calendar) to drop and count them"
        )
        raise DataQualityError(msg)
    frame = raw.select(list(BAR_SCHEMA))
    frame = frame.with_columns(
        trade_date=trade_dates(frame["event_time"], calendar, params.bar_seconds)
    )
    symbols = sorted(frame["symbol"].unique().to_list())
    keys = {symbol: _key(symbol, root) for symbol in symbols}
    by_symbol = {
        str(key[0]): part.sort("event_time")
        for key, part in frame.partition_by("symbol", as_dict=True, include_key=True).items()
    }
    vol: dict[str, dict[dt.date, float]] = {symbol: {} for symbol in symbols}
    for symbol, day, volume in (
        frame.group_by(["symbol", "trade_date"]).agg(volume=pl.col("volume").sum()).iter_rows()
    ):
        vol[symbol][day] = volume
    last_date = {symbol: max(days) for symbol, days in vol.items()}
    dates = sorted({day for days in vol.values() for day in days})

    first, switches = _plan(vol, last_date, keys, dates, params)
    final = switches[-1].successor if switches else first
    if last_date[final] < dates[-1]:
        msg = (
            f"{root}: the series holds {final} but it has no bars after {last_date[final]} and the "
            f"raw dataset runs to {dates[-1]}: {final}'s successor (expiry +{params.chain_months} "
            "months) is missing, so the series would stop. Add the missing contract to the raw "
            "dataset, or trim the dataset to end where the chain ends"
        )
        raise DataQualityError(msg)

    session_end = dict(frame.group_by("trade_date").agg(pl.col("event_time").max()).iter_rows())
    roll_rows: list[dict[str, object]] = []
    ratios: list[float] = []
    for switch in switches:
        reference_time, from_price, to_price = _reference(by_symbol, switch, dates, params, root)
        ratio = to_price / from_price
        ratios.append(ratio)
        decided_at = int(session_end[dates[switch.index - 1]])
        roll_rows.append(
            {
                "symbol": root,
                "event_time": decided_at,
                "available_at": decided_at,
                "from_contract": switch.front,
                "to_contract": switch.successor,
                "effective_trade_date": dates[switch.index].isoformat(),
                "reference_time": reference_time,
                "from_price": from_price,
                "to_price": to_price,
                "ratio": ratio,
                "gap_points": to_price - from_price,
                "reason": switch.reason,
            }
        )

    # segment k holds contract k from session starts[k] (inclusive) to starts[k + 1] (exclusive)
    starts = [0, *(switch.index for switch in switches)]
    held = [first, *(switch.successor for switch in switches)]
    factors = [1.0] * len(held)
    for k in range(len(held) - 2, -1, -1):  # bars before roll k+1 are scaled by every later ratio
        factors[k] = factors[k + 1] * ratios[k]
    plain: list[pl.DataFrame] = []
    scaled: list[pl.DataFrame] = []
    for k, symbol in enumerate(held):
        bars = by_symbol[symbol].filter(pl.col("trade_date") >= dates[starts[k]])
        if k + 1 < len(held):
            bars = bars.filter(pl.col("trade_date") < dates[starts[k + 1]])
        bars = bars.with_columns(symbol=pl.lit(root), contract=pl.lit(symbol))
        plain.append(bars)
        scaled.append(bars.with_columns(*[(pl.col(c) * factors[k]).alias(c) for c in _PRICES]))

    def finish(parts: list[pl.DataFrame]) -> pl.DataFrame:
        return (
            pl.concat(parts)
            .select(list(CONTINUOUS_BAR_SCHEMA))
            .cast(CONTINUOUS_BAR_SCHEMA)  # type: ignore[arg-type]
            .sort(CONTINUOUS_BAR_SORT_KEYS)
        )

    rolls = pl.DataFrame(roll_rows, schema=ROLL_SCHEMA)
    return ContinuousSeries(
        root=root,
        unadjusted=finish(plain),
        adjusted=finish(scaled),
        rolls=rolls.sort(ROLL_SORT_KEYS),
        sessions=len(dates),
        first_contract=first,
        calendar=calendar_label(calendar),
        trimmed_rows=trimmed_rows,
    )


def dataset_names(root: str, params: RollParams) -> tuple[str, str, str]:
    """``(unadjusted, ratio-adjusted, rolls)`` dataset ids for ``root``: ``es_1m_cont_v3`` ...

    ``v3``: trade dates come from the CME session calendar (ADR-0092); ``v2`` used the 17:00
    wall-clock rule (ADR-0087), ``v1`` a fixed ``+2 h UTC`` shift. Both are superseded."""
    stem = f"{root.lower()}_{params.interval_label}"
    version = DATASET_VERSION
    return f"{stem}_cont_{version}", f"{stem}_cont_ratio_{version}", f"{stem}_rolls_{version}"


def write_continuous(
    store_root: Path,
    series: ContinuousSeries,
    *,
    raw_dataset: str,
    raw_hash: str,
    params: RollParams,
) -> list[DatasetManifest]:
    """Checks and writes the three datasets of ``series`` under ``store_root``.

    The unadjusted dataset declares ``price_basis=raw`` and the ratio-adjusted one
    ``price_basis=adjusted`` (ADR-0071), so the engine's existing guards apply. Bar datasets go
    through the quality battery before anything is written (``calendar_coverage`` is skipped: a
    continuous 1-minute series has no bar for a minute nothing traded).
    """
    unadjusted, adjusted, rolls = dataset_names(series.root, params)
    origin = (
        f"root={series.root};from={raw_dataset}@{raw_hash[:16]};{params.describe()};"
        f"calendar={series.calendar};trimmed_rows={series.trimmed_rows}"
    )
    reason = "continuous minute bars: calendar_coverage is a daily-session check"
    for frame in (series.unadjusted, series.adjusted):
        run_quality_checks(
            frame.lazy(), None, skip=frozenset({"calendar_coverage"}), skip_reason=reason
        )
    return [
        build_dataset(
            store_root,
            DatasetId(unadjusted),
            series.unadjusted,
            schema=CONTINUOUS_BAR_SCHEMA,
            sort_keys=CONTINUOUS_BAR_SORT_KEYS,
            source=f"continuous:{DATASET_VERSION};price_basis=raw;adjustment=none;{origin}",
        ),
        build_dataset(
            store_root,
            DatasetId(adjusted),
            series.adjusted,
            schema=CONTINUOUS_BAR_SCHEMA,
            sort_keys=CONTINUOUS_BAR_SORT_KEYS,
            source=f"continuous:{DATASET_VERSION};price_basis=adjusted;adjustment=ratio;{origin}",
        ),
        build_dataset(
            store_root,
            DatasetId(rolls),
            series.rolls,
            schema=ROLL_SCHEMA,
            sort_keys=ROLL_SORT_KEYS,
            source=f"continuous:{DATASET_VERSION};rolls;{origin}",
        ),
    ]


def build_continuous_datasets(
    store_root: Path,
    root: str,
    *,
    raw_dataset: str,
    params: RollParams | None = None,
    trim_to_calendar: bool = False,
) -> tuple[ContinuousSeries, list[DatasetManifest]]:
    """Reads ``raw_dataset`` from the store, builds ``root``'s continuous series and writes it.

    ``trim_to_calendar`` drops the raw bars outside the CME session calendar's coverage (NKD
    before 2012-11-19) instead of refusing; the count goes in the manifests (ADR-0092)."""
    params = params or RollParams()
    store = ParquetDataStore(store_root)
    raw = store.read(DatasetId(raw_dataset), TimestampNs(END_AT_OPEN)).collect()
    calendar = calendar_for(root)
    trimmed = 0
    if trim_to_calendar:
        keep = ~outside_calendar(raw["event_time"], calendar, params.bar_seconds)
        trimmed = raw.height - int(keep.sum())
        raw = raw.filter(keep)
    series = build_continuous(
        raw, root=root.upper(), params=params, calendar=calendar, trimmed_rows=trimmed
    )
    manifests = write_continuous(
        store_root,
        series,
        raw_dataset=raw_dataset,
        raw_hash=store.manifest(DatasetId(raw_dataset)).content_hash,
        params=params,
    )
    return series, manifests
