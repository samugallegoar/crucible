"""Canonical JSON: one text for one value, in any key order.

The identity of an artifact (``experiments/artifact_id.py``), of an expression
(``dsl/identity.py``) and of a checkpoint all hash canonical JSON, so they must agree byte for
byte. This is the one implementation; ``artifact_id.canonical_json`` re-exports it.
"""

from __future__ import annotations

import json


def canonical_json(value: object) -> str:
    """Key-sorted, whitespace-free JSON: the same text for the same content, in any key order.

    ``ensure_ascii=True`` keeps the bytes identical across platforms and locales. Non-finite
    floats are not refused here, matching the artifact identity's historical behaviour.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
