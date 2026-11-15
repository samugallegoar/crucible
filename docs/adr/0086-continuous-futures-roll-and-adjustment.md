# ADR-0086: Continuous futures — a causal volume roll, ratio adjustment for research, unadjusted for fills

Status: **proposed** (2026-11-14). It changes results, so by AGENTS.md §10 it is written and reviewed
before the builder exists; the choices below are the conservative ones, and the four the owner should
confirm are listed at the end.

## Context

The five raw datasets (`es|nq|ym|rty|nkd_1m_raw`, ADR-0085) hold individual contracts. Fathom's work
order (milestone C2) asks for a continuous series in two versions: **adjusted** for research and
**unadjusted** for executable prices, with roll metadata. Two choices move every downstream number and
cannot be undone by a later user: *when* the series switches contract, and *how* the history is
adjusted. This ADR measures both on the actual data (read-only analysis of the built datasets,
2026-11-14) instead of adopting a convention.

**Trade date.** A Globex session opens 17:00 Central the evening before its date and closes 16:00
Central. Adding two hours to a bar's UTC open puts the evening open on the next calendar date and the
16:00 CT close on the same date, in both standard and daylight time, so `trade_date = date(open + 2h)`.
(The CME calendar milestone replaces this with `CMES` sessions and must agree with it.)

**What the data says.** A causal state machine was run on every root: hold one contract; on trade date
`d` look only at the *next* contract in the quarterly chain; switch when its volume on `d-1` exceeds the
held contract's volume on `d-1`; never switch back; if the held contract has no bars on `d` it has
expired and the switch is forced.

| Root | Switches | Days from the switch to the old contract's last bar (median / p10 / p90 / min / max) | Switches forced by expiry |
|---|---|---|---|
| ES | 66 | 4 / 3 / 4 / 2 / 6 | 0 |
| NQ | 66 | 4 / 3 / 4 / 2 / 6 | 0 |
| YM | 66 | 4 / 3 / 4 / 3 / 6 | 0 |
| RTY | 37 (starts 2017-07) | 3 / 3 / 4 / 2 / 4 | 0 |
| NKD | 66 | -1 / -1 / 0 / -5 / 1 | 1 |

- **The liquid roots never switch early on noise.** The earliest switch in ES, NQ and YM is 6 calendar
  days before the old contract's last bar, and RTY's is 4: no hysteresis was needed.
- **Expiry is the third Friday** of the contract month for ES, NQ, YM and RTY (65 of 66 last bars in
  each of the first three, 36 of 37 in RTY; the one other in each is a Thursday). NKD's last bar is mostly the second Thursday (52 of 65, with 8 first Thursdays, 4 second Fridays, 1 Wednesday): its
  expiry is not a simple weekday rule.
- **Volume leaves the front early for the equity indices and late for NKD.** Median share of the held
  contract in (held + next) volume, by sessions before its last bar:

  | Sessions before the last bar | 0 | 1 | 2 | 3 | 5 | 8 |
  |---|---|---|---|---|---|---|
  | ES | 0.01 | 0.10 | 0.14 | 0.18 | 0.45 | 0.98 |
  | NQ | 0.01 | 0.09 | 0.14 | 0.20 | 0.42 | 0.99 |
  | YM | 0.01 | 0.08 | 0.12 | 0.17 | 0.43 | 0.99 |
  | RTY | 0.00 | 0.07 | 0.11 | 0.18 | 0.51 | 0.99 |
  | NKD | 0.15 | 0.64 | 0.75 | 0.83 | 0.97 | 0.99 |

  NKD's liquidity migrates in the last one or two sessions, so a volume rule alone holds an NKD
  contract through its final trading day.
- **Roll gaps** (next minus front at the last minute both traded on the session before the switch):

  | Root | Median gap | Largest gap as % of price | Sum of gaps (points) |
  |---|---|---|---|
  | ES | -5.00 pts (-0.207%) | 1.24% | +670.0 |
  | NQ | -1.12 pts (-0.020%) | 1.37% | +3,772.2 |
  | YM | -60.50 pts (-0.298%) | 1.14% | +2,762.0 |
  | RTY | +5.30 pts (+0.341%) | 1.18% | +322.4 |
  | NKD | -20.00 pts (-0.098%) | 1.31% | -1,310.0 |

- **What each adjustment does to the oldest data:**

  | Root | Difference adjustment moves the oldest bar by | Ratio adjustment multiplies it by |
  |---|---|---|
  | ES | -670 pts (-61.5% of its 1,090 level) | 0.9616 |
  | NQ | **-3,772 pts (-204.6% of its 1,844 level: negative prices)** | 0.8387 |
  | YM | -2,762 pts (-27.1%) | 1.0315 |
  | RTY | -322 pts (-23.0%) | 0.8616 |
  | NKD | +1,310 pts (+13.5%) | 1.0397 |

## Decision

1. **The roll rule is the causal volume rule above, with an expiry backstop.** The contract held on
   trade date `d` is a function of sessions before `d` only: the *next* contract in the quarterly chain
   replaces it when its volume on `d-1` exceeds the held contract's (`threshold`, default `1.0`), or
   when the held contract is `backstop_sessions` sessions (default `1`) or fewer from its last trading
   session. Rolls are one-way. The switch is effective from the first bar of trade date `d` (the evening
   session that opens at 17:00 CT, an hour after `d-1`'s close), so the decision is known before the first
   bar it governs. The first contract is the one with the most volume on the first session. The
   backstop keeps the series out of a contract's final session (NKD would otherwise be held through it);
   it never triggers for ES, NQ, YM or RTY on this data, where volume leaves five sessions earlier.
2. **Expiry comes from contract metadata, not from the price path.** The scheduled last trading session
   of each contract is the date of its last observed bar (the exchange publishes it in advance; the
   specification, not the price, fixes it). This is a documented approximation: a contract specification
   table (and the `CMES` calendar) replaces it, and it is exact for liquid contracts, where 65 of 66 last
   bars fall on the third Friday.
3. **Two series from one rule, with the same timestamps.**
   - **Unadjusted** (`{root}_1m_cont_v1`): each bar is the held contract's own bar, carrying a `contract`
     column; prices are real traded prices; volume is the held contract's. It jumps at a roll. This is the
     **only series fills and money are computed on** (tick costs, point value, prop-firm rules).
   - **Ratio-adjusted** (`{root}_1m_cont_ratio_v1`): every bar before a roll is multiplied by
     `ratio = next / front`, both taken at the last minute both contracts traded on the session before the
     switch, compounded backwards over all later rolls; volume is not scaled. Percent returns inside every
     contract are preserved exactly and prices stay positive.
   - **Rolls** (`{root}_1m_rolls_v1`): one row per roll: from and to contract, the effective trade date,
     `decided_at` (end of the deciding session, when the decision became knowable), the reference time, the
     two reference prices, `ratio`, `gap_points` and `reason` (`volume` or `backstop`).
4. **No difference (Panama) adjustment.** It moves NQ's oldest data by -204.6% of its level, so the
   earliest adjusted NQ prices are negative on this data, which breaks any return, ratio or log feature;
   the ratio series keeps every price positive (the largest factor on the oldest data is 0.8387).
5. **A position held across a roll is closed in the old contract and opened in the new one, and pays for
   both.** The jump in the unadjusted series is not P&L; the rolls table says where it is. C3 charges a
   round trip at each roll (the worse outcome for the strategy; AGENTS.md §1.4).
6. **No mixing inside a session.** A minute with no trade in the held contract is a gap, not a bar from the
   other contract.
7. **The builder is a pure function of the raw datasets and its parameters** (`threshold`,
   `backstop_sessions`, the root's expiry source). The parameters go in the dataset manifest's `source`
   string, so a different rule is a different dataset, and a rebuild reproduces the content hash.
8. **The adjusted series is safe only for scale-invariant use.** A bar's adjusted level depends on *later*
   rolls, so a price level, a difference in points or a fixed price threshold computed on it would carry
   information about the future carry. Returns, ratios of prices and z-scores of returns are unaffected
   (every bar in a window shares the future factor). The DSL (milestone C4) must restrict level operators on
   adjusted data to scale-invariant forms, and the lookahead harness must include a case for it.

## Alternatives considered

- **Roll a fixed number of days before expiry** (a calendar rule). Rejected as the primary rule: the data
  show the liquid roots migrate with a tight, stable timing that a calendar rule only approximates, and it
  ignores NKD's different behaviour. Kept as the *backstop*.
- **Roll on open interest.** Not available: `ohlcv-1m` has volume only.
- **Roll on the same day's volume.** Rejected: the day's volume is known only at its end, so the rule would
  look ahead. The previous session's volume is used.
- **Look at every later contract, not only the next.** Rejected: far contracts have almost no volume, and
  that is exactly how the first analysis went wrong (pairs of non-front contracts produced "crossovers" 232
  to 266 days from expiry). The state machine only compares the held contract with its successor.
- **Difference adjustment.** Rejected (decision 4).
- **No adjustment, only the unadjusted series.** Rejected: a return computed across a roll would include
  the gap; the work order asks for both series.
- **Provider continuous symbology (`ES.c.0`, `ES.v.0`).** Already rejected in ADR-0085: the roll dates would
  not be ours to record.

## Consequences

- The builder, three dataset schemas (`contract` column and the rolls table), and the C3 roll-cost charge
  are new work; none exists yet. This ADR changes no code and no result.
- ES, NQ, YM and RTY roll about four calendar days before the old contract's last bar, which is a
  property of the data and of this rule, not a parameter of the exchange.
- The backstop is **not calibrated**: the data cannot say whether one session or two is better for NKD
  (the held share is 0.64 one session out and 0.75 two out). One session is the choice that changes least.
- Ratio adjustment does not preserve dollar P&L per point of old data: money is always computed on the
  unadjusted series.
- The `trade_date` rule uses a fixed two-hour shift; if the `CMES` sessions disagree with it on any date,
  the calendar wins and the analysis here is re-run.
- The figures above come from throwaway analysis scripts over `data/processed`; they are not in the
  repository and no result here depends on anything outside the five datasets. The builder milestone
  must reproduce the switch counts, the timing table and the gap table from its own output as an
  acceptance test, so these numbers stop being a claim of this document and become a check.

## For the owner to confirm

1. The causal volume rule on the previous session, with `threshold` 1.0 and no hysteresis.
2. `backstop_sessions` = 1 (never hold a contract into its final session).
3. Ratio adjustment for research, unadjusted for fills, and no difference adjustment.
4. A position across a roll pays a full round trip.
