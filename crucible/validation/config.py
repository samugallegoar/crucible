"""Splitter config models (the `validation:` block).

Self-contained in this package, not part of
`crucible/experiments/config.py`'s discriminated union — unlike
`execution/`, nothing in the `experiments` layer consumes these (the
`validate` command takes a factor file, not a splitter). See docs/modules/validation.md known gaps
for the migration path.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WalkForwardConfig(_FrozenModel):
    type: Literal["walk_forward"] = "walk_forward"
    train_size: int = Field(gt=0)
    test_size: int = Field(gt=0)
    anchored: bool
    validate_size: int = Field(ge=0, default=0)


class PurgedKFoldConfig(_FrozenModel):
    type: Literal["purged_kfold"] = "purged_kfold"
    n_splits: int = Field(ge=2)
    purge: int = Field(ge=0, default=0)
    embargo: int = Field(ge=0, default=0)


class CombinatorialPurgedCVConfig(_FrozenModel):
    type: Literal["cpcv"] = "cpcv"
    n_groups: int = Field(ge=3)
    n_test_groups: int = Field(ge=1)
    purge: int = Field(ge=0, default=0)
    embargo: int = Field(ge=0, default=0)


SplitterConfig = Annotated[
    WalkForwardConfig | PurgedKFoldConfig | CombinatorialPurgedCVConfig,
    Field(discriminator="type"),
]
