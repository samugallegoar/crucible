"""Property: the PIT accessor never returns a row with available_at > as_of."""

from __future__ import annotations

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.core.clock import SimulationClock
from crucible.core.types import DatasetId, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.pit import StorePITAccessor
from crucible.data.store import ParquetDataStore, build_dataset

rows = st.lists(
    st.tuples(
        st.sampled_from(["AAA", "BBB"]),
        st.integers(min_value=0, max_value=1_000),  # event_time
        st.integers(min_value=0, max_value=100),  # publication delay
    ),
    min_size=1,
    max_size=60,
    unique_by=lambda r: (r[0], r[1]),
)


@settings(max_examples=25, deadline=None)
@given(data=rows, as_of=st.integers(min_value=0, max_value=1_200))
def test_no_future_rows_ever(data: list[tuple[str, int, int]], as_of: int) -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        frame = pl.DataFrame(
            {
                "symbol": [r[0] for r in data],
                "event_time": [r[1] for r in data],
                "available_at": [r[1] + r[2] for r in data],
                "open": [1.0] * len(data),
                "high": [1.0] * len(data),
                "low": [1.0] * len(data),
                "close": [1.0] * len(data),
                "volume": [0.0] * len(data),
            }
        )
        dataset = DatasetId("bars_prop")
        build_dataset(
            Path(tmp),
            dataset,
            frame,
            schema=BAR_SCHEMA,
            sort_keys=BAR_SORT_KEYS,
            source="property-test",
        )
        clock = SimulationClock(TimestampNs(as_of))
        pit = StorePITAccessor(ParquetDataStore(Path(tmp)), clock)

        history = pit.history(
            dataset,
            ["close"],
            [Symbol("AAA"), Symbol("BBB")],
            TimestampNs(as_of),
            lookback=1_000,
        )
        assert (history.get_column("available_at") <= as_of).all()

        latest = pit.get(dataset, ["close"], [Symbol("AAA"), Symbol("BBB")], TimestampNs(as_of))
        assert (latest.get_column("available_at") <= as_of).all()
