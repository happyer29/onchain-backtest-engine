"""Fixed, bounded query profile for the audited Pump.fun ClickHouse indexer.

This module owns physical SQL shape only.  It deliberately does not derive
Pump curve semantics or promote source fidelity: those operations require the
cross-stream protocol normalizer and bounded evidence evaluator.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final

from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
    quoted_identifier,
)
from backtest.application.models import CAPABILITY_PROOF_FIELDS, CapabilityStream, EvidenceStatus
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    StateFidelity,
)
from backtest.domain.identifiers import ContentDigest
from backtest.domain.time import BlockRange

PUMPFUN_INDEXER_V1_PROFILE_ID: Final = "pumpfun-indexer-v1"
PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION: Final = "pumpfun-indexer-v1-raw-v1"
PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE: Final = "11111111111111111111111111111111"
PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE: Final = "So11111111111111111111111111111111111111112"
PUMPFUN_INDEXER_V1_TERMINAL_VIRTUAL_TOKEN_RESERVES: Final = 279_900_000_000_000

_PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_TEMPLATE_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_QUERY_FINGERPRINT_DOMAIN = b"backtest.clickhouse.pumpfun-indexer-v1.query.v1\x00"
_TEMPLATE_DIGEST_DOMAIN = b"backtest.clickhouse.pumpfun-indexer-v1.templates.v1\x00"


@dataclass(frozen=True, slots=True)
class PumpfunIndexerV1Sentinel:
    """Exact decoded source payload for a known non-produced Solana slot."""

    policy_id: str
    block_time_epoch_seconds: int
    block_hash: str
    validator: str
    rewards: int
    transaction_count: int

    def __post_init__(self) -> None:
        if _PROFILE_ID_RE.fullmatch(self.policy_id) is None:
            raise ValueError("sentinel policy_id is invalid")
        for field_name in ("block_time_epoch_seconds", "rewards", "transaction_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if not isinstance(self.block_hash, str) or not isinstance(self.validator, str):
            raise TypeError("sentinel FixedString payloads must be strings")
        if len(self.block_hash) != 48 or len(self.validator) != 48:
            raise ValueError("sentinel FixedString payloads must preserve all 48 decoded bytes")


PUMPFUN_INDEXER_V1_SENTINEL: Final = PumpfunIndexerV1Sentinel(
    policy_id="solana-skipped-slot-epoch-zero-pinned-fingerprint-v1",
    block_time_epoch_seconds=0,
    block_hash=" " * 48,
    validator="MISSING" + " " * 41,
    rewards=0,
    transaction_count=0,
)


@dataclass(frozen=True, slots=True)
class PumpfunIndexerV1Query:
    """One fixed query and its secret-free, identity-bearing raw row contract."""

    profile_id: str
    template_id: str
    sql: str
    parameters: Mapping[str, Any]
    columns: tuple[str, ...]
    block_ordinal_column_index: int
    fingerprint: ContentDigest

    def __post_init__(self) -> None:
        if self.profile_id != PUMPFUN_INDEXER_V1_PROFILE_ID:
            raise ValueError("query uses an unsupported source profile")
        if _TEMPLATE_ID_RE.fullmatch(self.template_id) is None:
            raise ValueError("query template_id is invalid")
        _assert_safe_query(self.sql)
        if not self.columns or len(self.columns) != len(set(self.columns)):
            raise ValueError("profile query columns must be non-empty and unique")
        if not 0 <= self.block_ordinal_column_index < len(self.columns):
            raise ValueError("block ordinal column index is outside the raw row contract")
        if self.columns[self.block_ordinal_column_index] != "block_ordinal":
            raise ValueError("block ordinal column index does not identify block_ordinal")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


_BLOCK_COLUMNS: Final = (
    "block_ordinal",
    "block_time",
    "block_hash",
    "validator",
    "rewards",
    "transaction_count",
    "source_row_count",
    "payload_variant_count",
    "is_nonproduced_sentinel",
)

_LAUNCH_COLUMNS: Final = (
    "block_ordinal",
    "block_time",
    "transaction_index",
    "raw_instruction_index",
    "signature",
    "mint",
    "creator",
    "creation_user",
    "curve_address",
    "quote_asset",
    "mayhem_mode",
    "token_program",
    "cashback_enabled",
    "direct_pump_invocation",
    "pump_program_index",
    "parent_program",
    "source_version",
    "bundle_size",
    "bundle_structure",
    "bundled_buys",
    "bundled_buys_count",
    "dev_balance",
)

_TRADE_COLUMNS: Final = (
    "block_ordinal",
    "block_time",
    "transaction_index",
    "raw_instruction_index",
    "signature",
    "mint",
    "quote_asset",
    "direction",
    "instruction_type",
    "base_amount_atomic",
    "quote_amount_atomic",
    "virtual_token_reserves_after_atomic",
    "virtual_sol_reserves_after_lamports",
    "failed",
    "signing_wallet",
    "fee_payer",
    "parent_program",
    "provided_gas_fee_lamports",
    "provided_gas_limit",
    "network_fee_lamports",
    "consumed_gas",
    "pump_program_account_index",
    "cu_price_instruction_index",
    "cu_limit_instruction_index",
    "tip_instruction_index",
    "num_signatures",
    "transaction_version",
    "blockhash_prefix",
    "creation_block_ordinal",
    "creation_transaction_index",
    "creation_raw_instruction_index",
    "creator",
    "creation_user",
    "curve_address",
    "token_program",
    "cashback_enabled",
    "mayhem_mode",
    "source_row_count",
    "payload_variant_count",
)

_LIFECYCLE_COLUMNS: Final = (
    "candidate_kind",
    "block_ordinal",
    "block_time",
    "transaction_index",
    "raw_instruction_index",
    "signature",
    "mint",
    "curve_address",
    "token_program",
    "cashback_enabled",
    "mayhem_mode",
    "creation_block_ordinal",
    "creation_transaction_index",
    "creation_raw_instruction_index",
    "terminal_raw_instruction_index",
    "terminal_virtual_token_reserves_after_atomic",
    "terminal_virtual_sol_reserves_after_lamports",
    "terminal_candidate_count",
    "terminal_source_row_count",
    "terminal_payload_variant_count",
    "migration_user",
    "migration_mint_amount_atomic",
    "migration_sol_amount_lamports",
    "pool_migration_fee_lamports",
    "migration_pool",
    "migration_timestamp",
    "migration_parent_program",
    "source_row_count",
    "payload_variant_count",
)

_OUTPUT_COLUMNS: Final[Mapping[CapabilityStream, tuple[str, ...]]] = MappingProxyType(
    {
        CapabilityStream.BLOCK_CLOCK: _BLOCK_COLUMNS,
        CapabilityStream.TOKEN_LAUNCH: _LAUNCH_COLUMNS,
        CapabilityStream.PUMP_CURVE_TRADE: _TRADE_COLUMNS,
        CapabilityStream.PUMP_CURVE_LIFECYCLE: _LIFECYCLE_COLUMNS,
    }
)

_TEMPLATE_IDS: Final[Mapping[CapabilityStream, str]] = MappingProxyType(
    {
        CapabilityStream.BLOCK_CLOCK: "pumpfun-indexer-v1-block-clock-v1",
        CapabilityStream.TOKEN_LAUNCH: "pumpfun-indexer-v1-token-launch-v1",
        CapabilityStream.PUMP_CURVE_TRADE: "pumpfun-indexer-v1-curve-trade-v1",
        CapabilityStream.PUMP_CURVE_LIFECYCLE: "pumpfun-indexer-v1-curve-lifecycle-v1",
    }
)

_TABLES: Final[Mapping[CapabilityStream, str]] = MappingProxyType(
    {
        CapabilityStream.BLOCK_CLOCK: "solana_blocks",
        CapabilityStream.TOKEN_LAUNCH: "pumpfun_token_creation",
        CapabilityStream.PUMP_CURVE_TRADE: "pumpfun_v2_swaps",
        CapabilityStream.PUMP_CURVE_LIFECYCLE: "pfamm_migrations",
    }
)

_PHYSICAL_MAPPINGS: Final[Mapping[CapabilityStream, Mapping[str, str]]] = MappingProxyType(
    {
        CapabilityStream.BLOCK_CLOCK: MappingProxyType(
            {
                "block_ordinal": "slot",
                "block_time": "block_time",
                "block_hash": "hash",
                "validator": "validator",
                "rewards": "rewards",
                "transaction_count": "amount_of_transactions",
            }
        ),
        CapabilityStream.TOKEN_LAUNCH: MappingProxyType(
            {
                "block_ordinal": "slot",
                "block_time": "block_time",
                "transaction_index": "tx_idx",
                "raw_instruction_index": "creation_ix_index",
                "signature": "signature",
                "mint": "mint",
                "creator": "creator",
                "creation_user": "fee_payer",
                "curve_address": "curve_address",
                "quote_asset": "quote_coin",
                "mayhem_mode": "mayhem_mode",
                "token_program": "token_program",
                "cashback_enabled": "is_cashback_enabled",
                "direct_pump_invocation": "direct_pf_invocation",
                "pump_program_index": "pf_program_index",
                "parent_program": "parent_program",
                "source_version": "version",
                "bundle_size": "bundle_size",
                "bundle_structure": "bundle_structure",
                "bundled_buys": "bundled_buys",
                "bundled_buys_count": "bundled_buys_count",
                "dev_balance": "dev_balance",
            }
        ),
        CapabilityStream.PUMP_CURVE_TRADE: MappingProxyType(
            {
                "block_ordinal": "slot",
                "block_time": "block_time",
                "transaction_index": "tx_idx",
                "raw_instruction_index": "ix_idx",
                "signature": "signature",
                "mint": "base_coin",
                "quote_asset": "quote_coin",
                "direction": "direction",
                "instruction_type": "instruction_type",
                "base_amount_atomic": "base_coin_amount",
                "quote_amount_atomic": "quote_coin_amount",
                "virtual_token_reserves_after_atomic": "virtual_token_balance_after",
                "virtual_sol_reserves_after_lamports": "virtual_sol_balance_after",
                "failed": "failed",
                "signing_wallet": "signing_wallet",
                "fee_payer": "fee_payer",
                "parent_program": "parent_program",
                "provided_gas_fee_lamports": "provided_gas_fee",
                "provided_gas_limit": "provided_gas_limit",
                "network_fee_lamports": "fee",
                "consumed_gas": "consumed_gas",
                "pump_program_account_index": "pf_program_account_index",
                "cu_price_instruction_index": "cu_price_ix_index",
                "cu_limit_instruction_index": "cu_limit_ix_index",
                "tip_instruction_index": "tip_index",
                "num_signatures": "num_signatures",
                "transaction_version": "transaction_version",
                "blockhash_prefix": "blockhash_prefix",
            }
        ),
        CapabilityStream.PUMP_CURVE_LIFECYCLE: MappingProxyType(
            {
                "block_ordinal": "slot",
                "block_time": "block_time",
                "transaction_index": "tx_idx",
                "signature": "signature",
                "mint": "mint",
                "curve_address": "bonding_curve",
                "migration_user": "user",
                "migration_mint_amount_atomic": "mint_amount",
                "migration_sol_amount_lamports": "sol_amount",
                "pool_migration_fee_lamports": "pool_migration_fee",
                "migration_pool": "pool",
                "migration_timestamp": "timestamp",
                "migration_parent_program": "parent_program",
            }
        ),
    }
)


@dataclass(frozen=True, slots=True)
class PumpfunIndexerV1Profile:
    """Composition-owned source profile; no SQL is loaded from configuration."""

    profile_id: str = PUMPFUN_INDEXER_V1_PROFILE_ID
    capability_schema_version: str = PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION
    sentinel: PumpfunIndexerV1Sentinel = PUMPFUN_INDEXER_V1_SENTINEL
    native_sol_quote: str = PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE
    wrapped_sol_quote: str = PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE
    terminal_virtual_token_reserves: int = PUMPFUN_INDEXER_V1_TERMINAL_VIRTUAL_TOKEN_RESERVES

    def __post_init__(self) -> None:
        if self.profile_id != PUMPFUN_INDEXER_V1_PROFILE_ID:
            raise ValueError("unsupported Pump.fun indexer profile ID")
        if self.capability_schema_version != PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION:
            raise ValueError("unsupported Pump.fun capability schema version")
        if not isinstance(self.sentinel, PumpfunIndexerV1Sentinel):
            raise TypeError("sentinel must be a PumpfunIndexerV1Sentinel")
        if not isinstance(self.native_sol_quote, str) or not self.native_sol_quote:
            raise ValueError("native SOL quote marker must be a non-empty string")
        if not isinstance(self.wrapped_sol_quote, str) or not self.wrapped_sol_quote:
            raise ValueError("wrapped SOL quote marker must be a non-empty string")
        if self.wrapped_sol_quote == self.native_sol_quote:
            raise ValueError("native and wrapped SOL source markers must be distinct")
        if (
            isinstance(self.terminal_virtual_token_reserves, bool)
            or not isinstance(self.terminal_virtual_token_reserves, int)
            or self.terminal_virtual_token_reserves <= 0
        ):
            raise ValueError("terminal virtual-token reserve must be a positive integer")

    @property
    def template_digest(self) -> ContentDigest:
        document = {
            "capability_schema_version": self.capability_schema_version,
            "native_sol_quote": self.native_sol_quote,
            "wrapped_sol_quote": self.wrapped_sol_quote,
            "output_columns": {
                stream.value: list(_OUTPUT_COLUMNS[stream]) for stream in CapabilityStream
            },
            "profile_id": self.profile_id,
            "sentinel": {
                "block_hash": self.sentinel.block_hash,
                "block_time_epoch_seconds": self.sentinel.block_time_epoch_seconds,
                "policy_id": self.sentinel.policy_id,
                "rewards": self.sentinel.rewards,
                "transaction_count": self.sentinel.transaction_count,
                "validator": self.sentinel.validator,
            },
            "tables": {stream.value: _TABLES[stream] for stream in CapabilityStream},
            "template_ids": {stream.value: _TEMPLATE_IDS[stream] for stream in CapabilityStream},
            "terminal_virtual_token_reserves": self.terminal_virtual_token_reserves,
        }
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return ContentDigest(sha256(_TEMPLATE_DIGEST_DOMAIN + encoded).hexdigest())

    def output_columns(self, stream: CapabilityStream) -> tuple[str, ...]:
        try:
            return _OUTPUT_COLUMNS[stream]
        except KeyError:
            raise ValueError("unsupported Pump.fun capability stream") from None

    def build_query(
        self,
        *,
        stream: CapabilityStream,
        database: str,
        block_range: BlockRange,
        decision_range: BlockRange,
        policy: ClickHouseQueryPolicy,
    ) -> PumpfunIndexerV1Query:
        _validate_ranges(block_range, decision_range, policy)
        qualified = f"{quoted_identifier(database)}.{quoted_identifier(_TABLES[stream])}"
        launch_table = (
            f"{quoted_identifier(database)}."
            f"{quoted_identifier(_TABLES[CapabilityStream.TOKEN_LAUNCH])}"
        )
        trade_table = (
            f"{quoted_identifier(database)}."
            f"{quoted_identifier(_TABLES[CapabilityStream.PUMP_CURVE_TRADE])}"
        )
        if stream is CapabilityStream.BLOCK_CLOCK:
            sql, parameters = _block_clock_sql(qualified, block_range, self)
        elif stream is CapabilityStream.TOKEN_LAUNCH:
            sql, parameters = _token_launch_sql(qualified, block_range, self)
        elif stream is CapabilityStream.PUMP_CURVE_TRADE:
            sql, parameters = _curve_trade_sql(
                qualified,
                launch_table,
                block_range,
                decision_range,
                self,
            )
        elif stream is CapabilityStream.PUMP_CURVE_LIFECYCLE:
            sql, parameters = _curve_lifecycle_sql(
                qualified,
                trade_table,
                launch_table,
                block_range,
                decision_range,
                self,
            )
        else:
            raise ValueError("unsupported Pump.fun capability stream")
        _assert_safe_query(sql)
        columns = self.output_columns(stream)
        template_id = _TEMPLATE_IDS[stream]
        return PumpfunIndexerV1Query(
            profile_id=self.profile_id,
            template_id=template_id,
            sql=sql,
            parameters=parameters,
            columns=columns,
            block_ordinal_column_index=columns.index("block_ordinal"),
            fingerprint=_query_fingerprint(
                profile_id=self.profile_id,
                template_id=template_id,
                template_digest=self.template_digest,
                sql=sql,
                parameters=parameters,
            ),
        )

    def validate_capabilities(self, capabilities: Sequence[ClickHouseCapability]) -> None:
        if len(capabilities) != len(CapabilityStream):
            raise ValueError("pumpfun-indexer-v1 requires exactly four capabilities")
        by_stream = {item.descriptor.stream: item for item in capabilities}
        if set(by_stream) != set(CapabilityStream):
            raise ValueError("pumpfun-indexer-v1 requires one capability per stream")
        databases = {item.database for item in capabilities}
        if len(databases) != 1:
            raise ValueError("pumpfun-indexer-v1 capabilities must use one database")
        for stream in CapabilityStream:
            capability = by_stream[stream]
            descriptor = capability.descriptor
            expected_protocol = "solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun"
            if descriptor.schema_version != self.capability_schema_version:
                raise ValueError("pumpfun-indexer-v1 capability schema token mismatch")
            if descriptor.protocol != expected_protocol:
                raise ValueError("pumpfun-indexer-v1 capability protocol mismatch")
            if capability.table != _TABLES[stream]:
                raise ValueError("pumpfun-indexer-v1 physical table mismatch")
            if dict(capability.logical_to_physical) != dict(_PHYSICAL_MAPPINGS[stream]):
                raise ValueError("pumpfun-indexer-v1 physical column mapping mismatch")
            if capability.order_by or capability.utc_pruning is not None:
                raise ValueError("pumpfun-indexer-v1 owns ordering and pruning")
            if descriptor.keyset_key_is_proven:
                raise ValueError("pumpfun-indexer-v1 does not accept static keyset proof")
            if any(
                getattr(descriptor.proofs, name) is not EvidenceStatus.UNKNOWN
                for name in CAPABILITY_PROOF_FIELDS
            ):
                raise ValueError("pumpfun-indexer-v1 static proofs must remain UNKNOWN")
            fidelity = descriptor.fidelity
            if (
                fidelity.identity is not IdentityFidelity.UNKNOWN
                or fidelity.ordering is not OrderingFidelity.UNKNOWN
                or fidelity.state is not StateFidelity.NONE
                or fidelity.fees is not FeesFidelity.UNKNOWN
                or fidelity.chain_finality is not ChainFinality.UNKNOWN
                or fidelity.completeness is not IngestionCompleteness.UNKNOWN
                or fidelity.consistency is not SourceConsistency.UNKNOWN
            ):
                raise ValueError("pumpfun-indexer-v1 static fidelity must remain unpromoted")


PUMPFUN_INDEXER_V1_PROFILE: Final = PumpfunIndexerV1Profile()


def build_pumpfun_indexer_v1_query(
    *,
    stream: CapabilityStream,
    database: str,
    block_range: BlockRange,
    decision_range: BlockRange,
    policy: ClickHouseQueryPolicy,
) -> PumpfunIndexerV1Query:
    """Build one fixed raw query through the installed immutable profile."""

    return PUMPFUN_INDEXER_V1_PROFILE.build_query(
        stream=stream,
        database=database,
        block_range=block_range,
        decision_range=decision_range,
        policy=policy,
    )


def pumpfun_indexer_v1_query_template_digest() -> ContentDigest:
    """Return the profile/query/output-contract digest used by source identity."""

    return PUMPFUN_INDEXER_V1_PROFILE.template_digest


def registered_pumpfun_indexer_v1_profile(
    capabilities: Sequence[ClickHouseCapability],
) -> PumpfunIndexerV1Profile | None:
    """Select the profile only from its dedicated schema token and exact mapping."""

    versions = {item.descriptor.schema_version for item in capabilities}
    if PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION not in versions:
        return None
    if versions != {PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION}:
        raise ValueError("pumpfun-indexer-v1 cannot be mixed with another query profile")
    PUMPFUN_INDEXER_V1_PROFILE.validate_capabilities(capabilities)
    return PUMPFUN_INDEXER_V1_PROFILE


def pumpfun_indexer_v1_physical_mapping(
    stream: CapabilityStream,
) -> Mapping[str, str]:
    """Return the immutable direct-column contract used to select the profile."""

    try:
        return _PHYSICAL_MAPPINGS[stream]
    except KeyError:
        raise ValueError("unsupported Pump.fun capability stream") from None


def _validate_ranges(
    block_range: BlockRange,
    decision_range: BlockRange,
    policy: ClickHouseQueryPolicy,
) -> None:
    if not isinstance(block_range, BlockRange) or not isinstance(decision_range, BlockRange):
        raise TypeError("profile query ranges must be BlockRange values")
    if block_range.span > policy.max_block_span:
        raise ValueError("requested block shard exceeds Pump.fun profile hard span limit")
    if decision_range.span > policy.max_block_span:
        raise ValueError("decision range exceeds Pump.fun profile hard span limit")
    if (
        block_range.network_id != decision_range.network_id
        or block_range.position_schema_id != decision_range.position_schema_id
    ):
        raise ValueError("profile block and decision ranges use different chain identities")


def _common_parameters(block_range: BlockRange) -> dict[str, Any]:
    return {
        "from_block_ordinal": block_range.from_block_ordinal,
        "to_block_ordinal": block_range.to_block_ordinal,
    }


def _decision_parameters(decision_range: BlockRange) -> dict[str, Any]:
    return {
        "decision_from_block_ordinal": decision_range.from_block_ordinal,
        "decision_to_block_ordinal": decision_range.to_block_ordinal,
    }


def _block_clock_sql(
    table: str,
    block_range: BlockRange,
    profile: PumpfunIndexerV1Profile,
) -> tuple[str, Mapping[str, Any]]:
    # Qualify every physical input.  ClickHouse otherwise resolves the earlier
    # ``block_time`` output alias inside a later aggregate expression and treats
    # ``min(block_time)`` as a nested aggregate.
    variant = (
        "uniqExact(tuple(b.block_time, b.hash, b.validator, b.rewards, b.amount_of_transactions))"
    )
    exact_sentinel = " AND ".join(
        (
            "min(b.block_time) = toDateTime({sentinel_epoch_seconds:UInt32}, 'UTC')",
            "min(b.hash) = {sentinel_block_hash:String}",
            "min(b.validator) = {sentinel_validator:String}",
            "min(b.rewards) = {sentinel_rewards:UInt64}",
            "min(b.amount_of_transactions) = {sentinel_transaction_count:UInt64}",
        )
    )
    sql = f"""SELECT
    toUInt64(b.slot) AS block_ordinal,
    toUInt64(toUnixTimestamp(min(b.block_time))) AS block_time,
    min(b.hash) AS block_hash,
    min(b.validator) AS validator,
    min(b.rewards) AS rewards,
    min(b.amount_of_transactions) AS transaction_count,
    count() AS source_row_count,
    {variant} AS payload_variant_count,
    if(({variant}) = 1 AND {exact_sentinel}, toUInt8(1), toUInt8(0))
        AS is_nonproduced_sentinel
FROM {table} AS b
PREWHERE b.slot >= {{from_block_ordinal:UInt64}}
    AND b.slot < {{to_block_ordinal:UInt64}}
GROUP BY b.slot
ORDER BY b.slot"""
    parameters = _common_parameters(block_range)
    parameters.update(
        {
            "sentinel_epoch_seconds": profile.sentinel.block_time_epoch_seconds,
            "sentinel_block_hash": profile.sentinel.block_hash,
            "sentinel_validator": profile.sentinel.validator,
            "sentinel_rewards": profile.sentinel.rewards,
            "sentinel_transaction_count": profile.sentinel.transaction_count,
        }
    )
    return sql, parameters


def _launch_projection(*, alias: str = "") -> tuple[tuple[str, str], ...]:
    prefix = f"{alias}." if alias else ""
    return (
        ("block_ordinal", f"toUInt64({prefix}slot)"),
        ("block_time", f"toUInt64(toUnixTimestamp({prefix}block_time))"),
        ("transaction_index", f"toUInt64({prefix}tx_idx)"),
        ("raw_instruction_index", f"toInt64({prefix}creation_ix_index)"),
        ("signature", f"{prefix}signature"),
        # The indexer stores several address-like values in FixedString columns
        # (and stores the token-program String with explicit NUL padding).  Cut
        # only the trailing zero representation before joins and canonical IDs.
        ("mint", f"toStringCutToZero({prefix}mint)"),
        ("creator", f"toStringCutToZero({prefix}creator)"),
        ("creation_user", f"toStringCutToZero({prefix}fee_payer)"),
        ("curve_address", f"toStringCutToZero({prefix}curve_address)"),
        ("quote_asset", f"{prefix}quote_coin"),
        ("mayhem_mode", f"{prefix}mayhem_mode"),
        ("token_program", f"toStringCutToZero({prefix}token_program)"),
        ("cashback_enabled", f"{prefix}is_cashback_enabled"),
        ("direct_pump_invocation", f"{prefix}direct_pf_invocation"),
        ("pump_program_index", f"{prefix}pf_program_index"),
        ("parent_program", f"{prefix}parent_program"),
        ("source_version", f"{prefix}version"),
        ("bundle_size", f"{prefix}bundle_size"),
        ("bundle_structure", f"{prefix}bundle_structure"),
        ("bundled_buys", f"{prefix}bundled_buys"),
        ("bundled_buys_count", f"{prefix}bundled_buys_count"),
        ("dev_balance", f"{prefix}dev_balance"),
    )


def _token_launch_sql(
    table: str,
    block_range: BlockRange,
    profile: PumpfunIndexerV1Profile,
) -> tuple[str, Mapping[str, Any]]:
    projection = ",\n    ".join(
        f"{expression} AS {quoted_identifier(name)}" for name, expression in _launch_projection()
    )
    sql = f"""SELECT
    {projection}
FROM {table} FINAL
PREWHERE slot >= {{from_block_ordinal:UInt64}}
    AND slot < {{to_block_ordinal:UInt64}}
WHERE quote_coin = {{native_sol_quote:String}}
ORDER BY slot, tx_idx, creation_ix_index, signature"""
    parameters = _common_parameters(block_range)
    parameters["native_sol_quote"] = profile.native_sol_quote
    return sql, parameters


def _eligible_launch_sql(table: str) -> str:
    projection = ",\n        ".join(
        f"{expression} AS {quoted_identifier(name)}"
        for name, expression in _launch_projection()
        if name
        in {
            "block_ordinal",
            "transaction_index",
            "raw_instruction_index",
            "mint",
            "creator",
            "creation_user",
            "curve_address",
            "quote_asset",
            "mayhem_mode",
            "token_program",
            "cashback_enabled",
        }
    )
    return f"""SELECT
        {projection}
    FROM {table} FINAL
    PREWHERE slot >= {{decision_from_block_ordinal:UInt64}}
        AND slot < {{decision_to_block_ordinal:UInt64}}
    WHERE quote_coin = {{native_sol_quote:String}}
        AND mayhem_mode = {{eligible_mayhem_mode:UInt8}}"""


def _trade_source_projection() -> tuple[tuple[str, str], ...]:
    return (
        ("block_ordinal", "toUInt64(s.slot)"),
        ("block_time", "toUInt64(toUnixTimestamp(s.block_time))"),
        ("transaction_index", "toUInt64(s.tx_idx)"),
        ("raw_instruction_index", "toInt64(s.ix_idx)"),
        ("signature", "s.signature"),
        ("mint", "s.base_coin"),
        ("quote_asset", "s.quote_coin"),
        ("direction", "s.direction"),
        ("instruction_type", "s.instruction_type"),
        ("base_amount_atomic", "s.base_coin_amount"),
        ("quote_amount_atomic", "s.quote_coin_amount"),
        ("virtual_token_reserves_after_atomic", "s.virtual_token_balance_after"),
        ("virtual_sol_reserves_after_lamports", "s.virtual_sol_balance_after"),
        ("failed", "s.failed"),
        ("signing_wallet", "s.signing_wallet"),
        ("fee_payer", "s.fee_payer"),
        ("parent_program", "s.parent_program"),
        ("provided_gas_fee_lamports", "s.provided_gas_fee"),
        ("provided_gas_limit", "s.provided_gas_limit"),
        ("network_fee_lamports", "s.fee"),
        ("consumed_gas", "s.consumed_gas"),
        ("pump_program_account_index", "s.pf_program_account_index"),
        ("cu_price_instruction_index", "s.cu_price_ix_index"),
        ("cu_limit_instruction_index", "s.cu_limit_ix_index"),
        ("tip_instruction_index", "s.tip_index"),
        ("num_signatures", "s.num_signatures"),
        ("transaction_version", "s.transaction_version"),
        ("blockhash_prefix", "s.blockhash_prefix"),
        ("creation_block_ordinal", "l.block_ordinal"),
        ("creation_transaction_index", "l.transaction_index"),
        ("creation_raw_instruction_index", "l.raw_instruction_index"),
        ("creator", "l.creator"),
        ("creation_user", "l.creation_user"),
        ("curve_address", "l.curve_address"),
        ("token_program", "l.token_program"),
        ("cashback_enabled", "l.cashback_enabled"),
        ("mayhem_mode", "l.mayhem_mode"),
    )


def _aggregated_projection(
    values: tuple[tuple[str, str], ...],
    *,
    grouped_names: frozenset[str],
) -> str:
    result: list[str] = []
    for name, expression in values:
        rendered = expression if name in grouped_names else f"min({expression})"
        result.append(f"{rendered} AS {quoted_identifier(name)}")
    return ",\n    ".join(result)


def _curve_trade_sql(
    table: str,
    launch_table: str,
    block_range: BlockRange,
    decision_range: BlockRange,
    profile: PumpfunIndexerV1Profile,
) -> tuple[str, Mapping[str, Any]]:
    values = _trade_source_projection()
    projection = _aggregated_projection(
        values,
        grouped_names=frozenset({"raw_instruction_index", "signature"}),
    )
    variant_tuple = ", ".join(expression for _, expression in values)
    eligible_launches = _eligible_launch_sql(launch_table)
    sql = f"""SELECT
    {projection},
    count() AS source_row_count,
    uniqExact(tuple({variant_tuple})) AS payload_variant_count
FROM {table} AS s
ALL INNER JOIN (
    {eligible_launches}
) AS l ON s.base_coin = l.mint
PREWHERE s.slot >= {{from_block_ordinal:UInt64}}
    AND s.slot < {{to_block_ordinal:UInt64}}
WHERE s.failed = {{successful_failed_flag:UInt8}}
    AND s.quote_coin = {{wrapped_sol_quote:String}}
GROUP BY s.signature, s.ix_idx
ORDER BY block_ordinal, transaction_index, raw_instruction_index, signature"""
    parameters = _common_parameters(block_range)
    parameters.update(_decision_parameters(decision_range))
    parameters.update(
        {
            "eligible_mayhem_mode": 0,
            "native_sol_quote": profile.native_sol_quote,
            "wrapped_sol_quote": profile.wrapped_sol_quote,
            "successful_failed_flag": 0,
        }
    )
    return sql, parameters


def _terminal_trade_sql(
    trade_table: str,
    launch_table: str,
    *,
    require_migration_buy_v2: bool = False,
) -> str:
    values = _trade_source_projection()
    projection = _aggregated_projection(
        values,
        grouped_names=frozenset({"raw_instruction_index", "signature"}),
    )
    variant_tuple = ", ".join(expression for _, expression in values)
    eligible_launches = _eligible_launch_sql(launch_table)
    migration_instruction = (
        "\n    AND s.direction = {terminal_buy_direction:String}"
        "\n    AND s.instruction_type = {terminal_buy_instruction:String}"
        if require_migration_buy_v2
        else ""
    )
    return f"""SELECT
    {projection},
    count() AS source_row_count,
    uniqExact(tuple({variant_tuple})) AS payload_variant_count
FROM {trade_table} AS s
ALL INNER JOIN (
    {eligible_launches}
) AS l ON s.base_coin = l.mint
PREWHERE s.slot >= {{from_block_ordinal:UInt64}}
    AND s.slot < {{to_block_ordinal:UInt64}}
WHERE s.failed = {{successful_failed_flag:UInt8}}
    AND s.quote_coin = {{wrapped_sol_quote:String}}
    AND s.virtual_token_balance_after = {{terminal_virtual_token_reserves:UInt64}}
    {migration_instruction}
GROUP BY s.signature, s.ix_idx"""


def _migration_source_sql(table: str) -> str:
    values = (
        ("block_ordinal", "toUInt64(m.slot)"),
        ("block_time", "toUInt64(toUnixTimestamp(m.block_time))"),
        ("transaction_index", "toUInt64(m.tx_idx)"),
        ("signature", "m.signature"),
        ("mint", "m.mint"),
        ("curve_address", "m.bonding_curve"),
        ("migration_user", "m.user"),
        ("migration_mint_amount_atomic", "m.mint_amount"),
        ("migration_sol_amount_lamports", "m.sol_amount"),
        ("pool_migration_fee_lamports", "m.pool_migration_fee"),
        ("migration_pool", "m.pool"),
        ("migration_timestamp", "m.timestamp"),
        ("migration_parent_program", "m.parent_program"),
    )
    projection = _aggregated_projection(
        values,
        grouped_names=frozenset({"signature", "mint", "curve_address", "migration_pool"}),
    )
    variant_tuple = ", ".join(expression for _, expression in values)
    return f"""SELECT
    {projection},
    count() AS source_row_count,
    uniqExact(tuple({variant_tuple})) AS payload_variant_count
FROM {table} AS m
PREWHERE m.slot >= {{from_block_ordinal:UInt64}}
    AND m.slot < {{to_block_ordinal:UInt64}}
GROUP BY m.signature, m.mint, m.bonding_curve, m.pool"""


def _completion_candidate_select(terminal_alias: str = "t") -> str:
    return f"""SELECT
    'COMPLETION_CANDIDATE' AS candidate_kind,
    {terminal_alias}.block_ordinal AS block_ordinal,
    {terminal_alias}.block_time AS block_time,
    {terminal_alias}.transaction_index AS transaction_index,
    toNullable({terminal_alias}.raw_instruction_index) AS raw_instruction_index,
    {terminal_alias}.signature AS signature,
    {terminal_alias}.mint AS mint,
    {terminal_alias}.curve_address AS curve_address,
    {terminal_alias}.token_program AS token_program,
    {terminal_alias}.cashback_enabled AS cashback_enabled,
    {terminal_alias}.mayhem_mode AS mayhem_mode,
    {terminal_alias}.creation_block_ordinal AS creation_block_ordinal,
    {terminal_alias}.creation_transaction_index AS creation_transaction_index,
    {terminal_alias}.creation_raw_instruction_index AS creation_raw_instruction_index,
    toNullable({terminal_alias}.raw_instruction_index) AS terminal_raw_instruction_index,
    toNullable({terminal_alias}.virtual_token_reserves_after_atomic)
        AS terminal_virtual_token_reserves_after_atomic,
    toNullable({terminal_alias}.virtual_sol_reserves_after_lamports)
        AS terminal_virtual_sol_reserves_after_lamports,
    toUInt64(1) AS terminal_candidate_count,
    {terminal_alias}.source_row_count AS terminal_source_row_count,
    {terminal_alias}.payload_variant_count AS terminal_payload_variant_count,
    CAST(NULL AS Nullable(String)) AS migration_user,
    CAST(NULL AS Nullable(UInt64)) AS migration_mint_amount_atomic,
    CAST(NULL AS Nullable(UInt64)) AS migration_sol_amount_lamports,
    CAST(NULL AS Nullable(UInt64)) AS pool_migration_fee_lamports,
    CAST(NULL AS Nullable(String)) AS migration_pool,
    CAST(NULL AS Nullable(UInt32)) AS migration_timestamp,
    CAST(NULL AS Nullable(String)) AS migration_parent_program,
    {terminal_alias}.source_row_count AS source_row_count,
    {terminal_alias}.payload_variant_count AS payload_variant_count"""


def _migration_candidate_select() -> str:
    return """SELECT
    'MIGRATION_CANDIDATE' AS candidate_kind,
    m.block_ordinal AS block_ordinal,
    m.block_time AS block_time,
    m.transaction_index AS transaction_index,
    CAST(NULL AS Nullable(Int64)) AS raw_instruction_index,
    m.signature AS signature,
    m.mint AS mint,
    m.curve_address AS curve_address,
    l.token_program AS token_program,
    l.cashback_enabled AS cashback_enabled,
    l.mayhem_mode AS mayhem_mode,
    l.block_ordinal AS creation_block_ordinal,
    l.transaction_index AS creation_transaction_index,
    l.raw_instruction_index AS creation_raw_instruction_index,
    if(t.source_row_count = 0, CAST(NULL AS Nullable(Int64)),
        toNullable(t.raw_instruction_index)) AS terminal_raw_instruction_index,
    if(t.source_row_count = 0, CAST(NULL AS Nullable(UInt64)),
        toNullable(t.virtual_token_reserves_after_atomic))
        AS terminal_virtual_token_reserves_after_atomic,
    if(t.source_row_count = 0, CAST(NULL AS Nullable(UInt64)),
        toNullable(t.virtual_sol_reserves_after_lamports))
        AS terminal_virtual_sol_reserves_after_lamports,
    t.terminal_candidate_count AS terminal_candidate_count,
    t.source_row_count AS terminal_source_row_count,
    t.payload_variant_count AS terminal_payload_variant_count,
    toNullable(m.migration_user) AS migration_user,
    toNullable(m.migration_mint_amount_atomic) AS migration_mint_amount_atomic,
    toNullable(m.migration_sol_amount_lamports) AS migration_sol_amount_lamports,
    toNullable(m.pool_migration_fee_lamports) AS pool_migration_fee_lamports,
    toNullable(m.migration_pool) AS migration_pool,
    toNullable(m.migration_timestamp) AS migration_timestamp,
    toNullable(m.migration_parent_program) AS migration_parent_program,
    m.source_row_count AS source_row_count,
    m.payload_variant_count AS payload_variant_count"""


def _curve_lifecycle_sql(
    table: str,
    trade_table: str,
    launch_table: str,
    block_range: BlockRange,
    decision_range: BlockRange,
    profile: PumpfunIndexerV1Profile,
) -> tuple[str, Mapping[str, Any]]:
    terminal = _terminal_trade_sql(trade_table, launch_table)
    migration_terminal = _terminal_trade_sql(
        trade_table,
        launch_table,
        require_migration_buy_v2=True,
    )
    terminal_by_transaction = f"""SELECT
    min(u.block_ordinal) AS block_ordinal,
    min(u.transaction_index) AS transaction_index,
    u.signature AS signature,
    u.mint AS mint,
    min(u.raw_instruction_index) AS raw_instruction_index,
    min(u.virtual_token_reserves_after_atomic) AS virtual_token_reserves_after_atomic,
    min(u.virtual_sol_reserves_after_lamports) AS virtual_sol_reserves_after_lamports,
    count() AS terminal_candidate_count,
    sum(u.source_row_count) AS source_row_count,
    greatest(
        max(u.payload_variant_count),
        uniqExact(tuple(
            u.block_ordinal,
            u.transaction_index,
            u.raw_instruction_index,
            u.virtual_token_reserves_after_atomic,
            u.virtual_sol_reserves_after_lamports
        ))
    ) AS payload_variant_count
FROM (
    {migration_terminal}
) AS u
GROUP BY u.signature, u.mint"""
    migrations = _migration_source_sql(table)
    eligible_launches = _eligible_launch_sql(launch_table)
    output_projection = ", ".join(quoted_identifier(column) for column in _LIFECYCLE_COLUMNS)
    completion = _completion_candidate_select()
    migration = _migration_candidate_select()
    sql = f"""SELECT {output_projection}
FROM (
    {completion}
    FROM (
        {terminal}
    ) AS t
    UNION ALL
    {migration}
    FROM (
        {migrations}
    ) AS m
    ALL INNER JOIN (
        {eligible_launches}
    ) AS l ON m.mint = l.mint
    ALL LEFT JOIN (
        {terminal_by_transaction}
    ) AS t ON m.signature = t.signature
        AND m.mint = t.mint
        AND m.block_ordinal = t.block_ordinal
        AND m.transaction_index = t.transaction_index
) AS lifecycle_candidates
ORDER BY block_ordinal, transaction_index, candidate_kind, signature"""
    parameters = _common_parameters(block_range)
    parameters.update(_decision_parameters(decision_range))
    parameters.update(
        {
            "eligible_mayhem_mode": 0,
            "native_sol_quote": profile.native_sol_quote,
            "wrapped_sol_quote": profile.wrapped_sol_quote,
            "successful_failed_flag": 0,
            "terminal_buy_direction": "buy",
            "terminal_buy_instruction": "buy_v2",
            "terminal_virtual_token_reserves": profile.terminal_virtual_token_reserves,
        }
    )
    return sql, parameters


def _query_fingerprint(
    *,
    profile_id: str,
    template_id: str,
    template_digest: ContentDigest,
    sql: str,
    parameters: Mapping[str, Any],
) -> ContentDigest:
    material = json.dumps(
        {
            "parameters": dict(parameters),
            "profile_id": profile_id,
            "query_template_digest": template_digest.hex,
            "query_template_id": template_id,
            "sql": sql,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ContentDigest(sha256(_QUERY_FINGERPRINT_DOMAIN + material).hexdigest())


def _assert_safe_query(sql: str) -> None:
    normalized = " ".join(sql.upper().split())
    if not normalized.startswith("SELECT "):
        raise AssertionError("Pump.fun source profile may only emit SELECT")
    if "SELECT *" in normalized:
        raise AssertionError("Pump.fun source profile must never emit SELECT star")
    if re.search(r"\bOFFSET\b", normalized) is not None:
        raise AssertionError("Pump.fun source profile must never emit OFFSET")
    if ";" in sql:
        raise AssertionError("Pump.fun source profile must emit exactly one statement")


__all__ = [
    "PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION",
    "PUMPFUN_INDEXER_V1_NATIVE_SOL_QUOTE",
    "PUMPFUN_INDEXER_V1_PROFILE",
    "PUMPFUN_INDEXER_V1_PROFILE_ID",
    "PUMPFUN_INDEXER_V1_SENTINEL",
    "PUMPFUN_INDEXER_V1_TERMINAL_VIRTUAL_TOKEN_RESERVES",
    "PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE",
    "PumpfunIndexerV1Profile",
    "PumpfunIndexerV1Query",
    "PumpfunIndexerV1Sentinel",
    "build_pumpfun_indexer_v1_query",
    "pumpfun_indexer_v1_physical_mapping",
    "pumpfun_indexer_v1_query_template_digest",
    "registered_pumpfun_indexer_v1_profile",
]
