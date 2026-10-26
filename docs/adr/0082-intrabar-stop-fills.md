# ADR-0082: Intrabar stop and take-profit fills in the strategy-spec path

Status: accepted (2026-10-25)

## Context

A spec's `risk.stop_loss_pct` / `take_profit_pct` were measured and *decided* on closes only:
`_walk` compared `close[i]` against the level, and the exit was booked at that close. Two
consequences the 2026-10 audit flagged:

- a bar whose low pierced the stop but closed above it did not trigger at all, so a
  mean-reversion rule kept a position the market had already stopped out — the optimistic
  direction;
- a take-profit whose close exceeded the target filled at that close, i.e. *beyond* the target,
  which no limit order can guarantee.

The docs said so ("stops are close-based"), but a spec author reads `stop_loss_pct: 5` as "I am
out at −5 %", and the engine did not enforce that.

## Decision

`risk.stop_fill` (new, default `level`) selects the model:

- **`level`**: the bar's `high`/`low` reach the level, and the fill is
  - the **open** when the bar gapped through the level (the only price actually available),
  - otherwise the **level** itself;
  - when one bar touches both the stop and the take-profit, the **stop** fills (the worse
    outcome, ADR-0012's adverse rule);
  - the vectorized engine values that bar at the fill via a new optional `exit_price` column in
    the `SignalFunction` output, so the position's return over that bar is
    `exit_price / close[t-1] − 1` rather than `close[t] / close[t-1] − 1`.
- **`close`**: the pre-ADR-0082 model, unchanged, for reproducing earlier runs.

The `exit_price` column is the general seam: any signal may provide it, and `scores` keeps its
`ts`/`symbol`/`score` schema so run artifacts do not grow a column.

## Alternatives considered

- **Trigger on highs/lows but keep filling at the close.** Cheaper, but it fills a stop at a
  price better than the stop whenever the bar recovers — optimistic in the other direction, and
  it would have been easy to mistake for a fix. Rejected.
- **Make it the promoted path's job (submit real STOP orders).** The right end state, but the
  promotion adapter re-emits target weights each bar; turning a spec's stop into a resting stop
  order needs order lifecycle management across bars (cancel on exit/flip, resize on partial
  fills). That is a feature, not a correction; the promoted run currently exits at the next open,
  which is never better than the level, and the docs say so.
- **Support it in the vectorized multi-currency path.** The FX equity model tracks a per-symbol
  quantity and a single FX grid; a per-bar exit price would need the same treatment as `close`
  in both the P&L and the sizing denominator. Refused explicitly instead of silently ignoring the
  column.
- **Keep `close` as the default.** Rejected: the default is what most specs get, and the whole
  point is that the previous default was optimistic.

## Consequences

- **Behaviour change** for any spec with a stop or take-profit. No example or golden uses stops,
  so no golden number moved; the product golden's artifact hash did, because the canonical spec
  now carries `stop_fill` and a spec run's experiment id is derived from it (`docs/COMPATIBILITY.md`).
- A spec with `stop_fill: level` is refused on the vectorized multi-currency path (a clear error,
  not a silent no-op).
- `docs/modules/strategy_spec.md` states the fill rule and the promoted-path caveat; the models'
  docstring says the same at the field.
- Tests: `tests/unit/test_strategy_spec.py` covers a wick trigger at the level, a gap at the
  open, "both touched, stop wins", and the `close` model; `tests/unit/test_vectorized_engine.py`
  covers the engine valuing a bar at `exit_price`.
- Open follow-up: the promoted path submitting real stop orders (above), and a per-bar exit price
  in the FX path.
