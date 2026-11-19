"""Property: a skill-less return series almost never clears a deflated Sharpe threshold.

The calibration sanity check of the futures statistics (PRD C6a, ADR-0103): a strategy with no edge
must not be "significant". The series here is a random-sign, zero-mean return series -- the exact
null hypothesis -- and the family it is deflated against is itself a panel of null trials, so a
pass rate noticeably ABOVE the nominal 5% would mean the deflation flatters a search.

The test runs a FIXED number of replications from a seeded generator, so it is deterministic on
every platform and either passes or fails the same way: no Hypothesis exploration, no wall clock.
The bound is loose on purpose (0.10 against a nominal 0.05 at 400 replications, where the binomial
standard deviation of the rate is ~0.011): a strict 0.05 assertion would be a coin flip on the
sample, not a calibration test.
"""

from __future__ import annotations

import numpy as np

from crucible.core.stats import is_degenerate_returns
from crucible.validation.dsr import deflated_sharpe_ratio

REPLICATIONS = 400
OBSERVATIONS = 252
NOMINAL = 0.05
TOLERANCE = 0.10
"""The largest pass rate a null series may reach: twice the nominal level, four standard deviations
of the binomial rate away from it."""


def test_a_null_return_series_does_not_clear_the_dsr_threshold_above_the_nominal_rate() -> None:
    rng = np.random.default_rng(20261119)
    hits = 0
    valid = 0
    for _ in range(REPLICATIONS):
        # the family: five null trials whose per-period Sharpes estimate the cross-trial dispersion
        family = [float(rng.normal(0.0, 0.01, OBSERVATIONS).mean() / 0.01) for _ in range(5)]
        signals = rng.choice([-1.0, 1.0], size=OBSERVATIONS) * rng.exponential(0.01, OBSERVATIONS)
        if is_degenerate_returns(signals):  # a refusal, never a pass
            continue
        valid += 1
        hits += int(deflated_sharpe_ratio(signals, family, n_trials=len(family)).dsr >= 0.95)
    assert valid == REPLICATIONS  # a random-sign series is never degenerate
    assert hits / valid <= TOLERANCE, (
        f"a null series cleared DSR >= 0.95 in {hits}/{valid} replications "
        f"({hits / valid:.3f}), above the {TOLERANCE:.2f} a skill-less series may reach: the "
        "deflation is flattering the search (ADR-0015, ADR-0103)"
    )
    assert hits / valid >= 0.0  # and the test ran at all
    assert NOMINAL == 0.05
