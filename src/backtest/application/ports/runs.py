"""Replaceable seams for local replay, exact bundles and run publication."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backtest.application.delivery_schedules import DeliveryScheduleManifest

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import InferenceMode
from backtest.application.models import CommittedArtifact
from backtest.application.run_results import RunPhysicalSettings, SuccessfulRunManifest
from backtest.application.run_specs import ResolvedRunSpec
from backtest.domain.identifiers import (
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    DeliveryScheduleId,
    ExecutionAttemptId,
    FeatureSetId,
    # Include model bundle id so the identifiers dependency remains explicit.
    ModelBundleId,
    ModelScheduleId,
    PredictionSetId,
    ReplayPackId,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)
from backtest.domain.roundtrips import RoundTripRecord
from backtest.engine.causal_data import CausalScalarProvider
from backtest.engine.contracts import (
    # Include default engine physical settings so the contracts dependency remains
    # explicit.
    DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    EnginePhysicalSettings,
    RiskPolicy,
    RunEventSink,
    StrategyInstance,
    # Include venue execution model so the contracts dependency remains explicit.
    VenueExecutionModel,
)
from backtest.engine.reference import ReferenceRunConfig, RunSummary, SlotLatencyModel
from backtest.engine.replay import HistoricalEventSource, ObservationDeliverySource


# Keep the runtime component receipt contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class RuntimeComponentReceipt:
    role: str
    bundle_id: BundleId
    config_digest: ContentDigest

    # Define runtime component receipt post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the runtime component receipt post init workflow in explicit, reviewable
        # steps.
        if not self.role or self.role != self.role.strip():
            raise ValueError("runtime component role must be non-empty and trimmed")


# Keep the resolved runtime components contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedRuntimeComponents:
    strategy: StrategyInstance
    execution_model: VenueExecutionModel
    risk_policy: RiskPolicy
    # Declare latency explicitly in the resolved runtime components contract.
    latency: SlotLatencyModel
    receipts: tuple[RuntimeComponentReceipt, ...]

    def __post_init__(self) -> None:
        # Execute the resolved runtime components post init workflow in explicit,
        # reviewable steps.
        ordered = tuple(sorted(self.receipts, key=lambda item: item.role))
        if ordered != self.receipts or len({item.role for item in ordered}) != len(ordered):
            raise ValueError("runtime receipts must be sorted and unique by role")


# Keep the historical event source factory contract and validation rules together.
@runtime_checkable
class HistoricalEventSourceFactory(Protocol):
    def open_resolved(
        self, spec: ResolvedRunSpec
    ) -> AbstractContextManager[HistoricalEventSource]: ...


# Keep the resolved delivery schedule source contract and validation rules together.
@runtime_checkable
class ResolvedDeliveryScheduleSource(ObservationDeliverySource, Protocol):
    @property
    def delivery_schedule_id(self) -> DeliveryScheduleId: ...

    @property
    # Define resolved delivery schedule source replay pack id as one focused operation
    # with an explicit boundary.
    def replay_pack_id(self) -> ReplayPackId: ...

    @property
    def manifest(self) -> DeliveryScheduleManifest: ...


# Keep the delivery schedule source factory contract and validation rules together.
@runtime_checkable
class DeliveryScheduleSourceFactory(Protocol):
    def open_resolved(
        self, spec: ResolvedRunSpec
    ) -> AbstractContextManager[ResolvedDeliveryScheduleSource]: ...


# Apply dataclass semantics to the following resolved causal overlays contract.
@dataclass(frozen=True, slots=True)
class ResolvedCausalOverlays:
    """Verified execution-only feature/prediction providers and their exact contract."""

    feature_set_ids: tuple[FeatureSetId, ...]
    model_schedule_id: ModelScheduleId | None
    prediction_set_ids: tuple[PredictionSetId, ...]
    embedded_model_bundle_ids: tuple[ModelBundleId, ...]
    inference_mode: InferenceMode
    # Declare inference policy digest explicitly in the resolved causal overlays contract.
    inference_policy_digest: ContentDigest
    snapshot_id: SnapshotId
    replay_pack_id: ReplayPackId
    replay_semantics_id: ContentDigest
    replay_layout_schema_id: ContentDigest
    # Declare runtime lock id explicitly in the resolved causal overlays contract.
    runtime_lock_id: RuntimeLockId
    canonical_exact: bool
    features: CausalScalarProvider | None
    predictions: CausalScalarProvider | None

    def __post_init__(self) -> None:
        # Execute the resolved causal overlays post init workflow in explicit, reviewable
        # steps.
        for values, label in (
            (self.feature_set_ids, "FeatureSet IDs"),
            (self.prediction_set_ids, "PredictionSet IDs"),
            (self.embedded_model_bundle_ids, "embedded ModelBundle IDs"),
        ):
            # Process feature set ids, prediction set ids and embedded model bundle ids
            # inside the bounded resolved causal overlays post init loop.
            if tuple(sorted(values, key=lambda item: item.hex)) != values:
                raise ValueError(f"{label} must be sorted")
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if bool(self.feature_set_ids) != (self.features is not None):
            # Fail the resolved causal overlays post init path with ValueError for feature
            # set ids and provider presence disagree when feature set ids and features is
            # true; do not continue ambiguously.
            raise ValueError("FeatureSet IDs and provider presence disagree")
        if self.inference_mode is InferenceMode.DISABLED:
            # Handle the resolved causal overlays post init inference mode and disabled
            # condition as a distinct block.
            if (
                self.model_schedule_id is not None
                or self.prediction_set_ids
                or self.embedded_model_bundle_ids
                or self.predictions is not None
                # Evaluate the complete resolved causal overlays post init prediction set ids,
                # embedded model bundle ids and model schedule id condition before guarded
                # effects.
            ):
                raise ValueError("disabled inference supplied model or prediction inputs")
        # Handle the resolved causal overlays post init complement of inference mode and
        # disabled explicitly.
        elif self.inference_mode is InferenceMode.FROZEN:
            # Handle the resolved causal overlays post init inference mode and frozen
            # condition as a distinct block.
            if (
                self.model_schedule_id is None
                or not self.prediction_set_ids
                or self.embedded_model_bundle_ids
                or self.predictions is None
                # Evaluate the complete resolved causal overlays post init embedded model
                # bundle ids, model schedule id and prediction set ids condition before
                # guarded effects.
            ):
                raise ValueError("frozen inference overlay contract is incomplete")
        # Handle the resolved causal overlays post init complement of inference mode and
        # frozen explicitly.
        elif self.inference_mode is InferenceMode.EMBEDDED_BATCH:
            # Handle the resolved causal overlays post init inference mode and embedded
            # batch condition as a distinct block.
            if (
                self.model_schedule_id is None
                or self.prediction_set_ids
                or not self.embedded_model_bundle_ids
                or self.predictions is None
                # Evaluate the complete resolved causal overlays post init prediction set ids,
                # model schedule id and embedded model bundle ids condition before guarded
                # effects.
            ):
                raise ValueError("embedded inference overlay contract is incomplete")
        else:
            raise ValueError("unsupported resolved inference mode")


# Keep the causal overlay source factory contract and validation rules together.
@runtime_checkable
class CausalOverlaySourceFactory(Protocol):
    def open_resolved(
        self, spec: ResolvedRunSpec
    ) -> AbstractContextManager[ResolvedCausalOverlays]: ...


# Apply runtime checkable semantics to the following runtime components resolver contract.
@runtime_checkable
class RuntimeComponentsResolver(Protocol):
    def resolve(self, spec: ResolvedRunSpec) -> ResolvedRuntimeComponents: ...


# Keep the run output session contract and validation rules together.
@runtime_checkable
class RunOutputSession(RunEventSink, Protocol):
    def append_roundtrip(self, record: RoundTripRecord) -> None: ...

    def finalize(
        self,
        # Keep the manifest input explicit in the finalize contract.
        manifest: SuccessfulRunManifest,
        *,
        final_balances: tuple[tuple[str, str, str, int], ...],
    ) -> CommittedArtifact: ...

    def abort(self) -> None: ...


# Keep the run output store contract and validation rules together.
@runtime_checkable
class RunOutputStore(Protocol):
    def start(
        self,
        *,
        # Keep the spec input explicit in the start contract.
        spec: ResolvedRunSpec,
        execution_attempt_id: ExecutionAttemptId,
        physical_settings: RunPhysicalSettings,
    ) -> RunOutputSession: ...


# Keep the backtest engine contract and validation rules together.
@runtime_checkable
class BacktestEngine(Protocol):
    def run(
        self,
        *,
        # Keep the source input explicit in the run contract.
        source: HistoricalEventSource,
        strategy: StrategyInstance,
        execution_model: VenueExecutionModel,
        risk_policy: RiskPolicy,
        config: ReferenceRunConfig,
        # Keep the sink input explicit in the run contract.
        sink: RunEventSink | None = None,
        features: CausalScalarProvider | None = None,
        predictions: CausalScalarProvider | None = None,
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
        # Keep the run summary step explicit within the backtest engine run workflow.
    ) -> RunSummary: ...


@runtime_checkable
class BacktestEnginePreflight(Protocol):
    """Optional strict capability proof performed before output staging."""

    def preflight(
        self,
        *,
        source: HistoricalEventSource,
        strategy: StrategyInstance,
        # Keep the execution model input explicit in the preflight contract.
        execution_model: VenueExecutionModel,
        risk_policy: RiskPolicy,
        config: ReferenceRunConfig,
        features: CausalScalarProvider | None,
        predictions: CausalScalarProvider | None,
        # Keep the delivery schedule input explicit in the preflight contract.
        delivery_schedule: ObservationDeliverySource | None,
        physical_settings: EnginePhysicalSettings,
    ) -> None: ...


__all__ = [
    "BacktestEngine",
    # Keep the backtest engine preflight component named inside the all contract.
    "BacktestEnginePreflight",
    "CausalOverlaySourceFactory",
    "DeliveryScheduleSourceFactory",
    "HistoricalEventSourceFactory",
    "ResolvedCausalOverlays",
    # Keep the resolved delivery schedule source component named inside the all contract.
    "ResolvedDeliveryScheduleSource",
    "ResolvedRuntimeComponents",
    "RunOutputSession",
    "RunOutputStore",
    "RuntimeComponentReceipt",
    # Keep the runtime components resolver component named inside the all contract.
    "RuntimeComponentsResolver",
]
