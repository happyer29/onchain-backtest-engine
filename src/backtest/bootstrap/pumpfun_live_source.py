"""Composition of the audited Pump.fun source profile and pure normalizer.

The ClickHouse adapter owns fixed SQL, the Pump plugin owns row semantics, and
this composition layer binds them into the capabilities exposed to application
use cases.  No endpoint or credential enters this module or its identities.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final, NoReturn

from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PumpfunIndexerV1Profile,
    registered_pumpfun_indexer_v1_profile,
)
from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
    clickhouse_capability_mapping_digest,
)
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceAdapterError, SourceBatch
from backtest.application.models import (
    BoundedSourceEvidenceReceipt,
    BoundedSourceEvidenceRequest,
    CapabilityCutEvidence,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    EvidenceStatus,
    ExtractionRequest,
    build_bounded_source_evidence_receipt,
)
from backtest.application.ports.source import IndexedBatch
from backtest.application.source_evidence import (
    MAYHEM_EXCLUSION_REASON,
    LaunchUniverseEvidence,
    SkippedSlotSentinelEvidence,
    TerminalLifecycleOrderingEvidence,
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
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange
from backtest.plugins.protocols.pumpfun.live_normalizer import (
    PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES,
    PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES,
    PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
    PUMPFUN_REAL_TOKEN_OFFSET,
    PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
    DerivedLifecycleGroupObservation,
    ExcludedLaunchObservation,
    PumpfunLiveNormalizationError,
    PumpfunLiveNormalizationErrorCode,
    PumpfunLiveNormalizer,
    PumpfunNormalizationObservation,
    PumpfunNormalizationSummary,
    SkippedSlotObservation,
)
from backtest.plugins.protocols.pumpfun.model import (
    PUMP_STATIC_PROGRAM_CONTRACT_V1,
    PumpFeeProfile,
)

PUMPFUN_LIVE_FEE_PROFILE_ID: Final = "pump-static-95-30-v1"
PUMPFUN_LIVE_FEE_EFFECTIVE_FROM_UNIX_S: Final = 0
PUMPFUN_LIVE_FEE_EFFECTIVE_UNTIL_UNIX_S: Final = 4_102_444_800
PUMPFUN_BUNDLED_BUY_PLACEHOLDER_POLICY_ID: Final = (
    "pumpfun-same-signature-mint-bundled-buy-placeholder-v1"
)
PUMPFUN_EVENT_CLOCK_VALIDATION_POLICY_ID: Final = "solana-full-block-clock-cross-check-v1"
PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS: Final = 4_096

_NORMALIZED_PROTOCOL_VERSION: Final[Mapping[CapabilityStream, str]] = {
    CapabilityStream.BLOCK_CLOCK: "solana-block-clock-v1",
    CapabilityStream.TOKEN_LAUNCH: PUMP_STATIC_PROGRAM_CONTRACT_V1,
    CapabilityStream.PUMP_CURVE_TRADE: PUMP_STATIC_PROGRAM_CONTRACT_V1,
    CapabilityStream.PUMP_CURVE_LIFECYCLE: PUMP_STATIC_PROGRAM_CONTRACT_V1,
}
_NORMALIZED_SCHEMA_VERSION: Final[Mapping[CapabilityStream, str]] = {
    CapabilityStream.BLOCK_CLOCK: "solana-block-clock-normalized-v1",
    CapabilityStream.TOKEN_LAUNCH: "pumpfun-token-launch-normalized-v2",
    CapabilityStream.PUMP_CURVE_TRADE: "pumpfun-curve-trade-normalized-v2",
    CapabilityStream.PUMP_CURVE_LIFECYCLE: "pumpfun-curve-lifecycle-normalized-v2",
}
_TOTAL_KEY: Final[Mapping[CapabilityStream, tuple[str, ...]]] = {
    CapabilityStream.BLOCK_CLOCK: ("block_ordinal",),
    CapabilityStream.TOKEN_LAUNCH: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        "mint",
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        "mint",
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        "mint",
    ),
}
_STREAM_ORDER: Final = (
    CapabilityStream.BLOCK_CLOCK,
    CapabilityStream.TOKEN_LAUNCH,
    CapabilityStream.PUMP_CURVE_TRADE,
    CapabilityStream.PUMP_CURVE_LIFECYCLE,
)
_REQUIRED_PROOFS: Final[Mapping[CapabilityStream, tuple[str, ...]]] = {
    CapabilityStream.BLOCK_CLOCK: (
        "successful_transactions_included",
        "failed_transactions_included",
        "vote_transactions_included",
        "skipped_blocks_distinguished",
        "block_time_second_resolution",
        "block_time_monotone",
    ),
    CapabilityStream.TOKEN_LAUNCH: (
        "global_zero_based_transaction_index",
        "creation_fields_immutable",
        "bundled_instruction_order",
        "launch_transaction_success_exact",
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "global_zero_based_transaction_index",
        "curve_transitions_complete",
        "fee_component_rounding_exact",
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "global_zero_based_transaction_index",
        "lifecycle_complete",
    ),
}


class PumpfunLiveSourceErrorCode(StrEnum):
    """Stable, secret-free failures at the live source composition boundary."""

    PROFILE_INVALID = "PROFILE_INVALID"
    REQUEST_IDENTITY_MISMATCH = "REQUEST_IDENTITY_MISMATCH"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    INCOMPLETE_BLOCK_RANGE = "INCOMPLETE_BLOCK_RANGE"
    TRANSACTION_CLOCK_MISMATCH = "TRANSACTION_CLOCK_MISMATCH"
    BUNDLED_BUY_CONTRACT_MISMATCH = "BUNDLED_BUY_CONTRACT_MISMATCH"
    CURVE_TRANSITION_MISMATCH = "CURVE_TRANSITION_MISMATCH"
    LIFECYCLE_CONTRACT_MISMATCH = "LIFECYCLE_CONTRACT_MISMATCH"


class PumpfunLiveSourceError(RuntimeError):
    """Typed rejection that never carries a driver exception or source row."""

    def __init__(self, code: PumpfunLiveSourceErrorCode) -> None:
        if not isinstance(code, PumpfunLiveSourceErrorCode):
            raise TypeError("code must be a PumpfunLiveSourceErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class PumpfunLiveSourceComposition:
    """Immutable wiring for one validated four-stream physical source profile."""

    raw_capabilities: tuple[ClickHouseCapability, ...]
    metadata_capabilities: tuple[CapabilityDescriptor, ...]
    projection_capabilities: tuple[ClickHouseCapability, ...]
    query_policy: ClickHouseQueryPolicy
    normalizer: PumpfunLiveNormalizer
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    normalizer_digest: ContentDigest
    _profile: PumpfunIndexerV1Profile

    def scan(
        self,
        reader: ClickHouseSourceReader,
        request: ExtractionRequest,
    ) -> Iterator[IndexedBatch]:
        """Run the fixed physical query and stream its normalized logical batches."""

        try:
            capability = self._raw_capability(request.shard.capability_id)
            descriptor = self._metadata_descriptor(request.shard.capability_id)
            if request.shard.columns != descriptor.columns:
                _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
            if capability.descriptor.stream is CapabilityStream.TOKEN_LAUNCH and not _is_contained(
                request.shard.block_range, request.decision_range
            ):
                _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
            query = self._profile.build_query(
                stream=capability.descriptor.stream,
                database=capability.database,
                block_range=request.shard.block_range,
                decision_range=request.decision_range,
                policy=self.query_policy,
            )
            session = self.normalizer.begin(
                stream=capability.descriptor.stream,
                capability_id=capability.descriptor.capability_id,
                covered_range=request.shard.block_range,
            )
            batch_seen = False
            for batch in reader.scan_pumpfun_indexer_v1(request, query):
                batch_seen = True
                _validate_raw_batch(
                    batch,
                    capability_id=capability.descriptor.capability_id,
                    covered_range=request.shard.block_range,
                    columns=self.normalizer.raw_columns(capability.descriptor.stream),
                    query_fingerprint=query.fingerprint,
                )
                yield session.normalize(batch)
            if batch_seen:
                session.finish()
                return
            empty = SourceBatch(
                capability_id=capability.descriptor.capability_id,
                covered_range=request.shard.block_range,
                columns=self.normalizer.raw_columns(capability.descriptor.stream),
                rows=(),
                query_fingerprint=query.fingerprint,
            )
            normalized = session.normalize(empty)
            session.finish()
            yield normalized
        except PumpfunLiveSourceError:
            raise
        except PumpfunLiveNormalizationError as error:
            _raise_normalization(error)
        except SourceAdapterError:
            _fail(PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED)
        except (TypeError, ValueError):
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)

    def inspect_bounded_evidence(
        self,
        reader: ClickHouseSourceReader,
        request: BoundedSourceEvidenceRequest,
        *,
        projector_digest: ContentDigest,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        """Prove one immutable bounded cut through four fixed streaming queries."""

        self._validate_evidence_request(request, projector_digest)
        evidence = _EvidenceAccumulator(request)
        try:
            for stream in _STREAM_ORDER:
                capability = self._raw_capability_for_stream(stream)
                selected_range = (
                    request.decision_range
                    if stream is CapabilityStream.TOKEN_LAUNCH
                    else request.block_range
                )
                for subrange in _shards(
                    selected_range,
                    maximum_span=min(
                        PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS,
                        self.query_policy.evidence_max_block_span,
                    ),
                ):
                    query = self._profile.build_query(
                        stream=stream,
                        database=capability.database,
                        block_range=subrange,
                        decision_range=request.decision_range,
                        policy=self.query_policy,
                    )
                    session = self.normalizer.begin(
                        stream=stream,
                        capability_id=capability.descriptor.capability_id,
                        covered_range=subrange,
                        observation_sink=evidence.observe,
                    )
                    for raw_batch in reader.stream_pumpfun_indexer_v1_evidence(
                        request,
                        capability_id=capability.descriptor.capability_id,
                        block_range=subrange,
                        query=query,
                    ):
                        _validate_raw_batch(
                            raw_batch,
                            capability_id=capability.descriptor.capability_id,
                            covered_range=subrange,
                            columns=self.normalizer.raw_columns(stream),
                            query_fingerprint=query.fingerprint,
                        )
                        normalized = session.normalize(raw_batch)
                        evidence.consume(stream, raw_batch, normalized)
                    summary = session.finish()
                    evidence.add_summary(stream, subrange, query.fingerprint, summary)
            evidence.finish()
        except PumpfunLiveSourceError:
            raise
        except PumpfunLiveNormalizationError as error:
            _raise_normalization(error)
        except SourceAdapterError:
            _fail(PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED)
        except (OverflowError, TypeError, ValueError):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        return self._build_receipts(request, projector_digest, evidence)

    def _build_receipts(
        self,
        request: BoundedSourceEvidenceRequest,
        projector_digest: ContentDigest,
        evidence: _EvidenceAccumulator,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        result_digest = evidence.result_digest(
            capability_mapping_digest=self.capability_mapping_digest,
            query_template_digest=self.query_template_digest,
            normalizer_digest=self.normalizer_digest,
            projector_digest=projector_digest,
        )
        upstream_revision = f"pumpfun-live-cut-v2:{result_digest.hex}"
        query_fingerprints = tuple(sorted(evidence.query_fingerprints, key=lambda item: item.hex))
        launch = LaunchUniverseEvidence(
            decision_range=request.decision_range,
            policy_id=PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
            classified_count=evidence.launch_classified_count,
            eligible_count=evidence.launch_eligible_count,
            excluded_count=evidence.launch_excluded_count,
            ordered_exclusion_digest=evidence.exclusion_digest,
            exclusion_reason=MAYHEM_EXCLUSION_REASON,
        )
        sentinel = SkippedSlotSentinelEvidence(
            profile_id=SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
            recognized_count=evidence.sentinel_count,
            ordered_sentinel_digest=evidence.sentinel_digest,
        )
        lifecycle = TerminalLifecycleOrderingEvidence(
            profile_id=PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
            derived_group_count=evidence.derived_lifecycle_count,
            ordered_group_digest=evidence.lifecycle_digest,
        )
        receipts: list[BoundedSourceEvidenceReceipt] = []
        for stream in _STREAM_ORDER:
            descriptor = self._metadata_descriptor_for_stream(stream)
            cut = CapabilityCutEvidence(
                capability_id=descriptor.capability_id,
                block_range=request.block_range,
                snapshot_cut_to_block=request.block_range.to_block_ordinal,
                chain_finality=ChainFinality.FINALIZED,
                ingestion_watermark_to_block=request.block_range.to_block_ordinal,
                completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
                consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
                upstream_revision=upstream_revision,
            )
            receipts.append(
                build_bounded_source_evidence_receipt(
                    source_id=request.source_id,
                    capability_id=descriptor.capability_id,
                    protocol_version=descriptor.protocol_version,
                    capability_schema_version=descriptor.schema_version,
                    capability_mapping_digest=self.capability_mapping_digest,
                    query_template_digest=self.query_template_digest,
                    projector_digest=projector_digest,
                    normalizer_digest=self.normalizer_digest,
                    cut_evidence=cut,
                    decision_range=request.decision_range,
                    proofs=_proven_proofs(stream),
                    source_fidelity=_proven_source_fidelity(stream),
                    query_fingerprints=query_fingerprints,
                    result_digest=result_digest,
                    observed_rows=evidence.raw_rows[stream],
                    launch_universe=(launch if stream is CapabilityStream.TOKEN_LAUNCH else None),
                    skipped_slot_sentinel=(
                        sentinel if stream is CapabilityStream.BLOCK_CLOCK else None
                    ),
                    terminal_lifecycle_ordering=(
                        lifecycle if stream is CapabilityStream.PUMP_CURVE_LIFECYCLE else None
                    ),
                )
            )
        return tuple(sorted(receipts, key=lambda item: item.capability_id.value))

    def _validate_evidence_request(
        self,
        request: BoundedSourceEvidenceRequest,
        projector_digest: ContentDigest,
    ) -> None:
        # Bounded proof requests must carry the exact installed projector config digest.
        if not isinstance(projector_digest, ContentDigest):
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
        network_ids = {item.network_id for item in self.raw_capabilities}
        position_ids = {item.position_schema_id for item in self.raw_capabilities}
        if (
            # The source capability set must identify one immutable network and position schema.
            len(network_ids) != 1
            or len(position_ids) != 1
            or request.block_range.network_id != next(iter(network_ids))
            or request.block_range.position_schema_id != next(iter(position_ids))
            or request.capability_mapping_digest != self.capability_mapping_digest
            # Both physical query and projection operands are checked before remote evidence reads.
            or request.query_template_digest != self.query_template_digest
            or request.projector_digest != projector_digest
            or request.normalizer_digest != self.normalizer_digest
            or request.launch_universe_policy_id != self.normalizer.launch_universe_policy_id
            or request.skipped_slot_sentinel_policy_id != SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID
            # Sentinel and terminal normalization policies remain separately pinned.
            or request.terminal_lifecycle_ordering_policy_id
            != PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID
        ):
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)

    def _raw_capability(self, capability_id: CapabilityId) -> ClickHouseCapability:
        for capability in self.raw_capabilities:
            if capability.descriptor.capability_id == capability_id:
                return capability
        _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)

    def _raw_capability_for_stream(self, stream: CapabilityStream) -> ClickHouseCapability:
        for capability in self.raw_capabilities:
            if capability.descriptor.stream is stream:
                return capability
        _fail(PumpfunLiveSourceErrorCode.PROFILE_INVALID)

    def _metadata_descriptor(self, capability_id: CapabilityId) -> CapabilityDescriptor:
        for descriptor in self.metadata_capabilities:
            if descriptor.capability_id == capability_id:
                return descriptor
        _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)

    def _metadata_descriptor_for_stream(self, stream: CapabilityStream) -> CapabilityDescriptor:
        for descriptor in self.metadata_capabilities:
            if descriptor.stream is stream:
                return descriptor
        _fail(PumpfunLiveSourceErrorCode.PROFILE_INVALID)


def build_pumpfun_live_source_composition(
    raw_capabilities: tuple[ClickHouseCapability, ...],
    *,
    query_policy: ClickHouseQueryPolicy | None = None,
) -> PumpfunLiveSourceComposition:
    """Build immutable live-source wiring only for the installed audited profile."""

    policy = query_policy or ClickHouseQueryPolicy()
    try:
        profile = registered_pumpfun_indexer_v1_profile(raw_capabilities)
        if profile is None:
            _fail(PumpfunLiveSourceErrorCode.PROFILE_INVALID)
        normalizer = PumpfunLiveNormalizer(
            PumpFeeProfile.static_95_30(
                profile_id=PUMPFUN_LIVE_FEE_PROFILE_ID,
                effective_from_unix_s=PUMPFUN_LIVE_FEE_EFFECTIVE_FROM_UNIX_S,
                effective_until_unix_s=PUMPFUN_LIVE_FEE_EFFECTIVE_UNTIL_UNIX_S,
            )
        )
        for stream in _STREAM_ORDER:
            if profile.output_columns(stream) != normalizer.raw_columns(stream):
                _fail(PumpfunLiveSourceErrorCode.PROFILE_INVALID)
        metadata = tuple(
            sorted(
                (
                    _normalized_descriptor(item, normalizer, projection=False)
                    for item in raw_capabilities
                ),
                key=lambda item: item.capability_id.value,
            )
        )
        projection = tuple(
            sorted(
                (_projection_capability(item, normalizer) for item in raw_capabilities),
                key=lambda item: item.descriptor.capability_id.value,
            )
        )
        mapping_digest = clickhouse_capability_mapping_digest(raw_capabilities)
        normalizer_digest = domain_digest(
            "backtest.pumpfun-live-source-normalization.v1",
            {
                "bundled_buy_policy_id": PUMPFUN_BUNDLED_BUY_PLACEHOLDER_POLICY_ID,
                "event_clock_policy_id": PUMPFUN_EVENT_CLOCK_VALIDATION_POLICY_ID,
                "normalizer_config_digest": normalizer.config_digest.hex,
            },
        )
        return PumpfunLiveSourceComposition(
            raw_capabilities=tuple(raw_capabilities),
            metadata_capabilities=metadata,
            projection_capabilities=projection,
            query_policy=policy,
            normalizer=normalizer,
            capability_mapping_digest=mapping_digest,
            query_template_digest=profile.template_digest,
            normalizer_digest=normalizer_digest,
            _profile=profile,
        )
    except PumpfunLiveSourceError:
        raise
    except (TypeError, ValueError):
        _fail(PumpfunLiveSourceErrorCode.PROFILE_INVALID)


def _normalized_descriptor(
    raw: ClickHouseCapability,
    normalizer: PumpfunLiveNormalizer,
    *,
    projection: bool,
) -> CapabilityDescriptor:
    stream = raw.descriptor.stream
    columns = normalizer.output_columns(stream)
    fidelity = _projection_source_fidelity(stream) if projection else _unknown_source_fidelity()
    return CapabilityDescriptor(
        capability_id=raw.descriptor.capability_id,
        protocol="solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun",
        protocol_version=_NORMALIZED_PROTOCOL_VERSION[stream],
        schema_version=_NORMALIZED_SCHEMA_VERSION[stream],
        stream=stream,
        columns=columns,
        mandatory_columns=columns,
        fidelity=fidelity,
        proofs=CapabilityProofs(),
        total_key=_TOTAL_KEY[stream],
        keyset_key_is_proven=True,
    )


def _projection_capability(
    raw: ClickHouseCapability,
    normalizer: PumpfunLiveNormalizer,
) -> ClickHouseCapability:
    descriptor = _normalized_descriptor(raw, normalizer, projection=True)
    return ClickHouseCapability(
        descriptor=descriptor,
        network_id=raw.network_id,
        position_schema_id=raw.position_schema_id,
        database=raw.database,
        table=raw.table,
        logical_to_physical={column: column for column in descriptor.columns},
    )


def _unknown_source_fidelity() -> SourceFidelity:
    return SourceFidelity(
        identity=IdentityFidelity.UNKNOWN,
        ordering=OrderingFidelity.UNKNOWN,
        state=StateFidelity.NONE,
        fees=FeesFidelity.UNKNOWN,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )


def _projection_source_fidelity(stream: CapabilityStream) -> SourceFidelity:
    if stream is CapabilityStream.BLOCK_CLOCK:
        ordering = OrderingFidelity.TRANSACTION_EXACT
        state = StateFidelity.NONE
        fees = FeesFidelity.UNKNOWN
    elif stream is CapabilityStream.PUMP_CURVE_TRADE:
        ordering = OrderingFidelity.INSTRUCTION_EXACT
        state = StateFidelity.AFTER_ONLY
        fees = FeesFidelity.COMPONENTS
    else:
        ordering = OrderingFidelity.INSTRUCTION_EXACT
        state = StateFidelity.AFTER_ONLY
        fees = FeesFidelity.UNKNOWN
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=ordering,
        state=state,
        fees=fees,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )


def _proven_source_fidelity(stream: CapabilityStream) -> SourceFidelity:
    static = _projection_source_fidelity(stream)
    return SourceFidelity(
        identity=static.identity,
        ordering=static.ordering,
        state=static.state,
        fees=static.fees,
        chain_finality=ChainFinality.FINALIZED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
    )


def _proven_proofs(stream: CapabilityStream) -> CapabilityProofs:
    values = dict.fromkeys(_REQUIRED_PROOFS[stream], EvidenceStatus.PROVEN)
    return CapabilityProofs(**values)


def _shards(value: BlockRange, *, maximum_span: int) -> Iterator[BlockRange]:
    start = value.from_block_ordinal
    while start < value.to_block_ordinal:
        end = min(start + maximum_span, value.to_block_ordinal)
        yield BlockRange(value.network_id, value.position_schema_id, start, end)
        start = end


@dataclass(slots=True)
class _LaunchState:
    signature: str
    mint: str
    creator: str
    creation_user: str
    curve: str
    token_program: str
    cashback_enabled: int
    creation_position: tuple[int, int, int]
    virtual_token: int = PUMPFUN_INITIAL_VIRTUAL_TOKEN_RESERVES
    virtual_sol: int = PUMPFUN_INITIAL_VIRTUAL_SOL_RESERVES
    last_trade_position: tuple[int, int, int] | None = None
    terminal: tuple[int, int, int, str, int] | None = None
    completion_position: tuple[int, int, int] | None = None
    migrated: bool = False


class _EvidenceAccumulator:
    """Streaming cross-capability checks with block- and launch-bounded memory."""

    __slots__ = (
        "_clock",
        "_exclusions",
        "_last_clock_block",
        "_last_clock_time",
        # Launch classification and lifecycle groups retain independent bounded evidence state.
        "_launch_policy",
        "_launches",
        "_lifecycle_groups",
        "_sentinels",
        "_summaries",
        # Per-shard observation summaries are distinct from whole-cut counters.
        "_summary_excluded_launches",
        "_summary_lifecycle_groups",
        "_summary_sentinels",
        "derived_lifecycle_count",
        "launch_classified_count",
        # Eligible and excluded launch counts cannot be inferred from canonical event counts.
        "launch_eligible_count",
        "launch_excluded_count",
        "query_fingerprints",
        "raw_rows",
        "sentinel_count",
        # The slot sentinel counter records coverage without fabricating a clock boundary.
    )

    def __init__(self, request: BoundedSourceEvidenceRequest) -> None:
        # Classification follows the explicitly requested family; no proof is promoted here.
        self._launch_policy = request.launch_universe_policy_id
        self._clock: dict[int, tuple[int, int]] = {}
        self._launches: dict[str, _LaunchState] = {}
        self._last_clock_block: int | None = None
        self._last_clock_time: int | None = None
        # Exclusion framing binds the strategy-specific universe policy and initialization range.
        self._exclusions = _OrderedDigest(
            "backtest.pumpfun-live-source-exclusions.v1",
            {
                "policy_id": self._launch_policy,
                "range": _range_document(
                    # Copy initialization may precede decisions; Sniping keeps its original
                    # decision-only range.
                    request.decision_range
                    if request.copy_selection is None
                    else request.copy_selection.history_range
                ),
            },
            # The completed exclusion operand document determines deterministic digest framing.
        )
        self._sentinels = _OrderedDigest(
            "backtest.pumpfun-live-source-sentinels.v1",
            {
                "profile_id": SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
                # Sentinel coverage is measured over the complete declared extraction range.
                "range": _range_document(request.block_range),
            },
        )
        self._lifecycle_groups = _OrderedDigest(
            "backtest.pumpfun-live-source-lifecycle-groups.v1",
            # Terminal group evidence has its own profile and ordered digest.
            {
                "profile_id": PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
                "range": _range_document(request.block_range),
            },
        )
        # Per-shard summaries and query fingerprints remain bounded preparation evidence.
        self._summaries: list[dict[str, object]] = []
        self.query_fingerprints: set[ContentDigest] = set()
        self.raw_rows = dict.fromkeys(_STREAM_ORDER, 0)
        self.launch_classified_count = 0
        self.launch_eligible_count = 0
        # Known exclusions and skipped slots never appear as execution targets.
        self.launch_excluded_count = 0
        self.sentinel_count = 0
        self.derived_lifecycle_count = 0
        self._summary_excluded_launches = 0
        self._summary_sentinels = 0
        # Shard counters allow deterministic reconciliation against whole-cut observations.
        self._summary_lifecycle_groups = 0

    def observe(self, observation: PumpfunNormalizationObservation) -> None:
        if isinstance(observation, SkippedSlotObservation):
            if observation.profile_id != SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID:
                _fail(PumpfunLiveSourceErrorCode.INCOMPLETE_BLOCK_RANGE)
            # A known skipped slot contributes only to coverage evidence.
            self._sentinels.update(
                (observation.block_ordinal,),
                {
                    "block_ordinal": observation.block_ordinal,
                    "profile_id": observation.profile_id,
                    # Sentinel identity includes its pinned profile, not a synthetic transaction
                    # count.
                },
            )
            self.sentinel_count += 1
            return
        if isinstance(observation, ExcludedLaunchObservation):
            # Excluded launches must use the selected immutable universe policy.
            if (
                observation.policy_id != self._launch_policy
                or observation.reason != MAYHEM_EXCLUSION_REASON
            ):
                _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
            # Hash every exclusion in exact source occurrence order.
            self._exclusions.update(
                (
                    observation.block_ordinal,
                    observation.transaction_index,
                    observation.event_index,
                    # Signature and mint disambiguate exclusions within shared transaction
                    # coordinates.
                    observation.signature,
                    observation.mint,
                ),
                {
                    "block_ordinal": observation.block_ordinal,
                    # Preserve exclusion coordinates and classification reason for later binding
                    # checks.
                    "event_index": observation.event_index,
                    "mint": observation.mint,
                    "policy_id": observation.policy_id,
                    "reason": observation.reason,
                    "signature": observation.signature,
                    # The original signature remains provenance and never becomes an execution
                    # signal.
                    "transaction_index": observation.transaction_index,
                },
            )
            self.launch_excluded_count += 1
            return
        # Only the recognized terminal normalization observation may reach lifecycle evidence.
        if not isinstance(observation, DerivedLifecycleGroupObservation):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        if observation.profile_id != PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID:
            _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
        self._lifecycle_groups.update(
            # Terminal occurrence identity starts with the same atomic transaction coordinates.
            (
                observation.block_ordinal,
                observation.transaction_index,
                observation.terminal_event_index,
                observation.signature,
                # Mint identity prevents mixing terminal events from separate curves.
                observation.mint,
            ),
            {
                "block_ordinal": observation.block_ordinal,
                "completion_event_index": observation.completion_event_index,
                # Completion and migration indices remain explicitly ordered after the terminal
                # trade.
                "curve_address": observation.curve_address,
                "migration_event_index": observation.migration_event_index,
                "mint": observation.mint,
                "profile_id": observation.profile_id,
                "signature": observation.signature,
                # Terminal trade index and transaction coordinate allow reconstruction of atomic
                # ordering.
                "terminal_event_index": observation.terminal_event_index,
                "transaction_index": observation.transaction_index,
            },
        )
        self.derived_lifecycle_count += 1

    def consume(
        self,
        stream: CapabilityStream,
        raw_batch: IndexedBatch,
        normalized_batch: IndexedBatch,
    ) -> None:
        if stream is CapabilityStream.BLOCK_CLOCK:
            self._consume_clock(normalized_batch)
            return
        self._cross_check_clock(raw_batch)
        if stream is CapabilityStream.TOKEN_LAUNCH:
            self._consume_launches(raw_batch)
        elif stream is CapabilityStream.PUMP_CURVE_TRADE:
            self._consume_trades(raw_batch)
        elif stream is CapabilityStream.PUMP_CURVE_LIFECYCLE:
            self._consume_lifecycle(raw_batch, normalized_batch)

    def add_summary(
        self,
        stream: CapabilityStream,
        block_range: BlockRange,
        query_fingerprint: ContentDigest,
        summary: PumpfunNormalizationSummary,
    ) -> None:
        if summary.stream is not stream:
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        self.query_fingerprints.add(query_fingerprint)
        self.raw_rows[stream] += summary.raw_row_count
        self.launch_classified_count += summary.launch_classified_count
        self.launch_eligible_count += summary.launch_eligible_count
        self._summary_excluded_launches += summary.launch_excluded_count
        self._summary_sentinels += summary.recognized_sentinel_count
        self._summary_lifecycle_groups += summary.derived_lifecycle_group_count
        self._summaries.append(
            {
                "derived_lifecycle_group_count": summary.derived_lifecycle_group_count,
                "launch_classified_count": summary.launch_classified_count,
                "launch_eligible_count": summary.launch_eligible_count,
                "launch_excluded_count": summary.launch_excluded_count,
                "normalized_row_count": summary.normalized_row_count,
                "normalized_stream_digest": summary.normalized_stream_digest.hex,
                "ordered_exclusion_digest": summary.ordered_exclusion_digest.hex,
                "ordered_lifecycle_group_digest": summary.ordered_lifecycle_group_digest.hex,
                "ordered_sentinel_digest": summary.ordered_sentinel_digest.hex,
                "query_fingerprint": query_fingerprint.hex,
                "range": _range_document(block_range),
                "raw_row_count": summary.raw_row_count,
                "recognized_sentinel_count": summary.recognized_sentinel_count,
                "stream": stream.value,
            }
        )

    def finish(self) -> None:
        if (
            self.launch_excluded_count != self._summary_excluded_launches
            or self.sentinel_count != self._summary_sentinels
            or self.derived_lifecycle_count != self._summary_lifecycle_groups
        ):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        if self.launch_classified_count != (
            self.launch_eligible_count + self.launch_excluded_count
        ):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        if self.launch_eligible_count != len(self._launches):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        for launch in self._launches.values():
            if launch.terminal is not None and launch.completion_position is None:
                _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)

    @property
    def exclusion_digest(self) -> ContentDigest:
        return self._exclusions.digest()

    @property
    def sentinel_digest(self) -> ContentDigest:
        return self._sentinels.digest()

    @property
    def lifecycle_digest(self) -> ContentDigest:
        return self._lifecycle_groups.digest()

    def result_digest(
        self,
        *,
        capability_mapping_digest: ContentDigest,
        query_template_digest: ContentDigest,
        normalizer_digest: ContentDigest,
        projector_digest: ContentDigest,
    ) -> ContentDigest:
        return domain_digest(
            "backtest.pumpfun-live-source-evidence-result.v2",
            {
                "bundled_buy_policy_id": PUMPFUN_BUNDLED_BUY_PLACEHOLDER_POLICY_ID,
                "capability_mapping_digest": capability_mapping_digest.hex,
                "event_clock_policy_id": PUMPFUN_EVENT_CLOCK_VALIDATION_POLICY_ID,
                "exclusion_digest": self.exclusion_digest.hex,
                "lifecycle_digest": self.lifecycle_digest.hex,
                "normalizer_digest": normalizer_digest.hex,
                "projector_digest": projector_digest.hex,
                "query_template_digest": query_template_digest.hex,
                "sentinel_digest": self.sentinel_digest.hex,
                "summaries": self._summaries,
            },
        )

    def _consume_clock(self, batch: IndexedBatch) -> None:
        indexes = _indexes(batch.columns)
        for row in batch.rows:
            block = _integer(row[indexes["block_ordinal"]])
            block_time = _integer(row[indexes["block_time"]])
            transactions = _integer(row[indexes["transaction_count"]])
            if (
                block in self._clock
                or (self._last_clock_block is not None and block <= self._last_clock_block)
                or (self._last_clock_time is not None and block_time < self._last_clock_time)
            ):
                _fail(PumpfunLiveSourceErrorCode.INCOMPLETE_BLOCK_RANGE)
            self._clock[block] = transactions, block_time
            self._last_clock_block = block
            self._last_clock_time = block_time

    def _cross_check_clock(self, batch: IndexedBatch) -> None:
        indexes = _indexes(batch.columns)
        for row in batch.rows:
            block = _integer(row[indexes["block_ordinal"]])
            transaction = _integer(row[indexes["transaction_index"]])
            expected = self._clock.get(block)
            if expected is None:
                _fail(PumpfunLiveSourceErrorCode.TRANSACTION_CLOCK_MISMATCH)
            transaction_count, block_time = expected
            if (
                transaction >= transaction_count
                or _datetime_ns(row[indexes["block_time"]]) != block_time
            ):
                _fail(PumpfunLiveSourceErrorCode.TRANSACTION_CLOCK_MISMATCH)

    def _consume_launches(self, batch: IndexedBatch) -> None:
        indexes = _indexes(batch.columns)
        for row in batch.rows:
            if _integer(row[indexes["mayhem_mode"]]) == 1:
                continue
            launch = _LaunchState(
                signature=_text(row[indexes["signature"]]),
                mint=_text(row[indexes["mint"]]),
                creator=_text(row[indexes["creator"]]),
                creation_user=_text(row[indexes["creation_user"]]),
                curve=_text(row[indexes["curve_address"]]),
                token_program=_text(row[indexes["token_program"]]),
                cashback_enabled=_integer(row[indexes["cashback_enabled"]]),
                creation_position=(
                    _integer(row[indexes["block_ordinal"]]),
                    _integer(row[indexes["transaction_index"]]),
                    _integer(row[indexes["raw_instruction_index"]]),
                ),
            )
            if launch.mint in self._launches:
                _fail(PumpfunLiveSourceErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH)
            self._launches[launch.mint] = launch

    def _consume_trades(self, batch: IndexedBatch) -> None:
        indexes = _indexes(batch.columns)
        for row in batch.rows:
            mint = _text(row[indexes["mint"]])
            launch = self._launches.get(mint)
            if launch is None or not _trade_creation_matches(row, indexes, launch):
                _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
            position = (
                _integer(row[indexes["block_ordinal"]]),
                _integer(row[indexes["transaction_index"]]),
                _integer(row[indexes["raw_instruction_index"]]),
            )
            if position <= launch.creation_position or (
                launch.last_trade_position is not None and position <= launch.last_trade_position
            ):
                _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
            if launch.terminal is not None:
                _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
            direction = _text(row[indexes["direction"]])
            base = _integer(row[indexes["base_amount_atomic"]])
            quote = _integer(row[indexes["quote_amount_atomic"]])
            virtual_token = _integer(row[indexes["virtual_token_reserves_after_atomic"]])
            virtual_sol = _integer(row[indexes["virtual_sol_reserves_after_lamports"]])
            if direction == "buy":
                expected_token = launch.virtual_token - base
                expected_sol = launch.virtual_sol + quote
            elif direction == "sell":
                expected_token = launch.virtual_token + base
                expected_sol = launch.virtual_sol - quote
            else:
                _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
            if expected_token != virtual_token or expected_sol != virtual_sol:
                _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
            signature = _text(row[indexes["signature"]])
            if signature == launch.signature and (
                position[:2] != launch.creation_position[:2]
                or position[2] <= launch.creation_position[2]
            ):
                _fail(PumpfunLiveSourceErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH)
            launch.virtual_token = virtual_token
            launch.virtual_sol = virtual_sol
            launch.last_trade_position = position
            if virtual_token == PUMPFUN_REAL_TOKEN_OFFSET:
                if direction != "buy":
                    _fail(PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH)
                launch.terminal = (*position, signature, virtual_sol)

    def _consume_lifecycle(self, raw: IndexedBatch, normalized: IndexedBatch) -> None:
        raw_indexes = _indexes(raw.columns)
        output_indexes = _indexes(normalized.columns)
        if len(raw.rows) != len(normalized.rows):
            _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
        for raw_row, output_row in zip(raw.rows, normalized.rows, strict=True):
            mint = _text(raw_row[raw_indexes["mint"]])
            launch = self._launches.get(mint)
            if launch is None or not _lifecycle_creation_matches(raw_row, raw_indexes, launch):
                _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
            kind = _text(output_row[output_indexes["lifecycle_kind"]])
            position = (
                _integer(output_row[output_indexes["block_ordinal"]]),
                _integer(output_row[output_indexes["transaction_index"]]),
                _integer(output_row[output_indexes["event_index"]]),
            )
            signature = _text(output_row[output_indexes["signature"]])
            curve = _text(output_row[output_indexes["venue"]])
            if curve != launch.curve:
                _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
            if kind == "COMPLETED":
                terminal = launch.terminal
                if terminal is None or launch.completion_position is not None:
                    _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
                block, transaction, raw_instruction, terminal_signature, virtual_sol = terminal
                if (
                    position != (block, transaction, raw_instruction * 2 + 1)
                    or signature != terminal_signature
                    or _integer(output_row[output_indexes["virtual_sol_reserves_lamports"]])
                    != virtual_sol
                ):
                    _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
                launch.completion_position = position
            elif kind == "MIGRATED":
                if (
                    launch.completion_position is None
                    or position <= launch.completion_position
                    or launch.migrated
                ):
                    _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)
                launch.migrated = True
            else:
                _fail(PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH)


class _OrderedDigest:
    __slots__ = ("_hash", "_last_key")

    def __init__(self, domain: str, header: object) -> None:
        self._hash = sha256()
        self._hash.update(domain.encode("utf-8") + b"\x00")
        self._update_bytes(header)
        self._last_key: tuple[object, ...] | None = None

    def update(self, key: tuple[object, ...], value: object) -> None:
        if self._last_key is not None and key <= self._last_key:
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        self._last_key = key
        self._update_bytes(value)

    def digest(self) -> ContentDigest:
        return ContentDigest(self._hash.hexdigest())

    def _update_bytes(self, value: object) -> None:
        encoded = canonical_json_bytes(value)
        self._hash.update(len(encoded).to_bytes(8, "big"))
        self._hash.update(encoded)


def _trade_creation_matches(
    row: tuple[Any, ...],
    indexes: Mapping[str, int],
    launch: _LaunchState,
) -> bool:
    return (
        (
            _integer(row[indexes["creation_block_ordinal"]]),
            _integer(row[indexes["creation_transaction_index"]]),
            _integer(row[indexes["creation_raw_instruction_index"]]),
        )
        == launch.creation_position
        and _text(row[indexes["creator"]]) == launch.creator
        and _text(row[indexes["creation_user"]]) == launch.creation_user
        and _text(row[indexes["curve_address"]]) == launch.curve
        and _text(row[indexes["token_program"]]) == launch.token_program
        and _integer(row[indexes["cashback_enabled"]]) == launch.cashback_enabled
        and _integer(row[indexes["mayhem_mode"]]) == 0
    )


def _lifecycle_creation_matches(
    row: tuple[Any, ...],
    indexes: Mapping[str, int],
    launch: _LaunchState,
) -> bool:
    return (
        (
            _integer(row[indexes["creation_block_ordinal"]]),
            _integer(row[indexes["creation_transaction_index"]]),
            _integer(row[indexes["creation_raw_instruction_index"]]),
        )
        == launch.creation_position
        and _text(row[indexes["curve_address"]]) == launch.curve
        and _text(row[indexes["token_program"]]) == launch.token_program
        and _integer(row[indexes["cashback_enabled"]]) == launch.cashback_enabled
        and _integer(row[indexes["mayhem_mode"]]) == 0
    )


def _indexes(columns: tuple[str, ...]) -> dict[str, int]:
    return {name: index for index, name in enumerate(columns)}


def _validate_raw_batch(
    batch: IndexedBatch,
    *,
    capability_id: CapabilityId,
    covered_range: BlockRange,
    columns: tuple[str, ...],
    query_fingerprint: ContentDigest,
) -> None:
    if (
        batch.capability_id != capability_id
        or batch.covered_range != covered_range
        or batch.columns != columns
        or batch.query_fingerprint != query_fingerprint
    ):
        _fail(PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("source integer is outside its unsigned contract")
    return value


def _text(value: object) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    if not isinstance(value, str) or not value:
        raise ValueError("source text is invalid")
    return value.rstrip("\x00")


def _datetime_ns(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError("source block time precedes Unix epoch")
        return value * 1_000_000_000
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source block time is invalid")
    utc = value.astimezone(UTC)
    if utc.microsecond != 0:
        raise ValueError("source block time is not second resolution")
    seconds = int(utc.timestamp())
    if seconds < 0:
        raise ValueError("source block time precedes Unix epoch")
    return seconds * 1_000_000_000


def _range_document(value: BlockRange) -> dict[str, object]:
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
    }


def _is_contained(candidate: BlockRange, outer: BlockRange) -> bool:
    return (
        candidate.network_id == outer.network_id
        and candidate.position_schema_id == outer.position_schema_id
        and candidate.from_block_ordinal >= outer.from_block_ordinal
        and candidate.to_block_ordinal <= outer.to_block_ordinal
    )


def _raise_normalization(error: PumpfunLiveNormalizationError) -> NoReturn:
    if error.code is PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE:
        _fail(PumpfunLiveSourceErrorCode.INCOMPLETE_BLOCK_RANGE)
    _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)


def _fail(code: PumpfunLiveSourceErrorCode) -> NoReturn:
    raise PumpfunLiveSourceError(code)


__all__ = [
    "PUMPFUN_BUNDLED_BUY_PLACEHOLDER_POLICY_ID",
    "PUMPFUN_EVENT_CLOCK_VALIDATION_POLICY_ID",
    "PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS",
    "PUMPFUN_LIVE_FEE_EFFECTIVE_FROM_UNIX_S",
    "PUMPFUN_LIVE_FEE_EFFECTIVE_UNTIL_UNIX_S",
    "PUMPFUN_LIVE_FEE_PROFILE_ID",
    "PumpfunLiveSourceComposition",
    "PumpfunLiveSourceError",
    "PumpfunLiveSourceErrorCode",
    "build_pumpfun_live_source_composition",
]
