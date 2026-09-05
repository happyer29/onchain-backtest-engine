# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
    clickhouse_capability_mapping_digest,
    query_template_digest,
)

# Import reader at the visible module dependency boundary.
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceAdapterError
from backtest.application.models import (
    BoundedSourceEvidenceRequest,
    CapabilityDescriptor,
    # Include capability stream so the models dependency remains explicit.
    CapabilityStream,
    EvidenceStatus,
    QueryLimits,
)
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    ChainFinality,
    # Include fees fidelity so the fidelity dependency remains explicit.
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    # Include source fidelity so the fidelity dependency remains explicit.
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange

# Bind source id once as an explicit module-level contract.
SOURCE_ID = SourceId("bounded-indexer")

_COLUMNS = {
    CapabilityStream.BLOCK_CLOCK: (
        "block_ordinal",
        "block_time",
        # Keep the transaction count component named inside the columns contract.
        "transaction_count",
        "block_hash",
    ),
    CapabilityStream.TOKEN_LAUNCH: (
        "block_ordinal",
        # Keep the transaction index component named inside the columns contract.
        "transaction_index",
        "event_index",
        "signature",
        "transaction_succeeded",
    ),
    # Keep the capability stream component named inside the columns contract.
    CapabilityStream.PUMP_CURVE_TRADE: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        # Complete the columns group only after its semantic components are visible.
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        # Keep the signature component named inside the columns contract.
        "signature",
    ),
}


# Keep the stream contract and validation rules together.
@dataclass
class _Stream(AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]):
    rows: Sequence[Sequence[Any]]
    closed: bool = False

    def __enter__(self) -> Iterator[Sequence[Sequence[Any]]]:
        # Return the completed stream enter result without a hidden fallback.
        return iter((self.rows,))

    def __exit__(self, *args: object) -> None:
        self.closed = True


# Keep the client contract and validation rules together.
class _Client:
    def __init__(self, rows: Mapping[str, Sequence[Sequence[Any]]]) -> None:
        # Execute the client init workflow in explicit, reviewable steps.
        self.rows = dict(rows)
        self.calls: list[dict[str, Any]] = []
        self.streams: list[_Stream] = []

    def query(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("bounded evidence must use streaming reads")

    # Define client query row block stream as one focused operation with an explicit
    # boundary.
    def query_row_block_stream(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        # Close the query row block stream signature after its explicit inputs.
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _Stream:
        # Execute the client query row block stream workflow in explicit, reviewable
        # steps.
        table = next(name for name in self.rows if f"`{name}`" in query)
        self.calls.append(
            {
                "query": query,
                "parameters": parameters,
                # Keep settings named so the query and parameters payload passed to append
                # remains self-describing within client query row block stream.
                "settings": settings,
                "query_tz": query_tz,
                "transport_settings": transport_settings,
            }
        )
        # Assemble stream once so the client query row block stream workflow shares one
        # value.
        stream = _Stream(self.rows[table])
        self.streams.append(stream)
        return stream


def _capability(stream: CapabilityStream) -> ClickHouseCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    columns = _COLUMNS[stream]
    descriptor = CapabilityDescriptor(
        capability_id=CapabilityId(f"fixture.{stream.value.lower()}.v2"),
        protocol="solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun",
        protocol_version="1",
        # Pass schema version explicitly so CapabilityDescriptor receives a reviewable
        # value and v2 input in capability.
        schema_version="2",
        stream=stream,
        columns=columns,
        mandatory_columns=columns,
        fidelity=SourceFidelity(
            # Pass identity fidelity explicitly so SourceFidelity receives a reviewable
            # unknown and none input in capability.
            IdentityFidelity.UNKNOWN,
            OrderingFidelity.UNKNOWN,
            StateFidelity.NONE,
            FeesFidelity.UNKNOWN,
            ChainFinality.UNKNOWN,
            # Pass ingestion completeness explicitly so SourceFidelity receives a
            # reviewable unknown and none input in capability.
            IngestionCompleteness.UNKNOWN,
            SourceConsistency.UNKNOWN,
        ),
    )
    return ClickHouseCapability(
        # Pass descriptor explicitly so ClickHouseCapability receives a reviewable default
        # and slot input in capability.
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table=stream.value.lower(),
        # Pass logical to physical explicitly so ClickHouseCapability receives a
        # reviewable default and slot input in capability.
        logical_to_physical={
            column: "slot" if column == "block_ordinal" else column for column in columns
        },
    )


def _rows(
    # Close the rows signature after its explicit inputs.
    *,
    transaction_index: int = 1,
    launch_succeeded: object = True,
    include_launch: bool = True,
) -> dict[str, Sequence[Sequence[Any]]]:
    # Execute the rows workflow in explicit, reviewable steps.
    return {
        "block_clock": (("hash", 10, 1_000_000_000, 3),),
        "token_launch": (
            ((10, 0, "launch", transaction_index, launch_succeeded),) if include_launch else ()
        ),
        # Include pump curve trade in the completed rows result.
        "pump_curve_trade": ((10, 0, "trade", transaction_index),),
        "pump_curve_lifecycle": ((10, 0, "migration", transaction_index),),
    }


def _request(*, max_rows: int = 100) -> BoundedSourceEvidenceRequest:
    # Execute the request workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        11,
    )
    return BoundedSourceEvidenceRequest(
        source_id=SOURCE_ID,
        block_range=block_range,
        decision_range=block_range,
        capability_mapping_digest=clickhouse_capability_mapping_digest(
            tuple(_capability(stream) for stream in CapabilityStream)
        ),
        query_template_digest=query_template_digest(),
        projector_digest=ContentDigest("1" * 64),
        normalizer_digest=ContentDigest("2" * 64),
        launch_universe_policy_id="fixture-launch-universe-v1",
        skipped_slot_sentinel_policy_id="fixture-skipped-slot-sentinel-v1",
        terminal_lifecycle_ordering_policy_id="fixture-terminal-lifecycle-order-v1",
        query_limits=QueryLimits(20, 1024**3, max_rows),
    )


# Define reader as one focused operation with an explicit boundary.
def _reader(client: _Client) -> ClickHouseSourceReader:
    # Execute the reader workflow in explicit, reviewable steps.
    return ClickHouseSourceReader(
        client=client,
        source_id=SOURCE_ID,
        capabilities=tuple(_capability(stream) for stream in CapabilityStream),
        policy=ClickHouseQueryPolicy(evidence_max_block_span=10),
        # Pass query id factory explicitly so ClickHouseSourceReader receives a reviewable
        # bt and tuple input in reader.
        query_id_factory=lambda operation: f"bt_{operation}",
    )


def test_bounded_evidence_is_read_only_explicit_and_fail_closed() -> None:
    # Execute the test bounded evidence is read only explicit and fail closed workflow in
    # explicit, reviewable steps.
    client = _Client(_rows())

    receipts = _reader(client).inspect_bounded_evidence(_request())

    assert len(receipts) == 4
    by_stream = {
        next(
            # Pass capability explicitly so next receives a reviewable stream and
            # descriptor input in test bounded evidence is read only explicit and fail
            # closed.
            capability.descriptor.stream
            for capability in (_capability(item) for item in CapabilityStream)
            if capability.descriptor.capability_id == receipt.capability_id
        ): receipt
        for receipt in receipts
        # Complete the by stream group only after its semantic components are visible.
    }
    clock = by_stream[CapabilityStream.BLOCK_CLOCK]
    launch = by_stream[CapabilityStream.TOKEN_LAUNCH]
    assert clock.proofs.block_time_second_resolution is EvidenceStatus.PROVEN
    assert clock.proofs.block_time_monotone is EvidenceStatus.PROVEN
    # Verify the launch transaction success exact, proven and proofs relationship before
    # this scenario is accepted.
    assert launch.proofs.launch_transaction_success_exact is EvidenceStatus.PROVEN
    assert launch.proofs.global_zero_based_transaction_index is EvidenceStatus.UNKNOWN
    assert launch.proofs.creation_fields_immutable is EvidenceStatus.UNKNOWN
    assert clock.proofs.failed_transactions_included is EvidenceStatus.UNKNOWN
    assert clock.cut_evidence.chain_finality is ChainFinality.UNKNOWN
    # Verify the completeness, unknown and cut evidence relationship before this scenario
    # is accepted.
    assert clock.cut_evidence.completeness is IngestionCompleteness.UNKNOWN
    assert clock.cut_evidence.consistency is SourceConsistency.UNKNOWN
    assert clock.source_fidelity == _capability(CapabilityStream.BLOCK_CLOCK).descriptor.fidelity
    assert clock.decision_range == _request().decision_range
    assert clock.projector_digest == ContentDigest("1" * 64)
    assert clock.normalizer_digest == ContentDigest("2" * 64)
    assert len(clock.query_fingerprints) == 1
    assert len(launch.query_fingerprints) == 2
    assert all(stream.closed for stream in client.streams)
    # Verify len(client.calls) == 4 before this scenario is accepted.
    assert len(client.calls) == 4
    for call in client.calls:
        # Process client.calls inside the bounded test bounded evidence is read only
        # explicit and fail closed loop.
        normalized = " ".join(call["query"].upper().split())
        assert normalized.startswith("SELECT ")
        assert "SELECT *" not in normalized
        assert " OFFSET " not in f" {normalized} "
        assert call["parameters"] == {
            # Keep the from block ordinal expectation tied to call, parameters and from
            # block ordinal in this scenario.
            "from_block_ordinal": 10,
            "to_block_ordinal": 11,
        }
        assert call["settings"]["readonly"] == 1
        assert call["settings"]["max_result_rows"] == 100
        # Verify the max result bytes, call and settings relationship before this scenario
        # is accepted.
        assert call["settings"]["max_result_bytes"] == 64 * 1024**2
        assert call["settings"]["max_threads"] == 1
        assert call["settings"]["max_block_size"] == 8_192
        assert call["query_tz"] == "UTC"
        assert call["transport_settings"]["query_id"].startswith("bt_evidence_")


@pytest.mark.parametrize("launch_succeeded", [False, 1, "true", None])
# Define test launch success proof refutes non literal true as one focused operation with
# an explicit boundary.
def test_launch_success_proof_refutes_non_literal_true(launch_succeeded: object) -> None:
    # Execute the test launch success proof refutes non literal true workflow in explicit,
    # reviewable steps.
    receipts = _reader(_Client(_rows(launch_succeeded=launch_succeeded))).inspect_bounded_evidence(
        _request()
    )
    launch = next(
        item
        # Pass item explicitly so next receives a reviewable v2 and value input in test
        # launch success proof refutes non literal true.
        for item in receipts
        if item.capability_id.value == "fixture.token_launch.v2"
        # Complete next only after its v2 and value inputs are visible in test launch success
        # proof refutes non literal true.
    )

    assert launch.proofs.launch_transaction_success_exact is EvidenceStatus.REFUTED


def test_empty_launch_range_does_not_create_vacuous_success_proof() -> None:
    # Execute the test empty launch range does not create vacuous success proof workflow
    # in explicit, reviewable steps.
    receipts = _reader(_Client(_rows(include_launch=False))).inspect_bounded_evidence(_request())
    launch = next(
        item for item in receipts if item.capability_id.value == "fixture.token_launch.v2"
    )

    assert launch.observed_rows == 0
    # Verify the launch transaction success exact, unknown and proofs relationship before
    # this scenario is accepted.
    assert launch.proofs.launch_transaction_success_exact is EvidenceStatus.UNKNOWN


def test_cross_stream_bounds_can_refute_but_never_prove_global_index() -> None:
    # Execute the test cross stream bounds can refute but never prove global index
    # workflow in explicit, reviewable steps.
    receipts = _reader(_Client(_rows(transaction_index=3))).inspect_bounded_evidence(_request())

    for receipt in receipts:
        # Process receipts inside the bounded test cross stream bounds can refute but
        # never prove global index loop.
        if receipt.capability_id.value != "fixture.block_clock.v2":
            assert receipt.proofs.global_zero_based_transaction_index is EvidenceStatus.REFUTED


def test_evidence_hard_span_and_local_row_limit_fail_closed() -> None:
    # Execute the test evidence hard span and local row limit fail closed workflow in
    # explicit, reviewable steps.
    reader = _reader(_Client(_rows()))
    oversized = BoundedSourceEvidenceRequest(
        source_id=SOURCE_ID,
        block_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            # Pass block32 transaction32 position schema id explicitly so BlockRange
            # receives a reviewable solana mainnet network id and block32 transaction32
            # position schema id input in test evidence hard span and local row limit fail
            # closed.
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            0,
            11,
        ),
        decision_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            0,
            11,
        ),
        capability_mapping_digest=clickhouse_capability_mapping_digest(
            tuple(_capability(stream) for stream in CapabilityStream)
        ),
        query_template_digest=query_template_digest(),
        projector_digest=ContentDigest("1" * 64),
        normalizer_digest=ContentDigest("2" * 64),
        launch_universe_policy_id="fixture-launch-universe-v1",
        skipped_slot_sentinel_policy_id="fixture-skipped-slot-sentinel-v1",
        terminal_lifecycle_ordering_policy_id="fixture-terminal-lifecycle-order-v1",
        query_limits=QueryLimits(20, 1024**3, 100),
    )

    with pytest.raises(ValueError, match="hard span"):
        reader.inspect_bounded_evidence(oversized)
    too_many_rows = _rows()
    too_many_rows["token_launch"] = (
        # Keep the launch component named inside the too many rows['token launch']
        # contract.
        (10, 0, "launch-a", 1, True),
        (10, 1, "launch-b", 2, True),
    )
    with pytest.raises(SourceAdapterError, match="evidence-query"):
        _reader(_Client(too_many_rows)).inspect_bounded_evidence(_request(max_rows=1))
