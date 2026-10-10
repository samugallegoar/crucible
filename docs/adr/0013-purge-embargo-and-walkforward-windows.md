# ADR-0013: Purge/embargo convention and walk-forward's validate window

- **Status**: accepted
- **Date**: 2026-09-17

## Context

The original requirements require "Purged K-fold and Combinatorial Purged CV with
embargo" and, separately, that walk-forward exposes "train/validate/test
windows are first-class config." `docs/GLOSSARY.md` defines `embargo`
("rows after a test block excluded from training to stop leakage through
serial correlation") but never defines `purge`, and neither the original requirements nor
the glossary says whether purge is one- or two-directional, or how
walk-forward's three-way windows relate to purge/embargo at all. Both are
Gate 4 conventions where an ambiguous choice changes what OOS numbers
mean, so AGENTS.md §10 requires resolving it here rather than in code.

## Decision

**Purge is bidirectional, embargo is one-directional.** For purged
K-fold/CPCV, `purge` removes training rows adjacent to *either* edge of a
test block (a training label whose window overlaps the test period leaks
regardless of which side of the test block it sits on). `embargo` removes
an *additional* amount only from the start of the train block immediately
following a test block, matching the glossary's existing one-directional
definition and the standard purged-CV literature (López de Prado,
*Advances in Financial Machine Learning*, ch. 7) that "purged K-fold" and
"CPCV" are named after.

**Walk-forward gets a validate window, not a purge parameter.** Because
walk-forward's train is always strictly before its test (no train data
ever follows test within one split), the bidirectional-purge concept
doesn't apply, and the original requirements never ask for one there — it asks for
train/validate/test windows instead. `WalkForwardSplitter` implements
exactly that: an optional `validate_size` window sits between train and
test. This is the conservative reading of the original requirements' own text rather than
an invented parameter.

Both choices resolve ambiguity toward *more* leakage protection (wider
exclusion, not narrower), consistent with AGENTS.md §1.4 (pessimism on
ambiguity).

## Alternatives considered

- **Embargo bidirectional too** (trim both before and after test):
  rejected — contradicts the glossary's existing "rows *after* a test
  block" wording, and there is no serial-correlation argument for the
  before-test side once purge already covers label overlap there.
- **A `purge` gap parameter on `WalkForwardSplitter`** (reusing the K-fold
  term for the train→test boundary): rejected — the original requirements name
  train/validate/test specifically for walk-forward and never mentions
  purge there; a `validate_size` window subsumes the same protective gap
  without overloading "purge" to mean two different things in two
  splitters.
- **A configurable `step_size` for walk-forward** (independent of
  `test_size`): rejected — the original requirements say results "aggregate OOS only,"
  which implies non-overlapping OOS coverage; an independent stride would
  let test windows overlap and double-count. Advance is fixed to
  `test_size`.

## Consequences

`PurgedKFoldSplitter`/`CombinatorialPurgedCVSplitter` share one
purge/embargo helper (`_purged_train_ranges` in
`crucible/validation/splits.py`); `WalkForwardSplitter` has no purge
parameter at all. `docs/GLOSSARY.md` gains a `purge` entry alongside the
existing `embargo` one. Revisit if a future Monte Carlo/null-test module
(Phase 3 priorities 5–6) needs walk-forward leakage protection beyond what
`validate_size` provides — not needed for priority 1's acceptance.

`_purged_train_ranges` refuses (`ConfigurationError`) rather than silently
truncating when requested purge/embargo would exceed a group's own width —
the pessimism-on-ambiguity principle this ADR already invokes applies to
this edge case too.
