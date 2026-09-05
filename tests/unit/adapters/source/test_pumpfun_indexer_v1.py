from __future__ import annotations

from dataclasses import replace

import pytest

from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
    PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE,
    PUMPFUN_INDEXER_V1_PROFILE,
    PUMPFUN_INDEXER_V1_PROFILE_ID,
    PUMPFUN_INDEXER_V1_SENTINEL,
    PUMPFUN_INDEXER_V1_TERMINAL_VIRTUAL_TOKEN_RESERVES,
    PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE,
    PumpfunIndexerV1Query,
    pumpfun_indexer_v1_physical_mapping,
    registered_pumpfun_indexer_v1_profile,
)
from backtest.adapters.source.clickhouse.query import ClickHouseCapability, ClickHouseQueryPolicy
from backtest.application.models import CapabilityDescriptor, CapabilityProofs, CapabilityStream
from backtest.bootstrap.source import select_clickhouse_query_profile
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
from backtest.domain.identifiers import CapabilityId, NetworkId
from backtest.domain.time import BlockRange

_TABLES = {
    CapabilityStream.BLOCK_CLOCK: "solana_blocks",
    CapabilityStream.TOKEN_LAUNCH: "pumpfun_token_creation",
    CapabilityStream.PUMP_CURVE_TRADE: "pumpfun_v2_swaps",
    CapabilityStream.PUMP_CURVE_LIFECYCLE: "pfamm_migrations",
}


def _range(start: int, end: int) -> BlockRange:
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        start,
        end,
    )


def _capability(stream: CapabilityStream) -> ClickHouseCapability:
    mapping = pumpfun_indexer_v1_physical_mapping(stream)
    protocol = "solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun"
    descriptor = CapabilityDescriptor(
        capability_id=CapabilityId(f"profile.{stream.value.lower()}.v1"),
        protocol=protocol,
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
    )
    return ClickHouseCapability(
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table=_TABLES[stream],
        logical_to_physical=mapping,
    )


def _capabilities() -> tuple[ClickHouseCapability, ...]:
    return tuple(_capability(stream) for stream in CapabilityStream)


def _query(stream: CapabilityStream) -> PumpfunIndexerV1Query:
    return PUMPFUN_INDEXER_V1_PROFILE.build_query(
        stream=stream,
        database="default",
        block_range=_range(180, 260),
        decision_range=_range(100, 200),
        policy=ClickHouseQueryPolicy(max_block_span=1_000),
    )


def _normalized(sql: str) -> str:
    return " ".join(sql.split())


def test_registry_selects_only_exact_dedicated_four_stream_profile() -> None:
    capabilities = _capabilities()

    selected = registered_pumpfun_indexer_v1_profile(capabilities)

    assert selected is PUMPFUN_INDEXER_V1_PROFILE
    assert select_clickhouse_query_profile(capabilities) is selected
    assert selected.profile_id == PUMPFUN_INDEXER_V1_PROFILE_ID
    assert len(selected.template_digest.hex) == 64


def test_registry_leaves_generic_capabilities_unselected() -> None:
    generic = replace(
        _capability(CapabilityStream.BLOCK_CLOCK),
        descriptor=replace(
            _capability(CapabilityStream.BLOCK_CLOCK).descriptor,
            schema_version="generic-direct-v2",
        ),
    )

    assert registered_pumpfun_indexer_v1_profile((generic,)) is None


def test_registry_rejects_partial_mapping_drift_and_static_promotion() -> None:
    capabilities = _capabilities()
    trade = next(
        item for item in capabilities if item.descriptor.stream is CapabilityStream.PUMP_CURVE_TRADE
    )
    changed_mapping = dict(trade.logical_to_physical)
    changed_mapping["mint"] = "wrong_mint"
    drifted = replace(trade, logical_to_physical=changed_mapping)

    with pytest.raises(ValueError, match="column mapping mismatch"):
        registered_pumpfun_indexer_v1_profile(
            tuple(drifted if item is trade else item for item in capabilities)
        )

    promoted = replace(
        trade,
        descriptor=replace(
            trade.descriptor,
            fidelity=replace(trade.descriptor.fidelity, identity=IdentityFidelity.EXACT),
        ),
    )
    with pytest.raises(ValueError, match="unpromoted"):
        registered_pumpfun_indexer_v1_profile(
            tuple(promoted if item is trade else item for item in capabilities)
        )


def test_block_query_collapses_exact_duplicates_and_exposes_full_payload_variants() -> None:
    query = _query(CapabilityStream.BLOCK_CLOCK)
    normalized = _normalized(query.sql)

    assert "FROM `default`.`solana_blocks`" in normalized
    assert "GROUP BY b.slot" in normalized
    assert "count() AS source_row_count" in normalized
    assert (
        "uniqExact(tuple(b.block_time, b.hash, b.validator, b.rewards, "
        "b.amount_of_transactions)) AS payload_variant_count"
    ) in normalized
    assert "ORDER BY b.slot" in normalized
    assert query.parameters["from_block_ordinal"] == 180
    assert query.parameters["to_block_ordinal"] == 260


def test_block_sentinel_is_exact_and_bound_as_data_not_rendered_sql() -> None:
    query = _query(CapabilityStream.BLOCK_CLOCK)

    assert PUMPFUN_INDEXER_V1_SENTINEL.block_hash == " " * 48
    assert PUMPFUN_INDEXER_V1_SENTINEL.validator == "MISSING" + " " * 41
    assert query.parameters["sentinel_epoch_seconds"] == 0
    assert query.parameters["sentinel_block_hash"] == " " * 48
    assert query.parameters["sentinel_validator"] == "MISSING" + " " * 41
    assert query.parameters["sentinel_rewards"] == 0
    assert query.parameters["sentinel_transaction_count"] == 0
    assert "MISSING" not in query.sql
    assert "is_nonproduced_sentinel" in query.columns


def test_launch_query_uses_final_and_keeps_mayhem_for_classification() -> None:
    query = _query(CapabilityStream.TOKEN_LAUNCH)
    normalized = _normalized(query.sql)

    assert "FROM `default`.`pumpfun_token_creation` FINAL" in normalized
    assert "WHERE quote_coin = {native_sol_quote:String}" in normalized
    assert "mayhem_mode =" not in normalized
    assert query.parameters["native_sol_quote"] == PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE
    assert "creation_user" in query.columns
    assert "mayhem_mode" in query.columns


def test_trade_query_filters_success_and_joins_eligible_decision_launches() -> None:
    query = _query(CapabilityStream.PUMP_CURVE_TRADE)
    normalized = _normalized(query.sql)

    assert "FROM `default`.`pumpfun_v2_swaps` AS s" in normalized
    assert "pumpfun_token_creation` FINAL" in normalized
    assert "decision_from_block_ordinal:UInt64" in normalized
    assert "decision_to_block_ordinal:UInt64" in normalized
    assert "s.failed = {successful_failed_flag:UInt8}" in normalized
    assert "mayhem_mode = {eligible_mayhem_mode:UInt8}" in normalized
    assert "GROUP BY s.signature, s.ix_idx" in normalized
    assert "count() AS source_row_count" in normalized
    assert "uniqExact(tuple(" in normalized
    assert "DISTINCT" not in normalized.upper()
    assert query.parameters["successful_failed_flag"] == 0
    assert query.parameters["eligible_mayhem_mode"] == 0
    assert query.parameters["wrapped_sol_quote"] == PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE
    assert "s.quote_coin = {wrapped_sol_quote:String}" in normalized
    assert query.parameters["decision_from_block_ordinal"] == 100
    assert query.parameters["decision_to_block_ordinal"] == 200
    assert query.columns[-2:] == ("source_row_count", "payload_variant_count")


def test_lifecycle_query_emits_completion_and_migration_candidates() -> None:
    query = _query(CapabilityStream.PUMP_CURVE_LIFECYCLE)
    normalized = _normalized(query.sql)

    assert "'COMPLETION_CANDIDATE' AS candidate_kind" in normalized
    assert "'MIGRATION_CANDIDATE' AS candidate_kind" in normalized
    assert "UNION ALL" in normalized
    assert "FROM `default`.`pfamm_migrations` AS m" in normalized
    assert "LEFT JOIN" in normalized
    assert "terminal_candidate_count" in normalized
    assert "CAST(NULL AS Nullable(Int64)) AS raw_instruction_index" in normalized
    assert query.parameters["terminal_virtual_token_reserves"] == (
        PUMPFUN_INDEXER_V1_TERMINAL_VIRTUAL_TOKEN_RESERVES
    )
    assert query.parameters["terminal_virtual_token_reserves"] == 279_900_000_000_000
    assert query.parameters["terminal_buy_direction"] == "buy"
    assert query.parameters["terminal_buy_instruction"] == "buy_v2"
    assert normalized.count("s.direction = {terminal_buy_direction:String}") == 1
    assert normalized.count("s.instruction_type = {terminal_buy_instruction:String}") == 1


def test_every_profile_query_is_single_read_only_bounded_statement() -> None:
    for stream in CapabilityStream:
        query = _query(stream)
        normalized = _normalized(query.sql).upper()
        assert normalized.startswith("SELECT ")
        assert "SELECT *" not in normalized
        assert " OFFSET " not in f" {normalized} "
        assert ";" not in query.sql
        assert "{from_block_ordinal:UInt64}" in query.sql
        assert "{to_block_ordinal:UInt64}" in query.sql
        assert query.profile_id == PUMPFUN_INDEXER_V1_PROFILE_ID
        assert query.template_id.startswith("pumpfun-indexer-v1-")
        assert len(query.fingerprint.hex) == 64


def test_query_and_template_identity_change_with_exact_operands() -> None:
    original = _query(CapabilityStream.PUMP_CURVE_TRADE)
    moved = PUMPFUN_INDEXER_V1_PROFILE.build_query(
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        database="default",
        block_range=_range(181, 260),
        decision_range=_range(100, 200),
        policy=ClickHouseQueryPolicy(max_block_span=1_000),
    )
    changed_constants = replace(PUMPFUN_INDEXER_V1_PROFILE, native_sol_quote="another-sol-marker")

    assert original.fingerprint != moved.fingerprint
    assert changed_constants.template_digest != PUMPFUN_INDEXER_V1_PROFILE.template_digest


def test_response_block_size_does_not_change_pumpfun_query_identity() -> None:
    operands = {
        "stream": CapabilityStream.PUMP_CURVE_TRADE,
        "database": "default",
        "block_range": _range(180, 260),
        "decision_range": _range(100, 200),
    }

    small_blocks = PUMPFUN_INDEXER_V1_PROFILE.build_query(
        **operands,
        policy=ClickHouseQueryPolicy(max_block_span=1_000, max_block_size=128),
    )
    larger_blocks = PUMPFUN_INDEXER_V1_PROFILE.build_query(
        **operands,
        policy=ClickHouseQueryPolicy(max_block_span=1_000, max_block_size=8_192),
    )

    assert small_blocks == larger_blocks


def test_query_rejects_unsafe_database_oversized_range_and_mixed_chain() -> None:
    with pytest.raises(ValueError, match="safe ClickHouse identifier"):
        PUMPFUN_INDEXER_V1_PROFILE.build_query(
            stream=CapabilityStream.BLOCK_CLOCK,
            database="default; DROP TABLE solana_blocks",
            block_range=_range(1, 2),
            decision_range=_range(1, 2),
            policy=ClickHouseQueryPolicy(max_block_span=10),
        )

    with pytest.raises(ValueError, match="hard span limit"):
        PUMPFUN_INDEXER_V1_PROFILE.build_query(
            stream=CapabilityStream.BLOCK_CLOCK,
            database="default",
            block_range=_range(1, 12),
            decision_range=_range(1, 2),
            policy=ClickHouseQueryPolicy(max_block_span=10),
        )

    # A syntactically valid alternate genesis must still fail the same-network query gate.
    other_network_range = replace(
        _range(1, 2),
        network_id=NetworkId("solana:11111111111111111111111111111112"),
    )
    # Query construction cannot combine decision and extraction ranges from two chains.
    with pytest.raises(ValueError, match="different chain identities"):
        PUMPFUN_INDEXER_V1_PROFILE.build_query(
            stream=CapabilityStream.BLOCK_CLOCK,
            database="default",
            block_range=_range(1, 2),
            # Only the network differs; the numeric range and hard limit stay compatible.
            decision_range=other_network_range,
            policy=ClickHouseQueryPolicy(max_block_span=10),
        )
