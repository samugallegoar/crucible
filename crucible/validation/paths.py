"""Return-sequence risk: simulated equity paths and their distributions (ADR-0083).

**What this answers.** Given the returns (or the trades) a strategy actually produced, how much do
the headline outcomes depend on *which* returns happened and in *what order*? Resample the history
many times and look at the spread of terminal equity, of the worst drawdown, of the chance of
finishing below the start and of touching a ruin level, plus a fan of percentile bands over time.

**What this does not answer.** Whether the strategy has an edge. A resampled history is built from
the same returns, so it is centred on the realized result: a low "probability of loss" here only
says the realized mean was positive relative to its sampling noise, which any lucky or overfit
backtest also shows. Evidence about an edge needs a null (``validation.null_tests``, the shuffled
returns test) or a correction for the search that found the strategy (the deflated Sharpe, PBO,
``validation.reality_check``). Every summary carries ``kind = "return_sequence_risk"`` so a report
cannot mistake one for the other.

Two resamplers, one summary:

* :func:`simulate_return_paths` - the stationary bootstrap of per-period returns
  (``validation.resampling``): keeps short-range dependence (volatility clustering, holding a
  position through several bars) that an i.i.d. draw destroys. Its effective sample is the number
  of *blocks*, not of bars.
* :func:`simulate_trade_paths` - an i.i.d. bootstrap of per-trade returns on equity, compounded
  trade after trade. The honest unit when positions are held for many bars or the account is flat
  most of the time: ``n`` trades carry the information, however many bars the backtest has. It
  marks equity at trade closes, so it sees closed-trade drawdowns only and assumes constant
  sizing and independent trades.

Units: returns are simple per-period fractions; paths are equity *multiples* of the starting value
(1.0 at time 0). Pessimism: a ruin level is the multiple the account must never touch, and a path
is checked at every step, not only at the end.

Performance: paths are generated and summarized in chunks, so memory is bounded by the chunk and by
the fan's time grid, not by ``n_paths x horizon``; the full matrix is built only on request
(``keep_paths``) and refused above a cell budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError
from crucible.validation.resampling import optimal_block_length, stationary_bootstrap_indices

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from numpy.typing import NDArray

KIND = "return_sequence_risk"
"""Tag on every summary: sampling/sequence risk of one history, not evidence of an edge."""

PERCENTILES: tuple[int, ...] = (5, 25, 50, 75, 95)
DEFAULT_PATHS = 1_000
DEFAULT_RUIN_LOSS = 0.5
"""The default ruin level: the account falls to half of its starting value at any time."""
DEFAULT_DRAWDOWN_THRESHOLD = -0.30
"""Same default as ``validation.monte_carlo``: the drawdown whose probability is reported."""
DEFAULT_FAN_POINTS = 200
MIN_OBSERVATIONS = 10
MAX_KEPT_CELLS = 25_000_000
"""``keep_paths`` refuses a request above this many path values (about 200 MB of float64)."""
_CHUNK_CELLS = 4_000_000
"""Path values generated at a time while summarizing."""


@dataclass(frozen=True, slots=True)
class PathSummary:
    """Distribution summaries of ``n_paths`` simulated equity paths of ``horizon`` steps.

    ``fan`` maps a percentile to the equity multiple at each of ``fan_steps`` (step 0 is the
    start, 1.0). ``max_drawdown_*`` are drawdowns (negative numbers): ``p05`` is the bad tail.
    ``paths`` is None unless the caller asked to keep them."""

    kind: str
    method: str
    n_paths: int
    horizon: int
    mean_block: float | None
    ruin_loss: float
    drawdown_threshold: float
    terminal_multiple: dict[str, float]
    max_drawdown: dict[str, float]
    prob_loss: float
    prob_ruin: float
    prob_drawdown_worse_than_threshold: float
    fan_steps: tuple[int, ...]
    fan: dict[str, tuple[float, ...]]
    paths: NDArray[np.float64] | None = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        """The summary as plain JSON-ready values (without the paths)."""
        return {
            "kind": self.kind,
            "method": self.method,
            "n_paths": self.n_paths,
            "horizon": self.horizon,
            "mean_block": self.mean_block,
            "ruin_loss": self.ruin_loss,
            "drawdown_threshold": self.drawdown_threshold,
            "terminal_multiple": dict(self.terminal_multiple),
            "max_drawdown": dict(self.max_drawdown),
            "prob_loss": self.prob_loss,
            "prob_ruin": self.prob_ruin,
            "prob_drawdown_worse_than_threshold": self.prob_drawdown_worse_than_threshold,
            "fan_steps": list(self.fan_steps),
            "fan": {key: list(values) for key, values in self.fan.items()},
        }


def _returns_array(returns: object, what: str) -> NDArray[np.float64]:
    arr = np.asarray(returns, dtype=np.float64)
    if arr.ndim != 1:
        msg = f"{what} must be a 1-D series, got shape {arr.shape}"
        raise ConfigurationError(msg)
    if arr.size < MIN_OBSERVATIONS:
        msg = (
            f"cannot simulate paths from {arr.size} {what}; need >= {MIN_OBSERVATIONS} (a "
            "distribution estimated from fewer observations is not worth reporting)"
        )
        raise ConfigurationError(msg)
    if not np.all(np.isfinite(arr)) or np.any(arr <= -1.0):
        msg = f"cannot simulate paths: the {what} contain NaN/infinite values or a loss of 100%"
        raise ConfigurationError(msg)
    return arr


def _check_levels(n_paths: int, ruin_loss: float, drawdown_threshold: float) -> None:
    if n_paths < 1:
        msg = f"n_paths must be >= 1, got {n_paths}"
        raise ConfigurationError(msg)
    if not 0.0 < ruin_loss < 1.0:
        msg = (
            f"ruin_loss is the fraction of the start that must be lost, in (0, 1); got {ruin_loss}"
        )
        raise ConfigurationError(msg)
    if not -1.0 < drawdown_threshold < 0.0:
        msg = f"drawdown_threshold must be a negative fraction above -1, got {drawdown_threshold}"
        raise ConfigurationError(msg)


def _fan_grid(horizon: int, fan_points: int) -> NDArray[np.int64]:
    count = max(2, min(horizon + 1, fan_points))
    return np.unique(np.linspace(0, horizon, count).round().astype(np.int64))


def _summarize(
    chunks: Iterable[NDArray[np.float64]],
    *,
    method: str,
    n_paths: int,
    horizon: int,
    mean_block: float | None,
    ruin_loss: float,
    drawdown_threshold: float,
    fan_points: int,
    keep_paths: bool,
) -> PathSummary:
    """Folds an iterable of ``(m, horizon + 1)`` multiple matrices into a :class:`PathSummary`."""
    grid = _fan_grid(horizon, fan_points)
    terminal: list[NDArray[np.float64]] = []
    drawdown: list[NDArray[np.float64]] = []
    lowest: list[NDArray[np.float64]] = []
    fan_cols: list[NDArray[np.float64]] = []
    kept: list[NDArray[np.float64]] = []
    for multiples in chunks:
        peaks = np.maximum.accumulate(multiples, axis=1)
        terminal.append(multiples[:, -1].copy())
        drawdown.append(np.minimum(0.0, (multiples / peaks - 1.0).min(axis=1)))
        lowest.append(multiples.min(axis=1))
        fan_cols.append(multiples[:, grid].copy())
        if keep_paths:
            kept.append(multiples.copy())
    final = np.concatenate(terminal)
    worst = np.concatenate(drawdown)
    floor = np.concatenate(lowest)
    bands = np.concatenate(fan_cols, axis=0)
    names = [f"p{p:02d}" for p in PERCENTILES]
    return PathSummary(
        kind=KIND,
        method=method,
        n_paths=n_paths,
        horizon=horizon,
        mean_block=mean_block,
        ruin_loss=ruin_loss,
        drawdown_threshold=drawdown_threshold,
        terminal_multiple={
            **{n: float(v) for n, v in zip(names, np.percentile(final, PERCENTILES), strict=True)},
            "mean": float(final.mean()),
        },
        max_drawdown={
            n: float(v) for n, v in zip(names, np.percentile(worst, PERCENTILES), strict=True)
        },
        prob_loss=float((final < 1.0).mean()),
        prob_ruin=float((floor <= 1.0 - ruin_loss).mean()),
        prob_drawdown_worse_than_threshold=float((worst <= drawdown_threshold).mean()),
        fan_steps=tuple(int(s) for s in grid),
        fan={
            n: tuple(float(v) for v in row)
            for n, row in zip(names, np.percentile(bands, PERCENTILES, axis=0), strict=True)
        },
        paths=np.concatenate(kept, axis=0) if keep_paths else None,
    )


def _guard_kept(n_paths: int, horizon: int, keep_paths: bool) -> None:
    if keep_paths and n_paths * (horizon + 1) > MAX_KEPT_CELLS:
        msg = (
            f"keeping {n_paths} paths of {horizon + 1} points is {n_paths * (horizon + 1):,} "
            f"values, above the {MAX_KEPT_CELLS:,} budget; ask for fewer paths, or use the fan "
            "(percentile bands), which needs no stored paths"
        )
        raise ConfigurationError(msg)


def _chunk_size(horizon: int) -> int:
    return max(1, _CHUNK_CELLS // (horizon + 1))


def simulate_return_paths(
    returns: object,
    rng: np.random.Generator,
    *,
    n_paths: int = DEFAULT_PATHS,
    horizon: int | None = None,
    mean_block: float | None = None,
    ruin_loss: float = DEFAULT_RUIN_LOSS,
    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD,
    fan_points: int = DEFAULT_FAN_POINTS,
    keep_paths: bool = False,
) -> PathSummary:
    """Stationary-bootstrap equity paths of per-period ``returns``.

    ``horizon`` (default: as many periods as the history has) is the number of steps per path;
    ``mean_block`` (default: chosen from the data, ``resampling.optimal_block_length``) the mean
    block length, 1 being the i.i.d. bootstrap. Describes the sampling variability of this
    history's outcomes, not the existence of an edge (module docstring).
    """
    arr = _returns_array(returns, "returns")
    _check_levels(n_paths, ruin_loss, drawdown_threshold)
    steps = arr.size if horizon is None else int(horizon)
    if steps < 1:
        msg = f"horizon must be >= 1, got {horizon}"
        raise ConfigurationError(msg)
    _guard_kept(n_paths, steps, keep_paths)
    block = optimal_block_length(arr) if mean_block is None else float(mean_block)
    size = _chunk_size(steps)

    def chunks() -> Iterator[NDArray[np.float64]]:
        remaining = n_paths
        while remaining > 0:
            m = min(size, remaining)
            idx = stationary_bootstrap_indices(arr.size, steps, block, m, rng)
            multiples = np.empty((m, steps + 1))
            multiples[:, 0] = 1.0
            np.cumprod(1.0 + arr[idx], axis=1, out=multiples[:, 1:])
            yield multiples
            remaining -= m

    return _summarize(
        chunks(),
        method="stationary_bootstrap",
        n_paths=n_paths,
        horizon=steps,
        mean_block=block,
        ruin_loss=ruin_loss,
        drawdown_threshold=drawdown_threshold,
        fan_points=fan_points,
        keep_paths=keep_paths,
    )


def simulate_trade_paths(
    trade_returns: object,
    rng: np.random.Generator,
    *,
    n_paths: int = DEFAULT_PATHS,
    n_trades: int | None = None,
    ruin_loss: float = DEFAULT_RUIN_LOSS,
    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD,
    fan_points: int = DEFAULT_FAN_POINTS,
    keep_paths: bool = False,
) -> PathSummary:
    """I.i.d. bootstrap of per-trade returns on equity, compounded trade after trade.

    ``trade_returns`` are each completed trade's net return as a fraction of the equity it was
    opened with (a trade that risks 50% of the account and gains 10% is 0.05). ``n_trades``
    (default: as many as the history has) is the number of trades per path. The horizon of the
    summary is in trades, and drawdown and ruin are seen at trade closes only.
    """
    arr = _returns_array(trade_returns, "trade returns")
    _check_levels(n_paths, ruin_loss, drawdown_threshold)
    steps = arr.size if n_trades is None else int(n_trades)
    if steps < 1:
        msg = f"n_trades must be >= 1, got {n_trades}"
        raise ConfigurationError(msg)
    _guard_kept(n_paths, steps, keep_paths)
    size = _chunk_size(steps)

    def chunks() -> Iterator[NDArray[np.float64]]:
        remaining = n_paths
        while remaining > 0:
            m = min(size, remaining)
            draws = rng.integers(0, arr.size, size=(m, steps))
            multiples = np.empty((m, steps + 1))
            multiples[:, 0] = 1.0
            np.cumprod(1.0 + arr[draws], axis=1, out=multiples[:, 1:])
            yield multiples
            remaining -= m

    return _summarize(
        chunks(),
        method="trade_bootstrap",
        n_paths=n_paths,
        horizon=steps,
        mean_block=None,
        ruin_loss=ruin_loss,
        drawdown_threshold=drawdown_threshold,
        fan_points=fan_points,
        keep_paths=keep_paths,
    )
