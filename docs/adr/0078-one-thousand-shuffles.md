# ADR-0078: 1,000 shuffles by default in the shuffled-returns test

- **Status**: accepted
- **Date**: 2026-10-19

## Context

The one-step backtest's shuffled-returns test (ADR-0068, ADR-0070) estimated its p-value from 100
shuffles. A Monte Carlo p-value has a standard error of `sqrt(p (1 - p) / B)`: about 0.04 at
p = 0.2 and B = 100, so two seeds could disagree in the second decimal, and the smallest possible
value was 0.0099. The owner asked for 10,000 to make it robust, measured the cost (about five
minutes for ten years of daily bars) and chose 1,000 instead.

## Decision

- `DEFAULT_ITERATIONS = 1_000` (`product/nulltest.py`); the CLI flag, the MCP tool and
  `BacktestRequest` default to it. `null_iterations` still sets any value, 0 turns the test off. The
  estimator, the seed and the shuffle are unchanged.
- Measured on the SMA 10/30 example (SPY daily, 2015-2025, offline): 100 shuffles 6.2 s, 1,000 31.7 s,
  10,000 289 s, about 25-30 ms per shuffle (polars engine runs, a dataset write and the spec
  compilation, no single hotspot). The p-value moved 0.228 (100), 0.215 (1,000), 0.219 (10,000).
  Standard error at p = 0.2: 0.04, 0.013, 0.004.
- A p-value below 0.001 is printed with four decimals (`p_text`), and so is the floor
  `1 / (B + 1)` when it is below 0.001 (it would otherwise print as `0.000` at 10,000 shuffles).
- The agent guide, the tool description and the troubleshooting page say what the default costs and
  tell agents they can pass 100 for a quick look.

## Alternatives considered

- **Keep 100**: leaves the headline p-value coarse by default, which is the problem.
- **10,000** (289 s, standard error 0.004): the first choice, rejected as too slow for the default
  (a run in an MCP client can time out well before five minutes, and an agent trying several
  variants waits that long each time). It stays available with `null_iterations`.
- **Speed up the shuffles first (parallel workers)**: a separate piece of work; an iteration's draw
  would have to be seeded per iteration to stay deterministic, which changes every p-value. The
  natural step if the default is ever raised.

## Consequences

- Default runs take about ten times longer than before (about 30 s for ten years of daily bars, in
  proportion to bars and symbols). The MCP server's own timeout is 900 s (`CRUCIBLE_MCP_TIMEOUT`).
- Every run is still one trial and the shuffles never count as trials (ADR-0019).
- Not changed: shuffling still destroys volatility clustering, and the test still ignores the other
  variants tried (see the DSR for that).
