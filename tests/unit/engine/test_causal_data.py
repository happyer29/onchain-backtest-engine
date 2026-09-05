# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest

from backtest.engine.causal_data import (
    CausalScalarRow,
    CausalScalarView,
    # Include in memory causal scalar provider so the causal data dependency remains
    # explicit.
    InMemoryCausalScalarProvider,
)


def test_point_in_time_view_never_exposes_future_scalar() -> None:
    # Execute the test point in time view never exposes future scalar workflow in
    # explicit, reviewable steps.
    provider = InMemoryCausalScalarProvider(
        (
            CausalScalarRow("score", 7, 10, 100),
            CausalScalarRow("score", 7, 20, 200),
        )
        # Complete InMemoryCausalScalarProvider only after its score and causal scalar row
        # inputs are visible in test point in time view never exposes future scalar.
    )

    assert CausalScalarView(provider, 9).value("score", 7) is None
    assert CausalScalarView(provider, 10).value("score", 7) == 100
    assert CausalScalarView(provider, 19).value("score", 7) == 100
    assert CausalScalarView(provider, 20).value("score", 7) == 200


# Define test future row does not change prior view as one focused operation with an
# explicit boundary.
def test_future_row_does_not_change_prior_view() -> None:
    # Execute the test future row does not change prior view workflow in explicit,
    # reviewable steps.
    prior = InMemoryCausalScalarProvider((CausalScalarRow("score", 1, 5, 10),))
    with_future = InMemoryCausalScalarProvider(
        (
            CausalScalarRow("score", 1, 5, 10),
            CausalScalarRow("score", 1, 999, -1),
            # Complete InMemoryCausalScalarProvider only after its score and causal scalar row
            # inputs are visible in test future row does not change prior view.
        )
    )
    assert CausalScalarView(prior, 100).value("score", 1) == CausalScalarView(
        with_future, 100
    ).value("score", 1)


# Define test event bound view uses replay row without exposing an unbound default as one
# focused operation with an explicit boundary.
def test_event_bound_view_uses_replay_row_without_exposing_an_unbound_default() -> None:
    # Execute the test event bound view uses replay row without exposing an unbound
    # default workflow in explicit, reviewable steps.
    provider = InMemoryCausalScalarProvider((CausalScalarRow("score", 7, 10, 100),))

    assert CausalScalarView(provider, 10, bound_entity_id=7).current("score") == 100
    with pytest.raises(RuntimeError, match="not bound"):
        CausalScalarView(provider, 10).current("score")


def test_duplicate_or_unsorted_scalar_coordinates_are_rejected() -> None:
    # Execute the test duplicate or unsorted scalar coordinates are rejected workflow in
    # explicit, reviewable steps.
    row = CausalScalarRow("score", 1, 5, 10)
    with pytest.raises(ValueError, match="unique"):
        InMemoryCausalScalarProvider((row, row))
    with pytest.raises(ValueError, match="canonical order"):
        # Keep raises, value error and pytest active only for the bounded test duplicate
        # or unsorted scalar coordinates are rejected operation.
        InMemoryCausalScalarProvider(
            (CausalScalarRow("score", 1, 6, 11), CausalScalarRow("score", 1, 5, 10))
        )
