"""Typer inbound adapter with an injected composition backend.

This module intentionally imports no concrete adapter, runtime lock or
bootstrap module. ``backtest.bootstrap.cli`` owns composition and process
startup; tests can inject a small in-memory backend.
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Annotated, NoReturn, Protocol

import typer

# Import pydantic at the visible module dependency boundary.
from pydantic import ValidationError

from backtest.application.backups import BackupError, BackupGeneration, RestoreReport
from backtest.application.benchmarks import (
    BenchmarkLaunchRoute,
    BenchmarkPublication,
    # Include benchmark workload so the benchmarks dependency remains explicit.
    BenchmarkWorkload,
    CacheCondition,
    ExactBenchmarkCommand,
)
from backtest.application.canonical_data import PreparedSnapshot

# Import delivery schedules at the visible module dependency boundary.
from backtest.application.delivery_schedules import CompiledDeliverySchedule
from backtest.application.errors import ApplicationError
from backtest.application.job_commands import ResolvedBacktestJob, ResolvedSweepJob
from backtest.application.job_views import JobStatusView
from backtest.application.ml_job_commands import MlResolvedJob

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    AttemptState,
    CommittedArtifact,
    DatasetPlan,
    JobRecord,
    # Include job type so the models dependency remains explicit.
    JobType,
    ListJobsRequest,
    PlanDatasetRequest,
)
from backtest.application.ports.run_results import RoundTripCursor, RoundTripPage

# Import replay packs at the visible module dependency boundary.
from backtest.application.replay_packs import CompiledReplayPack
from backtest.application.retention import (
    GarbageCollectionBatch,
    GarbageCollectionPlan,
    GarbageCollectionReceipt,
    # Include pin record so the retention dependency remains explicit.
    PinRecord,
    RetentionError,
)
from backtest.application.run_contracts import RunContractDescriptor, RunContractNotFoundError
from backtest.application.run_drafts import RunDraft

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import ResolvedRunSpec, resolved_run_spec_from_bytes
from backtest.application.sweeps import (
    ResolvedSweepSpec,
    SweepEntry,
    # Include sweep result so the sweeps dependency remains explicit.
    SweepResult,
    resolved_sweep_spec_from_bytes,
)
from backtest.application.use_cases.compile_replay import CompileReplayRequest
from backtest.application.use_cases.query_artifacts import (
    # Include artifact details so the query artifacts dependency remains explicit.
    ArtifactDetails,
    ArtifactLineage,
    ArtifactQueryError,
)
from backtest.application.use_cases.query_run_results import (
    # Include pumpfun sniping run summary view so the query run results dependency remains
    # explicit.
    CopyRunSummaryView,
    RunResultQueryError,
    RunResultSummaryView,
)
from backtest.application.use_cases.query_runs import RunIndexQueryError, RunSummaryView

# The CLI calls the same execution use case as the control API.
from backtest.application.use_cases.run_backtest import (
    # Include run backtest request so the run backtest dependency remains explicit.
    RunBacktestRequest,
    RunBacktestResult,
)
from backtest.application.use_cases.store_source_inspection import StoredSourceInspection
from backtest.application.use_cases.submit_job import SubmitJobRequest

# Import chain at the visible module dependency boundary.
from backtest.domain.account_requirements import AccountComponentRecord
from backtest.domain.chain import ChainPosition
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    Identifier,
    # Include job id so the identifiers dependency remains explicit.
    JobId,
    SnapshotId,
    SourceId,
)
from backtest.domain.roundtrips import (
    # Copy uses a distinct immutable result shape on the same bounded paging transport.
    ROUNDTRIP_RESULT_SCHEMA_V3,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    RoundTripRecord,
)

# Copy positions retain their own immutable row model.
from backtest.engine.copytrading_results import CopyPositionRecord

# Import ml schemas at the visible module dependency boundary.
from backtest.interfaces.api.ml_schemas import (
    BuildFeaturesJobForm,
    BuildLabelsJobForm,
    BuildModelScheduleJobForm,
    BuildUniverseJobForm,
    # Include predict job form so the ml schemas dependency remains explicit.
    PredictJobForm,
    TrainModelJobForm,
)
from backtest.interfaces.api.schemas import (
    CopyPositionResponse,
    # Copy JSON uses the same lossless response codec as the browser API.
    CopyRunSummaryResponse,
    DatasetPlanResponse,
    # Include job list response so the schemas dependency remains explicit.
    JobListResponse,
    JobResponse,
    PlanDatasetCommand,
    SourceInspectionResponse,
    run_draft_command_from_bytes,
    # Close the schemas import after its required symbols are visible.
)

ConfigPath = Annotated[
    Path,
    typer.Option("--config", help="Local TOML profile."),
]
# Bind capability path once as an explicit module-level contract.
CapabilityPath = Annotated[
    Path | None,
    typer.Option("--capabilities", help="Secret-free ClickHouse capability TOML."),
]


class CliUsageError(RuntimeError):
    """Safe composition/startup failure suitable for terminal output."""

    def __init__(self, code: str, safe_message: str) -> None:
        # Execute the cli usage error init workflow in explicit, reviewable steps.
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class CliBackend(Protocol):
    """Operations required by the CLI, implemented by the composition root."""

    def inspect_source(
        self,
        source_id: SourceId | None,
        *,
        evidence_from_block: int | None = None,
        # Keep the evidence to block input explicit in the inspect source contract.
        evidence_to_block: int | None = None,
        decision_from_block: int | None = None,
        decision_to_block: int | None = None,
    ) -> StoredSourceInspection: ...

    def plan_dataset(self, request: PlanDatasetRequest) -> DatasetPlan: ...

    def prepare_dataset(self, plan: DatasetPlan) -> PreparedSnapshot: ...

    def compile_replay(self, request: CompileReplayRequest) -> CompiledReplayPack: ...

    # Define cli backend compile delivery schedule as one focused operation with an
    # explicit boundary.
    def compile_delivery_schedule(
        self,
        resolved_spec: ResolvedRunSpec,
        compiler_version: str,
    ) -> CompiledDeliverySchedule: ...

    # Define cli backend run backtest as one focused operation with an explicit boundary.
    def run_backtest(self, request: RunBacktestRequest) -> RunBacktestResult: ...

    def default_run_physical_settings(self) -> RunPhysicalSettings: ...

    def run_sweep(self, spec: ResolvedSweepSpec) -> SweepResult: ...

    def execute_ml_job(self, command: MlResolvedJob) -> CommittedArtifact: ...

    def resolve_run_spec(self, draft: RunDraft) -> ResolvedRunSpec: ...

    # Define cli backend run benchmark as one focused operation with an explicit boundary.
    def run_benchmark(self, command: ExactBenchmarkCommand) -> BenchmarkPublication: ...

    def submit_job(self, request: SubmitJobRequest) -> JobRecord | JobStatusView: ...

    def list_jobs(self, request: ListJobsRequest) -> tuple[JobRecord | JobStatusView, ...]: ...

    def get_job(self, job_id: JobId) -> JobRecord | JobStatusView: ...

    def cancel_job(self, job_id: JobId) -> JobRecord | JobStatusView: ...

    # Define cli backend retry job as one focused operation with an explicit boundary.
    def retry_job(self, job_id: JobId) -> JobRecord | JobStatusView: ...

    def verify_artifact(self, artifact_id: ArtifactId) -> ArtifactDetails: ...

    def list_runs(self, *, limit: int, offset: int) -> tuple[RunSummaryView, ...]: ...

    def describe_run_contract(self, schema: str) -> RunContractDescriptor: ...

    def show_run_summary(self, artifact_id: ArtifactId) -> RunResultSummaryView: ...

    # Define cli backend list roundtrips as one focused operation with an explicit
    # boundary.
    def list_roundtrips(
        self,
        artifact_id: ArtifactId,
        *,
        after: RoundTripCursor | None,
        # Keep the limit input explicit in the list roundtrips contract.
        limit: int,
    ) -> RoundTripPage: ...

    def show_lineage(self, artifact_id: ArtifactId) -> ArtifactLineage: ...

    def create_pin(
        self,
        # Keep the pin id input explicit in the create pin contract.
        pin_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
    ) -> PinRecord: ...

    def retire_pin(self, pin_id: Identifier) -> PinRecord: ...

    # Define cli backend plan garbage collection as one focused operation with an explicit
    # boundary.
    def plan_garbage_collection(
        self,
        additional_retained_roots: tuple[ArtifactId, ...],
    ) -> GarbageCollectionPlan: ...

    def execute_garbage_collection(
        # Keep the remaining execute garbage collection inputs visible at the cli backend
        # execute garbage collection boundary.
        self,
        additional_retained_roots: tuple[ArtifactId, ...],
    ) -> tuple[GarbageCollectionPlan, GarbageCollectionBatch]: ...

    def purge_trash(self, batch_id: ContentDigest) -> GarbageCollectionReceipt: ...

    def create_backup(self) -> BackupGeneration: ...

    # Define cli backend verify restore as one focused operation with an explicit
    # boundary.
    def verify_restore(self, backup_cut_id: ContentDigest) -> tuple[RestoreReport, str]: ...

    def serve(self) -> None: ...


# Keep the cli backend factory contract and validation rules together.
class CliBackendFactory(Protocol):
    def __call__(
        self,
        config_path: Path,
        capabilities_file: Path | None,
        # Close the call signature after its explicit inputs.
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
    ) -> CliBackend: ...


class CliRecoveryBackend(Protocol):
    """Recovery-only operations that must not require the live catalog."""

    def verify_restore(self, backup_cut_id: ContentDigest) -> tuple[RestoreReport, str]: ...


class CliRecoveryBackendFactory(Protocol):
    def __call__(self, config_path: Path) -> CliRecoveryBackend: ...


def create_cli(
    backend_factory: CliBackendFactory,
    # Keep the recovery backend factory input explicit in the create cli contract.
    recovery_backend_factory: CliRecoveryBackendFactory | None = None,
) -> typer.Typer:
    """Create the CLI without importing an infrastructure composition root."""

    cli = typer.Typer(
        name="backtest",
        no_args_is_help=True,
        pretty_exceptions_enable=False,
        help="On-Chain Backtest Engine control plane.",
        # Complete Typer only after its backtest and value inputs are visible in create cli.
    )

    @cli.command()
    def inspect_source(
        config: ConfigPath = Path("configs/local-16gb.toml"),
        capabilities: CapabilityPath = None,
        # Keep the source id input explicit in the inspect source contract.
        source_id: Annotated[str | None, typer.Option("--source-id")] = None,
        evidence_from_block: Annotated[
            int | None,
            typer.Option("--evidence-from-block", min=0),
        ] = None,
        # Keep the evidence to block input explicit in the inspect source contract.
        evidence_to_block: Annotated[
            int | None,
            typer.Option("--evidence-to-block", min=1),
        ] = None,
        decision_from_block: Annotated[
            int | None,
            typer.Option("--decision-from-block", min=0),
        ] = None,
        decision_to_block: Annotated[
            int | None,
            typer.Option("--decision-to-block", min=1),
        ] = None,
    ) -> None:
        """Inspect metadata and optionally generate bounded source evidence."""

        try:
            # Perform the protected inspect source operation before explicit failure
            # handling.
            if (evidence_from_block is None) != (evidence_to_block is None):
                # Handle the inspect source evidence from block and evidence to block
                # condition as a distinct block.
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
            if (
                # Keep evidence from block visible while evaluating the evidence from
                # block and evidence to block guard.
                evidence_from_block is not None
                and evidence_to_block is not None
                and evidence_to_block <= evidence_from_block
            ):
                # Handle the inspect source evidence from block and evidence to block
                # condition as a distinct block.
                raise CliUsageError(
                    "INVALID_EVIDENCE_RANGE",
                    "The bounded evidence block range must be non-empty.",
                )
            if (
                decision_from_block is not None
                and decision_to_block is not None
                and decision_to_block <= decision_from_block
            ):
                raise CliUsageError(
                    "INVALID_DECISION_RANGE",
                    "The decision block range must be non-empty.",
                )
            if (
                decision_from_block is not None
                and decision_to_block is not None
                and evidence_from_block is not None
                and evidence_to_block is not None
                and (
                    decision_from_block < evidence_from_block
                    or decision_to_block > evidence_to_block
                )
            ):
                raise CliUsageError(
                    "INVALID_DECISION_RANGE",
                    "The decision block range must be inside the evidence range.",
                )
            backend = backend_factory(config, capabilities, require_capabilities=True)
            # Assemble selected source once so the inspect source workflow shares one
            # value.
            selected_source = None if source_id is None else SourceId(source_id)
            stored = backend.inspect_source(
                selected_source,
                evidence_from_block=evidence_from_block,
                evidence_to_block=evidence_to_block,
                decision_from_block=decision_from_block,
                decision_to_block=decision_to_block,
                # Complete inspect_source only after its selected source and evidence from
                # block inputs are visible in inspect source.
            )
            typer.echo(SourceInspectionResponse.from_stored(stored).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    # Define plan dataset as one focused operation with an explicit boundary.
    def plan_dataset(
        request_file: Annotated[Path, typer.Argument(help="Versioned plan command JSON.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
        capabilities: CapabilityPath = None,
    ) -> None:
        """Compile requirements into selective columns and half-open shards."""

        try:
            # Perform the protected plan dataset operation before explicit failure
            # handling.
            command = PlanDatasetCommand.model_validate_json(_bounded_read(request_file))
            backend = backend_factory(config, capabilities, require_capabilities=True)
            plan = backend.plan_dataset(command.to_domain())
            typer.echo(DatasetPlanResponse.from_domain(plan).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible plan dataset step.
            _fail(error)

    @cli.command()
    def submit_job(
        job_type: Annotated[JobType, typer.Option("--type")],
        payload_file: Annotated[Path, typer.Option("--payload")],
        # Keep the idempotency key input explicit in the submit job contract.
        idempotency_key: Annotated[str, typer.Option("--idempotency-key")],
        input_artifact: Annotated[
            list[str] | None,
            typer.Option("--input-artifact"),
        ] = None,
        # Keep the spec version input explicit in the submit job contract.
        spec_version: Annotated[int, typer.Option("--spec-version", min=1)] = 1,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Resolve and durably enqueue one immutable local job command."""

        try:
            # Perform the protected submit job operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            record = backend.submit_job(
                SubmitJobRequest(
                    spec_version=spec_version,
                    job_type=job_type,
                    # Keep the payload file _bounded_read step visible while building
                    # record.
                    payload_json=_bounded_read(payload_file),
                    idempotency_key=idempotency_key,
                    input_artifact_ids=tuple(ArtifactId(value) for value in (input_artifact or [])),
                )
            )
            # Invoke echo for model dump json and job response as a visible submit job
            # step.
            typer.echo(_job_response(record).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("jobs")
    def list_jobs(
        # Keep the state input explicit in the list jobs contract.
        state: Annotated[AttemptState | None, typer.Option("--state")] = None,
        limit: Annotated[int, typer.Option(min=1, max=1_000)] = 100,
        offset: Annotated[int, typer.Option(min=0)] = 0,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """List bounded operational job metadata."""

        try:
            # Perform the protected list jobs operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            records = backend.list_jobs(ListJobsRequest(state=state, limit=limit, offset=offset))
            response = JobListResponse(items=tuple(_job_response(record) for record in records))
            # CLI uses offsets; preserve its envelope without HTTP-only continuation metadata.
            typer.echo(response.model_dump_json(indent=2, exclude={"next_cursor"}))
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible list jobs step.
            _fail(error)

    @cli.command()
    def get_job(
        job_id: Annotated[str, typer.Argument()],
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the get job signature after its explicit inputs.
    ) -> None:
        """Show one operational job record."""

        try:
            # Perform the protected get job operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            record = backend.get_job(JobId(job_id))
            typer.echo(_job_response(record).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following cancel job contract.
    @cli.command()
    def cancel_job(
        job_id: Annotated[str, typer.Argument()],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Durably request cancellation of a non-terminal job."""

        try:
            # Perform the protected cancel job operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            record = backend.cancel_job(JobId(job_id))
            typer.echo(_job_response(record).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following retry job contract.
    @cli.command()
    def retry_job(
        job_id: Annotated[str, typer.Argument()],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Durably requeue one failed or interrupted immutable job command."""

        try:
            # Perform the protected retry job operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            record = backend.retry_job(JobId(job_id))
            typer.echo(_job_response(record).model_dump_json(indent=2))
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following verify artifact contract.
    @cli.command()
    def verify_artifact(
        artifact_id: Annotated[str, typer.Argument(help="Exact committed artifact ID.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Reverify one exact committed artifact and print bounded metadata."""

        try:
            # Perform the protected verify artifact operation before explicit failure
            # handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            details = backend.verify_artifact(ArtifactId(artifact_id))
            manifest = json.loads(details.manifest_bytes)
            if not isinstance(manifest, dict):
                raise ValueError("artifact manifest root must be an object")
            # Invoke echo for descriptor and manifest as a visible verify artifact step.
            typer.echo(
                json.dumps(
                    {
                        "descriptor": _artifact_document(details.descriptor),
                        "manifest": manifest,
                        # Keep verified named so the descriptor and manifest payload
                        # passed to dumps remains self-describing within verify artifact.
                        "verified": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    # Complete dumps only after its descriptor and manifest inputs are visible
                    # in verify artifact.
                )
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    # Define list runs as one focused operation with an explicit boundary.
    def list_runs(
        limit: Annotated[int, typer.Option(min=1, max=1_000)] = 100,
        offset: Annotated[int, typer.Option(min=0)] = 0,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """List bounded verified committed run summaries."""

        try:
            # Perform the protected list runs operation before explicit failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            typer.echo(
                json.dumps(
                    {
                        "items": [
                            # Pass run summary document explicitly to echo for items and
                            # dumps.
                            _run_summary_document(item)
                            for item in backend.list_runs(limit=limit, offset=offset)
                        ]
                    },
                    indent=2,
                    # Pass sort keys explicitly so dumps receives a reviewable items and
                    # list runs input in list runs.
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following describe run contract contract.
    @cli.command()
    def describe_run_contract(
        contract_schema: Annotated[
            str,
            typer.Argument(help="Exact versioned run-draft contract schema."),
            # Close the describe run contract signature after its explicit inputs.
        ],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Print one closed typed run contract and its immutable semantics."""

        try:
            # Perform the protected describe run contract operation before explicit
            # failure handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            typer.echo(
                json.dumps(
                    backend.describe_run_contract(contract_schema).document(),
                    indent=2,
                    # Pass sort keys explicitly so dumps receives a reviewable document
                    # and describe run contract input in describe run contract.
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following show run summary contract.
    @cli.command()
    def show_run_summary(
        run_artifact_id: Annotated[
            str,
            typer.Argument(help="Exact committed Pump.fun Sniping Run artifact ID."),
            # Close the show run summary signature after its explicit inputs.
        ],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Verify and print bounded Pump.fun Sniping summary metadata."""

        try:
            # Perform the protected show run summary operation before explicit failure
            # handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            summary = backend.show_run_summary(ArtifactId(run_artifact_id))
            typer.echo(json.dumps(_sniping_summary_document(summary), indent=2, sort_keys=True))
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following list roundtrips contract.
    @cli.command()
    def list_roundtrips(
        run_artifact_id: Annotated[
            str,
            typer.Argument(help="Exact committed Pump.fun Sniping Run artifact ID."),
            # Close the list roundtrips signature after its explicit inputs.
        ],
        after: Annotated[
            str | None,
            typer.Option(
                "--after",
                # Pass help explicitly so Option receives a reviewable --after and value
                # input in list roundtrips.
                help="Exclusive keyset cursor as BOUNDARY_ORDINAL:ROUNDTRIP_ID.",
            ),
        ] = None,
        limit: Annotated[int, typer.Option(min=1, max=200)] = 200,
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the list roundtrips signature after its explicit inputs.
    ) -> None:
        """Verify and print one keyset page of Pump.fun target lifecycles."""

        try:
            # Perform the protected list roundtrips operation before explicit failure
            # handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            page = backend.list_roundtrips(
                ArtifactId(run_artifact_id),
                after=_roundtrip_cursor(after),
                limit=limit,
                # Complete list_roundtrips only after its artifact id and roundtrip cursor
                # inputs are visible in list roundtrips.
            )
            typer.echo(json.dumps(_roundtrip_page_document(page), indent=2, sort_keys=True))
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    # Define show lineage as one focused operation with an explicit boundary.
    def show_lineage(
        artifact_id: Annotated[str, typer.Argument(help="Exact committed artifact ID.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Show the verified transitive input closure for one artifact."""

        try:
            # Perform the protected show lineage operation before explicit failure
            # handling.
            backend = backend_factory(config, None, prefer_running_controller=True)
            lineage = backend.show_lineage(ArtifactId(artifact_id))
            typer.echo(
                json.dumps(
                    {
                        # Pass artifacts explicitly to echo for artifacts and edges.
                        "artifacts": [_artifact_document(item) for item in lineage.artifacts],
                        "edges": [
                            {
                                "input_artifact_id": edge.input_artifact_id.hex,
                                "output_artifact_id": edge.output_artifact_id.hex,
                                # Close the artifacts and edges payload only after all show
                                # lineage fields are present.
                            }
                            for edge in lineage.edges
                        ],
                        "root_artifact_id": lineage.root_artifact_id.hex,
                    },
                    # Pass indent explicitly so dumps receives a reviewable artifacts and
                    # edges input in show lineage.
                    indent=2,
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible show lineage step.
            _fail(error)

    @cli.command()
    def pin(
        pin_id: Annotated[str, typer.Argument(help="Immutable local pin ID.")],
        root: Annotated[
            # Keep the list input explicit in the pin contract.
            list[str],
            typer.Option("--root", help="Exact committed retention root; repeatable."),
        ],
        reason: Annotated[str, typer.Option("--reason")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the pin signature after its explicit inputs.
    ) -> None:
        """Atomically retain exact committed roots and their verified closure."""

        try:
            # Perform the protected pin operation before explicit failure handling.
            backend = backend_factory(config, None)
            record = backend.create_pin(
                Identifier(pin_id),
                tuple(ArtifactId(value) for value in root),
                reason,
                # Complete create_pin only after its identifier and tuple inputs are visible
                # in pin.
            )
            typer.echo(json.dumps(_pin_document(record), indent=2, sort_keys=True))
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    # Define unpin as one focused operation with an explicit boundary.
    def unpin(
        pin_id: Annotated[str, typer.Argument(help="Existing immutable local pin ID.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Atomically retire a pin into the durable retired namespace."""

        try:
            # Perform the protected unpin operation before explicit failure handling.
            backend = backend_factory(config, None)
            record = backend.retire_pin(Identifier(pin_id))
            typer.echo(
                json.dumps(
                    {**_pin_document(record), "status": "RETIRED"},
                    # Pass indent explicitly so dumps receives a reviewable retired and
                    # status input in unpin.
                    indent=2,
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible unpin step.
            _fail(error)

    @cli.command()
    def gc(
        execute: Annotated[
            bool,
            # Keep the typer input explicit in the gc contract.
            typer.Option(
                "--execute/--dry-run",
                help="Move the freshly revalidated plan to trash, or only show it.",
            ),
        ] = False,
        # Keep the retain input explicit in the gc contract.
        retain: Annotated[
            list[str] | None,
            typer.Option("--retain", help="Additional exact root protected for this plan."),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the gc signature after its explicit inputs.
    ) -> None:
        """Plan or execute reachability GC without deleting trash immediately."""

        try:
            # Perform the protected gc operation before explicit failure handling.
            backend = backend_factory(config, None)
            roots = tuple(ArtifactId(value) for value in (retain or []))
            if execute:
                # Handle the gc execute branch as a distinct logical block.
                plan, batch = backend.execute_garbage_collection(roots)
                document: dict[str, object] = {
                    "batch": _gc_batch_document(batch),
                    "mode": "EXECUTE",
                    "plan": _gc_plan_document(plan),
                    # Complete the document group only after its semantic components are
                    # visible.
                }
            else:
                # Handle the gc complement of execute explicitly.
                document = {
                    "mode": "DRY_RUN",
                    "plan": _gc_plan_document(backend.plan_garbage_collection(roots)),
                }
            typer.echo(json.dumps(document, indent=2, sort_keys=True))
        # Translate known errors through the gc boundary without hiding other errors.
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("gc-purge")
    def gc_purge(
        batch_id: Annotated[str, typer.Argument(help="Committed GC batch ID.")],
        # Keep the config input explicit in the gc purge contract.
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Physically delete one verified trash batch after its configured grace."""

        try:
            # Perform the protected gc purge operation before explicit failure handling.
            backend = backend_factory(config, None)
            receipt = backend.purge_trash(ContentDigest(batch_id))
            typer.echo(
                json.dumps(
                    {
                        # Keep artifact ids named so the artifact ids and batch id payload
                        # passed to dumps remains self-describing within gc purge.
                        "artifact_ids": [item.hex for item in receipt.artifact_ids],
                        "batch_id": receipt.batch_id.hex,
                        "deleted_at_ns": receipt.deleted_at_ns,
                        "deleted_bytes": receipt.deleted_bytes,
                        "receipt_digest": receipt.receipt_digest.hex,
                        # Close the artifact ids and batch id payload only after all gc purge
                        # fields are present.
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        # Translate known errors through the gc purge boundary without hiding other
        # errors.
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    def backup(
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the backup signature after its explicit inputs.
    ) -> None:
        """Create one verified generation at the host-configured external target."""

        try:
            # Perform the protected backup operation before explicit failure handling.
            generation = backend_factory(config, None).create_backup()
            typer.echo(json.dumps(_backup_document(generation), indent=2, sort_keys=True))
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("restore-verify")
    # Define restore verify as one focused operation with an explicit boundary.
    def restore_verify(
        backup_cut_id: Annotated[str, typer.Argument(help="Committed backup cut ID.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Restore one generation into a fresh configured drill directory and verify it."""

        try:
            # Perform the protected restore verify operation before explicit failure
            # handling.
            recovery_backend: CliRecoveryBackend
            if recovery_backend_factory is None:
                recovery_backend = backend_factory(config, None)
            else:
                recovery_backend = recovery_backend_factory(config)
            # Assemble (report, destination name) once so the restore verify workflow
            # shares one value.
            report, destination_name = recovery_backend.verify_restore(ContentDigest(backup_cut_id))
            typer.echo(
                json.dumps(
                    _restore_document(report, destination_name=destination_name),
                    indent=2,
                    # Pass sort keys explicitly so dumps receives a reviewable restore
                    # document and report input in restore verify.
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following serve contract.
    @cli.command()
    def serve(
        config: ConfigPath = Path("configs/local-16gb.toml"),
        capabilities: CapabilityPath = None,
    ) -> None:
        """Run the loopback Control API and packaged Web UI."""

        try:
            backend_factory(config, capabilities).serve()
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    # Define prepare dataset as one focused operation with an explicit boundary.
    def prepare_dataset(
        request_file: Annotated[Path, typer.Argument(help="Versioned plan command JSON.")],
        config: ConfigPath = Path("configs/local-16gb.toml"),
        capabilities: CapabilityPath = None,
    ) -> None:
        """Extract bounded shards and publish a committed canonical snapshot."""

        try:
            # Perform the protected prepare dataset operation before explicit failure
            # handling.
            command = PlanDatasetCommand.model_validate_json(_bounded_read(request_file))
            backend = backend_factory(config, capabilities, require_capabilities=True)
            plan = backend.plan_dataset(command.to_domain())
            prepared = backend.prepare_dataset(plan)
            typer.echo(
                # Pass json explicitly to echo for dataset revision id and logical content
                # hash.
                json.dumps(
                    {
                        "dataset_revision_id": prepared.dataset_revision_id.hex,
                        "logical_content_hash": prepared.logical_content_hash.hex,
                        "snapshot_id": prepared.snapshot_id.hex,
                        # Close the dataset revision id and logical content hash payload only
                        # after all prepare dataset fields are present.
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                # Complete echo only after its dataset revision id and logical content hash
                # inputs are visible in prepare dataset.
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    def compile_replay(
        # Keep the snapshot id input explicit in the compile replay contract.
        snapshot_id: Annotated[str, typer.Argument()],
        compiler_version: Annotated[str, typer.Option("--compiler-version")] = "numpy-mmap-v3",
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Compile a verified canonical snapshot into a local mmap ReplayPack."""

        try:
            # Perform the protected compile replay operation before explicit failure
            # handling.
            backend = backend_factory(config, None)
            compiled = backend.compile_replay(
                CompileReplayRequest(SnapshotId(snapshot_id), compiler_version)
            )
            typer.echo(
                # Pass json explicitly to echo for replay build key and replay layout
                # schema id.
                json.dumps(
                    {
                        "replay_build_key": compiled.requested_build.replay_build_key.hex,
                        "replay_layout_schema_id": (
                            compiled.manifest.layout.replay_layout_schema_id.hex
                            # Complete dumps only after its replay build key and replay layout
                            # schema id inputs are visible in compile replay.
                        ),
                        "replay_pack_id": compiled.replay_pack_id.hex,
                        "replay_semantics_id": (
                            compiled.manifest.semantics.replay_semantics_id.hex
                        ),
                        # Keep snapshot id named so the replay build key and replay layout
                        # schema id payload passed to dumps remains self-describing within
                        # compile replay.
                        "snapshot_id": compiled.manifest.snapshot_id.hex,
                    },
                    indent=2,
                    sort_keys=True,
                )
                # Complete echo only after its replay build key and replay layout schema id
                # inputs are visible in compile replay.
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    def compile_delivery_schedule(
        # Keep the resolved spec file input explicit in the compile delivery schedule
        # contract.
        resolved_spec_file: Annotated[
            Path, typer.Argument(help="Exact ResolvedRunSpec using a ReplayPack.")
        ],
        compiler_version: Annotated[
            str, typer.Option("--compiler-version")
            # Keep the numpy input explicit in the compile delivery schedule contract.
        ] = "numpy-delivery-mmap-v1",
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Materialize the exact observation delivery stream for repeated runs."""

        try:
            # Perform the protected compile delivery schedule operation before explicit
            # failure handling.
            spec = resolved_run_spec_from_bytes(_bounded_read(resolved_spec_file))
            backend = backend_factory(config, None)
            compiled = backend.compile_delivery_schedule(
                spec,
                compiler_version,
                # Complete compile_delivery_schedule only after its spec and compiler version
                # inputs are visible in compile delivery schedule.
            )
            typer.echo(
                json.dumps(
                    {
                        "delivery_build_key": compiled.delivery_build_key.hex,
                        # Keep delivery schedule id named so the delivery build key and
                        # delivery schedule id payload passed to dumps remains self-
                        # describing within compile delivery schedule.
                        "delivery_schedule_id": compiled.delivery_schedule_id.hex,
                        "delivery_stream_hash": (
                            compiled.manifest.logical_delivery_stream_hash.hex
                        ),
                        "replay_pack_id": compiled.manifest.replay_pack_id.hex,
                        # Close the delivery build key and delivery schedule id payload only
                        # after all compile delivery schedule fields are present.
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        # Translate known errors through the compile delivery schedule boundary without
        # hiding other errors.
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    def resolve_run(
        draft_file: Annotated[
            # Keep the help input explicit in the resolve run contract.
            Path, typer.Argument(help="Typed reference RunSpecDraft JSON document.")
        ],
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Pin exact local artifacts, defaults and bundles into a ResolvedRunSpec."""

        try:
            # Perform the protected resolve run operation before explicit failure
            # handling.
            command = run_draft_command_from_bytes(_bounded_read(draft_file))
            backend = backend_factory(config, None)
            spec = backend.resolve_run_spec(command.to_domain())
            typer.echo(json.dumps(spec.document(), indent=2, sort_keys=True))
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible resolve run step.
            _fail(error)

    @cli.command("run-backtest")
    @cli.command("run")
    def run_backtest(
        resolved_spec_file: Annotated[
            # Keep the help input explicit in the run backtest contract.
            Path, typer.Argument(help="Exact ResolvedRunSpec JSON document.")
        ],
        attempt_nonce: Annotated[str, typer.Option("--attempt-nonce")],
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            # Keep the str input explicit in the run backtest contract.
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        run_backend: Annotated[
            RunBackend | None,
            # Keep the case sensitive input explicit in the run backtest contract.
            typer.Option("--backend", case_sensitive=True),
        ] = None,
        reader_batch_rows: Annotated[
            int | None,
            typer.Option("--reader-batch-rows", min=1),
            # Close the run backtest signature after its explicit inputs.
        ] = None,
        reader_readahead: Annotated[
            int | None,
            typer.Option("--reader-readahead"),
        ] = None,
        # Keep the output buffer rows input explicit in the run backtest contract.
        output_buffer_rows: Annotated[
            int | None,
            typer.Option("--output-buffer-rows", min=1),
        ] = None,
        threads: Annotated[
            # Keep the int input explicit in the run backtest contract.
            int | None,
            typer.Option("--threads", min=1),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Run one sequential deterministic backtest from committed local inputs."""

        try:
            # Perform the protected run backtest operation before explicit failure
            # handling.
            backend = backend_factory(
                config,
                None,
                prefer_running_controller=enqueue,
            )
            # Assemble defaults once so the run backtest workflow shares one value.
            defaults = backend.default_run_physical_settings()
            physical_settings = _selected_run_physical_settings(
                defaults,
                profile_threads=defaults.threads,
                run_backend=run_backend,
                # Pass reader batch rows explicitly so _selected_run_physical_settings
                # receives a reviewable threads and defaults input in run backtest.
                reader_batch_rows=reader_batch_rows,
                reader_readahead=reader_readahead,
                output_buffer_rows=output_buffer_rows,
                threads=threads,
            )
            # Assemble request once so the run backtest workflow shares one value.
            request = RunBacktestRequest(
                resolved_run_spec_from_bytes(_bounded_read(resolved_spec_file)),
                ContentDigest(attempt_nonce),
                physical_settings,
            )
            # Guard this path with enqueue before applying effects.
            if enqueue:
                # Handle the run backtest enqueue branch as a distinct logical block.
                if idempotency_key is None:
                    # Handle the run backtest idempotency_key is None branch as a distinct
                    # logical block.
                    raise CliUsageError(
                        "IDEMPOTENCY_KEY_REQUIRED",
                        "Queued runs require an explicit idempotency key.",
                    )
                command = ResolvedBacktestJob(
                    # Pass request explicitly so ResolvedBacktestJob receives a reviewable
                    # resolved spec and attempt nonce input in run backtest.
                    request.resolved_spec,
                    request.attempt_nonce,
                    request.physical_settings,
                )
                record = backend.submit_job(
                    # Keep the submit job request and run backtest SubmitJobRequest step
                    # visible while building record.
                    SubmitJobRequest(
                        spec_version=1,
                        job_type=JobType.RUN_BACKTEST,
                        payload_json=command.canonical_bytes(),
                        idempotency_key=idempotency_key,
                        # Complete SubmitJobRequest only after its run backtest and canonical
                        # bytes inputs are visible in run backtest.
                    )
                )
                typer.echo(_job_response(record).model_dump_json(indent=2))
                return
            if idempotency_key is not None:
                # Handle the run backtest idempotency_key is not None branch as a distinct
                # logical block.
                raise CliUsageError(
                    "IDEMPOTENCY_KEY_WITHOUT_ENQUEUE",
                    "An idempotency key is only accepted together with --enqueue.",
                )
            result = backend.run_backtest(request)
            # Invoke echo for execution attempt id and logical run id as a visible run
            # backtest step.
            typer.echo(
                json.dumps(
                    {
                        "execution_attempt_id": result.execution_attempt_id.hex,
                        "logical_run_id": result.logical_run_id.hex,
                        # Keep run artifact id named so the execution attempt id and
                        # logical run id payload passed to dumps remains self-describing
                        # within run backtest.
                        "run_artifact_id": result.artifact.artifact_id.hex,
                    },
                    indent=2,
                    sort_keys=True,
                )
                # Complete echo only after its execution attempt id and logical run id inputs
                # are visible in run backtest.
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("run-sweep")
    @cli.command("sweep")
    # Define run sweep as one focused operation with an explicit boundary.
    def run_sweep(
        resolved_sweep_spec_file: Annotated[
            Path, typer.Argument(help="Exact ResolvedSweepSpec JSON document.")
        ],
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        # Keep the idempotency key input explicit in the run sweep contract.
        idempotency_key: Annotated[
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        run_backend: Annotated[
            # Keep the run backend input explicit in the run sweep contract.
            RunBackend | None,
            typer.Option("--backend", case_sensitive=True),
        ] = None,
        reader_batch_rows: Annotated[
            int | None,
            # Keep the min input explicit in the run sweep contract.
            typer.Option("--reader-batch-rows", min=1),
        ] = None,
        reader_readahead: Annotated[
            int | None,
            typer.Option("--reader-readahead"),
            # Close the run sweep signature after its explicit inputs.
        ] = None,
        output_buffer_rows: Annotated[
            int | None,
            typer.Option("--output-buffer-rows", min=1),
        ] = None,
        # Keep the threads input explicit in the run sweep contract.
        threads: Annotated[
            int | None,
            typer.Option("--threads", min=1),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
        # Close the run sweep signature after its explicit inputs.
    ) -> None:
        """Run independent resolved attempts and compare canonical results."""

        try:
            # Perform the protected run sweep operation before explicit failure handling.
            backend = backend_factory(
                config,
                None,
                prefer_running_controller=enqueue,
            )
            # Assemble resolved once so the run sweep workflow shares one value.
            resolved = resolved_sweep_spec_from_bytes(_bounded_read(resolved_sweep_spec_file))
            defaults = backend.default_run_physical_settings()
            spec = ResolvedSweepSpec.create(
                tuple(
                    SweepEntry(
                        # Pass entry explicitly so SweepEntry receives a reviewable
                        # resolved spec and attempt nonce input in run sweep.
                        entry.resolved_spec,
                        entry.attempt_nonce,
                        _selected_run_physical_settings(
                            entry.physical_settings,
                            profile_threads=defaults.threads,
                            # Pass run backend explicitly so
                            # _selected_run_physical_settings receives a reviewable
                            # physical settings and threads input in run sweep.
                            run_backend=run_backend,
                            reader_batch_rows=reader_batch_rows,
                            reader_readahead=reader_readahead,
                            output_buffer_rows=output_buffer_rows,
                            threads=threads,
                            # Complete _selected_run_physical_settings only after its physical
                            # settings and threads inputs are visible in run sweep.
                        ),
                    )
                    for entry in resolved.entries
                ),
                comparison_metrics=resolved.comparison_metrics,
                # Complete create only after its resolved spec and attempt nonce inputs are
                # visible in run sweep.
            )
            if enqueue:
                # Handle the run sweep enqueue branch as a distinct logical block.
                if idempotency_key is None:
                    # Handle the run sweep idempotency_key is None branch as a distinct
                    # logical block.
                    raise CliUsageError(
                        "IDEMPOTENCY_KEY_REQUIRED",
                        "Queued sweeps require an explicit idempotency key.",
                    )
                command = ResolvedSweepJob(spec)
                # Assemble record once so the run sweep workflow shares one value.
                record = backend.submit_job(
                    SubmitJobRequest(
                        spec_version=1,
                        job_type=JobType.RUN_SWEEP,
                        payload_json=command.canonical_bytes(),
                        # Pass idempotency key explicitly so SubmitJobRequest receives a
                        # reviewable run sweep and canonical bytes input in run sweep.
                        idempotency_key=idempotency_key,
                    )
                )
                typer.echo(_job_response(record).model_dump_json(indent=2))
                return
            # Guard this path with idempotency_key is not None before applying effects.
            if idempotency_key is not None:
                # Handle the run sweep idempotency_key is not None branch as a distinct
                # logical block.
                raise CliUsageError(
                    "IDEMPOTENCY_KEY_WITHOUT_ENQUEUE",
                    "An idempotency key is only accepted together with --enqueue.",
                )
            result = backend.run_sweep(spec)
            # Invoke echo for entries and result digest as a visible run sweep step.
            typer.echo(
                json.dumps(
                    {
                        "entries": [
                            {
                                # Keep canonical result hash named so the entries and
                                # result digest payload passed to dumps remains self-
                                # describing within run sweep.
                                "canonical_result_hash": item.canonical_result_hash.hex,
                                "entry_id": item.entry_id.hex,
                                "execution_attempt_id": item.execution_attempt_id.hex,
                                "logical_run_id": item.logical_run_id.hex,
                                "run_artifact_id": item.run_artifact.artifact_id.hex,
                                # Close the entries and result digest payload only after all
                                # run sweep fields are present.
                            }
                            for item in result.entries
                        ],
                        "result_digest": result.result_digest.hex,
                        "sweep_spec_id": result.sweep_spec_id.hex,
                        # Close the entries and result digest payload only after all run sweep
                        # fields are present.
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        # Translate known errors through the run sweep boundary without hiding other
        # errors.
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("build-features")
    def build_features(
        request_file: Annotated[
            # Keep the help input explicit in the build features contract.
            Path, typer.Argument(help="Typed resolved build-features command JSON.")
        ],
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            str | None,
            # Keep the typer input explicit in the build features contract.
            typer.Option("--idempotency-key"),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Build a point-in-time FeatureSet from exact committed inputs."""

        try:
            # Perform the protected build features operation before explicit failure
            # handling.
            command = BuildFeaturesJobForm.model_validate_json(
                _bounded_read(request_file)
            ).to_domain()
            _execute_ml_command(
                backend_factory(
                    # Pass config explicitly so backend_factory receives a reviewable
                    # config and enqueue input in build features.
                    config,
                    None,
                    prefer_running_controller=enqueue,
                ),
                command,
                # Pass enqueue explicitly so _execute_ml_command receives a reviewable
                # backend factory and config input in build features.
                enqueue=enqueue,
                idempotency_key=idempotency_key,
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following build universe contract.
    @cli.command("build-universe")
    def build_universe(
        request_file: Annotated[
            Path, typer.Argument(help="Typed resolved build-universe command JSON.")
        ],
        # Keep the enqueue input explicit in the build universe contract.
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        # Keep the config input explicit in the build universe contract.
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Build a point-in-time Universe from exact committed inputs."""

        try:
            # Perform the protected build universe operation before explicit failure
            # handling.
            command = BuildUniverseJobForm.model_validate_json(
                _bounded_read(request_file)
            ).to_domain()
            _execute_ml_command(
                backend_factory(
                    # Pass config explicitly so backend_factory receives a reviewable
                    # config and enqueue input in build universe.
                    config,
                    None,
                    prefer_running_controller=enqueue,
                ),
                command,
                # Pass enqueue explicitly so _execute_ml_command receives a reviewable
                # backend factory and config input in build universe.
                enqueue=enqueue,
                idempotency_key=idempotency_key,
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following build labels contract.
    @cli.command("build-labels")
    def build_labels(
        request_file: Annotated[
            Path, typer.Argument(help="Typed resolved build-labels command JSON.")
        ],
        # Keep the enqueue input explicit in the build labels contract.
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        # Keep the config input explicit in the build labels contract.
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Build a training-only LabelSet from exact committed inputs."""

        try:
            # Perform the protected build labels operation before explicit failure
            # handling.
            command = BuildLabelsJobForm.model_validate_json(
                _bounded_read(request_file)
            ).to_domain()
            _execute_ml_command(
                backend_factory(
                    # Pass config explicitly so backend_factory receives a reviewable
                    # config and enqueue input in build labels.
                    config,
                    None,
                    prefer_running_controller=enqueue,
                ),
                command,
                # Pass enqueue explicitly so _execute_ml_command receives a reviewable
                # backend factory and config input in build labels.
                enqueue=enqueue,
                idempotency_key=idempotency_key,
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following train contract.
    @cli.command("train")
    def train(
        request_file: Annotated[
            Path, typer.Argument(help="Typed resolved train-model command JSON.")
        ],
        # Keep the enqueue input explicit in the train contract.
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        # Keep the config input explicit in the train contract.
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Train an exact model bundle from point-in-time artifacts."""

        try:
            # Perform the protected train operation before explicit failure handling.
            command = TrainModelJobForm.model_validate_json(_bounded_read(request_file)).to_domain()
            _execute_ml_command(
                backend_factory(
                    config,
                    None,
                    # Pass prefer running controller explicitly so backend_factory
                    # receives a reviewable config and enqueue input in train.
                    prefer_running_controller=enqueue,
                ),
                command,
                enqueue=enqueue,
                idempotency_key=idempotency_key,
                # Complete _execute_ml_command only after its backend factory and config
                # inputs are visible in train.
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command("build-model-schedule")
    def build_model_schedule(
        # Keep the request file input explicit in the build model schedule contract.
        request_file: Annotated[
            Path, typer.Argument(help="Typed resolved model-schedule command JSON.")
        ],
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            # Keep the str input explicit in the build model schedule contract.
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Publish an exact point-in-time model schedule."""

        try:
            # Perform the protected build model schedule operation before explicit failure
            # handling.
            command = BuildModelScheduleJobForm.model_validate_json(
                _bounded_read(request_file)
            ).to_domain()
            _execute_ml_command(
                backend_factory(
                    # Pass config explicitly so backend_factory receives a reviewable
                    # config and enqueue input in build model schedule.
                    config,
                    None,
                    prefer_running_controller=enqueue,
                ),
                command,
                # Pass enqueue explicitly so _execute_ml_command receives a reviewable
                # backend factory and config input in build model schedule.
                enqueue=enqueue,
                idempotency_key=idempotency_key,
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Apply command semantics to the following predict contract.
    @cli.command("predict")
    def predict(
        request_file: Annotated[Path, typer.Argument(help="Typed resolved predict command JSON.")],
        enqueue: Annotated[bool, typer.Option("--enqueue")] = False,
        idempotency_key: Annotated[
            # Keep the str input explicit in the predict contract.
            str | None,
            typer.Option("--idempotency-key"),
        ] = None,
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Build frozen predictions from exact features and model schedule."""

        try:
            # Perform the protected predict operation before explicit failure handling.
            command = PredictJobForm.model_validate_json(_bounded_read(request_file)).to_domain()
            _execute_ml_command(
                backend_factory(
                    config,
                    None,
                    # Pass prefer running controller explicitly so backend_factory
                    # receives a reviewable config and enqueue input in predict.
                    prefer_running_controller=enqueue,
                ),
                command,
                enqueue=enqueue,
                idempotency_key=idempotency_key,
                # Complete _execute_ml_command only after its backend factory and config
                # inputs are visible in predict.
            )
        except _KNOWN_ERRORS as error:
            _fail(error)

    @cli.command()
    def benchmark(
        # Keep the target artifact id input explicit in the benchmark contract.
        target_artifact_id: Annotated[
            str,
            typer.Argument(help="Exact committed target artifact ID."),
        ],
        attempt_nonce: Annotated[str, typer.Option("--attempt-nonce")],
        # Keep the workload input explicit in the benchmark contract.
        workload: Annotated[
            BenchmarkWorkload,
            typer.Option("--workload"),
        ] = BenchmarkWorkload.REPLAY_PACK_SCAN,
        launch_route: Annotated[
            # Keep the benchmark launch route input explicit in the benchmark contract.
            BenchmarkLaunchRoute,
            typer.Option("--launch-route"),
        ] = BenchmarkLaunchRoute.LOCAL_ARTIFACT,
        cache_condition: Annotated[
            CacheCondition,
            # Keep the typer input explicit in the benchmark contract.
            typer.Option("--cache-condition"),
        ] = CacheCondition.WARM,
        capacity_days: Annotated[int, typer.Option("--capacity-days")] = 1,
        batch_rows: Annotated[int, typer.Option("--batch-rows")] = 65_536,
        readahead: Annotated[int, typer.Option("--readahead")] = 1,
        # Keep the process count input explicit in the benchmark contract.
        process_count: Annotated[int, typer.Option("--process-count")] = 1,
        native_threads: Annotated[int, typer.Option("--native-threads", min=1)] = 1,
        warmup_iterations: Annotated[
            int,
            typer.Option("--warmup-iterations", min=0, max=10),
            # Close the benchmark signature after its explicit inputs.
        ] = 1,
        measured_iterations: Annotated[
            int,
            typer.Option("--measured-iterations", min=1, max=100),
        ] = 3,
        # Keep the config input explicit in the benchmark contract.
        config: ConfigPath = Path("configs/local-16gb.toml"),
    ) -> None:
        """Profile and measure one exact committed local artifact target."""

        try:
            # Perform the protected benchmark operation before explicit failure handling.
            backend = backend_factory(config, None)
            published = backend.run_benchmark(
                ExactBenchmarkCommand(
                    target_artifact_id=ArtifactId(target_artifact_id),
                    workload=workload,
                    # Pass launch route explicitly so ExactBenchmarkCommand receives a
                    # reviewable artifact id and content digest input in benchmark.
                    launch_route=launch_route,
                    cache_condition=cache_condition,
                    batch_rows=batch_rows,
                    readahead=readahead,
                    process_count=process_count,
                    # Pass native threads per process explicitly so ExactBenchmarkCommand
                    # receives a reviewable artifact id and content digest input in
                    # benchmark.
                    native_threads_per_process=native_threads,
                    warmup_iterations=warmup_iterations,
                    measured_iterations=measured_iterations,
                    capacity_days=capacity_days,
                    attempt_nonce=ContentDigest(attempt_nonce),
                    # Complete ExactBenchmarkCommand only after its artifact id and content
                    # digest inputs are visible in benchmark.
                )
            )
            report = published.report
            typer.echo(
                json.dumps(
                    # Open the benchmark artifact id and benchmark spec id payload
                    # explicitly for dumps within benchmark.
                    {
                        "benchmark_artifact_id": published.artifact.artifact_id.hex,
                        "benchmark_spec_id": report.spec.benchmark_spec_id.hex,
                        "canonical_result_hash": report.canonical_result_hash.hex,
                        "median_items_per_second": report.median_items_per_second,
                        # Keep p95 wall time ns named so the benchmark artifact id and
                        # benchmark spec id payload passed to dumps remains self-
                        # describing within benchmark.
                        "p95_wall_time_ns": report.p95_wall_time_ns,
                        "profiler": [item.document() for item in report.profiler],
                        "report_digest": report.report_digest.hex,
                        "samples": [item.document() for item in report.samples],
                    },
                    # Pass indent explicitly so dumps receives a reviewable benchmark
                    # artifact id and benchmark spec id input in benchmark.
                    indent=2,
                    sort_keys=True,
                )
            )
        except _KNOWN_ERRORS as error:
            # Invoke _fail for error as a visible benchmark step.
            _fail(error)

    return cli


def _selected_run_physical_settings(
    base: RunPhysicalSettings,
    *,
    # Keep the profile threads input explicit in the selected run physical settings
    # contract.
    profile_threads: int,
    run_backend: RunBackend | None,
    reader_batch_rows: int | None,
    reader_readahead: int | None,
    output_buffer_rows: int | None,
    # Keep the threads input explicit in the selected run physical settings contract.
    threads: int | None,
) -> RunPhysicalSettings:
    # Execute the selected run physical settings workflow in explicit, reviewable steps.
    selected_threads = base.threads if threads is None else threads
    if selected_threads != profile_threads:
        # Handle the selected run physical settings selected_threads != profile_threads
        # branch as a distinct logical block.
        raise CliUsageError(
            "RUN_THREAD_LIMIT_MISMATCH",
            "Run threads must match the selected host profile.",
        )
    return RunPhysicalSettings(
        # Pass backend explicitly so RunPhysicalSettings receives a reviewable backend and
        # reader batch rows input in selected run physical settings.
        backend=base.backend if run_backend is None else run_backend,
        reader_batch_rows=(
            base.reader_batch_rows if reader_batch_rows is None else reader_batch_rows
        ),
        reader_readahead=(base.reader_readahead if reader_readahead is None else reader_readahead),
        # Pass output buffer rows explicitly so RunPhysicalSettings receives a reviewable
        # backend and reader batch rows input in selected run physical settings.
        output_buffer_rows=(
            base.output_buffer_rows if output_buffer_rows is None else output_buffer_rows
        ),
        threads=selected_threads,
    )


# Bind known errors once as an explicit module-level contract.
_KNOWN_ERRORS = (
    ApplicationError,
    ArtifactQueryError,
    BackupError,
    CliUsageError,
    # Keep the oserror component named inside the known errors contract.
    OSError,
    RetentionError,
    RunContractNotFoundError,
    RunResultQueryError,
    TypeError,
    # Keep the validation error component named inside the known errors contract.
    ValidationError,
    ValueError,
)


def _bounded_read(path: Path, maximum: int = 2 * 1024 * 1024) -> bytes:
    # Execute the bounded read workflow in explicit, reviewable steps.
    with path.open("rb") as stream:
        payload = stream.read(maximum + 1)
    if not payload:
        raise ValueError("input file is empty")
    if len(payload) > maximum:
        # Fail the bounded read path with ValueError for input file exceeds the configured
        # command limit when maximum and payload is true; do not continue ambiguously.
        raise ValueError("input file exceeds the configured command limit")
    return payload


def _execute_ml_command(
    backend: CliBackend,
    command: MlResolvedJob,
    # Close the execute ml command signature after its explicit inputs.
    *,
    enqueue: bool,
    idempotency_key: str | None,
) -> None:
    # Execute the execute ml command workflow in explicit, reviewable steps.
    if enqueue:
        # Handle the execute ml command enqueue branch as a distinct logical block.
        if idempotency_key is None:
            # Handle the execute ml command idempotency_key is None branch as a distinct
            # logical block.
            raise CliUsageError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Queued ML jobs require an explicit idempotency key.",
            )
        record = backend.submit_job(
            # Keep the submit job request and job type SubmitJobRequest step visible while
            # building record.
            SubmitJobRequest(
                spec_version=1,
                job_type=command.JOB_TYPE,
                payload_json=command.canonical_bytes(),
                idempotency_key=idempotency_key,
                # Pass input artifact ids explicitly so SubmitJobRequest receives a
                # reviewable job type and canonical bytes input in execute ml command.
                input_artifact_ids=command.input_artifact_ids,
            )
        )
        typer.echo(_job_response(record).model_dump_json(indent=2))
        return
    # Guard this path with idempotency_key is not None before applying effects.
    if idempotency_key is not None:
        # Handle the execute ml command idempotency_key is not None branch as a distinct
        # logical block.
        raise CliUsageError(
            "IDEMPOTENCY_KEY_WITHOUT_ENQUEUE",
            "An idempotency key is only accepted together with --enqueue.",
        )
    artifact = backend.execute_ml_job(command)
    # Invoke echo for artifact id and artifact kind as a visible execute ml command step.
    typer.echo(
        json.dumps(
            {
                "artifact_id": artifact.artifact_id.hex,
                "artifact_kind": artifact.kind.value,
                # Keep build key named so the artifact id and artifact kind payload passed
                # to dumps remains self-describing within execute ml command.
                "build_key": artifact.build_key.hex,
                "manifest_digest": artifact.manifest_digest.hex,
            },
            indent=2,
            sort_keys=True,
            # Complete dumps only after its artifact id and artifact kind inputs are visible
            # in execute ml command.
        )
    )


def _job_response(value: JobRecord | JobStatusView) -> JobResponse:
    # Execute the job response workflow in explicit, reviewable steps.
    if isinstance(value, JobRecord):
        return JobResponse.from_domain(value)
    return JobResponse.from_view(value)


def _artifact_document(value: CommittedArtifact) -> dict[str, object]:
    # Execute the artifact document workflow in explicit, reviewable steps.
    return {
        "artifact_id": value.artifact_id.hex,
        "build_key": value.build_key.hex,
        "input_artifact_ids": [item.hex for item in value.input_artifact_ids],
        "kind": value.kind.value,
        # Include manifest digest in the completed artifact document result.
        "manifest_digest": value.manifest_digest.hex,
    }


def _run_summary_document(value: RunSummaryView) -> dict[str, object]:
    # Execute the run summary document workflow in explicit, reviewable steps.
    return {
        "audit_hash": value.audit_hash.hex,
        "canonicality": value.canonicality.value,
        "canonical_result_hash": value.canonical_result_hash.hex,
        # Dates explain the same newest-first ordering used by API and Web UI.
        "completed_at": value.completed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "comparison": value.comparison.document(),
        # Include execution attempt id in the completed run summary document result.
        "execution_attempt_id": value.execution_attempt_id.hex,
        "logical_run_id": value.logical_run_id.hex,
        "physical_settings": value.physical_settings.document(),
        "run_artifact_id": value.run_artifact_id.hex,
        "started_at": value.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "warnings": list(value.warnings),
        # Return the completed run summary document result without a hidden fallback.
    }


def _sniping_summary_document(value: RunResultSummaryView) -> dict[str, object]:
    # Execute the sniping summary document workflow in explicit, reviewable steps.
    if isinstance(value, CopyRunSummaryView):
        return CopyRunSummaryResponse.from_domain(value).model_dump(mode="json")
    # The established Sniping document remains unchanged for its original summary family.
    return {
        "accepted_buy_count": value.accepted_buy_count,
        "accepted_order_count": value.accepted_order_count,
        "account_deposit_locked_atomic": str(value.account_deposit_locked_atomic),
        "account_deposit_paid_atomic": str(value.account_deposit_paid_atomic),
        # Include account deposit refunded atomic in the completed sniping summary
        # document result.
        "account_deposit_refunded_atomic": str(value.account_deposit_refunded_atomic),
        "adverse_slippage_count": value.adverse_slippage_count,
        "audit_hash": value.audit_hash.hex,
        "buy_slippage_failure_count": value.buy_slippage_failure_count,
        "canonical_result_hash": value.canonical_result_hash.hex,
        # Include cashback receivable atomic in the completed sniping summary document
        # result.
        "cashback_receivable_atomic": str(value.cashback_receivable_atomic),
        "closed_position_count": value.closed_position_count,
        "cooldown_skipped_count": value.cooldown_skipped_count,
        "creator_fee_paid_atomic": str(value.creator_fee_paid_atomic),
        "delivered_event_count": value.delivered_event_count,
        # Include economic pnl atomic in the completed sniping summary document result.
        "economic_pnl_atomic": (
            None if value.economic_pnl_atomic is None else str(value.economic_pnl_atomic)
        ),
        "execution_mode": value.execution_mode.value,
        "execution_attempt_id": value.execution_attempt_id.hex,
        "failed_buy_count": value.failed_buy_count,
        # Include failed order count in the completed sniping summary document result.
        "failed_order_count": value.failed_order_count,
        "failed_sell_count": value.failed_sell_count,
        "favorable_slippage_count": value.favorable_slippage_count,
        "fill_count": value.fill_count,
        "fill_hash": value.fill_hash.hex,
        # Include filled order count in the completed sniping summary document result.
        "filled_order_count": value.filled_order_count,
        "filled_sell_count": value.filled_sell_count,
        "final_balances_count": value.final_balances_count,
        "final_balances_digest": value.final_balances_digest.hex,
        "historical_event_count": value.historical_event_count,
        "historical_group_count": value.historical_group_count,
        "gross_sell_settlement_atomic": (
            None
            if value.gross_sell_settlement_atomic is None
            else str(value.gross_sell_settlement_atomic)
        ),
        # Include ledger hash in the completed sniping summary document result.
        "ledger_hash": value.ledger_hash.hex,
        "ledger_transaction_count": value.ledger_transaction_count,
        "logical_run_id": value.logical_run_id.hex,
        "network_base_fee_paid_atomic": str(value.network_base_fee_paid_atomic),
        "network_id": value.network_id.value,
        # Include network priority fee paid atomic in the completed sniping summary
        # document result.
        "network_priority_fee_paid_atomic": str(value.network_priority_fee_paid_atomic),
        "open_position_count": value.open_position_count,
        "position_schema_id": value.position_schema_id.value,
        "protocol_fee_paid_atomic": str(value.protocol_fee_paid_atomic),
        "real_liquidity_sufficient_filled_sell_count": (
            value.real_liquidity_sufficient_filled_sell_count
        ),
        "realized_cash_pnl_atomic": str(value.realized_cash_pnl_atomic),
        # Include rejected order count in the completed sniping summary document result.
        "rejected_order_count": value.rejected_order_count,
        "roundtrip_count": value.roundtrip_count,
        "roundtrip_digest": value.roundtrip_digest.hex,
        "run_artifact_id": value.run_artifact_id.hex,
        "sell_slippage_failure_count": value.sell_slippage_failure_count,
        "settlement_policy_id": value.settlement_policy_id,
        "summary_schema_id": value.summary_schema_id,
        "synthetic_funded_sell_atomic": (
            None
            if value.synthetic_funded_sell_atomic is None
            else str(value.synthetic_funded_sell_atomic)
        ),
        "synthetic_liquidity_used_sell_count": value.synthetic_liquidity_used_sell_count,
        # Include target count in the completed sniping summary document result.
        "target_count": value.target_count,
        "unvalued_open_position_count": value.unvalued_open_position_count,
        "valuation_status": value.valuation_status.value,
        "valued_economic_pnl_subtotal_atomic": str(value.valued_economic_pnl_subtotal_atomic),
        "venue_funded_sell_atomic": (
            None if value.venue_funded_sell_atomic is None else str(value.venue_funded_sell_atomic)
        ),
    }


# Define roundtrip cursor as one focused operation with an explicit boundary.
def _roundtrip_cursor(value: str | None) -> RoundTripCursor | None:
    # Execute the roundtrip cursor workflow in explicit, reviewable steps.
    if value is None:
        return None
    boundary, separator, digest = value.partition(":")
    if (
        not separator
        # Keep boundary visible while evaluating the separator, isascii and isdecimal
        # guard.
        or not boundary.isascii()
        or not boundary.isdecimal()
        or (len(boundary) > 1 and boundary.startswith("0"))
    ):
        # Handle the roundtrip cursor separator, isascii and isdecimal condition as a
        # distinct block.
        raise CliUsageError(
            "INVALID_ROUNDTRIP_CURSOR",
            "Round-trip cursor must be BOUNDARY_ORDINAL:ROUNDTRIP_ID.",
        )
    try:
        # Return the completed roundtrip cursor result without a hidden fallback.
        return RoundTripCursor(int(boundary), ContentDigest(digest))
    except (TypeError, ValueError) as error:
        # Translate the (TypeError, ValueError) failure through the roundtrip cursor
        # boundary.
        raise CliUsageError(
            "INVALID_ROUNDTRIP_CURSOR",
            "Round-trip cursor must be BOUNDARY_ORDINAL:ROUNDTRIP_ID.",
        ) from error


def _roundtrip_page_document(value: RoundTripPage) -> dict[str, object]:
    # Execute the roundtrip page document workflow in explicit, reviewable steps.
    return {
        "items": [_roundtrip_document(item) for item in value.items],
        "next_cursor": (
            None
            if value.next_cursor is None
            # Route all remaining cases through the explicit alternative branch.
            else (
                f"{value.next_cursor.target_boundary_ordinal}:{value.next_cursor.roundtrip_id.hex}"
            )
        ),
    }


# Define roundtrip document as one focused operation with an explicit boundary.
def _roundtrip_document(value: RoundTripRecord | CopyPositionRecord) -> dict[str, object]:
    # Execute the roundtrip document workflow in explicit, reviewable steps.
    if isinstance(value, CopyPositionRecord):
        return CopyPositionResponse.from_domain(value).model_dump(mode="json")
    # Legacy Sniping row fields are emitted only for an actual Sniping record.
    return {
        "acquired_token_amount_atomic": str(value.acquired_token_amount_atomic),
        "account_components": [
            _account_component_document(item) for item in value.account_components
        ],
        "account_profile_id": value.account_profile_id,
        # Include asset id in the completed roundtrip document result.
        "asset_id": value.asset_id.value,
        "buy": None if value.buy is None else _roundtrip_leg_document(value.buy),
        "cashback_receivable_atomic": str(value.cashback_receivable_atomic),
        "cooldown_consumed": value.cooldown_consumed,
        "cooldown_until_ns": (
            # Include value in the completed roundtrip document result.
            None if value.cooldown_until_ns is None else str(value.cooldown_until_ns)
        ),
        "creation_user_id": value.creation_user_id.value,
        "developer_id": value.developer_id.value,
        "economic_pnl_atomic": (
            # Include value in the completed roundtrip document result.
            None if value.economic_pnl_atomic is None else str(value.economic_pnl_atomic)
        ),
        "execution_mode": value.execution_mode.value,
        "mtm_liquidity": _liquidity_evidence_document(value.mtm_liquidity),
        "mtm_cash_pnl_atomic": (
            None if value.mtm_cash_pnl_atomic is None else str(value.mtm_cash_pnl_atomic)
        ),
        # Include mtm liquidation value atomic in the completed roundtrip document result.
        "mtm_liquidation_value_atomic": (
            None
            if value.mtm_liquidation_value_atomic is None
            else str(value.mtm_liquidation_value_atomic)
        ),
        # Include mtm status in the completed roundtrip document result.
        "mtm_status": value.mtm_status.value,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "quote_asset_id": value.quote_asset_id.value,
        "realized_cash_pnl_atomic": (
            # Include value in the completed roundtrip document result.
            None if value.realized_cash_pnl_atomic is None else str(value.realized_cash_pnl_atomic)
        ),
        # Include roundtrip id in the completed roundtrip document result.
        "roundtrip_id": value.roundtrip_id.hex,
        "result_schema_id": value.source_schema_id,
        "sell": None if value.sell is None else _roundtrip_leg_document(value.sell),
        "sell_landing_liquidity": _liquidity_evidence_document(value.sell_landing_liquidity),
        "sell_reference_liquidity": _liquidity_evidence_document(value.sell_reference_liquidity),
        "settled_synthetic_funded_atomic": (
            None
            if value.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else str(value.settled_synthetic_funded_atomic)
        ),
        "settled_venue_funded_atomic": (
            None
            if value.source_schema_id == ROUNDTRIP_RESULT_SCHEMA_V3
            else str(value.settled_venue_funded_atomic)
        ),
        "status": value.status.value,
        "target_event_id": value.target_event_id.hex,
        "target_position": _chain_position_document(value.target_position),
        # Include target time ns in the completed roundtrip document result.
        "target_time_ns": str(value.target_time_ns),
        "venue_id": value.venue_id.value,
    }


def _liquidity_evidence_document(
    value: QuoteLiquidityEvidenceRecord | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "asset_id": value.asset_id.value,
        "observed_available_output_atomic": str(value.observed_available_output_atomic),
        "policy_id": value.policy_id,
        "required_output_atomic": str(value.required_output_atomic),
        "synthetic_shortfall_atomic": str(value.synthetic_shortfall_atomic),
    }


def _account_component_document(value: AccountComponentRecord) -> dict[str, object]:
    """Render v3 account amounts without lossy JSON numbers."""

    return {
        "asset_id": value.asset_id.value,
        "attribution_id": value.attribution_id.hex,
        "attribution_kind": value.attribution_kind.value,
        "lifecycle": value.lifecycle.value,
        "locked_delta_atomic": str(value.locked_delta_atomic),
        "maximum_reserved_atomic": str(value.maximum_reserved_atomic),
        "paid_atomic": str(value.paid_atomic),
        "refunded_atomic": str(value.refunded_atomic),
        "release_policy": value.release_policy.value,
        "released_atomic": str(value.released_atomic),
        "requirement_schema_id": value.requirement_schema_id,
        "scope": value.scope.value,
    }


def _roundtrip_leg_document(value: RoundTripLegRecord) -> dict[str, object]:
    # Execute the roundtrip leg document workflow in explicit, reviewable steps.
    return {
        "amount_in_atomic": (
            None if value.amount_in_atomic is None else str(value.amount_in_atomic)
        ),
        "creator_fee_atomic": str(value.creator_fee_atomic),
        # Include decision position in the completed roundtrip leg document result.
        "decision_position": _chain_position_document(value.decision_position),
        "failure_code": value.failure_code,
        "landing_out_atomic": (
            None if value.landing_out_atomic is None else str(value.landing_out_atomic)
        ),
        # Include landing position in the completed roundtrip leg document result.
        "landing_position": (
            None
            if value.landing_position is None
            else _chain_position_document(value.landing_position)
        ),
        # Include minimum out atomic in the completed roundtrip leg document result.
        "minimum_out_atomic": str(value.minimum_out_atomic),
        "network_base_fee_atomic": str(value.network_base_fee_atomic),
        "network_priority_fee_atomic": str(value.network_priority_fee_atomic),
        "protocol_fee_atomic": str(value.protocol_fee_atomic),
        "reference_out_atomic": str(value.reference_out_atomic),
        # Include side in the completed roundtrip leg document result.
        "side": value.side.value,
        "signed_slippage_atomic": (
            None if value.signed_slippage_atomic is None else str(value.signed_slippage_atomic)
        ),
    }


# Define chain position document as one focused operation with an explicit boundary.
def _chain_position_document(value: ChainPosition) -> dict[str, object]:
    # Execute the chain position document workflow in explicit, reviewable steps.
    return {
        "block_ordinal": value.block_ordinal,
        "boundary_ordinal": str(value.boundary_ordinal),
        "event_index": value.event_index,
        "network_id": value.network_id.value,
        # Include position schema id in the completed chain position document result.
        "position_schema_id": value.position_schema_id.value,
        "transaction_index": value.transaction_index,
    }


def _pin_document(value: PinRecord) -> dict[str, object]:
    # Execute the pin document workflow in explicit, reviewable steps.
    return {
        "created_at_ns": value.created_at_ns,
        "pin_id": value.pin_id.value,
        "reason": value.reason,
        "record_digest": value.record_digest.hex,
        # Include roots in the completed pin document result.
        "roots": [item.hex for item in value.roots],
        "transitive_closure": [item.hex for item in value.transitive_closure],
    }


def _gc_plan_document(value: GarbageCollectionPlan) -> dict[str, object]:
    # Execute the gc plan document workflow in explicit, reviewable steps.
    return {
        "candidates": [
            {
                "artifact_id": item.artifact_id.hex,
                "committed_at_ns": item.committed_at_ns,
                # Include kind in the completed gc plan document result.
                "kind": item.kind.value,
                "size_bytes": item.size_bytes,
                "tree_digest": item.tree_digest.hex,
            }
            for item in value.candidates
            # Return the completed gc plan document result without a hidden fallback.
        ],
        "pinned_roots": [item.hex for item in value.pinned_roots],
        "plan_id": value.plan_id.hex,
        "planned_at_ns": value.planned_at_ns,
        "policy": {
            # Include maximum sweep bytes in the completed gc plan document result.
            "maximum_sweep_bytes": value.policy.maximum_sweep_bytes,
            "minimum_artifact_age_ns": value.policy.minimum_artifact_age_ns,
            "trash_grace_period_ns": value.policy.trash_grace_period_ns,
        },
        "reclaimable_bytes": value.reclaimable_bytes,
        # Include retained roots in the completed gc plan document result.
        "retained_roots": [item.hex for item in value.retained_roots],
    }


def _gc_batch_document(value: GarbageCollectionBatch) -> dict[str, object]:
    # Execute the gc batch document workflow in explicit, reviewable steps.
    return {
        "artifact_ids": [item.hex for item in value.artifact_ids],
        "batch_id": value.batch_id.hex,
        "moved_at_ns": value.moved_at_ns,
        "plan_id": value.plan_id.hex,
        # Include purge not before ns in the completed gc batch document result.
        "purge_not_before_ns": value.purge_not_before_ns,
    }


def _backup_document(value: BackupGeneration) -> dict[str, object]:
    # Execute the backup document workflow in explicit, reviewable steps.
    return {
        "artifact_ids": [item.hex for item in value.artifact_ids],
        "backup_cut_id": value.backup_cut_id.hex,
        "catalog_digest": value.catalog_digest.hex,
        "created_at_ns": value.created_at_ns,
        # Include total bytes in the completed backup document result.
        "total_bytes": value.total_bytes,
    }


def _restore_document(
    value: RestoreReport,
    *,
    # Keep the destination name input explicit in the restore document contract.
    destination_name: str,
) -> dict[str, object]:
    # Execute the restore document workflow in explicit, reviewable steps.
    return {
        "backup_cut_id": value.backup_cut_id.hex,
        "catalog_rebuild": {
            "conflicting_build_keys": value.catalog_rebuild.conflicting_build_keys,
            "indexed_artifacts": value.catalog_rebuild.indexed_artifacts,
            # Include quarantined artifacts in the completed restore document result.
            "quarantined_artifacts": value.catalog_rebuild.quarantined_artifacts,
        },
        "destination_name": destination_name,
        "reconciliation_complete": value.reconciliation_complete,
        "restored_artifacts": value.restored_artifacts,
        # Include restored job roots in the completed restore document result.
        "restored_job_roots": [item.hex for item in value.restored_job_roots],
    }


def _fail(error: BaseException) -> NoReturn:
    # Execute the fail workflow in explicit, reviewable steps.
    if isinstance(error, ApplicationError):
        # Handle the fail isinstance(error, ApplicationError) branch as a distinct logical
        # block.
        code = error.code.value
        message = error.safe_message
    # Handle the fail complement of isinstance(error, ApplicationError) explicitly.
    elif isinstance(error, CliUsageError):
        # Handle the fail isinstance(error, CliUsageError) branch as a distinct logical
        # block.
        code = error.code
        message = error.safe_message
    # Handle the fail complement of isinstance(error, CliUsageError) explicitly.
    elif isinstance(error, RunIndexQueryError):
        # Distinguish repairable projection state from a missing exact artifact.
        code = error.code
        message = "The verified Run ordering index is unavailable and must be rebuilt."
    elif isinstance(error, ArtifactQueryError):
        # Handle the fail isinstance(error, ArtifactQueryError) branch as a distinct
        # logical block.
        code = "ARTIFACT_VERIFICATION_FAILED"
        message = "The requested verified artifact metadata is unavailable."
    # Handle the fail complement of isinstance(error, ArtifactQueryError) explicitly.
    elif isinstance(error, RetentionError):
        # Handle the fail isinstance(error, RetentionError) branch as a distinct logical
        # block.
        code = "RETENTION_OPERATION_REJECTED"
        message = "The retention operation was rejected by the configured safety policy."
    # Handle the fail complement of isinstance(error, RetentionError) explicitly.
    elif isinstance(error, BackupError):
        # Handle the fail isinstance(error, BackupError) branch as a distinct logical
        # block.
        code = "BACKUP_OPERATION_REJECTED"
        message = "The backup or restore verification operation failed closed."
    # Handle the fail complement of isinstance(error, BackupError) explicitly.
    elif isinstance(error, RunResultQueryError):
        # Handle the fail isinstance(error, RunResultQueryError) branch as a distinct
        # logical block.
        code = error.code
        message = "Verified Pump.fun Run results are unavailable."
    # Handle the fail complement of isinstance(error, RunResultQueryError) explicitly.
    elif isinstance(error, RunContractNotFoundError):
        # Handle the fail error run contract not found error type condition as a distinct
        # block.
        code = "RUN_CONTRACT_NOT_FOUND"
        message = "The requested typed run contract is unavailable."
    # Handle the fail complement of error run contract not found error type explicitly.
    elif isinstance(error, OSError):
        # Handle the fail isinstance(error, OSError) branch as a distinct logical block.
        code = "LOCAL_INPUT_ERROR"
        message = "A local input or configuration file could not be read."
    else:
        # Handle the fail complement of isinstance(error, OSError) explicitly.
        code = "INVALID_LOCAL_COMMAND"
        message = "Input does not match the versioned command schema."
    typer.echo(json.dumps({"code": code, "message": message}, ensure_ascii=False), err=True)
    raise typer.Exit(code=2)


__all__ = [
    # Keep the cli backend component named inside the all contract.
    "CliBackend",
    "CliBackendFactory",
    "CliRecoveryBackend",
    "CliRecoveryBackendFactory",
    "CliUsageError",
    # Keep the create cli component named inside the all contract.
    "create_cli",
]
