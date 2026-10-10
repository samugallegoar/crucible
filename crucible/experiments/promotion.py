"""Promotion: rerun a vectorized experiment's signal through the
event-driven engine at Level 2+ (ADR-0037).

``promote_config`` rewrites an ``ExperimentConfig`` that was validated for
the vectorized path (``assemble_vectorized_engine``, ADR-0036 — so it is,
by construction, already free of corporate actions/universe/multi-currency/
futures/risk) into one that runs the *same signal function* through
``BacktestEngine`` under real Level 2+ friction, via ``PromotedSignalStrategy``.
The promoted run is a genuine re-decision under realistic frictions, not a
replay of the vectorized run's already-computed weight schedule: at every
bar, ``PromotedSignalStrategy`` re-evaluates the signal function against
the PIT-legal history available at that moment and sizes an order against
the portfolio's *actual* equity (which Level 2+ costs have already eaten
into) — a schedule computed frictionlessly in advance could not do that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, cast

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol
from crucible.data.store import ParquetDataStore
from crucible.experiments.config import ExecutionConfig, ExperimentConfig, StrategyConfig
from crucible.experiments.runner import import_entrypoint

if TYPE_CHECKING:
    from crucible.core.events import BarEvent
    from crucible.strategy.context import BacktestContext
    from crucible.vectorized.interfaces import SignalFunction

_HISTORY_FIELDS = ["open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class _Settings:
    signal: SignalFunction
    signal_params: dict[str, object]
    bars_dataset: DatasetId
    symbols: list[Symbol]
    lookback: int
    base: Currency
    symbol_currency: dict[str, str]
    fx_dataset: DatasetId | None
    futures_multipliers: dict[str, Decimal]


class PromotedSignalStrategy:
    """Generic event-driven adapter for any vectorized ``SignalFunction``.
    Every parameter is read from ``ctx.params`` (same convention as every
    other example strategy) — never constructed directly by a caller, only
    referenced by entrypoint from a config ``promote_config`` builds."""

    def _cfg(self, ctx: BacktestContext) -> _Settings:
        """The promotion's settings, read from ``ctx.params`` on every call: a strategy may not keep
        attributes on ``self`` (the engine refuses to checkpoint one whose attributes changed
        during the run, ADR-0048), and promoted runs must be resumable like any other."""
        params = ctx.params
        raw_signal_params = params["signal_params"]
        assert isinstance(raw_signal_params, dict)
        raw_symbols = params["symbols"]
        assert isinstance(raw_symbols, list)
        # present only for a multi-currency config (ADR-0062); absent for every other promotion
        raw_currency = params.get("symbol_currency", {})
        assert isinstance(raw_currency, dict)
        fx_rates = params.get("fx_rates")
        return _Settings(
            signal=cast("SignalFunction", import_entrypoint(str(params["signal_entrypoint"]))),
            signal_params=raw_signal_params,
            bars_dataset=DatasetId(str(params["bars_dataset"])),
            symbols=[Symbol(str(s)) for s in raw_symbols],
            lookback=int(str(params["lookback"])),
            base=Currency(str(params["base_currency"])),
            symbol_currency={str(k): str(v) for k, v in raw_currency.items()},
            fx_dataset=DatasetId(str(fx_rates)) if fx_rates is not None else None,
            futures_multipliers={
                str(k): Decimal(str(v))
                for k, v in params.get("futures_multipliers", {}).items()  # type: ignore[attr-defined]
            },
        )

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        """Rebalances once, on the last bar of a timestamp (ADR-0064).

        The engine marks the portfolio bar by bar, so on the first symbol's bar the later symbols'
        marks (hence the equity the sizing reads) are one bar stale. The vectorized run sizes from
        the equity after every symbol's bar of the timestamp, so the promoted strategy waits until
        it has seen a bar for every symbol that has one at this timestamp (a symbol without a bar
        there is not waited for, so staggered calendars still rebalance). A bar that reaches the
        engine after a later timestamp's bar (a slower feed) is ignored. Limit: if one symbol's bar
        becomes available later than another's at the same timestamp, only the bars available when
        the first arrives are counted, so the decision is taken then with the late symbol's mark
        stale, as before this change."""
        cfg = self._cfg(ctx)
        if event.symbol not in cfg.symbols:
            return
        ts = int(event.event_time)
        state = ctx.state
        latest = state.get("seen_ts", -1)
        assert isinstance(latest, int)
        if ts < latest:
            return  # a late bar of a timestamp already decided: never rebalance backwards
        if latest != ts:
            state["seen_ts"] = ts
            state["seen"] = []
            state["expected"] = self._bars_at(ctx, cfg, ts)
        seen = state["seen"]
        assert isinstance(seen, list)
        if str(event.symbol) not in seen:
            seen.append(str(event.symbol))
        expected = state["expected"]
        assert isinstance(expected, int)
        if len(seen) >= expected and state.get("rebalanced_ts") != ts:
            state["rebalanced_ts"] = ts
            self._rebalance(ctx, cfg)

    def _bars_at(self, ctx: BacktestContext, cfg: _Settings, ts: int) -> int:
        """How many universe symbols have a bar at ``ts`` (PIT-legal: every bar of a timestamp is
        available at it)."""
        latest = ctx.data.history(
            cfg.bars_dataset,
            ["close"],
            cfg.symbols,
            as_of=ctx.clock.now,
            lookback=1,
        )
        return int(latest.filter(latest["event_time"] == ts).height)

    def _rebalance(self, ctx: BacktestContext, cfg: _Settings) -> None:
        history = ctx.data.history(
            cfg.bars_dataset,
            _HISTORY_FIELDS,
            cfg.symbols,
            as_of=ctx.clock.now,
            lookback=cfg.lookback,
        )
        if history.height == 0:
            return

        scored = cfg.signal(history.lazy(), cfg.signal_params).collect()
        if scored.height == 0:
            return
        latest_scores = {
            row["symbol"]: row["score"]
            for row in scored.sort(["symbol", "ts"])
            .group_by("symbol", maintain_order=True)
            .last()
            .to_dicts()
        }

        latest_prices = {
            row["symbol"]: row["close"]
            for row in history.sort(["symbol", "event_time"])
            .group_by("symbol", maintain_order=True)
            .last()
            .to_dicts()
        }

        equity = ctx.portfolio.equity(cfg.base)
        for symbol in cfg.symbols:
            key = str(symbol)
            if key not in latest_scores or key not in latest_prices:
                continue
            weight = Decimal(repr(latest_scores[key]))
            # the price comes from the PIT history (it includes the other symbols' bars at this
            # timestamp, which the engine's marks do not yet); a foreign symbol's price is
            # converted to base currency at the FX mid known now (ADR-0029, ADR-0062)
            # a futures contract's notional is price * multiplier (ADR-0065); 1 for anything else
            price = (
                Decimal(repr(latest_prices[key]))
                * cfg.futures_multipliers.get(key, Decimal(1))
                * self._fx_mid(ctx, cfg, symbol)
            )
            target_qty = (
                (equity * weight / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
                if weight != 0
                else Decimal("0")
            )
            position = ctx.portfolio.position(symbol)
            current_qty = position.qty if position is not None else Decimal("0")
            delta = target_qty - current_qty
            if delta == 0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            ctx.orders.submit(symbol, side, abs(delta))

    def _fx_mid(self, ctx: BacktestContext, cfg: _Settings, symbol: Symbol) -> Decimal:
        """The symbol's currency-to-base mid as of now (1 for a base-currency symbol), read through
        the PIT accessor exactly as the engine marks equity."""
        currency = cfg.symbol_currency.get(str(symbol), str(cfg.base))
        if currency == str(cfg.base):
            return Decimal(1)
        if cfg.fx_dataset is None:
            msg = (
                f"symbol {symbol} is quoted in {currency} but the promotion has no fx_rates dataset"
            )
            raise CrucibleError(msg)
        pair = Symbol(f"{currency}{cfg.base}")
        row = ctx.data.get(cfg.fx_dataset, ["mid"], [pair], as_of=ctx.clock.now)
        if row.height == 0:
            msg = f"no FX rate for {pair} available as of ts={ctx.clock.now}"
            raise CrucibleError(msg)
        return Decimal(repr(float(row.get_column("mid")[0])))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def promote_config(
    vectorized_config: ExperimentConfig,
    *,
    target_realism_level: RealismLevel,
    execution: ExecutionConfig,
    promotion_lookback: int,
) -> ExperimentConfig:
    """Builds an ``ExperimentConfig`` that reruns ``vectorized_config``'s
    signal through the event-driven engine at ``target_realism_level``
    (must be Level 2+ -- a Level 0/1 rerun is just the vectorized config
    itself, run directly). ``execution`` and ``promotion_lookback`` are
    required, not defaulted: guessing a spread/latency model or a history
    window would fabricate an assumption the caller never made (CLAUDE.md
    §10's conservative-ambiguity rule), and a wrong (too-small) lookback
    would silently starve the signal of history it needs, producing a
    result that isn't actually the same signal.

    The symbol universe is read directly from the bars dataset (not
    through a PIT accessor) -- this happens at config-construction time,
    before any simulated engine exists, so there is no as_of to violate;
    it is the same class of one-time, whole-dataset read
    ``run_experiment``'s own quality gate and manifest hashing already do.
    """
    if target_realism_level < RealismLevel.SPREAD_LATENCY:
        msg = (
            f"promotion targets Level 2+ (got {target_realism_level.name}); a Level 0/1 rerun "
            "is exactly the vectorized config itself -- run it directly through "
            "run_vectorized_experiment instead"
        )
        raise ConfigurationError(msg)
    if promotion_lookback <= 0:
        msg = f"promotion_lookback must be > 0, got {promotion_lookback}"
        raise ConfigurationError(msg)

    store = ParquetDataStore(vectorized_config.data.store)
    bars_dataset = DatasetId(vectorized_config.data.bars)
    symbols = (
        store.read(bars_dataset, as_of=vectorized_config.end_ns)
        .select("symbol")
        .unique()
        .collect()
        .get_column("symbol")
        .sort()
        .to_list()
    )
    if not symbols:
        msg = f"bars dataset {bars_dataset!r} has no symbols as of {vectorized_config.end_ns}"
        raise ConfigurationError(msg)

    params: dict[str, object] = {
        "signal_entrypoint": vectorized_config.strategy.entrypoint,
        "signal_params": dict(vectorized_config.strategy.params),
        "bars_dataset": vectorized_config.data.bars,
        "symbols": symbols,
        "lookback": promotion_lookback,
        "base_currency": vectorized_config.data.base_currency,
    }
    if vectorized_config.data.symbol_currency:
        # only for a multi-currency config, so every single-currency promotion keeps its params
        # (and its experiment id) unchanged (ADR-0062)
        params["symbol_currency"] = dict(vectorized_config.data.symbol_currency)
        if vectorized_config.data.fx_rates is not None:
            params["fx_rates"] = vectorized_config.data.fx_rates
    if vectorized_config.data.futures_multipliers:
        # only for a futures config, so every other promotion keeps its params and id (ADR-0065)
        params["futures_multipliers"] = {
            s: str(m) for s, m in vectorized_config.data.futures_multipliers.items()
        }
    strategy = StrategyConfig(
        entrypoint="crucible.experiments.promotion:PromotedSignalStrategy",
        params=params,
    )
    experiment = vectorized_config.experiment.model_copy(
        update={"realism_level": target_realism_level}
    )
    return vectorized_config.model_copy(
        update={"experiment": experiment, "strategy": strategy, "execution": execution}
    )
