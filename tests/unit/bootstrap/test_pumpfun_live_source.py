from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
    PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE,
    PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE,
    PumpfunIndexerV1Query,
    pumpfun_indexer_v1_physical_mapping,
)
from backtest.adapters.source.clickhouse.query import ClickHouseCapability
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceBatch
from backtest.application.models import (
    BoundedSourceEvidenceRequest,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    DatasetShard,
    EvidenceStatus,
    ExtractionRequest,
    QueryLimits,
)
from backtest.bootstrap.pumpfun_live_source import (
    PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS,
    PUMPFUN_LIVE_FEE_EFFECTIVE_FROM_UNIX_S,
    PUMPFUN_LIVE_FEE_EFFECTIVE_UNTIL_UNIX_S,
    PUMPFUN_LIVE_FEE_PROFILE_ID,
    PumpfunLiveSourceError,
    PumpfunLiveSourceErrorCode,
    build_pumpfun_live_source_composition,
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
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES,
    PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES,
    PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
    PUMPFUN_LEGACY_TOKEN_PROGRAM,
    PUMPFUN_MIGRATION_MINT_AMOUNT,
    PUMPFUN_POOL_MIGRATION_FEE,
    PUMPFUN_REAL_SOL_OFFSET,
    PUMPFUN_REAL_TOKEN_OFFSET,
    PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
)

_TIME = datetime(2026, 9, 1, tzinfo=UTC)
_TIME_S = int(_TIME.timestamp())
_SOURCE_ID = SourceId("pumpfun-live-test-source")
_PROJECTOR_DIGEST = ContentDigest("a" * 64)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TABLES = {
    CapabilityStream.BLOCK_CLOCK: "solana_blocks",
    CapabilityStream.TOKEN_LAUNCH: "pumpfun_token_creation",
    CapabilityStream.PUMP_CURVE_TRADE: "pumpfun_v2_swaps",
    CapabilityStream.PUMP_CURVE_LIFECYCLE: "pfamm_migrations",
}


@dataclass(frozen=True, slots=True)
class _Call:
    stream: CapabilityStream
    block_range: BlockRange
    query: PumpfunIndexerV1Query


class _Reader:
    def __init__(
        self,
        rows: dict[CapabilityStream, tuple[dict[str, object], ...]],
        *,
        suppress_scan_batches: bool = False,
    ) -> None:
        self.rows = rows
        self.suppress_scan_batches = suppress_scan_batches
        self.calls: list[_Call] = []

    def scan_pumpfun_indexer_v1(
        self,
        request: ExtractionRequest,
        query: PumpfunIndexerV1Query,
    ) -> tuple[SourceBatch, ...]:
        stream = _stream_for_capability(request.shard.capability_id)
        self.calls.append(_Call(stream, request.shard.block_range, query))
        if self.suppress_scan_batches:
            return ()
        return (self._batch(stream, request.shard.block_range, query),)

    def stream_pumpfun_indexer_v1_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
        *,
        capability_id: CapabilityId,
        block_range: BlockRange,
        query: PumpfunIndexerV1Query,
    ) -> tuple[SourceBatch, ...]:
        del request
        stream = _stream_for_capability(capability_id)
        self.calls.append(_Call(stream, block_range, query))
        return (self._batch(stream, block_range, query),)

    def _batch(
        self,
        stream: CapabilityStream,
        block_range: BlockRange,
        query: PumpfunIndexerV1Query,
    ) -> SourceBatch:
        selected = tuple(
            row
            for row in self.rows[stream]
            if block_range.contains_block(cast(int, row["block_ordinal"]))
        )
        return SourceBatch(
            capability_id=_capability_id(stream),
            covered_range=block_range,
            columns=query.columns,
            rows=tuple(tuple(row[column] for column in query.columns) for row in selected),
            query_fingerprint=query.fingerprint,
        )


def test_composition_exposes_canonical_metadata_and_stream_specific_fidelity() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())

    profile = composition.normalizer.fee_profile
    assert (
        profile.profile_id,
        profile.effective_from_unix_s,
        profile.effective_until_unix_s,
        profile.protocol_fee_bps,
        profile.creator_fee_bps,
    ) == (
        PUMPFUN_LIVE_FEE_PROFILE_ID,
        PUMPFUN_LIVE_FEE_EFFECTIVE_FROM_UNIX_S,
        PUMPFUN_LIVE_FEE_EFFECTIVE_UNTIL_UNIX_S,
        95,
        30,
    )
    metadata = {item.stream: item for item in composition.metadata_capabilities}
    projected = {
        item.descriptor.stream: item.descriptor for item in composition.projection_capabilities
    }
    assert set(metadata) == set(CapabilityStream)
    for stream, descriptor in metadata.items():
        assert set(descriptor.columns) == set(composition.normalizer.output_columns(stream))
        assert descriptor.fidelity.identity is IdentityFidelity.UNKNOWN
        assert descriptor.fidelity.ordering is OrderingFidelity.UNKNOWN
        assert descriptor.proofs == CapabilityProofs()
        assert descriptor.keyset_key_is_proven
        assert "block_ordinal" in descriptor.total_key

    assert projected[CapabilityStream.BLOCK_CLOCK].fidelity == _fidelity(
        OrderingFidelity.TRANSACTION_EXACT,
        StateFidelity.NONE,
        FeesFidelity.UNKNOWN,
    )
    assert projected[CapabilityStream.TOKEN_LAUNCH].fidelity == _fidelity(
        OrderingFidelity.INSTRUCTION_EXACT,
        StateFidelity.AFTER_ONLY,
        FeesFidelity.UNKNOWN,
    )
    assert projected[CapabilityStream.PUMP_CURVE_TRADE].fidelity == _fidelity(
        OrderingFidelity.INSTRUCTION_EXACT,
        StateFidelity.AFTER_ONLY,
        FeesFidelity.COMPONENTS,
    )
    assert projected[CapabilityStream.PUMP_CURVE_LIFECYCLE].fidelity == _fidelity(
        OrderingFidelity.INSTRUCTION_EXACT,
        StateFidelity.AFTER_ONLY,
        FeesFidelity.UNKNOWN,
    )


def test_scan_normalizes_rows_and_emits_exact_empty_query_receipt_batch() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    block_range = _range(10, 11)
    request = _extraction_request(composition, CapabilityStream.TOKEN_LAUNCH, block_range)
    populated = _Reader(_valid_rows())

    batches = tuple(composition.scan(cast(ClickHouseSourceReader, populated), request))

    assert len(batches) == 1
    assert batches[0].row_count == 1
    assert batches[0].columns == composition.normalizer.output_columns(
        CapabilityStream.TOKEN_LAUNCH
    )
    assert batches[0].query_fingerprint == populated.calls[0].query.fingerprint

    empty_reader = _Reader(_empty_rows(), suppress_scan_batches=True)
    empty_batches = tuple(composition.scan(cast(ClickHouseSourceReader, empty_reader), request))
    assert len(empty_batches) == 1
    assert empty_batches[0].row_count == 0
    assert empty_batches[0].query_fingerprint == empty_reader.calls[0].query.fingerprint

    tail_shard = replace(
        request,
        shard=replace(request.shard, block_range=_range(12, 13)),
    )
    with pytest.raises(PumpfunLiveSourceError) as raised:
        tuple(composition.scan(cast(ClickHouseSourceReader, _Reader(_valid_rows())), tail_shard))
    assert raised.value.code is PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH


def test_bounded_evidence_is_deterministic_cross_checked_and_structured() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    request = _evidence_request(composition, _range(10, 13), _range(10, 11))
    first_reader = _Reader(_valid_rows())
    second_reader = _Reader(_valid_rows())

    first = composition.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, first_reader),
        request,
        projector_digest=_PROJECTOR_DIGEST,
    )
    second = composition.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, second_reader),
        request,
        projector_digest=_PROJECTOR_DIGEST,
    )

    assert first == second
    assert len(first) == 4
    assert len({item.result_digest for item in first}) == 1
    assert len({item.cut_evidence.upstream_revision for item in first}) == 1
    assert all(item.cut_evidence.block_range == request.block_range for item in first)
    assert all(item.cut_evidence.chain_finality is ChainFinality.FINALIZED for item in first)
    assert all(
        item.cut_evidence.completeness is IngestionCompleteness.COMPLETE_TO_WATERMARK
        for item in first
    )
    assert all(
        item.cut_evidence.consistency is SourceConsistency.SNAPSHOT_CONSISTENT for item in first
    )

    by_stream = {_stream_for_capability(item.capability_id): item for item in first}
    assert by_stream[CapabilityStream.TOKEN_LAUNCH].launch_universe is not None
    assert by_stream[CapabilityStream.TOKEN_LAUNCH].launch_universe.classified_count == 2
    assert by_stream[CapabilityStream.TOKEN_LAUNCH].launch_universe.eligible_count == 1
    assert by_stream[CapabilityStream.TOKEN_LAUNCH].launch_universe.excluded_count == 1
    assert by_stream[CapabilityStream.BLOCK_CLOCK].skipped_slot_sentinel is not None
    assert by_stream[CapabilityStream.BLOCK_CLOCK].skipped_slot_sentinel.recognized_count == 1
    lifecycle = by_stream[CapabilityStream.PUMP_CURVE_LIFECYCLE].terminal_lifecycle_ordering
    assert lifecycle is not None
    assert lifecycle.derived_group_count == 1
    assert (
        by_stream[CapabilityStream.PUMP_CURVE_TRADE].proofs.curve_transitions_complete
        is EvidenceStatus.PROVEN
    )
    assert (
        by_stream[CapabilityStream.PUMP_CURVE_TRADE].proofs.fee_component_rounding_exact
        is EvidenceStatus.PROVEN
    )
    assert (
        by_stream[CapabilityStream.BLOCK_CLOCK].source_fidelity.ordering
        is OrderingFidelity.TRANSACTION_EXACT
    )
    assert by_stream[CapabilityStream.BLOCK_CLOCK].source_fidelity.state is StateFidelity.NONE
    assert by_stream[CapabilityStream.TOKEN_LAUNCH].source_fidelity.fees is FeesFidelity.UNKNOWN
    assert (
        by_stream[CapabilityStream.PUMP_CURVE_TRADE].source_fidelity.fees is FeesFidelity.COMPONENTS
    )

    ranges = {call.stream: call.block_range for call in first_reader.calls}
    assert ranges[CapabilityStream.TOKEN_LAUNCH] == request.decision_range
    assert ranges[CapabilityStream.BLOCK_CLOCK] == request.block_range
    assert ranges[CapabilityStream.PUMP_CURVE_TRADE] == request.block_range
    assert ranges[CapabilityStream.PUMP_CURVE_LIFECYCLE] == request.block_range


def test_bounded_evidence_fails_closed_on_cross_stream_mismatch() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    rows = _valid_rows()
    trade = dict(rows[CapabilityStream.PUMP_CURVE_TRADE][0])
    trade["block_time"] = _TIME_S + 1
    rows[CapabilityStream.PUMP_CURVE_TRADE] = (
        trade,
        *rows[CapabilityStream.PUMP_CURVE_TRADE][1:],
    )

    with pytest.raises(PumpfunLiveSourceError) as raised:
        composition.inspect_bounded_evidence(
            cast(ClickHouseSourceReader, _Reader(rows)),
            _evidence_request(composition, _range(10, 13), _range(10, 11)),
            projector_digest=_PROJECTOR_DIGEST,
        )
    assert raised.value.code is PumpfunLiveSourceErrorCode.TRANSACTION_CLOCK_MISMATCH


def test_bundle_count_is_nonbinding_but_same_signature_contract_is_strict() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    rows = _valid_rows()
    launch = dict(rows[CapabilityStream.TOKEN_LAUNCH][0])
    launch["bundled_buys_count"] = 4
    rows[CapabilityStream.TOKEN_LAUNCH] = (
        launch,
        *rows[CapabilityStream.TOKEN_LAUNCH][1:],
    )
    request = _evidence_request(composition, _range(10, 13), _range(10, 11))

    composition.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, _Reader(rows)),
        request,
        projector_digest=_PROJECTOR_DIGEST,
    )

    wrong_transaction = dict(rows[CapabilityStream.PUMP_CURVE_TRADE][0])
    wrong_transaction["transaction_index"] = 2
    rows[CapabilityStream.PUMP_CURVE_TRADE] = (
        wrong_transaction,
        *rows[CapabilityStream.PUMP_CURVE_TRADE][1:],
    )
    with pytest.raises(PumpfunLiveSourceError) as raised:
        composition.inspect_bounded_evidence(
            cast(ClickHouseSourceReader, _Reader(rows)),
            request,
            projector_digest=_PROJECTOR_DIGEST,
        )
    assert raised.value.code is PumpfunLiveSourceErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH


def test_same_creation_transaction_sell_is_applied_but_is_not_a_bundled_buy() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    rows = _valid_rows()
    first, terminal = rows[CapabilityStream.PUMP_CURVE_TRADE]
    first_virtual_token = int(first["virtual_token_reserves_after_atomic"])
    first_virtual_sol = int(first["virtual_sol_reserves_after_lamports"])
    same_transaction_sell = _trade_row(
        block=10,
        transaction=0,
        instruction=3,
        signature=str(first["signature"]),
        mint=str(first["mint"]),
        curve_address=str(first["curve_address"]),
        creator=str(first["creator"]),
        creation_user=str(first["creation_user"]),
        direction="sell",
        base=50,
        quote=50,
        virtual_token=first_virtual_token + 50,
        virtual_sol=first_virtual_sol - 50,
    )
    adjusted_terminal = dict(terminal)
    adjusted_terminal["base_amount_atomic"] = first_virtual_token + 50 - PUMPFUN_REAL_TOKEN_OFFSET
    adjusted_terminal["quote_amount_atomic"] = int(
        terminal["virtual_sol_reserves_after_lamports"]
    ) - (first_virtual_sol - 50)
    rows[CapabilityStream.PUMP_CURVE_TRADE] = (
        first,
        same_transaction_sell,
        adjusted_terminal,
    )

    receipts = composition.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, _Reader(rows)),
        _evidence_request(composition, _range(10, 13), _range(10, 11)),
        projector_digest=_PROJECTOR_DIGEST,
    )

    assert len(receipts) == 4


def test_bounded_evidence_shards_at_4096_and_rejects_identity_drift() -> None:
    composition = build_pumpfun_live_source_composition(_capabilities())
    full = _range(0, PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS + 1)
    decision = _range(0, 1)
    rows = _empty_rows()
    rows[CapabilityStream.BLOCK_CLOCK] = tuple(
        _block_row(block, transactions=0, block_time=_TIME_S)
        for block in range(full.to_block_ordinal)
    )
    reader = _Reader(rows)
    request = _evidence_request(composition, full, decision)

    composition.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, reader),
        request,
        projector_digest=_PROJECTOR_DIGEST,
    )

    assert all(call.block_range.span <= 4_096 for call in reader.calls)
    launch_calls = [call for call in reader.calls if call.stream is CapabilityStream.TOKEN_LAUNCH]
    assert [item.block_range for item in launch_calls] == [decision]
    assert len([call for call in reader.calls if call.stream is CapabilityStream.BLOCK_CLOCK]) == 2

    drifted = replace(request, normalizer_digest=ContentDigest("b" * 64))
    with pytest.raises(PumpfunLiveSourceError) as raised:
        composition.inspect_bounded_evidence(
            cast(ClickHouseSourceReader, _Reader(rows)),
            drifted,
            projector_digest=_PROJECTOR_DIGEST,
        )
    assert raised.value.code is PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH


def _capability_id(stream: CapabilityStream) -> CapabilityId:
    return CapabilityId(f"pumpfun-live-test.{stream.value.lower()}.v1")


def _stream_for_capability(capability_id: CapabilityId) -> CapabilityStream:
    for stream in CapabilityStream:
        if _capability_id(stream) == capability_id:
            return stream
    raise AssertionError("unknown fixture capability")


def _capabilities() -> tuple[ClickHouseCapability, ...]:
    fidelity = SourceFidelity(
        identity=IdentityFidelity.UNKNOWN,
        ordering=OrderingFidelity.UNKNOWN,
        state=StateFidelity.NONE,
        fees=FeesFidelity.UNKNOWN,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )
    result: list[ClickHouseCapability] = []
    for stream in CapabilityStream:
        mapping = pumpfun_indexer_v1_physical_mapping(stream)
        result.append(
            ClickHouseCapability(
                descriptor=CapabilityDescriptor(
                    capability_id=_capability_id(stream),
                    protocol=("solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun"),
                    protocol_version="raw-source-v1",
                    schema_version=PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
                    stream=stream,
                    columns=tuple(mapping),
                    mandatory_columns=("block_ordinal",),
                    fidelity=fidelity,
                    proofs=CapabilityProofs(),
                ),
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                database="default",
                table=_TABLES[stream],
                logical_to_physical=mapping,
            )
        )
    return tuple(result)


def _range(start: int, end: int) -> BlockRange:
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        start,
        end,
    )


def _limits() -> QueryLimits:
    return QueryLimits(
        max_execution_seconds=30,
        max_memory_bytes=64 * 1024**2,
        max_result_rows=100_000,
    )


def _extraction_request(
    composition: Any,
    stream: CapabilityStream,
    block_range: BlockRange,
) -> ExtractionRequest:
    descriptor = next(item for item in composition.metadata_capabilities if item.stream is stream)
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("c" * 64),
        shard=DatasetShard(0, descriptor.capability_id, block_range, descriptor.columns),
        decision_range=block_range,
        query_limits=_limits(),
    )


def _evidence_request(
    composition: Any,
    block_range: BlockRange,
    decision_range: BlockRange,
) -> BoundedSourceEvidenceRequest:
    return BoundedSourceEvidenceRequest(
        source_id=_SOURCE_ID,
        block_range=block_range,
        decision_range=decision_range,
        capability_mapping_digest=composition.capability_mapping_digest,
        query_template_digest=composition.query_template_digest,
        projector_digest=_PROJECTOR_DIGEST,
        normalizer_digest=composition.normalizer_digest,
        launch_universe_policy_id=PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
        skipped_slot_sentinel_policy_id=SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
        terminal_lifecycle_ordering_policy_id=PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
        query_limits=_limits(),
    )


def _fidelity(
    ordering: OrderingFidelity,
    state: StateFidelity,
    fees: FeesFidelity,
) -> SourceFidelity:
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=ordering,
        state=state,
        fees=fees,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )


def _valid_rows() -> dict[CapabilityStream, tuple[dict[str, object], ...]]:
    signature = _signature(1)
    terminal_signature = _signature(3)
    mint = _key(11)
    curve = _key(41)
    creator = _key(21)
    creation_user = _key(31)
    first_virtual_token = PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES - 100
    first_virtual_sol = PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES + 101
    terminal_quote = 20_000_000
    terminal_virtual_sol = first_virtual_sol + terminal_quote
    migration_sol = terminal_virtual_sol - PUMPFUN_REAL_SOL_OFFSET - PUMPFUN_POOL_MIGRATION_FEE
    eligible = _launch_row(
        transaction=0,
        signature=signature,
        mint=mint,
        curve=curve,
        creator=creator,
        creation_user=creation_user,
        bundled_buys_count=1,
    )
    excluded = _launch_row(
        transaction=1,
        signature=_signature(2),
        mint=_key(12),
        curve=_key(42),
        creator=_key(22),
        creation_user=_key(32),
        mayhem_mode=1,
    )
    common = {
        "mint": mint,
        "creator": creator,
        "creation_user": creation_user,
        "curve_address": curve,
    }
    return {
        CapabilityStream.BLOCK_CLOCK: (
            _block_row(10, transactions=3, block_time=_TIME_S),
            _sentinel_row(11),
            _block_row(12, transactions=2, block_time=_TIME_S + 2),
        ),
        CapabilityStream.TOKEN_LAUNCH: (eligible, excluded),
        CapabilityStream.PUMP_CURVE_TRADE: (
            _trade_row(
                block=10,
                transaction=0,
                instruction=2,
                signature=signature,
                base=100,
                quote=101,
                virtual_token=first_virtual_token,
                virtual_sol=first_virtual_sol,
                **common,
            ),
            _trade_row(
                block=12,
                transaction=0,
                instruction=2,
                signature=terminal_signature,
                base=first_virtual_token - PUMPFUN_REAL_TOKEN_OFFSET,
                quote=terminal_quote,
                virtual_token=PUMPFUN_REAL_TOKEN_OFFSET,
                virtual_sol=terminal_virtual_sol,
                **common,
            ),
        ),
        CapabilityStream.PUMP_CURVE_LIFECYCLE: (
            _completion_row(
                signature=terminal_signature,
                terminal_virtual_sol=terminal_virtual_sol,
                **common,
            ),
            _migration_row(
                signature=terminal_signature,
                migration_sol=migration_sol,
                terminal_virtual_sol=terminal_virtual_sol,
                **common,
            ),
        ),
    }


def _empty_rows() -> dict[CapabilityStream, tuple[dict[str, object], ...]]:
    return dict.fromkeys(CapabilityStream, ())


def _block_row(
    block: int,
    *,
    transactions: int,
    block_time: int,
) -> dict[str, object]:
    return {
        "block_ordinal": block,
        "block_time": block_time,
        "block_hash": _fixed(_key(70)),
        "validator": _fixed(_key(71)),
        "rewards": 0,
        "transaction_count": transactions,
        "source_row_count": 1,
        "payload_variant_count": 1,
        "is_nonproduced_sentinel": 0,
    }


def _sentinel_row(block: int) -> dict[str, object]:
    return {
        "block_ordinal": block,
        "block_time": 0,
        "block_hash": " " * 48,
        "validator": "MISSING" + " " * 41,
        "rewards": 0,
        "transaction_count": 0,
        "source_row_count": 1,
        "payload_variant_count": 1,
        "is_nonproduced_sentinel": 1,
    }


def _launch_row(
    *,
    transaction: int,
    signature: str,
    mint: str,
    curve: str,
    creator: str,
    creation_user: str,
    mayhem_mode: int = 0,
    bundled_buys_count: int = 0,
) -> dict[str, object]:
    return {
        "block_ordinal": 10,
        "block_time": _TIME_S,
        "transaction_index": transaction,
        "raw_instruction_index": 1,
        "signature": signature,
        "mint": mint,
        "creator": creator,
        "creation_user": creation_user,
        "curve_address": curve,
        "quote_asset": PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE,
        "mayhem_mode": mayhem_mode,
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "direct_pump_invocation": 1,
        "pump_program_index": 4,
        "parent_program": _key(80),
        "source_version": _TIME,
        "bundle_size": 1,
        "bundle_structure": "[]",
        "bundled_buys": 0,
        "bundled_buys_count": bundled_buys_count,
        "dev_balance": 0,
    }


def _trade_row(
    *,
    block: int,
    transaction: int,
    instruction: int,
    signature: str,
    mint: str,
    curve_address: str,
    creator: str,
    creation_user: str,
    base: int,
    quote: int,
    virtual_token: int,
    virtual_sol: int,
    direction: str = "buy",
) -> dict[str, object]:
    return {
        "block_ordinal": block,
        "block_time": _TIME_S + block - 10,
        "transaction_index": transaction,
        "raw_instruction_index": instruction,
        "signature": signature,
        "mint": mint,
        "quote_asset": PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE,
        "direction": direction,
        "instruction_type": "buy_v2" if direction == "buy" else "sell",
        "base_amount_atomic": base,
        "quote_amount_atomic": quote,
        "virtual_token_reserves_after_atomic": virtual_token,
        "virtual_sol_reserves_after_lamports": virtual_sol,
        "failed": 0,
        "signing_wallet": _key(51),
        "fee_payer": _key(52),
        "parent_program": _key(53),
        "provided_gas_fee_lamports": 1,
        "provided_gas_limit": 100_000,
        "network_fee_lamports": 5_001,
        "consumed_gas": 50_000,
        "pump_program_account_index": 3,
        "cu_price_instruction_index": 0,
        "cu_limit_instruction_index": 1,
        "tip_instruction_index": -1,
        "num_signatures": 1,
        "transaction_version": 0,
        "blockhash_prefix": "abc",
        "creation_block_ordinal": 10,
        "creation_transaction_index": 0,
        "creation_raw_instruction_index": 1,
        "creator": creator,
        "creation_user": creation_user,
        "curve_address": curve_address,
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _completion_row(
    *,
    signature: str,
    mint: str,
    curve_address: str,
    creator: str,
    creation_user: str,
    terminal_virtual_sol: int,
) -> dict[str, object]:
    del creator, creation_user
    return {
        "candidate_kind": "COMPLETION_CANDIDATE",
        "block_ordinal": 12,
        "block_time": _TIME_S + 2,
        "transaction_index": 0,
        "raw_instruction_index": 2,
        "signature": signature,
        "mint": mint,
        "curve_address": curve_address,
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "creation_block_ordinal": 10,
        "creation_transaction_index": 0,
        "creation_raw_instruction_index": 1,
        "terminal_raw_instruction_index": 2,
        "terminal_virtual_token_reserves_after_atomic": PUMPFUN_REAL_TOKEN_OFFSET,
        "terminal_virtual_sol_reserves_after_lamports": terminal_virtual_sol,
        "terminal_candidate_count": 1,
        "terminal_source_row_count": 1,
        "terminal_payload_variant_count": 1,
        "migration_user": None,
        "migration_mint_amount_atomic": None,
        "migration_sol_amount_lamports": None,
        "pool_migration_fee_lamports": None,
        "migration_pool": None,
        "migration_timestamp": None,
        "migration_parent_program": None,
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _migration_row(
    *,
    signature: str,
    mint: str,
    curve_address: str,
    creator: str,
    creation_user: str,
    migration_sol: int,
    terminal_virtual_sol: int,
) -> dict[str, object]:
    del creator, creation_user
    return {
        "candidate_kind": "MIGRATION_CANDIDATE",
        "block_ordinal": 12,
        "block_time": _TIME_S + 2,
        "transaction_index": 0,
        "raw_instruction_index": None,
        "signature": signature,
        "mint": mint,
        "curve_address": curve_address,
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "creation_block_ordinal": 10,
        "creation_transaction_index": 0,
        "creation_raw_instruction_index": 1,
        "terminal_raw_instruction_index": 2,
        "terminal_virtual_token_reserves_after_atomic": PUMPFUN_REAL_TOKEN_OFFSET,
        "terminal_virtual_sol_reserves_after_lamports": terminal_virtual_sol,
        "terminal_candidate_count": 1,
        "terminal_source_row_count": 1,
        "terminal_payload_variant_count": 1,
        "migration_user": _key(61),
        "migration_mint_amount_atomic": PUMPFUN_MIGRATION_MINT_AMOUNT,
        "migration_sol_amount_lamports": migration_sol,
        "pool_migration_fee_lamports": PUMPFUN_POOL_MIGRATION_FEE,
        "migration_pool": _key(62),
        "migration_timestamp": int((_TIME + timedelta(seconds=2)).timestamp()),
        "migration_parent_program": _key(63),
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _fixed(value: str) -> str:
    return value + "\x00" * (48 - len(value))


def _key(seed: int) -> str:
    return _base58(bytes([seed]) * 32)


def _signature(seed: int) -> str:
    return _base58(bytes([seed]) * 64)


def _base58(value: bytes) -> str:
    leading_zeroes = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        encoded.append(_BASE58_ALPHABET[remainder])
    return "1" * leading_zeroes + "".join(reversed(encoded))
