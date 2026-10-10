"""Paper runtime: the backtest engine driven through the DataFeed seam.

The same ``Strategy`` object runs unchanged; only the runtime
differs. Config-to-engine translation is ``assemble_engine``'s, not
duplicated here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from crucible.core.errors import ConfigurationError
from crucible.core.types import Currency, RealismLevel
from crucible.experiments.runner import assemble_engine
from crucible.live.execution import VenueExecution
from crucible.live.paper import PaperBroker
from crucible.live.replay import ReplayDataFeed
from crucible.live.venue import SimulatedVenue
from crucible.live.venue_feed import VenueDataFeed

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from crucible.core.engine import BacktestEngine, BacktestResult
    from crucible.core.interfaces import Event
    from crucible.core.types import Symbol
    from crucible.data.store import ParquetDataStore
    from crucible.execution.backend import ExecutionBackend, ExecutionContext
    from crucible.experiments.config import ExperimentConfig
    from crucible.live.feed import FeedContext
    from crucible.live.interfaces import DataFeed


class PaperRuntime:
    """Runs a validated ``ExperimentConfig`` on replayed data through a
    ``ReplayDataFeed`` and exposes a ``PaperBroker`` over the same engine.

    ``symbols`` narrows the feed (unset = every symbol in the bars dataset);
    a symbol with no bars in the run window raises ``CrucibleError`` when
    ``run()`` starts.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        store: ParquetDataStore | None = None,
        symbols: frozenset[Symbol] | None = None,
        observer: Callable[[Event], None] | None = None,
    ) -> None:
        def factory(ctx: FeedContext) -> DataFeed:
            feed = ReplayDataFeed(ctx)
            if symbols is not None:
                feed.subscribe(symbols)
            return feed

        self._engine = assemble_engine(config, store=store, observer=observer, feed_factory=factory)
        self._broker = PaperBroker(self._engine)

    @property
    def engine(self) -> BacktestEngine:
        return self._engine

    @property
    def broker(self) -> PaperBroker:
        return self._broker

    def run(self) -> BacktestResult:
        return self._engine.run()


class LiveRuntime:
    """The backtest engine driven by a simulated venue.

    Behind a feature flag: the config must carry ``live: {enabled: true}``.
    Orders go to the venue and fills return as events through a lazily
    stamping feed; the strategy, risk and ledger are the engine's own. Library
    API only. Limits: Levels 1+, single currency, no futures, single orders.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        store: ParquetDataStore | None = None,
        observer: Callable[[Event], None] | None = None,
    ) -> None:
        live = config.live
        if live is None or not live.enabled:
            msg = (
                "LiveRuntime is behind a feature flag: set `live: {enabled: true}` in the "
                "experiment config"
            )
            raise ConfigurationError(msg)
        level = config.experiment.realism_level
        if level < RealismLevel.BASIC_FRICTION:
            msg = (
                "LiveRuntime needs realism level >= 1 (BASIC_FRICTION); "
                f"the config has {level.name}"
            )
            raise ConfigurationError(msg)
        if config.data.symbol_currency or config.data.futures_multipliers:
            msg = (
                "LiveRuntime is single-currency and has no futures support in this piece; "
                "clear data.symbol_currency and data.futures_multipliers"
            )
            raise ConfigurationError(msg)

        holder: list[SimulatedVenue] = []

        def backend_factory(ctx: ExecutionContext) -> ExecutionBackend:
            venue = SimulatedVenue(
                level=ctx.level,
                spread=ctx.setup.spread,
                latency=ctx.setup.latency,
                slippage=ctx.setup.slippage,
                commission=ctx.setup.commission,
                participation=ctx.setup.participation,
                stats=ctx.stats,
                rng=ctx.rng,
                initial_cash=config.initial_cash,
                base_currency=Currency(config.data.base_currency),
            )
            holder.append(venue)
            return VenueExecution(venue)

        def feed_factory(fctx: FeedContext) -> DataFeed:
            return VenueDataFeed(fctx, holder[0])

        self._engine = assemble_engine(
            config,
            store=store,
            observer=observer,
            feed_factory=feed_factory,
            execution_backend_factory=backend_factory,
        )
        self._venue = holder[0]

    @property
    def engine(self) -> BacktestEngine:
        return self._engine

    @property
    def venue(self) -> SimulatedVenue:
        return self._venue

    def run(self) -> BacktestResult:
        return self._engine.run()

    def checkpoint(self, path: Path) -> None:
        """Writes the engine, feed and venue state at the current session
        boundary (call it right after ``engine.run_until``)."""
        self._engine.checkpoint(path)

    def resume_from(
        self, path: Path, *, venue_state: Literal["restore", "external"] = "restore"
    ) -> None:
        """Resumes into this fresh runtime. ``restore`` rebuilds the in-process
        venue from the checkpoint; ``external`` models a venue that kept running:
        its state is not restored and any difference from the checkpoint is
        refused (ADR-0044)."""
        backend = self._engine.execution
        assert isinstance(backend, VenueExecution)
        backend.restore_mode = venue_state
        self._engine.resume_from(path)
