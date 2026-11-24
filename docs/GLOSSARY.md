# Glossary

Shared vocabulary. Add a term when you introduce it anywhere in code or docs.

- **return-sequence risk** — how much a backtest's outcome (final value, drawdown, chance of
  loss or ruin) depends on the sample and the order of the returns, estimated by resampling the
  realized history (`validation/paths.py`, ADR-0083). Centred on the realized result, so it is
  **not** evidence of an edge.
- **stationary bootstrap** — a resampling of a time series in blocks whose lengths are geometric
  (Politis & Romano 1994): keeps short-range dependence and the resampled series is stationary; the
  mean block length can be estimated from the data (Politis & White 2004).
- **fan chart** — the P5, P25, P50, P75 and P95 percentile bands of simulated equity paths over time.
- **risk of ruin** — here: the probability that a simulated path ever touches a ruin level (default:
  down 50% from the start), checked at every step.
- **Reality Check / SPA** — White's (2000) and Hansen's (2005) bootstrap tests that the best of
  several candidate strategies beats a benchmark once the search over the candidates is paid for
  (`validation/reality_check.py`, ADR-0083): evidence about an edge, unlike a sequence-risk fan.
- **structure id / parameterization id (DSL)** — `DSX-…` hashes an expression's canonical shape (operators, features, fixed literals, typed parameter placeholders and their binding pattern) and ignores parameter names and values; `DSP-…` adds each parameter's type, value and bounds; `DSC-…` (C4b) adds the compiler and operator versions and the inputs (ADR-0096).
- **holdout vault** — the declared, data-layer-locked period of the futures family (C6c,
  ADR-0105): Globex trade dates from 2025-01-01 for `ES, NQ, YM, RTY, NKD`, open-ended. A read whose
  `as_of` reaches its start (`data/vault.py::vault_start_ns`, the scheduled open of the first
  protected session) is refused unless an authorized evaluation is running. The declaration lives in
  the store root AND in the Crucible home, and either copy locks the period.
- **vault registration** — `VR-<16 hex>`, the identity of one evaluation request: the complete config
  hash, the datasets' content hashes, the `CND-` candidate id and the window (which must lie inside
  the vault). It starts `pending`, becomes `authorized` when a human verifies the admin token, and
  becomes `evaluated` after its single evaluation (or after a crash inside it).
- **open counter** — the persistent, never-decremented number of evaluations the vault has opened
  (`vault.duckdb` table `counter`, mirrored as `opens` in the store's `vault.json`). It is
  incremented BEFORE any row is read, so a failed or crashed evaluation still consumes its
  registration; a database behind the mirror is refused.
- **price exponent (DSL)** — the degree of a DSL node in price (close = 1, close/close = 0); a constant unifies only with degree 0, which enforces ADR-0086 scale invariance node by node.
- **ADV** — Average Daily Volume; participation caps are expressed against it.
- **arrival rules** — which bar an order may first interact with under
  latency, and whether that interaction is full-bar or mid-bar (ADR-0012).
- **artifact schema version** — the integer `schema_version` in `manifest.json`
  (`experiments/artifacts.py::SCHEMA_VERSION`); bumped when an artifact column or key is removed,
  renamed, retyped or changes meaning (`docs/COMPATIBILITY.md` §3).
- **as-of / PIT (point-in-time)** — a query semantics where only rows with
  `available_at <= as_of` are visible. The only data access the engine allows.
- **available_at** — when a market participant could first have known a datum
  (publication/receipt time). Mandatory column on every dataset.
- **checkpoint** — a canonical-JSON file holding the engine, component and
  strategy state at a session boundary, from which `resume_from` continues
  the run (E7, ADR-0041).
- **client order id** — the id a caller gives an order when sending it to a venue;
  the engine's order id is used as the venue's, so venue events name engine
  orders directly (ADR-0043).
- **contamination flagging** — checking whether an evaluation-mode run's
  data window overlaps a prior optimization-mode trial in the same family;
  a hit means the "held-out" evaluation may have leaked into the search
  that chose it (ADR-0021).
- **candidate / candidate id (`CND-`)** — what a futures evaluation IS, independent of the window
  it was run on (ADR-0103 decision 4): the strategy (a DSL expression by its canonical structure
  and parameterization ids, a spec by its canonical dump, an entrypoint by its path and
  parameters), the size, the root and the four datasets, the execution and costs sections, the
  fidelity and the session and signal sections. The id excludes the window, the warm-up, the run
  name, the family, the capital and the statistics, so one candidate run on four windows is one
  candidate and `total_trials` counts it once. `candidate_id(config)` in
  `experiments/futures_config.py`.
- **CPCV** — Combinatorial Purged Cross-Validation; the priority-1
  splitter (`CombinatorialPurgedCVSplitter`) used for walk-forward-style
  purged cross-validation. Not the same technique as CSCV, below.
- **CSCV** — Combinatorial Symmetric Cross-Validation; PBO's specific
  split scheme (Bailey, Borwein, López de Prado & Zhu 2015), implemented
  as CPCV configured symmetrically with purge=embargo=0 (ADR-0015).
- **DataFeed seam** — how the engine gets market events: an injectable
  `feed_factory` builds a `DataFeed` per run (default `ReplayDataFeed`,
  which stamps bars-then-actions and yields in `(ts, seq)` order); the
  engine merges it with its own event queue (ADR-0039).
- **design note** — the short note (in the PR description) an
  agent writes before code: problem, placement, interfaces touched, tests, docs, compatibility
  impact (AGENTS.md §4).
- **DSR** — Deflated Sharpe Ratio; the Probabilistic Sharpe Ratio (PSR)
  evaluated against the expected maximum Sharpe a family's trial count
  would produce by chance. Computed per-period, never annualized
  (ADR-0015).
- **embargo** — rows after a test block excluded from training to stop leakage
  through serial correlation.
- **event_time** — when the thing happened or the period it refers to.
- **ex-date / pay-date** — a dividend's two dates (ADR-0026):
  entitlement (who gets paid, and how much) is resolved from the position
  held on the *ex-date*; the cash itself only moves on the later
  *pay-date*. Received on longs, paid on shorts.
- **execution backend** — what the engine drives to execute orders: the ladder
  simulator (backtest, paper) or `VenueExecution` (live); built by
  `execution_backend_factory` (ADR-0043).
- **factor regression** — OLS of a strategy's returns on factor return
  series (market/size/value/momentum/quality/low-vol); the intercept
  (alpha) and its t-stat measure return unexplained by the factors (ADR-0020).
- **feed cursor** — the `(ts, seq, id)` of the last event popped from the
  feed; stored in a checkpoint so resume can skip the feed through it and
  refuse if the event there differs (ADR-0041).
- **feed head (preload)** — the one event a `PeekableFeed` has pulled but not
  yet delivered; a lazy-feed checkpoint stores it and `preload` restores it
  (ADR-0044).
- **feed-first merge** — at equal `ts` the feed's event runs before the
  engine queue's (dividend pay-date events), reproducing the old single-heap
  order (ADR-0039).
- **FX marking vs. trading role** — two different rates for two different
  purposes (ADR-0009/0025): *marking* (valuing cash/positions
  in base currency for equity/reporting) uses the *mid* rate; *trading*
  (an actual conversion that moves ledger cash) uses the *adverse* side
  of the quoted spread — the ask when buying the quoted currency, the
  bid when selling it. Never mixed: marking never moves cash, and a real
  conversion never gets the favorable side.
- **fill range** — `[low, high]` of a bar widened to its bid/ask quotes when it carries them
  (`BarEvent.fill_range()`); the bound of invariant I5 (ADR-0060).
- **fill** — an execution of (part of) an order: quantity at a price at a time.
- **funded in local currency** — the multi-currency convention of both engines (ADR-0025,
  ADR-0062): a foreign position is paid for from its own currency's cash, so an FX move changes only
  the accumulated pnl, not the principal; equity is marked at the FX mid.
- **fx_to_base** — the mid FX rate (symbol currency to base) at a fill's
  timestamp, recorded on every fill row (`"1"` in base currency) so attribution
  can convert the fill (ADR-0047).
- **generated block** — text between `<!-- BEGIN GENERATED: name -->` markers in a doc, produced from
  code by `tools/docgen.py` and checked by a test (`docs/INVENTORY.md`, `docs/SCHEMAS.md`,
  `docs/adr/README.md`).
- **golden surface** — the artifact set covered by byte-identity golden
  tests (config.yaml, the Parquet artifacts, metrics.json); provenance and
  presentation files are excluded by ADR-0011.
- **golden test** — byte-identical comparison of run output against a stored
  reference fixture.
- **holder of record** — the position held before a dividend's ex-date; the
  engine resolves entitlement from it, so a same-day fill neither earns nor owes
  the dividend (ADR-0046).
- **incremental fold** — `InMemoryLedger.fold` applying only newly appended transactions to a
  cached running state instead of replaying the whole ledger; equals the full fold
  (`_fold_full`) by property test (ADR-0054).
- **inert addition** — a new optional config field, column or key whose default reproduces the old
  behaviour; the only golden hashes allowed to move are `config.yaml` and `experiment_id`
  (`docs/COMPATIBILITY.md` §6).
- **information barrier** — the engine-enforced guarantee that a strategy
  cannot observe data with `available_at > now`.
- **initial margin / maintenance margin (futures)** — per-contract amounts on a
  `FuturesSpec`: initial is required to open or increase a position, maintenance
  to keep it; enforced by the margin limits against equity (ADR-0050).
- **intrabar ambiguity** — the unknowable price path within a bar; resolved
  pessimistically (adverse outcome for the strategy).
- **layering rule** — a module may import only from its own package or a layer below it; enforced by
  `import-linter` (`docs/ARCHITECTURE.md`).
- **lazy stamping** — a feed that assigns event ids and sequence numbers when
  the engine pulls each event, not up front (`DataFeed.stamping = "lazy"`);
  needed when events depend on orders placed during the run (ADR-0044).
- **lookahead** — any use of information before its `available_at`. Raises
  `LookaheadError`.
- **MAE / MFE** — Maximum Adverse / Favorable Excursion of a trade.
- **manifest** — the identity record of a dataset version (schema version,
  content hash, row count, source, build time).
- **Monte Carlo (resampling)** — return-order shuffle, start-date shift,
  block bootstrap: resamples a run's *already-computed* return series, no
  re-simulation (ADR-0017). Distinct from Monte Carlo
  *perturbation* (execution assumptions or strategy parameters varied and
  re-simulated via `experiments/perturbation.py`, ADR-0018) — the two
  are related but not the same mechanism.
- **no-time-travel rule** — an order never fills against a bar whose
  `available_at` is at or before the order's creation time; that bar's open
  is in the order's past (ADR-0010).
- **notional (risk)** — `PortfolioView.notional(symbol, qty)`: base-currency
  value of `qty` units at the last mark, FX-converted and multiplied by the
  futures multiplier; what the risk limits compare against thresholds (ADR-0045).
- **null test** — re-runs the engine against *altered* market data
  (shuffled return order, sign-flipped, synthetic GBM) to check whether an
  apparent edge is distinguishable from what a strategy would produce on
  data with no genuine structure (ADR-0019). Distinct
  from Monte Carlo, which varies config or resamples returns but never the
  underlying bars.
- **OOS (out-of-sample)** — data not used to fit or select a
  strategy/model; only OOS performance is aggregated into validation
  results.
- **mark** — a valuation of the portfolio at a point in simulation time.
- **PaperRuntime** — the backtest engine driven through the DataFeed seam
  plus a `PaperBroker` (ADR-0040).
- **PBO** — Probability of Backtest Overfitting (CSCV method); needs a
  trials × periods returns panel, so it's not computable from a single
  run (ADR-0015) — `crucible optimize` assembles one from a parameter
  sweep's trials (ADR-0022).
- **PeekableFeed** — one-event lookahead over a feed that enforces I9
  (ADR-0039).
- **pnl_fx / pnl_price** — the trade log's split of a round trip's base-currency
  PnL: the price move valued at the entry FX rate, and the rate move on the exit
  value; they sum to `pnl` exactly in Decimal and to float precision in the
  output columns (ADR-0049).
- **price basis** — whether a bar's prices are `raw` (as traded) or `adjusted` (split
  and dividend adjusted); declared in every import spec (no default) and recorded in the
  dataset manifest's `source` (ADR-0052).
- **PSR** — Probabilistic Sharpe Ratio: the probability the true Sharpe
  exceeds a stated benchmark, given the estimate's sampling noise (skew/
  kurtosis-corrected). DSR is PSR evaluated against a specific,
  trial-count-aware benchmark (ADR-0015). On the futures path (ADR-0103) it is computed on the
  UNANNUALIZED per-period Sharpe of the daily returns on the fixed capital; the annualized Sharpe
  is presentation only.
- **PSR on fixed-capital returns / daily return (futures)** — the daily number every futures
  statistic stands on (ADR-0103): `(closing_equity_t - closing_equity_{t-1}) / initial_capital`,
  with the previous trade date's closing equity and the capital on the first date. It does NOT
  compound; a trade date with on-schedule bars and no position is a real zero return, and a trade
  date with no valid bars is `missing_sessions` — excluded and counted, never zero-filled.
- **purge** — training rows removed from both edges of a test block whose
  label window could overlap it; distinct from `embargo`'s one-directional
  trim (ADR-0013).
- **pessimism rule** — when the simulator cannot know, it assumes the worse
  outcome for the strategy.
- **plateau / spike** — a sensitivity-surface diagnostic (R4.4): performance that holds up at parameter values near the chosen
  one is a "plateau" (evidence of real structure); a sharp drop-off is a
  "spike" (overfitting red flag). Measured as a relative drop-ratio from
  the chosen point to its immediate neighbors (ADR-0016).
- **quoted spread** — the `quoted` spread model: half of the wider of a bar's open and close
  bid/ask spread, so a buy pays the ask and a sell gets the bid; raises on a missing or crossed
  quote (ADR-0060).
- **realism level** — rung 0–5 on the execution-realism ladder; carried as
  metadata on every result.
- **position episode** — a vectorized run's unit of "trade": a maximal run of bars with the same
  nonzero lagged-weight sign, closed when the weight returns to zero or flips; pnl is before costs
  (ADR-0061). Not the FIFO lot round trip of the event-driven trade log.
- **portfolio constructor / target weight** — `PortfolioConstructor.construct`
  maps signal scores/expected returns to target weights (fractions of
  equity); `ctx.targets.set/set_all` hands a weight to the engine, which
  resolves it into a real order immediately (diff against the current
  position, floor to an integer qty). Six built-ins split into diagonal
  (equal weight, fixed fractional, vol target, risk parity, fractional
  Kelly — ignore cross-asset covariance) and correlation-aware
  (mean-variance, full sample covariance via `numpy.linalg.solve`,
  ADR-0029).
- **reconciliation (external venue)** — on `resume_from(venue_state="external")`
  the venue's stream position and open orders are compared with the
  checkpoint; any difference is refused with an itemised message (ADR-0044).
- **resume equivalence** — a run checkpointed at any session boundary and
  resumed finishes byte-identically to the uninterrupted run (I13,
  ADR-0041); proven by `tests/integration/
  test_checkpoint_resume_equivalence.py`.
- **risk engine / risk limit / risk action** — `RiskEngine` runs `pre_trade`
  on every order and `on_mark` on every mark, returning a `RiskDecision`
  (ALLOW/REJECT/RESIZE/FLATTEN/HALT). `CompositeRiskEngine` composes small
  `PreTradeLimit`/`MarkLimit` units, checked in order, first non-ALLOW
  wins. HALT is a one-way stop for the rest of the run; FLATTEN closes
  every position via real market orders that bypass risk checks on
  themselves (ADR-0027).
- **multi-strategy / attribution / marginal risk contribution** —
  `strategy.multi.MultiStrategy` runs several independent strategies
  inside one engine call, sharing one portfolio; every order/fill carries
  a `strategy_id` tag. Attribution (`analytics.attribution`) is realized
  cash flow only, bucketed onto the equity mark grid; `strategy_correlation`
  (Pearson, on raw $ PnL deltas) and `marginal_risk_contribution`
  (`Cov(pnl_i, portfolio_pnl)/SD(portfolio_pnl)`, summing exactly to
  `SD(portfolio_pnl)`) are the attribution measures (ADR-0030).
- **round trip** — a matched entry/exit pair in the trade log (FIFO lot
  matching per symbol); the unit of hit-rate and holding-period stats.
- **margin requirement / margin call** — (ADR-0031): a short
  position's collateral requirement, mark-to-market, `notional ×
  margin_rate` (initial rate to open/increase, default 1.5×; maintenance
  rate to keep holding, default 1.3×). `MarginRequirementLimit` REJECTs
  an order that would breach the initial requirement; `MarginCallLimit`
  FLATTENs the whole book when equity falls below the maintenance
  requirement (not a partial/targeted liquidation — a documented
  simplification).
- **borrow cost / margin financing** — (ADR-0032): periodic
  carrying costs accrued at every mark, Actual/365. Borrow cost =
  `notional × short_borrow_rate` on a short position (the stock-loan
  fee); margin financing = `|cash| × margin_financing_rate` on a
  negative (debit) cash balance. Both end-of-period-balance-based
  (not intraday time-weighted), both `0.0`-default (zero behavior
  change), neither counted in `fees_paid` (commissions only).
- **futures multiplier / mark-to-market (MTM) settlement / roll** —
  (ADR-0033). `multiplier`: dollars of real P&L per 1.0 of
  quoted price movement, per contract. MTM settlement: unlike an
  equity's unrealized PnL sitting in the position, a futures position's
  *entire* unrealized move since the last mark realizes to cash **every
  mark** (`BacktestEngine._settle_futures_mtm`), via a synthetic
  close-then-reopen transaction pair that rebases `avg_cost` to the
  current mark. Roll: closing an expiring contract and opening the next
  — needs no dedicated mechanism, since each contract month is its own
  `Symbol` and a roll is just two ordinary orders.
- **tick size / tick value / point value** — the smallest price step of a futures contract, its
  dollar value per contract, and the dollars per 1.0 of price (ES: 0.25, $12.50, $50). The table
  is `crucible/data/futures_specs.py` (ADR-0090).
- **causal roll** — a roll executed as two trades (close the old contract, open the new one) at the
  OPEN of the first simulated bar at or after the roll decision at which both contracts have a raw
  one-minute bar opening: on one-minute bars that is the first minute both contracts traded, on a
  resampled grid it waits for such a bar open (at most one coarse bar of delay, never earlier). Raw
  prices price both legs; the default of the futures simulator. Its labelled alternative is the
  reference-price approximation (ADR-0090, ADR-0100).
- **fidelity level** — how finely and how expensively a futures run reads its series: a
  `resolution` (`1m`, or `5m`/`15m` causally resampled) and a `cost_detail` (`full`, or
  `commission_only`, which is optimistic). The named presets are `screen` (15m, commission only),
  `standard` (5m, full) and `full` (1m, full); it is part of the run id (ADR-0100).
- **resampled bucket / partial bucket** — the bars a coarser resolution aggregates: the bar ENDS in
  `(k·m, (k+1)·m]` minutes inside ONE scheduled session segment, labelled by the bucket's end
  clipped to the session close. A `partial` bucket is one clipped by a session open or close that
  is not on the `m`-minute grid; an empty bucket produces no bar (ADR-0100).
- **submission / batch** — a batch is one base futures config plus an ordered list of candidate
  expressions (only the strategy and run name change per candidate); every candidate is a
  *submission* (recorded in the registry's `submissions` table with its `CND-` id), while a *trial*
  is one distinct run. `submission_count` counts submission EVENTS (every submitted candidate plus
  every standalone run), `unique_candidate_count` the distinct candidates, and `total_trials` what
  a deflation is divided by — in C6a the same as the unique count (ADR-0100, ADR-0103).
- **effective trials (`effective_trials`)** — an ESTIMATE of how many effectively independent
  trials a futures family holds, from its candidates' pairwise daily-return correlations
  (C6b, ADR-0104). Distances are `d = sqrt((1 - rho) / 2)` and agglomerative AVERAGE-LINKAGE
  clustering merges while the smallest mean inter-cluster distance is `<= sqrt((1 - rho*) / 2)`;
  the count left is `effective_trials`, always between 1 and the number of candidates. It is
  threshold-dependent (`rho*`, default 0.5) so it always travels with its sensitivity table for
  `rho*` in {0.3, 0.5, 0.7, 0.9}, it is labelled `assessment: "estimator"`, and one pair with
  no valid correlation makes it `unavailable` rather than smaller.
- **supplementary DSR (`dsr_effective_trials`)** — the same Deflated Sharpe Ratio reading with
  `N` replaced by `effective_trials`, keeping the primary `dsr`'s per-period Sharpe and
  cross-trial dispersion (C6b, ADR-0104). It sits under a `supplementary` key BESIDE the primary
  `dsr`, which is deflated by `total_trials` and stays the conservative result; it never feeds a
  verdict, and it is null with a reason when the estimate is unavailable.
- **CSCV panel** — the trials x periods returns matrix PBO needs (CSCV, ADR-0015/0070): one
  column per period, one row per candidate, and the SAME periods for every row. Nothing is
  filled, so a candidate whose trade dates differ makes PBO unavailable. On the futures path a
  batch's panel is its distinct candidates' daily returns on the batch window, and a
  walk-forward's is a separate full-window run per distinct candidate (`in_sample`): the
  selected out-of-sample chain is never a PBO input (ADR-0104).
- **information coefficient (IC)** — on the futures path, the per-trade-date Spearman correlation
  between a DSL expression's score at each decision bar and the close-to-close return over
  `statistics.ic_horizon_bars` bars of the signal series; a pair crossing a session edge or a
  contract change is dropped, and a trade date with fewer than 10 valid pairs gives no IC. Only a
  DSL expression has one (a spec or Python strategy records null with a reason). ADR-0103.
- **Globex trade date / session regime** — the CME trading day a minute belongs to: its session
  opens the evening before (Monday's on Sunday 17:00; before 2012-11-19 at 15:30) and closes on
  the trade date. A regime is the regular week of a period (open, close, daily breaks); holidays
  are per-trade-date overrides. The table is `crucible/data/cme_session_table.py` (ADR-0091).
- **unverified session** — a scheduled session touching an unsourced window of the CME session
  calendar: built from the regime because no archived document gives its holiday hours; strict
  callers refuse it (ADR-0091).
- **off-schedule bar** — a bar outside every scheduled segment (typically a print in the minute
  after a close); not tradable, never a closure signal (ADR-0091).
- **lot (futures)** — one fill's contracts inside a position, with its own entry price, stop and
  target in ticks; reductions close lots FIFO (ADR-0093).
- **scale invariance** — a signal rule's decisions do not change when every price is multiplied
  by the same positive constant; required on the ratio-adjusted continuous series, whose levels
  depend on later rolls, and checked statically and with prices x16 and x1/16 (ADR-0094).
- **session open** — the start of the trading session containing a timestamp
  (`session_open_at`); the dividend holder-of-record cutoff (ADR-0046).
- **settlement lag / available cash** — T+N delay before sale
  proceeds join spendable cash; `PortfolioBalances.available_cash` is the
  settlement-lag-aware subset of `cash` — always ≤ `cash`, never used by
  `equity()`. Only incoming cash (sale proceeds) lags; a purchase debits
  buying power immediately. `BacktestEngine.settlement_lag_days` (0 =
  disabled); `risk.InsufficientCashLimit` is the first consumer
  (ADR-0028).
- **scenario fan-out** — one config run under several execution-assumption
  sets (optimistic/base/conservative/extreme); the decay report shows how
  fast the edge erodes as assumptions harden (R3.10).
- **simulated venue** — `SimulatedVenue`, the local reference exchange for
  `LiveRuntime`: own order state and account, fills priced by the backtest
  models; not an independent matching engine (ADR-0043).
- **stub (Protocol)** — a Protocol with no implementation, marked `stub` in
  `docs/EXTENSION_POINTS.md` and named in its module's *Known gaps*.
- **through (limit fill)** — the bar traded strictly beyond the limit price;
  a touch (equal) never fills at Levels 0–2 (pessimism; queue models arrive
  at Level 3).
- **trial / trial family** — one parameter evaluation / the scope in which
  trials are counted for DSR and PBO (ADR-0008). A futures family's `total_trials` counts distinct
  candidates (`CND-`), not run directories (ADR-0103).
- **universe(t)** — the set of tradeable symbols at time t, including names
  later delisted (no survivorship bias).
- **walk-forward** — validation scheme that trains on a period, evaluates
  on the period immediately after, and slides forward; anchored (expanding
  train) or rolling (fixed-width train).
- **futures fold** — one train/test pair of a futures walk-forward (ADR-0101): fold k trains on the
  base window's trade dates before its test window (`rolling`: the N immediately before;
  `anchored`: every date from the first one) and tests on the M dates that follow. Test windows are
  contiguous and never overlap; a trailing remainder shorter than M is not evaluated and is
  reported as `unused_trade_dates`.
- **terminal exit** — the cost a walk-forward fold pays for ending flat (ADR-0101): the contracts
  open at the fold's last test bar times one side of the full per-contract cost (fees, half the
  spread and slippage ticks), booked on the fold's last trade date. Pessimistic by design, so no
  fold closes an open position for free and no position is carried into the next fold.
- **signal warm-up (futures)** — the `window.warmup_trade_dates` Globex trade dates immediately
  before a futures run's window that the run READS only to compute the signal and then drops: no
  fill, mark, ledger row, position or roll comes from them (ADR-0101).
- **comparison key (futures)** — what makes two futures artifacts comparable (ADR-0102): the
  simulator version, the `fidelity` level, the execution section (fill timing, roll execution,
  strictness, bracket policy), the session section and the signal input. Root, contracts, cost
  amounts, strategy, window, family and capital are deliberately NOT in it, because a USD daily P&L
  is scale free; two members with equal keys may be correlated, and a pair whose keys differ is
  reported `incompatible` with the differing paths.
- **overlap (trade dates)** — the trade dates two members BOTH have, i.e. the inner join of their
  daily series. It is the only basis of a cross-run correlation: a date one member does not have is
  excluded, never filled with a zero P&L (a zero would be an invented flat day). A walk-forward's
  flat FOLD is different: its zero rows are real, because being flat was a decision (ADR-0102).
- **session boundary** — the point after the last event of a timestamp was
  fully handled (dispatched, callbacks flushed, marked); where `run_until`
  returns and `checkpoint` is legal (ADR-0041).
- **Snapshottable** — protocol for a component with resumable run state:
  `snapshot()` returns codec values, `restore(state)` mutates in place
  (ADR-0041).
- **StatefulStrategy** — optional strategy protocol
  (`checkpoint_state`/`restore_state`) for state not held in `ctx.state`;
  called instead of `on_start` on resume (ADR-0042).
- **settlement bar** — the flat final bar a Polymarket contract gets at its window end (1.0
  for the winning side, `settlement_floor` for the loser), paired with a `delisting`
  corporate action so the engine liquidates positions at the outcome (ADR-0052).
- **shift discipline** — (ADR-0035): the vectorized engine's
  structural anti-lookahead guarantee. A `SignalFunction`'s raw `score` is
  never used directly as a position; the engine unconditionally computes
  `weight = score.shift(lag_bars).over(symbol)` (`lag_bars >= 1`, no
  opt-out) before `weight` ever multiplies a return. This makes position
  `t` provably unable to read `score` at index `>= t`, regardless of what
  the signal function computed internally — the vectorized-path analogue
  of the event-driven engine's `as_of`-gated `LookaheadError` (there is no
  per-event checkpoint in a vectorized batch computation, so the guarantee
  has to be structural instead).
- **vectorized weight / turnover cost** — (ADR-0035): `weight` is a
  signal's lagged `score`, interpreted directly as a target portfolio
  fraction (no engine-side ranking or leverage normalization — a signal
  wanting that does it itself before returning `score`). `turnover_t =
  sum_symbol(|weight_t - weight_{t-1}|)`; multiplied by
  `(slippage_bps + commission_bps) / 10_000` as the vectorized engine's
  approximation of the event-driven engine's per-fill bps costs (which
  apply to actual traded notional, not portfolio-fraction turnover —
  a documented, deliberate approximation, not a bug).
- **promotion** — (ADR-0037): rerunning a vectorized experiment's
  signal function through the event-driven engine at Level 2+, via
  `PromotedSignalStrategy`, which *re-evaluates* the signal at every bar
  under real friction and actual (eroded) equity — not a replay of the
  vectorized run's precomputed weight schedule, which couldn't react to
  a worse-than-assumed fill or a smaller portfolio and so wouldn't
  actually test the signal under real frictions.
- **trial-registry finalization (parallel sweeps)** — (ADR-0038):
  `run_experiment` splits into a parallelizable compute phase (quality
  gate, engine, metrics, Monte Carlo — touches no shared state) and a
  serial finalize phase (trial registration, DSR, contamination — the
  only part touching the shared `trial_registry.duckdb`). A parallel
  sweep (`run_experiment_parallel`) always finalizes in the parent
  process, in the caller's config order, never in a worker and never
  racing on completion order — the property that keeps a parallel
  sweep's results byte-identical to running the same configs
  sequentially (E1), not just crash-free.

**Strategy spec** — a versioned YAML/JSON description of a trading rule (entry, exit, sizing, stops)
that Crucible compiles to a vectorized signal, so no code is written (ADR-0067).
`docs/guide/strategy-spec.md`.

**Buy-and-hold benchmark** — the same symbols, window, capital and costs held from the first bar; every
one-step result is shown next to it (ADR-0068). With several symbols: equal weight.

**Verdict level** — the product's honest conclusion: `no_edge_detected`, `not_conclusive` or
`some_evidence`; never a claim that a strategy works. `docs/guide/reading-a-report.md`.

**Home folder** — where `crucible backtest` keeps fetched data, runs and the provider cache
(`CRUCIBLE_HOME`, `crucible config set-home`).

**MCP (Model Context Protocol)** — a protocol that lets an agent call tools on a server. `crucible-mcp`
(ADR-0066) exposes the `--json` CLI commands as tools, each run in a fresh process.

**Ruleset** — a versioned, sourced YAML file of one prop-firm program's rules (identity,
instruments and their contract weights, phases, typed rules, an attribution per value and the
`not_modeled` gaps). The engine knows rule kinds, never a firm; a released version is immutable and
`ruleset_sha256` is its canonical content hash (ADR-0106). `docs/modules/prop.md`.

**Rule-day** — the trading day of one rule, from *its own* reset time and time zone (17:00 Chicago
by default): the instant the daily-loss reference resets, a soft lock lifts and the scaling plan
takes the next limit. A bar belongs to the rule-day of its OPEN time, and the last bar of a rule-day
is known causally from the CME session calendar's scheduled close, never from the next bar (ADR-0106).

**Breach price** — the exact price at which a threshold rule's basis touches its money threshold,
solved in integer ticks and rounded against the strategy: floor for a long (equity falls with
price), ceiling for a short. Touching the threshold is a breach, so the comparison is `<=`
(ADR-0106).

**Joint pessimism** (`high_before_low_conservative`) — the conservative OHLC approximation of the
prop-firm overlay: the favourable extreme (high for a long, low for a short) updates the high-water
marks *before* the adverse extreme is tested, and both are applied even when no single path inside
the bar produces both. It is an upper bound on harm, not a path claim, and biases only against
passing (ADR-0106).

**Counterfactual application** — a ruleset read now (`as_of`, `effective_from`) applied to a data
window that starts before it took effect. Every pre-2025 run under current rules is one, and the
attempt result says so (`counterfactual_application: true`, ADR-0106).

**Censored attempt** — an attempt the data ended before it resolved (the last rule-day is incomplete
per the CME session calendar). It is its own outcome class, never folded into a failure rate
(ADR-0106).

**Evaluation status** — what a prop-firm ruleset's declared gaps allow a result to claim:
`complete` (nothing unmodeled, or only immaterial rules), `conditional_on_modeled_rules` (a
material rule is unmodeled) or `blocked` (a critical one is). `material_unmodeled` names them
(ADR-0106).

**Evidence** — where a rule value comes from (ADR-0107 section 7): `official_quote` (an official
page), `owner_provided` (the owner pasted it; `provided_by: owner`, the URL may be null and the
saved text is hashed), `assumption` (a named default the owner accepted where the firm is silent,
with its rationale) or `conflict_resolution` (a genuine contradiction resolved to the stricter
reading). Every rule declares one, and a synthetic attribution can never be verified.

**Sensitivity scenario** — a full ruleset with one conflict's alternative value switched in, id
`<conflict_id>#<index>`, label `sensitivity`. It is simulated and reported beside the primary
result, never presented as an official plan (ADR-0107 section 7). The primary scenario is
`primary`, label `official`.

**Attempt / start date** — one prop-firm account simulated from one Globex trade date (the
attempt's START) under one ruleset's phases. A prop evaluation starts one attempt on every trade
date of a futures run's window with an on-schedule bar; the attempts OVERLAP (two starts a day
apart share most of their trade dates), which is why their statistics need a block bootstrap rather
than an i.i.d. one (ADR-0107 section 4).

**Complete start** — a start whose horizon fits in the data, `d + H <= last trade date`. Complete
starts are never censored, so they are the denominator of the pass probability `p = passes /
complete starts`; the bounds over ALL starts (`p_low`, `p_high`) are reported beside it
(ADR-0107 section 5).

**Horizon outcome** — `horizon`: the analyst's horizon H was reached with the attempt unresolved.
It is not a firm's rule and not a failure: a `timeout` is a firm's own time limit ending a phase,
and a `censored` attempt is one the data ended before `d + H`. The three are separate classes
(ADR-0107 section 4).

**Effective independent attempts** — `n / H` for `n` complete starts and horizon H trade dates: how
many non-overlapping attempts the sequence is worth. On a one-year window with H = 20 it is about
twelve, which is why an interval over 250 overlapping starts is not twelve times narrower than one
over twelve independent attempts (ADR-0107 section 5).

**Payout cycle** — the span between two withdrawals on a funded account. Eligibility windows that
declare `since_last_payout` count only rule-days after the previous withdrawal; the first cycle
starts at the phase's start (ADR-0107 section 9).

**Practical eligibility** — whether the exact plan may be traded by the exact execution mode:
`eligible`, `eligible_conditional` (no critical blocker, but at least one `effect: condition`
compliance obligation the simulation cannot prove, e.g. orders only through the firm's API, each
listed) or `blocked_by_compliance` (a critical compliance rule such as a ban on automated trading
applies to this ruleset and this `execution_mode`). A mechanically successful attempt under a
blocker is never a practically valid pass, and under a condition it is a `conditionally_valid_passes`
(ADR-0107 section 11).

**`becomes_immaterial_if`** — the audited fact that would change a `not_modeled` entry's materiality:
on a `material` entry what would let it be read as immaterial, on an `immaterial` entry what would
make it bind. It is a condition on the materiality, never a downgrade: the declared materiality
stands until an audit establishes it (ADR-0107, amendment of 2026-11-23).

**`unlimited` vs `unknown`** — `unlimited` is an explicit source value (a payout cap the firm
states is uncapped); `unknown` is a value the sources do not give. In a rule it means the rule
cannot be modeled and goes to `not_modeled`, with one bounded exception: a payout cap
(`payout.max_usd`, `max_usd_by_payout`) accepts `unknown`, the simulation then pays what the other
terms allow and the payouts and cash statistics are labelled `upper_bound`. `unknown` is never
read as `unlimited` and never as zero. A numeric sentinel (>= 1,000,000 USD for a cap) is refused
(ADR-0107 section 7).

**Image transcription (`official_image_transcription`)** — an evidence type for a firm value that is
printed only inside a saved picture (Topstep's XFA scaling-plan ladder is the first): the attribution
carries the image's own sha256, its path under the private snapshots root, the values exactly as
printed, and who transcribed them when. The self-check (`crucible.prop.sources`, `crucible prop
validate --snapshots-root`) verifies the image FILE by its hash and never compares the transcription
with page text, because the numbers are only in the image. A transcription is a named person's
reading, so it is checked for existence and for the file's bytes — the owner still confirms the
ruleset (ADR-0107, amendment of 2026-11-23).

**Supporting source** — an attribution on a rule that supports its basis, timing or units WITHOUT
carrying its value (the page sentence that says a tier is read at the session close). Held to the
same self-check as the value's own source, so a quote never hides inside a description.

**Floor rung** — the first rung of a `scaling_plan` ladder when it declares no threshold: the size
for every balance below the second rung's threshold, which is how a zero or negative balance has a
tier instead of none. A ladder keyed on `min_balance_usd` reads the closing BALANCE and takes its
boundary from its own `comparison` (`>=` keeps a balance exactly on a threshold in the upper rung,
`>` keeps it in the lower one).

**`upper_bound`** — the label on a cash number computed against a value the sources do not state
(`cash_estimate_status: upper_bound`, `PayoutRecord.bound: upper_bound`): the payout paid as much
as every other term allowed, so the real amount can only be lower. The attempt's `estimate_status`
is then at best `partial`, with the reason "payout cap unknown". Pass/fail outcomes are unaffected.

**Session-calendar coverage gap** - an attempt whose trade dates reach a CME session the table
could not source (`verified: False`, built from the regular-week regime: the 2023 holidays other
than Labor Day, Christmas and New Year, and MLK 2024). The attempt lists it
(`session_calendar_gaps`, `"<first>..<last>"` in the table's own Chicago days, which is why the
2023-11-24 session lands in the Thanksgiving 2023 window that starts on 2023-11-22) and its
estimate becomes `partial` with the reason `session calendar unsourced <first>..<last>`: a
session-relative `flat_by`, a rule-day boundary and an EOD test computed over that day are not
sourced numbers.

**Activity requirement** — a rule kind that requires at least N qualifying rule-days in EVERY
rolling window of M days (`calendar_days` or `trading_days`), where a qualifying day satisfies a
`qualifies_if` predicate (minimum trades, minimum absolute or signed P&L). It is the mirror of
`inactivity` (a maximum gap since the last traded day) and its violation action is explicit
(`fail` or `close_account`). A window is judged only once it is full, at that rule-day's close.

**Cost component** — one of the per-side charges an execution costs a prop-firm account, recorded
separately (ADR-0107 section 10 as amended): the brokerage **commission** (the firm's
`per_side_usd`), the **exchange** fee, the **clearing** fee, the **nfa** assessment and **other**.
A ruleset declares, for each of the four non-commission components, whether the firm's commission
contains it (`included`), charges it on top (`excluded`) or does not say (`unknown`). A component
the sources do not state is a GAP, never a zero, and the cost total is never presented as complete
while one is unknown or unpriced.

**Promotion** — a better value a firm publishes for a limited offer (`promotions` on a rule:
`id`, `field`, `value` or `multiplier`, `starts_on`, `ends_on`, `requires`, `purchase_on_or_after`,
`source`). It applies only when every requirement is declared in the run's participant profile and
matches and the declared `purchase_date` falls in the window; `ends_on: unknown` never continues
past the ruleset's `as_of`; anything missing or `unknown` leaves the base value and is reported
(`promotion <id> not applied: <reason>`). The promoted value is a property of the run, recorded per
attempt in `promotions_applied`, never of the file.

**Assumption kind** — what KIND of default a rule assumption is: `section7_default` (the documented
ADR-0107 section 7 default), `provisional_conservative` (the source is silent or soft and the
pessimistic reading is temporary) or `owner_decision` (the owner ruled on it). REQUIRED on every
assumption entry, so a review knows what to re-check when a page changes.

**Breach on fill** — an `evaluated: intraday` loss threshold crossed by realized P&L or by the
costs of a fill is a breach at THAT fill's timestamp, flat or not: the basis tested is the
post-fill one, the fill's own commission, spread and slippage included, and a position still open
is liquidated at that fill's price (ADR-0106, amendment of 2026-11-23).

**session_entry_block** — the overlay event recorded when a session-close `flat_by` window refuses
an entry: the flat_by rule's own id and a reason (`entry blocked: flat_by_1510_ct until 17:00 CT`).
A `news_entry_block` is the same for a news window and `entry_blocked` for a lock;
`resize` under the size rule is reserved for a size limit that actually clipped.

**Participant profile** — the run's immutable declaration of who its account is, as a flat mapping
from classification dimension to value (`cme_membership_status: non_member`,
`nfa_assessment_eligibility: fcm_member`). A ruleset never states one, so it is a RUN input
(`--participant-profile FILE`, MCP `participant_profile`); it is required as soon as a commission
declares a component `excluded`, its canonical SHA-256 is recorded in the artifact and is part of the
evaluation id, and using it keeps the cost estimate `conditional` (`participant profile declared by
the run, not stated by the firm`) — never `complete`.

**Classification dimension** — the one name a fee row uses to say whom it is written for
(`cme_membership_status`, `nfa_assessment_eligibility`, …). Dimension names are identifiers
(`^[a-z][a-z0-9_]*$`), not a fixed enum, and each row brings its own; `none` marks a charge the
source says is the same for every participant (with value `all`). A component is priced only when
the profile declares the row's dimension and matches its value: a missing or `unknown` value is a
gap (`classification <dim> not declared`), and there is no default and no fallback to the only row
there is.

**Cost-assumption file** — the YAML a user passes to price the cost gaps the sources leave
(`--cost-assumption FILE`): `name`, `kind`, `description`, `provided_by`, `status: unverified`,
`evidence` and `amounts` keyed by root, each root a list of `{covers, per_side_usd, unit}`. It
prices only the root and components it names (no extrapolation), an `unknown` component it prices
is ADDED (the pessimistic direction), it may not override an `included` or an already-priced
`excluded` component, and it never turns a gap into a complete cost: the estimate is `conditional`,
and the file's SHA-256 plus the gaps it priced and the gaps it left are recorded in the artifact.
`kind` states what the amounts CLAIM: a `point_estimate` is the owner's best single figure (an
amount on a cost the firm already has is refused), an `upper_bound` is a ceiling that fills only the
gaps (an amount on such a cost is skipped).

**Upper-bound cost assumption** — a cost-assumption file with `kind: upper_bound`: an explicit,
versioned CEILING per root and component that prices only the gaps a firm's own sources leave, so a
preliminary analysis can run across every firm before the per-firm cost table is complete
(`rulesets/prop/cost_assumptions/upper_bound_v1.yaml`). It is never a firm's value, it prices no
commission the firm states, and it labels what it claims: `cost_bound: upper` in `summary.json` and
every `attempts.parquet` row, the cash statistic `lower_bound` when it priced every remaining gap
(the cost is a ceiling, so the net cash can only rise; a gap it left keeps the cash `unavailable`),
the pass probability's reason `costs are an upper bound: the probability is pessimistic and any net
cash under it is a lower bound`, and the comparability note *firms with fewer
sourced cost components receive more of the bound, so cross-firm comparisons under it are
pessimistic for the less documented firms*. It is hashed like a ruleset and versioned by whole file:
a change is `upper_bound_v2.yaml`, never an edit in place once merged.
