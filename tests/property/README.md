# Property tests (hypothesis)

Invariants as properties: ledger identities, order state machine, fills within bar bounds,
participation caps, PIT never returning the future, event-queue order, probability bounds. Fast
and derandomized in CI (`tests/conftest.py`); see [`tests/README.md`](../README.md) §2 and §7.
