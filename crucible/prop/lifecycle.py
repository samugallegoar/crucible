"""The account lifecycle as an explicit state machine (ADR-0107 section 9).

States:

- ``evaluation``: an evaluation account, before or during an attempt;
- ``funded_active``: a funded account trading freely;
- ``payout_pending``: an eligible payout has been decided at this close and not yet applied;
- ``funded_locked_until_reset``: a soft rule liquidated and locked trading until the rule resets;
- ``failed``: a hard rule ended the account;
- ``passed_terminal``: every evaluation phase passed;
- ``censored``: the data ended before the account resolved.

The end-of-day order is fixed: (1) EOD marks, (2) threshold tests, (3) pass conditions,
(4) payout eligibility, (5) withdrawal, (6) post-payout transitions (threshold reset, lock on the
first payout, cycle counters reset), (7) cap and consistency windows reopen. The overlay follows
that order; this module records it so every transition carries its time and cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

AccountState = Literal[
    "evaluation",
    "funded_active",
    "payout_pending",
    "funded_locked_until_reset",
    "failed",
    "passed_terminal",
    "censored",
]

EOD_ORDER: tuple[str, ...] = (
    "eod_marks",
    "threshold_tests",
    "pass_conditions",
    "payout_eligibility",
    "withdrawal",
    "post_payout_transitions",
    "cap_and_consistency_windows_reopen",
)
"""The order of step 9 of ADR-0107, asserted by the lifecycle tests."""

TERMINAL: frozenset[AccountState] = frozenset({"failed", "passed_terminal", "censored"})


@dataclass(frozen=True, slots=True)
class Transition:
    """One recorded state change: when, from, to and why."""

    time_ns: int
    from_state: AccountState
    to_state: AccountState
    cause: str


class Lifecycle:
    """The state of one account and its append-only transition record."""

    __slots__ = ("_state", "_transitions")

    def __init__(self, state: AccountState) -> None:
        self._state: AccountState = state
        self._transitions: list[Transition] = []

    @classmethod
    def for_phase(cls, kind: str) -> Lifecycle:
        """The opening state of a phase: evaluation or a funded account trading."""
        if kind == "evaluation":
            return cls("evaluation")
        if kind == "funded":
            return cls("funded_active")
        msg = f"phase kind {kind!r} has no lifecycle state; expected evaluation or funded"
        raise ValueError(msg)

    @property
    def state(self) -> AccountState:
        return self._state

    @property
    def transitions(self) -> tuple[Transition, ...]:
        return tuple(self._transitions)

    @property
    def terminal(self) -> bool:
        return self._state in TERMINAL

    def transition(self, to_state: AccountState, *, time_ns: int, cause: str) -> Transition:
        """Record a transition. A no-op transition is refused: only real changes are recorded."""
        if to_state == self._state:
            msg = f"lifecycle is already {self._state}; a no-op transition is not a record"
            raise ValueError(msg)
        if self.terminal and to_state != self._state:
            msg = (
                f"lifecycle is terminal ({self._state}); it cannot move to {to_state} "
                f"(cause {cause!r})"
            )
            raise ValueError(msg)
        record = Transition(
            time_ns=int(time_ns),
            from_state=self._state,
            to_state=to_state,
            cause=cause,
        )
        self._transitions.append(record)
        self._state = to_state
        return record

    def to_document(self) -> list[dict[str, object]]:
        return [
            {
                "time_ns": item.time_ns,
                "from": item.from_state,
                "to": item.to_state,
                "cause": item.cause,
            }
            for item in self._transitions
        ]

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self._state,
            "transitions": [
                [t.time_ns, t.from_state, t.to_state, t.cause] for t in self._transitions
            ],
        }

    def restore(self, state: dict[str, object]) -> None:
        self._state = cast(AccountState, str(state["state"]))
        rows = cast(list[list[object]], state["transitions"])
        self._transitions = [
            Transition(
                int(str(when)),
                cast(AccountState, str(source)),
                cast(AccountState, str(target)),
                str(cause),
            )
            for when, source, target, cause in rows
        ]
