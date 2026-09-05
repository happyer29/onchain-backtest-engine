# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from hypothesis import given

# Import hypothesis at the visible module dependency boundary.
from hypothesis import strategies as st
from hypothesis.strategies import DataObject

from backtest.adapters.columnar.arrow.parquet_replay import _validate_snapshot_manifest
from backtest.adapters.source.common import SourceBatch
from backtest.application.errors import ReprepareRequiredError

# Import replay packs at the visible module dependency boundary.
from backtest.application.replay_packs import ReplaySemanticsManifest
from backtest.domain.event_hashing import canonical_event_stream_hash
from backtest.domain.fidelity import IdentityFidelity, OrderingFidelity
from backtest.domain.identifiers import CapabilityId
from backtest.domain.market_events import SwapEvent, canonical_event_sort_key

# Import time at the visible module dependency boundary.
from backtest.domain.time import SlotRange
from backtest.plugins.protocols.reference import (
    ProjectionKind,
    ProjectionSpec,
    ReferenceProtocolProjector,
    # Close the reference import after its required symbols are visible.
)

_CAPABILITY_ID = CapabilityId("fixture.swaps.v1")
_COLUMNS = (
    "row_id",
    "slot",
    # Keep the transaction index component named inside the columns contract.
    "transaction_index",
    "event_index",
    "signature",
    "pool_id",
    "sold_asset_id",
    # Keep the bought asset id component named inside the columns contract.
    "bought_asset_id",
    "sold_amount_atomic",
    "bought_amount_atomic",
    "fee_amount_atomic",
    "pool_asset_a_id",
    # Keep the pool asset b id component named inside the columns contract.
    "pool_asset_b_id",
)
_SEMANTIC_COLUMNS = tuple((name, name) for name in _COLUMNS if name != "row_id")


@pytest.mark.parametrize(
    "identity_fidelity",
    # Open the identity fidelity and exact payload explicitly for parametrize within test
    # identical payloads keep distinct proven source occurrences.
    (IdentityFidelity.EXACT, IdentityFidelity.AMBIGUOUS),
)
def test_identical_payloads_keep_distinct_proven_source_occurrences(
    identity_fidelity: IdentityFidelity,
) -> None:
    # Execute the test identical payloads keep distinct proven source occurrences workflow
    # in explicit, reviewable steps.
    projector = _projector(identity_fidelity, proven_total_key=("row_id",))
    events = projector.project(
        _batch(
            _row(row_id="source-row-a", event_index=3),
            _row(row_id="source-row-b", event_index=4),
            # Complete _batch only after its source-row-a and source-row-b inputs are visible
            # in test identical payloads keep distinct proven source occurrences.
        )
    )

    first, second = events
    assert isinstance(first, SwapEvent)
    assert isinstance(second, SwapEvent)
    # Verify the source record id, envelope and first relationship before this scenario is
    # accepted.
    assert first.envelope.source_record_id != second.envelope.source_record_id
    assert first.envelope.canonical_event_id != second.envelope.canonical_event_id
    assert first.envelope.stable_causal_id != second.envelope.stable_causal_id
    assert (
        first.pool_id,
        # Keep the first expectation tied to pool id, sold asset id and bought asset id in
        # this scenario.
        first.sold_asset_id,
        first.bought_asset_id,
        first.sold_amount_atomic,
        first.bought_amount_atomic,
        first.fee_amount_atomic,
        # Verify the pool id, sold asset id and bought asset id relationship before this
        # scenario is accepted.
    ) == (
        second.pool_id,
        second.sold_asset_id,
        second.bought_asset_id,
        second.sold_amount_atomic,
        # Keep the second expectation tied to pool id, sold asset id and bought asset id
        # in this scenario.
        second.bought_amount_atomic,
        second.fee_amount_atomic,
    )


def test_identity_fidelity_is_part_of_occurrence_identity_without_upgrade() -> None:
    # Execute the test identity fidelity is part of occurrence identity without upgrade
    # workflow in explicit, reviewable steps.
    row = _row(row_id="same-source-key", event_index=7)
    exact = _projector(IdentityFidelity.EXACT, proven_total_key=("row_id",)).project(_batch(row))[0]
    ambiguous = _projector(
        IdentityFidelity.AMBIGUOUS,
        proven_total_key=("row_id",),
        # Keep the row _batch step visible while building ambiguous.
    ).project(_batch(row))[0]

    assert exact.envelope.source_record_id != ambiguous.envelope.source_record_id
    assert exact.envelope.canonical_event_id != ambiguous.envelope.canonical_event_id


@pytest.mark.parametrize(
    ("identity_fidelity", "total_key", "proven", "message"),
    # Open the identity fidelity and total key payload explicitly for parametrize within
    # test projection spec rejects unproven identity contracts.
    (
        (
            IdentityFidelity.EXACT,
            (),
            False,
            # Pass exact source identity requires explicitly so parametrize receives a
            # reviewable identity fidelity and total key input in test projection spec
            # rejects unproven identity contracts.
            "exact source identity requires a proven total key",
        ),
        (
            IdentityFidelity.CANDIDATE,
            ("row_id",),
            # Keep parametrize, mark and identity fidelity visible while completing
            # parametrize within test projection spec rejects unproven identity contracts.
            False,
            "unproven source total key",
        ),
        (
            IdentityFidelity.CANDIDATE,
            # Open the identity fidelity and total key payload explicitly for parametrize
            # within test projection spec rejects unproven identity contracts.
            (),
            True,
            "proven source total key must not be empty",
        ),
    ),
    # Complete parametrize only after its identity fidelity and total key inputs are visible
    # in test projection spec rejects unproven identity contracts.
)
def test_projection_spec_rejects_unproven_identity_contracts(
    identity_fidelity: IdentityFidelity,
    total_key: tuple[str, ...],
    proven: bool,
    # Keep the message input explicit in the test projection spec rejects unproven
    # identity contracts contract.
    message: str,
) -> None:
    # Execute the test projection spec rejects unproven identity contracts workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match=message):
        _spec(identity_fidelity, total_key=total_key, proven=proven)


def test_ambiguous_duplicate_candidate_position_fails_closed() -> None:
    # Execute the test ambiguous duplicate candidate position fails closed workflow in
    # explicit, reviewable steps.
    projector = _projector(IdentityFidelity.AMBIGUOUS)
    duplicate = _row(row_id="ignored", event_index=3)

    with pytest.raises(ValueError, match="indistinguishable source occurrences"):
        projector.project(_batch(duplicate, duplicate))


def test_duplicate_proven_total_key_invalidates_the_source_proof() -> None:
    # Execute the test duplicate proven total key invalidates the source proof workflow in
    # explicit, reviewable steps.
    projector = _projector(IdentityFidelity.EXACT, proven_total_key=("row_id",))

    with pytest.raises(ValueError, match="indistinguishable source occurrences"):
        # Keep raises, value error and pytest active only for the bounded test duplicate
        # proven total key invalidates the source proof operation.
        projector.project(
            _batch(
                _row(row_id="duplicate", event_index=1),
                _row(row_id="duplicate", event_index=2),
            )
            # Complete project only after its duplicate and batch inputs are visible in test
            # duplicate proven total key invalidates the source proof.
        )


@pytest.mark.parametrize("bad_key", (1.25, datetime(2026, 1, 1)))
def test_noncanonical_or_timezone_ambiguous_total_key_fails_closed(bad_key: object) -> None:
    # Execute the test noncanonical or timezone ambiguous total key fails closed workflow
    # in explicit, reviewable steps.
    projector = _projector(IdentityFidelity.EXACT, proven_total_key=("row_id",))

    with pytest.raises(ValueError, match="source total-key column"):
        projector.project(_batch(_row(row_id=bad_key, event_index=1)))


@given(
    source_indexes=st.lists(
        # Define test occurrence ids and stream hash do not depend on source row order as
        # one focused operation with an explicit boundary.
        st.integers(min_value=0, max_value=10_000),
        min_size=1,
        max_size=10,
        unique=True,
    ),
    # Define test occurrence ids and stream hash do not depend on source row order as one
    # focused operation with an explicit boundary.
    data=st.data(),
)
def test_occurrence_ids_and_stream_hash_do_not_depend_on_source_row_order(
    source_indexes: list[int],
    data: DataObject,
    # Close the test occurrence ids and stream hash do not depend on source row order
    # signature after its explicit inputs.
) -> None:
    # Execute the test occurrence ids and stream hash do not depend on source row order
    # workflow in explicit, reviewable steps.
    projector = _projector(IdentityFidelity.EXACT, proven_total_key=("row_id",))
    reordered = data.draw(st.permutations(source_indexes))
    first = projector.project(
        _batch(*(_row(row_id=f"row-{index}", event_index=index) for index in source_indexes))
    )
    # Assemble second once so the test occurrence ids and stream hash do not depend on
    # source row order workflow shares one value.
    second = projector.project(
        _batch(*(_row(row_id=f"row-{index}", event_index=index) for index in reordered))
    )

    first_by_position = {
        event.envelope.position.event_index: (
            # Keep the event component named inside the first by position contract.
            event.envelope.source_record_id,
            event.envelope.canonical_event_id,
            event.envelope.stable_causal_id,
        )
        for event in first
        # Complete the first by position group only after its semantic components are visible.
    }
    second_by_position = {
        event.envelope.position.event_index: (
            event.envelope.source_record_id,
            event.envelope.canonical_event_id,
            # Keep the event component named inside the second by position contract.
            event.envelope.stable_causal_id,
        )
        for event in second
    }
    assert first_by_position == second_by_position
    # Verify the canonical event stream hash, sorted and first relationship before this
    # scenario is accepted.
    assert canonical_event_stream_hash(sorted(first, key=canonical_event_sort_key)) == (
        canonical_event_stream_hash(sorted(second, key=canonical_event_sort_key))
    )


def test_v2_semantics_does_not_alias_the_legacy_content_identity_contract() -> None:
    # Execute the test v2 semantics does not alias the legacy content identity contract
    # workflow in explicit, reviewable steps.
    legacy = ReplaySemanticsManifest.canonical_v1()
    current = ReplaySemanticsManifest.canonical_v2()

    assert legacy.canonical_schema_version == 1
    assert current.canonical_schema_version == 2
    assert legacy.replay_semantics_id != current.replay_semantics_id


# Define test projector identity binds exact projection configuration as one focused
# operation with an explicit boundary.
def test_projector_identity_binds_exact_projection_configuration() -> None:
    # Execute the test projector identity binds exact projection configuration workflow in
    # explicit, reviewable steps.
    first_spec = _spec(
        IdentityFidelity.EXACT,
        total_key=("row_id",),
        proven=True,
    )
    # Assemble second spec once so the test projector identity binds exact projection
    # configuration workflow shares one value.
    second_spec = replace(first_spec, protocol_version="2")

    first = ReferenceProtocolProjector((first_spec,))
    second = ReferenceProtocolProjector((second_spec,))

    assert first.config_digest != second.config_digest
    assert first.bundle_id != second.bundle_id


# Define test parquet reader rejects legacy canonical identity manifest as one focused
# operation with an explicit boundary.
def test_parquet_reader_rejects_legacy_canonical_identity_manifest() -> None:
    # Execute the test parquet reader rejects legacy canonical identity manifest workflow
    # in explicit, reviewable steps.
    legacy_manifest = {
        "artifact_schema": "canonical-snapshot/v1",
        "canonical_schema_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "dataset_revision_id": "1" * 64,
        # Keep the distributions component named inside the legacy manifest contract.
        "distributions": [],
        "logical_content_hash": "2" * 64,
        "projector_bundle_id": "3" * 64,
        "requested_analysis_range": [1, 2],
        "requested_extraction_range": [1, 2],
        # Keep the source boundaries component named inside the legacy manifest contract.
        "source_boundaries": [],
        "source_id": "fixture",
        "spec_id": "4" * 64,
        "validation_status": "PASS",
    }

    # Acquire raises, reprepare required error and pytest at an explicit test parquet
    # reader rejects legacy canonical identity manifest context boundary so cleanup
    # remains scoped.
    with pytest.raises(ReprepareRequiredError, match="prepared again"):
        # Keep raises, reprepare required error and pytest active only for the bounded
        # test parquet reader rejects legacy canonical identity manifest operation.
        _validate_snapshot_manifest(
            legacy_manifest,
            (),
        )


def _projector(
    # Keep the fidelity input explicit in the projector contract.
    fidelity: IdentityFidelity,
    *,
    proven_total_key: tuple[str, ...] = (),
) -> ReferenceProtocolProjector:
    # Execute the projector workflow in explicit, reviewable steps.
    return ReferenceProtocolProjector(
        (
            _spec(
                fidelity,
                total_key=proven_total_key,
                # Include proven in the completed projector result.
                proven=bool(proven_total_key),
            ),
        )
    )


def _spec(
    # Keep the fidelity input explicit in the spec contract.
    fidelity: IdentityFidelity,
    *,
    total_key: tuple[str, ...],
    proven: bool,
) -> ProjectionSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    return ProjectionSpec(
        capability_id=_CAPABILITY_ID,
        kind=ProjectionKind.SWAP,
        protocol="fixture",
        protocol_version="1",
        # Pass identity fidelity explicitly so ProjectionSpec receives a reviewable
        # fixture and 1 input in spec.
        identity_fidelity=fidelity,
        ordering_fidelity=OrderingFidelity.INSTRUCTION_EXACT,
        source_total_key=total_key,
        source_total_key_is_proven=proven,
        columns=_SEMANTIC_COLUMNS,
        # Complete ProjectionSpec only after its fixture and 1 inputs are visible in spec.
    )


def _batch(*rows: tuple[object, ...]) -> SourceBatch:
    # Execute the batch workflow in explicit, reviewable steps.
    return SourceBatch(
        capability_id=_CAPABILITY_ID,
        covered_range=SlotRange(100, 101),
        columns=_COLUMNS,
        rows=rows,
        # Complete SourceBatch only after its slot range and capability id inputs are visible
        # in batch.
    )


def _row(*, row_id: object, event_index: int) -> tuple[object, ...]:
    # Execute the row workflow in explicit, reviewable steps.
    values: dict[str, object] = {
        "row_id": row_id,
        "slot": 100,
        "transaction_index": 2,
        "event_index": event_index,
        # Keep the signature component named inside the values contract.
        "signature": "same-transaction",
        "pool_id": "pool",
        "sold_asset_id": "SOL",
        "bought_asset_id": "TOKEN",
        "sold_amount_atomic": 100,
        # Keep the bought amount atomic component named inside the values contract.
        "bought_amount_atomic": 1_000,
        "fee_amount_atomic": 1,
        "pool_asset_a_id": "SOL",
        "pool_asset_b_id": "TOKEN",
    }
    # Return the completed row result without a hidden fallback.
    return tuple(values[column] for column in _COLUMNS)
