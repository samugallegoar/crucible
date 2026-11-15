"""Dataset contracts: the typed schemas every stored dataset conforms to.

Every dataset carries the two mandatory time columns:
``event_time`` (when it happened / period it refers to) and ``available_at``
(when a market participant could first have known it). Both are UTC int64 ns.
"""

from __future__ import annotations

import polars as pl

BAR_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),  # instrument identifier, unique within the dataset
    "event_time": pl.Int64(),  # bar close (UTC ns)
    "available_at": pl.Int64(),  # close + feed latency (UTC ns, >= event_time; ADR-0007)
    "open": pl.Float64(),  # first price of the bar, in the symbol's currency
    "high": pl.Float64(),  # highest price of the bar
    "low": pl.Float64(),  # lowest price of the bar
    "close": pl.Float64(),  # last price of the bar; the mark
    "volume": pl.Float64(),  # shares/contracts traded in the bar, >= 0
}
BAR_SORT_KEYS = ["available_at", "symbol", "event_time"]

BAR_QUOTE_SCHEMA: dict[str, pl.DataType] = {
    "bid_open": pl.Float64(),  # best bid at the bar's first quote; nullable; 0 is a one-sided book
    "ask_open": pl.Float64(),  # best ask at the bar's first quote; nullable; >= bid_open
    "bid_close": pl.Float64(),  # best bid at the bar's last quote; nullable
    "ask_close": pl.Float64(),  # best ask at the bar's last quote; nullable; >= bid_close
}
# optional extension of BAR_SCHEMA: a dataset without these columns is still a valid bar dataset
QUOTED_BAR_SCHEMA: dict[str, pl.DataType] = {**BAR_SCHEMA, **BAR_QUOTE_SCHEMA}

UNIVERSE_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),  # instrument identifier
    "start_at": pl.Int64(),  # first instant the symbol is a member (UTC ns, inclusive)
    "end_at": pl.Int64(),  # exclusive; i64::MAX = still a member
    "reason": pl.String(),  # free-text reason for the membership row
    # membership tables are reference data known at build time:
    "event_time": pl.Int64(),  # UTC ns; reference data known at build time
    "available_at": pl.Int64(),  # UTC ns; when the row became knowable (>= event_time)
}
UNIVERSE_SORT_KEYS = ["symbol", "start_at"]

CORPORATE_ACTION_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),  # instrument identifier
    "action": pl.String(),  # CorporateActionType value (engine applies cash_dividend, delisting)
    "effective_at": pl.Int64(),  # UTC ns; run timestamp (ex-date for CASH_DIVIDEND, ADR-0026)
    "event_time": pl.Int64(),  # UTC ns; when the action happened
    "available_at": pl.Int64(),  # UTC ns; when it became knowable (>= event_time)
    "value": pl.Float64(),  # nullable: action parameter (e.g. dividend/share)
    "pay_at": pl.Int64(),  # nullable: required for CASH_DIVIDEND, unused otherwise (ADR-0026)
}
CORPORATE_ACTION_SORT_KEYS = ["effective_at", "symbol"]

END_AT_OPEN = 2**63 - 1
"""Sentinel for `end_at` of a still-active universe membership row."""

FX_RATE_SCHEMA: dict[str, pl.DataType] = {
    # ``symbol`` holds a currency-pair code, e.g. "EURUSD" means
    # "1 EUR = `mid` USD" (ADR-0009). Reuses the bar-shaped PIT
    # accessor (`event_time`/`available_at`/`symbol`) rather than a
    # separate accessor -- an FX rate is PIT data like any other.
    "symbol": pl.String(),  # currency-pair code, e.g. EURUSD = 1 EUR costs `mid` USD
    "event_time": pl.Int64(),  # UTC ns; the quote's time
    "available_at": pl.Int64(),  # UTC ns; when the quote became knowable (>= event_time)
    "mid": pl.Float64(),  # marking role: valuation only, never moves cash
    "bid": pl.Float64(),  # trading role: adverse side when selling the pair's first currency
    "ask": pl.Float64(),  # trading role: adverse side when buying the pair's first currency
}
FX_RATE_SORT_KEYS = ["available_at", "symbol", "event_time"]

CONTINUOUS_BAR_SCHEMA: dict[str, pl.DataType] = {
    # a continuous futures series (ADR-0086): BAR_SCHEMA plus the contract that printed the bar
    "symbol": pl.String(),  # the continuous instrument, i.e. the root (ES); one per dataset
    "event_time": pl.Int64(),  # bar close (UTC ns)
    "available_at": pl.Int64(),  # close + feed latency (UTC ns, >= event_time; ADR-0007)
    "open": pl.Float64(),  # first price of the bar: the contract's own, or ratio-adjusted
    "high": pl.Float64(),  # highest price of the bar
    "low": pl.Float64(),  # lowest price of the bar
    "close": pl.Float64(),  # last price of the bar; the mark
    "volume": pl.Float64(),  # contracts traded in the bar by the held contract; never adjusted
    "contract": pl.String(),  # the individual contract held when the bar printed (ESH2024)
}
CONTINUOUS_BAR_SORT_KEYS = ["available_at", "symbol", "event_time"]

ROLL_SCHEMA: dict[str, pl.DataType] = {
    # one row per contract switch of a continuous series (ADR-0086)
    "symbol": pl.String(),  # the continuous instrument, i.e. the root (ES)
    "event_time": pl.Int64(),  # end of the deciding session (UTC ns): when the roll became knowable
    "available_at": pl.Int64(),  # same instant: the roll is knowable once the deciding session ends
    "from_contract": pl.String(),  # the contract held before the roll
    "to_contract": pl.String(),  # the contract held from the effective session on
    "effective_trade_date": pl.String(),  # first Globex trade date (YYYY-MM-DD) of the new contract
    "reference_time": pl.Int64(),  # close (UTC ns) of the last minute both contracts traded before
    "from_price": pl.Float64(),  # the old contract's close at reference_time
    "to_price": pl.Float64(),  # the new contract's close at reference_time
    "ratio": pl.Float64(),  # to_price / from_price: what earlier bars are multiplied by
    "gap_points": pl.Float64(),  # to_price - from_price: the jump in the unadjusted series
    "reason": pl.String(),  # volume (the next contract led), backstop (expiry) or expired (no bars)
}
ROLL_SORT_KEYS = ["available_at", "symbol", "event_time"]
