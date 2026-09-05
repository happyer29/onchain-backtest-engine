"""Deterministic normalization for the audited Pump.fun ClickHouse row shape.

The module knows Pump semantics but deliberately knows nothing about ClickHouse,
SQL, source credentials, or application evidence DTOs.  Composition code supplies
objects that structurally implement :class:`IndexedBatch`; the returned immutable
batches implement the same protocol and can be passed to the canonical projector.

The normalizer object is immutable.  Mutable state is confined to one explicitly
bounded stream session so continuity and ordering can be checked across arbitrary
driver batch boundaries without materializing a shard.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, NoReturn

from backtest.application.models import CapabilityStream
from backtest.application.ports.source import IndexedBatch
from backtest.domain.chain import UINT32_MAX
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange
from backtest.plugins.protocols.pumpfun.model import (
    PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1,
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
    PumpCurveLifecycle,
    PumpFeeProfile,
    PumpMode,
    PumpQuoteError,
    historical_trade_fee_breakdown,
)

PUMPFUN_LIVE_NORMALIZER_PROFILE_ID: Final = "pumpfun-indexer-v1-live-normalizer-v2"
PUMPFUN_CURVE_TRADE_NORMALIZER_PROFILE_ID: Final = "pumpfun-curve-trade-normalizer/v2"
PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID: Final = (
    "successful-sol-paired-non-mayhem-pumpfun-launches-in-decision-range-v2"
)
SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID: Final = (
    "solana-skipped-slot-epoch-zero-pinned-fingerprint-v1"
)
PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID: Final = "pumpfun-terminal-buy-completion-migration-order-v1"
PUMPFUN_STATIC_CURVE_STATE_PROFILE_ID: Final = "pumpfun-static-curve-state-v1"
PUMPFUN_MIGRATION_STATE_PROFILE_ID: Final = "pumpfun-pfamm-migration-state-v1"

PUMPFUN_LAUNCH_SOL_SOURCE_ASSET: Final = "11111111111111111111111111111111"
PUMPFUN_TRADE_SOL_SOURCE_ASSET: Final = "So11111111111111111111111111111111111111112"
PUMPFUN_CANONICAL_SOL_ASSET: Final = "SOL"
PUMPFUN_LEGACY_TOKEN_PROGRAM: Final = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
PUMPFUN_TOKEN_2022_PROGRAM: Final = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES: Final = 1_073_000_000_000_000
PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES: Final = 30_000_000_000
PUMPFUN_INITIAL_REAL_TOKEN_RESERVES: Final = 793_100_000_000_000
PUMPFUN_INITIAL_REAL_SOL_RESERVES: Final = 0
PUMPFUN_TOKEN_TOTAL_SUPPLY: Final = 1_000_000_000_000_000
PUMPFUN_REAL_TOKEN_OFFSET: Final = 279_900_000_000_000
PUMPFUN_REAL_SOL_OFFSET: Final = 30_000_000_000
PUMPFUN_MIGRATION_MINT_AMOUNT: Final = 206_900_000_000_000
PUMPFUN_POOL_MIGRATION_FEE: Final = 15_000_001

_MAX_U64: Final = (1 << 64) - 1
_BASE58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]+\Z")
_BASE58_ALPHABET: Final = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_VALUES: Final = {character: index for index, character in enumerate(_BASE58_ALPHABET)}
_SENTINEL_BLOCK_HASH: Final = " " * 48
_SENTINEL_VALIDATOR: Final = "MISSING" + " " * 41
_MAYHEM_EXCLUSION_REASON: Final = "MAYHEM_EXCLUDED"

_BLOCK_RAW_COLUMNS: Final = (
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

_LAUNCH_RAW_COLUMNS: Final = (
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

_TRADE_RAW_COLUMNS: Final = (
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

_LIFECYCLE_RAW_COLUMNS: Final = (
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

_RAW_COLUMNS: Final[Mapping[CapabilityStream, tuple[str, ...]]] = {
    CapabilityStream.BLOCK_CLOCK: _BLOCK_RAW_COLUMNS,
    CapabilityStream.TOKEN_LAUNCH: _LAUNCH_RAW_COLUMNS,
    CapabilityStream.PUMP_CURVE_TRADE: _TRADE_RAW_COLUMNS,
    CapabilityStream.PUMP_CURVE_LIFECYCLE: _LIFECYCLE_RAW_COLUMNS,
}

_BLOCK_OUTPUT_COLUMNS: Final = (
    "block_ordinal",
    "block_time",
    "transaction_count",
    "block_hash",
)
_LAUNCH_OUTPUT_COLUMNS: Final = (
    "block_ordinal",
    "transaction_index",
    "event_index",
    "signature",
    "transaction_succeeded",
    "mint",
    "creator",
    "creation_user",
    "venue",
    "quote_asset",
    "virtual_token_reserves_atomic",
    "virtual_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "real_sol_reserves_lamports",
    "token_total_supply_atomic",
    "lifecycle",
    "mode",
)
_TRADE_OUTPUT_COLUMNS: Final = (
    "block_ordinal",
    "transaction_index",
    "event_index",
    "signature",
    "venue",
    "mint",
    "quote_asset",
    "side",
    "base_amount_atomic",
    "quote_amount_atomic",
    "protocol_fee_atomic",
    "creator_fee_atomic",
    "virtual_token_reserves_atomic",
    "virtual_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "real_sol_reserves_lamports",
    "token_total_supply_atomic",
    "lifecycle",
    "mode",
)
_LIFECYCLE_OUTPUT_COLUMNS: Final = (
    "block_ordinal",
    "transaction_index",
    "event_index",
    "signature",
    "mint",
    "venue",
    "lifecycle_kind",
    "virtual_token_reserves_atomic",
    "virtual_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "real_sol_reserves_lamports",
    "token_total_supply_atomic",
    "lifecycle",
    "mode",
)
_OUTPUT_COLUMNS: Final[Mapping[CapabilityStream, tuple[str, ...]]] = {
    CapabilityStream.BLOCK_CLOCK: _BLOCK_OUTPUT_COLUMNS,
    CapabilityStream.TOKEN_LAUNCH: _LAUNCH_OUTPUT_COLUMNS,
    CapabilityStream.PUMP_CURVE_TRADE: _TRADE_OUTPUT_COLUMNS,
    CapabilityStream.PUMP_CURVE_LIFECYCLE: _LIFECYCLE_OUTPUT_COLUMNS,
}

_SUPPORTED_TRADE_INSTRUCTIONS: Final = frozenset(
    {
        ("buy", "buy"),
        ("buy", "buy_exact_quote_in_v2"),
        ("buy", "buy_exact_sol_in"),
        ("buy", "buy_v2"),
        ("sell", "sell"),
        ("sell", "sell_v2"),
    }
)


class PumpfunLiveNormalizationErrorCode(StrEnum):
    """Stable fail-closed reasons exposed by the live normalization boundary."""

    INCOMPLETE_BLOCK_RANGE = "INCOMPLETE_BLOCK_RANGE"
    BATCH_CONTRACT_INVALID = "BATCH_CONTRACT_INVALID"
    RAW_SCHEMA_MISMATCH = "RAW_SCHEMA_MISMATCH"
    POSITION_INVALID = "POSITION_INVALID"
    IDENTIFIER_INVALID = "IDENTIFIER_INVALID"
    LAUNCH_CONTRACT_INVALID = "LAUNCH_CONTRACT_INVALID"
    UNSUPPORTED_PROGRAM_MODE = "UNSUPPORTED_PROGRAM_MODE"
    TRADE_CONTRACT_INVALID = "TRADE_CONTRACT_INVALID"
    LIFECYCLE_CONTRACT_INVALID = "LIFECYCLE_CONTRACT_INVALID"
    FEE_PROFILE_INVALID = "FEE_PROFILE_INVALID"
    STREAM_NOT_FINISHED = "STREAM_NOT_FINISHED"
    STREAM_ALREADY_FINISHED = "STREAM_ALREADY_FINISHED"


class PumpfunLiveNormalizationError(ValueError):
    """A deterministic, secret-free rejection of one raw source stream."""

    def __init__(self, code: PumpfunLiveNormalizationErrorCode) -> None:
        if not isinstance(code, PumpfunLiveNormalizationErrorCode):
            raise TypeError("code must be a PumpfunLiveNormalizationErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class PumpfunNormalizedBatch:
    """Immutable adapter-neutral output accepted by the canonical projector."""

    capability_id: CapabilityId
    covered_range: BlockRange
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    query_fingerprint: ContentDigest

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, CapabilityId):
            raise TypeError("capability_id must be a CapabilityId")
        if not isinstance(self.covered_range, BlockRange):
            raise TypeError("covered_range must be a BlockRange")
        if not self.columns or len(set(self.columns)) != len(self.columns):
            raise ValueError("normalized columns must be non-empty and unique")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("normalized row width does not match columns")
        if not isinstance(self.query_fingerprint, ContentDigest):
            raise TypeError("query_fingerprint must be a ContentDigest")

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class SkippedSlotObservation:
    profile_id: str
    block_ordinal: int


@dataclass(frozen=True, slots=True)
class ExcludedLaunchObservation:
    policy_id: str
    reason: str
    block_ordinal: int
    transaction_index: int
    event_index: int
    signature: str
    mint: str


@dataclass(frozen=True, slots=True)
class DerivedLifecycleGroupObservation:
    profile_id: str
    block_ordinal: int
    transaction_index: int
    terminal_event_index: int
    completion_event_index: int
    migration_event_index: int
    signature: str
    mint: str
    curve_address: str


type PumpfunNormalizationObservation = (
    SkippedSlotObservation | ExcludedLaunchObservation | DerivedLifecycleGroupObservation
)
type PumpfunNormalizationObservationSink = Callable[[PumpfunNormalizationObservation], None]


@dataclass(frozen=True, slots=True)
class PumpfunNormalizationSummary:
    """Bounded primitive metadata from one fully consumed stream session."""

    stream: CapabilityStream
    raw_row_count: int
    normalized_row_count: int
    normalized_stream_digest: ContentDigest
    launch_classified_count: int
    launch_eligible_count: int
    launch_excluded_count: int
    ordered_exclusion_digest: ContentDigest
    recognized_sentinel_count: int
    ordered_sentinel_digest: ContentDigest
    derived_lifecycle_group_count: int
    ordered_lifecycle_group_digest: ContentDigest

    def __post_init__(self) -> None:
        for name in (
            "raw_row_count",
            "normalized_row_count",
            "launch_classified_count",
            "launch_eligible_count",
            "launch_excluded_count",
            "recognized_sentinel_count",
            "derived_lifecycle_group_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.launch_classified_count != (
            self.launch_eligible_count + self.launch_excluded_count
        ):
            raise ValueError("classified launches must equal eligible plus excluded")


@dataclass(frozen=True, slots=True)
class PumpfunLiveNormalizer:
    """Immutable configuration and factory for bounded normalization sessions."""

    fee_profile: PumpFeeProfile

    def __post_init__(self) -> None:
        if not isinstance(self.fee_profile, PumpFeeProfile):
            raise TypeError("fee_profile must be a PumpFeeProfile")
        if (
            self.fee_profile.program_version != PUMP_STATIC_PROGRAM_CONTRACT_V1
            or self.fee_profile.protocol_fee_bps != 95
            or self.fee_profile.creator_fee_bps != 30
        ):
            raise PumpfunLiveNormalizationError(
                PumpfunLiveNormalizationErrorCode.FEE_PROFILE_INVALID
            )

    @property
    def profile_id(self) -> str:
        return PUMPFUN_LIVE_NORMALIZER_PROFILE_ID

    @property
    def config_digest(self) -> ContentDigest:
        """Bind every source-derived transform without binding endpoint or credentials."""

        return domain_digest(
            "backtest.pumpfun-live-normalizer-config.v2",
            {
                "curve_state": {
                    "initial_real_sol": PUMPFUN_INITIAL_REAL_SOL_RESERVES,
                    "initial_real_token": PUMPFUN_INITIAL_REAL_TOKEN_RESERVES,
                    "initial_virtual_sol": PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES,
                    "initial_virtual_token": PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES,
                    "profile_id": PUMPFUN_STATIC_CURVE_STATE_PROFILE_ID,
                    "real_sol_offset": PUMPFUN_REAL_SOL_OFFSET,
                    "real_token_offset": PUMPFUN_REAL_TOKEN_OFFSET,
                    "token_total_supply": PUMPFUN_TOKEN_TOTAL_SUPPLY,
                },
                "fee_profile": {
                    "buy_formula_version": self.fee_profile.buy_formula_version,
                    "creator_fee_bps": self.fee_profile.creator_fee_bps,
                    "effective_from_unix_s": self.fee_profile.effective_from_unix_s,
                    "effective_until_unix_s": self.fee_profile.effective_until_unix_s,
                    "profile_id": self.fee_profile.profile_id,
                    "program_version": self.fee_profile.program_version,
                    "protocol_fee_bps": self.fee_profile.protocol_fee_bps,
                    "sell_formula_version": self.fee_profile.sell_formula_version,
                },
                "historical_fee_formula": PUMP_HISTORICAL_COMPONENT_FEE_FORMULA_V1,
                "launch_universe_policy_id": PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
                "migration": {
                    "mint_amount": PUMPFUN_MIGRATION_MINT_AMOUNT,
                    "pool_migration_fee": PUMPFUN_POOL_MIGRATION_FEE,
                    "profile_id": PUMPFUN_MIGRATION_STATE_PROFILE_ID,
                },
                "launch_sol_source_asset": PUMPFUN_LAUNCH_SOL_SOURCE_ASSET,
                "normalizer_profile_id": PUMPFUN_LIVE_NORMALIZER_PROFILE_ID,
                "output_columns": {
                    stream.value: list(_OUTPUT_COLUMNS[stream]) for stream in CapabilityStream
                },
                "raw_columns": {
                    stream.value: list(_RAW_COLUMNS[stream]) for stream in CapabilityStream
                },
                "sentinel": {
                    "block_hash": _SENTINEL_BLOCK_HASH,
                    "block_time_epoch_seconds": 0,
                    "profile_id": SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
                    "rewards": 0,
                    "transaction_count": 0,
                    "validator": _SENTINEL_VALIDATOR,
                },
                "supported_trade_instructions": [
                    list(item) for item in sorted(_SUPPORTED_TRADE_INSTRUCTIONS)
                ],
                "terminal_lifecycle_profile_id": PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
                "trade_sol_source_asset": PUMPFUN_TRADE_SOL_SOURCE_ASSET,
                "trade_normalizer_profile_id": PUMPFUN_CURVE_TRADE_NORMALIZER_PROFILE_ID,
                "token_program_modes": {
                    "legacy": PUMPFUN_LEGACY_TOKEN_PROGRAM,
                    "token_2022": PUMPFUN_TOKEN_2022_PROGRAM,
                },
            },
        )

    def raw_columns(self, stream: CapabilityStream) -> tuple[str, ...]:
        return _columns_for(_RAW_COLUMNS, stream)

    def output_columns(self, stream: CapabilityStream) -> tuple[str, ...]:
        return _columns_for(_OUTPUT_COLUMNS, stream)

    def begin(
        self,
        *,
        stream: CapabilityStream,
        capability_id: CapabilityId,
        covered_range: BlockRange,
        observation_sink: PumpfunNormalizationObservationSink | None = None,
    ) -> PumpfunNormalizationSession:
        """Create one explicit session for exactly one capability shard."""

        return PumpfunNormalizationSession(
            normalizer=self,
            stream=stream,
            capability_id=capability_id,
            covered_range=covered_range,
            observation_sink=observation_sink,
        )


class PumpfunNormalizationSession:
    """Streaming validation state for one capability and one half-open block range."""

    __slots__ = (
        "_capability_id",
        "_covered_range",
        "_derived_lifecycle_groups",
        "_excluded_launches",
        "_expected_block",
        "_failed",
        "_finished",
        "_last_launch_transaction",
        "_last_order_key",
        "_last_produced_block_time",
        "_launch_classified",
        "_launch_eligible",
        "_lifecycle_completion",
        "_lifecycle_migration_seen",
        "_lifecycle_position",
        "_normalized_rows",
        "_normalized_stream_digest",
        "_normalizer",
        "_observation_sink",
        "_ordered_exclusion_digest",
        "_ordered_lifecycle_digest",
        "_ordered_sentinel_digest",
        "_query_fingerprint",
        "_raw_rows",
        "_recognized_sentinels",
        "_stream",
        "_summary",
    )

    def __init__(
        self,
        *,
        normalizer: PumpfunLiveNormalizer,
        stream: CapabilityStream,
        capability_id: CapabilityId,
        covered_range: BlockRange,
        observation_sink: PumpfunNormalizationObservationSink | None,
    ) -> None:
        if not isinstance(normalizer, PumpfunLiveNormalizer):
            raise TypeError("normalizer must be a PumpfunLiveNormalizer")
        if not isinstance(stream, CapabilityStream):
            raise TypeError("stream must be a CapabilityStream")
        if not isinstance(capability_id, CapabilityId):
            raise TypeError("capability_id must be a CapabilityId")
        if not isinstance(covered_range, BlockRange):
            raise TypeError("covered_range must be a BlockRange")
        if observation_sink is not None and not callable(observation_sink):
            raise TypeError("observation_sink must be callable")
        self._normalizer = normalizer
        self._stream = stream
        self._capability_id = capability_id
        self._covered_range = covered_range
        self._observation_sink = observation_sink
        self._query_fingerprint: ContentDigest | None = None
        self._raw_rows = 0
        self._normalized_rows = 0
        self._launch_classified = 0
        self._launch_eligible = 0
        self._excluded_launches = 0
        self._recognized_sentinels = 0
        self._derived_lifecycle_groups = 0
        self._expected_block = covered_range.from_block_ordinal
        self._last_produced_block_time: int | None = None
        self._last_order_key: tuple[object, ...] | None = None
        self._last_launch_transaction: tuple[int, int] | None = None
        self._lifecycle_position: tuple[int, int] | None = None
        self._lifecycle_completion: tuple[str, str, str, int, int] | None = None
        self._lifecycle_migration_seen = False
        self._normalized_stream_digest = _OrderedDigest(
            "backtest.pumpfun-normalized-stream.v2",
            {
                "capability_id": capability_id.value,
                "columns": list(_OUTPUT_COLUMNS[stream]),
                "range": _range_document(covered_range),
                "stream": stream.value,
            },
        )
        self._ordered_exclusion_digest = _OrderedDigest(
            "backtest.pumpfun-ordered-launch-exclusions.v1",
            {
                "policy_id": PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
                "range": _range_document(covered_range),
            },
        )
        self._ordered_sentinel_digest = _OrderedDigest(
            "backtest.solana-ordered-skipped-slots.v1",
            {
                "profile_id": SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
                "range": _range_document(covered_range),
            },
        )
        self._ordered_lifecycle_digest = _OrderedDigest(
            "backtest.pumpfun-ordered-derived-lifecycle-groups.v1",
            {
                "profile_id": PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
                "range": _range_document(covered_range),
            },
        )
        self._finished = False
        self._failed = False
        self._summary: PumpfunNormalizationSummary | None = None

    def normalize(self, batch: IndexedBatch) -> PumpfunNormalizedBatch:
        """Normalize one driver batch while retaining only bounded validation state."""

        if self._finished:
            _raise(PumpfunLiveNormalizationErrorCode.STREAM_ALREADY_FINISHED)
        if self._failed:
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        try:
            self._validate_batch(batch)
            normalized: list[tuple[Any, ...]] = []
            indexes = {name: index for index, name in enumerate(batch.columns)}
            for row in batch.rows:
                self._raw_rows += 1
                output = self._normalize_row(row, indexes)
                if output is not None:
                    self._normalized_stream_digest.update(list(output))
                    self._normalized_rows += 1
                    normalized.append(output)
            fingerprint = self._query_fingerprint
            if fingerprint is None:  # pragma: no cover - _validate_batch establishes it
                _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
            return PumpfunNormalizedBatch(
                capability_id=self._capability_id,
                covered_range=self._covered_range,
                columns=_OUTPUT_COLUMNS[self._stream],
                rows=tuple(normalized),
                query_fingerprint=fingerprint,
            )
        except PumpfunLiveNormalizationError:
            self._failed = True
            raise
        except (OverflowError, PumpQuoteError, TypeError, ValueError) as error:
            self._failed = True
            raise PumpfunLiveNormalizationError(_row_contract_error_code(self._stream)) from error

    def finish(self) -> PumpfunNormalizationSummary:
        """Seal the stream and prove checks that require end-of-range knowledge."""

        if self._failed:
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        if self._summary is not None:
            return self._summary
        if (
            self._stream is CapabilityStream.BLOCK_CLOCK
            and self._expected_block != self._covered_range.to_block_ordinal
        ):
            self._failed = True
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        self._finished = True
        self._summary = PumpfunNormalizationSummary(
            stream=self._stream,
            raw_row_count=self._raw_rows,
            normalized_row_count=self._normalized_rows,
            normalized_stream_digest=self._normalized_stream_digest.digest(),
            launch_classified_count=self._launch_classified,
            launch_eligible_count=self._launch_eligible,
            launch_excluded_count=self._excluded_launches,
            ordered_exclusion_digest=self._ordered_exclusion_digest.digest(),
            recognized_sentinel_count=self._recognized_sentinels,
            ordered_sentinel_digest=self._ordered_sentinel_digest.digest(),
            derived_lifecycle_group_count=self._derived_lifecycle_groups,
            ordered_lifecycle_group_digest=self._ordered_lifecycle_digest.digest(),
        )
        return self._summary

    @property
    def result(self) -> PumpfunNormalizationSummary:
        if self._summary is None:
            _raise(PumpfunLiveNormalizationErrorCode.STREAM_NOT_FINISHED)
        return self._summary

    def _validate_batch(self, batch: IndexedBatch) -> None:
        if batch.capability_id != self._capability_id:
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        if batch.covered_range != self._covered_range:
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        if batch.columns != _RAW_COLUMNS[self._stream]:
            _raise(PumpfunLiveNormalizationErrorCode.RAW_SCHEMA_MISMATCH)
        if batch.row_count != len(batch.rows):
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        if any(len(row) != len(batch.columns) for row in batch.rows):
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        fingerprint = batch.query_fingerprint
        if not isinstance(fingerprint, ContentDigest):
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)
        if self._query_fingerprint is None:
            self._query_fingerprint = fingerprint
        elif self._query_fingerprint != fingerprint:
            _raise(PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID)

    def _normalize_row(
        self,
        row: tuple[Any, ...],
        indexes: Mapping[str, int],
    ) -> tuple[Any, ...] | None:
        values = _Row(row, indexes)
        if self._stream is CapabilityStream.BLOCK_CLOCK:
            return self._normalize_block(values)
        if self._stream is CapabilityStream.TOKEN_LAUNCH:
            return self._normalize_launch(values)
        if self._stream is CapabilityStream.PUMP_CURVE_TRADE:
            return self._normalize_trade(values)
        if self._stream is CapabilityStream.PUMP_CURVE_LIFECYCLE:
            return self._normalize_lifecycle(values)

    def _normalize_block(self, values: _Row) -> tuple[Any, ...] | None:
        block = _uint(values["block_ordinal"], maximum=UINT32_MAX)
        if block != self._expected_block:
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        self._expected_block += 1
        if _uint(values["source_row_count"]) < 1:
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        if _uint(values["payload_variant_count"]) != 1:
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        flag = _flag(values["is_nonproduced_sentinel"])
        time_seconds, time_ns = _block_time(values["block_time"])
        raw_hash = _raw_text(values["block_hash"])
        raw_validator = _raw_text(values["validator"])
        rewards = _uint(values["rewards"])
        transaction_count = _uint(values["transaction_count"], maximum=UINT32_MAX)
        exact_sentinel = (
            time_seconds == 0
            and raw_hash == _SENTINEL_BLOCK_HASH
            and raw_validator == _SENTINEL_VALIDATOR
            and rewards == 0
            and transaction_count == 0
        )
        sentinel_shaped = (
            flag
            or time_seconds == 0
            or raw_hash == _SENTINEL_BLOCK_HASH
            or raw_validator == _SENTINEL_VALIDATOR
        )
        if flag and exact_sentinel:
            observation = SkippedSlotObservation(
                profile_id=SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
                block_ordinal=block,
            )
            self._recognized_sentinels += 1
            self._ordered_sentinel_digest.update(_observation_document(observation))
            self._emit(observation)
            return None
        if exact_sentinel or sentinel_shaped:
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        try:
            block_hash = _base58_identifier(raw_hash, decoded_bytes=32)
        except ValueError as error:
            raise PumpfunLiveNormalizationError(
                PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE
            ) from error
        if (
            self._last_produced_block_time is not None
            and time_seconds < self._last_produced_block_time
        ):
            _raise(PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE)
        self._last_produced_block_time = time_seconds
        return block, time_ns, transaction_count, block_hash

    def _normalize_launch(self, values: _Row) -> tuple[Any, ...] | None:
        block, transaction, raw_instruction, event_index = self._position(values)
        signature = _signature(values["signature"])
        mint = _public_key(values["mint"])
        creator = _public_key(values["creator"])
        creation_user = _public_key(values["creation_user"])
        curve = _public_key(values["curve_address"])
        quote_source = _public_key(values["quote_asset"])
        if quote_source != PUMPFUN_LAUNCH_SOL_SOURCE_ASSET:
            _raise(PumpfunLiveNormalizationErrorCode.LAUNCH_CONTRACT_INVALID)
        mayhem = _flag(values["mayhem_mode"])
        key = (block, transaction, raw_instruction, signature, mint)
        self._require_order(key, PumpfunLiveNormalizationErrorCode.LAUNCH_CONTRACT_INVALID)
        transaction_key = block, transaction
        if self._last_launch_transaction == transaction_key:
            _raise(PumpfunLiveNormalizationErrorCode.LAUNCH_CONTRACT_INVALID)
        self._last_launch_transaction = transaction_key
        _block_time(values["block_time"])
        _flag(values["direct_pump_invocation"])
        _uint(values["pump_program_index"])
        _uint(values["bundle_size"])
        _uint(values["bundled_buys"])
        _uint(values["bundled_buys_count"])
        _uint(values["dev_balance"])
        self._launch_classified += 1
        if mayhem:
            observation = ExcludedLaunchObservation(
                policy_id=PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
                reason=_MAYHEM_EXCLUSION_REASON,
                block_ordinal=block,
                transaction_index=transaction,
                event_index=event_index,
                signature=signature,
                mint=mint,
            )
            self._excluded_launches += 1
            self._ordered_exclusion_digest.update(_observation_document(observation))
            self._emit(observation)
            return None
        mode = _mode(values["token_program"], values["cashback_enabled"])
        self._launch_eligible += 1
        return (
            block,
            transaction,
            event_index,
            signature,
            True,
            mint,
            creator,
            creation_user,
            curve,
            PUMPFUN_CANONICAL_SOL_ASSET,
            PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES,
            PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES,
            PUMPFUN_INITIAL_REAL_TOKEN_RESERVES,
            PUMPFUN_INITIAL_REAL_SOL_RESERVES,
            PUMPFUN_TOKEN_TOTAL_SUPPLY,
            PumpCurveLifecycle.ACTIVE.value,
            mode.value,
        )

    def _normalize_trade(self, values: _Row) -> tuple[Any, ...]:
        block, transaction, raw_instruction, event_index = self._position(values)
        signature = _signature(values["signature"])
        mint = _public_key(values["mint"])
        curve = _public_key(values["curve_address"])
        if _public_key(values["quote_asset"]) != PUMPFUN_TRADE_SOL_SOURCE_ASSET:
            _raise(PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        if _flag(values["failed"]):
            _raise(PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        if _flag(values["mayhem_mode"]):
            _raise(PumpfunLiveNormalizationErrorCode.UNSUPPORTED_PROGRAM_MODE)
        mode = _mode(values["token_program"], values["cashback_enabled"])
        source_count = _uint(values["source_row_count"])
        variants = _uint(values["payload_variant_count"])
        if source_count < 1 or variants != 1:
            _raise(PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        key = (block, transaction, raw_instruction, signature, mint)
        self._require_order(key, PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        direction = _closed_text(values["direction"])
        instruction = _closed_text(values["instruction_type"])
        if (direction, instruction) not in _SUPPORTED_TRADE_INSTRUCTIONS:
            _raise(PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        base_amount = _uint(values["base_amount_atomic"])
        quote_amount = _uint(values["quote_amount_atomic"])
        if base_amount == 0 or (direction == "buy" and quote_amount == 0):
            _raise(PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID)
        virtual_token, virtual_sol, real_token, real_sol, lifecycle = _curve_state(
            values["virtual_token_reserves_after_atomic"],
            values["virtual_sol_reserves_after_lamports"],
        )
        effective_at, _ = _block_time(values["block_time"])
        try:
            fees = historical_trade_fee_breakdown(
                mode,
                curve_sol_lamports=quote_amount,
                fee_profile=self._normalizer.fee_profile,
                effective_at_unix_s=effective_at,
            )
        except PumpQuoteError as error:
            raise PumpfunLiveNormalizationError(
                PumpfunLiveNormalizationErrorCode.FEE_PROFILE_INVALID
            ) from error
        return (
            block,
            transaction,
            event_index,
            signature,
            curve,
            mint,
            PUMPFUN_CANONICAL_SOL_ASSET,
            direction.upper(),
            base_amount,
            quote_amount,
            fees.protocol_fee_lamports,
            fees.creator_fee_lamports,
            virtual_token,
            virtual_sol,
            real_token,
            real_sol,
            PUMPFUN_TOKEN_TOTAL_SUPPLY,
            lifecycle.value,
            mode.value,
        )

    def _normalize_lifecycle(self, values: _Row) -> tuple[Any, ...]:
        block = _uint(values["block_ordinal"], maximum=UINT32_MAX)
        transaction = _transaction_index(values["transaction_index"])
        if not self._covered_range.contains_block(block):
            _raise(PumpfunLiveNormalizationErrorCode.POSITION_INVALID)
        _block_time(values["block_time"])
        signature = _signature(values["signature"])
        mint = _public_key(values["mint"])
        curve = _public_key(values["curve_address"])
        if _flag(values["mayhem_mode"]):
            _raise(PumpfunLiveNormalizationErrorCode.UNSUPPORTED_PROGRAM_MODE)
        mode = _mode(values["token_program"], values["cashback_enabled"])
        candidate = _closed_text(values["candidate_kind"])
        candidate_order = {"COMPLETION_CANDIDATE": 0, "MIGRATION_CANDIDATE": 1}.get(candidate)
        if candidate_order is None:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        key = (block, transaction, candidate_order, signature, mint)
        self._require_order(key, PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        self._start_lifecycle_position(block, transaction)
        if _uint(values["source_row_count"]) < 1 or _uint(values["payload_variant_count"]) != 1:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        if candidate == "COMPLETION_CANDIDATE":
            return self._normalize_completion(
                values, block, transaction, signature, mint, curve, mode
            )
        return self._normalize_migration(values, block, transaction, signature, mint, curve, mode)

    def _normalize_completion(
        self,
        values: _Row,
        block: int,
        transaction: int,
        signature: str,
        mint: str,
        curve: str,
        mode: PumpMode,
    ) -> tuple[Any, ...]:
        if self._lifecycle_completion is not None or self._lifecycle_migration_seen:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        raw_instruction = _instruction_index(values["raw_instruction_index"])
        terminal_instruction = _instruction_index(values["terminal_raw_instruction_index"])
        if raw_instruction != terminal_instruction:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        if (
            _uint(values["terminal_candidate_count"]) != 1
            or _uint(values["terminal_source_row_count"]) < 1
            or _uint(values["terminal_payload_variant_count"]) != 1
        ):
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        if any(
            values[name] is not None
            for name in (
                "migration_user",
                "migration_mint_amount_atomic",
                "migration_sol_amount_lamports",
                "pool_migration_fee_lamports",
                "migration_pool",
                "migration_timestamp",
                "migration_parent_program",
            )
        ):
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        virtual_token = _uint(values["terminal_virtual_token_reserves_after_atomic"])
        virtual_sol = _uint(values["terminal_virtual_sol_reserves_after_lamports"])
        if virtual_token != PUMPFUN_REAL_TOKEN_OFFSET or virtual_sol < PUMPFUN_REAL_SOL_OFFSET:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        event_index = _derived_event_index(raw_instruction, offset=1)
        self._lifecycle_completion = signature, mint, curve, raw_instruction, virtual_sol
        return _lifecycle_row(
            block=block,
            transaction=transaction,
            event_index=event_index,
            signature=signature,
            mint=mint,
            curve=curve,
            lifecycle=PumpCurveLifecycle.COMPLETED,
            mode=mode,
            virtual_sol=virtual_sol,
        )

    def _normalize_migration(
        self,
        values: _Row,
        block: int,
        transaction: int,
        signature: str,
        mint: str,
        curve: str,
        mode: PumpMode,
    ) -> tuple[Any, ...]:
        if self._lifecycle_migration_seen or values["raw_instruction_index"] is not None:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        migration_user = _public_key(values["migration_user"])
        migration_pool = _public_key(values["migration_pool"])
        del migration_user, migration_pool
        if _uint(values["migration_mint_amount_atomic"]) != PUMPFUN_MIGRATION_MINT_AMOUNT:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        migration_sol = _uint(values["migration_sol_amount_lamports"])
        if _uint(values["pool_migration_fee_lamports"]) != PUMPFUN_POOL_MIGRATION_FEE:
            _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
        _uint(values["migration_timestamp"])
        real_sol = _checked_add(migration_sol, PUMPFUN_POOL_MIGRATION_FEE)
        virtual_sol = _checked_add(real_sol, PUMPFUN_REAL_SOL_OFFSET)
        terminal_values = (
            values["terminal_raw_instruction_index"],
            values["terminal_virtual_token_reserves_after_atomic"],
            values["terminal_virtual_sol_reserves_after_lamports"],
        )
        has_terminal = any(item is not None for item in terminal_values)
        if has_terminal:
            if any(item is None for item in terminal_values):
                _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
            raw_instruction = _instruction_index(values["terminal_raw_instruction_index"])
            if (
                _uint(values["terminal_candidate_count"]) != 1
                or _uint(values["terminal_source_row_count"]) < 1
                or _uint(values["terminal_payload_variant_count"]) != 1
                or _uint(values["terminal_virtual_token_reserves_after_atomic"])
                != PUMPFUN_REAL_TOKEN_OFFSET
                or _uint(values["terminal_virtual_sol_reserves_after_lamports"]) != virtual_sol
                or self._lifecycle_completion
                != (signature, mint, curve, raw_instruction, virtual_sol)
            ):
                _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
            terminal_event = _derived_event_index(raw_instruction, offset=0)
            completion_event = _derived_event_index(raw_instruction, offset=1)
            event_index = _derived_event_index(raw_instruction, offset=2)
            observation = DerivedLifecycleGroupObservation(
                profile_id=PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
                block_ordinal=block,
                transaction_index=transaction,
                terminal_event_index=terminal_event,
                completion_event_index=completion_event,
                migration_event_index=event_index,
                signature=signature,
                mint=mint,
                curve_address=curve,
            )
            self._derived_lifecycle_groups += 1
            self._ordered_lifecycle_digest.update(_observation_document(observation))
            self._emit(observation)
        else:
            if (
                _uint(values["terminal_candidate_count"]) != 0
                or _uint(values["terminal_source_row_count"]) != 0
                or _uint(values["terminal_payload_variant_count"]) != 0
                or self._lifecycle_completion is not None
            ):
                _raise(PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID)
            event_index = 0
        self._lifecycle_migration_seen = True
        return _lifecycle_row(
            block=block,
            transaction=transaction,
            event_index=event_index,
            signature=signature,
            mint=mint,
            curve=curve,
            lifecycle=PumpCurveLifecycle.MIGRATED,
            mode=mode,
            virtual_sol=virtual_sol,
        )

    def _position(self, values: _Row) -> tuple[int, int, int, int]:
        block = _uint(values["block_ordinal"], maximum=UINT32_MAX)
        transaction = _transaction_index(values["transaction_index"])
        raw_instruction = _instruction_index(values["raw_instruction_index"])
        if not self._covered_range.contains_block(block):
            _raise(PumpfunLiveNormalizationErrorCode.POSITION_INVALID)
        return block, transaction, raw_instruction, _derived_event_index(raw_instruction, offset=0)

    def _require_order(
        self,
        key: tuple[object, ...],
        code: PumpfunLiveNormalizationErrorCode,
    ) -> None:
        if self._last_order_key is not None and key <= self._last_order_key:
            _raise(code)
        self._last_order_key = key

    def _start_lifecycle_position(self, block: int, transaction: int) -> None:
        position = block, transaction
        if self._lifecycle_position != position:
            self._lifecycle_position = position
            self._lifecycle_completion = None
            self._lifecycle_migration_seen = False

    def _emit(self, observation: PumpfunNormalizationObservation) -> None:
        if self._observation_sink is not None:
            self._observation_sink(observation)


class _Row:
    __slots__ = ("_indexes", "_row")

    def __init__(self, row: tuple[Any, ...], indexes: Mapping[str, int]) -> None:
        self._row = row
        self._indexes = indexes

    def __getitem__(self, name: str) -> Any:
        return self._row[self._indexes[name]]


class _OrderedDigest:
    __slots__ = ("_hash",)

    def __init__(self, domain: str, header: object) -> None:
        self._hash = sha256()
        self._hash.update(domain.encode("utf-8") + b"\x00")
        self.update(header)

    def update(self, value: object) -> None:
        encoded = canonical_json_bytes(value)
        self._hash.update(len(encoded).to_bytes(8, "big"))
        self._hash.update(encoded)

    def digest(self) -> ContentDigest:
        return ContentDigest(self._hash.hexdigest())


def _columns_for(
    source: Mapping[CapabilityStream, tuple[str, ...]],
    stream: CapabilityStream,
) -> tuple[str, ...]:
    if not isinstance(stream, CapabilityStream):
        raise TypeError("stream must be a CapabilityStream")
    return source[stream]


def _uint(value: object, *, maximum: int = _MAX_U64) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError("source value is outside its unsigned integer contract")
    return value


def _flag(value: object) -> bool:
    integer = _uint(value, maximum=1)
    return integer == 1


def _transaction_index(value: object) -> int:
    return _uint(value, maximum=UINT32_MAX - 1)


def _instruction_index(value: object) -> int:
    maximum = (UINT32_MAX - 2) // 2
    return _uint(value, maximum=maximum)


def _derived_event_index(raw_instruction_index: int, *, offset: int) -> int:
    value = raw_instruction_index * 2 + offset
    if value > UINT32_MAX:
        raise OverflowError("derived event index exceeds UInt32")
    return value


def _raw_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("source identifier is not ASCII") from error
    if not isinstance(value, str):
        raise ValueError("source identifier is not text")
    return value


def _strip_fixed_nul(value: object) -> str:
    text = _raw_text(value)
    stripped = text.rstrip("\x00")
    if not stripped or "\x00" in stripped:
        raise ValueError("source identifier contains invalid NUL padding")
    return stripped


def _base58_identifier(value: object, *, decoded_bytes: int) -> str:
    text = _strip_fixed_nul(value)
    if text != text.strip() or _BASE58_RE.fullmatch(text) is None:
        raise ValueError("source identifier is not canonical base58 text")
    decoded = _base58_decode(text)
    if len(decoded) != decoded_bytes:
        raise ValueError("source identifier has an unexpected decoded width")
    return text


def _public_key(value: object) -> str:
    try:
        return _base58_identifier(value, decoded_bytes=32)
    except ValueError as error:
        raise PumpfunLiveNormalizationError(
            PumpfunLiveNormalizationErrorCode.IDENTIFIER_INVALID
        ) from error


def _signature(value: object) -> str:
    try:
        return _base58_identifier(value, decoded_bytes=64)
    except ValueError as error:
        raise PumpfunLiveNormalizationError(
            PumpfunLiveNormalizationErrorCode.IDENTIFIER_INVALID
        ) from error


def _base58_decode(value: str) -> bytes:
    number = 0
    for character in value:
        number = number * 58 + _BASE58_VALUES[character]
    body = b"" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + body


def _closed_text(value: object) -> str:
    text = _strip_fixed_nul(value)
    if text != text.strip() or any(ord(character) < 32 for character in text):
        raise ValueError("source enum text is malformed")
    return text


def _block_time(value: object) -> tuple[int, int]:
    if isinstance(value, bool):
        raise ValueError("source block_time must be an integer epoch second")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        utc = value.astimezone(UTC)
        if utc.microsecond != 0:
            raise ValueError("source block_time must have second resolution")
        seconds = int(utc.timestamp())
    else:
        raise ValueError("source block_time must be an integer or timezone-aware datetime")
    if not 0 <= seconds <= _MAX_U64:
        raise ValueError("source block_time is outside the unsigned epoch-second contract")
    return seconds, seconds * 1_000_000_000


def _mode(token_program_value: object, cashback_value: object) -> PumpMode:
    token_program = _public_key(token_program_value)
    cashback = _flag(cashback_value)
    if token_program == PUMPFUN_LEGACY_TOKEN_PROGRAM and not cashback:
        return PumpMode.NORMAL
    if token_program == PUMPFUN_TOKEN_2022_PROGRAM:
        return PumpMode.CASHBACK if cashback else PumpMode.TOKEN_2022
    _raise(PumpfunLiveNormalizationErrorCode.UNSUPPORTED_PROGRAM_MODE)


def _curve_state(
    virtual_token_value: object,
    virtual_sol_value: object,
) -> tuple[int, int, int, int, PumpCurveLifecycle]:
    virtual_token = _uint(virtual_token_value)
    virtual_sol = _uint(virtual_sol_value)
    if virtual_token < PUMPFUN_REAL_TOKEN_OFFSET or virtual_sol < PUMPFUN_REAL_SOL_OFFSET:
        raise ValueError("Pump virtual reserves are below the proven fixed offsets")
    real_token = virtual_token - PUMPFUN_REAL_TOKEN_OFFSET
    real_sol = virtual_sol - PUMPFUN_REAL_SOL_OFFSET
    if real_token > PUMPFUN_TOKEN_TOTAL_SUPPLY:
        raise ValueError("Pump real token reserves exceed total supply")
    lifecycle = PumpCurveLifecycle.COMPLETED if real_token == 0 else PumpCurveLifecycle.ACTIVE
    return virtual_token, virtual_sol, real_token, real_sol, lifecycle


def _checked_add(left: int, right: int) -> int:
    value = left + right
    if value > _MAX_U64:
        raise OverflowError("Pump reserve derivation exceeds UInt64")
    return value


def _lifecycle_row(
    *,
    block: int,
    transaction: int,
    event_index: int,
    signature: str,
    mint: str,
    curve: str,
    lifecycle: PumpCurveLifecycle,
    mode: PumpMode,
    virtual_sol: int,
) -> tuple[Any, ...]:
    return (
        block,
        transaction,
        event_index,
        signature,
        mint,
        curve,
        lifecycle.value,
        PUMPFUN_REAL_TOKEN_OFFSET,
        virtual_sol,
        0,
        virtual_sol - PUMPFUN_REAL_SOL_OFFSET,
        PUMPFUN_TOKEN_TOTAL_SUPPLY,
        lifecycle.value,
        mode.value,
    )


def _observation_document(observation: PumpfunNormalizationObservation) -> dict[str, object]:
    if isinstance(observation, SkippedSlotObservation):
        return {
            "block_ordinal": observation.block_ordinal,
            "profile_id": observation.profile_id,
        }
    if isinstance(observation, ExcludedLaunchObservation):
        return {
            "block_ordinal": observation.block_ordinal,
            "event_index": observation.event_index,
            "mint": observation.mint,
            "policy_id": observation.policy_id,
            "reason": observation.reason,
            "signature": observation.signature,
            "transaction_index": observation.transaction_index,
        }
    return {
        "block_ordinal": observation.block_ordinal,
        "completion_event_index": observation.completion_event_index,
        "curve_address": observation.curve_address,
        "migration_event_index": observation.migration_event_index,
        "mint": observation.mint,
        "profile_id": observation.profile_id,
        "signature": observation.signature,
        "terminal_event_index": observation.terminal_event_index,
        "transaction_index": observation.transaction_index,
    }


def _range_document(value: BlockRange) -> dict[str, object]:
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
    }


def _row_contract_error_code(stream: CapabilityStream) -> PumpfunLiveNormalizationErrorCode:
    return {
        CapabilityStream.BLOCK_CLOCK: PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE,
        CapabilityStream.TOKEN_LAUNCH: PumpfunLiveNormalizationErrorCode.LAUNCH_CONTRACT_INVALID,
        CapabilityStream.PUMP_CURVE_TRADE: PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID,
        CapabilityStream.PUMP_CURVE_LIFECYCLE: (
            PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID
        ),
    }[stream]


def _raise(code: PumpfunLiveNormalizationErrorCode) -> NoReturn:
    raise PumpfunLiveNormalizationError(code)


__all__ = [
    "PUMPFUN_CANONICAL_SOL_ASSET",
    "PUMPFUN_CURVE_TRADE_NORMALIZER_PROFILE_ID",
    "PUMPFUN_INITIAL_REAL_SOL_RESERVES",
    "PUMPFUN_INITIAL_REAL_TOKEN_RESERVES",
    "PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES",
    "PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES",
    "PUMPFUN_LAUNCH_SOL_SOURCE_ASSET",
    "PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID",
    "PUMPFUN_LEGACY_TOKEN_PROGRAM",
    "PUMPFUN_LIVE_NORMALIZER_PROFILE_ID",
    "PUMPFUN_MIGRATION_MINT_AMOUNT",
    "PUMPFUN_MIGRATION_STATE_PROFILE_ID",
    "PUMPFUN_POOL_MIGRATION_FEE",
    "PUMPFUN_REAL_SOL_OFFSET",
    "PUMPFUN_REAL_TOKEN_OFFSET",
    "PUMPFUN_STATIC_CURVE_STATE_PROFILE_ID",
    "PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID",
    "PUMPFUN_TOKEN_2022_PROGRAM",
    "PUMPFUN_TOKEN_TOTAL_SUPPLY",
    "PUMPFUN_TRADE_SOL_SOURCE_ASSET",
    "SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID",
    "DerivedLifecycleGroupObservation",
    "ExcludedLaunchObservation",
    "PumpfunLiveNormalizationError",
    "PumpfunLiveNormalizationErrorCode",
    "PumpfunLiveNormalizer",
    "PumpfunNormalizationObservation",
    "PumpfunNormalizationObservationSink",
    "PumpfunNormalizationSession",
    "PumpfunNormalizationSummary",
    "PumpfunNormalizedBatch",
    "SkippedSlotObservation",
]
