"""Composition-owned resolver for the checked-in reference strategy stack."""

from __future__ import annotations

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.arrow.canonical import canonical_writer_bundle_id
from backtest.adapters.columnar.numpy import NumpyMmapReplaySource

# Import numpy at the visible module dependency boundary.
from backtest.adapters.delivery_schedule.numpy import NumpyMmapDeliverySchedule
from backtest.adapters.delivery_schedule.numpy.compiler import (
    DELIVERY_WRITER_SETTINGS_DIGEST,
    unit_delivery_build_tools,
)

# Import layout at the visible module dependency boundary.
from backtest.adapters.delivery_schedule.numpy.layout import COMPILER_VERSION
from backtest.adapters.ml.numpy import (
    NumpyMlArtifactFormatError,
    NumpyModelScheduleReader,
    NumpyPredictionSetProvider,
    # Close the numpy import after its required symbols are visible.
)
from backtest.adapters.ml.numpy.overlays import LocalNumpyCausalOverlayFactory
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.application.build_tool_roles import (
    CANONICAL_WRITER_ROLE,
    # Include delivery compiler role so the build tool roles dependency remains explicit.
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
)
from backtest.application.canonical_data import EffectiveSourceBoundary, ValidationStatus
from backtest.application.code_bundles import (
    # Include code bundle integrity error so the code bundles dependency remains explicit.
    CodeBundleIntegrityError,
    ExactCodeBundleClosure,
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
)

# Import delivery schedules at the visible module dependency boundary.
from backtest.application.delivery_schedules import DeliveryBuildManifest
from backtest.application.ml_contracts import ModelCanonicality, ModelUnavailableError
from backtest.application.run_drafts import (
    PumpfunSnipingRunDraft,
    ReferenceRunDraft,
    # Include run draft so the run drafts dependency remains explicit.
    RunDraft,
)
from backtest.application.run_specs import (
    ReplayContract,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.bootstrap.reference_bundles import (
    # Include reference bundle integrity error so the reference bundles dependency remains
    # explicit.
    ReferenceBundleIntegrityError,
    ReferenceBundleRegistry,
)
from backtest.bootstrap.sniping_run_resolver import PumpfunSnipingRunSpecResolver
from backtest.domain.execution import ExecutionMode

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import FidelityRequirement, OrderingFidelity
from backtest.domain.identifiers import BundleId, NetworkId, PositionSchemaId, RuntimeLockId
from backtest.domain.market_events import EventKind
from backtest.engine.replay import ReplayBoundary
from backtest.engine.rng import RNG_ALGORITHM

# Import strategies at the visible module dependency boundary.
from backtest.plugins.strategies import FIRST_SWAP_MINIMUM_FIDELITY

_REFERENCE_ENGINE_MINIMUM_FIDELITY = FidelityRequirement(
    ordering=OrderingFidelity.TRANSACTION_EXACT
)

_DEFAULT_BUNDLE_CLOSURE = ReferenceBundleRegistry().snapshot()


# Define default bundle id as one focused operation with an explicit boundary.
def _default_bundle_id(role: str) -> BundleId:
    return _DEFAULT_BUNDLE_CLOSURE.manifest_for(role).bundle_id


REFERENCE_CLOCK_BUNDLE_ID = _default_bundle_id("clock")
REFERENCE_PROTOCOL_BUNDLE_ID = _default_bundle_id("protocol:reference_amm")
OBSERVED_UNIVERSE_BUNDLE_ID = _default_bundle_id("universe")
# Bind no valuation bundle id once as an explicit module-level contract.
NO_VALUATION_BUNDLE_ID = _default_bundle_id("valuation:price_source")


class ReferenceRunResolutionError(RuntimeError):
    """A draft references incompatible physical inputs or unsupported plugins."""


class ReferenceRunSpecResolver:
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        runtime_lock_id: RuntimeLockId,
        # Close the init signature after its explicit inputs.
        *,
        parquet_memory_limit_mb: int,
        threads: int,
        bundle_registry: ReferenceBundleRegistry | None = None,
        expected_projector_bundle_id: BundleId | None = None,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
        sniping_resolver: PumpfunSnipingRunSpecResolver | None = None,
    ) -> None:
        # Execute the reference run spec resolver init workflow in explicit, reviewable
        # steps.
        if parquet_memory_limit_mb <= 0 or threads <= 0:
            raise ValueError("resolver reader limits must be positive")
        self._artifacts = artifacts
        self._runtime_lock_id = runtime_lock_id
        self._parquet_memory_limit_mb = parquet_memory_limit_mb
        # Assemble self threads once so the reference run spec resolver init workflow
        # shares one value.
        self._threads = threads
        self._bundle_registry = bundle_registry or ReferenceBundleRegistry()
        self._expected_projector_bundle_id = expected_projector_bundle_id
        self._build_tools = build_tools or _unit_reference_resolver_tools()
        self._sniping_resolver = sniping_resolver or PumpfunSnipingRunSpecResolver(
            # Pass artifacts explicitly so PumpfunSnipingRunSpecResolver receives a
            # reviewable build tools and artifacts input in reference run spec resolver
            # init.
            artifacts,
            runtime_lock_id,
            parquet_memory_limit_mb=parquet_memory_limit_mb,
            threads=threads,
            expected_projector_bundle_id=expected_projector_bundle_id,
            # Pass build tools explicitly so PumpfunSnipingRunSpecResolver receives a
            # reviewable build tools and artifacts input in reference run spec resolver
            # init.
            build_tools=self._build_tools,
        )
        self._causal_overlays = LocalNumpyCausalOverlayFactory(
            artifacts,
            build_tools=self._build_tools,
            # Complete LocalNumpyCausalOverlayFactory only after its build tools and artifacts
            # inputs are visible in reference run spec resolver init.
        )

    def resolve(self, draft: RunDraft) -> ResolvedRunSpec:
        # Execute the reference run spec resolver resolve workflow in explicit, reviewable
        # steps.
        if isinstance(draft, PumpfunSnipingRunDraft):
            return self._sniping_resolver.resolve(draft)
        if not isinstance(draft, ReferenceRunDraft):
            # Handle the reference run spec resolver resolve isinstance, draft and
            # reference run draft condition as a distinct block.
            raise ReferenceRunResolutionError(
                "this resolver does not implement the requested run contract"
            )
        if draft.execution_mode not in {
            ExecutionMode.EXOGENOUS_REPLAY,
            # Keep execution mode visible while evaluating the execution mode, draft and
            # exogenous replay guard.
            ExecutionMode.SHADOW_STATE_REPLAY,
        }:
            # Handle the reference run spec resolver resolve execution mode, draft and
            # exogenous replay condition as a distinct block.
            raise ReferenceRunResolutionError(
                "reference resolver does not claim conditional protocol replay"
            )
        try:
            bundle_closure = self._bundle_registry.snapshot()
        # Translate reference bundle integrity error through the reference run spec
        # resolver resolve boundary without hiding other errors.
        except ReferenceBundleIntegrityError as error:
            # Translate the ReferenceBundleIntegrityError failure through the reference
            # run spec resolver resolve boundary.
            raise ReferenceRunResolutionError(
                "reference code bundle closure failed exact source verification"
            ) from error
        components = _components(draft, bundle_closure)
        if draft.replay_pack_id is None:
            # Handle the reference run spec resolver resolve draft.replay_pack_id is None
            # branch as a distinct logical block.
            source = CanonicalParquetReplaySource(
                self._artifacts,
                draft.snapshot_id,
                duckdb_memory_limit_mb=self._parquet_memory_limit_mb,
                threads=self._threads,
                # Pass expected projector bundle id explicitly so
                # CanonicalParquetReplaySource receives a reviewable artifacts and
                # snapshot id input in reference run spec resolver resolve.
                expected_projector_bundle_id=self._expected_projector_bundle_id,
                build_tools=self._build_tools,
            )
            replay_input = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
            source_boundaries = source.source_boundaries
            # Assemble replay boundaries once so the reference run spec resolver resolve
            # workflow shares one value.
            replay_boundaries = source.boundaries()
            decision_boundaries = replay_boundaries if draft.model_schedule_id is not None else ()
        else:
            # Handle the reference run spec resolver resolve complement of
            # draft.replay_pack_id is None explicitly.
            with NumpyMmapReplaySource(
                self._artifacts,
                draft.replay_pack_id,
                build_tools=self._build_tools,
            ) as replay:
                # Keep numpy mmap replay source, artifacts and replay pack id active only
                # for the bounded reference run spec resolver resolve operation.
                if replay.snapshot_id != draft.snapshot_id:
                    raise ReferenceRunResolutionError("ReplayPack derives from another snapshot")
                dataset_revision_id = replay.dataset_revision_id
                logical_content_hash = replay.logical_content_hash
                replay_semantics_id = replay.replay_semantics_id
                # Assemble replay layout schema id once so the reference run spec resolver
                # resolve workflow shares one value.
                replay_layout_schema_id = replay.replay_layout_schema_id
                source_boundaries = replay.source_boundaries
                replay_boundaries = replay.boundaries()
                decision_boundaries = (
                    replay_boundaries if draft.model_schedule_id is not None else ()
                    # Complete the decision boundaries group only after its semantic
                    # components are visible.
                )
            replay_input = ResolvedReplayInput(
                ReplayInputFormat.REPLAY_PACK,
                replay_layout_schema_id=replay_layout_schema_id,
                replay_pack_id=draft.replay_pack_id,
                # Complete ResolvedReplayInput only after its replay pack and replay pack id
                # inputs are visible in reference run spec resolver resolve.
            )
        if draft.replay_pack_id is None:
            # Handle the reference run spec resolver resolve draft.replay_pack_id is None
            # branch as a distinct logical block.
            dataset_revision_id = source.dataset_revision_id
            logical_content_hash = source.logical_content_hash
            replay_semantics_id = source.replay_semantics_id

        _require_reference_fidelity(source_boundaries)
        network_id, position_schema_id = _chain_identity(replay_boundaries)
        # Invoke _require_model_schedule_and_predictions for draft and decision boundaries
        # as a visible reference run spec resolver resolve step.
        self._require_model_schedule_and_predictions(draft, decision_boundaries)

        spec = ResolvedRunSpec.create(
            network_id=network_id,
            position_schema_id=position_schema_id,
            dataset_revision_id=dataset_revision_id,
            # Pass logical content hash explicitly so create receives a reviewable
            # snapshot id and runtime lock id input in reference run spec resolver
            # resolve.
            logical_content_hash=logical_content_hash,
            snapshot_id=draft.snapshot_id,
            replay_semantics_id=replay_semantics_id,
            replay_input=replay_input,
            components=components,
            # Pass runtime lock id explicitly so create receives a reviewable snapshot id
            # and runtime lock id input in reference run spec resolver resolve.
            runtime_lock_id=self._runtime_lock_id,
            initial_portfolio=draft.initial_portfolio,
            root_seed=draft.root_seed,
            feature_set_ids=draft.feature_set_ids,
            model_schedule_id=draft.model_schedule_id,
            # Pass prediction set ids explicitly so create receives a reviewable snapshot
            # id and runtime lock id input in reference run spec resolver resolve.
            prediction_set_ids=draft.prediction_set_ids,
            delivery_schedule_id=draft.delivery_schedule_id,
            replay_contract=ReplayContract.CANONICAL_EXACT,
        )
        try:
            # Invoke require_components for components and dependency merkle root as a
            # visible reference run spec resolver resolve step.
            bundle_closure.require_components(spec.components, spec.dependency_merkle_root)
        except CodeBundleIntegrityError as error:  # pragma: no cover - built from this closure
            raise ReferenceRunResolutionError(
                "resolved run differs from its exact code bundle closure"
            ) from error
        if draft.delivery_schedule_id is not None:
            # Handle the reference run spec resolver resolve draft.delivery_schedule_id is
            # not None branch as a distinct logical block.
            assert draft.replay_pack_id is not None
            with NumpyMmapDeliverySchedule(
                self._artifacts,
                draft.delivery_schedule_id,
                build_tools=self._build_tools,
                # Complete NumpyMmapDeliverySchedule only after its artifacts and delivery
                # schedule id inputs are visible in reference run spec resolver resolve.
            ) as schedule:
                # Keep numpy mmap delivery schedule, artifacts and delivery schedule id
                # active only for the bounded reference run spec resolver resolve
                # operation.
                delivery_layout_id = spec.replay_input.replay_layout_schema_id
                if delivery_layout_id is None:  # pragma: no cover - ReplayPack branch proves it
                    raise AssertionError("resolved ReplayPack has no layout schema ID")
                expected = DeliveryBuildManifest(
                    replay_pack_id=draft.replay_pack_id,
                    replay_semantics_id=spec.replay_semantics_id,
                    replay_layout_schema_id=delivery_layout_id,
                    # Keep the item and components tuple step visible while building
                    # expected.
                    components=tuple(
                        item
                        for item in components
                        if item.role in {"clock", "engine", "latency", "scheduler"}
                    ),
                    # Pass rng algorithm explicitly so DeliveryBuildManifest receives a
                    # reviewable clock and engine input in reference run spec resolver
                    # resolve.
                    rng_algorithm=RNG_ALGORITHM,
                    root_seed=draft.root_seed,
                    compiler_bundle_id=self._build_tools.require_current(DELIVERY_COMPILER_ROLE),
                    compiler_version=COMPILER_VERSION,
                    writer_bundle_id=self._build_tools.require_current(DELIVERY_WRITER_ROLE),
                    # Pass runtime lock id explicitly so DeliveryBuildManifest receives a
                    # reviewable clock and engine input in reference run spec resolver
                    # resolve.
                    runtime_lock_id=self._runtime_lock_id,
                    writer_settings_digest=DELIVERY_WRITER_SETTINGS_DIGEST,
                )
                schedule.require_build(expected)
        if draft.feature_set_ids or draft.prediction_set_ids:
            # Handle the reference run spec resolver resolve feature set ids, prediction
            # set ids and draft condition as a distinct block.
            try:
                self._causal_overlays.verify_resolved(spec)
            except Exception as error:
                # Translate the Exception failure through the reference run spec resolver
                # resolve boundary.
                raise ReferenceRunResolutionError(
                    "causal overlays do not satisfy the exact resolved replay contract"
                ) from error
        return spec

    def _require_model_schedule_and_predictions(
        # Keep the remaining require model schedule and predictions inputs visible at the
        # reference run spec resolver require model schedule and predictions boundary.
        self,
        draft: ReferenceRunDraft,
        decision_boundaries: tuple[ReplayBoundary, ...],
    ) -> None:
        # Execute the reference run spec resolver require model schedule and predictions
        # workflow in explicit, reviewable steps.
        schedule_id = draft.model_schedule_id
        if schedule_id is None:
            if draft.prediction_set_ids:  # pragma: no cover - draft validates this invariant
                raise ReferenceRunResolutionError(
                    "PredictionSets require an exact ModelSchedule ID"
                )
            return
        try:
            # Perform the protected reference run spec resolver require model schedule and
            # predictions operation before explicit failure handling.
            with NumpyModelScheduleReader(
                self._artifacts,
                schedule_id,
                build_tools=self._build_tools,
            ) as schedule:
                # Keep numpy model schedule reader, artifacts and schedule id active only
                # for the bounded reference run spec resolver require model schedule and
                # predictions operation.
                if schedule.canonicality is not ModelCanonicality.CANONICAL_EXACT:
                    # Handle the reference run spec resolver require model schedule and
                    # predictions canonicality, canonical exact and schedule condition as
                    # a distinct block.
                    raise ReferenceRunResolutionError(
                        "canonical run requires a CANONICAL_EXACT ModelSchedule"
                    )
                for boundary in decision_boundaries:
                    schedule.model_for(boundary.boundary_ordinal)
            # Traverse draft.prediction_set_ids explicitly so each reference run spec
            # resolver require model schedule and predictions iteration remains traceable.
            for prediction_id in draft.prediction_set_ids:
                # Process draft.prediction_set_ids inside the bounded reference run spec
                # resolver require model schedule and predictions loop.
                with NumpyPredictionSetProvider(
                    self._artifacts,
                    prediction_id,
                    build_tools=self._build_tools,
                ) as prediction:
                    # Keep numpy prediction set provider, artifacts and prediction id
                    # active only for the bounded reference run spec resolver require
                    # model schedule and predictions operation.
                    if prediction.model_schedule_id != schedule_id:
                        # Handle the reference run spec resolver require model schedule
                        # and predictions model schedule id, schedule id and prediction
                        # condition as a distinct block.
                        raise ReferenceRunResolutionError(
                            "PredictionSet references another ModelSchedule"
                        )
        except ReferenceRunResolutionError:
            raise
        # Translate model unavailable error through the reference run spec resolver
        # require model schedule and predictions boundary without hiding other errors.
        except ModelUnavailableError as error:
            # Translate the ModelUnavailableError failure through the reference run spec
            # resolver require model schedule and predictions boundary.
            raise ReferenceRunResolutionError(
                "ModelSchedule has no eligible model for a replay decision"
            ) from error
        except (NumpyMlArtifactFormatError, RuntimeError, TypeError, ValueError) as error:
            # Translate the numpy ml artifact format error, runtime error and type error
            # failure through the reference run spec resolver require model schedule and
            # predictions boundary.
            raise ReferenceRunResolutionError(
                "model schedule or prediction input failed exact verification"
            ) from error


def _require_reference_fidelity(
    boundaries: tuple[EffectiveSourceBoundary, ...],
    # Close the require reference fidelity signature after its explicit inputs.
) -> None:
    # Execute the require reference fidelity workflow in explicit, reviewable steps.
    if not boundaries:
        raise ReferenceRunResolutionError("snapshot contains no source fidelity boundaries")
    saw_swap = False
    failures: list[str] = []
    for boundary in boundaries:
        # Process boundaries inside the bounded require reference fidelity loop.
        if boundary.source_boundary.validation_status is not ValidationStatus.PASS:
            # Handle the require reference fidelity validation status, pass and source
            # boundary condition as a distinct block.
            failures.append(
                f"{boundary.source_boundary.capability_id.value}:validation_status="
                f"{boundary.source_boundary.validation_status.value}<PASS"
            )
        requirements = [_REFERENCE_ENGINE_MINIMUM_FIDELITY]
        # Evaluate the complete require reference fidelity event kind, venue trade and
        # boundary condition before guarded effects.
        if boundary.event_kind is EventKind.VENUE_TRADE:
            # Handle the require reference fidelity event kind, venue trade and boundary
            # condition as a distinct block.
            saw_swap = True
            requirements.append(FIRST_SWAP_MINIMUM_FIDELITY)
        required = FidelityRequirement.combine(tuple(requirements))
        for gap in boundary.source_fidelity.gaps(required):
            # Process gaps, required and source fidelity inside the bounded require
            # reference fidelity loop.
            failures.append(
                f"{boundary.source_boundary.capability_id.value}:{gap.field}="
                f"{gap.available}<{gap.required}"
            )
    if not saw_swap:
        # Handle the require reference fidelity not saw_swap branch as a distinct logical
        # block.
        raise ReferenceRunResolutionError(
            "reference strategy requires a committed SWAP capability boundary"
        )
    if failures:
        # Handle the require reference fidelity failures branch as a distinct logical
        # block.
        raise ReferenceRunResolutionError(
            "source fidelity does not satisfy the resolved reference stack: "
            + ", ".join(sorted(failures))
        )


def _chain_identity(
    # Keep the boundaries input explicit in the chain identity contract.
    boundaries: tuple[ReplayBoundary, ...],
) -> tuple[NetworkId, PositionSchemaId]:
    # Execute the chain identity workflow in explicit, reviewable steps.
    if not boundaries:
        raise ReferenceRunResolutionError("snapshot contains no replay boundaries")
    identity = (boundaries[0].network_id, boundaries[0].position_schema_id)
    if any(
        (boundary.network_id, boundary.position_schema_id) != identity
        # Pass boundary explicitly so any receives a reviewable network id and position
        # schema id input in chain identity.
        for boundary in boundaries
        # Complete any only after its network id and position schema id inputs are visible in
        # chain identity.
    ):
        raise ReferenceRunResolutionError("snapshot mixes network or position identities")
    return identity


def _unit_reference_resolver_tools() -> PinnedCodeBundleSet:
    # Execute the unit reference resolver tools workflow in explicit, reviewable steps.
    by_role = {item.role: item for item in unit_ml_build_tools().identities}
    by_role.update({item.role: item for item in unit_delivery_build_tools().identities})
    canonical_writer = PinnedCodeBundleIdentity.for_unit_tests(
        CANONICAL_WRITER_ROLE,
        canonical_writer_bundle_id(),
        # Complete for_unit_tests only after its canonical writer bundle id and canonical
        # writer role inputs are visible in unit reference resolver tools.
    )
    by_role[canonical_writer.role] = canonical_writer
    return PinnedCodeBundleSet(tuple(sorted(by_role.values(), key=lambda item: item.role)))


def _components(
    draft: ReferenceRunDraft,
    # Keep the bundle closure input explicit in the components contract.
    bundle_closure: ExactCodeBundleClosure,
) -> tuple[ResolvedComponent, ...]:
    # Execute the components workflow in explicit, reviewable steps.
    def bundle_id(role: str) -> BundleId:
        return bundle_closure.manifest_for(role).bundle_id

    values = (
        ResolvedComponent.create(
            role="clock",
            # Register clock through bundle_id so the values table remains scannable.
            bundle_id=bundle_id("clock"),
            config={"duration_mapping": "ceil-to-next-boundary-v1"},
        ),
        ResolvedComponent.create(
            role="engine",
            # Register engine through bundle_id so the values table remains scannable.
            bundle_id=bundle_id("engine"),
            config={"maximum_dynamic_items": draft.maximum_dynamic_items},
        ),
        ResolvedComponent.create(
            role="execution",
            # Register execution through bundle_id so the values table remains scannable.
            bundle_id=bundle_id("execution"),
            config={"fee_bps": draft.fee_bps, "mode": draft.execution_mode.value},
        ),
        ResolvedComponent.create(
            role="inference",
            # Register inference through bundle_id so the values table remains scannable.
            bundle_id=bundle_id("inference"),
            config=draft.inference_policy.document(),
        ),
        ResolvedComponent.create(
            role="latency",
            # Register latency through bundle_id so the values table remains scannable.
            bundle_id=bundle_id("latency"),
            config={
                "observation_slots": draft.observation_slots,
                "order_slots": draft.order_slots,
            },
            # Complete create only after its latency and observation slots inputs are visible
            # in components.
        ),
        ResolvedComponent.create(
            role="protocol:reference_amm",
            bundle_id=bundle_id("protocol:reference_amm"),
            config={"version": 1},
            # Complete create only after its protocol:reference amm and version inputs are
            # visible in components.
        ),
        ResolvedComponent.create(
            role="risk",
            bundle_id=bundle_id("risk"),
            config={"maximum_order_input_atomic": draft.maximum_order_input_atomic},
            # Complete create only after its risk and maximum order input atomic inputs are
            # visible in components.
        ),
        ResolvedComponent.create(
            role="scheduler",
            bundle_id=bundle_id("scheduler"),
            config={"phase_table": "canonical-v1"},
            # Complete create only after its scheduler and phase table inputs are visible in
            # components.
        ),
        ResolvedComponent.create(
            role="strategy",
            bundle_id=bundle_id("strategy"),
            config={
                # Keep amount in atomic named so the strategy and amount in atomic payload
                # passed to create remains self-describing within components.
                "amount_in_atomic": draft.amount_in_atomic,
                "bought_asset_id": draft.bought_asset_id.value,
                "minimum_amount_out_atomic": draft.minimum_amount_out_atomic,
                "pool_id": draft.pool_id.value,
                "sold_asset_id": draft.sold_asset_id.value,
                # Close the strategy and amount in atomic payload only after all components
                # fields are present.
            },
        ),
        ResolvedComponent.create(
            role="universe",
            bundle_id=bundle_id("universe"),
            # Pass policy explicitly so create receives a reviewable universe and policy
            # input in components.
            config={"policy": "point-in-time-observed-assets-v1"},
        ),
        ResolvedComponent.create(
            role="valuation:price_source",
            bundle_id=bundle_id("valuation:price_source"),
            # Pass policy explicitly so create receives a reviewable valuation:price
            # source and policy input in components.
            config={"policy": "none-v1"},
        ),
    )
    return tuple(sorted(values, key=lambda item: item.role))


__all__ = [
    # Keep the no valuation bundle id component named inside the all contract.
    "NO_VALUATION_BUNDLE_ID",
    "OBSERVED_UNIVERSE_BUNDLE_ID",
    "REFERENCE_CLOCK_BUNDLE_ID",
    "REFERENCE_PROTOCOL_BUNDLE_ID",
    "ReferenceRunResolutionError",
    # Keep the reference run spec resolver component named inside the all contract.
    "ReferenceRunSpecResolver",
]
