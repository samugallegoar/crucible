"""False-positive rate and power of the deflated Sharpe ratio under known conditions (ADR-0071).

The procedure studied is the one a researcher follows: evaluate ``N`` candidate strategies,
pick the one with the highest in-sample Sharpe ratio, and compute its DSR against all ``N``
trials (``crucible.validation.dsr.deflated_sharpe_ratio``, ``n_trials=N``). "Strong evidence"
means ``DSR >= 0.95``. Under a null where no strategy has an edge, the rate of strong evidence
is the false-positive rate; the nominal target is 5 %. The undeflated PSR against zero of the
same selected strategy is reported alongside, to show what the deflation buys.

Deterministic (seeded). Usage::

    uv run python -m tools.dsr_calibration             # 1,000 replications per scenario
    uv run python -m tools.dsr_calibration --reps 200  # quicker, noisier

Rates carry 95 % Wilson intervals. Synthetic results describe these processes only, not markets.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from crucible.core.errors import CrucibleError
from crucible.validation.dsr import deflated_sharpe_ratio, per_period_sharpe

SIGMA = 0.01
THRESHOLD = 0.95

Generator = Callable[[np.random.Generator], list[NDArray[np.float64]]]


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    n_trials: int
    generate: Generator
    edge_index: int | None = None
    """Trial with a true edge (power scenarios), else None (null)."""


@dataclass(frozen=True, slots=True)
class Outcome:
    strong_dsr: int
    strong_psr: int
    picked_edge: int
    invalid: int
    reps: int


def _iid(n: int, t: int, mu: float = 0.0) -> Generator:
    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        return list(mu + SIGMA * rng.standard_normal((n, t)))

    return gen


def _heterogeneous(n: int, lo: int, hi: int) -> Generator:
    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        lengths = rng.integers(lo, hi + 1, size=n)
        return [SIGMA * rng.standard_normal(int(t)) for t in lengths]

    return gen


def _ar1(n: int, t: int, phi: float) -> Generator:
    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        shocks = rng.standard_normal((n, t + 200)) * SIGMA * math.sqrt(1.0 - phi**2)
        x = np.empty_like(shocks)
        x[:, 0] = shocks[:, 0] / math.sqrt(1.0 - phi**2)
        for k in range(1, t + 200):
            x[:, k] = phi * x[:, k - 1] + shocks[:, k]
        return list(x[:, 200:])

    return gen


def _student_t(n: int, t: int, df: int) -> Generator:
    scale = SIGMA / math.sqrt(df / (df - 2))

    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        return list(scale * rng.standard_t(df, (n, t)))

    return gen


def _correlated(n: int, t: int, rho: float) -> Generator:
    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        common = rng.standard_normal(t)
        own = rng.standard_normal((n, t))
        return list(SIGMA * (math.sqrt(rho) * common + math.sqrt(1.0 - rho) * own))

    return gen


def _one_edge(n: int, t: int, per_period_sharpe: float) -> Generator:
    base = _iid(n, t)

    def gen(rng: np.random.Generator) -> list[NDArray[np.float64]]:
        series = base(rng)
        series[0] = series[0] + per_period_sharpe * SIGMA
        return series

    return gen


def scenarios() -> list[Scenario]:
    out = [
        Scenario(f"iid normal, N={n}, T={t}", n, _iid(n, t))
        for n in (1, 10, 100)
        for t in (252, 1260)
    ]
    out += [
        Scenario(
            "heterogeneous windows, N=20, T in [126, 2520]", 20, _heterogeneous(20, 126, 2520)
        ),
        Scenario("AR(1) phi=0.2, N=10, T=1260", 10, _ar1(10, 1260, 0.2)),
        Scenario("AR(1) phi=0.2, N=100, T=1260", 100, _ar1(100, 1260, 0.2)),
        Scenario("Student-t df=4, N=10, T=1260", 10, _student_t(10, 1260, 4)),
        Scenario("Student-t df=4, N=100, T=1260", 100, _student_t(100, 1260, 4)),
        Scenario("correlated rho=0.9, N=100, T=1260", 100, _correlated(100, 1260, 0.9)),
        Scenario("one edge SR=0.08/period, N=10, T=1260", 10, _one_edge(10, 1260, 0.08), 0),
        Scenario("one edge SR=0.08/period, N=100, T=1260", 100, _one_edge(100, 1260, 0.08), 0),
    ]
    return out


def run(scenario: Scenario, reps: int, seed: int) -> Outcome:
    rng = np.random.default_rng(seed)
    strong_dsr = strong_psr = picked = invalid = 0
    for _ in range(reps):
        series = scenario.generate(rng)
        sharpes = [per_period_sharpe(s) for s in series]
        best = int(np.argmax(sharpes))
        try:
            dsr = deflated_sharpe_ratio(series[best], sharpes, n_trials=scenario.n_trials).dsr
            psr = deflated_sharpe_ratio(series[best], [sharpes[best]], n_trials=1).dsr
        except CrucibleError:
            invalid += 1
            continue
        strong_dsr += int(dsr >= THRESHOLD)
        strong_psr += int(psr >= THRESHOLD)
        picked += int(best == scenario.edge_index)
    return Outcome(strong_dsr, strong_psr, picked, invalid, reps)


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95 % Wilson score interval of a proportion ``k / n``."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--reps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261011)
    args = parser.parse_args(argv)
    out = sys.stdout
    out.write(
        f"rate of DSR >= {THRESHOLD} for the selected best-of-N strategy; {args.reps} "
        f"replications per scenario, seed {args.seed}; [95% Wilson interval]\n"
    )
    out.write(f"{'scenario':<46} {'DSR>=.95':>22} {'naive PSR>=.95':>22} {'picked edge':>11}\n")
    started = time.perf_counter()
    for i, scenario in enumerate(scenarios()):
        res = run(scenario, args.reps, args.seed + i)
        valid = res.reps - res.invalid
        lo, hi = wilson(res.strong_dsr, valid)
        plo, phi_ = wilson(res.strong_psr, valid)
        picked = f"{res.picked_edge / valid:.3f}" if scenario.edge_index is not None else "-"
        out.write(
            f"{scenario.name:<46} {res.strong_dsr / valid:>6.3f} [{lo:.3f},{hi:.3f}]"
            f" {res.strong_psr / valid:>6.3f} [{plo:.3f},{phi_:.3f}] {picked:>11}"
            + (f"  ({res.invalid} invalid)" if res.invalid else "")
            + "\n"
        )
        out.flush()
    out.write(f"runtime {time.perf_counter() - started:.1f} s\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
