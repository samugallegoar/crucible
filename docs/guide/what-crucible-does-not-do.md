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

## It does not keep you out of the holdout period by force

The futures holdout vault (C6c, ADR-0105) locks Globex trade dates from 2025-01-01 for
`ES, NQ, YM, RTY, NKD` in Crucible's own data path: a read, a run window or a whole-file access that
reaches it raises `VaultLockedError`, every attempt lands in the access log, a registration carries
the complete config hash, and the single evaluation needs a human's admin token. Four residual
risks remain, and they are documented, not solved:

- **Direct file reads.** Anyone with filesystem access can read the Parquet files with another tool.
  The vault guards and logs Crucible's data path; it is not an access-control system. Keeping the
  admin token from an agent is the human's responsibility — and `vault set-admin` refuses a
  non-interactive call for exactly that reason.
- **The ratio-adjusted series carries one constant.** Backward ratio adjustment multiplies every
  pre-2025 bar by the product of the post-2025 roll ratios, which is one constant. Signals must be
  scale invariant (ADR-0094), so that constant carries no usable information; it is recorded anyway.
- **The period was not unseen.** Locking data later does not make it unseen. The declaration records
  the exposure audit: strategy-level work on ES in 2024, the execution simulator's full-span
  buy-and-hold path, and ingestion/integrity counts over the full span.
- **A copy of the store and a copy of the home.** The declaration lives in both and either copy
  locks the period, so a copy does not lift it — but deleting both copies deliberately does. That
  act is outside anything the engine can refuse.

## What the data covers

- Daily bars from Yahoo Finance (unofficial: it can change or throttle without notice) or Tiingo
  (official, free key), and intraday bars (5m, 15m, 30m, 1h) from Yahoo Finance only. Yahoo keeps
  about 60 days of 5-30 minute bars and about two years of hourly bars, so intraday tests are short
  and usually `not_conclusive`. Time-of-day rules: flat by the close (optionally at the closing
  price), exit at a clock time, an entry window and `time` in conditions; no market-on-open orders,
  no day-of-week conditions, and the market-on-close cutoff is the US one (ten minutes).
- CME Globex session hours (the equity-index futures ES, NQ, YM, RTY, NKD) come from a
  transcribed, cited schedule table for 2010-06 to 2027-12 (ADR-0091). Most 2023 holidays and
  Martin Luther King Day 2024 have no archived schedule: those sessions are flagged unverified,
  not guessed. Other futures have no session calendar yet.
- A futures run reads its series at one fidelity level (1m, or 5m/15m causally resampled from the
  one-minute series, ADR-0100). A coarse level does not see the intrabar path, and a causal roll
  then waits for the first coarse bar open at which both contracts have a one-minute bar (at most
  one bar of delay, recorded as an approximation). `fidelity: {cost_detail: commission_only}` is a
  screen: it is optimistic about the cost of trading and says so in the run's approximations.
- A futures batch (`crucible futures batch`) reports every candidate's descriptive metrics (net P&L,
  costs, fills, the conservative intraday drawdown, the minimum equity) AND, since C6a, its
  run's statistics (per-period and annualized Sharpe, mean daily return, PSR, DSR, IC) with their
  intervals and reasons — and it still ranks nothing. A futures run gives no VERDICT: robustness
  and prop-firm rules are C7, so `verdict_level` is null with `robustness_not_assessed`.
- The futures statistics answer "is this distinguishable from the search that produced it?", not
  "will it make money?": DSR counts the distinct candidates in the family's trial registry (not the
  effective number of independent trials, ADR-0104), a submission is an event and not a trial, and
  the IC is a single-root time-series one (no cross-sectional IC, and none at all for a spec or
  Python strategy).
- No fundamentals, news, filings or alternative data.
- Survivorship: a ticker you ask for today exists today. A test of a rule on today's index
  constituents over the past is flattered by the companies that were dropped; Crucible does not
  reconstruct historical membership from a provider.

## What the one-step flow does not do

- One strategy per run; no portfolio of strategies and no parameter sweeps (use `crucible optimize`
  with a config file, which counts every point and reports the probability of overfitting).
- Spec rules are the indicators listed in the [spec reference](strategy-spec.md): no ranking of a
  universe, no volatility targeting, no per-symbol weights.
- Walk-forward evaluation exists (`crucible walk-forward`, ADR-0081) but is a first slice:
  it selects one parameter per fold and reports only out-of-fold metrics. It does not yet
  report the concatenated out-of-fold equity series or its deflated Sharpe, and the
  selection inside a fold is not deflated (the summary says so).

## Prop-firm rules

- The prop-firm simulator is a conservative OHLC approximation, not a tape: it resolves the
  intrabar order against the strategy (the favourable extreme first, then the adverse one, applied
  together), so it can fail an account that a real path would have kept. The bias is one-directional
  (against passing) and declared in every result (`semantics: high_before_low_conservative`).
- A breach is a market liquidation at its trigger price (the breach price, the open when it gapped,
  the close for an end-of-day rule) plus costs and the stress slippage, not a fill at the threshold:
  a fast market can fill worse, and `liquidation_extra_slippage_ticks` exists to measure how much.
- No firm rule value is in the engine: a ruleset is sourced data, and a ruleset read now applied to
  older data is labelled a counterfactual application. C7a ships synthetic rulesets only, so no
  result of it describes a real firm, and a synthetic ruleset can never be `verified`.

## Scale

A run holds the bars in memory; the replay feed guards at about five million rows. Runs are
single-process apart from parallel sweeps. Daily bars for a few dozen symbols over decades are far
inside the limits.

## Hosting

Crucible runs locally. It has no hosted service, no account system and no remote MCP endpoint, so
clients that only accept a remote URL cannot attach it directly.

Per-module limits, for contributors, are the "Known gaps" at the end of each page in
[`docs/modules/`](../modules/).
