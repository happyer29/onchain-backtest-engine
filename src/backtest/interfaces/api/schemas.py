"""Explicit HTTP DTOs and application-boundary conversions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest.application.dataset_plans import dataset_plan_bytes

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import ResolvedBacktestJob
from backtest.application.job_views import JobStatusView
from backtest.application.ml_contracts import (
    ExactInferencePolicy,
    InferenceMissingPolicy,
    # Include inference mode so the ml contracts dependency remains explicit.
    InferenceMode,
)
from backtest.application.ml_reference import ReferenceMlContract
from backtest.application.models import (
    ArtifactKind,
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    BudgetLimits,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    # Include committed artifact so the models dependency remains explicit.
    CommittedArtifact,
    DataRequirement,
    DatasetPlan,
    EvidenceStatus,
    JobEventRecord,
    # Include job progress details so the models dependency remains explicit.
    JobProgressDetails,
    JobRecord,
    JobType,
    PlanDatasetRequest,
    ProgressLevel,
    # Include progress stage so the models dependency remains explicit.
    ProgressStage,
    QueryLimits,
    RequirementOrigin,
    SettlementRequirement,
)

# Import run results at the visible module dependency boundary.
from backtest.application.ports.run_results import (
    MAX_ROUNDTRIP_PAGE_SIZE,
    RoundTripCursor,
    RoundTripPage,
)

# Import system at the visible module dependency boundary.
from backtest.application.ports.system import SystemResourceSnapshot
from backtest.application.run_contracts import RunContractDescriptor, RunContractField
from backtest.application.run_drafts import (
    PUMPFUN_SNIPING_EXECUTION_MODES,
    PUMPFUN_SNIPING_LEGACY_RUN_DRAFT_SCHEMA,
    PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA,
    PumpFeeProfileDraft,
    # Include pumpfun sniping run draft so the run drafts dependency remains explicit.
    PumpfunSnipingRunDraft,
    ReferenceRunDraft,
    RunDraft,
    SolanaAccountDepositCostDraft,
    SolanaFeeProfileDraft,
    WalletAccountMode,
    # Include wallet account profile draft so the run drafts dependency remains explicit.
    WalletAccountProfileDraft,
)
from backtest.application.run_results import (
    MAX_RUN_WARNING_LENGTH,
    MAX_RUN_WARNINGS,
    # Include run physical settings schema so the run results dependency remains explicit.
    RUN_PHYSICAL_SETTINGS_SCHEMA,
    RunBackend,
    RunComparisonMetric,
    RunComparisonProjection,
    RunPhysicalSettings,
    # Include validate run warnings so the run results dependency remains explicit.
    validate_run_warnings,
)
from backtest.application.run_specs import (
    AssetBalance,
    ReplayContract,
    # Include resolved run spec so the run specs dependency remains explicit.
    ResolvedRunSpec,
    resolved_run_spec_from_bytes,
)
from backtest.application.sweeps import ResolvedSweepSpec
from backtest.application.use_cases.query_artifacts import (
    # Include max artifact lineage items so the query artifacts dependency remains
    # explicit.
    MAX_ARTIFACT_LINEAGE_ITEMS,
    ArtifactDetails,
    ArtifactLineage,
)
from backtest.application.use_cases.query_run_results import (
    PumpfunSnipingDashboardView,
    PumpfunSnipingRunSummaryView,
)

# Import query runs at the visible module dependency boundary.
from backtest.application.use_cases.query_runs import RunSummaryView
from backtest.application.use_cases.resolve_sweep_spec import SweepDraftEntry
from backtest.application.use_cases.store_source_inspection import StoredSourceInspection
from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.chain import UINT32_MAX, ChainPosition
from backtest.domain.execution import ExecutionMode

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    FidelityRequirement,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    AssetId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    DeliveryScheduleId,
    ExecutionAttemptId,
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    LogicalRunId,
    ModelScheduleId,
    NetworkId,
    PoolId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
    PredictionSetId,
    ReplayPackId,
    SnapshotId,
    SourceId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.ledger import LedgerCorrelationKind
from backtest.domain.roundtrips import (
    ROUNDTRIP_RESULT_SCHEMA_V4,
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    RoundTripLegSide,
    # Include round trip record so the roundtrips dependency remains explicit.
    RoundTripRecord,
    RoundTripStatus,
)
from backtest.domain.time import BlockRange

# Import sniping at the visible module dependency boundary.
from backtest.engine.sniping import SnipingValuationStatus
from backtest.interfaces.api.pagination import PAGE_TOKEN_PATTERN


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


# Keep the error response contract and validation rules together.
class ErrorResponse(ApiModel):
    code: str
    message: str


# Keep the health response contract and validation rules together.
class HealthResponse(ApiModel):
    status: str
    profile: str
    version: str
    control_plane_id: str


# Keep the artifact response contract and validation rules together.
class ArtifactResponse(ApiModel):
    artifact_id: str
    kind: ArtifactKind
    manifest_digest: str
    build_key: str
    # Declare input artifact ids explicitly in the artifact response contract.
    input_artifact_ids: tuple[str, ...]

    @classmethod
    def from_domain(cls, value: CommittedArtifact) -> Self:
        # Execute the artifact response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            artifact_id=value.artifact_id.hex,
            kind=value.kind,
            manifest_digest=value.manifest_digest.hex,
            build_key=value.build_key.hex,
            # Include input artifact ids in the completed artifact response from domain
            # result.
            input_artifact_ids=tuple(item.hex for item in value.input_artifact_ids),
        )

    def to_domain(self) -> CommittedArtifact:
        # Execute the artifact response to domain workflow in explicit, reviewable steps.
        return CommittedArtifact(
            artifact_id=ArtifactId(self.artifact_id),
            kind=self.kind,
            manifest_digest=ContentDigest(self.manifest_digest),
            build_key=ContentDigest(self.build_key),
            # Include input artifact ids in the completed artifact response to domain
            # result.
            input_artifact_ids=tuple(ArtifactId(item) for item in self.input_artifact_ids),
        )


# Keep the artifact details response contract and validation rules together.
class ArtifactDetailsResponse(ApiModel):
    descriptor: ArtifactResponse
    manifest: dict[str, Any]

    @classmethod
    def from_domain(cls, value: ArtifactDetails) -> Self:
        # Execute the artifact details response from domain workflow in explicit,
        # reviewable steps.
        document = json.loads(value.manifest_bytes)
        if not isinstance(document, dict) or not all(isinstance(key, str) for key in document):
            raise ValueError("artifact manifest root must be an object")
        return cls(
            descriptor=ArtifactResponse.from_domain(value.descriptor),
            # Pass manifest explicitly so cls receives a reviewable from domain and
            # descriptor input in artifact details response from domain.
            manifest=document,
        )


# Keep the lineage edge response contract and validation rules together.
class LineageEdgeResponse(ApiModel):
    output_artifact_id: str
    input_artifact_id: str


# Keep the artifact lineage response contract and validation rules together.
class ArtifactLineageResponse(ApiModel):
    root_artifact_id: str
    artifacts: tuple[ArtifactResponse, ...] = Field(max_length=MAX_ARTIFACT_LINEAGE_ITEMS)
    edges: tuple[LineageEdgeResponse, ...] = Field(max_length=MAX_ARTIFACT_LINEAGE_ITEMS)

    @classmethod
    # Define artifact lineage response from domain as one focused operation with an
    # explicit boundary.
    def from_domain(cls, value: ArtifactLineage) -> Self:
        # Execute the artifact lineage response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            root_artifact_id=value.root_artifact_id.hex,
            artifacts=tuple(ArtifactResponse.from_domain(item) for item in value.artifacts),
            edges=tuple(
                LineageEdgeResponse(
                    # Pass output artifact id explicitly so LineageEdgeResponse receives a
                    # reviewable hex and output artifact id input in artifact lineage
                    # response from domain.
                    output_artifact_id=item.output_artifact_id.hex,
                    input_artifact_id=item.input_artifact_id.hex,
                )
                for item in value.edges
            ),
            # Complete cls only after its hex and root artifact id inputs are visible in
            # artifact lineage response from domain.
        )


# Keep the system resources response contract and validation rules together.
class SystemResourcesResponse(ApiModel):
    logical_cpu_count: int
    load_average_milli: tuple[int, int, int] | None
    process_peak_rss_bytes: int
    process_current_private_rss_bytes: int
    # Declare physical memory total bytes explicitly in the system resources response
    # contract.
    physical_memory_total_bytes: int
    physical_memory_available_bytes: int
    measured_safe_child_private_budget_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    # Declare temporary used bytes explicitly in the system resources response contract.
    temporary_used_bytes: int
    configured_aggregate_child_memory_bytes: int
    configured_builder_memory_bytes: int
    configured_max_parallel_runs: int
    configured_native_threads_per_process: int
    # Declare configured tmp quota bytes explicitly in the system resources response
    # contract.
    configured_tmp_quota_bytes: int
    configured_disk_low_watermark_bytes: int
    configured_disk_emergency_watermark_bytes: int
    configured_memory_safety_reserve_bytes: int
    configured_page_cache_floor_bytes: int
    # Declare configured host staging output reserve bytes explicitly in the system
    # resources response contract.
    configured_host_staging_output_reserve_bytes: int
    configured_fixed_shared_overhead_bytes: int

    @classmethod
    def from_domain(cls, value: SystemResourceSnapshot) -> Self:
        return cls(**{field: getattr(value, field) for field in cls.model_fields})


# Keep the reference ml contract response contract and validation rules together.
class ReferenceMlContractResponse(ApiModel):
    runtime_lock_id: str
    compiler_version: str
    feature_builder_bundle_id: str
    supported_feature_names: tuple[str, ...]
    # Declare universe builder bundle id explicitly in the reference ml contract response
    # contract.
    universe_builder_bundle_id: str
    universe_spec_id: str
    universe_config_digest: str
    label_builder_bundle_id: str
    label_spec_id: str
    # Declare label config digest explicitly in the reference ml contract response
    # contract.
    label_config_digest: str
    trainer_bundle_id: str
    trainer_framework: str
    frozen_inference_bundle_id: str

    @classmethod
    # Define reference ml contract response from domain as one focused operation with an
    # explicit boundary.
    def from_domain(cls, value: ReferenceMlContract) -> Self:
        # Execute the reference ml contract response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            runtime_lock_id=value.runtime_lock_id.hex,
            compiler_version=value.compiler_version,
            feature_builder_bundle_id=value.feature_builder_bundle_id.hex,
            supported_feature_names=value.supported_feature_names,
            # Pass universe builder bundle id explicitly so cls receives a reviewable hex
            # and runtime lock id input in reference ml contract response from domain.
            universe_builder_bundle_id=value.universe_builder_bundle_id.hex,
            universe_spec_id=value.universe_spec_id.hex,
            universe_config_digest=value.universe_config_digest.hex,
            label_builder_bundle_id=value.label_builder_bundle_id.hex,
            label_spec_id=value.label_spec_id.hex,
            # Pass label config digest explicitly so cls receives a reviewable hex and
            # runtime lock id input in reference ml contract response from domain.
            label_config_digest=value.label_config_digest.hex,
            trainer_bundle_id=value.trainer_bundle_id.hex,
            trainer_framework=value.trainer_framework,
            frozen_inference_bundle_id=value.frozen_inference_bundle_id.hex,
        )


# Keep the initial balance input contract and validation rules together.
class InitialBalanceInput(ApiModel):
    asset_id: str = Field(min_length=1, max_length=256)
    amount_atomic: int = Field(ge=0)


class RunPhysicalSettingsCommand(ApiModel):
    """Strict, versioned physical-attempt settings accepted by API/UI."""

    settings_schema: Literal["backtest.run-physical-settings/v2"] = Field(
        default=RUN_PHYSICAL_SETTINGS_SCHEMA,
        alias="schema",
    )
    backend: RunBackend
    # Declare reader batch rows explicitly in the run physical settings command contract.
    reader_batch_rows: int = Field(gt=0)
    reader_readahead: Literal[1, 2, 4]
    output_buffer_rows: int = Field(gt=0)
    threads: int = Field(gt=0)

    @field_validator("reader_readahead", mode="before")
    # Apply classmethod semantics to the following run physical settings command reject
    # boolean readahead contract.
    @classmethod
    def reject_boolean_readahead(cls, value: object) -> object:
        # Execute the run physical settings command reject boolean readahead workflow in
        # explicit, reviewable steps.
        if isinstance(value, bool):
            raise ValueError("reader_readahead must be an integer")
        return value

    def to_domain(self) -> RunPhysicalSettings:
        # Execute the run physical settings command to domain workflow in explicit,
        # reviewable steps.
        return RunPhysicalSettings(
            backend=self.backend,
            reader_batch_rows=self.reader_batch_rows,
            reader_readahead=self.reader_readahead,
            output_buffer_rows=self.output_buffer_rows,
            # Pass threads explicitly so RunPhysicalSettings receives a reviewable backend
            # and reader batch rows input in run physical settings command to domain.
            threads=self.threads,
        )

    @classmethod
    def from_domain(cls, value: RunPhysicalSettings) -> Self:
        # Execute the run physical settings command from domain workflow in explicit,
        # reviewable steps.
        document = value.document()
        document["backend"] = value.backend
        return cls.model_validate(document)


_DigestHex = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
_IdentifierValue = Annotated[str, Field(min_length=1, max_length=256)]
# List cursors are opaque canonical base64url values with a strict transport bound.
_PageCursor = Annotated[str, Field(min_length=1, max_length=512, pattern=PAGE_TOKEN_PATTERN)]
# Bind canonical unsigned decimal once as an explicit module-level contract.
_CanonicalUnsignedDecimal = Annotated[str, Field(pattern=r"^(?:0|[1-9][0-9]*)$")]
_CanonicalSignedDecimal = Annotated[str, Field(pattern=r"^(?:0|-?[1-9][0-9]*)$")]


# Keep the run comparison response contract and validation rules together.
class RunComparisonResponse(ApiModel):
    canonical_result_hash: _DigestHex
    audit_hash: _DigestHex
    ledger_hash: _DigestHex
    fill_hash: _DigestHex
    # Declare historical group count explicitly in the run comparison response contract.
    historical_group_count: int = Field(ge=0)
    historical_event_count: int = Field(ge=0)
    delivered_event_count: int = Field(ge=0)
    accepted_order_count: int = Field(ge=0)
    rejected_order_count: int = Field(ge=0)
    # Declare filled order count explicitly in the run comparison response contract.
    filled_order_count: int = Field(ge=0)
    failed_order_count: int = Field(ge=0)
    ledger_transaction_count: int = Field(ge=0)
    fill_count: int = Field(ge=0)
    final_balances_count: int = Field(ge=0)
    # Declare final balances digest explicitly in the run comparison response contract.
    final_balances_digest: _DigestHex

    @classmethod
    def from_domain(cls, value: RunComparisonProjection) -> Self:
        # Execute the run comparison response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            canonical_result_hash=value.canonical_result_hash.hex,
            audit_hash=value.audit_hash.hex,
            ledger_hash=value.ledger_hash.hex,
            fill_hash=value.fill_hash.hex,
            # Pass historical group count explicitly so cls receives a reviewable hex and
            # canonical result hash input in run comparison response from domain.
            historical_group_count=value.historical_group_count,
            historical_event_count=value.historical_event_count,
            delivered_event_count=value.delivered_event_count,
            accepted_order_count=value.accepted_order_count,
            rejected_order_count=value.rejected_order_count,
            # Pass filled order count explicitly so cls receives a reviewable hex and
            # canonical result hash input in run comparison response from domain.
            filled_order_count=value.filled_order_count,
            failed_order_count=value.failed_order_count,
            ledger_transaction_count=value.ledger_transaction_count,
            fill_count=value.fill_count,
            final_balances_count=value.final_balances_count,
            # Pass final balances digest explicitly so cls receives a reviewable hex and
            # canonical result hash input in run comparison response from domain.
            final_balances_digest=value.final_balances_digest.hex,
        )

    def to_domain(self) -> RunComparisonProjection:
        # Execute the run comparison response to domain workflow in explicit, reviewable
        # steps.
        return RunComparisonProjection(
            canonical_result_hash=ContentDigest(self.canonical_result_hash),
            audit_hash=ContentDigest(self.audit_hash),
            ledger_hash=ContentDigest(self.ledger_hash),
            fill_hash=ContentDigest(self.fill_hash),
            # Pass historical group count explicitly so RunComparisonProjection receives a
            # reviewable canonical result hash and audit hash input in run comparison
            # response to domain.
            historical_group_count=self.historical_group_count,
            historical_event_count=self.historical_event_count,
            delivered_event_count=self.delivered_event_count,
            accepted_order_count=self.accepted_order_count,
            rejected_order_count=self.rejected_order_count,
            # Pass filled order count explicitly so RunComparisonProjection receives a
            # reviewable canonical result hash and audit hash input in run comparison
            # response to domain.
            filled_order_count=self.filled_order_count,
            failed_order_count=self.failed_order_count,
            ledger_transaction_count=self.ledger_transaction_count,
            fill_count=self.fill_count,
            final_balances_count=self.final_balances_count,
            # Include final balances digest in the completed run comparison response to
            # domain result.
            final_balances_digest=ContentDigest(self.final_balances_digest),
        )


# Keep the run summary response contract and validation rules together.
class RunSummaryResponse(ApiModel):
    run_artifact_id: _DigestHex
    logical_run_id: _DigestHex
    execution_attempt_id: _DigestHex
    canonical_result_hash: _DigestHex
    # Declare audit hash explicitly in the run summary response contract.
    audit_hash: _DigestHex
    comparison: RunComparisonResponse
    physical_settings: RunPhysicalSettingsCommand
    canonicality: ReplayContract
    started_at: datetime
    completed_at: datetime
    warnings: tuple[Annotated[str, Field(min_length=1, max_length=MAX_RUN_WARNING_LENGTH)], ...] = (
        # Keep the field and max run warnings Field step visible while building warnings.
        Field(max_length=MAX_RUN_WARNINGS)
    )

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # Return the completed run summary response validate warnings result without a
        # hidden fallback.
        return validate_run_warnings(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_run_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run timestamp must be timezone-aware")
        return value

    @classmethod
    def from_domain(cls, value: RunSummaryView) -> Self:
        # Execute the run summary response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            run_artifact_id=value.run_artifact_id.hex,
            logical_run_id=value.logical_run_id.hex,
            execution_attempt_id=value.execution_attempt_id.hex,
            canonical_result_hash=value.canonical_result_hash.hex,
            # Pass audit hash explicitly so cls receives a reviewable hex and run artifact
            # id input in run summary response from domain.
            audit_hash=value.audit_hash.hex,
            comparison=RunComparisonResponse.from_domain(value.comparison),
            physical_settings=RunPhysicalSettingsCommand.from_domain(value.physical_settings),
            canonicality=value.canonicality,
            started_at=value.started_at,
            completed_at=value.completed_at,
            warnings=value.warnings,
            # Complete cls only after its hex and run artifact id inputs are visible in run
            # summary response from domain.
        )

    def to_domain(self) -> RunSummaryView:
        # Execute the run summary response to domain workflow in explicit, reviewable
        # steps.
        comparison = self.comparison.to_domain()
        if (
            self.canonical_result_hash != comparison.canonical_result_hash.hex
            or self.audit_hash != comparison.audit_hash.hex
        ):
            # Fail the run summary response to domain path with ValueError for run
            # response aliases differ from exact typed fields when canonical result hash,
            # hex and audit hash is true; do not continue ambiguously.
            raise ValueError("run response aliases differ from exact typed fields")
        result = RunSummaryView(
            run_artifact_id=ArtifactId(self.run_artifact_id),
            logical_run_id=LogicalRunId(self.logical_run_id),
            execution_attempt_id=ExecutionAttemptId(self.execution_attempt_id),
            # Pass comparison explicitly so RunSummaryView receives a reviewable run
            # artifact id and logical run id input in run summary response to domain.
            comparison=comparison,
            physical_settings=self.physical_settings.to_domain(),
            canonicality=self.canonicality,
            started_at=self.started_at,
            completed_at=self.completed_at,
            warnings=self.warnings,
        )
        # Evaluate the complete run summary response to domain from domain, result and run
        # summary response condition before guarded effects.
        if RunSummaryResponse.from_domain(result) != self:
            raise ValueError("run response does not round-trip exactly")
        return result


class RunListResponse(ApiModel):
    items: tuple[RunSummaryResponse, ...] = Field(max_length=50)
    next_cursor: _PageCursor | None = None


# Keep the chain position response contract and validation rules together.
class ChainPositionResponse(ApiModel):
    """Lossless JSON projection of one exact network-aware chain position."""

    network_id: _IdentifierValue
    position_schema_id: _IdentifierValue
    block_ordinal: int = Field(ge=0, le=UINT32_MAX)
    transaction_index: int = Field(ge=-1, lt=UINT32_MAX)
    event_index: int | None = Field(default=None, ge=0, le=UINT32_MAX)
    # Declare boundary ordinal explicitly in the chain position response contract.
    boundary_ordinal: _CanonicalUnsignedDecimal

    @classmethod
    def from_domain(cls, value: ChainPosition) -> Self:
        # Execute the chain position response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            network_id=value.network_id.value,
            position_schema_id=value.position_schema_id.value,
            block_ordinal=value.block_ordinal,
            transaction_index=value.transaction_index,
            # Pass event index explicitly so cls receives a reviewable value and network
            # id input in chain position response from domain.
            event_index=value.event_index,
            boundary_ordinal=_unsigned_decimal(value.boundary_ordinal),
        )


# Keep the round trip leg response contract and validation rules together.
class RoundTripLegResponse(ApiModel):
    side: RoundTripLegSide
    decision_position: ChainPositionResponse
    landing_position: ChainPositionResponse | None
    amount_in_atomic: _CanonicalUnsignedDecimal | None
    # Declare reference out atomic explicitly in the round trip leg response contract.
    reference_out_atomic: _CanonicalUnsignedDecimal
    landing_out_atomic: _CanonicalUnsignedDecimal | None
    minimum_out_atomic: _CanonicalUnsignedDecimal
    signed_slippage_atomic: _CanonicalSignedDecimal | None
    protocol_fee_atomic: _CanonicalUnsignedDecimal
    # Declare creator fee atomic explicitly in the round trip leg response contract.
    creator_fee_atomic: _CanonicalUnsignedDecimal
    network_base_fee_atomic: _CanonicalUnsignedDecimal
    network_priority_fee_atomic: _CanonicalUnsignedDecimal
    failure_code: Annotated[str, Field(min_length=1, max_length=256)] | None

    @classmethod
    # Define round trip leg response from domain as one focused operation with an explicit
    # boundary.
    def from_domain(cls, value: RoundTripLegRecord) -> Self:
        # Execute the round trip leg response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            side=value.side,
            decision_position=ChainPositionResponse.from_domain(value.decision_position),
            landing_position=(
                None
                # Pass value explicitly so cls receives a reviewable side and from domain
                # input in round trip leg response from domain.
                if value.landing_position is None
                else ChainPositionResponse.from_domain(value.landing_position)
            ),
            amount_in_atomic=_optional_unsigned_decimal(value.amount_in_atomic),
            reference_out_atomic=_unsigned_decimal(value.reference_out_atomic),
            # Include landing out atomic in the completed round trip leg response from
            # domain result.
            landing_out_atomic=_optional_unsigned_decimal(value.landing_out_atomic),
            minimum_out_atomic=_unsigned_decimal(value.minimum_out_atomic),
            signed_slippage_atomic=_optional_signed_decimal(value.signed_slippage_atomic),
            protocol_fee_atomic=_unsigned_decimal(value.protocol_fee_atomic),
            creator_fee_atomic=_unsigned_decimal(value.creator_fee_atomic),
            # Include network base fee atomic in the completed round trip leg response
            # from domain result.
            network_base_fee_atomic=_unsigned_decimal(value.network_base_fee_atomic),
            network_priority_fee_atomic=_unsigned_decimal(value.network_priority_fee_atomic),
            failure_code=value.failure_code,
        )


class AccountComponentResponse(ApiModel):
    """Browser-safe exact v3 projection of one account requirement."""

    requirement_schema_id: _IdentifierValue
    asset_id: _IdentifierValue
    scope: AccountRequirementScope
    release_policy: AccountReleasePolicy
    maximum_reserved_atomic: _CanonicalUnsignedDecimal
    paid_atomic: _CanonicalUnsignedDecimal
    released_atomic: _CanonicalUnsignedDecimal
    refunded_atomic: _CanonicalUnsignedDecimal
    locked_delta_atomic: _CanonicalSignedDecimal
    lifecycle: AccountComponentLifecycle
    attribution_kind: LedgerCorrelationKind
    attribution_id: _DigestHex

    @classmethod
    def from_domain(cls, value: AccountComponentRecord) -> Self:
        """Preserve every atomic amount as a canonical decimal string."""

        return cls(
            requirement_schema_id=value.requirement_schema_id,
            asset_id=value.asset_id.value,
            scope=value.scope,
            release_policy=value.release_policy,
            maximum_reserved_atomic=_unsigned_decimal(value.maximum_reserved_atomic),
            paid_atomic=_unsigned_decimal(value.paid_atomic),
            released_atomic=_unsigned_decimal(value.released_atomic),
            refunded_atomic=_unsigned_decimal(value.refunded_atomic),
            locked_delta_atomic=_signed_decimal(value.locked_delta_atomic),
            lifecycle=value.lifecycle,
            attribution_kind=value.attribution_kind,
            attribution_id=value.attribution_id.hex,
        )


class QuoteLiquidityEvidenceResponse(ApiModel):
    """Browser-safe exact sell-liquidity evidence for one causal boundary."""

    policy_id: _IdentifierValue
    asset_id: _IdentifierValue
    required_output_atomic: _CanonicalUnsignedDecimal
    observed_available_output_atomic: _CanonicalUnsignedDecimal
    synthetic_shortfall_atomic: _CanonicalUnsignedDecimal

    @classmethod
    def from_domain(cls, value: QuoteLiquidityEvidenceRecord) -> Self:
        return cls(
            policy_id=value.policy_id,
            asset_id=value.asset_id.value,
            required_output_atomic=_unsigned_decimal(value.required_output_atomic),
            observed_available_output_atomic=_unsigned_decimal(
                value.observed_available_output_atomic
            ),
            synthetic_shortfall_atomic=_unsigned_decimal(value.synthetic_shortfall_atomic),
        )


class RoundTripResponse(ApiModel):
    """Browser-safe round-trip projection without lossy JSON integers."""

    roundtrip_id: _DigestHex
    network_id: _IdentifierValue
    position_schema_id: _IdentifierValue
    target_event_id: _DigestHex
    target_position: ChainPositionResponse
    # Declare target time ns explicitly in the round trip response contract.
    target_time_ns: _CanonicalUnsignedDecimal
    developer_id: _IdentifierValue
    creation_user_id: _IdentifierValue
    asset_id: _IdentifierValue
    quote_asset_id: _IdentifierValue
    # Declare venue id explicitly in the round trip response contract.
    venue_id: _IdentifierValue
    cooldown_consumed: bool
    cooldown_until_ns: _CanonicalUnsignedDecimal | None
    status: RoundTripStatus
    buy: RoundTripLegResponse | None
    # Declare sell explicitly in the round trip response contract.
    sell: RoundTripLegResponse | None
    acquired_token_amount_atomic: _CanonicalUnsignedDecimal
    account_profile_id: _IdentifierValue
    account_components: tuple[AccountComponentResponse, ...]
    cashback_receivable_atomic: _CanonicalUnsignedDecimal
    realized_cash_pnl_atomic: _CanonicalSignedDecimal | None
    # Declare mtm status explicitly in the round trip response contract.
    mtm_status: MtmStatus
    mtm_liquidation_value_atomic: _CanonicalSignedDecimal | None
    mtm_cash_pnl_atomic: _CanonicalSignedDecimal | None
    economic_pnl_atomic: _CanonicalSignedDecimal | None
    result_schema_id: _IdentifierValue
    execution_mode: ExecutionMode
    sell_reference_liquidity: QuoteLiquidityEvidenceResponse | None
    sell_landing_liquidity: QuoteLiquidityEvidenceResponse | None
    mtm_liquidity: QuoteLiquidityEvidenceResponse | None
    settled_venue_funded_atomic: _CanonicalUnsignedDecimal | None
    settled_synthetic_funded_atomic: _CanonicalUnsignedDecimal | None

    @classmethod
    # Define round trip response from domain as one focused operation with an explicit
    # boundary.
    def from_domain(cls, value: RoundTripRecord) -> Self:
        # Execute the round trip response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            roundtrip_id=value.roundtrip_id.hex,
            network_id=value.network_id.value,
            position_schema_id=value.position_schema_id.value,
            target_event_id=value.target_event_id.hex,
            # Include target position in the completed round trip response from domain
            # result.
            target_position=ChainPositionResponse.from_domain(value.target_position),
            target_time_ns=_unsigned_decimal(value.target_time_ns),
            developer_id=value.developer_id.value,
            creation_user_id=value.creation_user_id.value,
            asset_id=value.asset_id.value,
            # Pass quote asset id explicitly so cls receives a reviewable hex and
            # roundtrip id input in round trip response from domain.
            quote_asset_id=value.quote_asset_id.value,
            venue_id=value.venue_id.value,
            cooldown_consumed=value.cooldown_consumed,
            cooldown_until_ns=_optional_unsigned_decimal(value.cooldown_until_ns),
            status=value.status,
            # Include buy in the completed round trip response from domain result.
            buy=None if value.buy is None else RoundTripLegResponse.from_domain(value.buy),
            sell=None if value.sell is None else RoundTripLegResponse.from_domain(value.sell),
            acquired_token_amount_atomic=_unsigned_decimal(value.acquired_token_amount_atomic),
            account_profile_id=value.account_profile_id,
            account_components=tuple(
                AccountComponentResponse.from_domain(item) for item in value.account_components
            ),
            # Include cashback receivable atomic in the completed round trip response from
            # domain result.
            cashback_receivable_atomic=_unsigned_decimal(value.cashback_receivable_atomic),
            realized_cash_pnl_atomic=_optional_signed_decimal(value.realized_cash_pnl_atomic),
            mtm_status=value.mtm_status,
            mtm_liquidation_value_atomic=_optional_signed_decimal(
                value.mtm_liquidation_value_atomic
                # Complete _optional_signed_decimal only after its mtm liquidation value
                # atomic and value inputs are visible in round trip response from domain.
            ),
            mtm_cash_pnl_atomic=_optional_signed_decimal(value.mtm_cash_pnl_atomic),
            economic_pnl_atomic=_optional_signed_decimal(value.economic_pnl_atomic),
            result_schema_id=value.source_schema_id,
            execution_mode=value.execution_mode,
            sell_reference_liquidity=(
                None
                if value.sell_reference_liquidity is None
                else QuoteLiquidityEvidenceResponse.from_domain(value.sell_reference_liquidity)
            ),
            sell_landing_liquidity=(
                None
                if value.sell_landing_liquidity is None
                else QuoteLiquidityEvidenceResponse.from_domain(value.sell_landing_liquidity)
            ),
            mtm_liquidity=(
                None
                if value.mtm_liquidity is None
                else QuoteLiquidityEvidenceResponse.from_domain(value.mtm_liquidity)
            ),
            settled_venue_funded_atomic=(
                _unsigned_decimal(value.settled_venue_funded_atomic)
                if value.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V4
                else None
            ),
            settled_synthetic_funded_atomic=(
                _unsigned_decimal(value.settled_synthetic_funded_atomic)
                if value.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V4
                else None
            ),
        )


# Keep the round trip cursor response contract and validation rules together.
class RoundTripCursorResponse(ApiModel):
    target_boundary_ordinal: _CanonicalUnsignedDecimal
    roundtrip_id: _DigestHex

    @classmethod
    def from_domain(cls, value: RoundTripCursor) -> Self:
        # Execute the round trip cursor response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            target_boundary_ordinal=_unsigned_decimal(value.target_boundary_ordinal),
            roundtrip_id=value.roundtrip_id.hex,
        )


# Keep the round trip page response contract and validation rules together.
class RoundTripPageResponse(ApiModel):
    items: tuple[RoundTripResponse, ...] = Field(max_length=MAX_ROUNDTRIP_PAGE_SIZE)
    next_cursor: RoundTripCursorResponse | None

    @classmethod
    def from_domain(cls, value: RoundTripPage) -> Self:
        # Execute the round trip page response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            items=tuple(RoundTripResponse.from_domain(item) for item in value.items),
            next_cursor=(
                None
                if value.next_cursor is None
                # Route all remaining cases through the explicit alternative branch.
                else RoundTripCursorResponse.from_domain(value.next_cursor)
            ),
        )


# Keep the pumpfun sniping run summary response contract and validation rules together.
class PumpfunSnipingRunSummaryResponse(ApiModel):
    run_artifact_id: _DigestHex
    logical_run_id: _DigestHex
    execution_attempt_id: _DigestHex
    network_id: _IdentifierValue
    # Declare position schema id explicitly in the pumpfun sniping run summary response
    # contract.
    position_schema_id: _IdentifierValue
    canonical_result_hash: _DigestHex
    audit_hash: _DigestHex
    ledger_hash: _DigestHex
    fill_hash: _DigestHex
    # Declare roundtrip digest explicitly in the pumpfun sniping run summary response
    # contract.
    roundtrip_digest: _DigestHex
    final_balances_digest: _DigestHex
    historical_group_count: int = Field(ge=0)
    historical_event_count: int = Field(ge=0)
    delivered_event_count: int = Field(ge=0)
    # Declare target count explicitly in the pumpfun sniping run summary response
    # contract.
    target_count: int = Field(ge=0)
    cooldown_skipped_count: int = Field(ge=0)
    accepted_buy_count: int = Field(ge=0)
    accepted_order_count: int = Field(ge=0)
    rejected_order_count: int = Field(ge=0)
    # Declare filled order count explicitly in the pumpfun sniping run summary response
    # contract.
    filled_order_count: int = Field(ge=0)
    failed_order_count: int = Field(ge=0)
    failed_buy_count: int = Field(ge=0)
    failed_sell_count: int = Field(ge=0)
    closed_position_count: int = Field(ge=0)
    # Declare open position count explicitly in the pumpfun sniping run summary response
    # contract.
    open_position_count: int = Field(ge=0)
    ledger_transaction_count: int = Field(ge=0)
    fill_count: int = Field(ge=0)
    roundtrip_count: int = Field(ge=0)
    final_balances_count: int = Field(ge=0)
    # Declare realized cash pnl atomic explicitly in the pumpfun sniping run summary
    # response contract.
    realized_cash_pnl_atomic: _CanonicalSignedDecimal
    valuation_status: SnipingValuationStatus
    unvalued_open_position_count: int = Field(ge=0)
    valued_economic_pnl_subtotal_atomic: _CanonicalSignedDecimal
    economic_pnl_atomic: _CanonicalSignedDecimal | None
    # Declare cashback receivable atomic explicitly in the pumpfun sniping run summary
    # response contract.
    cashback_receivable_atomic: _CanonicalUnsignedDecimal
    protocol_fee_paid_atomic: _CanonicalUnsignedDecimal
    creator_fee_paid_atomic: _CanonicalUnsignedDecimal
    network_base_fee_paid_atomic: _CanonicalUnsignedDecimal
    network_priority_fee_paid_atomic: _CanonicalUnsignedDecimal
    # Declare account deposit paid atomic explicitly in the pumpfun sniping run summary
    # response contract.
    account_deposit_paid_atomic: _CanonicalUnsignedDecimal
    account_deposit_refunded_atomic: _CanonicalUnsignedDecimal
    account_deposit_locked_atomic: _CanonicalUnsignedDecimal
    favorable_slippage_count: int = Field(ge=0)
    adverse_slippage_count: int = Field(ge=0)
    # Declare buy slippage failure count explicitly in the pumpfun sniping run summary
    # response contract.
    buy_slippage_failure_count: int = Field(ge=0)
    sell_slippage_failure_count: int = Field(ge=0)
    summary_schema_id: _IdentifierValue
    execution_mode: ExecutionMode
    settlement_policy_id: _IdentifierValue
    filled_sell_count: int | None = Field(default=None, ge=0)
    real_liquidity_sufficient_filled_sell_count: int | None = Field(default=None, ge=0)
    synthetic_liquidity_used_sell_count: int | None = Field(default=None, ge=0)
    gross_sell_settlement_atomic: _CanonicalUnsignedDecimal | None
    venue_funded_sell_atomic: _CanonicalUnsignedDecimal | None
    synthetic_funded_sell_atomic: _CanonicalUnsignedDecimal | None

    @classmethod
    def from_domain(cls, value: PumpfunSnipingRunSummaryView) -> Self:
        # Execute the pumpfun sniping run summary response from domain workflow in
        # explicit, reviewable steps.
        return cls(
            run_artifact_id=value.run_artifact_id.hex,
            logical_run_id=value.logical_run_id.hex,
            execution_attempt_id=value.execution_attempt_id.hex,
            network_id=value.network_id.value,
            # Pass position schema id explicitly so cls receives a reviewable hex and run
            # artifact id input in pumpfun sniping run summary response from domain.
            position_schema_id=value.position_schema_id.value,
            canonical_result_hash=value.canonical_result_hash.hex,
            audit_hash=value.audit_hash.hex,
            ledger_hash=value.ledger_hash.hex,
            fill_hash=value.fill_hash.hex,
            # Pass roundtrip digest explicitly so cls receives a reviewable hex and run
            # artifact id input in pumpfun sniping run summary response from domain.
            roundtrip_digest=value.roundtrip_digest.hex,
            final_balances_digest=value.final_balances_digest.hex,
            historical_group_count=value.historical_group_count,
            historical_event_count=value.historical_event_count,
            delivered_event_count=value.delivered_event_count,
            # Pass target count explicitly so cls receives a reviewable hex and run
            # artifact id input in pumpfun sniping run summary response from domain.
            target_count=value.target_count,
            cooldown_skipped_count=value.cooldown_skipped_count,
            accepted_buy_count=value.accepted_buy_count,
            accepted_order_count=value.accepted_order_count,
            rejected_order_count=value.rejected_order_count,
            # Pass filled order count explicitly so cls receives a reviewable hex and run
            # artifact id input in pumpfun sniping run summary response from domain.
            filled_order_count=value.filled_order_count,
            failed_order_count=value.failed_order_count,
            failed_buy_count=value.failed_buy_count,
            failed_sell_count=value.failed_sell_count,
            closed_position_count=value.closed_position_count,
            # Pass open position count explicitly so cls receives a reviewable hex and run
            # artifact id input in pumpfun sniping run summary response from domain.
            open_position_count=value.open_position_count,
            ledger_transaction_count=value.ledger_transaction_count,
            fill_count=value.fill_count,
            roundtrip_count=value.roundtrip_count,
            final_balances_count=value.final_balances_count,
            # Include realized cash pnl atomic in the completed pumpfun sniping run
            # summary response from domain result.
            realized_cash_pnl_atomic=_signed_decimal(value.realized_cash_pnl_atomic),
            valuation_status=value.valuation_status,
            unvalued_open_position_count=value.unvalued_open_position_count,
            valued_economic_pnl_subtotal_atomic=_signed_decimal(
                value.valued_economic_pnl_subtotal_atomic
                # Complete _signed_decimal only after its valued economic pnl subtotal atomic
                # and value inputs are visible in pumpfun sniping run summary response from
                # domain.
            ),
            economic_pnl_atomic=_optional_signed_decimal(value.economic_pnl_atomic),
            cashback_receivable_atomic=_unsigned_decimal(value.cashback_receivable_atomic),
            protocol_fee_paid_atomic=_unsigned_decimal(value.protocol_fee_paid_atomic),
            creator_fee_paid_atomic=_unsigned_decimal(value.creator_fee_paid_atomic),
            # Include network base fee paid atomic in the completed pumpfun sniping run
            # summary response from domain result.
            network_base_fee_paid_atomic=_unsigned_decimal(value.network_base_fee_paid_atomic),
            network_priority_fee_paid_atomic=_unsigned_decimal(
                value.network_priority_fee_paid_atomic
            ),
            account_deposit_paid_atomic=_unsigned_decimal(value.account_deposit_paid_atomic),
            # Include account deposit refunded atomic in the completed pumpfun sniping run
            # summary response from domain result.
            account_deposit_refunded_atomic=_unsigned_decimal(
                value.account_deposit_refunded_atomic
            ),
            account_deposit_locked_atomic=_unsigned_decimal(value.account_deposit_locked_atomic),
            favorable_slippage_count=value.favorable_slippage_count,
            # Pass adverse slippage count explicitly so cls receives a reviewable hex and
            # run artifact id input in pumpfun sniping run summary response from domain.
            adverse_slippage_count=value.adverse_slippage_count,
            buy_slippage_failure_count=value.buy_slippage_failure_count,
            sell_slippage_failure_count=value.sell_slippage_failure_count,
            summary_schema_id=value.summary_schema_id,
            execution_mode=value.execution_mode,
            settlement_policy_id=value.settlement_policy_id,
            filled_sell_count=value.filled_sell_count,
            real_liquidity_sufficient_filled_sell_count=(
                value.real_liquidity_sufficient_filled_sell_count
            ),
            synthetic_liquidity_used_sell_count=value.synthetic_liquidity_used_sell_count,
            gross_sell_settlement_atomic=_optional_unsigned_decimal(
                value.gross_sell_settlement_atomic
            ),
            venue_funded_sell_atomic=_optional_unsigned_decimal(value.venue_funded_sell_atomic),
            synthetic_funded_sell_atomic=_optional_unsigned_decimal(
                value.synthetic_funded_sell_atomic
            ),
        )


class PumpfunSnipingDashboardResponse(ApiModel):
    """Bounded first-paint projection for the dedicated result dashboard."""

    summary: PumpfunSnipingRunSummaryResponse
    roundtrips: RoundTripPageResponse

    @classmethod
    def from_domain(cls, value: PumpfunSnipingDashboardView) -> Self:
        return cls(
            summary=PumpfunSnipingRunSummaryResponse.from_domain(value.summary),
            roundtrips=RoundTripPageResponse.from_domain(value.roundtrips),
        )


class RunBacktestCommand(ApiModel):
    """Typed heavy-job request; the HTTP handler only durably queues it."""

    resolved_run_spec: dict[str, Any]
    attempt_nonce: str = Field(min_length=64, max_length=71)
    physical_settings: RunPhysicalSettingsCommand

    def to_domain(self) -> ResolvedBacktestJob:
        # Execute the run backtest command to domain workflow in explicit, reviewable
        # steps.
        spec = resolved_run_spec_from_bytes(canonical_json_bytes(self.resolved_run_spec))
        return ResolvedBacktestJob(
            resolved_spec=spec,
            attempt_nonce=ContentDigest(self.attempt_nonce),
            physical_settings=self.physical_settings.to_domain(),
            # Complete ResolvedBacktestJob only after its attempt nonce and to domain inputs
            # are visible in run backtest command to domain.
        )


class ReferenceRunDraftCommand(ApiModel):
    """Typed UI/API input; never stored or executed before exact resolution."""

    snapshot_id: str = Field(min_length=64, max_length=71)
    replay_pack_id: str | None = Field(default=None, min_length=64, max_length=71)
    delivery_schedule_id: str | None = Field(default=None, min_length=64, max_length=71)
    pool_id: str = Field(min_length=1, max_length=256)
    sold_asset_id: str = Field(min_length=1, max_length=256)
    # Declare bought asset id explicitly in the reference run draft command contract.
    bought_asset_id: str = Field(min_length=1, max_length=256)
    amount_in_atomic: int = Field(gt=0)
    minimum_amount_out_atomic: int = Field(ge=0)
    fee_bps: int = Field(ge=0, le=10_000)
    execution_mode: ExecutionMode
    # Declare maximum order input atomic explicitly in the reference run draft command
    # contract.
    maximum_order_input_atomic: int = Field(gt=0)
    observation_slots: int = Field(ge=0)
    order_slots: int = Field(ge=0)
    initial_portfolio: tuple[InitialBalanceInput, ...] = Field(min_length=1)
    root_seed: int = Field(ge=0)
    # Declare maximum dynamic items explicitly in the reference run draft command
    # contract.
    maximum_dynamic_items: int = Field(default=1_000_000, gt=0)
    feature_set_ids: tuple[str, ...] = ()
    model_schedule_id: str | None = Field(default=None, min_length=64, max_length=71)
    prediction_set_ids: tuple[str, ...] = ()
    inference_mode: InferenceMode = InferenceMode.DISABLED
    # Declare prediction name explicitly in the reference run draft command contract.
    prediction_name: str | None = Field(default=None, min_length=1, max_length=256)
    inference_missing_policy: InferenceMissingPolicy = InferenceMissingPolicy.REJECT
    inference_delay_boundaries: int = Field(default=0, ge=0)

    def to_domain(self) -> ReferenceRunDraft:
        # Execute the reference run draft command to domain workflow in explicit,
        # reviewable steps.
        balances = tuple(
            sorted(
                (
                    AssetBalance(AssetId(item.asset_id), item.amount_atomic)
                    for item in self.initial_portfolio
                    # Complete sorted only after its amount atomic and initial portfolio
                    # inputs are visible in reference run draft command to domain.
                ),
                key=lambda item: item.asset_id.value,
            )
        )
        features = tuple(sorted(FeatureSetId(item) for item in self.feature_set_ids))
        # Assemble predictions once so the reference run draft command to domain workflow
        # shares one value.
        predictions = tuple(sorted(PredictionSetId(item) for item in self.prediction_set_ids))
        if self.inference_mode is InferenceMode.DISABLED:
            # Handle the reference run draft command to domain inference mode and disabled
            # condition as a distinct block.
            if (
                self.prediction_name is not None
                or self.inference_missing_policy is not InferenceMissingPolicy.REJECT
                or self.inference_delay_boundaries != 0
            ):
                # Fail the reference run draft command to domain path with ValueError for
                # disabled inference fields must use canonical defaults when prediction
                # name, inference missing policy and reject is true; do not continue
                # ambiguously.
                raise ValueError("disabled inference fields must use canonical defaults")
            inference = ExactInferencePolicy.disabled()
        # Handle the reference run draft command to domain complement of inference mode
        # and disabled explicitly.
        elif self.inference_mode is InferenceMode.FROZEN:
            # Handle the reference run draft command to domain inference mode and frozen
            # condition as a distinct block.
            if self.prediction_name is None:
                raise ValueError("frozen inference requires prediction_name")
            inference = ExactInferencePolicy.frozen_exact_linear(
                prediction_name=self.prediction_name,
                missing_policy=self.inference_missing_policy,
                # Pass inference delay boundaries explicitly so frozen_exact_linear
                # receives a reviewable prediction name and inference missing policy input
                # in reference run draft command to domain.
                inference_delay_boundaries=self.inference_delay_boundaries,
            )
        # Handle the reference run draft command to domain complement of inference mode
        # and frozen explicitly.
        elif self.inference_mode is InferenceMode.EMBEDDED_BATCH:
            # Handle the reference run draft command to domain inference mode and embedded
            # batch condition as a distinct block.
            if self.prediction_name is None:
                raise ValueError("embedded inference requires prediction_name")
            inference = ExactInferencePolicy.embedded_exact_linear(
                prediction_name=self.prediction_name,
                missing_policy=self.inference_missing_policy,
                # Pass inference delay boundaries explicitly so embedded_exact_linear
                # receives a reviewable prediction name and inference missing policy input
                # in reference run draft command to domain.
                inference_delay_boundaries=self.inference_delay_boundaries,
            )
        else:
            raise ValueError("stateful inference is not supported by the reference run")
        return ReferenceRunDraft(
            # Include snapshot id in the completed reference run draft command to domain
            # result.
            snapshot_id=SnapshotId(self.snapshot_id),
            replay_pack_id=(
                None if self.replay_pack_id is None else ReplayPackId(self.replay_pack_id)
            ),
            delivery_schedule_id=(
                # Keep reference run draft, amount in atomic and minimum amount out atomic
                # visible while completing ReferenceRunDraft within reference run draft
                # command to domain.
                None
                if self.delivery_schedule_id is None
                else DeliveryScheduleId(self.delivery_schedule_id)
            ),
            pool_id=PoolId(self.pool_id),
            # Include sold asset id in the completed reference run draft command to domain
            # result.
            sold_asset_id=AssetId(self.sold_asset_id),
            bought_asset_id=AssetId(self.bought_asset_id),
            amount_in_atomic=self.amount_in_atomic,
            minimum_amount_out_atomic=self.minimum_amount_out_atomic,
            fee_bps=self.fee_bps,
            # Pass execution mode explicitly so ReferenceRunDraft receives a reviewable
            # snapshot id and replay pack id input in reference run draft command to
            # domain.
            execution_mode=self.execution_mode,
            maximum_order_input_atomic=self.maximum_order_input_atomic,
            observation_slots=self.observation_slots,
            order_slots=self.order_slots,
            initial_portfolio=balances,
            # Pass root seed explicitly so ReferenceRunDraft receives a reviewable
            # snapshot id and replay pack id input in reference run draft command to
            # domain.
            root_seed=self.root_seed,
            maximum_dynamic_items=self.maximum_dynamic_items,
            feature_set_ids=features,
            model_schedule_id=(
                None if self.model_schedule_id is None else ModelScheduleId(self.model_schedule_id)
                # Complete ReferenceRunDraft only after its snapshot id and replay pack id
                # inputs are visible in reference run draft command to domain.
            ),
            prediction_set_ids=predictions,
            inference_policy=inference,
        )


# Keep the wallet account profile command contract and validation rules together.
class SolanaAccountDepositCostCommand(ApiModel):
    """Transport-safe exact price for one account requirement schema."""

    requirement_schema_id: str = Field(min_length=1, max_length=128)
    deposit_lamports: str = Field(min_length=1, max_length=40)

    def to_domain(self) -> SolanaAccountDepositCostDraft:
        return SolanaAccountDepositCostDraft(
            requirement_schema_id=self.requirement_schema_id,
            deposit_lamports=_positive_atomic_decimal(self.deposit_lamports),
        )


class WalletAccountProfileCommand(ApiModel):
    profile_schema: Literal["pumpfun-solana-wallet-account-profile/v2"] = Field(
        default="pumpfun-solana-wallet-account-profile/v2",
        alias="schema",
        serialization_alias="schema",
    )
    profile_id: str = Field(min_length=1, max_length=128)
    initial_uva_state: Literal["fresh", "prewarmed"]
    effective_from_unix_s: int = Field(ge=0)
    effective_until_unix_s: int = Field(gt=0)
    account_costs: list[SolanaAccountDepositCostCommand] = Field(
        min_length=3,
        max_length=3,
    )

    # Define wallet account profile command to domain as one focused operation with an
    # explicit boundary.
    def to_domain(self) -> WalletAccountProfileDraft:
        # Execute the wallet account profile command to domain workflow in explicit,
        # reviewable steps.
        return WalletAccountProfileDraft(
            profile_id=self.profile_id,
            initial_uva_state=WalletAccountMode(self.initial_uva_state),
            effective_from_unix_s=self.effective_from_unix_s,
            effective_until_unix_s=self.effective_until_unix_s,
            account_costs=tuple(item.to_domain() for item in self.account_costs),
            # Complete WalletAccountProfileDraft only after its profile id and mode inputs are
            # visible in wallet account profile command to domain.
        )


# Keep the pump fee profile command contract and validation rules together.
class PumpFeeProfileCommand(ApiModel):
    profile_id: str = Field(min_length=1, max_length=128)
    program_version: str = Field(min_length=1, max_length=128)
    buy_formula_version: str = Field(min_length=1, max_length=128)
    sell_formula_version: str = Field(min_length=1, max_length=128)
    # Declare effective from unix s explicitly in the pump fee profile command contract.
    effective_from_unix_s: int = Field(ge=0)
    effective_until_unix_s: int = Field(gt=0)
    protocol_fee_bps: int = Field(ge=0, le=9_999)
    creator_fee_bps: int = Field(ge=0, le=9_999)

    def to_domain(self) -> PumpFeeProfileDraft:
        # Return the completed pump fee profile command to domain result without a hidden
        # fallback.
        return PumpFeeProfileDraft(**self.model_dump())


# Keep the solana fee profile command contract and validation rules together.
class SolanaFeeProfileCommand(ApiModel):
    profile_id: str = Field(min_length=1, max_length=128)
    formula_version: str = Field(min_length=1, max_length=128)
    transaction_format: str = Field(min_length=1, max_length=32)
    effective_from_unix_s: int = Field(ge=0)
    # Declare effective until unix s explicitly in the solana fee profile command
    # contract.
    effective_until_unix_s: int = Field(gt=0)
    charged_signature_count: int = Field(gt=0)
    lamports_per_signature: str = Field(min_length=1, max_length=40)
    compute_unit_limit: int = Field(gt=0)
    micro_lamports_per_compute_unit: str = Field(min_length=1, max_length=40)

    # Define solana fee profile command to domain as one focused operation with an
    # explicit boundary.
    def to_domain(self) -> SolanaFeeProfileDraft:
        # Execute the solana fee profile command to domain workflow in explicit,
        # reviewable steps.
        return SolanaFeeProfileDraft(
            profile_id=self.profile_id,
            formula_version=self.formula_version,
            transaction_format=self.transaction_format,
            effective_from_unix_s=self.effective_from_unix_s,
            # Pass effective until unix s explicitly so SolanaFeeProfileDraft receives a
            # reviewable profile id and formula version input in solana fee profile
            # command to domain.
            effective_until_unix_s=self.effective_until_unix_s,
            charged_signature_count=self.charged_signature_count,
            lamports_per_signature=_atomic_decimal(self.lamports_per_signature),
            compute_unit_limit=self.compute_unit_limit,
            micro_lamports_per_compute_unit=_atomic_decimal(self.micro_lamports_per_compute_unit),
            # Complete SolanaFeeProfileDraft only after its profile id and formula version
            # inputs are visible in solana fee profile command to domain.
        )


class PumpfunSnipingRunDraftCommand(ApiModel):
    """Strict v3 sniping DTO with one explicit closed execution mode."""

    contract_schema: Literal["pumpfun-sniping-run-draft/v3"] = "pumpfun-sniping-run-draft/v3"
    dataset_revision_id: str = Field(min_length=64, max_length=71)
    snapshot_id: str = Field(min_length=64, max_length=71)
    replay_pack_id: str | None = Field(default=None, min_length=64, max_length=71)
    delivery_schedule_id: str | None = Field(default=None, min_length=64, max_length=71)
    # Declare initial sol balance lamports explicitly in the pumpfun sniping run draft
    # command contract.
    initial_sol_balance_lamports: str = Field(min_length=1, max_length=40)
    gross_buy_budget_lamports: str = Field(min_length=1, max_length=40)
    buy_slippage_bps: int = Field(ge=0, le=10_000)
    sell_slippage_bps: int = Field(ge=0, le=10_000)
    # Unlike fixed latency, settlement mode is an explicit v3 user choice.
    execution_mode: ExecutionMode
    sell_delay_transactions: int = Field(gt=0)
    # Declare wallet account profile explicitly in the pumpfun sniping run draft command
    # contract.
    wallet_account_profile: WalletAccountProfileCommand
    pump_fee_profile: PumpFeeProfileCommand
    buy_solana_fee_profile: SolanaFeeProfileCommand
    sell_solana_fee_profile: SolanaFeeProfileCommand
    root_seed: str = Field(min_length=1, max_length=78)

    @field_validator("execution_mode")
    @classmethod
    def _supported_execution_mode(cls, value: ExecutionMode) -> ExecutionMode:
        # The generic enum includes modes whose Pump.fun semantics are not implemented.
        if value not in PUMPFUN_SNIPING_EXECUTION_MODES:
            raise ValueError("execution_mode is unsupported for Pump.fun Sniping v3")
        return value

    # Define pumpfun sniping run draft command to domain as one focused operation with an
    # explicit boundary.
    def to_domain(self) -> PumpfunSnipingRunDraft:
        # Execute the pumpfun sniping run draft command to domain workflow in explicit,
        # reviewable steps.
        return PumpfunSnipingRunDraft(
            dataset_revision_id=DatasetRevisionId(self.dataset_revision_id),
            snapshot_id=SnapshotId(self.snapshot_id),
            replay_pack_id=(
                None if self.replay_pack_id is None else ReplayPackId(self.replay_pack_id)
                # Complete PumpfunSnipingRunDraft only after its dataset revision id and
                # snapshot id inputs are visible in pumpfun sniping run draft command to
                # domain.
            ),
            delivery_schedule_id=(
                None
                if self.delivery_schedule_id is None
                else DeliveryScheduleId(self.delivery_schedule_id)
                # Complete PumpfunSnipingRunDraft only after its dataset revision id and
                # snapshot id inputs are visible in pumpfun sniping run draft command to
                # domain.
            ),
            initial_sol_balance_lamports=_atomic_decimal(self.initial_sol_balance_lamports),
            gross_buy_budget_lamports=_positive_atomic_decimal(self.gross_buy_budget_lamports),
            buy_slippage_bps=self.buy_slippage_bps,
            sell_slippage_bps=self.sell_slippage_bps,
            execution_mode=self.execution_mode,
            # Pass sell delay transactions explicitly so PumpfunSnipingRunDraft receives a
            # reviewable dataset revision id and snapshot id input in pumpfun sniping run
            # draft command to domain.
            sell_delay_transactions=self.sell_delay_transactions,
            wallet_account_profile=self.wallet_account_profile.to_domain(),
            pump_fee_profile=self.pump_fee_profile.to_domain(),
            buy_solana_fee_profile=self.buy_solana_fee_profile.to_domain(),
            sell_solana_fee_profile=self.sell_solana_fee_profile.to_domain(),
            # Include root seed in the completed pumpfun sniping run draft command to
            # domain result.
            root_seed=_atomic_decimal(self.root_seed),
        )


RunDraftCommand = ReferenceRunDraftCommand | PumpfunSnipingRunDraftCommand


class RunDraftReresolveRequiredError(ValueError):
    """A legacy draft must be reconstructed under the explicit v3 mode contract."""

    code = "RERESOLVE_REQUIRED"

    def __init__(self, contract_schema: str) -> None:
        # Keep the rejected schema available for typed local callers and tests.
        self.contract_schema = contract_schema
        super().__init__(
            "RERESOLVE_REQUIRED: Pump.fun Sniping draft v2 has no explicit execution mode"
        )


# Keep the run contract field response contract and validation rules together.
class RunContractFieldResponse(ApiModel):
    name: str
    kind: str
    required: bool
    enum_values: tuple[str, ...]

    # Apply classmethod semantics to the following run contract field response from domain
    # contract.
    @classmethod
    def from_domain(cls, value: RunContractField) -> Self:
        # Execute the run contract field response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            name=value.name,
            kind=value.kind.value,
            required=value.required,
            enum_values=value.enum_values,
            # Complete cls only after its name and value inputs are visible in run contract
            # field response from domain.
        )


# Keep the run contract response contract and validation rules together.
class RunContractResponse(ApiModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    title: str
    editable_fields: tuple[RunContractFieldResponse, ...]
    fixed_semantics: dict[str, str]

    # Apply classmethod semantics to the following run contract response from domain
    # contract.
    @classmethod
    def from_domain(cls, value: RunContractDescriptor) -> Self:
        # Execute the run contract response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            schema=value.schema,
            title=value.title,
            editable_fields=tuple(
                RunContractFieldResponse.from_domain(item)
                # Pass item explicitly so tuple receives a reviewable from domain and
                # editable fields input in run contract response from domain.
                for item in value.editable_fields
                # Complete tuple only after its from domain and editable fields inputs are
                # visible in run contract response from domain.
            ),
            fixed_semantics=dict(value.fixed_semantics),
        )


class RunContractListResponse(ApiModel):
    items: tuple[RunContractResponse, ...] = Field(max_length=32)


# Define run draft command from bytes as one focused operation with an explicit boundary.
def run_draft_command_from_bytes(payload: bytes) -> RunDraftCommand:
    """Select one closed DTO from its explicit schema without accepting opaque JSON."""

    value = json.loads(payload)
    if not isinstance(value, dict):
        raise TypeError("run draft must be a JSON object")
    schema = value.get("contract_schema")
    # Recognize v2 specifically so it is not confused with arbitrary JSON.
    if schema == PUMPFUN_SNIPING_LEGACY_RUN_DRAFT_SCHEMA:
        raise RunDraftReresolveRequiredError(PUMPFUN_SNIPING_LEGACY_RUN_DRAFT_SCHEMA)
    if schema == PUMPFUN_SNIPING_RUN_DRAFT_SCHEMA:
        # Return the completed run draft command from bytes result without a hidden
        # fallback.
        return PumpfunSnipingRunDraftCommand.model_validate_json(payload)
    if schema is not None:
        raise ValueError("unknown run draft contract_schema")
    return ReferenceRunDraftCommand.model_validate_json(payload)


def run_draft_from_bytes(payload: bytes) -> RunDraft:
    # Return the completed run draft from bytes result without a hidden fallback.
    return run_draft_command_from_bytes(payload).to_domain()


def _atomic_decimal(value: str) -> int:
    # Execute the atomic decimal workflow in explicit, reviewable steps.
    if not value or any(character < "0" or character > "9" for character in value):
        raise ValueError("atomic amount must be an unsigned decimal string")
    if len(value) > 1 and value.startswith("0"):
        raise ValueError("atomic amount must use canonical decimal encoding")
    return int(value)


# Define positive atomic decimal as one focused operation with an explicit boundary.
def _positive_atomic_decimal(value: str) -> int:
    # Execute the positive atomic decimal workflow in explicit, reviewable steps.
    result = _atomic_decimal(value)
    if result <= 0:
        raise ValueError("atomic amount must be positive")
    return result


# Keep the resolved run spec response contract and validation rules together.
class ResolvedRunSpecResponse(ApiModel):
    spec_id: str
    logical_run_id: str
    resolved_spec: dict[str, Any]

    @classmethod
    # Define resolved run spec response from domain as one focused operation with an
    # explicit boundary.
    def from_domain(cls, value: ResolvedRunSpec) -> Self:
        # Execute the resolved run spec response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            spec_id=value.spec_id.hex,
            logical_run_id=value.logical_run_id.hex,
            resolved_spec=value.document(),
        )


# Keep the reference sweep entry command contract and validation rules together.
class ReferenceSweepEntryCommand(ApiModel):
    draft: ReferenceRunDraftCommand
    attempt_nonce: str = Field(min_length=64, max_length=71)
    physical_settings: RunPhysicalSettingsCommand

    def to_domain(self) -> SweepDraftEntry:
        # Execute the reference sweep entry command to domain workflow in explicit,
        # reviewable steps.
        return SweepDraftEntry(
            self.draft.to_domain(),
            ContentDigest(self.attempt_nonce),
            self.physical_settings.to_domain(),
        )


# Keep the reference sweep draft command contract and validation rules together.
class ReferenceSweepDraftCommand(ApiModel):
    entries: tuple[ReferenceSweepEntryCommand, ...] = Field(min_length=1, max_length=1_000)
    comparison_metrics: tuple[RunComparisonMetric, ...] = ()


# Keep the resolved sweep spec response contract and validation rules together.
class ResolvedSweepSpecResponse(ApiModel):
    sweep_spec_id: str
    resolved_sweep_spec: dict[str, Any]

    @classmethod
    def from_domain(cls, value: ResolvedSweepSpec) -> Self:
        # Execute the resolved sweep spec response from domain workflow in explicit,
        # reviewable steps.
        return cls(
            sweep_spec_id=value.sweep_spec_id.hex,
            resolved_sweep_spec=value.document(),
        )


# Keep the fidelity schema contract and validation rules together.
class FidelitySchema(ApiModel):
    identity: IdentityFidelity
    ordering: OrderingFidelity
    state: StateFidelity
    fees: FeesFidelity
    # Declare chain finality explicitly in the fidelity schema contract.
    chain_finality: ChainFinality
    completeness: IngestionCompleteness
    consistency: SourceConsistency

    def to_requirement(self) -> FidelityRequirement:
        # Execute the fidelity schema to requirement workflow in explicit, reviewable
        # steps.
        return FidelityRequirement(
            identity=self.identity,
            ordering=self.ordering,
            state=self.state,
            fees=self.fees,
            # Pass chain finality explicitly so FidelityRequirement receives a reviewable
            # identity and ordering input in fidelity schema to requirement.
            chain_finality=self.chain_finality,
            completeness=self.completeness,
            consistency=self.consistency,
        )


# Keep the settlement requirement input contract and validation rules together.
class SettlementRequirementInput(ApiModel):
    schema_: str = Field(alias="schema", min_length=1, max_length=256, serialization_alias="schema")
    target_stream: CapabilityStream
    settlement_streams: tuple[CapabilityStream, ...] = Field(min_length=1)
    initial_delay_transactions: int = Field(gt=0)
    # Declare minimum duration ns explicitly in the settlement requirement input contract.
    minimum_duration_ns: int = Field(gt=0)
    maximum_followup_delay_transactions: int = Field(gt=0)
    maximum_tail_blocks: int = Field(gt=0)

    def to_domain(self) -> SettlementRequirement:
        # Execute the settlement requirement input to domain workflow in explicit,
        # reviewable steps.
        return SettlementRequirement(
            schema=self.schema_,
            target_stream=self.target_stream,
            settlement_streams=self.settlement_streams,
            initial_delay_transactions=self.initial_delay_transactions,
            # Pass minimum duration ns explicitly so SettlementRequirement receives a
            # reviewable schema and target stream input in settlement requirement input to
            # domain.
            minimum_duration_ns=self.minimum_duration_ns,
            maximum_followup_delay_transactions=self.maximum_followup_delay_transactions,
            maximum_tail_blocks=self.maximum_tail_blocks,
        )


# Keep the requirement input contract and validation rules together.
class RequirementInput(ApiModel):
    origin: RequirementOrigin
    origin_id: str = Field(min_length=1, max_length=256)
    capability_id: str = Field(min_length=1, max_length=256)
    columns: tuple[str, ...] = Field(min_length=1)
    # Declare minimum fidelity explicitly in the requirement input contract.
    minimum_fidelity: FidelitySchema = FidelitySchema(
        identity=IdentityFidelity.UNKNOWN,
        ordering=OrderingFidelity.UNKNOWN,
        state=StateFidelity.NONE,
        fees=FeesFidelity.UNKNOWN,
        # Pass chain finality explicitly so FidelitySchema receives a reviewable unknown
        # and none input in requirement input.
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )
    accepted_protocol_versions: tuple[str, ...] = ()
    # Declare evidence contracts explicitly in the requirement input contract.
    evidence_contracts: tuple[str, ...] = ()
    warmup_blocks: int = Field(default=0, ge=0)
    settlement_tail_blocks: int = Field(default=0, ge=0)
    settlement_requirement: SettlementRequirementInput | None = None

    def to_domain(self) -> DataRequirement:
        # Execute the requirement input to domain workflow in explicit, reviewable steps.
        return DataRequirement(
            origin=self.origin,
            origin_id=self.origin_id,
            capability_id=CapabilityId(self.capability_id),
            columns=self.columns,
            # Include minimum fidelity in the completed requirement input to domain
            # result.
            minimum_fidelity=self.minimum_fidelity.to_requirement(),
            accepted_protocol_versions=self.accepted_protocol_versions,
            evidence_contracts=self.evidence_contracts,
            warmup_blocks=self.warmup_blocks,
            settlement_tail_blocks=self.settlement_tail_blocks,
            # Pass settlement requirement explicitly so DataRequirement receives a
            # reviewable origin and origin id input in requirement input to domain.
            settlement_requirement=(
                None
                if self.settlement_requirement is None
                else self.settlement_requirement.to_domain()
            ),
            # Complete DataRequirement only after its origin and origin id inputs are visible
            # in requirement input to domain.
        )


# Keep the budget limits input contract and validation rules together.
class BudgetLimitsInput(ApiModel):
    max_remote_bytes: int = Field(gt=0)
    max_local_bytes: int = Field(gt=0)
    max_days: int = Field(gt=0)
    temporary_reserve_bytes: int = Field(ge=0)
    # Declare disk low watermark bytes explicitly in the budget limits input contract.
    disk_low_watermark_bytes: int = Field(ge=0)


# Keep the query limits input contract and validation rules together.
class QueryLimitsInput(ApiModel):
    max_execution_seconds: int = Field(gt=0)
    max_memory_bytes: int = Field(gt=0)
    max_result_rows: int | None = Field(default=None, gt=0)


# Keep the plan dataset command contract and validation rules together.
class PlanDatasetCommand(ApiModel):
    source_id: str = Field(min_length=1, max_length=256)
    source_inspection_artifact_id: str = Field(min_length=64, max_length=71)
    network_id: str = Field(min_length=3, max_length=256)
    position_schema_id: str = Field(min_length=1, max_length=256)
    # Declare from block ordinal explicitly in the plan dataset command contract.
    from_block_ordinal: int = Field(ge=0)
    to_block_ordinal: int = Field(gt=0)
    warmup_blocks: int = Field(default=0, ge=0)
    settlement_tail_blocks: int = Field(default=0, ge=0)
    max_shard_blocks: int = Field(gt=0)
    # Declare requested days explicitly in the plan dataset command contract.
    requested_days: int | None = Field(default=None, gt=0)
    requirements: tuple[RequirementInput, ...] = Field(min_length=1)
    budget: BudgetLimitsInput
    query: QueryLimitsInput
    request_remote_estimate: bool = False

    # Define plan dataset command to domain as one focused operation with an explicit
    # boundary.
    def to_domain(self) -> PlanDatasetRequest:
        # Execute the plan dataset command to domain workflow in explicit, reviewable
        # steps.
        network_id = NetworkId(self.network_id)
        position_schema_id = PositionSchemaId(self.position_schema_id)
        return PlanDatasetRequest(
            source_id=SourceId(self.source_id),
            source_inspection_artifact_id=ArtifactId(self.source_inspection_artifact_id),
            # Pass network id explicitly so PlanDatasetRequest receives a reviewable
            # source id and source inspection artifact id input in plan dataset command to
            # domain.
            network_id=network_id,
            position_schema_id=position_schema_id,
            decision_range=BlockRange(
                network_id,
                position_schema_id,
                # Pass self explicitly so BlockRange receives a reviewable from block
                # ordinal and to block ordinal input in plan dataset command to domain.
                self.from_block_ordinal,
                self.to_block_ordinal,
            ),
            warmup_blocks=self.warmup_blocks,
            settlement_tail_blocks=self.settlement_tail_blocks,
            # Pass max shard blocks explicitly so PlanDatasetRequest receives a reviewable
            # source id and source inspection artifact id input in plan dataset command to
            # domain.
            max_shard_blocks=self.max_shard_blocks,
            requested_days=self.requested_days,
            requirements=tuple(item.to_domain() for item in self.requirements),
            budget_limits=BudgetLimits(**self.budget.model_dump()),
            query_limits=QueryLimits(**self.query.model_dump()),
            # Pass request remote estimate explicitly so PlanDatasetRequest receives a
            # reviewable source id and source inspection artifact id input in plan dataset
            # command to domain.
            request_remote_estimate=self.request_remote_estimate,
        )


# Keep the job command contract and validation rules together.
class JobCommand(ApiModel):
    spec_version: int = Field(default=1, gt=0)
    job_type: JobType
    payload: dict[str, Any]
    input_artifact_ids: tuple[str, ...] = Field(default=(), max_length=1_000)

    # Apply field validator semantics to the following job command validate artifact ids
    # contract.
    @field_validator("input_artifact_ids")
    @classmethod
    def validate_artifact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        # Execute the job command validate artifact ids workflow in explicit, reviewable
        # steps.
        try:
            normalized = tuple(sorted(ArtifactId(value).hex for value in values))
        except (TypeError, ValueError) as error:
            raise ValueError("input_artifact_ids contains an invalid content ID") from error
        if len(normalized) != len(set(normalized)):
            # Fail the job command validate artifact ids path with ValueError for input
            # artifact ids must not contain duplicates when normalized is true; do not
            # continue ambiguously.
            raise ValueError("input_artifact_ids must not contain duplicates")
        return normalized

    def payload_bytes(self) -> bytes:
        # Execute the job command payload bytes workflow in explicit, reviewable steps.
        return json.dumps(
            self.payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            # Pass sort keys explicitly so encode receives a reviewable utf-8 input in job
            # command payload bytes.
            sort_keys=True,
        ).encode("utf-8")

    def artifact_ids(self) -> tuple[ArtifactId, ...]:
        return tuple(ArtifactId(value) for value in self.input_artifact_ids)


# Keep the job response contract and validation rules together.
class JobResponse(ApiModel):
    job_id: str
    spec_version: int
    spec_id: str
    job_type: JobType
    # Declare payload digest explicitly in the job response contract.
    payload_digest: str
    input_artifact_count: int = Field(ge=0)
    input_artifact_ids_digest: _DigestHex
    state: AttemptState
    state_version: int
    submitted_at_ns: _CanonicalUnsignedDecimal
    updated_at_ns: _CanonicalUnsignedDecimal

    # Apply classmethod semantics to the following job response from domain contract.
    @classmethod
    def from_domain(cls, record: JobRecord) -> Self:
        return cls.from_view(JobStatusView.from_record(record))

    @classmethod
    def from_view(cls, value: JobStatusView) -> Self:
        # Execute the job response from view workflow in explicit, reviewable steps.
        return cls(
            job_id=value.job_id.value,
            spec_version=value.spec_version,
            spec_id=value.spec_id.hex,
            job_type=value.job_type,
            # Pass payload digest explicitly so cls receives a reviewable value and job id
            # input in job response from view.
            payload_digest=value.payload_digest.hex,
            input_artifact_count=value.input_artifact_count,
            input_artifact_ids_digest=value.input_artifact_ids_digest.hex,
            state=value.state,
            state_version=value.state_version,
            submitted_at_ns=_unsigned_decimal(value.submitted_at_ns),
            updated_at_ns=_unsigned_decimal(value.updated_at_ns),
            # Complete cls only after its value and job id inputs are visible in job response
            # from view.
        )


class JobListResponse(ApiModel):
    items: tuple[JobResponse, ...] = Field(max_length=1_000)
    next_cursor: _PageCursor | None = None


# Keep the job progress response contract and validation rules together.
class JobProgressResponse(ApiModel):
    sequence: int
    level: ProgressLevel
    stage: ProgressStage
    completed_units: int | None
    # Declare total units explicitly in the job progress response contract.
    total_units: int | None
    coalesced_events: int
    dropped_transport_frames: int
    private_rss_bytes: int | None
    total_rss_bytes: int | None
    # Declare major page faults explicitly in the job progress response contract.
    major_page_faults: int | None
    temporary_disk_bytes: int | None

    @classmethod
    def from_domain(cls, value: JobProgressDetails) -> Self:
        # Execute the job progress response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            sequence=value.sequence,
            level=value.level,
            stage=value.stage,
            completed_units=value.completed_units,
            # Pass total units explicitly so cls receives a reviewable sequence and level
            # input in job progress response from domain.
            total_units=value.total_units,
            coalesced_events=value.coalesced_events,
            dropped_transport_frames=value.dropped_transport_frames,
            private_rss_bytes=value.private_rss_bytes,
            total_rss_bytes=value.total_rss_bytes,
            # Pass major page faults explicitly so cls receives a reviewable sequence and
            # level input in job progress response from domain.
            major_page_faults=value.major_page_faults,
            temporary_disk_bytes=value.temporary_disk_bytes,
        )


# Keep the job event response contract and validation rules together.
class JobEventResponse(ApiModel):
    event_id: int
    job_id: str
    attempt_id: str | None
    event_type: str
    # Declare state version explicitly in the job event response contract.
    state_version: int
    created_at_ns: int
    progress: JobProgressResponse | None

    @classmethod
    def from_domain(cls, value: JobEventRecord) -> Self:
        # Execute the job event response from domain workflow in explicit, reviewable
        # steps.
        return cls(
            event_id=value.event_id,
            job_id=value.job_id.value,
            attempt_id=None if value.attempt_id is None else value.attempt_id.value,
            event_type=value.event_type,
            # Pass state version explicitly so cls receives a reviewable event id and
            # value input in job event response from domain.
            state_version=value.state_version,
            created_at_ns=value.created_at_ns,
            progress=(
                None if value.progress is None else JobProgressResponse.from_domain(value.progress)
            ),
            # Complete cls only after its event id and value inputs are visible in job event
            # response from domain.
        )


class JobEventListResponse(ApiModel):
    items: tuple[JobEventResponse, ...]


# Keep the source column response contract and validation rules together.
class SourceColumnResponse(ApiModel):
    name: str
    type_name: str
    nullable: bool


# Keep the source table response contract and validation rules together.
class SourceTableResponse(ApiModel):
    name: str
    engine: str
    partition_key: str
    sorting_key: str
    # Declare columns explicitly in the source table response contract.
    columns: tuple[SourceColumnResponse, ...]


# Keep the capability proofs response contract and validation rules together.
class CapabilityProofsResponse(ApiModel):
    block_time_monotone: EvidenceStatus
    block_time_second_resolution: EvidenceStatus
    bundled_instruction_order: EvidenceStatus
    creation_fields_immutable: EvidenceStatus
    # Declare curve transitions complete explicitly in the capability proofs response
    # contract.
    curve_transitions_complete: EvidenceStatus
    failed_transactions_included: EvidenceStatus
    fee_component_rounding_exact: EvidenceStatus
    global_zero_based_transaction_index: EvidenceStatus
    launch_transaction_success_exact: EvidenceStatus
    # Declare lifecycle complete explicitly in the capability proofs response contract.
    lifecycle_complete: EvidenceStatus
    skipped_blocks_distinguished: EvidenceStatus
    successful_transactions_included: EvidenceStatus
    vote_transactions_included: EvidenceStatus


# Keep the capability response contract and validation rules together.
class CapabilityResponse(ApiModel):
    capability_id: str
    protocol: str
    protocol_version: str
    schema_version: str
    # Declare stream explicitly in the capability response contract.
    stream: CapabilityStream
    columns: tuple[str, ...]
    mandatory_columns: tuple[str, ...]
    fidelity: FidelitySchema
    proofs: CapabilityProofsResponse
    # Declare total key explicitly in the capability response contract.
    total_key: tuple[str, ...]
    keyset_key_is_proven: bool
    utc_pruning_column: str | None
    utc_pruning_is_proven: bool


# Keep the block range response contract and validation rules together.
class BlockRangeResponse(ApiModel):
    network_id: str
    position_schema_id: str
    from_block_ordinal: int
    to_block_ordinal: int


# Keep the cut evidence response contract and validation rules together.
class CutEvidenceResponse(ApiModel):
    capability_id: str
    block_range: BlockRangeResponse
    snapshot_cut_to_block: int
    chain_finality: ChainFinality
    # Declare ingestion watermark to block explicitly in the cut evidence response
    # contract.
    ingestion_watermark_to_block: int | None
    completeness: IngestionCompleteness
    consistency: SourceConsistency
    upstream_revision: str | None


# Keep the source inspection response contract and validation rules together.
class SourceInspectionResponse(ApiModel):
    source_id: str
    network_id: str
    position_schema_id: str
    server_version: str
    # Declare schema fingerprint explicitly in the source inspection response contract.
    schema_fingerprint: str
    capability_mapping_digest: str
    query_template_digest: str
    inspected_at: str
    artifact_id: str
    # Declare evidence receipt ids explicitly in the source inspection response contract.
    evidence_receipt_ids: tuple[str, ...]
    tables: tuple[SourceTableResponse, ...]
    capabilities: tuple[CapabilityResponse, ...]
    cut_evidence: tuple[CutEvidenceResponse, ...]

    @classmethod
    # Define source inspection response from stored as one focused operation with an
    # explicit boundary.
    def from_stored(cls, stored: StoredSourceInspection) -> Self:
        # Execute the source inspection response from stored workflow in explicit,
        # reviewable steps.
        inspection = stored.inspection
        metadata = inspection.metadata
        mapping_digest = metadata.capability_mapping_digest
        query_digest = metadata.query_template_digest
        if mapping_digest is None or query_digest is None:
            # Fail the source inspection response from stored path with ValueError for
            # stored inspection is missing exact source digests when mapping digest and
            # query digest is true; do not continue ambiguously.
            raise ValueError("stored inspection is missing exact source digests")
        return cls(
            source_id=metadata.source_id.value,
            network_id=metadata.network_id.value,
            position_schema_id=metadata.position_schema_id.value,
            # Pass server version explicitly so cls receives a reviewable value and source
            # id input in source inspection response from stored.
            server_version=metadata.server_version,
            schema_fingerprint=inspection.schema_fingerprint.value,
            capability_mapping_digest=mapping_digest.hex,
            query_template_digest=query_digest.hex,
            inspected_at=inspection.inspected_at.isoformat(),
            # Pass artifact id explicitly so cls receives a reviewable value and source id
            # input in source inspection response from stored.
            artifact_id=stored.artifact.artifact_id.value,
            evidence_receipt_ids=tuple(item.receipt_id.hex for item in metadata.evidence_receipts),
            tables=tuple(
                SourceTableResponse(
                    name=table.name,
                    # Pass engine explicitly so SourceTableResponse receives a reviewable
                    # name and engine input in source inspection response from stored.
                    engine=table.engine,
                    partition_key=table.partition_key,
                    sorting_key=table.sorting_key,
                    columns=tuple(
                        SourceColumnResponse(
                            # Pass name explicitly so SourceColumnResponse receives a
                            # reviewable name and type name input in source inspection
                            # response from stored.
                            name=column.name,
                            type_name=column.type_name,
                            nullable=column.nullable,
                        )
                        for column in table.columns
                        # Complete tuple only after its columns and name inputs are visible in
                        # source inspection response from stored.
                    ),
                )
                for table in metadata.tables
            ),
            capabilities=tuple(_capability_response(item) for item in metadata.capabilities),
            # Include cut evidence in the completed source inspection response from stored
            # result.
            cut_evidence=tuple(
                CutEvidenceResponse(
                    capability_id=item.capability_id.value,
                    block_range=_block_range_response(item.block_range),
                    snapshot_cut_to_block=item.snapshot_cut_to_block,
                    # Pass chain finality explicitly so CutEvidenceResponse receives a
                    # reviewable value and capability id input in source inspection
                    # response from stored.
                    chain_finality=item.chain_finality,
                    ingestion_watermark_to_block=item.ingestion_watermark_to_block,
                    completeness=item.completeness,
                    consistency=item.consistency,
                    upstream_revision=item.upstream_revision,
                    # Complete CutEvidenceResponse only after its value and capability id
                    # inputs are visible in source inspection response from stored.
                )
                for item in metadata.cut_evidence
            ),
        )


# Keep the planned capability response contract and validation rules together.
class PlannedCapabilityResponse(ApiModel):
    capability_id: str
    protocol: str
    protocol_version: str
    schema_version: str
    # Declare stream explicitly in the planned capability response contract.
    stream: CapabilityStream
    columns: tuple[str, ...]
    fidelity: FidelitySchema
    proofs: CapabilityProofsResponse
    total_key: tuple[str, ...]
    # Declare keyset key is proven explicitly in the planned capability response contract.
    keyset_key_is_proven: bool
    utc_pruning_column: str | None
    utc_pruning_is_proven: bool


# Keep the dataset shard response contract and validation rules together.
class DatasetShardResponse(ApiModel):
    ordinal: int
    capability_id: str
    block_range: BlockRangeResponse
    columns: tuple[str, ...]


# Keep the capability extraction range response contract and validation rules together.
class CapabilityExtractionRangeResponse(ApiModel):
    capability_id: str
    block_range: BlockRangeResponse


# Keep the settlement requirement response contract and validation rules together.
class SettlementRequirementResponse(ApiModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    target_stream: CapabilityStream
    settlement_streams: tuple[CapabilityStream, ...]
    initial_delay_transactions: int
    # Declare minimum duration ns explicitly in the settlement requirement response
    # contract.
    minimum_duration_ns: int
    maximum_followup_delay_transactions: int
    maximum_tail_blocks: int


# Keep the budget issue response contract and validation rules together.
class BudgetIssueResponse(ApiModel):
    code: str
    kind: str
    message: str
    actual: int | None
    # Declare limit explicitly in the budget issue response contract.
    limit: int | None


# Keep the budget response contract and validation rules together.
class BudgetResponse(ApiModel):
    status: str
    estimated_source_rows: int | None
    estimated_source_bytes: int | None
    requested_days: int | None
    # Declare requested blocks explicitly in the budget response contract.
    requested_blocks: int
    planned_shards: int
    expected_local_parquet_bytes: int | None
    temporary_reserve_bytes: int | None
    current_free_disk_bytes: int | None
    # Declare disk low watermark bytes explicitly in the budget response contract.
    disk_low_watermark_bytes: int
    max_remote_bytes: int
    max_local_bytes: int
    max_days: int
    max_total_blocks: int
    # Declare max total shards explicitly in the budget response contract.
    max_total_shards: int
    max_shard_blocks: int
    issues: tuple[BudgetIssueResponse, ...]


# Keep the dataset plan response contract and validation rules together.
class DatasetPlanResponse(ApiModel):
    spec_version: int
    spec_id: str
    source_id: str
    source_inspection_artifact_id: str
    # Declare source schema fingerprint explicitly in the dataset plan response contract.
    source_schema_fingerprint: str
    capability_mapping_digest: str
    query_template_digest: str
    network_id: str
    position_schema_id: str
    # Declare decision range explicitly in the dataset plan response contract.
    decision_range: BlockRangeResponse
    settlement_tail: BlockRangeResponse | None
    settlement_requirement: SettlementRequirementResponse | None
    warmup_blocks: int
    evidence_contracts: tuple[str, ...]
    # Declare capabilities explicitly in the dataset plan response contract.
    capabilities: tuple[PlannedCapabilityResponse, ...]
    capability_ranges: tuple[CapabilityExtractionRangeResponse, ...]
    cut_evidence: tuple[CutEvidenceResponse, ...]
    shards: tuple[DatasetShardResponse, ...]
    budget: BudgetResponse
    # Declare resolved plan explicitly in the dataset plan response contract.
    resolved_plan: dict[str, Any]

    @classmethod
    def from_domain(cls, plan: DatasetPlan) -> Self:
        # Execute the dataset plan response from domain workflow in explicit, reviewable
        # steps.
        spec = plan.spec
        budget = plan.budget
        return cls(
            spec_version=spec.spec_version,
            spec_id=spec.spec_id.value,
            # Pass source id explicitly so cls receives a reviewable spec version and
            # value input in dataset plan response from domain.
            source_id=spec.source_id.value,
            source_inspection_artifact_id=spec.source_inspection_artifact_id.hex,
            source_schema_fingerprint=spec.source_schema_fingerprint.hex,
            capability_mapping_digest=spec.capability_mapping_digest.hex,
            query_template_digest=spec.query_template_digest.hex,
            # Pass network id explicitly so cls receives a reviewable spec version and
            # value input in dataset plan response from domain.
            network_id=spec.network_id.value,
            position_schema_id=spec.position_schema_id.value,
            decision_range=_block_range_response(spec.decision_range),
            settlement_tail=(
                None
                # Pass spec explicitly so cls receives a reviewable spec version and value
                # input in dataset plan response from domain.
                if spec.settlement_tail is None
                else _block_range_response(spec.settlement_tail)
            ),
            settlement_requirement=(
                None
                # Pass spec explicitly so cls receives a reviewable spec version and value
                # input in dataset plan response from domain.
                if spec.settlement_requirement is None
                else SettlementRequirementResponse(
                    schema=spec.settlement_requirement.schema,
                    target_stream=spec.settlement_requirement.target_stream,
                    settlement_streams=spec.settlement_requirement.settlement_streams,
                    # Pass initial delay transactions explicitly so
                    # SettlementRequirementResponse receives a reviewable schema and
                    # settlement requirement input in dataset plan response from domain.
                    initial_delay_transactions=(
                        spec.settlement_requirement.initial_delay_transactions
                    ),
                    minimum_duration_ns=spec.settlement_requirement.minimum_duration_ns,
                    maximum_followup_delay_transactions=(
                        # Pass spec explicitly so SettlementRequirementResponse receives a
                        # reviewable schema and settlement requirement input in dataset
                        # plan response from domain.
                        spec.settlement_requirement.maximum_followup_delay_transactions
                    ),
                    maximum_tail_blocks=spec.settlement_requirement.maximum_tail_blocks,
                )
            ),
            # Pass warmup blocks explicitly so cls receives a reviewable spec version and
            # value input in dataset plan response from domain.
            warmup_blocks=spec.warmup_blocks,
            evidence_contracts=spec.evidence_contracts,
            capabilities=tuple(
                PlannedCapabilityResponse(
                    capability_id=item.capability_id.value,
                    # Pass protocol explicitly so PlannedCapabilityResponse receives a
                    # reviewable value and capability id input in dataset plan response
                    # from domain.
                    protocol=item.protocol,
                    protocol_version=item.protocol_version,
                    schema_version=item.schema_version,
                    stream=item.stream,
                    columns=item.columns,
                    # Include fidelity in the completed dataset plan response from domain
                    # result.
                    fidelity=_fidelity_response(item.fidelity),
                    proofs=_proofs_response(item.proofs),
                    total_key=item.total_key,
                    keyset_key_is_proven=item.keyset_key_is_proven,
                    utc_pruning_column=item.utc_pruning_column,
                    # Pass utc pruning is proven explicitly so PlannedCapabilityResponse
                    # receives a reviewable value and capability id input in dataset plan
                    # response from domain.
                    utc_pruning_is_proven=item.utc_pruning_is_proven,
                )
                for item in spec.capabilities
            ),
            capability_ranges=tuple(
                # Include capability extraction range response in the completed dataset
                # plan response from domain result.
                CapabilityExtractionRangeResponse(
                    capability_id=item.capability_id.value,
                    block_range=_block_range_response(item.block_range),
                )
                for item in spec.capability_ranges
                # Complete tuple only after its capability ranges and value inputs are visible
                # in dataset plan response from domain.
            ),
            cut_evidence=tuple(
                CutEvidenceResponse(
                    capability_id=item.capability_id.value,
                    block_range=_block_range_response(item.block_range),
                    # Pass snapshot cut to block explicitly so CutEvidenceResponse
                    # receives a reviewable value and capability id input in dataset plan
                    # response from domain.
                    snapshot_cut_to_block=item.snapshot_cut_to_block,
                    chain_finality=item.chain_finality,
                    ingestion_watermark_to_block=item.ingestion_watermark_to_block,
                    completeness=item.completeness,
                    consistency=item.consistency,
                    # Pass upstream revision explicitly so CutEvidenceResponse receives a
                    # reviewable value and capability id input in dataset plan response
                    # from domain.
                    upstream_revision=item.upstream_revision,
                )
                for item in spec.cut_evidence
            ),
            shards=tuple(
                # Include dataset shard response in the completed dataset plan response
                # from domain result.
                DatasetShardResponse(
                    ordinal=shard.ordinal,
                    capability_id=shard.capability_id.value,
                    block_range=_block_range_response(shard.block_range),
                    columns=shard.columns,
                    # Complete DatasetShardResponse only after its ordinal and value inputs
                    # are visible in dataset plan response from domain.
                )
                for shard in spec.shards
            ),
            budget=BudgetResponse(
                status=budget.status.value,
                # Pass estimated source rows explicitly so BudgetResponse receives a
                # reviewable value and status input in dataset plan response from domain.
                estimated_source_rows=budget.estimated_source_rows,
                estimated_source_bytes=budget.estimated_source_bytes,
                requested_days=budget.requested_days,
                requested_blocks=budget.requested_blocks,
                planned_shards=budget.planned_shards,
                # Pass expected local parquet bytes explicitly so BudgetResponse receives
                # a reviewable value and status input in dataset plan response from
                # domain.
                expected_local_parquet_bytes=budget.expected_local_parquet_bytes,
                temporary_reserve_bytes=budget.temporary_reserve_bytes,
                current_free_disk_bytes=budget.current_free_disk_bytes,
                disk_low_watermark_bytes=budget.disk_low_watermark_bytes,
                max_remote_bytes=budget.max_remote_bytes,
                # Pass max local bytes explicitly so BudgetResponse receives a reviewable
                # value and status input in dataset plan response from domain.
                max_local_bytes=budget.max_local_bytes,
                max_days=budget.max_days,
                max_total_blocks=budget.max_total_blocks,
                max_total_shards=budget.max_total_shards,
                max_shard_blocks=budget.max_shard_blocks,
                # Include issues in the completed dataset plan response from domain
                # result.
                issues=tuple(
                    BudgetIssueResponse(
                        code=issue.code,
                        kind=issue.kind.value,
                        message=issue.message,
                        # Pass actual explicitly so BudgetIssueResponse receives a
                        # reviewable code and value input in dataset plan response from
                        # domain.
                        actual=issue.actual,
                        limit=issue.limit,
                    )
                    for issue in budget.issues
                ),
                # Complete BudgetResponse only after its value and status inputs are visible
                # in dataset plan response from domain.
            ),
            resolved_plan=cast(dict[str, Any], json.loads(dataset_plan_bytes(plan))),
        )


def _fidelity_response(value: SourceFidelity) -> FidelitySchema:
    # Execute the fidelity response workflow in explicit, reviewable steps.
    return FidelitySchema(
        identity=value.identity,
        ordering=value.ordering,
        state=value.state,
        fees=value.fees,
        # Pass chain finality explicitly so FidelitySchema receives a reviewable identity
        # and ordering input in fidelity response.
        chain_finality=value.chain_finality,
        completeness=value.completeness,
        consistency=value.consistency,
    )


def _capability_response(value: CapabilityDescriptor) -> CapabilityResponse:
    # Execute the capability response workflow in explicit, reviewable steps.
    return CapabilityResponse(
        capability_id=value.capability_id.value,
        protocol=value.protocol,
        protocol_version=value.protocol_version,
        schema_version=value.schema_version,
        # Pass stream explicitly so CapabilityResponse receives a reviewable value and
        # capability id input in capability response.
        stream=value.stream,
        columns=value.columns,
        mandatory_columns=value.mandatory_columns,
        fidelity=_fidelity_response(value.fidelity),
        proofs=_proofs_response(value.proofs),
        # Pass total key explicitly so CapabilityResponse receives a reviewable value and
        # capability id input in capability response.
        total_key=value.total_key,
        keyset_key_is_proven=value.keyset_key_is_proven,
        utc_pruning_column=value.utc_pruning_column,
        utc_pruning_is_proven=value.utc_pruning_is_proven,
    )


# Define proofs response as one focused operation with an explicit boundary.
def _proofs_response(value: CapabilityProofs) -> CapabilityProofsResponse:
    # Execute the proofs response workflow in explicit, reviewable steps.
    return CapabilityProofsResponse(
        block_time_monotone=value.block_time_monotone,
        block_time_second_resolution=value.block_time_second_resolution,
        bundled_instruction_order=value.bundled_instruction_order,
        creation_fields_immutable=value.creation_fields_immutable,
        # Pass curve transitions complete explicitly so CapabilityProofsResponse receives
        # a reviewable block time monotone and block time second resolution input in
        # proofs response.
        curve_transitions_complete=value.curve_transitions_complete,
        failed_transactions_included=value.failed_transactions_included,
        fee_component_rounding_exact=value.fee_component_rounding_exact,
        global_zero_based_transaction_index=value.global_zero_based_transaction_index,
        launch_transaction_success_exact=value.launch_transaction_success_exact,
        # Pass lifecycle complete explicitly so CapabilityProofsResponse receives a
        # reviewable block time monotone and block time second resolution input in proofs
        # response.
        lifecycle_complete=value.lifecycle_complete,
        skipped_blocks_distinguished=value.skipped_blocks_distinguished,
        successful_transactions_included=value.successful_transactions_included,
        vote_transactions_included=value.vote_transactions_included,
    )


# Define block range response as one focused operation with an explicit boundary.
def _block_range_response(value: BlockRange) -> BlockRangeResponse:
    # Execute the block range response workflow in explicit, reviewable steps.
    return BlockRangeResponse(
        network_id=value.network_id.value,
        position_schema_id=value.position_schema_id.value,
        from_block_ordinal=value.from_block_ordinal,
        to_block_ordinal=value.to_block_ordinal,
        # Complete BlockRangeResponse only after its value and network id inputs are visible
        # in block range response.
    )


def _unsigned_decimal(value: int) -> str:
    # Execute the unsigned decimal workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("unsigned decimal response value must be a non-negative integer")
    return str(value)


def _optional_unsigned_decimal(value: int | None) -> str | None:
    return None if value is None else _unsigned_decimal(value)


# Define signed decimal as one focused operation with an explicit boundary.
def _signed_decimal(value: int) -> str:
    # Execute the signed decimal workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("signed decimal response value must be an integer")
    return str(value)


def _optional_signed_decimal(value: int | None) -> str | None:
    return None if value is None else _signed_decimal(value)


# Bind all once as an explicit module-level contract.
__all__ = [
    "ArtifactDetailsResponse",
    "ArtifactLineageResponse",
    "ArtifactResponse",
    "ChainPositionResponse",
    # Keep the dataset plan response component named inside the all contract.
    "DatasetPlanResponse",
    "ErrorResponse",
    "HealthResponse",
    "JobCommand",
    "JobEventListResponse",
    # Keep the job event response component named inside the all contract.
    "JobEventResponse",
    "JobListResponse",
    "JobProgressResponse",
    "JobResponse",
    "PlanDatasetCommand",
    "PumpfunSnipingDashboardResponse",
    # Keep the pumpfun sniping run draft command component named inside the all contract.
    "PumpfunSnipingRunDraftCommand",
    "PumpfunSnipingRunSummaryResponse",
    "QuoteLiquidityEvidenceResponse",
    "ReferenceMlContractResponse",
    "ReferenceRunDraftCommand",
    "RoundTripCursorResponse",
    # Keep the round trip leg response component named inside the all contract.
    "RoundTripLegResponse",
    "RoundTripPageResponse",
    "RoundTripResponse",
    "RunBacktestCommand",
    "RunComparisonResponse",
    # Keep the run contract list response component named inside the all contract.
    "RunContractListResponse",
    "RunContractResponse",
    "RunDraftCommand",
    "RunDraftReresolveRequiredError",
    "RunListResponse",
    "RunPhysicalSettingsCommand",
    # Keep the run summary response component named inside the all contract.
    "RunSummaryResponse",
    "SourceInspectionResponse",
    "SystemResourcesResponse",
    "run_draft_command_from_bytes",
    "run_draft_from_bytes",
    # Complete the all group only after its semantic components are visible.
]
