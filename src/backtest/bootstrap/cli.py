"""CLI composition root.

Only this outer module knows concrete adapters, host configuration, controller
locks and the ASGI server.  The Typer interface receives a narrow backend.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from typing import Never, TypeVar

from backtest.adapters.artifacts.localfs import DataRootLayout, LocalCompletionReceiptStore
from backtest.adapters.control import (
    # Include control api error so the control dependency remains explicit.
    ControlApiError,
    ControlApiProtocolError,
    ControlApiUnavailableError,
    LocalControlApiClient,
)

# Import performance at the visible module dependency boundary.
from backtest.adapters.performance import (
    BenchmarkAdmissionError,
    UnsupportedCacheConditionError,
)
from backtest.adapters.results import LocalJobResultReader

# Import clickhouse at the visible module dependency boundary.
from backtest.adapters.source.clickhouse import CapabilityConfigError
from backtest.application.backups import BackupError, BackupGeneration, RestoreReport
from backtest.application.benchmarks import (
    BenchmarkPublication,
    BenchmarkWorkload,
    # Include exact benchmark command so the benchmarks dependency remains explicit.
    ExactBenchmarkCommand,
)
from backtest.application.canonical_data import PreparedSnapshot
from backtest.application.delivery_schedules import CompiledDeliverySchedule
from backtest.application.job_commands import (
    # Include prepare dataset job draft so the job commands dependency remains explicit.
    PrepareDatasetJobDraft,
    ResolvedBacktestJob,
    ResolvedCompileDeliveryScheduleJob,
    ResolvedCompileReplayJob,
    ResolvedSweepJob,
    # Include resolved prepare dataset job from bytes so the job commands dependency
    # remains explicit.
    resolved_prepare_dataset_job_from_bytes,
)
from backtest.application.job_views import JobStatusView
from backtest.application.ml_job_commands import MlResolvedJob
from backtest.application.models import (
    # Include artifact kind so the models dependency remains explicit.
    ArtifactKind,
    CommittedArtifact,
    DatasetPlan,
    JobRecord,
    # Include job type so the models dependency remains explicit.
    JobType,
    ListJobsRequest,
    PlanDatasetRequest,
    QueryLimits,
)

# Import run results at the visible module dependency boundary.
from backtest.application.ports.run_results import RoundTripCursor, RoundTripPage
from backtest.application.replay_packs import CompiledReplayPack
from backtest.application.retention import (
    GarbageCollectionBatch,
    GarbageCollectionPlan,
    # Include garbage collection receipt so the retention dependency remains explicit.
    GarbageCollectionReceipt,
    PinRecord,
)
from backtest.application.run_contracts import RunContractDescriptor
from backtest.application.run_drafts import RunDraft

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunPhysicalSettings
from backtest.application.run_specs import ResolvedRunSpec
from backtest.application.sweeps import ResolvedSweepSpec, SweepResult
from backtest.application.use_cases.cancel_job import CancelJobRequest
from backtest.application.use_cases.compile_replay import CompileReplayRequest

# Import complete job attempt at the visible module dependency boundary.
from backtest.application.use_cases.complete_job_attempt import CompleteJobAttempt
from backtest.application.use_cases.inspect_source import InspectSourceRequest
from backtest.application.use_cases.manage_retention import (
    CreatePinRequest,
    PlanGarbageCollectionRequest,
    # Close the manage retention import after its required symbols are visible.
)
from backtest.application.use_cases.query_artifacts import ArtifactDetails, ArtifactLineage
from backtest.application.use_cases.query_jobs import GetJobRequest
from backtest.application.use_cases.query_run_results import RunResultSummaryView
from backtest.application.use_cases.query_runs import RunSummaryView

# Import retry job at the visible module dependency boundary.
from backtest.application.use_cases.retry_job import RetryJobRequest
from backtest.application.use_cases.run_backtest import RunBacktestRequest, RunBacktestResult
from backtest.application.use_cases.store_source_inspection import StoredSourceInspection
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.bootstrap.catalog_reconciliation import LocalArtifactCatalogReconciler
from backtest.bootstrap.config import ConfigError, load_settings

# Import container at the visible module dependency boundary.
from backtest.bootstrap.container import RuntimeContainer, build_runtime_container
from backtest.bootstrap.direct_execution import (
    DirectJobCompletion,
    DirectJobExecutionError,
    DirectJobExecutor,
    # Close the direct execution import after its required symbols are visible.
)
from backtest.bootstrap.maintenance import MaintenanceConfigurationError
from backtest.bootstrap.projector_config import ProjectorConfigError
from backtest.bootstrap.recovery import RecoveryServices, build_recovery_services
from backtest.bootstrap.serve import run_control_server

# Import supervisor at the visible module dependency boundary.
from backtest.bootstrap.supervisor import build_single_host_supervisor
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    Identifier,
    # Include job id so the identifiers dependency remains explicit.
    JobId,
    SourceId,
)
from backtest.domain.time import BlockRange
from backtest.interfaces.api import create_app

# Import main at the visible module dependency boundary.
from backtest.interfaces.cli.main import (
    CliBackend,
    CliRecoveryBackend,
    CliUsageError,
    create_cli,
    # Close the main import after its required symbols are visible.
)
from backtest.runtime.control_plane_identity import control_plane_identity
from backtest.runtime.controller_lock import ControllerAlreadyRunningError, ControllerLock
from backtest.runtime.file_locks import LockUnavailableError

_ResultT = TypeVar("_ResultT")

# Bind ml result kinds once as an explicit module-level contract.
_ML_RESULT_KINDS: dict[JobType, ArtifactKind] = {
    JobType.BUILD_FEATURES: ArtifactKind.FEATURE_SET,
    JobType.BUILD_UNIVERSE: ArtifactKind.UNIVERSE,
    JobType.BUILD_LABELS: ArtifactKind.LABEL_SET,
    JobType.TRAIN_MODEL: ArtifactKind.MODEL_BUNDLE,
    # Keep the job type component named inside the ml result kinds contract.
    JobType.BUILD_MODEL_SCHEDULE: ArtifactKind.MODEL_SCHEDULE,
    JobType.PREDICT: ArtifactKind.PREDICTION_SET,
}


@dataclass(frozen=True, slots=True)
class RecoveryCliBackend:
    """Narrow CLI backend composed without opening live operational state."""

    services: RecoveryServices

    def verify_restore(self, backup_cut_id: ContentDigest) -> tuple[RestoreReport, str]:
        # Execute the recovery cli backend verify restore workflow in explicit, reviewable
        # steps.
        try:
            # Perform the protected recovery cli backend verify restore operation before
            # explicit failure handling.
            verification = self.services.verify_restore(backup_cut_id)
            return verification.report, verification.destination_name
        except MaintenanceConfigurationError as error:
            # Translate the MaintenanceConfigurationError failure through the recovery cli
            # backend verify restore boundary.
            raise CliUsageError(
                "BACKUP_NOT_CONFIGURED",
                "An external restore-drill location is not configured for this host.",
            ) from error


@dataclass(frozen=True, slots=True)
# Keep the control api cli backend contract and validation rules together.
class ControlApiCliBackend(CliBackend):
    """Job-control facade over the controller that already owns this data root."""

    client: LocalControlApiClient

    def default_run_physical_settings(self) -> RunPhysicalSettings:
        return self._call(self.client.run_physical_settings)

    def submit_job(self, request: SubmitJobRequest) -> JobStatusView:
        return self._call(lambda: self.client.submit_job(request))

    # Define control api cli backend list jobs as one focused operation with an explicit
    # boundary.
    def list_jobs(self, request: ListJobsRequest) -> tuple[JobStatusView, ...]:
        return self._call(lambda: self.client.list_jobs(request))

    def get_job(self, job_id: JobId) -> JobStatusView:
        return self._call(lambda: self.client.get_job(job_id))

    def cancel_job(self, job_id: JobId) -> JobStatusView:
        # Return the completed control api cli backend cancel job result without a hidden
        # fallback.
        return self._call(lambda: self.client.cancel_job(job_id))

    def retry_job(self, job_id: JobId) -> JobStatusView:
        return self._call(lambda: self.client.retry_job(job_id))

    def inspect_source(
        self,
        # Keep the source id input explicit in the inspect source contract.
        source_id: SourceId | None,
        *,
        evidence_from_block: int | None = None,
        evidence_to_block: int | None = None,
        decision_from_block: int | None = None,
        decision_to_block: int | None = None,
    ) -> StoredSourceInspection:
        # Execute the control api cli backend inspect source workflow in explicit,
        # reviewable steps.
        del (
            source_id,
            evidence_from_block,
            evidence_to_block,
            decision_from_block,
            decision_to_block,
        )
        return self._requires_local_authority()

    def plan_dataset(self, request: PlanDatasetRequest) -> DatasetPlan:
        # Execute the control api cli backend plan dataset workflow in explicit,
        # reviewable steps.
        del request
        return self._requires_local_authority()

    def prepare_dataset(self, plan: DatasetPlan) -> PreparedSnapshot:
        # Execute the control api cli backend prepare dataset workflow in explicit,
        # reviewable steps.
        del plan
        return self._requires_local_authority()

    def compile_replay(self, request: CompileReplayRequest) -> CompiledReplayPack:
        # Execute the control api cli backend compile replay workflow in explicit,
        # reviewable steps.
        del request
        return self._requires_local_authority()

    def compile_delivery_schedule(
        self,
        resolved_spec: ResolvedRunSpec,
        # Keep the compiler version input explicit in the compile delivery schedule
        # contract.
        compiler_version: str,
    ) -> CompiledDeliverySchedule:
        # Execute the control api cli backend compile delivery schedule workflow in
        # explicit, reviewable steps.
        del resolved_spec, compiler_version
        return self._requires_local_authority()

    def run_backtest(self, request: RunBacktestRequest) -> RunBacktestResult:
        # Execute the control api cli backend run backtest workflow in explicit,
        # reviewable steps.
        del request
        return self._requires_local_authority()

    def run_sweep(self, spec: ResolvedSweepSpec) -> SweepResult:
        # Execute the control api cli backend run sweep workflow in explicit, reviewable
        # steps.
        del spec
        return self._requires_local_authority()

    def execute_ml_job(self, command: MlResolvedJob) -> CommittedArtifact:
        # Execute the control api cli backend execute ml job workflow in explicit,
        # reviewable steps.
        del command
        return self._requires_local_authority()

    def resolve_run_spec(self, draft: RunDraft) -> ResolvedRunSpec:
        # Execute the control api cli backend resolve run spec workflow in explicit,
        # reviewable steps.
        del draft
        return self._requires_local_authority()

    def run_benchmark(self, command: ExactBenchmarkCommand) -> BenchmarkPublication:
        # Execute the control api cli backend run benchmark workflow in explicit,
        # reviewable steps.
        del command
        return self._requires_local_authority()

    def verify_artifact(self, artifact_id: ArtifactId) -> ArtifactDetails:
        return self._call(lambda: self.client.artifact_document(artifact_id))

    def list_runs(self, *, limit: int, offset: int) -> tuple[RunSummaryView, ...]:
        # Execute the control api cli backend list runs workflow in explicit, reviewable
        # steps.
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1_000
            or isinstance(offset, bool)
            # Keep isinstance visible while evaluating the isinstance, limit and offset
            # guard.
            or not isinstance(offset, int)
            or offset < 0
        ):
            raise ValueError("run query bounds are invalid")

        def query() -> tuple[RunSummaryView, ...]:
            # Execute the control api cli backend query workflow in explicit, reviewable
            # steps.
            remaining = limit
            selected_offset = offset
            items: list[RunSummaryView] = []
            while remaining > 0:
                # Keep the remaining > 0 loop body bounded within control api cli backend
                # query.
                page_limit = min(remaining, 50)
                page = self.client.run_documents(
                    limit=page_limit,
                    offset=selected_offset,
                )
                # Invoke extend for page as a visible control api cli backend query step.
                items.extend(page)
                if len(page) < page_limit:
                    break
                remaining -= len(page)
                selected_offset += len(page)
            # Return the completed control api cli backend query result without a hidden
            # fallback.
            return tuple(items)

        return self._call(query)

    def describe_run_contract(self, schema: str) -> RunContractDescriptor:
        return self._call(lambda: self.client.run_contract(schema))

    def show_run_summary(self, artifact_id: ArtifactId) -> RunResultSummaryView:
        # Return the completed control api cli backend show run summary result without a
        # hidden fallback.
        return self._call(lambda: self.client.sniping_run_summary(artifact_id))

    def list_roundtrips(
        self,
        artifact_id: ArtifactId,
        *,
        # Keep the after input explicit in the list roundtrips contract.
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        # Execute the control api cli backend list roundtrips workflow in explicit,
        # reviewable steps.
        return self._call(
            lambda: self.client.sniping_roundtrips(
                artifact_id,
                after=after,
                limit=limit,
                # Complete sniping_roundtrips only after its artifact id and after inputs are
                # visible in control api cli backend list roundtrips.
            )
        )

    def show_lineage(self, artifact_id: ArtifactId) -> ArtifactLineage:
        return self._call(lambda: self.client.lineage_document(artifact_id))

    def create_pin(
        # Keep the remaining create pin inputs visible at the control api cli backend
        # create pin boundary.
        self,
        pin_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
    ) -> PinRecord:
        # Execute the control api cli backend create pin workflow in explicit, reviewable
        # steps.
        del pin_id, roots, reason
        return self._requires_local_authority()

    def retire_pin(self, pin_id: Identifier) -> PinRecord:
        # Execute the control api cli backend retire pin workflow in explicit, reviewable
        # steps.
        del pin_id
        return self._requires_local_authority()

    def plan_garbage_collection(
        self,
        additional_retained_roots: tuple[ArtifactId, ...],
        # Keep the garbage collection plan input explicit in the plan garbage collection
        # contract.
    ) -> GarbageCollectionPlan:
        # Execute the control api cli backend plan garbage collection workflow in
        # explicit, reviewable steps.
        del additional_retained_roots
        return self._requires_local_authority()

    def execute_garbage_collection(
        self,
        additional_retained_roots: tuple[ArtifactId, ...],
        # Keep the tuple input explicit in the execute garbage collection contract.
    ) -> tuple[GarbageCollectionPlan, GarbageCollectionBatch]:
        # Execute the control api cli backend execute garbage collection workflow in
        # explicit, reviewable steps.
        del additional_retained_roots
        return self._requires_local_authority()

    def purge_trash(self, batch_id: ContentDigest) -> GarbageCollectionReceipt:
        # Execute the control api cli backend purge trash workflow in explicit, reviewable
        # steps.
        del batch_id
        return self._requires_local_authority()

    def create_backup(self) -> BackupGeneration:
        return self._requires_local_authority()

    def verify_restore(self, backup_cut_id: ContentDigest) -> tuple[RestoreReport, str]:
        # Execute the control api cli backend verify restore workflow in explicit,
        # reviewable steps.
        del backup_cut_id
        return self._requires_local_authority()

    def serve(self) -> None:
        self._requires_local_authority()

    @staticmethod
    # Define control api cli backend call as one focused operation with an explicit
    # boundary.
    def _call(operation: Callable[[], _ResultT]) -> _ResultT:
        # Execute the control api cli backend call workflow in explicit, reviewable steps.
        try:
            return operation()
        except ControlApiError as error:
            raise CliUsageError(error.code, error.safe_message) from None
        except (ControlApiProtocolError, ControlApiUnavailableError):
            # Translate the control api protocol error and control api unavailable error
            # failure through the control api cli backend call boundary.
            raise CliUsageError(
                "CONTROLLER_API_UNAVAILABLE",
                "The active local controller did not provide a valid bounded Control API.",
            ) from None

    @staticmethod
    # Define control api cli backend requires local authority as one focused operation
    # with an explicit boundary.
    def _requires_local_authority() -> Never:
        # Execute the control api cli backend requires local authority workflow in
        # explicit, reviewable steps.
        raise CliUsageError(
            "CONTROLLER_COMMAND_CONFLICT",
            "This command requires exclusive local authority; stop the server or enqueue it.",
        )


# Keep the runtime cli backend contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RuntimeCliBackend(CliBackend):
    container: RuntimeContainer
    config_path: Path = Path("configs/local-16gb.toml")
    capabilities_file: Path | None = None

    # Define runtime cli backend default run physical settings as one focused operation
    # with an explicit boundary.
    def default_run_physical_settings(self) -> RunPhysicalSettings:
        return self.container.settings.replay.to_run_physical_settings()

    def inspect_source(
        self,
        source_id: SourceId | None,
        # Close the inspect source signature after its explicit inputs.
        *,
        evidence_from_block: int | None = None,
        evidence_to_block: int | None = None,
        decision_from_block: int | None = None,
        decision_to_block: int | None = None,
    ) -> StoredSourceInspection:
        # Execute the runtime cli backend inspect source workflow in explicit, reviewable
        # steps.
        selected = source_id or SourceId(self.container.settings.source.source_id)
        if (evidence_from_block is None) != (evidence_to_block is None):
            # Handle the runtime cli backend inspect source evidence from block and
            # evidence to block condition as a distinct block.
            raise CliUsageError(
                "INVALID_EVIDENCE_RANGE",
                "Both bounded evidence block limits must be provided together.",
            )
        if (decision_from_block is None) != (decision_to_block is None):
            raise CliUsageError(
                "INVALID_DECISION_RANGE",
                "Both decision block limits must be provided together.",
            )
        if decision_from_block is not None and evidence_from_block is None:
            raise CliUsageError(
                "INVALID_DECISION_RANGE",
                "A decision range is valid only with a bounded evidence range.",
            )
        evidence_request = None
        # Evaluate the complete runtime cli backend inspect source evidence from block and
        # evidence to block condition before guarded effects.
        if evidence_from_block is not None and evidence_to_block is not None:
            # Handle the runtime cli backend inspect source evidence from block and
            # evidence to block condition as a distinct block.
            network_id, position_schema_id = self.container.source.chain_identity()
            extraction_range = BlockRange(
                network_id,
                position_schema_id,
                evidence_from_block,
                evidence_to_block,
            )
            selected_decision_range = BlockRange(
                network_id,
                position_schema_id,
                evidence_from_block if decision_from_block is None else decision_from_block,
                evidence_to_block if decision_to_block is None else decision_to_block,
            )
            evidence_request = self.container.source.build_evidence_request(
                source_id=selected,
                block_range=extraction_range,
                decision_range=selected_decision_range,
                query_limits=QueryLimits(
                    max_execution_seconds=(
                        self.container.settings.planning.max_query_execution_seconds
                    ),
                    max_memory_bytes=(
                        self.container.settings.planning.max_query_memory_mb * 1024**2
                    ),
                    max_result_rows=self.container.settings.planning.max_query_result_rows,
                ),
            )
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend inspect
            # source operation.
            result = self.container.control.inspect_source.execute(
                InspectSourceRequest(selected, evidence_request)
            )
            self.container.catalog.index_committed(result.artifact)
            return result

    # Define runtime cli backend plan dataset as one focused operation with an explicit
    # boundary.
    def plan_dataset(self, request: PlanDatasetRequest) -> DatasetPlan:
        return self.container.control.plan_dataset.execute(request)

    def prepare_dataset(self, plan: DatasetPlan) -> PreparedSnapshot:
        # Execute the runtime cli backend prepare dataset workflow in explicit, reviewable
        # steps.
        if self.container.prepare_dataset is None:
            # Handle the runtime cli backend prepare dataset
            # self.container.prepare_dataset is None branch as a distinct logical block.
            raise CliUsageError(
                "PROJECTOR_CONFIG_REQUIRED",
                "A strict protocol projection mapping is required for preparation.",
            )
        draft = PrepareDatasetJobDraft(plan)
        # Acquire controller lock at an explicit runtime cli backend prepare dataset
        # context boundary so cleanup remains scoped.
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend prepare
            # dataset operation.
            completion = self._execute_direct(
                JobType.PREPARE_DATASET,
                draft.canonical_bytes(),
                authority,
            )
        # Assemble command once so the runtime cli backend prepare dataset workflow shares
        # one value.
        command = resolved_prepare_dataset_job_from_bytes(completion.job.spec.canonical_payload)
        return self._read_direct_result(
            completion,
            lambda: self._result_reader().prepared_snapshot(
                command,
                # Pass completion explicitly so prepared_snapshot receives a reviewable
                # result artifact and command input in runtime cli backend prepare
                # dataset.
                completion.result_artifact,
            ),
            lambda result: (
                result.artifact,
                *(
                    # Pass item explicitly so _read_direct_result receives a reviewable
                    # prepared snapshot and result artifact input in runtime cli backend
                    # prepare dataset.
                    item.artifact
                    for item in result.distributions
                    if item.artifact.artifact_id
                    not in {reused.artifact_id for reused in command.reusable_distributions}
                ),
                # Complete _read_direct_result only after its prepared snapshot and result
                # artifact inputs are visible in runtime cli backend prepare dataset.
            ),
        )

    def compile_replay(self, request: CompileReplayRequest) -> CompiledReplayPack:
        # Execute the runtime cli backend compile replay workflow in explicit, reviewable
        # steps.
        command = ResolvedCompileReplayJob(request.snapshot_id, request.compiler_version)
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend compile
            # replay operation.
            completion = self._execute_direct(
                JobType.COMPILE_REPLAY,
                command.canonical_bytes(),
                authority,
            )
        # Return the completed runtime cli backend compile replay result without a hidden
        # fallback.
        return self._read_direct_result(
            completion,
            lambda: self._result_reader().compiled_replay(
                command,
                completion.result_artifact,
                # Complete compiled_replay only after its result artifact and command inputs
                # are visible in runtime cli backend compile replay.
            ),
            lambda result: (result.artifact,),
        )

    def compile_delivery_schedule(
        self,
        # Keep the resolved spec input explicit in the compile delivery schedule contract.
        resolved_spec: ResolvedRunSpec,
        compiler_version: str,
    ) -> CompiledDeliverySchedule:
        # Execute the runtime cli backend compile delivery schedule workflow in explicit,
        # reviewable steps.
        command = ResolvedCompileDeliveryScheduleJob(resolved_spec, compiler_version)
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend compile
            # delivery schedule operation.
            completion = self._execute_direct(
                JobType.COMPILE_DELIVERY_SCHEDULE,
                command.canonical_bytes(),
                authority,
            )
        # Return the completed runtime cli backend compile delivery schedule result
        # without a hidden fallback.
        return self._read_direct_result(
            completion,
            lambda: self._result_reader().compiled_delivery_schedule(
                command,
                completion.result_artifact,
                # Complete compiled_delivery_schedule only after its result artifact and
                # command inputs are visible in runtime cli backend compile delivery schedule.
            ),
            lambda result: (result.artifact,),
        )

    def run_backtest(self, request: RunBacktestRequest) -> RunBacktestResult:
        # Execute the runtime cli backend run backtest workflow in explicit, reviewable
        # steps.
        command = ResolvedBacktestJob(
            request.resolved_spec,
            request.attempt_nonce,
            request.physical_settings,
        )
        # Acquire controller lock at an explicit runtime cli backend run backtest context
        # boundary so cleanup remains scoped.
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend run
            # backtest operation.
            completion = self._execute_direct(
                JobType.RUN_BACKTEST,
                command.canonical_bytes(),
                authority,
            )
        # Return the completed runtime cli backend run backtest result without a hidden
        # fallback.
        return self._read_direct_result(
            completion,
            lambda: self._result_reader().run_result(
                command,
                completion.result_artifact,
                # Pass completion explicitly so run_result receives a reviewable result
                # artifact and attempt input in runtime cli backend run backtest.
                completion.attempt,
            ),
            lambda result: (result.artifact,),
        )

    def run_sweep(self, spec: ResolvedSweepSpec) -> SweepResult:
        # Execute the runtime cli backend run sweep workflow in explicit, reviewable
        # steps.
        command = ResolvedSweepJob(spec)
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend run
            # sweep operation.
            completion = self._execute_direct(
                JobType.RUN_SWEEP,
                command.canonical_bytes(),
                authority,
            )
        # Return the completed runtime cli backend run sweep result without a hidden
        # fallback.
        return self._read_direct_result(
            completion,
            lambda: self._result_reader().sweep_result(
                command,
                completion.result_artifact,
                # Pass completion explicitly so sweep_result receives a reviewable result
                # artifact and attempt input in runtime cli backend run sweep.
                completion.attempt,
            ),
            lambda result: (
                result.artifact,
                *(item.run_artifact for item in result.entries),
                # Complete _read_direct_result only after its sweep result and result artifact
                # inputs are visible in runtime cli backend run sweep.
            ),
        )

    def execute_ml_job(self, command: MlResolvedJob) -> CommittedArtifact:
        # Execute the runtime cli backend execute ml job workflow in explicit, reviewable
        # steps.
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend execute
            # ml job operation.
            completion = self._execute_direct(
                command.JOB_TYPE,
                command.canonical_bytes(),
                authority,
            )
        # Assemble expected kind once so the runtime cli backend execute ml job workflow
        # shares one value.
        expected_kind = _ML_RESULT_KINDS[command.JOB_TYPE]
        result = completion.result_artifact
        if result.kind is not expected_kind or completion.outputs != (result,):
            # Handle the runtime cli backend execute ml job kind, expected kind and
            # outputs condition as a distinct block.
            raise CliUsageError(
                "DIRECT_RESULT_INVALID",
                "The committed direct-job result failed typed read-back verification.",
            )
        return result

    # Define runtime cli backend resolve run spec as one focused operation with an
    # explicit boundary.
    def resolve_run_spec(self, draft: RunDraft) -> ResolvedRunSpec:
        return self.container.resolve_run_spec.execute(draft)

    def run_benchmark(self, command: ExactBenchmarkCommand) -> BenchmarkPublication:
        # Execute the runtime cli backend run benchmark workflow in explicit, reviewable
        # steps.
        if (
            command.native_threads_per_process
            > self.container.settings.resources.native_threads_per_process
        ):
            # Handle the runtime cli backend run benchmark native threads per process,
            # command and resources condition as a distinct block.
            raise CliUsageError(
                "BENCHMARK_THREAD_LIMIT_EXCEEDED",
                "The benchmark cannot raise the configured native-thread ceiling.",
            )
        if command.workload in {
            # Keep benchmark workload visible while evaluating the workload, native
            # threads per process and command guard.
            BenchmarkWorkload.FULL_BACKTEST,
            BenchmarkWorkload.EMBEDDED_INFERENCE,
            BenchmarkWorkload.FROZEN_INFERENCE,
            BenchmarkWorkload.CONTROL_PLANE_ROUND_TRIP,
        } and (
            # Keep command visible while evaluating the workload, native threads per
            # process and command guard.
            command.native_threads_per_process
            != self.container.settings.resources.native_threads_per_process
        ):
            # Handle the runtime cli backend run benchmark workload, native threads per
            # process and command condition as a distinct block.
            raise CliUsageError(
                "BENCHMARK_THREAD_PROFILE_MISMATCH",
                "Run and control benchmarks require the configured exact native-thread profile.",
            )
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend run
            # benchmark operation.
            try:
                # Perform the protected runtime cli backend run benchmark operation before
                # explicit failure handling.
                publication = self.container.run_exact_benchmark.execute(command)
                self.container.catalog.index_committed(publication.artifact)
                return publication
            except BenchmarkAdmissionError as error:
                # Translate the BenchmarkAdmissionError failure through the runtime cli
                # backend run benchmark boundary.
                raise CliUsageError(
                    "BENCHMARK_ADMISSION_REJECTED",
                    "The requested process count does not fit the measured local budget.",
                ) from error
            except UnsupportedCacheConditionError as error:
                # Translate the UnsupportedCacheConditionError failure through the runtime
                # cli backend run benchmark boundary.
                raise CliUsageError(
                    "CACHE_CONDITION_UNAVAILABLE",
                    "Cold cache is unavailable without verified privileged eviction.",
                ) from error
            except (RuntimeError, ValueError) as error:
                # Translate the (RuntimeError, ValueError) failure through the runtime cli
                # backend run benchmark boundary.
                raise CliUsageError(
                    "BENCHMARK_TARGET_INVALID",
                    "The exact benchmark target, route or committed closure failed verification.",
                ) from error

    def submit_job(self, request: SubmitJobRequest) -> JobRecord:
        # Execute the runtime cli backend submit job workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            return self.container.control.submit_job.execute(request)

    def list_jobs(self, request: ListJobsRequest) -> tuple[JobRecord, ...]:
        return self.container.control.list_jobs.execute(request)

    def get_job(self, job_id: JobId) -> JobRecord:
        # Return the completed runtime cli backend get job result without a hidden
        # fallback.
        return self.container.control.get_job.execute(GetJobRequest(job_id))

    def cancel_job(self, job_id: JobId) -> JobRecord:
        # Execute the runtime cli backend cancel job workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            return self.container.control.cancel_job.execute(CancelJobRequest(job_id))

    def retry_job(self, job_id: JobId) -> JobRecord:
        # Execute the runtime cli backend retry job workflow in explicit, reviewable
        # steps.
        retry = self.container.control.retry_job
        if retry is None:
            # Handle the runtime cli backend retry job retry is None branch as a distinct
            # logical block.
            raise CliUsageError(
                "RETRY_UNAVAILABLE",
                "The configured control plane does not provide durable job retry.",
            )
        with self._controller_lock():
            # Return the completed runtime cli backend retry job result without a hidden
            # fallback.
            return retry.execute(RetryJobRequest(job_id))

    def verify_artifact(self, artifact_id: ArtifactId) -> ArtifactDetails:
        # Execute the runtime cli backend verify artifact workflow in explicit, reviewable
        # steps.
        queries = self.container.control.query_artifacts
        if queries is None:
            # Handle the runtime cli backend verify artifact queries is None branch as a
            # distinct logical block.
            raise CliUsageError(
                "ARTIFACT_QUERY_UNAVAILABLE",
                "Verified artifact metadata queries are unavailable.",
            )
        return queries.details(artifact_id)

    # Define runtime cli backend list runs as one focused operation with an explicit
    # boundary.
    def list_runs(self, *, limit: int, offset: int) -> tuple[RunSummaryView, ...]:
        # Execute the runtime cli backend list runs workflow in explicit, reviewable
        # steps.
        queries = self.container.control.query_runs
        if queries is None:
            # Handle the runtime cli backend list runs queries is None branch as a
            # distinct logical block.
            raise CliUsageError(
                "RUN_QUERY_UNAVAILABLE",
                "Verified run metadata queries are unavailable.",
            )
        return queries.list(limit=limit, offset=offset)

    # Define runtime cli backend describe run contract as one focused operation with an
    # explicit boundary.
    def describe_run_contract(self, schema: str) -> RunContractDescriptor:
        # Execute the runtime cli backend describe run contract workflow in explicit,
        # reviewable steps.
        queries = self.container.control.query_run_contracts
        if queries is None:
            # Handle the runtime cli backend describe run contract queries is None branch
            # as a distinct logical block.
            raise CliUsageError(
                "RUN_CONTRACT_QUERY_UNAVAILABLE",
                "Typed run-contract discovery is unavailable.",
            )
        return queries.get(schema)

    # Define runtime cli backend show run summary as one focused operation with an
    # explicit boundary.
    def show_run_summary(self, artifact_id: ArtifactId) -> RunResultSummaryView:
        # Execute the runtime cli backend show run summary workflow in explicit,
        # reviewable steps.
        queries = self.container.control.query_run_results
        if queries is None:
            # Handle the runtime cli backend show run summary queries is None branch as a
            # distinct logical block.
            raise CliUsageError(
                "RUN_RESULT_QUERY_UNAVAILABLE",
                "Verified Pump.fun Run result queries are unavailable.",
            )
        return queries.summary(artifact_id)

    # Define runtime cli backend list roundtrips as one focused operation with an explicit
    # boundary.
    def list_roundtrips(
        self,
        artifact_id: ArtifactId,
        *,
        after: RoundTripCursor | None,
        # Keep the limit input explicit in the list roundtrips contract.
        limit: int,
    ) -> RoundTripPage:
        # Execute the runtime cli backend list roundtrips workflow in explicit, reviewable
        # steps.
        queries = self.container.control.query_run_results
        if queries is None:
            # Handle the runtime cli backend list roundtrips queries is None branch as a
            # distinct logical block.
            raise CliUsageError(
                "RUN_RESULT_QUERY_UNAVAILABLE",
                "Verified Pump.fun Run result queries are unavailable.",
            )
        return queries.roundtrips(artifact_id, after=after, limit=limit)

    # Define runtime cli backend show lineage as one focused operation with an explicit
    # boundary.
    def show_lineage(self, artifact_id: ArtifactId) -> ArtifactLineage:
        # Execute the runtime cli backend show lineage workflow in explicit, reviewable
        # steps.
        queries = self.container.control.query_artifacts
        if queries is None:
            # Handle the runtime cli backend show lineage queries is None branch as a
            # distinct logical block.
            raise CliUsageError(
                "ARTIFACT_QUERY_UNAVAILABLE",
                "Verified artifact lineage queries are unavailable.",
            )
        return queries.lineage(artifact_id)

    # Define runtime cli backend create pin as one focused operation with an explicit
    # boundary.
    def create_pin(
        self,
        pin_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
        # Keep the pin record input explicit in the create pin contract.
    ) -> PinRecord:
        # Execute the runtime cli backend create pin workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend create
            # pin operation.
            return self.container.maintenance.retention.create_pin(
                CreatePinRequest(pin_id, roots, reason)
            )

    def retire_pin(self, pin_id: Identifier) -> PinRecord:
        # Execute the runtime cli backend retire pin workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            return self.container.maintenance.retention.retire_pin(pin_id)

    def plan_garbage_collection(
        self,
        additional_retained_roots: tuple[ArtifactId, ...],
        # Keep the garbage collection plan input explicit in the plan garbage collection
        # contract.
    ) -> GarbageCollectionPlan:
        # Execute the runtime cli backend plan garbage collection workflow in explicit,
        # reviewable steps.
        return self.container.maintenance.retention.plan_garbage_collection(
            PlanGarbageCollectionRequest(additional_retained_roots)
        )

    def execute_garbage_collection(
        self,
        # Keep the additional retained roots input explicit in the execute garbage
        # collection contract.
        additional_retained_roots: tuple[ArtifactId, ...],
    ) -> tuple[GarbageCollectionPlan, GarbageCollectionBatch]:
        # Execute the runtime cli backend execute garbage collection workflow in explicit,
        # reviewable steps.
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend execute
            # garbage collection operation.
            plan = self.container.maintenance.retention.plan_garbage_collection(
                PlanGarbageCollectionRequest(additional_retained_roots)
            )
            try:
                batch = self.container.maintenance.retention.execute_garbage_collection(plan)
            # Translate lock unavailable error through the runtime cli backend execute
            # garbage collection boundary without hiding other errors.
            except LockUnavailableError as error:
                # Translate the LockUnavailableError failure through the runtime cli
                # backend execute garbage collection boundary.
                raise CliUsageError(
                    "RETENTION_BUSY",
                    "GC could not acquire exclusive retention authority; active readers continue.",
                ) from error
            return plan, batch

    # Define runtime cli backend purge trash as one focused operation with an explicit
    # boundary.
    def purge_trash(self, batch_id: ContentDigest) -> GarbageCollectionReceipt:
        # Execute the runtime cli backend purge trash workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            return self.container.maintenance.retention.purge_trash(batch_id)

    def create_backup(self) -> BackupGeneration:
        # Execute the runtime cli backend create backup workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend create
            # backup operation.
            try:
                return self.container.maintenance.create_backup()
            except MaintenanceConfigurationError as error:
                # Translate the MaintenanceConfigurationError failure through the runtime
                # cli backend create backup boundary.
                raise CliUsageError(
                    "BACKUP_NOT_CONFIGURED",
                    "An external backup target is not configured for this host.",
                ) from error

    def verify_restore(self, backup_cut_id: ContentDigest) -> tuple[RestoreReport, str]:
        # Execute the runtime cli backend verify restore workflow in explicit, reviewable
        # steps.
        with self._controller_lock():
            # Keep controller lock active only for the bounded runtime cli backend verify
            # restore operation.
            try:
                # Perform the protected runtime cli backend verify restore operation
                # before explicit failure handling.
                verification = self.container.maintenance.verify_restore(backup_cut_id)
                return verification.report, verification.destination_name
            except MaintenanceConfigurationError as error:
                # Translate the MaintenanceConfigurationError failure through the runtime
                # cli backend verify restore boundary.
                raise CliUsageError(
                    "BACKUP_NOT_CONFIGURED",
                    "An external restore-drill location is not configured for this host.",
                ) from error

    def serve(self) -> None:
        # Execute the runtime cli backend serve workflow in explicit, reviewable steps.
        settings = self.container.settings
        with self._controller_lock() as authority:
            # Keep controller lock active only for the bounded runtime cli backend serve
            # operation.
            supervisor = build_single_host_supervisor(
                self.container,
                # Pass authority explicitly so build_single_host_supervisor receives a
                # reviewable container and config path input in runtime cli backend serve.
                authority=authority,
                config_path=self.config_path,
                capabilities_file=self.capabilities_file,
                working_directory=Path.cwd(),
            )
            # Invoke run_control_server for control and container as a visible runtime cli
            # backend serve step.
            run_control_server(
                create_app(
                    self.container.control,
                    control_plane_id=control_plane_identity(
                        settings.paths.data_root.resolve(),
                        # Pass authority explicitly so control_plane_identity receives a
                        # reviewable resolve and data root input in runtime cli backend
                        # serve.
                        authority.instance_id,
                    ),
                    max_request_bytes=settings.control.max_request_mb * 1024 * 1024,
                    secure_cookie=settings.control.secure_cookie,
                ),
                # Pass supervisor explicitly so run_control_server receives a reviewable
                # control and container input in runtime cli backend serve.
                supervisor=supervisor,
                host=settings.control.host,
                port=settings.control.port,
                cycle_interval_seconds=settings.control.progress_interval_ms / 1_000,
            )

    # Define runtime cli backend index outputs as one focused operation with an explicit
    # boundary.
    def _index_outputs(self, *artifacts: CommittedArtifact) -> None:
        # Execute the runtime cli backend index outputs workflow in explicit, reviewable
        # steps.
        for artifact in artifacts:
            self.container.catalog.index_committed(artifact)

    def _execute_direct(
        self,
        job_type: JobType,
        # Keep the payload input explicit in the execute direct contract.
        payload: bytes,
        authority: ControllerLock,
    ) -> DirectJobCompletion:
        # Execute the runtime cli backend execute direct workflow in explicit, reviewable
        # steps.
        supervisor = build_single_host_supervisor(
            self.container,
            authority=authority,
            config_path=self.config_path,
            capabilities_file=self.capabilities_file,
            # Keep the cwd and path cwd step visible while building supervisor.
            working_directory=Path.cwd(),
        )
        receipts = LocalCompletionReceiptStore(DataRootLayout(self.container.artifacts.data_root))
        verifier = CompleteJobAttempt(
            self.container.jobs,
            # Pass self explicitly so CompleteJobAttempt receives a reviewable jobs and
            # container input in runtime cli backend execute direct.
            self.container.catalog,
            receipts,
            self.container.artifacts,
        )
        executor = DirectJobExecutor(
            # Pass submitter explicitly so DirectJobExecutor receives a reviewable submit
            # job and control input in runtime cli backend execute direct.
            submitter=self.container.control.submit_job,
            queue=self.container.jobs,
            supervisor=supervisor,
            verifier=verifier,
            artifacts=self.container.artifacts,
            # Keep the progress interval ms and control min step visible while building
            # executor.
            poll_interval_seconds=min(
                1.0,
                self.container.settings.control.progress_interval_ms / 1_000,
            ),
        )
        # Assemble request once so the runtime cli backend execute direct workflow shares
        # one value.
        request = SubmitJobRequest(
            spec_version=1,
            job_type=job_type,
            payload_json=payload,
            idempotency_key=f"direct-{secrets.token_hex(24)}",
            # Complete SubmitJobRequest only after its direct- and token hex inputs are
            # visible in runtime cli backend execute direct.
        )
        try:
            return executor.execute(request)
        except DirectJobExecutionError as error:
            raise CliUsageError(error.code, error.safe_message) from None

    # Define runtime cli backend result reader as one focused operation with an explicit
    # boundary.
    def _result_reader(self) -> LocalJobResultReader:
        return LocalJobResultReader(self.container.artifacts)

    @staticmethod
    def _read_direct_result(
        completion: DirectJobCompletion,
        # Keep the loader input explicit in the read direct result contract.
        loader: Callable[[], _ResultT],
        result_outputs: Callable[[_ResultT], tuple[CommittedArtifact, ...]],
    ) -> _ResultT:
        # Execute the runtime cli backend read direct result workflow in explicit,
        # reviewable steps.
        try:
            # Perform the protected runtime cli backend read direct result operation
            # before explicit failure handling.
            result = loader()
            expected = tuple(
                sorted(
                    result_outputs(result),
                    key=lambda item: item.artifact_id.hex,
                    # Complete sorted only after its hex and artifact id inputs are visible in
                    # runtime cli backend read direct result.
                )
            )
            if expected != completion.outputs:
                raise RuntimeError("typed result output closure differs from receipt")
            return result
        # Translate oserror through the runtime cli backend read direct result boundary
        # without hiding other errors.
        except (OSError, RuntimeError, ValueError):
            # Translate the (OSError, RuntimeError, ValueError) failure through the
            # runtime cli backend read direct result boundary.
            raise CliUsageError(
                "DIRECT_RESULT_INVALID",
                "The committed direct-job result failed typed read-back verification.",
            ) from None

    @contextmanager
    # Define runtime cli backend controller lock as one focused operation with an explicit
    # boundary.
    def _controller_lock(self) -> Iterator[ControllerLock]:
        # Execute the runtime cli backend controller lock workflow in explicit, reviewable
        # steps.
        settings = self.container.settings
        lock = ControllerLock(settings.paths.data_root.resolve() / "locks" / "controller.lock")
        acquired = False
        try:
            lock.acquire()
        # Translate controller already running error through the runtime cli backend
        # controller lock boundary without hiding other errors.
        except ControllerAlreadyRunningError:
            pass
        else:
            acquired = True
        if not acquired:
            # Handle the runtime cli backend controller lock not acquired branch as a
            # distinct logical block.
            raise CliUsageError(
                "CONTROLLER_ALREADY_RUNNING",
                "Another local controller already owns this data root.",
            )
        try:
            # Reconciliation is bracketed by controller authority and precedes all writes.
            reconciler = LocalArtifactCatalogReconciler(
                self.container.artifacts,
                self.container.catalog,
            )
            with reconciler.controller_session():
                yield lock
        finally:
            lock.release()


def build_cli_backend(
    config_path: Path,
    # Keep the capabilities file input explicit in the build cli backend contract.
    capabilities_file: Path | None,
    *,
    require_capabilities: bool = False,
    prefer_running_controller: bool = False,
) -> CliBackend:
    # Execute the build cli backend workflow in explicit, reviewable steps.
    failure: CliUsageError | None = None
    container: RuntimeContainer | None = None
    try:
        # Perform the protected build cli backend operation before explicit failure
        # handling.
        settings = load_settings(config_path)
        probe_lock, controller_id = _probe_controller(settings.paths.data_root.resolve())
        if controller_id is not None:
            # Handle the build cli backend controller_id is not None branch as a distinct
            # logical block.
            if not prefer_running_controller:
                # Handle the build cli backend not prefer_running_controller branch as a
                # distinct logical block.
                raise CliUsageError(
                    "CONTROLLER_ALREADY_RUNNING",
                    "Another local controller already owns this data root.",
                )
            client = LocalControlApiClient(
                # Pass settings explicitly so LocalControlApiClient receives a reviewable
                # host and control input in build cli backend.
                settings.control.host,
                settings.control.port,
                maximum_response_bytes=min(
                    settings.control.max_request_mb * 1024 * 1024,
                    8 * 1024 * 1024,
                    # Complete min only after its max request mb and control inputs are
                    # visible in build cli backend.
                ),
            )
            health = ControlApiCliBackend._call(client.health)
            if health.profile != config_path.stem or health.control_plane_id != controller_id:
                # Handle the build cli backend profile, stem and control plane id
                # condition as a distinct block.
                raise CliUsageError(
                    "CONTROLLER_API_MISMATCH",
                    "The configured loopback API does not own this local data root.",
                )
            return ControlApiCliBackend(client)
        if probe_lock is None:  # pragma: no cover - exhaustive probe contract
            raise AssertionError("controller probe returned neither authority nor owner")
        selected_capabilities = capabilities_file or settings.source.capabilities_file
        try:
            # Perform the protected build cli backend operation before explicit failure
            # handling.
            if require_capabilities and selected_capabilities is None:
                # Handle the build cli backend require capabilities and selected
                # capabilities condition as a distinct block.
                raise CliUsageError(
                    "CAPABILITY_CONFIG_REQUIRED",
                    "A secret-free source capability mapping is required for this command.",
                )
            container = build_runtime_container(
                # Pass settings explicitly so build_runtime_container receives a
                # reviewable stem and settings input in build cli backend.
                settings,
                profile=config_path.stem,
                capabilities_file=capabilities_file,
            )
            # Direct read-only commands need a complete projection before probe release.
            LocalArtifactCatalogReconciler(
                container.artifacts,
                container.catalog,
            ).reconcile_once()
        finally:
            # Invoke release as a visible step within the build cli backend workflow.
            probe_lock.release()
    except CliUsageError:
        raise
    except FileNotFoundError:
        # Translate the FileNotFoundError failure through the build cli backend boundary.
        failure = CliUsageError(
            "LOCAL_CONFIG_NOT_FOUND",
            "A required local configuration file could not be found.",
        )
    except (CapabilityConfigError, ProjectorConfigError):
        # Translate the capability config error and projector config error failure through
        # the build cli backend boundary.
        failure = CliUsageError(
            "CAPABILITY_CONFIG_INVALID",
            "The source capability mapping is invalid.",
        )
    except ConfigError:
        # Translate the ConfigError failure through the build cli backend boundary.
        failure = CliUsageError(
            "LOCAL_CONFIG_INVALID",
            "The local host configuration is invalid or incomplete.",
        )
    except BackupError:
        # Translate the BackupError failure through the build cli backend boundary.
        failure = CliUsageError(
            "BACKUP_CONFIG_INVALID",
            "The configured external backup target failed safety validation.",
        )
    if failure is not None:
        # Fail the build cli backend path with failure when failure is true; do not
        # continue ambiguously.
        raise failure
    if container is None:  # pragma: no cover - exhaustive exception mapping above
        raise AssertionError("CLI composition did not produce a runtime container")
    return RuntimeCliBackend(
        container,
        config_path.resolve(),
        None if selected_capabilities is None else selected_capabilities.resolve(),
        # Complete RuntimeCliBackend only after its resolve and container inputs are visible
        # in build cli backend.
    )


def _probe_controller(data_root: Path) -> tuple[ControllerLock | None, ContentDigest | None]:
    # Execute the probe controller workflow in explicit, reviewable steps.
    lock = ControllerLock(data_root / "locks" / "controller.lock")
    try:
        lock.acquire()
    except ControllerAlreadyRunningError as error:
        # Translate the ControllerAlreadyRunningError failure through the probe controller
        # boundary.
        owner = error.owner
        instance_id = None if owner is None else owner.get("instance_id")
        if not isinstance(instance_id, str):
            # Handle the probe controller not isinstance(instance_id, str) branch as a
            # distinct logical block.
            raise CliUsageError(
                "CONTROLLER_IDENTITY_UNAVAILABLE",
                "The active controller did not expose a valid local identity.",
            ) from None
        try:
            # Return the completed probe controller result without a hidden fallback.
            return None, control_plane_identity(data_root, instance_id)
        except ValueError:
            # Translate the ValueError failure through the probe controller boundary.
            raise CliUsageError(
                "CONTROLLER_IDENTITY_UNAVAILABLE",
                "The active controller did not expose a valid local identity.",
            ) from None
    return lock, None


# Define build cli recovery backend as one focused operation with an explicit boundary.
def build_cli_recovery_backend(config_path: Path) -> CliRecoveryBackend:
    """Compose offline restore verification without constructing RuntimeContainer."""

    failure: CliUsageError | None = None
    settings = None
    try:
        settings = load_settings(config_path)
    except FileNotFoundError:
        # Translate the FileNotFoundError failure through the build cli recovery backend
        # boundary.
        failure = CliUsageError(
            "LOCAL_CONFIG_NOT_FOUND",
            "A required local configuration file could not be found.",
        )
    except ConfigError:
        # Translate the ConfigError failure through the build cli recovery backend
        # boundary.
        failure = CliUsageError(
            "LOCAL_CONFIG_INVALID",
            "The local host configuration is invalid or incomplete.",
        )
    except BackupError:
        # Translate the BackupError failure through the build cli recovery backend
        # boundary.
        failure = CliUsageError(
            "BACKUP_CONFIG_INVALID",
            "The configured external backup target failed safety validation.",
        )
    if failure is not None:
        # Fail the build cli recovery backend path with failure when failure is true; do
        # not continue ambiguously.
        raise failure
    if settings is None:  # pragma: no cover - exhaustive exception mapping above
        raise AssertionError("recovery composition did not load host settings")
    return RecoveryCliBackend(build_recovery_services(settings))


app = create_cli(build_cli_backend, build_cli_recovery_backend)


def main() -> None:
    app()


# Guard this path with __name__ == '__main__' before applying effects.
if __name__ == "__main__":
    main()


__all__ = [
    "ControlApiCliBackend",
    "RecoveryCliBackend",
    # Keep the runtime cli backend component named inside the all contract.
    "RuntimeCliBackend",
    "app",
    "build_cli_backend",
    "build_cli_recovery_backend",
    "main",
    # Complete the all group only after its semantic components are visible.
]
