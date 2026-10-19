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
no earlier optimisation on the same data, **more than one instrument**, and a **realism check**: the
rules re-run with next-bar fills, a spread and latency, which must not cut the result materially. The
main run fills at the signal bar's close, which is optimistic, so a result that passes every other
guard but was never re-run with realistic fills says "not conclusive yet" and asks for that check. Most single-instrument,
few-dozen-trade backtests will say "not conclusive", and that is the honest answer.

## Strategy vs buy and hold

| Row | How to read it |
|---|---|
| Final value, total return | what the account ended at. Includes your costs. |
| Return per year | the compound annual growth rate. Compare it with buy-and-hold first. |
| Volatility | how much it swings, per year. |
| Worst fall from a peak (max drawdown) | the biggest loss from a high to a later low: what you would have had to sit through. A strategy that earns less but falls much less can still be the one you could actually hold. |
| Sharpe ratio, with its 95% range | return per unit of risk. The range is the honest part: if it is wide or includes zero, the data cannot tell skill from luck. It is an approximate bootstrap interval: on synthetic data with known answers it held the true Sharpe about 91-93% of the time with one year of daily data or with heavy-tailed returns, and about 94-95% with five years of well-behaved returns, so read it as the least uncertainty there is. The other rows have no range. |
| Completed trades | round trips. A position still open at the end is not counted. |
| Cost drag, turnover, break-even cost per side | what costs took off the annual return, how many times the capital changed hands per year, and the cost per side (in basis points) at which the strategy would earn nothing. If the break-even is only a little above the assumed cost, a slightly worse fill erases the result: this is the first thing to check on an intraday strategy. |
| Alpha vs buy and hold, beta, return per unit of exposure | the part of the return not explained by moving with the benchmark (with a t-statistic: below about 2 it is indistinguishable from zero), how much it moves with it, and the annual return scaled to being fully invested. A strategy that is invested a third of the time is not "worse" for earning less than buy-and-hold. |
| Winning trades (after costs), net expectancy, profit factor, average win / average loss | how often a trade made money after costs, the average result per trade in basis points with a 95% range (if it includes zero there is no proven edge per trade), gross wins over gross losses, and the size of an average win against an average loss. A high win rate with a small payoff ratio is a few big losses waiting to happen. |
| Average bars held, time in the market | how long a trade lasted (in bars of the chosen interval) and the share of bars with a position open. |
| Sharpe kept under realistic fills | the Sharpe after the realism check as a share of the headline Sharpe ("not run" until you ask for it). Well below 100% means the result leaned on optimistic fills. |
| Variants tried, deflated Sharpe, shuffled-returns p-value, realism level | how much searching went into the result and how it holds up against luck; read them next to the Sharpe, never without them. |

The table always has these rows in this order; a number that cannot be computed reads `n/a`.

Buy-and-hold uses the same instruments, window, capital and costs. With several symbols it is equal
weight. Both curves are drawn together, then both drawdowns.

## How much to trust this

- **Trial count**: how many variants have been tried on the same symbols (any window, any rules)
  in this Crucible home, unless you named a family. The report also deflates the result against
  every backtest in the home, other instruments included: trying an idea on one ticker after
  another is a search too, and a strong verdict needs to survive both counts. Variants tried by
  hand or with another tool are not in either, so they are lower bounds. Each one makes
  a good-looking result more likely by chance. Crucible counts them, so asking an agent to "try a few
  more numbers" visibly lowers the next result's reliability. That is the point.
- **Deflated Sharpe ratio (DSR)**: the probability that the Sharpe ratio is genuinely positive after
  accounting for the trial count and the shape of the returns. Under 0.95 is a warning.
- **Random re-ordering test**: the same bar-to-bar moves (gap and bar together) shuffled in
  time 100 times, the rules run on each. It reports how many shuffles matched or beat the strategy
  and a p-value of (that count + 1) / (101): it never says 0, because 100 shuffles cannot show
  that. If shuffled data does as well, the timing of the rules has not been shown to matter. Passing
  it means the strategy benefits from the real order of returns (trends, calm and stormy periods); it
  does not mean the edge will continue.
- **Realism level**: how pessimistic the fill assumptions were. The default (Level 1) fills at the
  signal bar's close with a small cost; `--realism-check` re-runs the rules with next-bar fills, a
  spread and latency (Level 2) so you can see how much survives.

## Warnings

Each warning has a code and a sentence. They are not decoration: any of `ci_includes_zero`,
`very_few_trades`, `few_trades`, `single_instrument`, `short_sample`, `dsr_low`, `null_not_beaten` or
`contaminated`, `fragile_to_execution` or `realism_not_checked` stops the verdict from being "some
evidence". Others (`wide_interval`, `multiple_trials`, `no_better_than_buy_and_hold`) are context
that belongs in your decision.

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
