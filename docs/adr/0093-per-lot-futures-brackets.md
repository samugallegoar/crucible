# ADR-0093: Futures brackets per lot, measured from each fill; off-schedule bars are not executable

Status: accepted (2026-11-17). Refines ADR-0090, decision 5. The owner set the requirements
(milestone C3b, refinement B): brackets live in the execution layer, are in ticks and are measured
from actual fill prices. Ambiguous configurations are refused. Partial fills and multiple entry
prices are tested, and the intrabar assumptions stay conservative.

## Context

The futures simulator (ADR-0090) kept one stop level and one target level per position. They were
anchored at the fill that opened or flipped it:
- an add at another price kept the first fill's levels;
- a partial reduction left them as they were;
- a bracket exit always closed the whole position.

A position built from two fills at 100.00 and 102.00 was therefore stopped as if both had been
bought at 100.00. That is not "measured from actual fill prices".

The simulator also let a pending order fill at the open of any bar in which the held contract
traded. That included off-schedule bars: ADR-0091 found that the prints in the minute after a
close are not part of any scheduled segment, and nothing executes on them.

## Decision

1. **Lots.** Every fill that opens or adds to a position (kind `signal`) creates a lot with its own
   stop and target in ticks from its own fill price.
   - A reduction by the strategy closes lots FIFO, splitting the oldest lot when needed; the
     surviving lots keep their levels. FIFO is the clearing convention, and the ledger already
     realizes P&L FIFO.
   - A flip closes every lot and anchors one new lot at the flip price.
2. **Rolls keep the lots.** A roll that keeps the position re-opens the same quantities, in the same
   order, at the new contract's roll price. Every lot's levels shift by the executed roll spread
   (new minus old), as the single pair did before. A roll combined with a target change opens one
   fresh lot.
3. **Stops first within a bar, for every lot.** If any lot's stop is touched in a bar, only stops
   fill in that bar. Every lot whose stop is touched exits at its stop, or at the open when the open
   is already beyond it. No target fills: the order of the high and the low inside the bar is
   unknown, and the worse path is assumed. Otherwise each lot whose target trades through
   (`target_fill_through_ticks`) exits at its limit, paying fees only. Each exiting lot is its own
   fill.
4. **Re-entry after a partial bracket exit.**
   - With `require_signal_reset`, the stopped lots are not bought back while the strategy's decided
     target is unchanged: the effective target is the position left after the exit.
   - Once the decided target changes, it trades normally, opening new lots with their own levels.
   - For a full exit this is the previous rule (flat until the signal changes).
   - `allow_immediate` re-buys at the next eligible open.
5. **Off-schedule bars are not executable.** `bars` may carry an `on_schedule` column (from
   `cme_sessions`, ADR-0091). On a bar where it is false, no signal order fills at the open or
   close, and no stop or target is evaluated: the Globex segment is closed, so a resting order
   cannot execute there. A null is refused. Without the column every bar is eligible, as before.
6. **Brackets are whole ticks.**
   - `stop_ticks`, `target_ticks` and `target_fill_through_ticks` must be plain integers.
   - A float (8.0, 0.25), a boolean or a string is refused, and the message says that a percentage
     stop is not accepted in the futures path.
   - The strategy-spec percentage stops (`risk.stop_loss_pct`, ADR-0082) are refused by the
     futures signal bridge (ADR-0094), not translated.
7. **The policy record states every rule above** (anchor per lot, FIFO, same-bar rule, off-schedule
   rule), and `SIMULATOR_VERSION` is bumped.

## Alternatives considered

- **One level pair from the average entry price.** It is not any fill's price. It moves the stop of
  lots already held whenever another lot is added, and a stop at the average can sit inside the
  range of a lot that is already losing more than its distance. Rejected.
- **Re-anchor the whole position at the latest fill.** It moves the older lots' stops on every add,
  so it is the same defect in the other direction. Rejected.
- **LIFO reductions.** They keep the oldest lots open longer and do not match the ledger's FIFO
  realization, so the two would disagree. Rejected.
- **Let targets fill in a bar where another lot's stop fills.** That assumes the favourable side of
  the bar was reached first or as well, which is optimistic and not knowable from OHLC bars.
  Rejected (AGENTS.md section 1, rule 4).
- **Evaluate stops on off-schedule prints.** A resting stop on Globex does not execute while the
  segment is closed. Treating the print as executable would book a fill the exchange would not have
  made. Rejected.

## Consequences

- **No change for single-lot runs.** A run that only goes flat to N contracts and back has one lot
  per position, so its fills and money are unchanged; the real-data acceptance figures (ADR-0090,
  ADR-0092) still hold.
- **Scale-in and scale-out strategies get correct brackets.** That includes strategies whose target
  moves between several contract counts. The simulator version changes, so their runs are a new
  identity.
- **Off-schedule bars must be marked.** A strategy that runs on CME bars passes `on_schedule` (the
  futures signal bridge does) so that orders cannot fill in a closed segment.
