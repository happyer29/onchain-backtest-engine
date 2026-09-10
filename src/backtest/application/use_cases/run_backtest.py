"""Preflight and execute one exact local backtest against committed inputs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field

# Import datetime at the visible module dependency boundary.
from datetime import UTC, datetime
from typing import Any, cast

from backtest.application.copy_run_contract import (
    copy_draft_from_spec,
    is_copy_run_spec,
    # Preparation compatibility is checked independently of runtime component construction.
    require_copy_preparation,
)
from backtest.application.ml_contracts import InferenceMode
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.copy_runs import CopyRuntimeResolver, ResolvedCopyRuntime

# Core-owned runtime ports preserve application independence from concrete plugins.
from backtest.application.ports.runs import (
    # Include backtest engine so the runs dependency remains explicit.
    BacktestEngine,
    BacktestEnginePreflight,
    CausalOverlaySourceFactory,
    DeliveryScheduleSourceFactory,
    HistoricalEventSourceFactory,
    # Include resolved causal overlays so the runs dependency remains explicit.
    ResolvedCausalOverlays,
    ResolvedDeliveryScheduleSource,
    ResolvedRuntimeComponents,
    RunOutputSession,
    RunOutputStore,
    # Include runtime components resolver so the runs dependency remains explicit.
    RuntimeComponentsResolver,
)
from backtest.application.ports.sniping_runs import (
    ResolvedSnipingRuntimeComponents,
    SnipingBacktestEngine,
    # Include sniping historical event source so the sniping runs dependency remains
    # explicit.
    SnipingHistoricalEventSource,
    SnipingRuntimeComponentsResolver,
)
from backtest.application.run_results import (
    RunBackend,
    # Include run comparison projection so the run results dependency remains explicit.
    RunComparisonProjection,
    RunPhysicalSettings,
    SuccessfulRunManifest,
    validate_run_warnings,
)

# Import run specs at the visible module dependency boundary.
from backtest.application.run_specs import ReplayContract, ResolvedComponent, ResolvedRunSpec
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_QUOTE_ASSET_ID,
    is_pumpfun_sniping_spec,
)

# Import source contracts at the visible module dependency boundary.
from backtest.application.source_contracts import require_pumpfun_sniping_source_contract
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    ExecutionAttemptId,
    # Include logical run id so the identifiers dependency remains explicit.
    LogicalRunId,
)
from backtest.engine.contracts import EnginePhysicalSettings
from backtest.engine.copytrading_run import CopyRunSink, CopyRunSummary, run_copy_backtest
from backtest.engine.reference import ReferenceRunConfig, RunSummary

# Historical input is an immutable local event source, never a source SQL client.
from backtest.engine.replay import HistoricalEventSource

# Import rng at the visible module dependency boundary.
from backtest.engine.rng import RNG_ALGORITHM
from backtest.engine.sniping import SnipingRunConfig, SnipingRunSummary
from backtest.engine.sniping_contracts import SnipingRunEventSink


class RunPreflightError(RuntimeError):
    """Exact resolved inputs or runtime components are incompatible."""


@dataclass(frozen=True, slots=True)
class RunBacktestRequest:
    resolved_spec: ResolvedRunSpec
    attempt_nonce: ContentDigest
    physical_settings: RunPhysicalSettings = field(
        # Keep the run physical settings and reference python RunPhysicalSettings step
        # visible while building physical settings.
        default_factory=lambda: RunPhysicalSettings(
            backend=RunBackend.REFERENCE_PYTHON,
            reader_batch_rows=65_536,
            reader_readahead=1,
            output_buffer_rows=8_192,
            # Pass threads explicitly so RunPhysicalSettings receives a reviewable
            # reference python and run backend input in run backtest request.
            threads=1,
        )
    )


# Keep the run backtest result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RunBacktestResult:
    logical_run_id: LogicalRunId
    execution_attempt_id: ExecutionAttemptId
    canonical_result_hash: ContentDigest
    # Declare artifact explicitly in the run backtest result contract.
    artifact: CommittedArtifact
    comparison: RunComparisonProjection
    physical_settings: RunPhysicalSettings
    canonicality: ReplayContract
    warnings: tuple[str, ...]

    # Define run backtest result post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the run backtest result post init workflow in explicit, reviewable
        # steps.
        if self.artifact.kind is not ArtifactKind.RUN:
            raise ValueError("a RunBacktestResult requires a committed Run artifact")
        if self.canonical_result_hash != self.comparison.canonical_result_hash:
            raise ValueError("run result hash differs from its comparison projection")
        if self.canonicality is not ReplayContract.CANONICAL_EXACT:
            # Fail the run backtest result post init path with ValueError for a successful
            # run result must be canonical exact when canonicality, canonical exact and
            # replay contract is true; do not continue ambiguously.
            raise ValueError("a successful run result must be CANONICAL_EXACT")
        validate_run_warnings(self.warnings)


# Keep the prepared run contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _PreparedRun:
    spec: ResolvedRunSpec
    physical_settings: RunPhysicalSettings
    engine: BacktestEngine
    # Declare source explicitly in the prepared run contract.
    source: HistoricalEventSource
    runtime: ResolvedRuntimeComponents
    schedule: ResolvedDeliveryScheduleSource | None
    overlays: ResolvedCausalOverlays | None
    run_config: ReferenceRunConfig
    # Declare engine settings explicitly in the prepared run contract.
    engine_settings: EnginePhysicalSettings


# Keep the prepared sniping run contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _PreparedSnipingRun:
    spec: ResolvedRunSpec
    physical_settings: RunPhysicalSettings
    engine: SnipingBacktestEngine
    # Declare source explicitly in the prepared sniping run contract.
    source: SnipingHistoricalEventSource
    runtime: ResolvedSnipingRuntimeComponents
    schedule: ResolvedDeliveryScheduleSource | None
    run_config: SnipingRunConfig
    engine_settings: EnginePhysicalSettings


@dataclass(frozen=True, slots=True)
class _PreparedCopyRun:
    """Exact source and fresh copy components are held open through execution/publication."""

    spec: ResolvedRunSpec
    source: SnipingHistoricalEventSource
    runtime: ResolvedCopyRuntime


# Keep the run backtest contract and validation rules together.
class RunBacktest:
    def __init__(
        self,
        source_factory: HistoricalEventSourceFactory,
        components: RuntimeComponentsResolver,
        # Keep the engine input explicit in the init contract.
        engine: BacktestEngine,
        outputs: RunOutputStore,
        *,
        delivery_schedules: DeliveryScheduleSourceFactory | None = None,
        causal_overlays: CausalOverlaySourceFactory | None = None,
        # Keep the additional engines input explicit in the init contract.
        additional_engines: Mapping[str, BacktestEngine] | None = None,
        sniping_components: SnipingRuntimeComponentsResolver | None = None,
        copy_components: CopyRuntimeResolver | None = None,
        sniping_engine: SnipingBacktestEngine | None = None,
        additional_sniping_engines: Mapping[str, SnipingBacktestEngine] | None = None,
        # Process thread limits remain an operational admission requirement for every backend.
        required_threads: int | None = None,
        # Keep the clock input explicit in the init contract.
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Execute the run backtest init workflow in explicit, reviewable steps.
        self._source_factory = source_factory
        self._components = components
        engines: dict[str, BacktestEngine] = {"reference-python-v1": engine}
        for backend_name, reference_candidate in (additional_engines or {}).items():
            # Process (additional_engines or {}).items() inside the bounded run backtest
            # init loop.
            if not backend_name or backend_name != backend_name.strip() or backend_name in engines:
                raise ValueError("additional run backend names must be unique and trimmed")
            engines[backend_name] = reference_candidate
        self._engines = engines
        sniping_engines: dict[str, SnipingBacktestEngine] = {}
        # Guard this path with sniping_engine is not None before applying effects.
        if sniping_engine is not None:
            sniping_engines[sniping_engine.backend_name] = sniping_engine
        for backend_name, sniping_candidate in (additional_sniping_engines or {}).items():
            # Process items and additional sniping engines inside the bounded run backtest
            # init loop.
            if (
                not backend_name
                or backend_name != backend_name.strip()
                or backend_name in sniping_engines
                or sniping_candidate.backend_name != backend_name
                # Evaluate the complete run backtest init backend name, sniping engines and
                # strip condition before guarded effects.
            ):
                # Handle the run backtest init backend name, sniping engines and strip
                # condition as a distinct block.
                raise ValueError(
                    "additional sniping backend names must be unique, exact and trimmed"
                )
            sniping_engines[backend_name] = sniping_candidate
        self._sniping_components = sniping_components
        # Copy runtime injection is separate from the established Sniping engine registry.
        self._copy_components = copy_components
        # Assemble self sniping engines once so the run backtest init workflow shares one
        # value.
        self._sniping_engines = sniping_engines
        self._outputs = outputs
        self._delivery_schedules = delivery_schedules
        self._causal_overlays = causal_overlays
        if required_threads is not None and (
            # Keep isinstance visible while evaluating the required threads and isinstance
            # guard.
            isinstance(required_threads, bool)
            or not isinstance(required_threads, int)
            or required_threads <= 0
        ):
            raise ValueError("required run threads must be a positive integer")
        # Assemble self required threads once so the run backtest init workflow shares one
        # value.
        self._required_threads = required_threads
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, request: RunBacktestRequest) -> RunBacktestResult:
        # Execute the run backtest execute workflow in explicit, reviewable steps.
        spec = request.resolved_spec
        attempt_id = spec.execution_attempt_id(
            request.attempt_nonce,
            request.physical_settings.identity_digest,
        )
        # Acquire open preflighted, spec and physical settings at an explicit run backtest
        # execute context boundary so cleanup remains scoped.
        with self._open_preflighted(spec, request.physical_settings) as prepared:
            # Keep open preflighted, spec and physical settings active only for the
            # bounded run backtest execute operation.
            output = self._outputs.start(
                spec=spec,
                execution_attempt_id=attempt_id,
                physical_settings=request.physical_settings,
            )
            # Assemble started at once so the run backtest execute workflow shares one
            # value.
            started_at = _aware_now(self._clock)
            try:
                # Perform the protected run backtest execute operation before explicit
                # failure handling.
                summary = _execute_prepared(prepared, output)
                completed_at = _aware_now(self._clock)
                manifest = SuccessfulRunManifest.create(
                    resolved_spec=spec,
                    attempt_nonce=request.attempt_nonce,
                    # Pass execution attempt id explicitly so create receives a reviewable
                    # attempt nonce and physical settings input in run backtest execute.
                    execution_attempt_id=attempt_id,
                    input_artifact_ids=_run_input_artifacts(spec),
                    summary=summary,
                    physical_settings=request.physical_settings,
                    started_at=started_at,
                    # Pass completed at explicitly so create receives a reviewable attempt
                    # nonce and physical settings input in run backtest execute.
                    completed_at=completed_at,
                )
                committed = output.finalize(
                    manifest,
                    final_balances=summary.final_balances,
                    # Complete finalize only after its final balances and manifest inputs are
                    # visible in run backtest execute.
                )
            except BaseException:
                # Translate the BaseException failure through the run backtest execute
                # boundary.
                output.abort()
                raise
        return RunBacktestResult(
            logical_run_id=manifest.logical_run_id,
            execution_attempt_id=manifest.execution_attempt_id,
            # Pass canonical result hash explicitly so RunBacktestResult receives a
            # reviewable logical run id and execution attempt id input in run backtest
            # execute.
            canonical_result_hash=manifest.summary.result_hash,
            artifact=committed,
            comparison=manifest.comparison,
            physical_settings=manifest.physical_settings,
            canonicality=manifest.canonicality,
            # Pass warnings explicitly so RunBacktestResult receives a reviewable logical
            # run id and execution attempt id input in run backtest execute.
            warnings=manifest.warnings,
        )

    def execute_summary(
        self,
        spec: ResolvedRunSpec,
        # Keep the physical settings input explicit in the execute summary contract.
        physical_settings: RunPhysicalSettings,
    ) -> RunSummary | SnipingRunSummary | CopyRunSummary:
        """Execute exact semantics without staging/publishing result bytes.

        This is intentionally narrower than ``execute`` and exists for the
        artifact-bound benchmark harness. It performs the identical input and
        engine preflight, but measures the engine/ML workload rather than the
        output publication protocol.
        """

        with self._open_preflighted(spec, physical_settings) as prepared:
            return _execute_prepared(prepared, None)

    @contextmanager
    def _open_preflighted(
        self,
        # Keep the spec input explicit in the open preflighted contract.
        spec: ResolvedRunSpec,
        physical_settings: RunPhysicalSettings,
    ) -> Iterator[_PreparedRun | _PreparedSnipingRun | _PreparedCopyRun]:
        # Execute the run backtest open preflighted workflow in explicit, reviewable
        # steps.
        if is_copy_run_spec(spec):
            with self._open_preflighted_copy(spec, physical_settings) as copy_prepared:
                yield copy_prepared
            return
        if is_pumpfun_sniping_spec(spec):
            # Handle the run backtest open preflighted is_pumpfun_sniping_spec(spec)
            # branch as a distinct logical block.
            with self._open_preflighted_sniping(spec, physical_settings) as prepared:
                yield prepared
            return
        if physical_settings.backend.is_pumpfun_sniping:
            raise RunPreflightError("Pump.fun Sniping backend cannot execute a FirstSwap spec")
        # Evaluate the complete run backtest open preflighted replay contract, canonical
        # exact and spec condition before guarded effects.
        if spec.replay_contract is not ReplayContract.CANONICAL_EXACT:
            raise RunPreflightError("reference engine refuses a non-canonical tolerance run")
        if (
            self._required_threads is not None
            and physical_settings.threads != self._required_threads
            # Evaluate the complete run backtest open preflighted required threads, threads
            # and physical settings condition before guarded effects.
        ):
            # Handle the run backtest open preflighted required threads, threads and
            # physical settings condition as a distinct block.
            raise RunPreflightError(
                "physical run threads differ from the configured process thread limit"
            )
        try:
            engine = self._engines[physical_settings.backend.value]
        # Translate key error through the run backtest open preflighted boundary without
        # hiding other errors.
        except KeyError as error:
            raise RunPreflightError("selected physical run backend is not installed") from error
        runtime = self._components.resolve(spec)
        with self._source_factory.open_resolved(spec) as source, ExitStack() as input_stack:
            # Keep open resolved, spec and source factory active only for the bounded run
            # backtest open preflighted operation.
            schedule: ResolvedDeliveryScheduleSource | None = None
            overlays: ResolvedCausalOverlays | None = None
            if spec.delivery_schedule_id is not None:
                # Handle the run backtest open preflighted spec.delivery_schedule_id is
                # not None branch as a distinct logical block.
                if self._delivery_schedules is None:
                    # Handle the run backtest open preflighted self._delivery_schedules is
                    # None branch as a distinct logical block.
                    raise RunPreflightError(
                        "resolved run declares a DeliverySchedule but no reader is configured"
                    )
                try:
                    # Perform the protected run backtest open preflighted operation before
                    # explicit failure handling.
                    schedule = input_stack.enter_context(
                        self._delivery_schedules.open_resolved(spec)
                    )
                except Exception as error:
                    # Translate the Exception failure through the run backtest open
                    # preflighted boundary.
                    raise RunPreflightError(
                        "resolved DeliverySchedule failed exact verification"
                    ) from error
            if spec.feature_set_ids or spec.inference_policy().mode is not InferenceMode.DISABLED:
                # Handle the run backtest open preflighted feature set ids, spec and mode
                # condition as a distinct block.
                if self._causal_overlays is None:
                    # Handle the run backtest open preflighted self._causal_overlays is
                    # None branch as a distinct logical block.
                    raise RunPreflightError(
                        "resolved run declares causal overlays but no reader is configured"
                    )
                try:
                    overlays = input_stack.enter_context(self._causal_overlays.open_resolved(spec))
                # Translate exception through the run backtest open preflighted boundary
                # without hiding other errors.
                except Exception as error:
                    # Translate the Exception failure through the run backtest open
                    # preflighted boundary.
                    raise RunPreflightError(
                        "resolved causal overlays failed exact verification"
                    ) from error
            _preflight(spec, source, runtime, schedule, overlays)
            run_config = ReferenceRunConfig(
                # Keep the execution mode and spec execution_mode step visible while
                # building run config.
                execution_mode=spec.execution_mode(),
                latency=runtime.latency,
                root_seed=spec.root_seed,
                initial_available={
                    item.asset_id: item.amount_atomic
                    # Pass item explicitly so ReferenceRunConfig receives a reviewable
                    # engine and execution mode input in run backtest open preflighted.
                    for item in spec.initial_portfolio
                    # Close the engine and execution mode payload only after all run backtest
                    # open preflighted fields are present.
                },
                maximum_dynamic_items=_maximum_dynamic_items(spec),
                engine_bundle_id=_component(spec, "engine").bundle_id,
            )
            engine_settings = EnginePhysicalSettings(
                # Pass reader batch rows explicitly so EnginePhysicalSettings receives a
                # reviewable reader batch rows and reader readahead input in run backtest
                # open preflighted.
                reader_batch_rows=physical_settings.reader_batch_rows,
                reader_readahead=physical_settings.reader_readahead,
                threads=physical_settings.threads,
            )
            if isinstance(engine, BacktestEnginePreflight):
                # Handle the run backtest open preflighted engine backtest engine
                # preflight type condition as a distinct block.
                engine.preflight(
                    source=source,
                    strategy=runtime.strategy,
                    execution_model=runtime.execution_model,
                    risk_policy=runtime.risk_policy,
                    # Pass config explicitly so preflight receives a reviewable strategy
                    # and execution model input in run backtest open preflighted.
                    config=run_config,
                    features=None if overlays is None else overlays.features,
                    predictions=None if overlays is None else overlays.predictions,
                    delivery_schedule=schedule,
                    physical_settings=engine_settings,
                    # Complete preflight only after its strategy and execution model inputs
                    # are visible in run backtest open preflighted.
                )
            yield _PreparedRun(
                spec,
                physical_settings,
                engine,
                # Pass source explicitly so _PreparedRun receives a reviewable spec and
                # physical settings input in run backtest open preflighted.
                source,
                runtime,
                schedule,
                overlays,
                run_config,
                # Pass engine settings explicitly so _PreparedRun receives a reviewable
                # spec and physical settings input in run backtest open preflighted.
                engine_settings,
            )

    @contextmanager
    def _open_preflighted_copy(
        self, spec: ResolvedRunSpec, settings: RunPhysicalSettings
    ) -> Iterator[_PreparedCopyRun]:
        """Reject incompatible source, runtime, backend or physical admission before outputs."""
        if (
            settings.backend is not RunBackend.REFERENCE_PUMPFUN_COPY_BUY
            or self._copy_components is None
        ):
            raise RunPreflightError("copy run requires its installed reference backend")
        # A valid backend still must fit the configured child-process thread limit.
        if self._required_threads is not None and settings.threads != self._required_threads:
            raise RunPreflightError("copy threads differ from the configured process thread limit")
        # Runtime verifies exact configs and rejects unsupported overlays/schedules.
        runtime = self._copy_components.resolve(spec)
        draft = copy_draft_from_spec(spec)
        with self._source_factory.open_resolved(spec) as source:
            if not isinstance(source, SnipingHistoricalEventSource):
                raise RunPreflightError("copy source has no verified DatasetSpec and clock")
            # Bind the readers' verified manifest identities to the resolved spec.
            for name in (
                "dataset_revision_id",
                "logical_content_hash",
                "replay_semantics_id",
                "network_id",
                # Position schema is verified alongside dataset, semantics and immutable network
                # identity.
                "position_schema_id",
            ):
                if getattr(source, name) != getattr(spec, name):
                    raise RunPreflightError("copy replay identity differs from the resolved spec")
            # Source manifests must prove the full prepared signer and settlement contract.
            require_copy_preparation(source.dataset_spec, draft.signing_wallets, draft.policy)
            if source.decision_range != source.dataset_spec.decision_range:
                raise RunPreflightError("copy decision range differs from its verified manifest")
            # No receipt may be omitted, added, reordered or substituted before engine mutation.
            expected = tuple(
                (item.role, item.bundle_id, item.config_digest) for item in spec.components
            )
            # Actual runtime receipts must preserve the same complete canonical component order.
            actual = tuple(
                (item.role, item.bundle_id, item.config_digest)
                for item in runtime.receipts
                # Receipts must match the complete resolved component tuple in canonical order.
            )
            if actual != expected:
                raise RunPreflightError("copy runtime receipts differ from resolved components")
            bundles = {item.role: item.bundle_id for item in spec.components}
            # Check actual strategy operands as well as its claimed bundle receipt.
            if (
                runtime.strategy.bundle_id != bundles["strategy"]
                or runtime.strategy.policy != draft.policy
                or runtime.strategy.signing_wallets != draft.signing_wallets
            ):
                # A changed wallet set or policy rejects execution before opening output
                # publication.
                raise RunPreflightError("copy strategy instance differs from its resolved receipt")
            # Verify actual instances as well as receipt strings before any wallet can mutate.
            protocol = runtime.protocol_factory()
            if protocol.bundle_id != bundles["protocol:pumpfun"]:
                raise RunPreflightError("copy protocol instance differs from its resolved receipt")
            if protocol.trade_payload_schema_id.value != "pumpfun-copybuy-trade-payload-v1":
                raise RunPreflightError("copy protocol requires exact signer-bearing payloads")
            # The network cost model cannot substitute a different installed component.
            if runtime.network_costs.bundle_id != bundles["network:solana"]:
                raise RunPreflightError("copy fee instance differs from its resolved receipt")
            # Initial cash and execution mode are semantic operands, never physical settings.
            if (
                runtime.config.initial_quote_balance_atomic != draft.initial_sol_balance_lamports
                or runtime.config.execution_mode != draft.execution_mode
            ):
                raise RunPreflightError("copy wallet config differs from its resolved draft")
            # Only fully verified local inputs and runtime instances enter the prepared copy run.
            yield _PreparedCopyRun(spec, source, runtime)

    @contextmanager
    def _open_preflighted_sniping(
        self,
        # Keep the spec input explicit in the open preflighted sniping contract.
        spec: ResolvedRunSpec,
        physical_settings: RunPhysicalSettings,
    ) -> Iterator[_PreparedSnipingRun]:
        # Execute the run backtest open preflighted sniping workflow in explicit,
        # reviewable steps.
        if spec.replay_contract is not ReplayContract.CANONICAL_EXACT:
            raise RunPreflightError("sniping engine refuses a non-canonical tolerance run")
        if not physical_settings.backend.is_pumpfun_sniping:
            raise RunPreflightError("Pump.fun Sniping spec requires a sniping backend")
        if (
            # Keep self visible while evaluating the required threads, threads and
            # physical settings guard.
            self._required_threads is not None
            and physical_settings.threads != self._required_threads
        ):
            # Handle the run backtest open preflighted sniping required threads, threads
            # and physical settings condition as a distinct block.
            raise RunPreflightError(
                "physical run threads differ from the configured process thread limit"
            )
        if self._sniping_components is None:
            raise RunPreflightError("Pump.fun Sniping runtime is not installed")
        # Keep expected failures inside the run backtest open preflighted sniping error
        # boundary.
        try:
            engine = self._sniping_engines[physical_settings.backend.value]
        except KeyError as error:
            raise RunPreflightError("selected Pump.fun Sniping backend is not installed") from error
        try:
            # Assemble runtime once so the run backtest open preflighted sniping workflow
            # shares one value.
            runtime = self._sniping_components.resolve(spec)
        except (RuntimeError, TypeError, ValueError) as error:
            raise RunPreflightError("Pump.fun Sniping runtime failed exact resolution") from error
        with self._source_factory.open_resolved(spec) as source, ExitStack() as input_stack:
            # Keep open resolved, spec and source factory active only for the bounded run
            # backtest open preflighted sniping operation.
            if not isinstance(source, SnipingHistoricalEventSource):
                # Handle the run backtest open preflighted sniping isinstance, source and
                # sniping historical event source condition as a distinct block.
                raise RunPreflightError(
                    "resolved replay input has no exact DatasetSpec/transaction clock contract"
                )
            schedule: ResolvedDeliveryScheduleSource | None = None
            if spec.delivery_schedule_id is not None:
                # Handle the run backtest open preflighted sniping
                # spec.delivery_schedule_id is not None branch as a distinct logical
                # block.
                if self._delivery_schedules is None:
                    # Handle the run backtest open preflighted sniping
                    # self._delivery_schedules is None branch as a distinct logical block.
                    raise RunPreflightError(
                        "resolved sniping run declares a DeliverySchedule "
                        "but no reader is configured"
                    )
                try:
                    # Perform the protected run backtest open preflighted sniping
                    # operation before explicit failure handling.
                    schedule = input_stack.enter_context(
                        self._delivery_schedules.open_resolved(spec)
                    )
                except Exception as error:
                    # Translate the Exception failure through the run backtest open
                    # preflighted sniping boundary.
                    raise RunPreflightError(
                        "resolved sniping DeliverySchedule failed exact verification"
                    ) from error
            _preflight_sniping(spec, source, runtime, schedule)
            run_config = SnipingRunConfig(
                # Pass quote asset id explicitly so SnipingRunConfig receives a reviewable
                # engine and decision range input in run backtest open preflighted
                # sniping.
                quote_asset_id=PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                decision_range=source.decision_range,
                initial_available={
                    item.asset_id: item.amount_atomic for item in spec.initial_portfolio
                },
                # Pass wallet account profile explicitly so SnipingRunConfig receives a
                # reviewable engine and decision range input in run backtest open
                # preflighted sniping.
                initial_uva_state=runtime.initial_uva_state,
                wallet_account_profile_id=runtime.wallet_account_profile_id,
                uva_schema_id=runtime.uva_schema_id,
                root_seed=spec.root_seed,
                maximum_dynamic_items=runtime.maximum_dynamic_items,
                # The selected semantic mode is resolved, never inferred from the backend.
                execution_mode=spec.execution_mode(),
                # Keep the spec _component step visible while building run config.
                engine_bundle_id=_component(spec, "engine").bundle_id,
            )
            yield _PreparedSnipingRun(
                spec=spec,
                physical_settings=physical_settings,
                # Pass engine explicitly so _PreparedSnipingRun receives a reviewable
                # reader batch rows and reader readahead input in run backtest open
                # preflighted sniping.
                engine=engine,
                source=source,
                runtime=runtime,
                schedule=schedule,
                run_config=run_config,
                # Keep the engine settings step explicit within the run backtest open
                # preflighted sniping workflow.
                engine_settings=EnginePhysicalSettings(
                    reader_batch_rows=physical_settings.reader_batch_rows,
                    reader_readahead=physical_settings.reader_readahead,
                    threads=physical_settings.threads,
                ),
                # Complete _PreparedSnipingRun only after its reader batch rows and reader
                # readahead inputs are visible in run backtest open preflighted sniping.
            )


def _execute_prepared(
    prepared: _PreparedRun | _PreparedSnipingRun | _PreparedCopyRun,
    output: RunOutputSession | None,
) -> RunSummary | SnipingRunSummary | CopyRunSummary:
    # Execute the execute prepared workflow in explicit, reviewable steps.
    if isinstance(prepared, _PreparedCopyRun):
        return run_copy_backtest(
            source=prepared.source,
            clock=prepared.source.transaction_clock(),
            decision_range=prepared.source.decision_range,
            # The runtime strategy receives only its verified point-in-time local source.
            strategy=prepared.runtime.strategy,
            # Fresh protocol state and a per-run wallet are constructed only inside replay.
            protocol_factory=prepared.runtime.protocol_factory,
            network_costs=prepared.runtime.network_costs,
            config=prepared.runtime.config,
            sink=None if output is None else cast(CopyRunSink, output),
        )
    # Sniping execution continues through its existing distinct implementation branch.
    if isinstance(prepared, _PreparedSnipingRun):
        # Handle the execute prepared prepared prepared sniping run type condition as a
        # distinct block.
        return prepared.engine.run(
            source=prepared.source,
            clock=prepared.source.transaction_clock(),
            strategy=prepared.runtime.strategy,
            protocol=prepared.runtime.protocol,
            # Pass network costs explicitly so run receives a reviewable source and
            # transaction clock input in execute prepared.
            network_costs=prepared.runtime.network_costs,
            config=prepared.run_config,
            sink=None if output is None else cast(SnipingRunEventSink, output),
            delivery_schedule=prepared.schedule,
            physical_settings=prepared.engine_settings,
            # Complete run only after its source and transaction clock inputs are visible in
            # execute prepared.
        )
    overlays = prepared.overlays
    return prepared.engine.run(
        source=prepared.source,
        strategy=prepared.runtime.strategy,
        # Pass execution model explicitly so run receives a reviewable source and strategy
        # input in execute prepared.
        execution_model=prepared.runtime.execution_model,
        risk_policy=prepared.runtime.risk_policy,
        config=prepared.run_config,
        sink=output,
        features=None if overlays is None else overlays.features,
        # Pass predictions explicitly so run receives a reviewable source and strategy
        # input in execute prepared.
        predictions=None if overlays is None else overlays.predictions,
        delivery_schedule=prepared.schedule,
        physical_settings=prepared.engine_settings,
    )


def _preflight_sniping(
    # Keep the spec input explicit in the preflight sniping contract.
    spec: ResolvedRunSpec,
    source: SnipingHistoricalEventSource,
    runtime: ResolvedSnipingRuntimeComponents,
    schedule: ResolvedDeliveryScheduleSource | None,
) -> None:
    # Execute the preflight sniping workflow in explicit, reviewable steps.
    for field_name in (
        "dataset_revision_id",
        "logical_content_hash",
        "replay_semantics_id",
        "network_id",
        # Traverse dataset revision id, logical content hash and replay semantics id
        # explicitly so each preflight sniping iteration remains traceable.
        "position_schema_id",
    ):
        # Process dataset revision id, logical content hash and replay semantics id inside
        # the bounded preflight sniping loop.
        if getattr(source, field_name) != getattr(spec, field_name):
            # Handle the preflight sniping getattr, source and field name condition as a
            # distinct block.
            raise RunPreflightError(
                f"Pump.fun Sniping replay input {field_name} differs from ResolvedRunSpec"
            )
    dataset_spec = source.dataset_spec
    if (
        # Keep dataset spec visible while evaluating the network id, position schema id
        # and decision range guard.
        dataset_spec.network_id != spec.network_id
        or dataset_spec.position_schema_id != spec.position_schema_id
        or dataset_spec.decision_range != source.decision_range
    ):
        raise RunPreflightError("Pump.fun Sniping DatasetSpec differs from the replay input")
    # Invoke require_pumpfun_sniping_source_contract for dataset spec as a visible
    # preflight sniping step.
    require_pumpfun_sniping_source_contract(dataset_spec)
    clock = source.transaction_clock()
    if clock.network_id != spec.network_id or clock.position_schema_id != spec.position_schema_id:
        raise RunPreflightError("Pump.fun Sniping transaction clock uses another chain")

    by_role = {component.role: component for component in spec.components}
    # Assemble receipts once so the preflight sniping workflow shares one value.
    receipts = {item.role: item for item in runtime.receipts}
    if set(receipts) != set(by_role):
        raise RunPreflightError("sniping runtime returned an incomplete or extra receipt set")
    for role in sorted(by_role):
        # Process sorted(by_role) inside the bounded preflight sniping loop.
        expected = by_role[role]
        receipt = receipts[role]
        if (
            receipt.bundle_id != expected.bundle_id
            or receipt.config_digest != expected.config_digest
            # Evaluate the complete preflight sniping bundle id, config digest and receipt
            # condition before guarded effects.
        ):
            # Handle the preflight sniping bundle id, config digest and receipt condition
            # as a distinct block.
            raise RunPreflightError(
                f"sniping runtime {role} receipt differs from resolved component"
            )
    if runtime.strategy.bundle_id != receipts["strategy"].bundle_id:
        raise RunPreflightError("sniping strategy instance differs from its receipt")
    # Evaluate the complete preflight sniping bundle id, protocol and runtime condition
    # before guarded effects.
    if runtime.protocol.bundle_id != receipts["protocol:pumpfun"].bundle_id:
        raise RunPreflightError("Pump runtime instance differs from its receipt")
    if runtime.network_costs.bundle_id != receipts["network:solana"].bundle_id:
        raise RunPreflightError("Solana cost model differs from its receipt")
    _preflight_delivery_schedule(spec, schedule)
    # Guard this path with schedule is not None before applying effects.
    if schedule is not None:
        # Handle the preflight sniping schedule is not None branch as a distinct logical
        # block.
        manifest = schedule.manifest
        if (
            manifest.network_id != spec.network_id
            or manifest.position_schema_id != spec.position_schema_id
            or manifest.decision_range != source.decision_range
            # Evaluate the complete preflight sniping network id, position schema id and
            # decision range condition before guarded effects.
        ):
            # Handle the preflight sniping network id, position schema id and decision
            # range condition as a distinct block.
            raise RunPreflightError(
                "Pump.fun Sniping DeliverySchedule chain or decision range differs"
            )


def _preflight(
    spec: ResolvedRunSpec,
    # Keep the source input explicit in the preflight contract.
    source: object,
    runtime: ResolvedRuntimeComponents,
    schedule: ResolvedDeliveryScheduleSource | None,
    overlays: ResolvedCausalOverlays | None,
) -> None:
    # Execute the preflight workflow in explicit, reviewable steps.
    for field_name in (
        "dataset_revision_id",
        "logical_content_hash",
        "replay_semantics_id",
    ):
        # Process dataset revision id, logical content hash and replay semantics id inside
        # the bounded preflight loop.
        if getattr(source, field_name, None) != getattr(spec, field_name):
            raise RunPreflightError(f"replay input {field_name} differs from ResolvedRunSpec")

    by_role = {component.role: component for component in spec.components}
    receipts = {item.role: item for item in runtime.receipts}
    required_runtime_roles = set(by_role)
    # Evaluate the complete preflight required runtime roles and receipts condition before
    # guarded effects.
    if set(receipts) != required_runtime_roles:
        raise RunPreflightError("runtime resolver returned an incomplete or extra receipt set")
    for role in sorted(required_runtime_roles):
        # Process sorted(required_runtime_roles) inside the bounded preflight loop.
        expected = by_role[role]
        receipt = receipts[role]
        if (
            receipt.bundle_id != expected.bundle_id
            or receipt.config_digest != expected.config_digest
            # Evaluate the complete preflight bundle id, config digest and receipt condition
            # before guarded effects.
        ):
            raise RunPreflightError(f"runtime {role} receipt differs from resolved component")
    if runtime.strategy.bundle_id != receipts["strategy"].bundle_id:
        raise RunPreflightError("strategy instance bundle differs from runtime receipt")
    if runtime.execution_model.bundle_id != receipts["execution"].bundle_id:
        # Fail the preflight path with RunPreflightError for execution instance bundle
        # differs from runtime receipt when bundle id, execution model and runtime is
        # true; do not continue ambiguously.
        raise RunPreflightError("execution instance bundle differs from runtime receipt")
    if runtime.risk_policy.bundle_id != receipts["risk"].bundle_id:
        raise RunPreflightError("risk instance bundle differs from runtime receipt")
    if runtime.latency.bundle_id != receipts["latency"].bundle_id:
        raise RunPreflightError("latency instance bundle differs from runtime receipt")
    # Evaluate the complete preflight config digest, latency and runtime condition before
    # guarded effects.
    if runtime.latency.config_digest != receipts["latency"].config_digest:
        raise RunPreflightError("latency config differs from runtime receipt")
    _preflight_delivery_schedule(spec, schedule)
    _preflight_causal_overlays(spec, overlays)


def _preflight_causal_overlays(
    # Keep the spec input explicit in the preflight causal overlays contract.
    spec: ResolvedRunSpec,
    overlays: ResolvedCausalOverlays | None,
) -> None:
    # Execute the preflight causal overlays workflow in explicit, reviewable steps.
    policy = spec.inference_policy()
    requires_overlays = bool(spec.feature_set_ids) or policy.mode is not InferenceMode.DISABLED
    if not requires_overlays:
        # Handle the preflight causal overlays not requires_overlays branch as a distinct
        # logical block.
        if overlays is not None:
            raise RunPreflightError("runtime supplied unresolved causal overlays")
        return
    if overlays is None:  # pragma: no cover - execute rejects before preflight
        raise RunPreflightError("resolved causal overlays were not opened")
    replay_pack_id = spec.replay_input.replay_pack_id
    replay_layout_id = spec.replay_input.replay_layout_schema_id
    if replay_pack_id is None or replay_layout_id is None:
        raise RunPreflightError("causal overlays require an exact ReplayPack input")
    # Evaluate the complete preflight causal overlays feature set ids, overlays and spec
    # condition before guarded effects.
    if overlays.feature_set_ids != spec.feature_set_ids:
        raise RunPreflightError("opened FeatureSet identities differ from ResolvedRunSpec")
    if overlays.prediction_set_ids != spec.prediction_set_ids:
        raise RunPreflightError("opened PredictionSet identities differ from ResolvedRunSpec")
    if (
        # Keep overlays visible while evaluating the inference mode, mode and inference
        # policy digest guard.
        overlays.inference_mode is not policy.mode
        or overlays.inference_policy_digest != policy.inference_policy_digest
    ):
        raise RunPreflightError("opened inference policy differs from ResolvedRunSpec")
    if overlays.model_schedule_id != spec.model_schedule_id:
        # Fail the preflight causal overlays path with RunPreflightError for opened model
        # schedule identity differs from resolved run spec when model schedule id,
        # overlays and spec is true; do not continue ambiguously.
        raise RunPreflightError("opened ModelSchedule identity differs from ResolvedRunSpec")
    if (
        overlays.snapshot_id != spec.snapshot_id
        or overlays.replay_pack_id != replay_pack_id
        or overlays.replay_semantics_id != spec.replay_semantics_id
        # Keep overlays visible while evaluating the snapshot id, replay pack id and
        # replay semantics id guard.
        or overlays.replay_layout_schema_id != replay_layout_id
    ):
        raise RunPreflightError("causal overlay replay contract differs from ResolvedRunSpec")
    if overlays.runtime_lock_id != spec.runtime_lock_id:
        raise RunPreflightError("causal overlay runtime lock differs from ResolvedRunSpec")
    # Guard this path with not overlays.canonical_exact before applying effects.
    if not overlays.canonical_exact:
        raise RunPreflightError("canonical run refuses tolerance-mode causal overlays")


def _preflight_delivery_schedule(
    spec: ResolvedRunSpec,
    schedule: ResolvedDeliveryScheduleSource | None,
    # Close the preflight delivery schedule signature after its explicit inputs.
) -> None:
    # Execute the preflight delivery schedule workflow in explicit, reviewable steps.
    schedule_id = spec.delivery_schedule_id
    if schedule_id is None:
        # Handle the preflight delivery schedule schedule_id is None branch as a distinct
        # logical block.
        if schedule is not None:
            raise RunPreflightError("runtime supplied an unresolved DeliverySchedule")
        return
    if schedule is None:  # pragma: no cover - execute rejects before preflight
        raise RunPreflightError("resolved DeliverySchedule was not opened")
    replay_pack_id = spec.replay_input.replay_pack_id
    replay_layout_schema_id = spec.replay_input.replay_layout_schema_id
    if replay_pack_id is None or replay_layout_schema_id is None:
        raise RunPreflightError("DeliverySchedule requires an exact ReplayPack input")
    # Assemble manifest once so the preflight delivery schedule workflow shares one value.
    manifest = schedule.manifest
    expected_components = tuple(
        component
        for component in spec.components
        if component.role in {"clock", "engine", "latency", "scheduler"}
        # Complete tuple only after its clock and engine inputs are visible in preflight
        # delivery schedule.
    )
    if schedule.delivery_schedule_id != schedule_id:
        raise RunPreflightError("opened DeliverySchedule identity differs from ResolvedRunSpec")
    if schedule.replay_pack_id != replay_pack_id:
        raise RunPreflightError("DeliverySchedule derives from another ReplayPack")
    # Evaluate the complete preflight delivery schedule replay pack id, replay semantics
    # id and replay layout schema id condition before guarded effects.
    if (
        manifest.replay_pack_id != replay_pack_id
        or manifest.replay_semantics_id != spec.replay_semantics_id
        or manifest.replay_layout_schema_id != replay_layout_schema_id
    ):
        # Fail the preflight delivery schedule path with RunPreflightError for delivery
        # schedule replay contract differs from resolved run spec when replay pack id,
        # replay semantics id and replay layout schema id is true; do not continue
        # ambiguously.
        raise RunPreflightError("DeliverySchedule replay contract differs from ResolvedRunSpec")
    build = manifest.build
    if build.components != expected_components:
        raise RunPreflightError("DeliverySchedule component configs differ from ResolvedRunSpec")
    if build.rng_algorithm != RNG_ALGORITHM or build.root_seed != spec.root_seed:
        # Fail the preflight delivery schedule path with RunPreflightError for delivery
        # schedule rng contract differs from resolved run spec when rng algorithm, root
        # seed and build is true; do not continue ambiguously.
        raise RunPreflightError("DeliverySchedule RNG contract differs from ResolvedRunSpec")
    if build.runtime_lock_id != spec.runtime_lock_id:
        raise RunPreflightError("DeliverySchedule runtime lock differs from ResolvedRunSpec")


def _maximum_dynamic_items(spec: ResolvedRunSpec) -> int:
    # Execute the maximum dynamic items workflow in explicit, reviewable steps.
    component = _component(spec, "engine")
    config = cast(dict[str, Any], json.loads(component.canonical_config))
    value = config.get("maximum_dynamic_items", 1_000_000)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RunPreflightError("engine maximum_dynamic_items must be a positive integer")
    # Return the completed maximum dynamic items result without a hidden fallback.
    return value


def _component(spec: ResolvedRunSpec, role: str) -> ResolvedComponent:
    # Execute the component workflow in explicit, reviewable steps.
    try:
        return next(item for item in spec.components if item.role == role)
    except StopIteration as error:  # pragma: no cover - ResolvedRunSpec validates roles
        raise RunPreflightError(f"resolved run has no {role} component") from error


def _run_input_artifacts(spec: ResolvedRunSpec) -> tuple[ArtifactId, ...]:
    # Execute the run input artifacts workflow in explicit, reviewable steps.
    values = [ArtifactId(spec.snapshot_id.hex)]
    if spec.replay_input.replay_pack_id is not None:
        values.append(ArtifactId(spec.replay_input.replay_pack_id.hex))
    if spec.delivery_schedule_id is not None:
        values.append(ArtifactId(spec.delivery_schedule_id.hex))
    # Guard this path with spec.model_schedule_id is not None before applying effects.
    if spec.model_schedule_id is not None:
        values.append(ArtifactId(spec.model_schedule_id.hex))
    values.extend(ArtifactId(item.hex) for item in spec.feature_set_ids)
    values.extend(ArtifactId(item.hex) for item in spec.prediction_set_ids)
    ordered = tuple(sorted(values, key=lambda item: item.hex))
    # Guard this path with len(set(ordered)) != len(ordered) before applying effects.
    if len(set(ordered)) != len(ordered):
        raise RunPreflightError("resolved run contains duplicate physical input artifacts")
    return ordered


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    # Execute the aware now workflow in explicit, reviewable steps.
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("run operational clock must return timezone-aware datetime")
    return value


__all__ = [
    # Keep the run backtest component named inside the all contract.
    "RunBacktest",
    "RunBacktestRequest",
    "RunBacktestResult",
    "RunPreflightError",
]
