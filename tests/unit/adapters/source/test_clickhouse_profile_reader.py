from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Any

import pytest

from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
    PUMPFUN_INDEXER_V1_PROFILE,
    PumpfunIndexerV1Query,
    pumpfun_indexer_v1_physical_mapping,
)
from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
    clickhouse_capability_mapping_digest,
)
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceAdapterError
from backtest.application.models import (
    BoundedSourceEvidenceRequest,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    DatasetShard,
    ExtractionRequest,
    QueryLimits,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange

_SOURCE_ID = SourceId("pumpfun-profile-source")
_TABLES = {
    CapabilityStream.BLOCK_CLOCK: "solana_blocks",
    CapabilityStream.TOKEN_LAUNCH: "pumpfun_token_creation",
    CapabilityStream.PUMP_CURVE_TRADE: "pumpfun_v2_swaps",
    CapabilityStream.PUMP_CURVE_LIFECYCLE: "pfamm_migrations",
}


@dataclass
class _Stream(AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]):
    blocks: Sequence[Sequence[Sequence[Any]]]
    closed: bool = False

    def __enter__(self) -> Iterator[Sequence[Sequence[Any]]]:
        return iter(self.blocks)

    def __exit__(self, *args: object) -> None:
        self.closed = True


class _Client:
    def __init__(self, blocks: Sequence[Sequence[Sequence[Any]]]) -> None:
        self.blocks = blocks
        self.calls: list[dict[str, Any]] = []
        self.streams: list[_Stream] = []

    def query(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("profile dispatch does not issue metadata queries")

    def query_row_block_stream(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _Stream:
        self.calls.append(
            {
                "parameters": parameters,
                "query": query,
                "query_tz": query_tz,
                "settings": settings,
                "transport_settings": transport_settings,
            }
        )
        stream = _Stream(self.blocks)
        self.streams.append(stream)
        return stream


def _range(start: int, end: int) -> BlockRange:
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        start,
        end,
    )


def _capability(stream: CapabilityStream) -> ClickHouseCapability:
    mapping = pumpfun_indexer_v1_physical_mapping(stream)
    return ClickHouseCapability(
        descriptor=CapabilityDescriptor(
            capability_id=CapabilityId(f"profile.{stream.value.lower()}.v1"),
            protocol="solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun",
            protocol_version="raw-source-v1",
            schema_version=PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
            stream=stream,
            columns=tuple(mapping),
            mandatory_columns=("block_ordinal",),
            fidelity=SourceFidelity(
                identity=IdentityFidelity.UNKNOWN,
                ordering=OrderingFidelity.UNKNOWN,
                state=StateFidelity.NONE,
                fees=FeesFidelity.UNKNOWN,
                chain_finality=ChainFinality.UNKNOWN,
                completeness=IngestionCompleteness.UNKNOWN,
                consistency=SourceConsistency.UNKNOWN,
            ),
            proofs=CapabilityProofs(),
        ),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table=_TABLES[stream],
        logical_to_physical=mapping,
    )


def _capabilities() -> tuple[ClickHouseCapability, ...]:
    return tuple(_capability(stream) for stream in CapabilityStream)


def _reader(client: _Client, *, policy: ClickHouseQueryPolicy) -> ClickHouseSourceReader:
    return ClickHouseSourceReader(
        client=client,
        source_id=_SOURCE_ID,
        capabilities=_capabilities(),
        policy=policy,
        query_id_factory=lambda operation: f"bt_{operation}",
    )


def _query(
    stream: CapabilityStream,
    *,
    block_range: BlockRange,
    decision_range: BlockRange,
    policy: ClickHouseQueryPolicy,
) -> PumpfunIndexerV1Query:
    return PUMPFUN_INDEXER_V1_PROFILE.build_query(
        stream=stream,
        database="default",
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )


def _row(query: PumpfunIndexerV1Query, block_ordinal: int) -> tuple[Any, ...]:
    values: list[Any] = [0] * len(query.columns)
    values[query.block_ordinal_column_index] = block_ordinal
    return tuple(values)


def _extraction_request(
    stream: CapabilityStream,
    *,
    block_range: BlockRange,
    decision_range: BlockRange,
    max_rows: int = 100,
) -> ExtractionRequest:
    capability = _capability(stream)
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("a" * 64),
        shard=DatasetShard(
            ordinal=0,
            capability_id=capability.descriptor.capability_id,
            block_range=block_range,
            columns=capability.descriptor.columns,
        ),
        decision_range=decision_range,
        query_limits=QueryLimits(30, 1024**3, max_rows),
    )


def _evidence_request(
    *,
    block_range: BlockRange,
    decision_range: BlockRange,
    max_rows: int = 100,
) -> BoundedSourceEvidenceRequest:
    return BoundedSourceEvidenceRequest(
        source_id=_SOURCE_ID,
        block_range=block_range,
        decision_range=decision_range,
        capability_mapping_digest=clickhouse_capability_mapping_digest(_capabilities()),
        query_template_digest=PUMPFUN_INDEXER_V1_PROFILE.template_digest,
        projector_digest=ContentDigest("b" * 64),
        normalizer_digest=ContentDigest("c" * 64),
        launch_universe_policy_id="successful-sol-paired-non-mayhem-v2",
        skipped_slot_sentinel_policy_id="skipped-slot-sentinel-v1",
        terminal_lifecycle_ordering_policy_id="terminal-lifecycle-order-v1",
        query_limits=QueryLimits(30, 1024**3, max_rows),
    )


def test_fixed_profile_scan_preserves_raw_contract_fingerprint_and_sdk_bounds() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=1_000)
    block_range = _range(180, 260)
    decision_range = _range(100, 200)
    query = _query(
        CapabilityStream.PUMP_CURVE_TRADE,
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )
    client = _Client(((_row(query, 180), _row(query, 259)),))
    reader = _reader(client, policy=policy)

    batches = tuple(
        reader.scan_pumpfun_indexer_v1(
            _extraction_request(
                CapabilityStream.PUMP_CURVE_TRADE,
                block_range=block_range,
                decision_range=decision_range,
            ),
            query,
        )
    )

    assert len(batches) == 1
    assert batches[0].capability_id == CapabilityId("profile.pump_curve_trade.v1")
    assert batches[0].covered_range == block_range
    assert batches[0].columns == query.columns
    assert batches[0].query_fingerprint == query.fingerprint
    call = client.calls[0]
    assert type(call["parameters"]) is dict
    assert call["parameters"] == dict(query.parameters)
    assert call["settings"]["readonly"] == 1
    assert call["settings"]["max_result_rows"] == 100
    assert call["settings"]["max_block_size"] == 8_192
    assert call["query_tz"] == "UTC"
    assert call["transport_settings"] == {"query_id": "bt_scan"}
    assert client.streams[0].closed is True


def test_fixed_profile_scan_rejects_range_decision_and_capability_mismatch_before_sdk() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=1_000)
    block_range = _range(180, 260)
    decision_range = _range(100, 200)
    client = _Client(())
    reader = _reader(client, policy=policy)
    request = _extraction_request(
        CapabilityStream.PUMP_CURVE_TRADE,
        block_range=block_range,
        decision_range=decision_range,
    )

    wrong_range = _query(
        CapabilityStream.PUMP_CURVE_TRADE,
        block_range=_range(181, 260),
        decision_range=decision_range,
        policy=policy,
    )
    with pytest.raises(ValueError, match="exact reader operands"):
        tuple(reader.scan_pumpfun_indexer_v1(request, wrong_range))

    wrong_decision = _query(
        CapabilityStream.PUMP_CURVE_TRADE,
        block_range=block_range,
        decision_range=_range(101, 200),
        policy=policy,
    )
    with pytest.raises(ValueError, match="exact reader operands"):
        tuple(reader.scan_pumpfun_indexer_v1(request, wrong_decision))

    wrong_stream = _query(
        CapabilityStream.PUMP_CURVE_LIFECYCLE,
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )
    with pytest.raises(ValueError, match="exact reader operands"):
        tuple(reader.scan_pumpfun_indexer_v1(request, wrong_stream))

    assert client.calls == []


def test_fixed_profile_scan_requires_the_exact_registered_four_stream_profile() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=1_000)
    block_range = _range(180, 260)
    decision_range = _range(100, 200)
    query = _query(
        CapabilityStream.PUMP_CURVE_TRADE,
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )
    capabilities = tuple(
        replace(
            capability,
            descriptor=replace(capability.descriptor, schema_version="generic-direct-v2"),
        )
        for capability in _capabilities()
    )
    client = _Client(())
    reader = ClickHouseSourceReader(
        client=client,
        source_id=_SOURCE_ID,
        capabilities=capabilities,
        policy=policy,
        query_id_factory=lambda operation: f"bt_{operation}",
    )

    with pytest.raises(ValueError, match="profile installed"):
        tuple(
            reader.scan_pumpfun_indexer_v1(
                _extraction_request(
                    CapabilityStream.PUMP_CURVE_TRADE,
                    block_range=block_range,
                    decision_range=decision_range,
                ),
                query,
            )
        )

    assert client.calls == []


def test_fixed_profile_evidence_streams_one_subrange_with_stricter_settings() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=20_000, evidence_max_block_span=8_192)
    whole_range = _range(0, 10_000)
    decision_range = _range(100, 200)
    subrange = _range(4_000, 8_096)
    query = _query(
        CapabilityStream.BLOCK_CLOCK,
        block_range=subrange,
        decision_range=decision_range,
        policy=policy,
    )
    client = _Client(((_row(query, 4_000),), (_row(query, 8_095),)))
    reader = _reader(client, policy=policy)

    batches = tuple(
        reader.stream_pumpfun_indexer_v1_evidence(
            _evidence_request(block_range=whole_range, decision_range=decision_range),
            capability_id=CapabilityId("profile.block_clock.v1"),
            block_range=subrange,
            query=query,
        )
    )

    assert [batch.row_count for batch in batches] == [1, 1]
    assert all(batch.covered_range == subrange for batch in batches)
    assert all(batch.query_fingerprint == query.fingerprint for batch in batches)
    call = client.calls[0]
    assert type(call["parameters"]) is dict
    assert call["parameters"] == dict(query.parameters)
    assert call["settings"]["readonly"] == 1
    assert call["settings"]["max_threads"] == 1
    assert call["settings"]["max_result_bytes"] == 64 * 1024**2
    assert call["settings"]["max_block_size"] == 8_192
    assert call["transport_settings"] == {"query_id": "bt_evidence_block_clock"}
    assert client.streams[0].closed is True


def test_fixed_profile_evidence_rejects_outside_or_over_4096_subrange_before_sdk() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=20_000, evidence_max_block_span=20_000)
    whole_range = _range(0, 10_000)
    decision_range = _range(100, 200)
    request = _evidence_request(block_range=whole_range, decision_range=decision_range)
    client = _Client(())
    reader = _reader(client, policy=policy)

    outside = _range(9_999, 10_001)
    outside_query = _query(
        CapabilityStream.BLOCK_CLOCK,
        block_range=outside,
        decision_range=decision_range,
        policy=policy,
    )
    with pytest.raises(ValueError, match="outside the bounded evidence request"):
        tuple(
            reader.stream_pumpfun_indexer_v1_evidence(
                request,
                capability_id=CapabilityId("profile.block_clock.v1"),
                block_range=outside,
                query=outside_query,
            )
        )

    oversized = _range(0, 4_097)
    oversized_query = _query(
        CapabilityStream.BLOCK_CLOCK,
        block_range=oversized,
        decision_range=decision_range,
        policy=policy,
    )
    with pytest.raises(ValueError, match="hard span limit"):
        tuple(
            reader.stream_pumpfun_indexer_v1_evidence(
                request,
                capability_id=CapabilityId("profile.block_clock.v1"),
                block_range=oversized,
                query=oversized_query,
            )
        )

    valid_subrange = _range(0, 1)
    valid_query = _query(
        CapabilityStream.BLOCK_CLOCK,
        block_range=valid_subrange,
        decision_range=decision_range,
        policy=policy,
    )
    for changed_request, message in (
        (replace(request, capability_mapping_digest=ContentDigest("d" * 64)), "mapping"),
        (replace(request, query_template_digest=ContentDigest("e" * 64)), "query-template"),
    ):
        with pytest.raises(ValueError, match=message):
            tuple(
                reader.stream_pumpfun_indexer_v1_evidence(
                    changed_request,
                    capability_id=CapabilityId("profile.block_clock.v1"),
                    block_range=valid_subrange,
                    query=valid_query,
                )
            )

    assert client.calls == []


def test_fixed_profile_evidence_row_cap_and_driver_details_fail_closed() -> None:
    policy = ClickHouseQueryPolicy(max_block_span=1_000)
    block_range = _range(180, 260)
    decision_range = _range(100, 200)
    query = _query(
        CapabilityStream.BLOCK_CLOCK,
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )
    client = _Client(((_row(query, 180), _row(query, 181)),))
    reader = _reader(client, policy=policy)
    evidence_range = _range(100, 260)

    with pytest.raises(SourceAdapterError) as caught:
        tuple(
            reader.stream_pumpfun_indexer_v1_evidence(
                _evidence_request(
                    block_range=evidence_range,
                    decision_range=decision_range,
                    max_rows=1,
                ),
                capability_id=CapabilityId("profile.block_clock.v1"),
                block_range=block_range,
                query=query,
            )
        )

    assert caught.value.operation == "evidence-query"
    assert caught.value.query_id == "bt_evidence_block_clock"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert client.streams[0].closed is True
