"""Exact artifact-bound resolver for Pump.fun Sniping v1."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import cast

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource

# Import canonical at the visible module dependency boundary.
from backtest.adapters.columnar.arrow.canonical import canonical_writer_bundle_id
from backtest.adapters.columnar.numpy import NumpyMmapReplaySource
from backtest.adapters.delivery_schedule.numpy import NumpyMmapDeliverySchedule
from backtest.adapters.delivery_schedule.numpy.compiler import (
    DELIVERY_WRITER_SETTINGS_DIGEST,
    # Include unit delivery build tools so the compiler dependency remains explicit.
    unit_delivery_build_tools,
)
from backtest.adapters.delivery_schedule.numpy.layout import (
    COMPILER_VERSION as DELIVERY_COMPILER_VERSION,
)
from backtest.application.build_tool_roles import (
    CANONICAL_WRITER_ROLE,
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
)

# Import code bundles at the visible module dependency boundary.
from backtest.application.code_bundles import (
    CodeBundleIntegrityError,
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
)

# Import delivery schedules at the visible module dependency boundary.
from backtest.application.delivery_schedules import DeliveryBuildManifest

# Import build tool roles at the visible module dependency boundary.
from backtest.application.models import SettlementRequirement
from backtest.application.ports.sniping_runs import SnipingHistoricalEventSource
from backtest.application.run_drafts import PumpfunSnipingRunDraft
from backtest.application.run_specs import (
    AssetBalance,
    # Include replay contract so the run specs dependency remains explicit.
    ReplayContract,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_QUOTE_ASSET_ID,
    sniping_component_configs,
)

# Import source contracts at the visible module dependency boundary.
from backtest.application.source_contracts import require_pumpfun_sniping_source_contract
from backtest.bootstrap.reference_bundles import (
    PumpfunSnipingBundleRegistry,
    ReferenceBundleIntegrityError,
)

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.identifiers import BundleId, RuntimeLockId

# Import rng at the visible module dependency boundary.
from backtest.engine.rng import RNG_ALGORITHM


class PumpfunSnipingRunResolutionError(RuntimeError):
    """A draft or its exact artifact closure cannot satisfy sniping v1."""


class PumpfunSnipingRunSpecResolver:
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        runtime_lock_id: RuntimeLockId,
        # Close the init signature after its explicit inputs.
        *,
        parquet_memory_limit_mb: int,
        threads: int,
        bundle_registry: PumpfunSnipingBundleRegistry | None = None,
        expected_projector_bundle_id: BundleId | None = None,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the pumpfun sniping run spec resolver init workflow in explicit,
        # reviewable steps.
        if parquet_memory_limit_mb <= 0 or threads <= 0:
            raise ValueError("resolver reader limits must be positive")
        self._artifacts = artifacts
        self._runtime_lock_id = runtime_lock_id
        self._parquet_memory_limit_mb = parquet_memory_limit_mb
        # Assemble self threads once so the pumpfun sniping run spec resolver init
        # workflow shares one value.
        self._threads = threads
        self._bundle_registry = bundle_registry or PumpfunSnipingBundleRegistry()
        self._expected_projector_bundle_id = expected_projector_bundle_id
        self._build_tools = build_tools or _unit_sniping_resolver_tools()

    def resolve(self, draft: PumpfunSnipingRunDraft) -> ResolvedRunSpec:
        # Execute the pumpfun sniping run spec resolver resolve workflow in explicit,
        # reviewable steps.
        if not isinstance(draft, PumpfunSnipingRunDraft):
            raise TypeError("draft must be PumpfunSnipingRunDraft")
        try:
            closure = self._bundle_registry.snapshot()
        except ReferenceBundleIntegrityError as error:
            # Translate the ReferenceBundleIntegrityError failure through the pumpfun
            # sniping run spec resolver resolve boundary.
            raise PumpfunSnipingRunResolutionError(
                "sniping code bundle closure failed exact source verification"
            ) from error
        configs = sniping_component_configs(draft)
        components = tuple(
            # Keep the create and resolved component create step visible while building
            # components.
            ResolvedComponent.create(
                role=manifest.role,
                bundle_id=manifest.bundle_id,
                api_version=manifest.api_version,
                config=configs[manifest.role],
                # Complete create only after its role and bundle id inputs are visible in
                # pumpfun sniping run spec resolver resolve.
            )
            for manifest in closure.manifests
        )

        if draft.replay_pack_id is None:
            # Handle the pumpfun sniping run spec resolver resolve draft.replay_pack_id is
            # None branch as a distinct logical block.
            selected = CanonicalParquetReplaySource(
                self._artifacts,
                draft.snapshot_id,
                duckdb_memory_limit_mb=self._parquet_memory_limit_mb,
                threads=self._threads,
                # Pass expected projector bundle id explicitly so
                # CanonicalParquetReplaySource receives a reviewable artifacts and
                # snapshot id input in pumpfun sniping run spec resolver resolve.
                expected_projector_bundle_id=self._expected_projector_bundle_id,
                build_tools=self._build_tools,
            )
            source_context: AbstractContextManager[SnipingHistoricalEventSource] = nullcontext(
                cast(SnipingHistoricalEventSource, selected)
                # Complete nullcontext only after its cast and sniping historical event source
                # inputs are visible in pumpfun sniping run spec resolver resolve.
            )
            replay_input = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
        else:
            # Handle the pumpfun sniping run spec resolver resolve complement of
            # draft.replay_pack_id is None explicitly.
            source_context = cast(
                AbstractContextManager[SnipingHistoricalEventSource],
                NumpyMmapReplaySource(
                    self._artifacts,
                    draft.replay_pack_id,
                    # Pass build tools explicitly so NumpyMmapReplaySource receives a
                    # reviewable artifacts and replay pack id input in pumpfun sniping run
                    # spec resolver resolve.
                    build_tools=self._build_tools,
                ),
            )
            replay_input = None

        try:
            # Perform the protected pumpfun sniping run spec resolver resolve operation
            # before explicit failure handling.
            with source_context as typed_source:
                # Keep source context active only for the bounded pumpfun sniping run spec
                # resolver resolve operation.
                if draft.replay_pack_id is not None:
                    # Handle the pumpfun sniping run spec resolver resolve
                    # draft.replay_pack_id is not None branch as a distinct logical block.
                    replay_pack = cast(NumpyMmapReplaySource, typed_source)
                    if replay_pack.snapshot_id != draft.snapshot_id:
                        # Handle the pumpfun sniping run spec resolver resolve snapshot
                        # id, replay pack and draft condition as a distinct block.
                        raise PumpfunSnipingRunResolutionError(
                            "ReplayPack derives from another snapshot"
                        )
                    replay_input = ResolvedReplayInput(
                        ReplayInputFormat.REPLAY_PACK,
                        # Pass replay layout schema id explicitly so ResolvedReplayInput
                        # receives a reviewable replay pack and replay layout schema id
                        # input in pumpfun sniping run spec resolver resolve.
                        replay_layout_schema_id=replay_pack.replay_layout_schema_id,
                        replay_pack_id=draft.replay_pack_id,
                    )
                if typed_source.dataset_revision_id != draft.dataset_revision_id:
                    # Handle the pumpfun sniping run spec resolver resolve dataset
                    # revision id, typed source and draft condition as a distinct block.
                    raise PumpfunSnipingRunResolutionError(
                        "draft dataset revision differs from the exact replay input"
                    )
                if (
                    typed_source.network_id != SOLANA_MAINNET_NETWORK_ID
                    # Keep typed source visible while evaluating the network id, solana
                    # mainnet network id and position schema id guard.
                    or typed_source.position_schema_id != BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
                ):
                    # Handle the pumpfun sniping run spec resolver resolve network id,
                    # solana mainnet network id and position schema id condition as a
                    # distinct block.
                    raise PumpfunSnipingRunResolutionError(
                        "sniping v1 requires the exact Solana block32 transaction contract"
                    )
                if typed_source.dataset_spec.decision_range != typed_source.decision_range:
                    # Handle the pumpfun sniping run spec resolver resolve decision range,
                    # dataset spec and typed source condition as a distinct block.
                    raise PumpfunSnipingRunResolutionError(
                        "replay decision range differs from its embedded DatasetSpec"
                    )
                require_pumpfun_sniping_source_contract(typed_source.dataset_spec)
                settlement_requirement = typed_source.dataset_spec.settlement_requirement
                # The Sniping resolver must reject the separate four-attempt copy settlement family.
                if not isinstance(
                    settlement_requirement, SettlementRequirement
                ):  # contract proves it
                    raise AssertionError("sniping source contract lost settlement requirement")
                if (
                    draft.sell_delay_transactions
                    > settlement_requirement.maximum_followup_delay_transactions
                ):
                    # Handle the pumpfun sniping run spec resolver resolve sell delay
                    # transactions, maximum followup delay transactions and draft
                    # condition as a distinct block.
                    raise PumpfunSnipingRunResolutionError(
                        "sell delay exceeds the maximum prepared settlement contract"
                    )
                clock = typed_source.transaction_clock()
                if (
                    # Keep clock visible while evaluating the network id, position schema
                    # id and clock guard.
                    clock.network_id != typed_source.network_id
                    or clock.position_schema_id != typed_source.position_schema_id
                ):
                    # Handle the pumpfun sniping run spec resolver resolve network id,
                    # position schema id and clock condition as a distinct block.
                    raise PumpfunSnipingRunResolutionError(
                        "transaction clock differs from the replay chain identity"
                    )
                if replay_input is None:  # pragma: no cover - branch assigns above
                    raise AssertionError("ReplayPack input was not resolved")
                spec = ResolvedRunSpec.create(
                    network_id=typed_source.network_id,
                    position_schema_id=typed_source.position_schema_id,
                    dataset_revision_id=typed_source.dataset_revision_id,
                    # Pass logical content hash explicitly so create receives a reviewable
                    # network id and position schema id input in pumpfun sniping run spec
                    # resolver resolve.
                    logical_content_hash=typed_source.logical_content_hash,
                    snapshot_id=draft.snapshot_id,
                    replay_semantics_id=typed_source.replay_semantics_id,
                    replay_input=replay_input,
                    components=components,
                    # Pass runtime lock id explicitly so create receives a reviewable
                    # network id and position schema id input in pumpfun sniping run spec
                    # resolver resolve.
                    runtime_lock_id=self._runtime_lock_id,
                    initial_portfolio=(
                        AssetBalance(
                            PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                            draft.initial_sol_balance_lamports,
                            # Complete AssetBalance only after its initial sol balance
                            # lamports and pumpfun sniping quote asset id inputs are visible
                            # in pumpfun sniping run spec resolver resolve.
                        ),
                    ),
                    root_seed=draft.root_seed,
                    delivery_schedule_id=draft.delivery_schedule_id,
                    replay_contract=ReplayContract.CANONICAL_EXACT,
                    # Complete create only after its network id and position schema id inputs
                    # are visible in pumpfun sniping run spec resolver resolve.
                )

                if draft.delivery_schedule_id is not None:
                    if draft.replay_pack_id is None:  # pragma: no cover - draft proves it
                        raise AssertionError("DeliverySchedule draft has no ReplayPack")
                    replay_layout_schema_id = replay_input.replay_layout_schema_id
                    if replay_layout_schema_id is None:  # pragma: no cover - ReplayPack proves it
                        raise AssertionError("resolved ReplayPack has no layout schema ID")
                    with NumpyMmapDeliverySchedule(
                        self._artifacts,
                        draft.delivery_schedule_id,
                        build_tools=self._build_tools,
                        # Complete NumpyMmapDeliverySchedule only after its artifacts and
                        # delivery schedule id inputs are visible in pumpfun sniping run spec
                        # resolver resolve.
                    ) as schedule:
                        # Keep numpy mmap delivery schedule, artifacts and delivery
                        # schedule id active only for the bounded pumpfun sniping run spec
                        # resolver resolve operation.
                        schedule.require_build(
                            DeliveryBuildManifest(
                                replay_pack_id=draft.replay_pack_id,
                                replay_semantics_id=typed_source.replay_semantics_id,
                                replay_layout_schema_id=replay_layout_schema_id,
                                # Pass components explicitly to require_build for clock
                                # and engine.
                                components=tuple(
                                    component
                                    for component in components
                                    if component.role in {"clock", "engine", "latency", "scheduler"}
                                ),
                                # Pass rng algorithm explicitly so DeliveryBuildManifest
                                # receives a reviewable clock and engine input in pumpfun
                                # sniping run spec resolver resolve.
                                rng_algorithm=RNG_ALGORITHM,
                                root_seed=draft.root_seed,
                                compiler_bundle_id=self._build_tools.require_current(
                                    DELIVERY_COMPILER_ROLE
                                ),
                                # Pass compiler version explicitly so
                                # DeliveryBuildManifest receives a reviewable clock and
                                # engine input in pumpfun sniping run spec resolver
                                # resolve.
                                compiler_version=DELIVERY_COMPILER_VERSION,
                                writer_bundle_id=self._build_tools.require_current(
                                    DELIVERY_WRITER_ROLE
                                ),
                                runtime_lock_id=self._runtime_lock_id,
                                # Pass writer settings digest explicitly so
                                # DeliveryBuildManifest receives a reviewable clock and
                                # engine input in pumpfun sniping run spec resolver
                                # resolve.
                                writer_settings_digest=DELIVERY_WRITER_SETTINGS_DIGEST,
                            )
                        )
                        if (
                            schedule.manifest.network_id != typed_source.network_id
                            # Keep schedule visible while evaluating the network id,
                            # position schema id and decision range guard.
                            or schedule.manifest.position_schema_id
                            != typed_source.position_schema_id
                            or schedule.manifest.decision_range != typed_source.decision_range
                        ):
                            # Handle the pumpfun sniping run spec resolver resolve network
                            # id, position schema id and decision range condition as a
                            # distinct block.
                            raise PumpfunSnipingRunResolutionError(
                                "DeliverySchedule chain or decision range differs from replay"
                            )
        except PumpfunSnipingRunResolutionError:
            raise
        # Translate code bundle integrity error through the pumpfun sniping run spec
        # resolver resolve boundary without hiding other errors.
        except (CodeBundleIntegrityError, RuntimeError, TypeError, ValueError) as error:
            # Translate the code bundle integrity error, runtime error and type error
            # failure through the pumpfun sniping run spec resolver resolve boundary.
            raise PumpfunSnipingRunResolutionError(
                "sniping replay input failed exact source/artifact verification"
            ) from error

        try:
            closure.require_components(spec.components, spec.dependency_merkle_root)
        except CodeBundleIntegrityError as error:  # pragma: no cover - built from closure
            raise PumpfunSnipingRunResolutionError(
                "resolved run differs from its exact sniping bundle closure"
            ) from error
        return spec


def _unit_sniping_resolver_tools() -> PinnedCodeBundleSet:
    # Execute the unit sniping resolver tools workflow in explicit, reviewable steps.
    by_role = {item.role: item for item in unit_delivery_build_tools().identities}
    writer = PinnedCodeBundleIdentity.for_unit_tests(
        CANONICAL_WRITER_ROLE,
        canonical_writer_bundle_id(),
    )
    # Assemble by role[writer role] once so the unit sniping resolver tools workflow
    # shares one value.
    by_role[writer.role] = writer
    return PinnedCodeBundleSet(tuple(sorted(by_role.values(), key=lambda item: item.role)))


__all__ = [
    "PumpfunSnipingRunResolutionError",
    "PumpfunSnipingRunSpecResolver",
    # Complete the all group only after its semantic components are visible.
]
