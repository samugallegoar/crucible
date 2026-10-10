# What Crucible does not do

Stated plainly, so you can decide whether it is the right tool. These are limits of the product, not
a to-do list.

## It does not give advice or predict

A backtest describes what a rule would have done. It does not say what a rule will do, and Crucible
never concludes that a strategy "works": its strongest verdict is "some evidence", reachable only
when every statistical guard passes.

## It does not trade

- **No broker connection.** There is a simulated venue used to prove that a backtest and a
  paper/live run make the same decisions; no order is ever sent anywhere.
- **No live data or alerts.**

## What it cannot model

- **Instruments**: equities and ETFs, multi-currency symbols, futures and prediction-market
  contracts in the engine. **No options**, no bonds, no order-book instruments.
- **Corporate actions**: dividends and delistings are applied by the event-driven engine; splits,
  spin-offs and mergers raise instead of being guessed. The one-step flow uses adjusted prices.
- **Margin**: Reg-T-style short margin and per-contract futures margins; no percent or SPAN margin,
  and a margin call liquidates the whole book.
- **Execution**: no order-book replay, queue position or tick-level quotes (Level 5). Time-in-force
  IOC/FOK/GTD are refused. The one-step headline run fills at the signal bar's close with a one-bar
  lag, which is optimistic; the realism check and the event-driven levels are the pessimistic view.
- **Taxes, borrow availability, dividends on shorts' recall, fees beyond the cost model.**

## What the data covers

- Daily bars from Yahoo Finance (unofficial: it can change or throttle without notice) or Tiingo
  (official, free key). Intraday bars exist in the engine but Yahoo keeps only about 60 days.
- No fundamentals, news, filings or alternative data.
- Survivorship: a ticker you ask for today exists today. A test of a rule on today's index
  constituents over the past is flattered by the companies that were dropped; Crucible does not
  reconstruct historical membership from a provider.

## What the one-step flow does not do

- One strategy per run; no portfolio of strategies and no parameter sweeps (use `crucible optimize`
  with a config file, which counts every point and reports the probability of overfitting).
- Spec rules are the indicators listed in the [spec reference](strategy-spec.md): no ranking of a
  universe, no volatility targeting, no per-symbol weights.
- Walk-forward and out-of-sample splits are engine features that need a config.

## Scale

A run holds the bars in memory; the replay feed guards at about five million rows. Runs are
single-process apart from parallel sweeps. Daily bars for a few dozen symbols over decades are far
inside the limits.

## Hosting

Crucible runs locally. It has no hosted service, no account system and no remote MCP endpoint, so
clients that only accept a remote URL cannot attach it directly.

Per-module limits, for contributors, are the "Known gaps" at the end of each page in
[`docs/modules/`](../modules/).
