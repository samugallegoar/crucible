# examples/

Runnable strategies + configs. **Every example is also a test**: it runs in
the integration suite and appears in the lookahead harness matrix.

## momentum — daily cross-sectional momentum with a delisting

```bash
uv run python examples/momentum/build_data.py    # synthetic datasets (seeded)
uv run crucible run examples/momentum/config.yaml
# -> prints EXP-<id>; open experiments/EXP-<id>/report.html
```

Eight synthetic GBM symbols over 2020–2021 (XNYS sessions); `SYM7` delists
about 60% of the way through and the engine liquidates it at the last mark
(ADR-0010). The strategy (`strategy.py`) ranks trailing returns and holds
the top 2 equal-weight, rebalancing every 10 sessions on the prior session's
information set.

`config_level4.yaml` runs the identical strategy at realism Level 4
(dynamic spread, latency, sqrt impact, per-share commissions, participation
caps) with optimistic/conservative/extreme scenario fan-out; `crucible run`
prints every scenario's experiment id and writes
`scenario_decay.{json,html}` into the base run's artifacts.

Tests that pin this example: `tests/integration/test_momentum_example.py`,
`tests/integration/test_scenario_fanout.py`,
`tests/lookahead/test_poisoned_future.py`, `tests/golden/test_determinism.py`.

## trend_demo — single-symbol trend following with genuine AR(1) edge

```bash
uv run python examples/trend_demo/build_data.py
uv run crucible run examples/trend_demo/config.yaml
uv run crucible run examples/trend_demo/config.yaml --runtime paper   # same results
uv run crucible run examples/trend_demo/config_live.yaml --runtime live
uv run crucible run-vectorized examples/trend_demo/config_vectorized.yaml
uv run crucible promote examples/trend_demo/config_vectorized.yaml --level 2 \
  --lookback 3 --execution my_execution.yaml --out promoted.yaml
```

One synthetic symbol with genuine lag-1 serial correlation in returns
(`build_data.py`, ADR-0024) — `TrendFollower` (`strategy.py`) reads its own
trailing return sign every session (`rebalance_every: 1`), long 100% or
flat. `RandomDirection` in the same file is the "no edge" comparison used
by the null-test acceptance demo. `vectorized_signal.py::
trend_follower_signal` (ADR-0035) is a vectorized mirror of
`TrendFollower` used by the vectorized-vs-event-driven agreement test —
see its module docstring for the bar-by-bar timing derivation.

```bash
uv run python -c "
from pathlib import Path
from crucible.experiments.config import load_config
from crucible.experiments.vectorized_runner import run_vectorized_experiment
config = load_config(Path('examples/trend_demo/config_vectorized.yaml'))
print(run_vectorized_experiment(config, Path('experiments')).experiment_id)
"
```

`config_vectorized.yaml` (ADR-0036) runs the same
dataset through the vectorized engine instead (`crucible run-vectorized`, ADR-0051;
the snippet above is the library equivalent). `promote_config`
(ADR-0037; `crucible promote`) can rewrite that same vectorized config into one that reruns
`trend_follower_signal` through the event-driven engine at Level 2+,
re-deciding under real friction rather than replaying a schedule.

`config_live.yaml` (ADR-0043/0044) runs the same strategy
through `LiveRuntime` on the simulated venue (`live: {enabled: true}`);
`tests/integration/test_live_parity.py` shows it matches the backtest
(orders, fills, ledger amounts, equity). From the CLI:
`crucible run examples/trend_demo/config_live.yaml --runtime live` (ADR-0051).

Tests that pin this example: `tests/integration/test_phase3_acceptance.py`,
`tests/integration/test_live_parity.py`,
`tests/lookahead/test_poisoned_future_trend_demo.py`,
`tests/unit/test_vectorized_engine.py`,
`tests/unit/test_vectorized_runner.py`,
`tests/unit/test_promotion.py`,
`tests/lookahead/test_vectorized_poisoned_future.py`,
`tests/integration/test_vectorized_agreement.py`,
`tests/integration/test_vectorized_run_experiment.py`,
`tests/integration/test_promotion_level2.py`.

## overfit_demo — a strategy with no skill, for the overfitting gates

```bash
uv run python examples/momentum/build_data.py    # it reuses the momentum dataset
uv run crucible optimize examples/overfit_demo/config.yaml --param seed \
  --values 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39
# -> PBO: 0.6500 (n_combinations=20, n_trials=40) and the best trial's DSR (0.29 on the shipped data)
```

`RandomSignal` (`strategy.py`, ADR-0023) picks its symbols with a seeded `rng.choice`, never from
data: by construction it has zero genuine edge. Sweeping its `seed` and keeping the best in-sample
Sharpe is exactly the search a trial-counting sweep guards against, so the sweep shows PBO above
0.5 and a best-trial DSR far below what its raw Sharpe suggests — the "known-overfit" half of
the overfit-detection acceptance demonstration (`trend_demo` is the genuine-edge half). With only a handful of
seeds the numbers are noisy; the acceptance test uses 40. The config is `mode: optimization`,
which `crucible optimize` requires.

Tests that pin this example: `tests/integration/test_phase3_acceptance.py`,
`tests/lookahead/test_poisoned_future_overfit_demo.py`.

## real_data — strategies on the imported datasets

`examples/real_data/` runs the momentum, trend and a new Polymarket strategy on the datasets
built from your own files (`crucible data build`, ADR-0052). See `examples/real_data/README.md`;
their tests use small hand-built stores, and `tests/bench` measures the real datasets.
