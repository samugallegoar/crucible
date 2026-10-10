# Glossary

Shared vocabulary. Add a term when you introduce it anywhere in code or docs.

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
  trial-count-aware benchmark (ADR-0015).
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
  trials are counted for DSR and PBO (ADR-0008).
- **universe(t)** — the set of tradeable symbols at time t, including names
  later delisted (no survivorship bias).
- **walk-forward** — validation scheme that trains on a period, evaluates
  on the period immediately after, and slides forward; anchored (expanding
  train) or rolling (fixed-width train).
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

**MCP (Model Context Protocol)** — a protocol that lets an agent call tools on a server. `crucible-mcp`
(ADR-0066) exposes the `--json` CLI commands as tools, each run in a fresh process.
