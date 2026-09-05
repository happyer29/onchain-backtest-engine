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
)

# Import reader at the visible module dependency boundary.
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceAdapterError
from backtest.application.models import (
    CapabilityDescriptor,
    CapabilityStream,
    # Include dataset shard so the models dependency remains explicit.
    DatasetShard,
    ExtractionRequest,
    QueryLimits,
)
from backtest.application.source_fingerprint import source_schema_fingerprint

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange


# Keep the fake result contract and validation rules together.
@dataclass
class _FakeResult:
    result_rows: Sequence[Sequence[Any]]
    closed: bool = False

    def close(self) -> None:
        # Assemble self closed once so the fake result close workflow shares one value.
        self.closed = True


# Keep the fake stream contract and validation rules together.
class _FakeStream(AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]):
    def __init__(self, blocks: Sequence[Sequence[Sequence[Any]]]) -> None:
        # Execute the fake stream init workflow in explicit, reviewable steps.
        self._blocks = blocks
        self.closed = False

    def __enter__(self) -> Iterator[Sequence[Sequence[Any]]]:
        return iter(self._blocks)

    def __exit__(self, *args: object) -> None:
        # Assemble self closed once so the fake stream exit workflow shares one value.
        self.closed = True


# Keep the fake client contract and validation rules together.
class _FakeClient:
    def __init__(self, blocks: Sequence[Sequence[Sequence[Any]]] = ()) -> None:
        # Execute the fake client init workflow in explicit, reviewable steps.
        self.blocks = blocks
        self.calls: list[dict[str, Any]] = []
        self.results: list[_FakeResult] = []
        self.streams: list[_FakeStream] = []

    def __repr__(self) -> str:
        # Return the completed fake client repr result without a hidden fallback.
        return "FakeClient(password=super-secret, host=secret.example)"

    def query(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        # Keep the settings input explicit in the query contract.
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _FakeResult:
        # Execute the fake client query workflow in explicit, reviewable steps.
        self.calls.append(
            {
                "kind": "query",
                "query": query,
                "parameters": parameters,
                # Keep settings named so the kind and query payload passed to append
                # remains self-describing within fake client query.
                "settings": settings,
                "query_tz": query_tz,
                "transport_settings": transport_settings,
            }
        )
        # Guard this path with 'version()' in query before applying effects.
        if "version()" in query:
            rows: Sequence[Sequence[Any]] = (("24.6.2.17",),)
        # Handle the fake client query complement of 'version()' in query explicitly.
        elif "system.tables" in query:
            rows = (("MergeTree", "block_date_utc", "(slot, tx_idx)"),)
        # Handle the fake client query complement of 'system.tables' in query explicitly.
        elif "system.columns" in query:
            # Handle the fake client query 'system.columns' in query branch as a distinct
            # logical block.
            rows = (
                ("slot", "UInt64"),
                ("tx_idx", "UInt32"),
                ("signature", "String"),
                ("amount", "Nullable(UInt64)"),
                # Complete the rows group only after its semantic components are visible.
            )
        else:
            raise AssertionError(f"unexpected metadata query: {query}")
        result = _FakeResult(rows)
        self.results.append(result)
        # Return the completed fake client query result without a hidden fallback.
        return result

    def query_row_block_stream(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        # Keep the settings input explicit in the query row block stream contract.
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _FakeStream:
        # Execute the fake client query row block stream workflow in explicit, reviewable
        # steps.
        self.calls.append(
            {
                "kind": "stream",
                "query": query,
                "parameters": parameters,
                # Keep settings named so the kind and query payload passed to append
                # remains self-describing within fake client query row block stream.
                "settings": settings,
                "query_tz": query_tz,
                "transport_settings": transport_settings,
            }
        )
        # Assemble stream once so the fake client query row block stream workflow shares
        # one value.
        stream = _FakeStream(self.blocks)
        self.streams.append(stream)
        return stream


# Keep the failing client contract and validation rules together.
class _FailingClient(_FakeClient):
    def query_row_block_stream(self, *args: Any, **kwargs: Any) -> _FakeStream:
        # Execute the failing client query row block stream workflow in explicit,
        # reviewable steps.
        raise RuntimeError(
            "connection failed: http://readonly:plain-text-password@secret.example:8123"
        )


def _descriptor() -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=CapabilityId("swaps.v1"),
        protocol="fixture",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # fixture input in descriptor.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("block_ordinal", "tx_idx", "signature", "amount"),
        mandatory_columns=("block_ordinal", "tx_idx", "signature"),
        fidelity=SourceFidelity(
            IdentityFidelity.CANDIDATE,
            # Pass ordering fidelity explicitly so SourceFidelity receives a reviewable
            # candidate and transaction exact input in descriptor.
            OrderingFidelity.TRANSACTION_EXACT,
            StateFidelity.NONE,
            FeesFidelity.UNKNOWN,
            ChainFinality.UNKNOWN,
            IngestionCompleteness.UNKNOWN,
            # Pass source consistency explicitly so SourceFidelity receives a reviewable
            # candidate and transaction exact input in descriptor.
            SourceConsistency.BEST_EFFORT,
        ),
        total_key=("signature", "tx_idx"),
        keyset_key_is_proven=True,
    )


# Define mapping as one focused operation with an explicit boundary.
def _mapping() -> ClickHouseCapability:
    # Execute the mapping workflow in explicit, reviewable steps.
    descriptor = _descriptor()
    return ClickHouseCapability(
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass database explicitly so ClickHouseCapability receives a reviewable default
        # and swaps input in mapping.
        database="default",
        table="swaps",
        logical_to_physical={
            column: "slot" if column == "block_ordinal" else column for column in descriptor.columns
        },
        # Pass order by explicitly so ClickHouseCapability receives a reviewable default
        # and swaps input in mapping.
        order_by=("block_ordinal", "signature", "tx_idx"),
    )


def _request(*, max_rows: int = 100) -> ExtractionRequest:
    # Execute the request workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        20,
    )
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("sha256:" + "c" * 64),
        shard=DatasetShard(
            ordinal=0,
            capability_id=CapabilityId("swaps.v1"),
            # Include block range in the completed request result.
            block_range=block_range,
            columns=("block_ordinal", "tx_idx", "signature", "amount"),
        ),
        decision_range=block_range,
        query_limits=QueryLimits(15, 1024**3, max_rows),
    )


# Define reader as one focused operation with an explicit boundary.
def _reader(client: _FakeClient) -> ClickHouseSourceReader:
    # Execute the reader workflow in explicit, reviewable steps.
    return ClickHouseSourceReader(
        client=client,
        source_id=SourceId("primary-indexer"),
        capabilities=(_mapping(),),
        policy=ClickHouseQueryPolicy(max_block_span=100, max_result_rows=1000),
        # Pass query id factory explicitly so ClickHouseSourceReader receives a reviewable
        # primary-indexer and bt input in reader.
        query_id_factory=lambda operation: f"bt_{operation}",
    )


def test_metadata_inspection_is_bounded_secret_free_and_closes_results() -> None:
    # Execute the test metadata inspection is bounded secret free and closes results
    # workflow in explicit, reviewable steps.
    client = _FakeClient()
    reader = _reader(client)

    metadata = reader.inspect_metadata(SourceId("primary-indexer"))
    fingerprint = source_schema_fingerprint(metadata)

    assert metadata.server_version == "24.6.2.17"
    # Verify the name, swaps and tables relationship before this scenario is accepted.
    assert metadata.tables[0].name == "default.swaps"
    assert metadata.tables[0].columns[0].name == "amount"
    assert metadata.tables[0].columns[0].nullable is True
    assert metadata.capability_mapping_digest is not None
    assert metadata.query_template_digest is not None
    # Verify len(fingerprint.hex) == 64 before this scenario is accepted.
    assert len(fingerprint.hex) == 64
    assert all(result.closed for result in client.results)
    assert "super-secret" not in repr(reader)
    assert "secret.example" not in repr(reader)

    for call in client.calls:
        # Process client.calls inside the bounded test metadata inspection is bounded
        # secret free and closes results loop.
        sql = call["query"]
        normalized = " ".join(sql.upper().split())
        assert normalized.startswith("SELECT ")
        assert "SELECT *" not in normalized
        assert " OFFSET " not in f" {normalized} "
        # Verify call['settings']['readonly'] == 1 before this scenario is accepted.
        assert call["settings"]["readonly"] == 1
        assert call["settings"]["max_block_size"] == 8_192
        assert call["query_tz"] == "UTC"
        assert call["transport_settings"]["query_id"].startswith("bt_")
        assert "password" not in str(call)


def test_scan_streams_blocks_preserves_duplicates_and_closes_context() -> None:
    # DatasetShard sorts the projection to amount, block_ordinal, signature, tx_idx.
    duplicate = (7, 11, "same", 3)
    client = _FakeClient(blocks=(((5, 10, "first", 1), duplicate), (duplicate,)))
    reader = _reader(client)

    batches = tuple(reader.scan(_request()))

    assert [batch.row_count for batch in batches] == [2, 1]
    # Verify the rows and batches relationship before this scenario is accepted.
    assert batches[0].rows[1] == batches[1].rows[0]
    assert client.streams[0].closed is True
    call = client.calls[-1]
    assert call["kind"] == "stream"
    assert call["parameters"] == {"from_block_ordinal": 10, "to_block_ordinal": 20}
    # Verify the max result rows, call and settings relationship before this scenario is
    # accepted.
    assert call["settings"]["max_result_rows"] == 100
    assert call["settings"]["readonly"] == 1
    assert call["settings"]["max_block_size"] == 8_192
    assert call["query_tz"] == "UTC"
    assert call["transport_settings"] == {"query_id": "bt_scan"}


def test_driver_error_is_not_retained_in_public_exception() -> None:
    # Execute the test driver error is not retained in public exception workflow in
    # explicit, reviewable steps.
    reader = _reader(_FailingClient())

    with pytest.raises(SourceAdapterError) as caught:
        tuple(reader.scan(_request()))

    rendered = str(caught.value)
    assert "plain-text-password" not in rendered
    # Verify 'secret.example' not in rendered before this scenario is accepted.
    assert "secret.example" not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert rendered == ("Source scan failed (query_id=bt_scan); driver details were suppressed.")


def test_rows_outside_half_open_range_abort_the_stream() -> None:
    # Execute the test rows outside half open range abort the stream workflow in explicit,
    # reviewable steps.
    client = _FakeClient(blocks=(((1, 20, "outside", 0),),))
    reader = _reader(client)

    with pytest.raises(SourceAdapterError, match="Source scan failed"):
        tuple(reader.scan(_request()))

    assert client.streams[0].closed is True


# Define test local row ceiling defends against non compliant driver as one focused
# operation with an explicit boundary.
def test_local_row_ceiling_defends_against_non_compliant_driver() -> None:
    # Execute the test local row ceiling defends against non compliant driver workflow in
    # explicit, reviewable steps.
    client = _FakeClient(
        blocks=(
            ((1, 10, "a", 0), (2, 11, "b", 1)),
            ((3, 12, "c", 2),),
        )
        # Complete _FakeClient only after its a and b inputs are visible in test local row
        # ceiling defends against non compliant driver.
    )
    reader = _reader(client)

    iterator = reader.scan(_request(max_rows=2))
    first = next(iterator)
    assert first.row_count == 2
    # Acquire raises, source adapter error and pytest at an explicit test local row
    # ceiling defends against non compliant driver context boundary so cleanup remains
    # scoped.
    with pytest.raises(SourceAdapterError, match="Source scan failed"):
        next(iterator)
    assert client.streams[0].closed is True


def test_unsafe_query_id_factory_is_rejected_before_driver_call() -> None:
    # Execute the test unsafe query id factory is rejected before driver call workflow in
    # explicit, reviewable steps.
    client = _FakeClient()
    reader = ClickHouseSourceReader(
        client=client,
        source_id=SourceId("primary-indexer"),
        capabilities=(_mapping(),),
        # Pass query id factory explicitly so ClickHouseSourceReader receives a reviewable
        # primary-indexer and unsafe/id?password=leak input in test unsafe query id
        # factory is rejected before driver call.
        query_id_factory=lambda _: "unsafe/id?password=leak",
    )

    with pytest.raises(ValueError, match="unsafe identifier"):
        tuple(reader.scan(_request()))
    assert client.calls == []
