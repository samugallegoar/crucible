"""Polymarket five-minute BTC contracts -> bars, settlement and delistings (ADR-0052).

Each contract has an UP and a DOWN symbol priced by the bid/ask mid. A snapshot is
usable only after its bucket ends (``available_at == event_time == bucket end``), the
recorded winner decides settlement, and the settlement bar plus a ``DELISTING`` action
at the window end let the engine liquidate positions at the outcome. Every dropped
snapshot is counted by reason.
"""

from __future__ import annotations

import glob
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import (
    BAR_QUOTE_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
    QUOTED_BAR_SCHEMA,
)
from crucible.data.importers.report import DatasetOutput, ImportReport, ImportResult

if TYPE_CHECKING:
    from crucible.data.importers.spec import PolymarketSpec

_NS = 1_000_000_000
_MAX_SNAPSHOT_ROWS = 20_000_000
_CSV_COLUMNS = (
    "slug",
    "start_time",
    "timestamp_log",
    "ask_YES",
    "bid_YES",
    "ask_NO",
    "bid_NO",
    "btc_current",
    "winner",
)
_TICK_COLUMNS = ("event_slug", "ts", "poly_up_bid", "poly_up_ask", "poly_down_bid", "poly_down_ask")
_OUTCOME_COLUMNS = ("event_slug", "window_start_ts", "window_end_ts", "winner_side")
_SIDES = ("up", "down")
_OHLC = ["symbol", "event_time", "open", "high", "low", "close", "volume"]
_QUOTES = list(BAR_QUOTE_SCHEMA)
_BARS = _OHLC + _QUOTES


def _quote(column: str) -> pl.Expr:
    """A float quote where NaN and infinity are missing (they would pass price comparisons)."""
    value = pl.col(column).cast(pl.Float64)
    return pl.when(value.is_finite()).then(value).otherwise(None)


def _load_csv(spec: PolymarketSpec) -> tuple[pl.LazyFrame, pl.DataFrame, int, int]:
    """Snapshots (slug, ts, up/down bid/ask, spot), contracts (slug, window_start, winner),
    the number of files and of raw snapshot rows."""
    files = sorted(glob.glob(spec.input))
    if not files:
        msg = f"input glob {spec.input!r} matched no files"
        raise ConfigurationError(msg)
    frames = []
    for path in files:
        try:
            frame = pl.read_csv(path, infer_schema_length=None)
        except (pl.exceptions.PolarsError, OSError) as exc:
            msg = f"cannot read {path} as CSV: {exc}"
            raise ConfigurationError(msg) from exc
        missing = [c for c in _CSV_COLUMNS if c not in frame.columns]
        if missing:
            msg = (
                f"{path}: missing column(s) {missing}; the polymarket CSV needs "
                f"{list(_CSV_COLUMNS)} (the winner column decides settlement)"
            )
            raise ConfigurationError(msg)
        frames.append(
            frame.select(
                slug=pl.col("slug").cast(pl.String),
                window_start=pl.col("start_time").cast(pl.Int64, strict=False),
                ts=pl.col("timestamp_log").cast(pl.Float64),
                up_bid=_quote("bid_YES"),
                up_ask=_quote("ask_YES"),
                down_bid=_quote("bid_NO"),
                down_ask=_quote("ask_NO"),
                spot=_quote("btc_current"),
                winner=pl.col("winner").cast(pl.String).str.strip_chars().str.to_uppercase(),
            )
        )
    raw = pl.concat(frames, how="vertical")
    unparsable = raw.filter(pl.col("window_start").is_null())
    if unparsable.height:
        msg = (
            f"start_time is missing or not a whole number of seconds for contract "
            f"{unparsable['slug'][0]} ({unparsable.height} row(s)); it defines the window, so "
            "fix the file"
        )
        raise ConfigurationError(msg)
    contracts = raw.group_by("slug").agg(
        pl.col("window_start").first(),
        pl.col("winner").drop_nulls().first().alias("winner"),
        pl.col("window_start").n_unique().alias("n_starts"),
        pl.col("winner").drop_nulls().n_unique().alias("n_winners"),
    )
    conflict = contracts.filter((pl.col("n_starts") > 1) | (pl.col("n_winners") > 1))
    if conflict.height:
        msg = (
            f"contract {conflict['slug'][0]} has conflicting start_time or winner values across "
            f"its rows ({conflict.height} contract(s) affected); the outcome decides settlement, "
            "so fix the file"
        )
        raise ConfigurationError(msg)
    contracts = contracts.drop("n_starts", "n_winners")
    snaps = raw.drop("window_start", "winner").lazy()
    return snaps, contracts, len(files), raw.height


def _load_parquet(spec: PolymarketSpec) -> tuple[pl.LazyFrame, pl.DataFrame, int, int]:
    """Lazy ticks (never fully in memory), contracts from the outcomes table (plus unresolved
    slugs found only in the ticks), the number of files and of raw tick rows."""
    files = sorted(glob.glob(spec.input))
    if not files:
        msg = f"input glob {spec.input!r} matched no files"
        raise ConfigurationError(msg)
    outcomes_path = spec.outcomes or ""
    try:
        outcomes = pl.read_parquet(outcomes_path)
    except (pl.exceptions.PolarsError, OSError) as exc:
        msg = f"cannot read outcomes file {outcomes_path}: {exc}"
        raise ConfigurationError(msg) from exc
    missing = [c for c in _OUTCOME_COLUMNS if c not in outcomes.columns]
    if missing:
        msg = f"{outcomes_path}: missing column(s) {missing}; needs {list(_OUTCOME_COLUMNS)}"
        raise ConfigurationError(msg)
    wrong = outcomes.filter(
        (pl.col("window_end_ts") - pl.col("window_start_ts")) != spec.window_seconds
    )
    if wrong.height:
        msg = (
            f"{outcomes_path}: outcome for {wrong['event_slug'][0]} has a window of "
            f"{wrong['window_end_ts'][0] - wrong['window_start_ts'][0]} s, but the spec says "
            f"window_seconds={spec.window_seconds}; fix the spec or the file"
        )
        raise ConfigurationError(msg)
    spot_column = f"{spec.spot_source}_price"
    lazy = pl.scan_parquet(files)
    names = lazy.collect_schema().names()
    missing = [c for c in (*_TICK_COLUMNS, spot_column) if c not in names]
    if missing:
        msg = f"{files[0]}: missing column(s) {missing}; needs {[*_TICK_COLUMNS, spot_column]}"
        raise ConfigurationError(msg)
    snaps = lazy.select(
        slug=pl.col("event_slug").cast(pl.String),
        ts=pl.col("ts").cast(pl.Float64),
        up_bid=_quote("poly_up_bid"),
        up_ask=_quote("poly_up_ask"),
        down_bid=_quote("poly_down_bid"),
        down_ask=_quote("poly_down_ask"),
        spot=_quote(spot_column),
    )
    contracts = outcomes.select(
        slug=pl.col("event_slug").cast(pl.String),
        window_start=pl.col("window_start_ts").cast(pl.Int64),
        winner=pl.col("winner_side").cast(pl.String).str.strip_chars().str.to_uppercase(),
    )
    tick_slugs = snaps.select("slug").unique().collect()
    orphan = tick_slugs.join(contracts.select("slug"), on="slug", how="anti")
    if orphan.height:
        contracts = pl.concat(
            [
                contracts,
                orphan.with_columns(
                    window_start=pl.col("slug").str.extract(r"(\d+)$", 1).cast(pl.Int64),
                    winner=pl.lit(None, pl.String),
                ),
            ],
            how="vertical",
        )
    rows_read = int(snaps.select(pl.len()).collect().item())
    return snaps, contracts, len(files), rows_read


def _side_bars(kept: pl.DataFrame, side: str) -> pl.DataFrame:
    bid, ask = pl.col(f"{side}_bid"), pl.col(f"{side}_ask")
    return (
        kept.filter(bid.is_not_null() & ask.is_not_null() & (ask > 0) & (bid >= 0) & (bid <= ask))
        .with_columns(mid=(bid + ask) / 2)
        # ties on ts are broken by the quotes, so the first/last quote of a bucket does not
        # depend on the order the rows happened to be read in
        .sort(["ts", f"{side}_bid", f"{side}_ask"], maintain_order=True)
        .group_by(["window_start", "event_time"], maintain_order=True)
        .agg(
            open=pl.col("mid").first(),
            high=pl.col("mid").max(),
            low=pl.col("mid").min(),
            close=pl.col("mid").last(),
            # the first and last valid quote of the bucket (ADR-0060): the frame is sorted by ts
            bid_open=bid.first(),
            ask_open=ask.first(),
            bid_close=bid.last(),
            ask_close=ask.last(),
        )
        .with_columns(
            symbol=pl.format("BTC5M-{}-{}", pl.col("window_start"), pl.lit(side.upper())),
            volume=pl.lit(0.0),
        )
        .select(_BARS)
    )


def import_polymarket(
    spec: PolymarketSpec,
    *,
    start: int | None,
    end: int | None,
    max_contracts: int | None,
) -> ImportResult:
    """Builds contract and spot bars plus settlement bars and delisting actions.

    ``start``/``end`` (UTC ns) select contracts by window start (``end`` exclusive) and
    ``max_contracts`` keeps the earliest. A bar closes at the end of its bucket and is
    available then; a snapshot whose bucket ends at or after the window end is excluded
    because it could not be known before settlement.
    """
    snaps, contracts, n_files, rows_read = (
        _load_csv(spec) if spec.kind == "polymarket_csv" else _load_parquet(spec)
    )
    dropped: dict[str, int] = {}

    is_resolved = pl.col("winner").is_in(["UP", "DOWN"]).fill_null(False)
    resolved = contracts.filter(is_resolved)
    unresolved = contracts.filter(~is_resolved)
    if start is not None:
        resolved = resolved.filter(pl.col("window_start") >= start // _NS)
        unresolved = unresolved.filter(pl.col("window_start") >= start // _NS)
    if end is not None:
        resolved = resolved.filter(pl.col("window_start") < end // _NS)
        unresolved = unresolved.filter(pl.col("window_start") < end // _NS)
    if unresolved.height:  # only the selected window: rows outside it were never going to be read
        n_rows = snaps.join(unresolved.lazy().select("slug"), on="slug").select(pl.len())
        dropped["unresolved_contract_rows"] = int(n_rows.collect().item())
    resolved = resolved.sort(["window_start", "slug"])
    if max_contracts is not None:
        resolved = resolved.head(max_contracts)
    resolved = resolved.with_columns(window_end=pl.col("window_start") + spec.window_seconds)

    joined_lazy = snaps.join(resolved.lazy(), on="slug", how="inner")
    n_joined = int(joined_lazy.select(pl.len()).collect().item())
    if n_joined > _MAX_SNAPSHOT_ROWS:
        msg = (
            f"{n_joined} snapshots selected, above the {_MAX_SNAPSHOT_ROWS} the importer holds "
            "in memory; select a window with --start/--end or --max-contracts"
        )
        raise ConfigurationError(msg)
    joined = joined_lazy.collect()
    bad_ts = pl.col("ts").is_null() | ~pl.col("ts").is_finite()
    n_bad_ts = joined.filter(bad_ts).height
    if n_bad_ts:
        dropped["invalid_ts"] = n_bad_ts
        joined = joined.filter(~bad_ts)
    joined = joined.with_columns(
        event_second=(pl.col("ts").floor().cast(pl.Int64) // spec.bar_seconds) * spec.bar_seconds
        + spec.bar_seconds
    )
    before = pl.col("ts") < pl.col("window_start")
    late = (~before) & (pl.col("event_second") >= pl.col("window_end"))
    n_before = joined.filter(before).height
    n_late = joined.filter(late).height
    if n_before:
        dropped["before_window"] = n_before
    if n_late:
        dropped["at_or_after_window_end"] = n_late
    kept = joined.filter(~before & ~late).with_columns(event_time=pl.col("event_second") * _NS)
    if resolved.height == 0:
        msg = (
            f"no contract survives: {contracts.height} contract(s) read, {unresolved.height} "
            "without a recorded winner (UP or DOWN), the rest outside --start/--end/"
            "--max-contracts; check the winner column and the selection"
        )
        raise ConfigurationError(msg)
    if kept.height == 0:
        msg = (
            f"no snapshot survives inside the {spec.window_seconds}-second windows ({dropped}); "
            "check that timestamp_log is in seconds and matches start_time"
        )
        raise ConfigurationError(msg)

    # per-side validity reasons (a snapshot's UP and DOWN quotes are judged independently)
    for side in _SIDES:
        bid, ask = pl.col(f"{side}_bid"), pl.col(f"{side}_ask")
        reasons = kept.select(
            null=(bid.is_null() | ask.is_null()).sum(),
            ask_not_positive=(bid.is_not_null() & ask.is_not_null() & (ask <= 0)).sum(),
            crossed=(bid.is_not_null() & (ask > 0) & ((bid > ask) | (bid < 0))).sum(),
        )
        for reason in ("null", "ask_not_positive", "crossed"):
            n = int(reasons[reason][0])
            if n:
                dropped[f"{side}_{reason}"] = n

    contract_bars = pl.concat([_side_bars(kept, side) for side in _SIDES], how="vertical")

    spot_ok = pl.col("spot").is_not_null() & pl.col("spot").is_finite() & (pl.col("spot") > 0)
    spot = (
        kept.filter(spot_ok)
        .sort(["ts", "spot"], maintain_order=True)
        .group_by("event_time", maintain_order=True)
        .agg(
            open=pl.col("spot").first(),
            high=pl.col("spot").max(),
            low=pl.col("spot").min(),
            close=pl.col("spot").last(),
        )
        .with_columns(
            symbol=pl.lit(spec.spot_symbol),
            volume=pl.lit(0.0),
            **{name: pl.lit(None, pl.Float64) for name in _QUOTES},  # spot has no book here
        )
        .select(_BARS)
    )
    n_spot_bad = kept.filter(~spot_ok).height
    if n_spot_bad:
        dropped["spot_invalid"] = n_spot_bad

    have = contract_bars.select("symbol").unique()
    settle = pl.concat(
        [
            resolved.select(
                symbol=pl.format("BTC5M-{}-{}", pl.col("window_start"), pl.lit(side.upper())),
                event_time=pl.col("window_end") * _NS,
                price=pl.when(pl.col("winner") == side.upper())
                .then(pl.lit(1.0))
                .otherwise(pl.lit(spec.settlement_floor)),
            )
            for side in _SIDES
        ],
        how="vertical",
    ).join(have, on="symbol", how="inner")
    settlement_bars = settle.select(
        "symbol",
        "event_time",
        open=pl.col("price"),
        high=pl.col("price"),
        low=pl.col("price"),
        close=pl.col("price"),
        volume=pl.lit(0.0),
        # a settlement is a print, not a market: no spread (ADR-0060)
        bid_open=pl.col("price"),
        ask_open=pl.col("price"),
        bid_close=pl.col("price"),
        ask_close=pl.col("price"),
    ).select(_BARS)
    actions = settle.select(
        "symbol",
        action=pl.lit("delisting"),
        effective_at=pl.col("event_time"),
        event_time=pl.col("event_time"),
        available_at=pl.col("event_time"),
        value=pl.lit(None, pl.Float64),
        pay_at=pl.lit(None, pl.Int64),
    ).select(list(CORPORATE_ACTION_SCHEMA))

    bars = (
        pl.concat([contract_bars, spot, settlement_bars], how="vertical")
        .with_columns(available_at=pl.col("event_time"))
        .select(list(QUOTED_BAR_SCHEMA))
    )

    observations = 2 * max(joined.height, 1)
    side_dropped = sum(v for k, v in dropped.items() if k.startswith(("up_", "down_")))
    if side_dropped / observations > spec.max_dropped_fraction:
        msg = (
            f"{side_dropped} of {observations} side quotes were dropped ({dropped}), above "
            f"max_dropped_fraction={spec.max_dropped_fraction}; inspect the source or raise the "
            "limit knowingly"
        )
        raise ConfigurationError(msg)

    report = ImportReport(
        kind=spec.kind,
        dataset=spec.dataset,
        price_basis=None,
        files=n_files,
        rows_read=rows_read,
        rows_written={spec.dataset: bars.height, f"{spec.dataset}_actions": actions.height},
        dropped=dropped,
        repaired={},
        extra={
            "contracts_kept": resolved.height,
            "contracts_unresolved": unresolved.height,
            "symbols": bars["symbol"].n_unique(),
            "bar_seconds": spec.bar_seconds,
            "quote_columns": True,
        },
    )
    return ImportResult(
        datasets=(
            DatasetOutput(
                dataset=spec.dataset,
                frame=bars,
                schema=QUOTED_BAR_SCHEMA,
                sort_keys=BAR_SORT_KEYS,
                check_bars=True,
                calendar="24/7",
                quality_skip=("calendar_coverage",),
                quality_skip_reason=(
                    "prediction-market contracts trade only inside their five-minute windows"
                ),
            ),
            DatasetOutput(
                dataset=f"{spec.dataset}_actions",
                frame=actions,
                schema=CORPORATE_ACTION_SCHEMA,
                sort_keys=CORPORATE_ACTION_SORT_KEYS,
                check_bars=False,
                calendar=None,
                quality_skip=(),
                quality_skip_reason="",
            ),
        ),
        report=report,
    )
