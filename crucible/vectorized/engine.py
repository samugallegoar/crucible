"""The vectorized Level 0/1 backtester (ADR-0035).

Owns its own plain config/result types rather than importing
``crucible.experiments.config.ExperimentConfig`` -- the layered view places the vectorized path
*below* the experiments layer, alongside
the event-driven core, so the dependency runs experiments -> vectorized,
never the other way. ``crucible.experiments`` is the glue that
translates an ``ExperimentConfig`` into a :class:`VectorizedConfig`; this module mirrors
``core/engine.py::BacktestEngine``'s own style of taking plain typed constructor-shaped
arguments for exactly that reason.

Shift discipline (R2.3): the engine takes a signal function's raw
``score`` output and applies a mandatory ``.shift(lag_bars).over(symbol)``
before it becomes a ``weight`` -- this happens unconditionally, regardless
of what the signal function itself already did internally. A signal
author who forgets to lag their own computation still can't make a
position at ``t`` reflect information from bar ``t`` or later; a signal
author who already lags internally (to mirror an event-driven strategy's
own timing, ADR-0035) simply gets one bar of *additional* lag stacked on
top -- "configurable only upward" (``vectorized/interfaces.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.vectorized.fx import run_fx_equity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.data.store import ParquetDataStore
    from crucible.vectorized.interfaces import SignalFunction

_REQUIRED_SCORE_COLUMNS = {"ts", "symbol", "score"}


@dataclass(frozen=True, slots=True)
class VectorizedConfig:
    """Engine-owned run parameters. Level 0/1 only (R3.1's ladder does not
    extend into the vectorized path) -- there are deliberately no
    slots for spread/latency/impact models, risk limits, multi-currency, or
    futures; ``VectorizedBacktestEngine.run`` refuses anything outside
    Level 0/1's ``slippage_bps``/``commission_bps`` shorthand (ADR-0010's
    same shorthand, reused).
    """

    store: ParquetDataStore
    bars_dataset: DatasetId
    signal: SignalFunction
    params: Mapping[str, object]
    initial_cash: Decimal
    realism_level: RealismLevel
    start: TimestampNs
    end: TimestampNs
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    lag_bars: int = 1
    # multi-currency (ADR-0062): used only when a symbol's currency is not ``base_currency``
    base_currency: str = "USD"
    symbol_currency: Mapping[str, str] = field(default_factory=dict)
    fx_dataset: DatasetId | None = None


@dataclass(frozen=True, slots=True)
class VectorizedResult:
    """``equity``: ``ts``/``equity`` (base-currency-implicit, no FX --
    known gap, see module doc). ``weights``: ``ts``/``symbol``/``weight``,
    already lagged -- the position actually in force when ``equity``'s
    return for that ``ts`` was realized. ``scores``: the signal function's
    raw, pre-lag output, kept for the promotion path and debugging. ``pnl``:
    ``ts``/``symbol``/``pnl``, the gross (before costs) pnl each symbol earned
    at each bar of the run window, in the run's currency; at every ``ts`` it
    sums to the change in ``equity`` when costs are zero (ADR-0062)."""

    equity: pl.DataFrame
    weights: pl.DataFrame
    scores: pl.DataFrame
    pnl: pl.DataFrame


def _validate_level(config: VectorizedConfig) -> None:
    if config.realism_level not in (RealismLevel.FRICTIONLESS, RealismLevel.BASIC_FRICTION):
        msg = (
            f"vectorized engine supports realism_level FRICTIONLESS or BASIC_FRICTION only, "
            f"got {config.realism_level.name}; Level 2+ needs the event-driven engine "
            "(promote this config and rerun through crucible.core.engine.BacktestEngine)"
        )
        raise ConfigurationError(msg)
    if config.realism_level is RealismLevel.FRICTIONLESS and (
        config.slippage_bps or config.commission_bps
    ):
        msg = (
            "FRICTIONLESS (Level 0) refuses nonzero slippage_bps/commission_bps "
            f"(got slippage_bps={config.slippage_bps}, commission_bps={config.commission_bps}); "
            "set realism_level to BASIC_FRICTION to configure friction (ADR-0010's rule, "
            "reused for the vectorized path)"
        )
        raise ConfigurationError(msg)
    if config.slippage_bps < 0 or config.commission_bps < 0:
        msg = (
            f"slippage_bps/commission_bps must be >= 0, got "
            f"slippage_bps={config.slippage_bps}, commission_bps={config.commission_bps}"
        )
        raise ConfigurationError(msg)
    if config.lag_bars < 1:
        msg = (
            f"lag_bars must be >= 1 (shift discipline has no opt-out, "
            f"vectorized/interfaces.py); got {config.lag_bars}"
        )
        raise ConfigurationError(msg)
    if config.end < config.start:
        msg = f"vectorized backtest end={config.end} before start={config.start}"
        raise ConfigurationError(msg)


def _validate_score_schema(scored: pl.LazyFrame) -> None:
    columns = set(scored.collect_schema().names())
    missing = _REQUIRED_SCORE_COLUMNS - columns
    if missing:
        msg = (
            f"signal function output is missing columns {sorted(missing)}; a SignalFunction "
            "must return a frame keyed (ts, symbol) with a score column "
            "(crucible/vectorized/interfaces.py)"
        )
        raise ConfigurationError(msg)


def _validate_score_grid(scored: pl.LazyFrame, bars: pl.LazyFrame) -> None:
    """Exactly one score per ``(symbol, ts)`` of the run's bar grid.

    ``lag_bars`` shifts the score frame by *rows*, and the engine joins it to the bars with an
    inner join, so a signal that drops a bar shifts every later weight by one row **and** removes
    that bar's return from the equity curve; a duplicated row double-counts a bar; a row for a
    timestamp the bars do not have moves the lag without contributing a return. None of those is
    visible in the result, so the engine refuses them (AGENTS.md §1.2: the engine enforces).
    """
    bar_pairs = bars.select(pl.col("symbol"), pl.col("event_time").alias("ts")).collect()
    expected = bar_pairs.unique()
    if bar_pairs.height != expected.height:
        duplicated = (
            bar_pairs.group_by(["symbol", "ts"])
            .len()
            .filter(pl.col("len") > 1)
            .sort("len", descending=True)
        )
        msg = (
            f"the bars dataset holds {bar_pairs.height - expected.height} duplicated "
            f"(symbol, event_time) rows, e.g. {duplicated.head(3).to_dicts()}; the vectorized "
            "engine assigns one weight and one return per bar, so a duplicated bar would be "
            "counted twice. Deduplicate the dataset (keep one version per bar) before running"
        )
        raise DataQualityError(msg)
    pairs = scored.select("symbol", "ts").collect()
    unique = pairs.unique()
    if pairs.height != unique.height:
        duplicated = (
            pairs.group_by(["symbol", "ts"])
            .len()
            .filter(pl.col("len") > 1)
            .sort("len", descending=True)
        )
        msg = (
            f"the signal function returned {pairs.height - unique.height} duplicated (symbol, ts) "
            f"score rows (of {pairs.height}), e.g. {duplicated.head(3).to_dicts()}; a signal must "
            "return exactly one score per bar, because the engine's lag shifts the score frame by "
            "rows and a duplicate double-counts that bar's weight and return"
        )
        raise ConfigurationError(msg)
    missing = expected.join(unique, on=["symbol", "ts"], how="anti")
    if missing.height:
        msg = (
            f"the signal function returned no score for {missing.height} of {expected.height} "
            f"(symbol, ts) bars, e.g. {missing.head(3).to_dicts()}; the mandatory lag shifts the "
            "score frame by rows, so a missing bar would lag every later weight by one row and "
            "drop that bar's return from the equity curve. Return a score for every bar of the "
            "frame the engine passes in (fill warm-up with 0.0 rather than dropping the rows)"
        )
        raise ConfigurationError(msg)
    extra = unique.join(expected, on=["symbol", "ts"], how="anti")
    if extra.height:
        msg = (
            f"the signal function returned {extra.height} (symbol, ts) score rows that are not "
            f"bars of dataset {sorted(extra.get_column('symbol').unique().to_list())}, e.g. "
            f"{extra.head(3).to_dicts()}; the lag is applied over the score frame, so a row "
            "without a bar would shift it. Score exactly the bars the engine passes in"
        )
        raise ConfigurationError(msg)


def _foreign_currencies(config: VectorizedConfig, prices: pl.LazyFrame) -> set[str]:
    """The non-base currencies of the symbols the bars actually hold (ADR-0062)."""
    if not config.symbol_currency:
        return set()
    present = prices.select("symbol").unique().collect().get_column("symbol").to_list()
    return {
        config.symbol_currency[s]
        for s in present
        if s in config.symbol_currency and config.symbol_currency[s] != config.base_currency
    }


class VectorizedBacktestEngine:
    """Stateless: every call to :meth:`run` is an independent backtest,
    entirely determined by its ``config`` (E1 determinism)."""

    def run(self, config: VectorizedConfig) -> VectorizedResult:
        _validate_level(config)

        bars = config.store.read(config.bars_dataset, as_of=config.end)
        scored = config.signal(bars, dict(config.params))
        _validate_score_schema(scored)
        _validate_score_grid(scored, bars)

        scored = scored.select(["ts", "symbol", "score"]).sort(["symbol", "ts"])
        weighted = scored.with_columns(
            weight=pl.col("score").shift(config.lag_bars).over("symbol").fill_null(0.0)
        )

        prices = (
            bars.select(["symbol", "event_time", "close"])
            .rename({"event_time": "ts"})
            .sort(["symbol", "ts"])
        )
        if _foreign_currencies(config, prices):
            return self._run_with_fx(config, weighted, prices, scored)
        joined = (
            weighted.join(prices, on=["symbol", "ts"], how="inner")
            .sort(["symbol", "ts"])
            .with_columns(
                ret=(pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0).fill_null(
                    0.0
                ),
                turnover=(
                    pl.col("weight") - pl.col("weight").shift(1).over("symbol").fill_null(0.0)
                ).abs(),
            )
            .filter((pl.col("ts") >= config.start) & (pl.col("ts") <= config.end))
        )

        cost_rate = (config.slippage_bps + config.commission_bps) / 10_000.0
        per_bar = (
            joined.group_by("ts")
            .agg(
                gross=(pl.col("weight") * pl.col("ret")).sum(),
                turnover_sum=pl.col("turnover").sum(),
            )
            .sort("ts")
            .with_columns(net=pl.col("gross") - pl.col("turnover_sum") * cost_rate)
            .collect()
        )

        equity_value = float(config.initial_cash)
        ts_rows: list[int] = []
        equity_rows: list[float] = []
        for row in per_bar.iter_rows(named=True):
            equity_value *= 1.0 + float(row["net"])
            ts_rows.append(int(row["ts"]))
            equity_rows.append(equity_value)

        equity = pl.DataFrame(
            {"ts": ts_rows, "equity": equity_rows},
            schema={"ts": pl.Int64(), "equity": pl.Float64()},
        )
        # gross per-symbol pnl: weight * return * the equity it was earned on (the prior bar's)
        prior = pl.DataFrame(
            {"ts": ts_rows, "prior_equity": [float(config.initial_cash), *equity_rows[:-1]]},
            schema={"ts": pl.Int64(), "prior_equity": pl.Float64()},
        )
        pnl = (
            joined.select("ts", "symbol", contrib=pl.col("weight") * pl.col("ret"))
            .collect()
            .join(prior, on="ts")
            .select("ts", "symbol", pnl=pl.col("contrib") * pl.col("prior_equity"))
            .sort(["ts", "symbol"])
        )
        return VectorizedResult(
            equity=equity,
            weights=weighted.select(["ts", "symbol", "weight"]).sort(["ts", "symbol"]).collect(),
            scores=scored.collect(),
            pnl=pnl,
        )

    def _run_with_fx(
        self,
        config: VectorizedConfig,
        weighted: pl.LazyFrame,
        prices: pl.LazyFrame,
        scored: pl.LazyFrame,
    ) -> VectorizedResult:
        """The multi-currency path (ADR-0062): needs one aligned bar calendar, an FX dataset with a
        ``<CCY><BASE>`` pair per foreign currency and a rate known at every bar (as-of
        ``available_at <= ts``). The run starts flat at its first in-window bar."""
        if config.fx_dataset is None:
            msg = (
                f"symbol_currency names non-base currencies for symbols in the bars but no FX "
                f"rate dataset is set (data.fx_rates); base_currency is {config.base_currency}"
            )
            raise ConfigurationError(msg)
        table = (
            weighted.join(prices, on=["symbol", "ts"], how="inner")
            .filter((pl.col("ts") >= config.start) & (pl.col("ts") <= config.end))
            .select("symbol", "ts", "close", "weight")
            .sort(["symbol", "ts"])
            .collect()
        )
        if table.height == 0:
            msg = (
                f"no bars between ts={config.start} and ts={config.end} in dataset "
                f"{config.bars_dataset!r}; widen the window or check the dataset (ADR-0062)"
            )
            raise DataQualityError(msg)
        grid = table.get_column("ts").unique().sort()
        symbols = table.get_column("symbol").unique(maintain_order=True).to_list()
        for symbol in symbols:
            have = table.filter(pl.col("symbol") == symbol).get_column("ts")
            if have.len() != grid.len():
                missing = grid.filter(~grid.is_in(have.implode()))[0]
                msg = (
                    f"the vectorized FX path needs a common calendar, but symbol {symbol} has no "
                    f"bar at ts={missing} while another symbol does; align the bars or use the "
                    "event-driven engine for staggered calendars (ADR-0062)"
                )
                raise DataQualityError(msg)

        currency_of = {s: config.symbol_currency.get(s, config.base_currency) for s in symbols}
        foreign = sorted({c for c in currency_of.values() if c != config.base_currency})
        fx_all = config.store.read(config.fx_dataset, as_of=config.end).collect()
        grid_frame = pl.DataFrame({"ts": grid})
        rates: dict[str, np.ndarray] = {}
        for ccy in foreign:
            pair = f"{ccy}{config.base_currency}"
            rows = fx_all.filter(pl.col("symbol") == pair).select(
                "event_time", "available_at", "mid"
            )
            if rows.height == 0:
                msg = (
                    f"no FX rate for {pair} in dataset {config.fx_dataset!r}: pairs are "
                    f"<CCY><BASE> ({config.base_currency} base) and are not inverted"
                )
                raise DataQualityError(msg)
            # the event engine's PIT read: among the rows available at ts, the latest event_time
            # (ties: the later available_at); built as a running best over rows by available_at
            ordered = (
                rows.sort(["available_at", "event_time", "mid"])
                .with_row_index("i")
                .with_columns(best_event=pl.col("event_time").cum_max())
                .with_columns(
                    best=pl.when(pl.col("event_time") == pl.col("best_event"))
                    .then(pl.col("i"))
                    .otherwise(None)
                    .forward_fill()
                )
            )
            known = ordered.select(
                "available_at", mid=ordered.get_column("mid").gather(ordered["best"])
            )
            joined = grid_frame.join_asof(
                known, left_on="ts", right_on="available_at", strategy="backward"
            )
            mid = joined.get_column("mid")
            if mid.null_count():
                first = joined.filter(pl.col("mid").is_null())[0, "ts"]
                msg = f"no FX rate for {pair} available as of ts={first}"
                raise DataQualityError(msg)
            values = mid.to_numpy()
            if not (np.isfinite(values).all() and (values > 0).all()):
                msg = f"FX mid for {pair} must be finite and positive at every bar"
                raise DataQualityError(msg)
            rates[ccy] = values

        n_rows, n_symbols = grid.len(), len(symbols)
        close = table.get_column("close").to_numpy().reshape(n_symbols, n_rows).T
        weight = table.get_column("weight").to_numpy().reshape(n_symbols, n_rows).T
        fx = np.ones((n_rows, n_symbols), dtype=np.float64)
        for column, symbol in enumerate(symbols):
            if currency_of[symbol] != config.base_currency:
                fx[:, column] = rates[currency_of[symbol]]
        equity_values, pnl_values = run_fx_equity(
            close=close,
            weight=weight,
            fx=fx,
            initial_cash=float(config.initial_cash),
            cost_rate=(config.slippage_bps + config.commission_bps) / 10_000.0,
        )
        stamps = grid.to_list()
        equity = pl.DataFrame(
            {"ts": stamps, "equity": equity_values.tolist()},
            schema={"ts": pl.Int64(), "equity": pl.Float64()},
        )
        pnl = pl.DataFrame(
            {
                "ts": [ts for ts in stamps for _ in symbols],
                "symbol": [s for _ in stamps for s in symbols],
                "pnl": pnl_values.reshape(-1).tolist(),
            },
            schema={"ts": pl.Int64(), "symbol": pl.String(), "pnl": pl.Float64()},
        ).sort(["ts", "symbol"])
        # the run starts flat: the weight at its first row is never held (no pnl, no cost), so
        # the weights frame must not report a position there (episodes are built from it)
        weights = (
            weighted.select(["ts", "symbol", "weight"])
            .with_columns(
                weight=pl.when(pl.col("ts") == int(grid[0]))
                .then(pl.lit(0.0))
                .otherwise(pl.col("weight"))
            )
            .sort(["ts", "symbol"])
            .collect()
        )
        return VectorizedResult(equity=equity, weights=weights, scores=scored.collect(), pnl=pnl)
