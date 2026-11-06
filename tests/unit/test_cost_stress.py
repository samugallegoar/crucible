"""The cost stress grid (ADR-0083): net return at k times the costs is gross - k * cost."""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.product.diagnostics import cost_stress


def test_a_hand_computed_grid() -> None:
    """Gross bars alternate +2% / -1% (100 bars) and each bar pays 0.1% of costs. At k times the
    costs a bar returns 0.02 - 0.001k or -0.01 - 0.001k."""
    n, cost = 100, 0.001
    gross = np.array([0.02, -0.01] * (n // 2))
    net = gross - cost
    rows = cost_stress(gross, net, 100_000.0, 2.0, 252.0, multipliers=(1.0, 2.0, 5.0))
    for row in rows:
        k = row["multiplier"]
        assert k is not None
        up, down = 0.02 - cost * k, -0.01 - cost * k
        final = 100_000.0 * ((1 + up) * (1 + down)) ** (n // 2)
        assert row["final_equity"] == pytest.approx(final)
        mean = (up + down) / 2
        sd = math.sqrt(n * ((up - down) / 2) ** 2 / (n - 1))  # deviations are +/- (up - down) / 2
        assert row["sharpe"] == pytest.approx(mean / sd * math.sqrt(252.0))
        assert row["cagr_pct"] == pytest.approx(((final / 100_000.0) ** (1 / 2.0) - 1) * 100)
    sharpes = [float(r["sharpe"] or 0) for r in rows]
    assert sharpes == sorted(sharpes, reverse=True)  # dearer costs, lower Sharpe


def test_no_cost_means_no_degradation() -> None:
    gross = np.array([0.01, -0.005, 0.003, 0.002] * 10)
    rows = cost_stress(gross, gross, 1_000.0, 1.0, 252.0)
    assert len({round(float(r["final_equity"] or 0), 9) for r in rows}) == 1


def test_a_stress_that_loses_everything_is_reported_as_none_not_a_number() -> None:
    gross = np.full(10, 0.01)
    net = gross - 0.3
    rows = cost_stress(gross, net, 1_000.0, 1.0, 252.0, multipliers=(1.0, 4.0))
    assert rows[1] == {"multiplier": 4.0, "sharpe": None, "cagr_pct": None, "final_equity": None}
