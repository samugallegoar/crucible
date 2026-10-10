# ADR-0069: Documentation split by audience, reference pages stay where they are

- **Status**: accepted
- **Date**: 2026-10-10

## Context

The front page and `docs/` read as a contributor manual ("Known limitations & future improvements",
unused extension points, an AGENTS.md checklist) although the product is used by people who ask an
agent for a backtest. The brief asked for `docs/` for users and `docs/contributing/` for the
contributor material.

## Decision

1. **Front door for users**: `README.md` is a product page; `docs/guide/` holds user pages (install and
   connect an agent, the strategy spec, reading a report, an example session, FAQ and
   troubleshooting, what Crucible does not do). `AGENT_GUIDE.md` (repo root, shipped in the package
   and served over MCP) is the page an agent follows.
2. **Contributor hub**: `docs/contributing/README.md` indexes the contributor material and
   `AGENTS.md` stays the entry point and operating manual.
3. **Reference pages are not moved.** `ARCHITECTURE`, `CONVENTIONS`, `SCHEMAS`, `INVENTORY`,
   `EXTENSION_POINTS`, `modules/`, `adr/` and the rest keep their paths. They are cited about 470
   times by `AGENTS.md section N`, code comments, tests, the doc generator and append-only ADRs and
   CHANGELOG; moving them would either break those references or rewrite history that is
   append-only by rule. The hub gives them the audience framing without the churn.
4. **Limits are stated, not promised**: "What Crucible does not do" replaces "future improvements";
   each module's "Known gaps" stays in its page, where a contributor looks.

## Alternatives considered

- *Physically move to `docs/contributing/` and rewrite every reference:* the literal ask. Rejected for
  the cost and for rewriting append-only records. Left as an owner decision (see the PR description):
  the generated docs and tests are parameterized on the paths, so it is a mechanical change if wanted.
- *Redirect stubs at the old paths:* doubles the page count and leaves two sources of truth.

## Consequences

- A user never meets an ADR or an invariant before they have a result; a contributor still finds the
  full manual from `AGENTS.md` and `docs/contributing/README.md`.
- The README no longer lists limitations first; they are in `docs/guide/what-crucible-does-not-do.md`
  and linked from the page that tells a user how to read a verdict.
