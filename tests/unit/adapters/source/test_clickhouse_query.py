# Declare this module's dependencies and contracts before execution.
from dataclasses import replace
from datetime import date

import pytest

from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    # Include click house query policy so the query dependency remains explicit.
    ClickHouseQueryPolicy,
    ProvenUtcDatePruning,
    UtcDateRange,
    build_scan_query,
    clickhouse_capability_mapping_digest,
    # Include validated identifier so the query dependency remains explicit.
    validated_identifier,
)
from backtest.application.models import (
    CapabilityDescriptor,
    CapabilityStream,
    # Include dataset shard so the models dependency remains explicit.
    DatasetShard,
    ExtractionRequest,
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
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange


# Define descriptor as one focused operation with an explicit boundary.
def _descriptor(*, proven_utc: bool = True) -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=CapabilityId("pumpfun.swaps.v1"),
        protocol="pumpfun",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # pumpfun input in descriptor.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("block_ordinal", "tx_idx", "signature", "block_date_utc", "amount"),
        mandatory_columns=("block_ordinal", "tx_idx", "signature"),
        fidelity=SourceFidelity(
            IdentityFidelity.CANDIDATE,
            # Pass ordering fidelity explicitly so SourceFidelity receives a reviewable
            # candidate and transaction exact input in descriptor.
            OrderingFidelity.TRANSACTION_EXACT,
            StateFidelity.AFTER_ONLY,
            FeesFidelity.TOTAL_ONLY,
            ChainFinality.UNKNOWN,
            IngestionCompleteness.UNKNOWN,
            # Pass source consistency explicitly so SourceFidelity receives a reviewable
            # candidate and transaction exact input in descriptor.
            SourceConsistency.BEST_EFFORT,
        ),
        total_key=("signature", "tx_idx"),
        keyset_key_is_proven=True,
        utc_pruning_column="block_date_utc" if proven_utc else None,
        # Pass utc pruning is proven explicitly so CapabilityDescriptor receives a
        # reviewable v1 and pumpfun input in descriptor.
        utc_pruning_is_proven=proven_utc,
    )


def _capability(*, with_utc: bool = True) -> ClickHouseCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    descriptor = _descriptor(proven_utc=with_utc)
    return ClickHouseCapability(
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass database explicitly so ClickHouseCapability receives a reviewable default
        # and pumpfun v2 swaps input in capability.
        database="default",
        table="pumpfun_v2_swaps",
        logical_to_physical={
            column: "slot" if column == "block_ordinal" else column for column in descriptor.columns
        },
        # Pass order by explicitly so ClickHouseCapability receives a reviewable default
        # and pumpfun v2 swaps input in capability.
        order_by=("block_ordinal", "signature", "tx_idx"),
        utc_pruning=(
            ProvenUtcDatePruning(
                "block_date_utc",
                lambda _: UtcDateRange(date(2026, 8, 30), date(2026, 9, 1)),
                # Complete ProvenUtcDatePruning only after its block date utc and utc date
                # range inputs are visible in capability.
            )
            if with_utc
            else None
        ),
    )


# Define request as one focused operation with an explicit boundary.
def _request(block_range: BlockRange | None = None) -> ExtractionRequest:
    # Execute the request workflow in explicit, reviewable steps.
    resolved_range = block_range or BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        100,
        200,
        # Complete BlockRange only after its solana mainnet network id and block32
        # transaction32 position schema id inputs are visible in request.
    )
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("sha256:" + "b" * 64),
        shard=DatasetShard(
            ordinal=0,
            # Include capability id in the completed request result.
            capability_id=CapabilityId("pumpfun.swaps.v1"),
            block_range=resolved_range,
            columns=(
                "block_ordinal",
                "tx_idx",
                # Pass signature explicitly so DatasetShard receives a reviewable v1 and
                # block ordinal input in request.
                "signature",
                "block_date_utc",
                "amount",
            ),
        ),
        decision_range=resolved_range,
        # Include query limits in the completed request result.
        query_limits=QueryLimits(
            max_execution_seconds=600,
            max_memory_bytes=8 * 1024**3,
            max_result_rows=None,
        ),
        # Complete ExtractionRequest only after its sha256: and b inputs are visible in
        # request.
    )


@pytest.mark.parametrize(
    "identifier",
    (
        "table; DROP TABLE x",
        # Pass table explicitly so parametrize receives a reviewable identifier and table;
        # drop table x input in test identifier validation rejects sql syntax.
        "db.table",
        "with space",
        "`quoted`",
        "name--comment",
        "name/*comment*/",
        # Keep parametrize, identifier and mark visible while completing parametrize
        # within test identifier validation rejects sql syntax.
        "",
    ),
)
def test_identifier_validation_rejects_sql_syntax(identifier: str) -> None:
    # Execute the test identifier validation rejects sql syntax workflow in explicit,
    # reviewable steps.
    with pytest.raises(ValueError, match="safe ClickHouse identifier"):
        validated_identifier(identifier)


def test_scan_query_has_only_explicit_projection_and_bound_parameters() -> None:
    # Execute the test scan query has only explicit projection and bound parameters
    # workflow in explicit, reviewable steps.
    bounded = build_scan_query(
        _capability(),
        _request(),
        ClickHouseQueryPolicy(max_block_span=1000),
    )

    # Assemble normalized once so the test scan query has only explicit projection and
    # bound parameters workflow shares one value.
    normalized = " ".join(bounded.sql.split())
    assert "SELECT *" not in normalized.upper()
    assert " OFFSET " not in f" {normalized.upper()} "
    assert "`amount` AS `amount`" in normalized
    assert "`slot` AS `block_ordinal`" in normalized
    # Verify the normalized relationship before this scenario is accepted.
    assert "`slot` >= {from_block_ordinal:UInt64}" in normalized
    assert "`slot` < {to_block_ordinal:UInt64}" in normalized
    assert "`block_date_utc` >= {from_date_utc:Date}" in normalized
    assert "`block_date_utc` < {to_date_utc:Date}" in normalized
    assert "ORDER BY `slot`, `signature`, `tx_idx`" in normalized
    # Verify the parameters, bounded and from block ordinal relationship before this
    # scenario is accepted.
    assert bounded.parameters == {
        "from_block_ordinal": 100,
        "to_block_ordinal": 200,
        "from_date_utc": date(2026, 8, 30),
        "to_date_utc": date(2026, 9, 1),
        # Verify the parameters, bounded and from block ordinal relationship before this
        # scenario is accepted.
    }
    assert bounded.columns == (
        "amount",
        "block_date_utc",
        "block_ordinal",
        # Keep the signature expectation tied to columns, bounded and amount in this
        # scenario.
        "signature",
        "tx_idx",
    )
    assert bounded.block_ordinal_column_index == 2


def test_utc_predicate_is_absent_without_explicit_proof_object() -> None:
    # Execute the test utc predicate is absent without explicit proof object workflow in
    # explicit, reviewable steps.
    bounded = build_scan_query(
        _capability(with_utc=False),
        _request(),
        ClickHouseQueryPolicy(max_block_span=1000),
    )

    # Verify 'from_date_utc' not in bounded.sql before this scenario is accepted.
    assert "from_date_utc" not in bounded.sql
    assert set(bounded.parameters) == {"from_block_ordinal", "to_block_ordinal"}


def test_utc_pruning_cannot_be_enabled_for_unproven_capability() -> None:
    # Execute the test utc pruning cannot be enabled for unproven capability workflow in
    # explicit, reviewable steps.
    descriptor = _descriptor(proven_utc=False)

    with pytest.raises(ValueError, match="proof is absent"):
        # Keep raises, value error and pytest active only for the bounded test utc pruning
        # cannot be enabled for unproven capability operation.
        ClickHouseCapability(
            descriptor=descriptor,
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            database="default",
            # Pass table explicitly so ClickHouseCapability receives a reviewable default
            # and swaps input in test utc pruning cannot be enabled for unproven
            # capability.
            table="swaps",
            logical_to_physical={column: column for column in descriptor.columns},
            utc_pruning=ProvenUtcDatePruning(
                "block_date_utc",
                lambda _: UtcDateRange(date(2026, 8, 30), date(2026, 9, 1)),
                # Complete ProvenUtcDatePruning only after its block date utc and utc date
                # range inputs are visible in test utc pruning cannot be enabled for unproven
                # capability.
            ),
        )


def test_query_rejects_oversized_shard_before_contacting_source() -> None:
    # Execute the test query rejects oversized shard before contacting source workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="hard span limit"):
        # Keep raises, value error and pytest active only for the bounded test query
        # rejects oversized shard before contacting source operation.
        build_scan_query(
            _capability(),
            _request(
                BlockRange(
                    SOLANA_MAINNET_NETWORK_ID,
                    # Pass block32 transaction32 position schema id explicitly so
                    # BlockRange receives a reviewable solana mainnet network id and
                    # block32 transaction32 position schema id input in test query rejects
                    # oversized shard before contacting source.
                    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                    0,
                    101,
                )
            ),
            # Pass max block span explicitly to build_scan_query for capability and
            # request.
            ClickHouseQueryPolicy(max_block_span=100),
        )


def test_request_limits_can_only_lower_adapter_hard_limits() -> None:
    # Execute the test request limits can only lower adapter hard limits workflow in
    # explicit, reviewable steps.
    policy = ClickHouseQueryPolicy(
        max_execution_seconds=30,
        max_memory_bytes=1024,
        max_result_rows=500,
        max_block_size=128,
    )
    # Assemble request once so the test request limits can only lower adapter hard limits
    # workflow shares one value.
    request = _request()
    settings = policy.scan_settings(request.query_limits)

    assert settings["readonly"] == 1
    assert settings["max_execution_time"] == 30
    assert settings["max_memory_usage"] == 1024
    # Verify settings['max_result_rows'] == 500 before this scenario is accepted.
    assert settings["max_result_rows"] == 500
    assert settings["result_overflow_mode"] == "throw"
    assert settings["read_overflow_mode"] == "throw"
    assert settings["max_block_size"] == 128
    assert (
        policy.evidence_settings(replace(request.query_limits, max_result_rows=10_000_000))[
            "max_block_size"
        ]
        == 128
    )
    assert policy.metadata_settings()["max_block_size"] == 128


@pytest.mark.parametrize("value", (0, -1, False, 1.5))
def test_response_block_row_ceiling_must_be_a_positive_integer(value: object) -> None:
    expected = TypeError if isinstance(value, bool | float) else ValueError

    with pytest.raises(expected, match="max_block_size"):
        ClickHouseQueryPolicy(max_block_size=value)


def test_response_block_size_does_not_change_logical_query_identity() -> None:
    small_blocks = build_scan_query(
        _capability(),
        _request(),
        ClickHouseQueryPolicy(max_block_span=1_000, max_block_size=128),
    )
    larger_blocks = build_scan_query(
        _capability(),
        _request(),
        ClickHouseQueryPolicy(max_block_span=1_000, max_block_size=8_192),
    )

    assert small_blocks == larger_blocks


def test_mapping_digest_pins_exact_logical_to_physical_columns() -> None:
    # Execute the test mapping digest pins exact logical to physical columns workflow in
    # explicit, reviewable steps.
    original = _capability(with_utc=False)
    changed_mapping = dict(original.logical_to_physical)
    changed_mapping["amount"] = "amount_v2"
    changed = ClickHouseCapability(
        descriptor=original.descriptor,
        # Pass network id explicitly so ClickHouseCapability receives a reviewable
        # descriptor and network id input in test mapping digest pins exact logical to
        # physical columns.
        network_id=original.network_id,
        position_schema_id=original.position_schema_id,
        database=original.database,
        table=original.table,
        logical_to_physical=changed_mapping,
        # Pass order by explicitly so ClickHouseCapability receives a reviewable
        # descriptor and network id input in test mapping digest pins exact logical to
        # physical columns.
        order_by=original.order_by,
    )

    assert clickhouse_capability_mapping_digest((original,)) != (
        clickhouse_capability_mapping_digest((changed,))
    )


# Define test projection must include mandatory columns as one focused operation with an
# explicit boundary.
def test_projection_must_include_mandatory_columns() -> None:
    # Execute the test projection must include mandatory columns workflow in explicit,
    # reviewable steps.
    request = _request()
    incomplete = replace(request.shard, columns=("block_ordinal", "amount"))

    with pytest.raises(ValueError, match="mandatory columns"):
        # Keep raises, value error and pytest active only for the bounded test projection
        # must include mandatory columns operation.
        build_scan_query(
            _capability(),
            replace(request, shard=incomplete),
            ClickHouseQueryPolicy(max_block_span=1000),
        )
