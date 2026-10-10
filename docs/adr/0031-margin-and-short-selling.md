# ADR-0031: Margin requirement and margin-call liquidation for shorts (Phase 5, priority 1)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

Phase 4 closed with every acceptance criterion demonstrated (ADR-0030);
Phase 5 scope is "Borrow availability/cost, margin engine with
liquidation, financing rates, futures specs/rolls/MTM," with acceptance
"golden tests against hand-computed ledgers for a short, a margin call,
and a futures roll." This ADR covers the first, foundational slice:
margin accounting and short-selling.

Before this priority, nothing in the engine modeled margin at all.
Mechanically, a short was already *possible* — `PositionState.apply`
(Phase 1) correctly handles a position flipping through zero and
accumulates `realized_pnl` with the right sign regardless of direction,
proven by ADR-0026's dividend-on-a-short test — but nothing *governed*
it: `InsufficientCashLimit` (ADR-0028) "always ALLOWs a SELL" by design
(a sell never needs cash), meaning a strategy could short an unlimited
notional with zero collateral. `core.types.TransactionType` already
carried `BORROW`/`FINANCING`/`MARGIN_CALL` members from the Phase 0
scaffold, anticipating this work but never implementing it.

Two design questions had no precedent: what margin model to use (real
margin rules are broker/jurisdiction-specific and far more elaborate than
a backtesting engine needs to be useful), and what happens when a margin
call fires — is it a hard stop, a resize, or a liquidation, and if
liquidation, how much.

## Decision

**A simplified, documented Reg-T-style model, not a broker-accurate
one.** Margin requirement for a short position is `notional ×
margin_rate`, where `notional = Σ|short qty · mark|` (mark-to-market,
never cost basis — margin requirements track current value, not entry
price) and `margin_rate` is a configurable multiplier: `initial_margin_rate`
(default 1.5 = 150% of notional, the standard Reg-T initial margin for a
short) gates *opening or increasing* a short; `maintenance_margin_rate`
(default 1.3 = 130%) gates *continuing to hold* one. This is real Reg-T's
shape (initial stricter than maintenance) without claiming to be an
accurate simulation of any specific broker's actual schedule — both rates
are config, and the module docstrings say plainly that this is a
simplified model.

**Two new risk limits, following the exact composition pattern ADR-0027
established** (`crucible/risk/limits.py`):
- `MarginRequirementLimit` (pre-trade): REJECTs an order that would open
  or increase a short beyond what current equity supports at
  `initial_margin_rate`. Never restricts covering/reducing a short (the
  pessimism rule this module's own docstring already states: a
  risk-reducing order is never blocked), and never restricts a long
  order (leveraged-long buying power is a *different* concern
  `InsufficientCashLimit` already covers via available cash — Phase 5's
  explicit ask is shorts specifically; margin buying power for the long
  side is a known gap, see Consequences). **REJECT-only**, not
  RESIZE-capable — the exact same call `MaxGrossExposureLimit` made in
  ADR-0027 ("computing a safe RESIZE here would need to handle direction
  flips against an existing position correctly... judged not worth the
  complexity yet"), reused verbatim for the identical reason: a short
  order can flip a long into a short (crossing zero), and computing the
  maximum affordable resize under that flip is materially more code than
  the simple over-limit-or-not check this priority needed.
- `MarginCallLimit` (mark, i.e. continuous): FLATTENs the *entire* book
  when equity falls below the total maintenance requirement on short
  positions. Not a partial liquidation (a real broker may sell only
  enough to restore compliance) and not scoped to just the short side
  (a real broker often covers shorts first, leaving longs alone) —
  **reuses the existing, already-tested FLATTEN mechanism exactly as
  ADR-0027 built it**, closing every position via real market orders
  that bypass risk checks on themselves. Computing a true minimum
  partial liquidation is a genuinely harder problem (which positions,
  how much of each, accounting for the equity impact of each partial
  close before deciding the next) that the original requirements do not ask this priority to
  solve, and reusing proven code is strictly safer than building a new,
  untested liquidation algorithm under this priority's time budget. This
  is the conservative choice per AGENTS.md §10 ("assume the worse
  outcome for the strategy") in two senses: it's the worse outcome for a
  strategy that would have preferred a smaller liquidation, and it's the
  choice least likely to hide a subtle new bug in a first Phase 5
  priority. Like `DailyLossFlattenLimit`, a margin call does **not** halt
  future trading — a strategy may reopen a position afterward, and if it
  breaches margin again, it gets flattened again.

**Both rates validate `>= 1.0`** (100% — collateral can never be less
than the position's own value in this model) at construction; no
cross-validation that `initial_margin_rate > maintenance_margin_rate` is
enforced, since the two limits are independently composable objects with
no shared state — documented as the expected relationship, left to the
config author to get right, consistent with how every other pluggable
risk limit in this codebase is independently parameterized.

**Config wiring mirrors every prior limit exactly**
(`experiments/config.py::MarginRequirementLimitConfig`/
`MarginCallLimitConfig`, added to the existing `PreTradeLimitConfig`/
`MarkLimitConfig` discriminated unions; `risk/registry.py` gained the
`"margin_requirement"`/`"margin_call"` keys). No new config surface
pattern was needed.

## Alternatives considered

- **A RESIZE-capable `MarginRequirementLimit`**: rejected for the same
  reason `MaxGrossExposureLimit` stayed REJECT-only (ADR-0027) — the
  direction-flip math (long→short crossing zero) makes "the maximum
  affordable short size" a meaningfully harder computation than this
  priority's scope justified. A future priority can add a RESIZE-capable
  variant behind the same Protocol with no caller change.
- **Partial liquidation on a margin call**: rejected — see Decision.
  Selectively covering only the short side, or only enough to restore
  compliance, are both real refinements a future priority could add
  (they'd need a new `RiskAction` or a `FLATTEN`-variant that takes a
  target subset/amount); reusing whole-book FLATTEN ships a *correct*,
  conservative behavior now rather than an *elaborate but unverified*
  one.
- **Deriving margin requirement from cost basis (`avg_cost`) instead of
  mark**: rejected — real margin requirements are mark-to-market by
  definition (that's *why* a price move against a short can trigger a
  call at all); using cost basis would make `MarginCallLimit` structurally
  incapable of ever firing from a price move, defeating its purpose.
- **A single combined `MarginLimit` handling both pre-trade and mark
  checks**: rejected — `PreTradeLimit` and `MarkLimit` are different
  Protocols with different `check()` signatures (order-scoped vs.
  book-scoped); every existing limit in this codebase respects that
  split, and margin's two checks (can-I-open vs. can-I-keep-holding) map
  naturally onto exactly that split anyway.

## Consequences

New: `crucible/risk/limits.py::MarginRequirementLimit`, `MarginCallLimit`,
`_mark_or_raise` (a small helper both use — a held position's mark,
guaranteed present once `portfolio.equity()` has already succeeded,
since `equity()` itself refuses when a held position lacks one). Config:
`MarginRequirementLimitConfig`, `MarginCallLimitConfig`. Registry:
`"margin_requirement"`, `"margin_call"` keys.

Tests: `tests/unit/test_risk_limits.py` (+10 — opening within/beyond
margin, never blocking a cover, a long→short flip correctly gated, a
short→long flip correctly ungated, rate validation for both limits, a
margin-call allow/flatten pair). `tests/integration/test_margin.py` (new,
3 — **hand-computed ledger tests per AGENTS.md §7**, satisfying half of
Phase 5's the original requirements acceptance criterion): a full short round trip (short
50@100, price drops to 80, cover 50@80, realized gain exactly 1000,
verified against the engine's *own* fill/ledger output, not re-derived
from it); a short rejected outright for insufficient initial margin; a
margin call triggered by an adverse price move (short 50@100, price
jumps to 140, `MarginCallLimit` FLATTENs, forced cover at 140, realized
loss exactly -2000). No golden-fixture (`tests/golden/`) change — margin
limits are opt-in risk config, not applied automatically, and no example
config enables them.

No `ExperimentConfig` top-level field was needed (unlike settlement lag,
ADR-0028) — margin, like every other risk limit, is purely
`RiskConfig`-scoped and opt-in.

Known gaps, explicitly deferred to later Phase 5 priorities (the original requirements's
full scope, not addressed here):
- **Borrow cost**: no periodic fee accrues on a short position yet
  (`TransactionType.BORROW` exists in the scaffold, unused). A real short
  costs a stock-loan fee over time; this priority only gates *opening*
  and *holding* a short via margin, not its ongoing carrying cost.
- **Financing rates**: no interest on margin cash balances
  (`TransactionType.FINANCING`, also scaffolded, unused).
- **Futures specs/rolls/MTM**: entirely unaddressed — a distinct,
  large feature (contract specs, daily MTM settlement instead of
  deferred P&L, roll mechanics) that the original requirements's acceptance criterion lists
  as a separate golden-test target ("a futures roll") from margin/shorts.
- **Leveraged-long margin** (buying a long position beyond 100% cash on
  margin, as opposed to a short): `InsufficientCashLimit` already
  prevents spending more cash than available, which happens to also
  prevent uncollateralized long leverage today, but there is no
  *margin-specific* initial/maintenance check for the long side the way
  `MarginRequirementLimit`/`MarginCallLimit` provide for shorts. A
  symmetric long-margin treatment is a natural, small follow-up.
- `MarginRequirementLimit` is REJECT-only (no RESIZE) and
  `MarginCallLimit` liquidates the whole book, not a partial/targeted
  amount — both documented above as deliberate, revisitable
  simplifications, not oversights.
