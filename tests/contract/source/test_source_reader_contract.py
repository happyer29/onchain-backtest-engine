"""Contract tests shared by every installed source adapter."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
)

# Import reader at the visible module dependency boundary.
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.in_memory import InMemorySourceReader
from backtest.application.models import (
    CapabilityDescriptor,
    CapabilityStream,
    # Include dataset shard so the models dependency remains explicit.
    DatasetShard,
    ExtractionRequest,
    QueryLimits,
    SourceColumn,
    SourceMetadata,
    # Include source table so the models dependency remains explicit.
    SourceTable,
)
from backtest.application.ports.source import SourceMetadataReader, SourceReader
from backtest.application.source_fingerprint import source_schema_fingerprint
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


# Keep the click house result contract and validation rules together.
@dataclass(slots=True)
class _ClickHouseResult:
    result_rows: Sequence[Sequence[Any]]
    closed: bool = False

    def close(self) -> None:
        # Assemble self closed once so the click house result close workflow shares one
        # value.
        self.closed = True


# Keep the click house stream contract and validation rules together.
class _ClickHouseStream(AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]):
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        # Execute the click house stream init workflow in explicit, reviewable steps.
        self._rows = rows
        self.closed = False

    def __enter__(self) -> Iterator[Sequence[Sequence[Any]]]:
        return iter((self._rows,))

    def __exit__(self, *args: object) -> None:
        # Assemble self closed once so the click house stream exit workflow shares one
        # value.
        self.closed = True


class _ClickHouseTransport:
    """Credential-bearing fake transport exercised only through the adapter."""

    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        # Execute the click house transport init workflow in explicit, reviewable steps.
        self._rows = rows
        self.calls: list[dict[str, Any]] = []
        self.results: list[_ClickHouseResult] = []
        self.streams: list[_ClickHouseStream] = []

    def __repr__(self) -> str:
        # Return the completed click house transport repr result without a hidden
        # fallback.
        return "Transport(password=contract-secret, host=secret.invalid)"

    def query(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        # Keep the settings input explicit in the query contract.
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _ClickHouseResult:
        # Execute the click house transport query workflow in explicit, reviewable steps.
        self.calls.append(
            {
                "kind": "metadata",
                "parameters": parameters,
                "query": query,
                # Keep query tz named so the kind and parameters payload passed to append
                # remains self-describing within click house transport query.
                "query_tz": query_tz,
                "settings": settings,
                "transport_settings": transport_settings,
            }
        )
        # Guard this path with 'version()' in query before applying effects.
        if "version()" in query:
            rows: Sequence[Sequence[Any]] = (("24.6.2",),)
        # Handle the click house transport query complement of 'version()' in query
        # explicitly.
        elif "system.tables" in query:
            rows = (("MergeTree", "", "(slot, signature)"),)
        # Handle the click house transport query complement of 'system.tables' in query
        # explicitly.
        elif "system.columns" in query:
            # Handle the click house transport query 'system.columns' in query branch as a
            # distinct logical block.
            rows = (
                ("amount", "UInt64"),
                ("signature", "String"),
                ("slot", "UInt64"),
            )
        else:  # pragma: no cover - adapter contract guards the query family
            raise AssertionError("unexpected ClickHouse metadata query")
        result = _ClickHouseResult(rows)
        self.results.append(result)
        return result

    def query_row_block_stream(
        # Keep the remaining query row block stream inputs visible at the click house
        # transport query row block stream boundary.
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        *,
        # Keep the query tz input explicit in the query row block stream contract.
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _ClickHouseStream:
        # Execute the click house transport query row block stream workflow in explicit,
        # reviewable steps.
        self.calls.append(
            {
                "kind": "scan",
                "parameters": parameters,
                "query": query,
                # Keep query tz named so the kind and parameters payload passed to append
                # remains self-describing within click house transport query row block
                # stream.
                "query_tz": query_tz,
                "settings": settings,
                "transport_settings": transport_settings,
            }
        )
        # Assemble stream once so the click house transport query row block stream
        # workflow shares one value.
        stream = _ClickHouseStream(self._rows)
        self.streams.append(stream)
        return stream


# Keep the source contract case contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _SourceContractCase:
    reader: SourceReader
    metadata_reader: SourceMetadataReader
    clickhouse: _ClickHouseTransport | None = None


# Define descriptor as one focused operation with an explicit boundary.
def _descriptor() -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=CapabilityId("swaps.v1"),
        protocol="test-protocol",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # test-protocol input in descriptor.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("block_ordinal", "signature", "amount"),
        mandatory_columns=("block_ordinal", "signature"),
        fidelity=SourceFidelity(
            identity=IdentityFidelity.CANDIDATE,
            # Pass ordering explicitly so SourceFidelity receives a reviewable candidate
            # and transaction exact input in descriptor.
            ordering=OrderingFidelity.TRANSACTION_EXACT,
            state=StateFidelity.NONE,
            fees=FeesFidelity.UNKNOWN,
            chain_finality=ChainFinality.UNKNOWN,
            completeness=IngestionCompleteness.UNKNOWN,
            # Pass consistency explicitly so SourceFidelity receives a reviewable
            # candidate and transaction exact input in descriptor.
            consistency=SourceConsistency.BEST_EFFORT,
        ),
        total_key=("signature",),
        keyset_key_is_proven=True,
    )


# Define metadata as one focused operation with an explicit boundary.
def _metadata() -> SourceMetadata:
    # Execute the metadata workflow in explicit, reviewable steps.
    descriptor = _descriptor()
    return SourceMetadata(
        source_id=SourceId("test-indexer"),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass server version explicitly so SourceMetadata receives a reviewable test-
        # indexer and in-memory/1 input in metadata.
        server_version="in-memory/1",
        tables=(
            SourceTable(
                name="fixture.swaps",
                engine="Memory",
                # Pass partition key explicitly so SourceTable receives a reviewable swaps
                # and memory input in metadata.
                partition_key="",
                sorting_key="slot",
                columns=(
                    SourceColumn("slot", "UInt64", False),
                    SourceColumn("signature", "String", False),
                    # Include source column in the completed metadata result.
                    SourceColumn("amount", "UInt64", False),
                ),
            ),
        ),
        capabilities=(descriptor,),
        # Complete SourceMetadata only after its test-indexer and in-memory/1 inputs are
        # visible in metadata.
    )


def _request() -> ExtractionRequest:
    # Execute the request workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        12,
    )
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("sha256:" + "1" * 64),
        shard=DatasetShard(
            ordinal=0,
            capability_id=CapabilityId("swaps.v1"),
            # Include block range in the completed request result.
            block_range=block_range,
            columns=("block_ordinal", "signature", "amount"),
        ),
        decision_range=block_range,
        query_limits=QueryLimits(
            max_execution_seconds=10,
            # Pass max memory bytes explicitly into QueryLimits within request.
            max_memory_bytes=64 * 1024**2,
            max_result_rows=100,
        ),
    )


def _contract_case(implementation: str) -> _SourceContractCase:
    # Execute the contract case workflow in explicit, reviewable steps.
    capability_id = CapabilityId("swaps.v1")
    duplicate = {"block_ordinal": 11, "signature": "same", "amount": 7}
    if implementation == "in-memory":
        # Handle the contract case implementation == 'in-memory' branch as a distinct
        # logical block.
        reader = InMemorySourceReader(
            _metadata(),
            {
                capability_id: (
                    {"block_ordinal": 9, "signature": "before", "amount": 1},
                    # Open the block ordinal and signature payload explicitly for
                    # InMemorySourceReader within contract case.
                    {"block_ordinal": 10, "signature": "first", "amount": 2},
                    duplicate,
                    duplicate,
                    {"block_ordinal": 12, "signature": "right-boundary", "amount": 3},
                )
                # Close the block ordinal and signature payload only after all contract case
                # fields are present.
            },
            batch_size=2,
        )
        return _SourceContractCase(reader, reader)
    if implementation != "clickhouse":  # pragma: no cover - fixed parametrization
        raise AssertionError("unknown source contract implementation")

    # DatasetShard canonicalizes columns as amount, block_ordinal, signature.
    transport = _ClickHouseTransport(
        (
            (2, 10, "first"),
            (7, 11, "same"),
            (7, 11, "same"),
            # Complete _ClickHouseTransport only after its first and same inputs are visible
            # in contract case.
        )
    )
    descriptor = _descriptor()
    mapping = ClickHouseCapability(
        descriptor=descriptor,
        # Pass network id explicitly so ClickHouseCapability receives a reviewable default
        # and swaps input in contract case.
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table="swaps",
        logical_to_physical={
            # Pass column explicitly so ClickHouseCapability receives a reviewable default
            # and swaps input in contract case.
            column: "slot" if column == "block_ordinal" else column
            for column in descriptor.columns
        },
        order_by=("block_ordinal", "signature"),
    )
    # Assemble clickhouse once so the contract case workflow shares one value.
    clickhouse = ClickHouseSourceReader(
        # Pass client explicitly so ClickHouseSourceReader receives a reviewable test-
        # indexer and contract input in contract case.
        client=transport,
        source_id=SourceId("test-indexer"),
        capabilities=(mapping,),
        policy=ClickHouseQueryPolicy(max_block_span=100, max_result_rows=1_000),
        query_id_factory=lambda operation: f"contract_{operation}",
        # Complete ClickHouseSourceReader only after its test-indexer and contract inputs are
        # visible in contract case.
    )
    return _SourceContractCase(clickhouse, clickhouse, transport)


@pytest.mark.parametrize("implementation", ("in-memory", "clickhouse"))
def test_each_source_adapter_satisfies_the_shared_bounded_reader_contract(
    implementation: str,
    # Close the test each source adapter satisfies the shared bounded reader contract
    # signature after its explicit inputs.
) -> None:
    # Execute the test each source adapter satisfies the shared bounded reader contract
    # workflow in explicit, reviewable steps.
    case = _contract_case(implementation)
    reader = case.reader

    assert isinstance(reader, SourceReader)
    assert reader.list_capabilities(SourceId("test-indexer")) == (_descriptor(),)

    batches = tuple(reader.scan(_request()))
    # Verify the row count, batch and batches relationship before this scenario is
    # accepted.
    assert sum(batch.row_count for batch in batches) == 3
    assert tuple(row for batch in batches for row in batch.rows) == (
        (2, 10, "first"),
        (7, 11, "same"),
        (7, 11, "same"),
        # Verify the row, first and same relationship before this scenario is accepted.
    )
    expected_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        # Keep block range, solana mainnet network id and block32 transaction32 position
        # schema id visible while completing BlockRange within test each source adapter
        # satisfies the shared bounded reader contract.
        12,
    )
    assert all(batch.covered_range == expected_range for batch in batches)
    assert len({batch.query_fingerprint for batch in batches}) == 1

    metadata = case.metadata_reader.inspect_metadata(SourceId("test-indexer"))
    # Verify the source id, metadata and test-indexer relationship before this scenario is
    # accepted.
    assert metadata.source_id == SourceId("test-indexer")
    assert metadata.capabilities == (_descriptor(),)
    assert metadata.capabilities[0].fidelity == _descriptor().fidelity
    assert source_schema_fingerprint(metadata) == source_schema_fingerprint(metadata)

    if case.clickhouse is not None:
        # Handle the test each source adapter satisfies the shared bounded reader contract
        # case.clickhouse is not None branch as a distinct logical block.
        scan = next(call for call in case.clickhouse.calls if call["kind"] == "scan")
        normalized = " ".join(cast(str, scan["query"]).upper().split())
        assert normalized.startswith(
            "SELECT `AMOUNT` AS `AMOUNT`, `SLOT` AS `BLOCK_ORDINAL`, "
            "`SIGNATURE` AS `SIGNATURE` FROM"
            # Complete startswith only after its declared inputs are visible in test each
            # source adapter satisfies the shared bounded reader contract.
        )
        assert "SELECT *" not in normalized
        assert "`SLOT` >= {FROM_BLOCK_ORDINAL:UINT64}" in normalized
        assert "`SLOT` < {TO_BLOCK_ORDINAL:UINT64}" in normalized
        assert scan["parameters"] == {"from_block_ordinal": 10, "to_block_ordinal": 12}
        # Verify the readonly, cast and scan relationship before this scenario is
        # accepted.
        assert cast(dict[str, object], scan["settings"])["readonly"] == 1
        assert scan["query_tz"] == "UTC"
        assert all(result.closed for result in case.clickhouse.results)
        assert all(stream.closed for stream in case.clickhouse.streams)
        assert "contract-secret" not in repr(reader)
        # Verify 'secret.invalid' not in repr(reader) before this scenario is accepted.
        assert "secret.invalid" not in repr(reader)


@pytest.mark.parametrize("implementation", ("in-memory", "clickhouse"))
def test_each_source_metadata_fingerprint_is_canonical_and_time_independent(
    implementation: str,
) -> None:
    # Execute the test each source metadata fingerprint is canonical and time independent
    # workflow in explicit, reviewable steps.
    metadata = _contract_case(implementation).metadata_reader.inspect_metadata(
        SourceId("test-indexer")
    )

    first = source_schema_fingerprint(metadata)
    _irrelevant_operational_time = datetime.now(UTC)
    # Assemble second once so the test each source metadata fingerprint is canonical and
    # time independent workflow shares one value.
    second = source_schema_fingerprint(metadata)

    assert first == second
    assert len(first.hex) == 64
