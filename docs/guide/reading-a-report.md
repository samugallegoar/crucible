# Reading a report

Every backtest produces `summary.html` (open it in a browser) and the same content as
`summary.json`. This page explains each part and how much weight it deserves.

## The top: headline and verdict

The headline is one sentence: what the strategy turned your money into, and what simply holding the
same instrument(s) would have done. The **verdict** is one of three, generated from the numbers:

| Verdict | Means |
|---|---|
| **No edge detected** | it did not make money on a risk-adjusted basis over this period |
| **Not conclusive** | it may have made money, but the evidence is too thin to tell skill from luck; the warnings below say why |
| **Some evidence** | it passed every guard Crucible applies; a reason to test further, never proof |

"Some evidence" needs all of: the 95% range of the Sharpe ratio above zero, at least 100 trades, at
least 5 years, a deflated Sharpe of 0.95 or more, the random re-ordering test beaten at the 5% level,
no earlier optimisation on the same data, and **more than one instrument**. Most single-instrument,
few-dozen-trade backtests will say "not conclusive", and that is the honest answer.

## Strategy vs buy and hold

| Row | How to read it |
|---|---|
| Final value, total return | what the account ended at. Includes your costs. |
| Return per year | the compound annual growth rate. Compare it with buy-and-hold first. |
| Volatility | how much it swings, per year. |
| Worst fall from a peak (max drawdown) | the biggest loss from a high to a later low: what you would have had to sit through. A strategy that earns less but falls much less can still be the one you could actually hold. |
| Sharpe ratio, with its 95% range | return per unit of risk. The range is the honest part: if it is wide or includes zero, the data cannot tell skill from luck. |
| Completed trades | round trips. A position still open at the end is not counted. |

Buy-and-hold uses the same instruments, window, capital and costs. With several symbols it is equal
weight. Both curves are drawn together, then both drawdowns.

## How much to trust this

- **Trial count**: how many variants of this idea have been tried on the same data. Each one makes
  a good-looking result more likely by chance. Crucible counts them, so asking an agent to "try a few
  more numbers" visibly lowers the next result's reliability. That is the point.
- **Deflated Sharpe ratio (DSR)**: the probability that the Sharpe ratio is genuinely positive after
  accounting for the trial count and the shape of the returns. Under 0.95 is a warning.
- **Random re-ordering test**: the same daily returns shuffled in time 100 times, the rules run on
  each. If shuffled data does as well, the timing of the rules has not been shown to matter. Passing
  it means the strategy benefits from the real order of returns (trends, calm and stormy periods); it
  does not mean the edge will continue.
- **Realism level**: how pessimistic the fill assumptions were. The default (Level 1) fills at the
  signal bar's close with a small cost; `--realism-check` re-runs the rules with next-bar fills, a
  spread and latency (Level 2) so you can see how much survives.

## Warnings

Each warning has a code and a sentence. They are not decoration: any of `ci_includes_zero`,
`very_few_trades`, `few_trades`, `single_instrument`, `short_sample`, `dsr_low`, `null_not_beaten` or
`contaminated` stops the verdict from being "some evidence". Others
(`wide_interval`, `multiple_trials`, `no_better_than_buy_and_hold`, `fragile_to_execution`) are
context that belongs in your decision.

## What to try next

The report lists concrete follow-ups generated from the flags: a different period, other
instruments, worse costs, and nearby parameter values (with the reminder that each is a trial).
These are how a result earns trust: it holds elsewhere, not just once.

## The files

| File | What it is |
|---|---|
| `summary.html` / `summary.json` | this report and its data (same bytes for the same request and data) |
| `report.html` | the technical report with the full metric table and provenance |
| `benchmark_equity.parquet` | the strategy and buy-and-hold equity per day |
| `strategy_spec.json` | the rules that ran |
| `manifest.json`, `trades.parquet`, `equity.parquet`, `weights.parquet`, `metrics.json` | technical artifacts: [`docs/SCHEMAS.md`](../SCHEMAS.md) |

A result is reproducible: same rules, same data (the dataset hash is in the footer), same settings
give the same numbers and the same files.
