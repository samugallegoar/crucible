# ADR-0078: 10,000 shuffles by default in the shuffled-returns test

- **Status**: accepted
- **Date**: 2026-10-19

## Context

The one-step backtest's shuffled-returns test (ADR-0068, ADR-0070) estimated its p-value from 100
shuffles. A Monte Carlo p-value has a standard error of `sqrt(p (1 - p) / B)`: about 0.04 at
p = 0.2 and B = 100, so two seeds could disagree in the second decimal, and the smallest possible
value was 0.0099. The owner asked for 10,000 to make it robust.

## Decision

- `DEFAULT_ITERATIONS = 10_000` (`product/nulltest.py`); the CLI flag and the MCP tool default to
  it. `null_iterations` still sets any value, 0 turns the test off. The estimator, the seed and the
  shuffle are unchanged.
- Measured on the SMA 10/30 example (SPY daily, 2015-2025, offline): 100 shuffles 6.2 s, 1,000 31.7 s,
  10,000 289 s, about 25-30 ms per shuffle (polars engine runs, a dataset write and the spec
  compilation, no single hotspot). The p-value moved 0.228 (100), 0.215 (1,000), 0.219 (10,000).
- A p-value below 0.001 is printed with four decimals (`p_text`), and so is the floor
  `1 / (B + 1)`; they were `0.000` at this size.
- The agent guide, the tool description and the troubleshooting page say what the default costs and
  tell agents to use 100-200 shuffles while exploring and the default for the result they report.

## Alternatives considered

- **Keep 100 and let people raise it**: leaves the headline p-value coarse by default, which is the
  problem.
- **Parallelize or speed up the shuffles first**: a separate piece of work (an iteration's draw would
  have to be seeded per iteration to stay deterministic, which changes every p-value); it is the
  natural next step if five minutes proves too slow.
- **A smaller default such as 1,000** (32 s, standard error 0.013): rejected by the owner's request.

## Consequences

- Default runs are slower by about two orders of magnitude, in proportion to bars and symbols. The
  MCP server's own timeout is 900 s (`CRUCIBLE_MCP_TIMEOUT`); a client with a shorter tool timeout
  will give up first, so agents should pass a smaller `null_iterations` while exploring.
- Every run is still one trial and the shuffles never count as trials (ADR-0019).
- Not changed: shuffling still destroys volatility clustering, and the test still ignores the other
  variants tried (see the DSR for that).
