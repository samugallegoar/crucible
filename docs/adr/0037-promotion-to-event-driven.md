# ADR-0037: Promotion to the event-driven engine

- **Status**: accepted
- **Date**: 2026-09-19

## Context

The original requirements's Phase 6 scope names "promotion to event-driven" as a deliverable:
rerun a vectorized experiment's config through the event-driven engine at
Level ≥2, presumably to check a signal that looked good frictionless
still holds up under real spread/latency/impact costs. The prior
session's handoff notes flagged this as genuinely undecided between two shapes:

1. **Replay the vectorized run's already-computed weight schedule** as a
   fixed sequence of target orders through the event-driven engine.
2. **Re-run the signal function itself** inside a thin event-driven
   `Strategy` wrapper, so it re-decides at each bar using the portfolio
   state and history actually available at that point in the *promoted*
   run.

This affects results (a genuine "what does promotion even mean"
question), so it's decided here per AGENTS.md §10.

## Decision

**Re-run the signal function (option 2).** A replayed schedule (option 1)
computed its weights frictionlessly, in one shot, against the vectorized
run's own equity curve — it has no way to react to a Level 2+ fill that
landed at a worse price than the frictionless run assumed, or to a
portfolio that is now smaller than the schedule expected because of
accumulated costs. That isn't testing whether the signal holds up under
realistic frictions; it's just paying realistic costs against a plan the
signal never actually made under those conditions. Re-running the signal
function is the only shape that is actually promotion in the sense the original requirements
means it — a real re-decision, at every bar, under the same friction the
strategy would face live.

**Mechanism**: `PromotedSignalStrategy` (`crucible/experiments/
promotion.py`) is a generic event-driven `Strategy` adapter, parameterized
entirely through `ctx.params` (same convention as every example
strategy): `signal_entrypoint`, `signal_params`, `bars_dataset`,
`symbols`, `lookback`, `base_currency`. At the first bar event of every
new timestamp it fetches `ctx.data.history(bars_dataset, [OHLCV fields],
symbols, as_of=ctx.clock.now, lookback=lookback)` — a PIT-legal,
already-collected `DataFrame` — feeds it to the wrapped `SignalFunction`
exactly as the vectorized engine would, takes the *latest* row's `score`
per symbol as a target weight, and sizes/submits an order the same way
`TrendFollower`/`Momentum` already do (`equity * weight / price`,
`ROUND_DOWN` toward zero — conservative for either sign). **No extra lag
is added by the wrapper** — the event-driven engine's own Level 1+
next-bar-open fill timing (ADR-0010) already supplies the realistic
execution delay; adding another shift on top would double-lag the signal
relative to what it experiences in the vectorized engine, defeating the
comparison promotion exists to make.

**`promote_config`** (same module) rewrites a vectorized-validated
`ExperimentConfig` (i.e., one that already passed
`assemble_vectorized_engine`'s refusals, ADR-0036 — so it is by
construction free of corporate actions, universe, multi-currency,
futures, and risk) into one whose `strategy` points at
`PromotedSignalStrategy` and whose `realism_level`/`execution` are the
caller's chosen Level 2+ target. Two parameters are **required, not
defaulted**:
- `execution: ExecutionConfig` — guessing a spread/latency/impact model
  would fabricate an assumption about realistic costs the caller never
  actually made (AGENTS.md §10).
- `promotion_lookback: int` — guessing a history window risks silently
  starving the signal of data it needs (too small ⇒ a different, wrong
  computation with no error to show for it) or wasting memory (too
  large) — the caller knows their signal's actual window requirement.

The symbol universe is read directly from the bars dataset via
`store.read(...).select("symbol").unique()` at config-construction time,
**not** through a PIT accessor — this happens before any simulated
engine exists (there is no `as_of` to violate), the same class of
one-time, whole-dataset read `run_experiment`'s own quality gate and
manifest hashing already perform. This avoids extending the `PITAccessor`
Protocol with a "list all symbols" method purely to serve this one
config-construction step.

## Alternatives considered

- **Replay the precomputed schedule** (option 1): rejected above — not
  genuine promotion, just friction applied to a plan made without it.
- **A `SignalFunction` → `Strategy` compiler that inlines the signal's
  own polars expressions into engine-native calls**: rejected as
  significant unnecessary complexity; `PromotedSignalStrategy` re-calling
  the same Python function at each bar is simple, correct, and the
  performance cost (recomputing a rolling window per bar rather than
  vectorized once) is exactly what a "promotion, run rarely, for
  validation" step is expected to cost — this is not the fast research
  path.
- **Extend `PITAccessor` with `symbols_as_of`** to keep symbol discovery
  inside the simulated PIT domain: rejected for this priority — the
  symbol list is needed once, at config-construction time, not by any
  code that runs inside the simulation loop; reading the dataset directly
  at that point is not a PIT violation (nothing simulated has an `as_of`
  yet) and avoids a Protocol change whose only caller would be this one
  config-building step.
- **Defaulting `execution`/`promotion_lookback` to "reasonable" values**:
  rejected — see Decision; both are results-affecting assumptions that
  belong to the researcher, not a guess baked into the library.

## Consequences

- `crucible/experiments/promotion.py` (new): `PromotedSignalStrategy`,
  `promote_config`.
- Promoted runs go through the **existing, unmodified**
  `experiments.runner.assemble_engine`/`run_experiment` pipeline — no new
  artifact-writing code was needed; a promoted config is simply an
  `ExperimentConfig` like any other from that point on.
- `PromotedSignalStrategy` re-evaluates the full `lookback`-window signal
  computation at every bar (not incrementally) — acceptable for a
  validation step run occasionally, not for a hot path.
- No test asserts numeric agreement between a promoted run and its
  vectorized source (unlike ADR-0035's Level 0/1 agreement test) — Level
  2+ friction is *supposed* to change the result; the acceptance test
  instead asserts the promoted run trades and its equity is meaningfully
  worse under heavy assumed costs than the frictionless vectorized run on
  the same signal and data, which is the property that actually
  distinguishes "genuinely re-decided under friction" from "somehow
  unaffected by the friction it was given."
- Known gap: no CLI surface for promotion (`promote_config` +
  `run_experiment` is a library-level call chain only, same status as
  `run_vectorized_experiment`, ADR-0036).
