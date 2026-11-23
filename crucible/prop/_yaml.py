"""Read a YAML document with PyYAML's libyaml-backed safe loader when the wheel ships it.

The ruleset registry is a folder of large, deeply nested YAML files (201 of them at the time of
writing), and every one of them is parsed twice by ``build_index`` (once for the schema version,
once by ``load_ruleset``). PyYAML's default ``safe_load`` scans and composes in **pure Python**:
8.5 s for that folder, which is the whole cost of ``python -m tools.docgen --check`` and of
``crucible prop list``. ``CSafeLoader`` is the same parse with the same constructors — the scanner
and parser are the C ones — and it takes 0.8 s. The documents, and therefore every content hash
and the ``INDEX.json`` lock, are identical (``tests/unit/test_prop_ruleset.py`` pins that the two
loaders agree on every shipped file).

Falling back to ``SafeLoader`` keeps a wheel built without libyaml working: only speed changes.
"""

from __future__ import annotations

from typing import Any

import yaml

_SAFE_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""``CSafeLoader`` (libyaml) when available, else ``SafeLoader``. Both are *safe* loaders: no
arbitrary Python objects, whatever the document says."""


def safe_load(text: str) -> object:
    """``yaml.safe_load(text)``, through the C scanner/parser when PyYAML ships it."""
    return yaml.load(text, Loader=_SAFE_LOADER)
