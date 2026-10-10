"""Frame loaders shared by the replay and venue feeds (ADR-0039/0044).

Moved verbatim from ``ReplayDataFeed._materialize``; the ordering, the derived
``open_time`` and the calendar override are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import CrucibleError
from crucible.core.types import Symbol, TimestampNs

if TYPE_CHECKING:
    from crucible.live.feed import FeedContext


def load_bars_frame(ctx: FeedContext) -> pl.DataFrame:
    lazy = (
        ctx.store.read(ctx.bars_dataset, ctx.end)
        .sort(["symbol", "event_time"])
        .with_columns(
            open_time=pl.coalesce(
                pl.col("event_time").shift(1).over("symbol"),
                pl.col("event_time"),
            )
        )
    )
    if ctx.calendar is not None:
        # true session opens where the calendar knows them; the derived
        # previous-close bound stays as the pessimistic fallback
        span = lazy.select(
            pl.col("event_time").min().alias("lo"), pl.col("event_time").max().alias("hi")
        ).collect()
        if span.height and span[0, "lo"] is not None:
            open_map = ctx.calendar.session_open_by_close(
                TimestampNs(int(span[0, "lo"])), TimestampNs(int(span[0, "hi"]))
            )
            if open_map:
                lazy = lazy.with_columns(
                    open_time=pl.col("event_time").replace_strict(
                        open_map, default=pl.col("open_time")
                    )
                )
    bars: pl.DataFrame = (
        lazy.filter(pl.col("available_at") >= int(ctx.start))
        .sort(["available_at", "symbol"])
        .collect()
    )
    return bars


def load_actions_frame(ctx: FeedContext) -> pl.DataFrame | None:
    if ctx.corporate_actions_dataset is None:
        return None
    return (
        ctx.store.read(ctx.corporate_actions_dataset, ctx.end)
        .filter(
            (pl.col("effective_at") >= int(ctx.start)) & (pl.col("effective_at") <= int(ctx.end))
        )
        .sort(["effective_at", "symbol"])
        .collect()
    )


def check_subscription(
    ctx: FeedContext, symbols: frozenset[Symbol] | None, bars: pl.DataFrame
) -> None:
    if symbols is None:
        return
    present = {str(s) for s in bars.get_column("symbol").to_list()}
    missing = sorted(str(s) for s in symbols if str(s) not in present)
    if missing:
        msg = (
            f"subscribed symbols {missing} have no bars in "
            f"[{ctx.start}, {ctx.end}] of dataset {ctx.bars_dataset}; "
            "fix the subscription or the run window"
        )
        raise CrucibleError(msg)
