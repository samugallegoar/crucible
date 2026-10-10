# ADR-0012: Ladder arrival, trigger, and cap semantics (Levels 2-4)

- **Status**: accepted
- **Date**: 2026-09-16

## Context

Levels 2-4 add latency, spreads, impact, path-dependent order types, and
liquidity caps to bar-resolution data. Each interacts with the intrabar
unknowability problem; every ambiguity must resolve pessimistically and be
pinned in code (extends ADR-0010).

## Decision

**Arrival rules.** `effective_at = created_at + latency` (drawn once per
order from the seeded run rng):
- a bar with `ts <= created_at` is in the order's past — never interacts;
- `effective_at >= bar.ts` — still in flight, skipped;
- `effective_at <= bar.open_time` — full-bar interaction (open-referenced
  fills, whole-bar trigger checks);
- otherwise (mid-bar arrival) — MARKET fills at the **close**, side-adjusted
  (no intrabar benefit); path-dependent types wait for the next bar because
  their trigger cannot be verified after arrival.

**`open_time`.** The feed stamps each bar with the true session open from
the run's calendar when the bar's `event_time` is a session close; otherwise
it falls back to the previous bar's close per symbol (first bar: its own
close). The fallback is a pessimistic lower bound: orders arriving between
the derived and true open are treated as mid-bar.

**Price pipeline (aggressive fills).** reference → ± half-spread (buy at
ask / sell at bid) → slippage/impact adverse adjustment → clamp into
`[low, high]` (I5 raises if a model proposes outside).

**Triggers.**
- Stops: gap-open fills at the open (you pay the gap); intrabar trigger
  fills at the stop, both adverse-adjusted. Strictly through, not touch.
- Stop-limits: arm on the trigger bar, act as a limit from the next bar
  (post-trigger path within the trigger bar is unknowable).
- Trailing stops: trail from the first eligible bar's open, then tighten on
  *closed* bar extremes only — no intrabar credit toward a better exit.
- Aggressive limit crossings take slippage but never fill worse than the
  limit; passive fills execute exactly at the limit (and are `maker` fills
  for maker/taker schedules).

**OCO / bracket ambiguity.** If both legs of an OCO pair could fill in one
bar, the leg with the worse cash outcome for the strategy executes and the
other is dropped (then cancelled by the fill). This implements the original requirements's
"assume the adverse one" for brackets generally.

**Liquidity (Level 3+).** Aggregate fills per symbol-bar are capped at
`max_bar_vol · volume` (I6, enforced with a shared per-bar budget in fill
order); each order is additionally capped at `max_adv · ADV`. Remainders
rest and carry. `queue_bps` requires the bar to trade *through* a resting
limit by that margin before it fills (a poor man's queue position).

**History-dependent models.** ADV/vol come from `MarketStats`, updated only
after a bar's fills are simulated (fills see pre-bar history only). A model
lacking history **rejects the order** with an actionable reason — it never
guesses.

**Algos.** TWAP: equal slices over `algo_bars`, each priced at the bar's
OHLC/4 proxy, adverse-adjusted. VWAP: same slicing priced at (H+L+C)/3 — an
approximation pending Level 5 intrabar data, recorded as a known gap.
PARTICIPATION: `algo_rate · bar volume` per bar at (H+L+C)/3.

## Alternatives considered

- **Fill mid-bar arrivals at a modeled intrabar price**: requires a path
  model; close is the only knowable no-benefit price. Rejected for now.
- **Stop-limit acting within its trigger bar**: grants unverifiable fills;
  rejected (pessimism).
- **Per-order (not aggregate) bar-volume caps**: lets N orders each take
  the full cap from one bar; aggregate is stricter and closer to reality.
- **Volume-forecast VWAP slicing**: needs a causal volume model; deferred.

## Consequences

At daily resolution with realistic (ms) latencies and a proper calendar,
orders still reach the next session's open — latency only bites at intraday
resolution or with extreme values, which is correct. Level 1 semantics are
unchanged (zero latency reproduces ADR-0010 byte-for-byte; the golden
fixture proved it through the refactor). VWAP's proxy pricing and the
queue_bps approximation are tracked in `docs/modules/execution.md` known
gaps.
