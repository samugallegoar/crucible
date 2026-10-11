"""Empirical coverage of the Sharpe-ratio bootstrap interval (ADR-0070).

``crucible.analytics.metrics`` reports a percentile interval from a circular block bootstrap
with block length ``floor(sqrt(n))`` and calls it a 95 % interval. This study measures how
often that interval contains the true annualized Sharpe ratio on synthetic return processes
whose Sharpe ratio is known exactly, for the default block length and for two alternatives.

Deterministic (seeded); prints a table. Usage::

    uv run python -m tools.bootstrap_coverage            # the full study (a few minutes)
    uv run python -m tools.bootstrap_coverage --reps 100 # quicker, noisier

Coverage is a proportion over ``reps`` replications, so its Monte Carlo standard error is
``sqrt(c (1 - c) / reps)`` (about 0.011 at 400 replications for c = 0.95). Synthetic coverage
says nothing about real markets; it only shows how the interval behaves when the process is
known.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.analytics import metrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

PERIODS_PER_YEAR = 252.0
MU = 0.0004
SIGMA = 0.01
TRUE_SHARPE = MU / SIGMA * math.sqrt(PERIODS_PER_YEAR)


@dataclass(frozen=True, slots=True)
class Process:
    name: str
    true_sharpe: float
    draw: Callable[[np.random.Generator, int], NDArray[np.float64]]


def _iid_normal(rng: np.random.Generator, n: int) -> NDArray[np.float64]:
    return MU + SIGMA * rng.standard_normal(n)


def _zero_alpha(rng: np.random.Generator, n: int) -> NDArray[np.float64]:
    return SIGMA * rng.standard_normal(n)


def _student_t4(rng: np.random.Generator, n: int) -> NDArray[np.float64]:
    # t with 4 degrees of freedom has variance 2; rescale to SIGMA
    return MU + SIGMA * rng.standard_t(4, n) / math.sqrt(2.0)


def _ar1(rng: np.random.Generator, n: int, phi: float = 0.3) -> NDArray[np.float64]:
    shocks = rng.standard_normal(n + 200) * SIGMA * math.sqrt(1.0 - phi**2)
    x = np.empty(n + 200)
    x[0] = shocks[0] / math.sqrt(1.0 - phi**2)
    for t in range(1, n + 200):
        x[t] = phi * x[t - 1] + shocks[t]
    return MU + x[200:]


def _garch(rng: np.random.Generator, n: int) -> NDArray[np.float64]:
    alpha, beta = 0.08, 0.9
    omega = SIGMA**2 * (1.0 - alpha - beta)
    var = SIGMA**2
    out = np.empty(n + 500)
    z = rng.standard_normal(n + 500)
    eps = 0.0
    for t in range(n + 500):
        var = omega + alpha * eps**2 + beta * var
        eps = math.sqrt(var) * z[t]
        out[t] = eps
    return MU + out[500:]


PROCESSES = (
    Process("iid normal", TRUE_SHARPE, _iid_normal),
    Process("zero alpha (iid)", 0.0, _zero_alpha),
    Process("student-t df=4", TRUE_SHARPE, _student_t4),
    Process("AR(1) phi=0.3", TRUE_SHARPE, _ar1),
    Process("GARCH(1,1) .08/.90", TRUE_SHARPE, _garch),
)


def block_bootstrap_ci(
    returns: NDArray[np.float64],
    stat: Callable[[NDArray[np.float64]], float],
    rng: np.random.Generator,
    block: int,
) -> tuple[float, float]:
    """The same circular block bootstrap as ``metrics._block_bootstrap_ci`` with a chosen
    block length (identical output when ``block == floor(sqrt(n))``)."""
    n = len(returns)
    n_blocks = -(-n // block)
    samples = np.empty(metrics.N_BOOTSTRAP)
    for i in range(metrics.N_BOOTSTRAP):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        samples[i] = stat(returns[idx])
    alpha = (1.0 - metrics.CI_LEVEL) / 2.0
    return float(np.quantile(samples, alpha)), float(np.quantile(samples, 1.0 - alpha))


def block_lengths(n: int) -> dict[str, int]:
    return {
        "sqrt(n) [default]": max(1, int(np.sqrt(n))),
        "n^(1/3)": max(1, round(n ** (1.0 / 3.0))),
        "1 (iid)": 1,
    }


def coverage(process: Process, n: int, block: int, reps: int, seed: int) -> tuple[float, float]:
    """(coverage, mean interval width) over ``reps`` replications."""
    rng = np.random.default_rng(seed)

    def sharpe(r: NDArray[np.float64]) -> float:
        # the private function is the implementation under study
        return metrics._sharpe(r, PERIODS_PER_YEAR)

    hits = 0
    widths = 0.0
    for _ in range(reps):
        returns = process.draw(rng, n)
        low, high = block_bootstrap_ci(returns, sharpe, rng, block)
        hits += int(low <= process.true_sharpe <= high)
        widths += high - low
    return hits / reps, widths / reps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=400)
    parser.add_argument("--n", type=int, nargs="+", default=[252, 1260])
    parser.add_argument("--seed", type=int, default=20261010)
    args = parser.parse_args(argv)
    out = sys.stdout
    out.write(
        f"nominal level {metrics.CI_LEVEL:.0%}, {metrics.N_BOOTSTRAP} bootstrap resamples, "
        f"{args.reps} replications per cell, seed {args.seed}; "
        f"MC s.e. of a coverage near 0.95 = {math.sqrt(0.95 * 0.05 / args.reps):.3f}\n"
    )
    out.write(f"{'process':<20} {'n':>5} {'block':<18} {'coverage':>8} {'width':>7}\n")
    for process in PROCESSES:
        for n in args.n:
            for label, block in block_lengths(n).items():
                cov, width = coverage(process, n, block, args.reps, args.seed)
                out.write(f"{process.name:<20} {n:>5} {label:<18} {cov:>8.3f} {width:>7.3f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
