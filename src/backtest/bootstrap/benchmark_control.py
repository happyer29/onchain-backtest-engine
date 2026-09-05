"""Private filesystem authority for real control-plane benchmark routes."""

from __future__ import annotations

import json
import os
import tempfile
import time

# Import abc at the visible module dependency boundary.
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from multiprocessing.util import Finalize

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from socket import AF_INET, SOCK_STREAM
from socket import socket as Socket
from threading import Event, Thread
from types import TracebackType

# Import typing at the visible module dependency boundary.
from typing import TYPE_CHECKING

from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    LocalCommittedArtifactScanner,
    # Include local completion receipt store so the localfs dependency remains explicit.
    LocalCompletionReceiptStore,
    MaterializedArtifactClosure,
    materialize_verified_artifact_closure,
)
from backtest.adapters.artifacts.localfs.safe_io import (
    # Include ensure real directory so the safe io dependency remains explicit.
    ensure_real_directory,
    file_records,
    fsync_directory,
    require_real_directory,
    safe_relative_path,
    # Include write durable exclusive so the safe io dependency remains explicit.
    write_durable_exclusive,
)
from backtest.adapters.control import (
    ControlApiUnavailableError,
    LocalControlApiClient,
    # Close the control import after its required symbols are visible.
)
from backtest.adapters.results import LocalJobResultReader
from backtest.application.attempt_identity import queued_execution_attempt_nonce
from backtest.application.benchmarks import (
    BenchmarkLaunchRoute,
    # Include control plane benchmark invocation so the benchmarks dependency remains
    # explicit.
    ControlPlaneBenchmarkInvocation,
)
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.job_commands import ResolvedBacktestJob, run_input_artifact_ids
from backtest.application.job_views import JobStatusView, job_input_artifact_ids_digest

# Import models at the visible module dependency boundary.
from backtest.application.models import AttemptState, JobType
from backtest.application.run_results import (
    RunComparisonProjection,
    RunPhysicalSettings,
    SuccessfulRunManifest,
    # Close the run results import after its required symbols are visible.
)
from backtest.application.use_cases.complete_job_attempt import CompleteJobAttempt
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.bootstrap.config import (
    BackupSettings,
    # Include path settings so the config dependency remains explicit.
    PathSettings,
    RetentionSettings,
    Settings,
    SourceSettings,
    load_settings,
    # Close the config import after its required symbols are visible.
)
from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest
from backtest.interfaces.api import create_app
from backtest.runtime.control_plane_identity import control_plane_identity
from backtest.runtime.controller_lock import ControllerLock

# Guard this path with TYPE_CHECKING before applying effects.
if TYPE_CHECKING:
    # Handle the module TYPE_CHECKING branch as a distinct logical block.
    from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor
    from backtest.bootstrap.container import RuntimeContainer
    from backtest.bootstrap.direct_execution import DirectJobExecutor

_GIB = 1024**3
_CONTROL_HTTP_TIMEOUT_SECONDS = 5.0
# Bind control maximum wait seconds once as an explicit module-level contract.
_CONTROL_MAXIMUM_WAIT_SECONDS = 49 * 60 * 60


@dataclass(slots=True)
class IsolatedBenchmarkWorkspace:
    """Owned private controller root; cleanup refuses unsafe filesystem state."""

    workspace_root: Path
    config_path: Path
    settings: Settings
    materialized: MaterializedArtifactClosure
    _closed: bool = False

    # Define isolated benchmark workspace close as one focused operation with an explicit
    # boundary.
    def close(self) -> None:
        # Execute the isolated benchmark workspace close workflow in explicit, reviewable
        # steps.
        if self._closed:
            return
        _remove_private_workspace(self.workspace_root)
        fsync_directory(self.workspace_root.parent)
        self._closed = True

    # Define isolated benchmark workspace enter as one focused operation with an explicit
    # boundary.
    def __enter__(self) -> IsolatedBenchmarkWorkspace:
        # Execute the isolated benchmark workspace enter workflow in explicit, reviewable
        # steps.
        if self._closed:
            raise RuntimeError("isolated benchmark workspace is closed")
        return self

    def __exit__(
        self,
        # Keep the exc type input explicit in the exit contract.
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


# Define create isolated benchmark workspace as one focused operation with an explicit
# boundary.
def create_isolated_benchmark_workspace(
    source_settings: Settings,
    *,
    root_artifact_id: ArtifactId,
    control_port: int,
    # Keep the isolated benchmark workspace input explicit in the create isolated benchmark
    # workspace contract.
) -> IsolatedBenchmarkWorkspace:
    """Materialize an exact seed closure and a secret-free child config.

    The caller starts either the Direct supervisor or the real loopback server
    after this function returns, so setup work is outside timed execution.
    """

    source_root = source_settings.paths.data_root.resolve()
    require_real_directory(source_root, label="benchmark source data root")
    temporary_root = source_root / "tmp"
    ensure_real_directory(temporary_root, parent=source_root)
    temporary_parent = temporary_root / "benchmark-control"
    # Invoke ensure_real_directory for temporary parent and temporary root as a visible
    # create isolated benchmark workspace step.
    ensure_real_directory(temporary_parent, parent=temporary_root)
    workspace_root = Path(tempfile.mkdtemp(prefix="authority-", dir=temporary_parent)).resolve()
    try:
        # Perform the protected create isolated benchmark workspace operation before
        # explicit failure handling.
        data_root = workspace_root / "data"
        materialized = materialize_verified_artifact_closure(
            LocalArtifactRepository(source_root),
            roots=(root_artifact_id,),
            destination_root=data_root,
            # Pass maximum copy bytes explicitly so materialize_verified_artifact_closure
            # receives a reviewable max local gb and planning input in create isolated
            # benchmark workspace.
            maximum_copy_bytes=source_settings.planning.max_local_gb * _GIB,
            minimum_free_after_bytes=source_settings.resources.disk_low_watermark_gb * _GIB,
        )
        isolated = replace(
            source_settings,
            # Keep the path settings and data root PathSettings step visible while
            # building isolated.
            paths=PathSettings(data_root=data_root),
            resources=replace(source_settings.resources, max_parallel_runs=1),
            retention=RetentionSettings(),
            backup=BackupSettings(),
            control=replace(
                # Pass source settings explicitly so replace receives a reviewable 1 and
                # control input in create isolated benchmark workspace.
                source_settings.control,
                host="127.0.0.1",
                port=control_port,
                secure_cookie=False,
            ),
            # Keep the source settings SourceSettings step visible while building
            # isolated.
            source=SourceSettings(),
        )
        config_path = workspace_root / "config.toml"
        write_durable_exclusive(config_path, _secret_free_config_bytes(isolated))
        fsync_directory(workspace_root)
        # Assemble loaded once so the create isolated benchmark workspace workflow shares
        # one value.
        loaded = load_settings(config_path)
        if loaded != isolated:
            raise RuntimeError("isolated benchmark config failed exact round-trip validation")
        return IsolatedBenchmarkWorkspace(
            workspace_root=workspace_root,
            # Pass config path explicitly so IsolatedBenchmarkWorkspace receives a
            # reviewable workspace root and config path input in create isolated benchmark
            # workspace.
            config_path=config_path,
            settings=loaded,
            materialized=materialized,
        )
    except BaseException:
        # Translate the BaseException failure through the create isolated benchmark
        # workspace boundary.
        _remove_private_workspace(workspace_root)
        fsync_directory(temporary_parent)
        raise


class IsolatedDirectControlBenchmarkExecutor:
    """Real durable Direct route on a private controller authority."""

    def __init__(self, source_settings: Settings, seed_run_artifact_id: ArtifactId) -> None:
        # Execute the isolated direct control benchmark executor init workflow in
        # explicit, reviewable steps.
        from backtest.bootstrap.container import build_runtime_container
        from backtest.bootstrap.direct_execution import DirectJobExecutor
        from backtest.bootstrap.supervisor import build_single_host_supervisor

        workspace = create_isolated_benchmark_workspace(
            source_settings,
            # Pass root artifact id explicitly so create_isolated_benchmark_workspace
            # receives a reviewable port and control input in isolated direct control
            # benchmark executor init.
            root_artifact_id=seed_run_artifact_id,
            control_port=source_settings.control.port,
        )
        authority: ControllerLock | None = None
        try:
            # Perform the protected isolated direct control benchmark executor init
            # operation before explicit failure handling.
            container = build_runtime_container(
                workspace.settings,
                profile="isolated-benchmark-direct",
            )
            container.catalog.rebuild_index(
                # Pass local committed artifact scanner explicitly to rebuild_index for
                # scan and artifacts.
                LocalCommittedArtifactScanner(container.artifacts).scan()
            )
            reader = LocalJobResultReader(container.artifacts)
            seed_manifest = reader.successful_run_manifest(seed_run_artifact_id)
            authority = ControllerLock(
                # Pass container explicitly into acquire within isolated direct control
                # benchmark executor init.
                container.artifacts.data_root / "locks" / "controller.lock",
                instance_id=f"benchmark-{workspace.materialized.closure_digest.hex}",
            ).acquire()
            supervisor = build_single_host_supervisor(
                container,
                # Pass authority explicitly so build_single_host_supervisor receives a
                # reviewable config path and cwd input in isolated direct control
                # benchmark executor init.
                authority=authority,
                config_path=workspace.config_path,
                capabilities_file=None,
                working_directory=Path.cwd(),
            )
            # Assemble receipts once so the isolated direct control benchmark executor
            # init workflow shares one value.
            receipts = LocalCompletionReceiptStore(DataRootLayout(container.artifacts.data_root))
            verifier = CompleteJobAttempt(
                container.jobs,
                container.catalog,
                receipts,
                # Pass container explicitly so CompleteJobAttempt receives a reviewable
                # jobs and catalog input in isolated direct control benchmark executor
                # init.
                container.artifacts,
            )
            direct = DirectJobExecutor(
                submitter=container.control.submit_job,
                queue=container.jobs,
                # Pass supervisor explicitly so DirectJobExecutor receives a reviewable
                # submit job and control input in isolated direct control benchmark
                # executor init.
                supervisor=supervisor,
                verifier=verifier,
                artifacts=container.artifacts,
                poll_interval_seconds=(workspace.settings.control.progress_interval_ms / 1_000),
            )
        # Translate base exception through the isolated direct control benchmark executor
        # init boundary without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the isolated direct control
            # benchmark executor init boundary.
            if authority is not None:
                authority.release()
            workspace.close()
            raise

        self._seed_run_artifact_id = seed_run_artifact_id
        # Assemble self workspace once so the isolated direct control benchmark executor
        # init workflow shares one value.
        self._workspace = workspace
        self._container: RuntimeContainer = container
        self._reader = reader
        self._seed_manifest: SuccessfulRunManifest = seed_manifest
        self._authority = authority
        # Assemble self supervisor once so the isolated direct control benchmark executor
        # init workflow shares one value.
        self._supervisor: SingleHostSupervisor = supervisor
        self._direct: DirectJobExecutor = direct
        self._finalizer = Finalize(
            None,
            _finalize_direct_authority,
            # Pass args explicitly so Finalize receives a reviewable finalize direct
            # authority and supervisor input in isolated direct control benchmark executor
            # init.
            args=(supervisor, authority, workspace),
            exitpriority=10,
        )

    def execute(
        self,
        # Keep the run artifact id input explicit in the execute contract.
        run_artifact_id: ArtifactId,
        route: BenchmarkLaunchRoute,
        physical_settings: RunPhysicalSettings,
        invocation: ControlPlaneBenchmarkInvocation,
    ) -> RunComparisonProjection:
        # Execute the isolated direct control benchmark executor execute workflow in
        # explicit, reviewable steps.
        if route is not BenchmarkLaunchRoute.DIRECT:
            raise ValueError("isolated Direct executor only accepts the DIRECT route")
        if run_artifact_id != self._seed_run_artifact_id:
            raise ValueError("control benchmark invocation changed its exact Run seed")
        command = ResolvedBacktestJob(
            # Pass resolved spec explicitly so ResolvedBacktestJob receives a reviewable
            # resolved spec and seed manifest input in isolated direct control benchmark
            # executor execute.
            resolved_spec=self._seed_manifest.resolved_spec,
            attempt_nonce=invocation.invocation_id,
            physical_settings=physical_settings,
        )
        completion = self._direct.execute(
            # Keep the submit job request and run backtest SubmitJobRequest step visible
            # while building completion.
            SubmitJobRequest(
                spec_version=1,
                job_type=JobType.RUN_BACKTEST,
                payload_json=command.canonical_bytes(),
                idempotency_key=f"benchmark-direct-{invocation.invocation_id.hex}",
                # Complete SubmitJobRequest only after its benchmark-direct- and run backtest
                # inputs are visible in isolated direct control benchmark executor execute.
            )
        )
        result = self._reader.run_result(
            command,
            completion.result_artifact,
            # Pass completion explicitly so run_result receives a reviewable result
            # artifact and attempt input in isolated direct control benchmark executor
            # execute.
            completion.attempt,
        )
        if result.artifact != completion.result_artifact:
            raise RuntimeError("Direct benchmark typed result differs from durable completion")
        manifest = self._reader.successful_run_manifest(result.artifact.artifact_id)
        # Return the completed isolated direct control benchmark executor execute result
        # without a hidden fallback.
        return manifest.comparison

    def close(self) -> None:
        self._finalizer()


def _finalize_direct_authority(
    supervisor: SingleHostSupervisor,
    # Keep the authority input explicit in the finalize direct authority contract.
    authority: ControllerLock,
    workspace: IsolatedBenchmarkWorkspace,
) -> None:
    # Execute the finalize direct authority workflow in explicit, reviewable steps.
    try:
        supervisor.shutdown()
    finally:
        # Handle the cleanup path after the protected finalize direct authority operation.
        try:
            authority.release()
        finally:
            workspace.close()


class IsolatedHttpControlBenchmarkExecutor:
    """Real loopback HTTP submit/poll/read-back on a private controller."""

    def __init__(self, source_settings: Settings, seed_run_artifact_id: ArtifactId) -> None:
        # Execute the isolated http control benchmark executor init workflow in explicit,
        # reviewable steps.
        from backtest.bootstrap.container import build_runtime_container
        from backtest.bootstrap.serve import run_control_server
        from backtest.bootstrap.supervisor import build_single_host_supervisor

        bound_socket = _bound_loopback_socket()
        port = int(bound_socket.getsockname()[1])
        # Assemble workspace once so the isolated http control benchmark executor init
        # workflow shares one value.
        workspace: IsolatedBenchmarkWorkspace | None = None
        authority: ControllerLock | None = None
        server_thread: Thread | None = None
        shutdown = Event()
        server_errors: list[BaseException] = []
        # Keep expected failures inside the isolated http control benchmark executor init
        # error boundary.
        try:
            # Perform the protected isolated http control benchmark executor init
            # operation before explicit failure handling.
            workspace = create_isolated_benchmark_workspace(
                source_settings,
                root_artifact_id=seed_run_artifact_id,
                control_port=port,
            )
            # Assemble container once so the isolated http control benchmark executor init
            # workflow shares one value.
            container = build_runtime_container(
                workspace.settings,
                profile="isolated-benchmark-control",
            )
            container.catalog.rebuild_index(
                # Pass local committed artifact scanner explicitly to rebuild_index for
                # scan and artifacts.
                LocalCommittedArtifactScanner(container.artifacts).scan()
            )
            reader = LocalJobResultReader(container.artifacts)
            seed_manifest = reader.successful_run_manifest(seed_run_artifact_id)
            authority = ControllerLock(
                # Pass container explicitly into acquire within isolated http control
                # benchmark executor init.
                container.artifacts.data_root / "locks" / "controller.lock",
                instance_id=f"benchmark-{workspace.materialized.closure_digest.hex}",
            ).acquire()
            expected_control_plane_id = control_plane_identity(
                container.artifacts.data_root,
                # Pass authority explicitly so control_plane_identity receives a
                # reviewable data root and artifacts input in isolated http control
                # benchmark executor init.
                authority.instance_id,
            )
            supervisor = build_single_host_supervisor(
                container,
                authority=authority,
                # Pass config path explicitly so build_single_host_supervisor receives a
                # reviewable config path and cwd input in isolated http control benchmark
                # executor init.
                config_path=workspace.config_path,
                capabilities_file=None,
                working_directory=Path.cwd(),
            )
            app = create_app(
                # Pass container explicitly so create_app receives a reviewable control
                # and max request mb input in isolated http control benchmark executor
                # init.
                container.control,
                control_plane_id=expected_control_plane_id,
                max_request_bytes=workspace.settings.control.max_request_mb * 1024 * 1024,
                secure_cookie=False,
            )
            # Assemble server thread once so the isolated http control benchmark executor
            # init workflow shares one value.
            server_thread = Thread(
                target=_run_isolated_control_server,
                kwargs={
                    "run_server": run_control_server,
                    "app": app,
                    # Keep supervisor named so the run server and app payload passed to
                    # Thread remains self-describing within isolated http control
                    # benchmark executor init.
                    "supervisor": supervisor,
                    "port": port,
                    "cycle_interval_seconds": (
                        workspace.settings.control.progress_interval_ms / 1_000
                    ),
                    # Keep bound socket named so the run server and app payload passed to
                    # Thread remains self-describing within isolated http control
                    # benchmark executor init.
                    "bound_socket": bound_socket,
                    "shutdown": shutdown,
                    "errors": server_errors,
                },
                name="backtest-benchmark-control-server",
                # This server is owned exclusively by a spawn-pool worker.
                # CPython joins non-daemon threads before multiprocessing
                # Finalize callbacks, which would deadlock before our callback
                # can signal this thread.  The explicit close/Finalize path
                # remains authoritative for normal teardown.
                daemon=False,
            )
            server_thread.start()
            client = LocalControlApiClient(
                "127.0.0.1",
                # Pass port explicitly so LocalControlApiClient receives a reviewable 1
                # and max request mb input in isolated http control benchmark executor
                # init.
                port,
                timeout_seconds=_CONTROL_HTTP_TIMEOUT_SECONDS,
                maximum_response_bytes=workspace.settings.control.max_request_mb * 1024 * 1024,
            )
            _await_control_server(
                # Pass client explicitly so _await_control_server receives a reviewable
                # progress interval ms and control input in isolated http control
                # benchmark executor init.
                client,
                expected_control_plane_id=expected_control_plane_id,
                thread=server_thread,
                errors=server_errors,
                poll_interval_seconds=(workspace.settings.control.progress_interval_ms / 1_000),
                # Complete _await_control_server only after its progress interval ms and
                # control inputs are visible in isolated http control benchmark executor init.
            )
        except BaseException:
            # Translate the BaseException failure through the isolated http control
            # benchmark executor init boundary.
            if server_thread is not None and workspace is not None and authority is not None:
                # Handle the isolated http control benchmark executor init server thread,
                # workspace and authority condition as a distinct block.
                _finalize_http_authority(
                    server_thread,
                    shutdown,
                    server_errors,
                    bound_socket,
                    # Pass authority explicitly so _finalize_http_authority receives a
                    # reviewable server thread and shutdown input in isolated http control
                    # benchmark executor init.
                    authority,
                    workspace,
                )
            else:
                # Handle the isolated http control benchmark executor init complement of
                # server thread, workspace and authority explicitly.
                bound_socket.close()
                if authority is not None:
                    authority.release()
                if workspace is not None:
                    workspace.close()
            # Fail the isolated http control benchmark executor init path with typed
            # failure; do not continue ambiguously.
            raise

        self._seed_run_artifact_id = seed_run_artifact_id
        self._workspace = workspace
        self._container: RuntimeContainer = container
        self._reader = reader
        # Assemble self seed manifest once so the isolated http control benchmark executor
        # init workflow shares one value.
        self._seed_manifest: SuccessfulRunManifest = seed_manifest
        self._authority = authority
        self._client = client
        self._server_thread = server_thread
        self._server_errors = server_errors
        # Assemble self shutdown once so the isolated http control benchmark executor init
        # workflow shares one value.
        self._shutdown = shutdown
        self._bound_socket = bound_socket
        self._poll_interval_seconds = workspace.settings.control.progress_interval_ms / 1_000
        self._finalizer = Finalize(
            None,
            # Pass finalize http authority explicitly so Finalize receives a reviewable
            # finalize http authority and server thread input in isolated http control
            # benchmark executor init.
            _finalize_http_authority,
            args=(
                server_thread,
                shutdown,
                server_errors,
                # Pass bound socket explicitly so Finalize receives a reviewable finalize
                # http authority and server thread input in isolated http control
                # benchmark executor init.
                bound_socket,
                authority,
                workspace,
            ),
            exitpriority=10,
            # Complete Finalize only after its finalize http authority and server thread
            # inputs are visible in isolated http control benchmark executor init.
        )

    def execute(
        self,
        run_artifact_id: ArtifactId,
        route: BenchmarkLaunchRoute,
        # Keep the physical settings input explicit in the execute contract.
        physical_settings: RunPhysicalSettings,
        invocation: ControlPlaneBenchmarkInvocation,
    ) -> RunComparisonProjection:
        # Execute the isolated http control benchmark executor execute workflow in
        # explicit, reviewable steps.
        if route is not BenchmarkLaunchRoute.CONTROL:
            raise ValueError("isolated HTTP executor only accepts the CONTROL route")
        if run_artifact_id != self._seed_run_artifact_id:
            raise ValueError("control benchmark invocation changed its exact Run seed")
        _require_live_server(self._server_thread, self._server_errors)
        # Assemble command once so the isolated http control benchmark executor execute
        # workflow shares one value.
        command = ResolvedBacktestJob(
            resolved_spec=self._seed_manifest.resolved_spec,
            attempt_nonce=invocation.invocation_id,
            physical_settings=physical_settings,
        )
        # Assemble inputs once so the isolated http control benchmark executor execute
        # workflow shares one value.
        inputs = run_input_artifact_ids(command.resolved_spec)
        request = SubmitJobRequest(
            spec_version=1,
            job_type=JobType.RUN_BACKTEST,
            payload_json=command.canonical_bytes(),
            # Pass idempotency key explicitly so SubmitJobRequest receives a reviewable
            # benchmark-control- and run backtest input in isolated http control benchmark
            # executor execute.
            idempotency_key=f"benchmark-control-{invocation.invocation_id.hex}",
            input_artifact_ids=inputs,
        )
        submitted = self._client.submit_job(request)
        _require_submitted_job(submitted, request, inputs)
        # Assemble terminal once so the isolated http control benchmark executor execute
        # workflow shares one value.
        terminal = self._wait_for_terminal(submitted)
        attempt_id = _successful_attempt_id(self._client, terminal)
        queued_nonce = queued_execution_attempt_nonce(
            command.attempt_nonce,
            attempt_id,
            # Pass terminal explicitly so queued_execution_attempt_nonce receives a
            # reviewable attempt nonce and spec id input in isolated http control
            # benchmark executor execute.
            terminal.spec_id,
        )
        expected_attempt_id = command.resolved_spec.execution_attempt_id(
            queued_nonce,
            physical_settings.identity_digest,
            # Complete execution_attempt_id only after its identity digest and queued nonce
            # inputs are visible in isolated http control benchmark executor execute.
        )
        candidates = self._client.run_documents(
            logical_run_id=command.resolved_spec.logical_run_id.hex,
            limit=50,
            offset=0,
            # Complete run_documents only after its hex and logical run id inputs are visible
            # in isolated http control benchmark executor execute.
        )
        matches = tuple(
            item for item in candidates if item.execution_attempt_id == expected_attempt_id
        )
        if len(matches) != 1:
            # Fail the isolated http control benchmark executor execute path with
            # RuntimeError for control api did not expose one exact completed run result
            # when matches is true; do not continue ambiguously.
            raise RuntimeError("Control API did not expose one exact completed Run result")
        view = matches[0]
        manifest = self._reader.successful_run_manifest(view.run_artifact_id)
        if (
            manifest.resolved_spec != command.resolved_spec
            # Keep manifest visible while evaluating the resolved spec, attempt nonce and
            # queued nonce guard.
            or manifest.attempt_nonce != queued_nonce
            or manifest.execution_attempt_id != expected_attempt_id
            or manifest.physical_settings != physical_settings
            or manifest.comparison != view.comparison
            or manifest.logical_run_id != view.logical_run_id
            # Keep manifest visible while evaluating the resolved spec, attempt nonce and
            # queued nonce guard.
            or manifest.canonicality != view.canonicality
            or manifest.warnings != view.warnings
        ):
            raise RuntimeError("Control API Run response differs from committed exact bytes")
        return manifest.comparison

    # Define isolated http control benchmark executor wait for terminal as one focused
    # operation with an explicit boundary.
    def _wait_for_terminal(self, submitted: JobStatusView) -> JobStatusView:
        # Execute the isolated http control benchmark executor wait for terminal workflow
        # in explicit, reviewable steps.
        deadline = time.monotonic() + _CONTROL_MAXIMUM_WAIT_SECONDS
        current = submitted
        while current.state not in {
            AttemptState.SUCCEEDED,
            AttemptState.FAILED,
            # Repeat the isolated http control benchmark executor wait for terminal step
            # only while state, current and succeeded remains true.
            AttemptState.CANCELLED,
            AttemptState.INTERRUPTED,
        }:
            # Keep the state, current and succeeded loop body bounded within isolated http
            # control benchmark executor wait for terminal.
            if time.monotonic() >= deadline:
                raise RuntimeError("Control benchmark exceeded its finite job wait")
            time.sleep(self._poll_interval_seconds)
            _require_live_server(self._server_thread, self._server_errors)
            observed = self._client.get_job(submitted.job_id)
            # Invoke _require_same_job for current and observed as a visible isolated http
            # control benchmark executor wait for terminal step.
            _require_same_job(current, observed)
            current = observed
        if current.state is not AttemptState.SUCCEEDED:
            raise RuntimeError("Control benchmark job did not complete successfully")
        return current

    # Define isolated http control benchmark executor close as one focused operation with
    # an explicit boundary.
    def close(self) -> None:
        self._finalizer()


def _bound_loopback_socket() -> Socket:
    # Execute the bound loopback socket workflow in explicit, reviewable steps.
    result = Socket(AF_INET, SOCK_STREAM)
    try:
        # Perform the protected bound loopback socket operation before explicit failure
        # handling.
        result.bind(("127.0.0.1", 0))
        result.listen(128)
        result.set_inheritable(True)
        return result
    except BaseException:
        # Translate the BaseException failure through the bound loopback socket boundary.
        result.close()
        raise


def _run_isolated_control_server(
    *,
    run_server: Callable[..., None],
    # Keep the app input explicit in the run isolated control server contract.
    app: object,
    supervisor: SingleHostSupervisor,
    port: int,
    cycle_interval_seconds: float,
    bound_socket: Socket,
    # Keep the shutdown input explicit in the run isolated control server contract.
    shutdown: Event,
    errors: list[BaseException],
) -> None:
    # Execute the run isolated control server workflow in explicit, reviewable steps.
    try:
        # Perform the protected run isolated control server operation before explicit
        # failure handling.
        run_server(
            app,
            supervisor=supervisor,
            host="127.0.0.1",
            port=port,
            # Pass cycle interval seconds explicitly so run_server receives a reviewable 1
            # and app input in run isolated control server.
            cycle_interval_seconds=cycle_interval_seconds,
            bound_sockets=(bound_socket,),
            shutdown_event=shutdown,
        )
    except BaseException as error:
        # Invoke append for error as a visible run isolated control server step.
        errors.append(error)


def _await_control_server(
    client: LocalControlApiClient,
    *,
    expected_control_plane_id: ContentDigest,
    # Keep the thread input explicit in the await control server contract.
    thread: Thread,
    errors: list[BaseException],
    poll_interval_seconds: float,
) -> None:
    # Execute the await control server workflow in explicit, reviewable steps.
    deadline = time.monotonic() + 10.0
    while True:
        # Keep the True loop body bounded within await control server.
        _require_live_server(thread, errors)
        try:
            health = client.health()
        except ControlApiUnavailableError:
            # Translate the ControlApiUnavailableError failure through the await control
            # server boundary.
            if time.monotonic() >= deadline:
                raise RuntimeError("isolated Control API did not become ready") from None
            time.sleep(poll_interval_seconds)
            continue
        if health.control_plane_id != expected_control_plane_id:
            # Fail the await control server path with RuntimeError for isolated control
            # api exposed another controller identity when control plane id, expected
            # control plane id and health is true; do not continue ambiguously.
            raise RuntimeError("isolated Control API exposed another controller identity")
        return


def _require_live_server(thread: Thread, errors: list[BaseException]) -> None:
    # Execute the require live server workflow in explicit, reviewable steps.
    if errors:
        raise RuntimeError("isolated Control API server failed") from errors[0]
    if not thread.is_alive():
        raise RuntimeError("isolated Control API server stopped unexpectedly")


def _require_submitted_job(
    # Keep the submitted input explicit in the require submitted job contract.
    submitted: JobStatusView,
    request: SubmitJobRequest,
    input_artifact_ids: tuple[ArtifactId, ...],
) -> None:
    # Execute the require submitted job workflow in explicit, reviewable steps.
    payload_digest = sha256(request.payload_json).hexdigest()
    expected_spec_id = resolved_job_spec_hex(
        spec_version=request.spec_version,
        job_type=request.job_type.value,
        payload_digest_hex=payload_digest,
        # Pass input artifact hexes explicitly so resolved_job_spec_hex receives a
        # reviewable spec version and value input in require submitted job.
        input_artifact_hexes=(item.hex for item in input_artifact_ids),
    )
    if (
        submitted.spec_version != request.spec_version
        or submitted.spec_id.hex != expected_spec_id
        # Keep submitted visible while evaluating the spec version, hex and expected spec
        # id guard.
        or submitted.job_type is not request.job_type
        or submitted.payload_digest.hex != payload_digest
        or submitted.input_artifact_count != len(input_artifact_ids)
        or submitted.input_artifact_ids_digest != job_input_artifact_ids_digest(input_artifact_ids)
    ):
        # Fail the require submitted job path with RuntimeError for control api submitted
        # another resolved job specification when spec version, hex and expected spec id
        # is true; do not continue ambiguously.
        raise RuntimeError("Control API submitted another resolved job specification")


def _require_same_job(expected: JobStatusView, actual: JobStatusView) -> None:
    # Execute the require same job workflow in explicit, reviewable steps.
    if (
        actual.job_id != expected.job_id
        or actual.spec_version != expected.spec_version
        or actual.spec_id != expected.spec_id
        or actual.job_type is not expected.job_type
        # Keep actual visible while evaluating the job id, spec version and spec id guard.
        or actual.payload_digest != expected.payload_digest
        or actual.input_artifact_count != expected.input_artifact_count
        or actual.input_artifact_ids_digest != expected.input_artifact_ids_digest
        or actual.state_version < expected.state_version
    ):
        # Fail the require same job path with RuntimeError for control api job identity
        # changed while polling when job id, spec version and spec id is true; do not
        # continue ambiguously.
        raise RuntimeError("Control API job identity changed while polling")


def _successful_attempt_id(
    client: LocalControlApiClient,
    job: JobStatusView,
) -> AttemptId:
    # Execute the successful attempt id workflow in explicit, reviewable steps.
    after_event_id = 0
    succeeded: list[AttemptId] = []
    for _ in range(10):
        # Process range(10) inside the bounded successful attempt id loop.
        events = client.list_job_events(job.job_id, after_event_id=after_event_id, limit=1_000)
        if not events:
            break
        after_event_id = events[-1].event_id
        succeeded.extend(
            # Pass event explicitly so extend receives a reviewable attempt succeeded and
            # attempt id input in successful attempt id.
            event.attempt_id
            for event in events
            if event.event_type == "ATTEMPT_SUCCEEDED" and event.attempt_id is not None
        )
        if succeeded:
            # Keep the break step explicit within the successful attempt id workflow.
            break
    if len(succeeded) != 1:
        raise RuntimeError("Control API job has no unique successful durable attempt")
    return succeeded[0]


def _finalize_http_authority(
    # Keep the server thread input explicit in the finalize http authority contract.
    server_thread: Thread,
    shutdown: Event,
    errors: list[BaseException],
    bound_socket: Socket,
    authority: ControllerLock,
    # Keep the workspace input explicit in the finalize http authority contract.
    workspace: IsolatedBenchmarkWorkspace,
) -> None:
    # Execute the finalize http authority workflow in explicit, reviewable steps.
    shutdown.set()
    server_thread.join(timeout=15.0)
    timed_out = server_thread.is_alive()
    if timed_out:
        # Closing the pre-bound listener is the final bounded wake-up for an
        # otherwise stuck uvicorn loop. Cleanup below is never skipped.
        bound_socket.close()
        server_thread.join(timeout=5.0)
        timed_out = server_thread.is_alive()
    try:
        bound_socket.close()
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        # Handle the cleanup path after the protected finalize http authority operation.
        try:
            authority.release()
        finally:
            workspace.close()
    if timed_out:
        # Fail the finalize http authority path with RuntimeError for isolated control api
        # did not stop within its grace period when timed out is true; do not continue
        # ambiguously.
        raise RuntimeError("isolated Control API did not stop within its grace period")
    if errors:
        raise RuntimeError("isolated Control API server failed") from errors[0]


def _secret_free_config_bytes(settings: Settings) -> bytes:
    """Serialize only execution/control tables; source and backup stay absent."""

    tables = (
        _toml_table("paths", settings.paths, ("data_root",)),
        _toml_table(
            "resources",
            settings.resources,
            # Open the resources and max aggregate child memory mb payload explicitly for
            # _toml_table within secret free config bytes.
            (
                "max_aggregate_child_memory_mb",
                "max_builder_memory_mb",
                "builder_peak_private_memory_mb",
                "run_peak_private_memory_mb",
                # Pass max parallel runs explicitly so _toml_table receives a reviewable
                # resources and max aggregate child memory mb input in secret free config
                # bytes.
                "max_parallel_runs",
                "tmp_quota_gb",
                "max_run_tmp_gb",
                "max_run_output_gb",
                "disk_low_watermark_gb",
                # Pass disk emergency watermark gb explicitly so _toml_table receives a
                # reviewable resources and max aggregate child memory mb input in secret
                # free config bytes.
                "disk_emergency_watermark_gb",
                "native_threads_per_process",
                "memory_safety_reserve_mb",
                "page_cache_floor_mb",
                "host_staging_output_reserve_mb",
                # Pass fixed shared overhead mb explicitly so _toml_table receives a
                # reviewable resources and max aggregate child memory mb input in secret
                # free config bytes.
                "fixed_shared_overhead_mb",
                "memory_breach_samples",
                "swap_activity_samples",
            ),
        ),
        # Register planning through _toml_table so the tables table remains scannable.
        _toml_table(
            "planning",
            settings.planning,
            (
                "max_remote_gb",
                # Pass max local gb explicitly so _toml_table receives a reviewable
                # planning and max remote gb input in secret free config bytes.
                "max_local_gb",
                "max_days",
                "staging_reserve_gb",
                "max_total_blocks",
                "max_total_shards",
                # Pass max shard blocks explicitly so _toml_table receives a reviewable
                # planning and max remote gb input in secret free config bytes.
                "max_shard_blocks",
                "max_query_execution_seconds",
                "max_query_memory_mb",
                "max_query_result_rows",
            ),
            # Complete _toml_table only after its planning and max remote gb inputs are
            # visible in secret free config bytes.
        ),
        _toml_table(
            "replay",
            settings.replay,
            ("backend", "reader_batch_rows", "reader_readahead", "output_buffer_rows", "threads"),
            # Pass reader batch rows explicitly so _toml_table receives a reviewable
            # replay and backend input in secret free config bytes.
            names={"reader_batch_rows": "batch_rows", "reader_readahead": "readahead"},
        ),
        _toml_table(
            "control",
            settings.control,
            # Open the control and host payload explicitly for _toml_table within secret
            # free config bytes.
            (
                "host",
                "port",
                "progress_interval_ms",
                "max_request_mb",
                # Pass secure cookie explicitly so _toml_table receives a reviewable
                # control and host input in secret free config bytes.
                "secure_cookie",
            ),
        ),
    )
    return ("\n\n".join(tables) + "\n").encode("utf-8")


# Define remove private workspace as one focused operation with an explicit boundary.
def _remove_private_workspace(root: Path) -> None:
    """Delete only an inventoried private tree; unexpected entries fail closed."""

    records = file_records(root)
    for record in records:
        # Process records inside the bounded remove private workspace loop.
        relative = safe_relative_path(record.path)
        os.unlink(root.joinpath(*relative.parts))
    for directory, _, _ in os.walk(root, topdown=False, followlinks=False):
        Path(directory).rmdir()


def _toml_table(
    # Keep the name input explicit in the toml table contract.
    name: str,
    value: object,
    expected_fields: tuple[str, ...],
    *,
    names: dict[str, str] | None = None,
    # Keep the str input explicit in the toml table contract.
) -> str:
    # Execute the toml table workflow in explicit, reviewable steps.
    declared_fields = getattr(value, "__dataclass_fields__", None)
    if not isinstance(declared_fields, dict):
        raise TypeError(f"isolated benchmark config [{name}] is not a dataclass")
    actual_fields = tuple(declared_fields)
    if actual_fields != expected_fields:
        # Fail the toml table path with RuntimeError for isolated benchmark config schema
        # drifted in [ and ] when actual fields and expected fields is true; do not
        # continue ambiguously.
        raise RuntimeError(f"isolated benchmark config schema drifted in [{name}]")
    aliases = names or {}
    lines = [f"[{name}]"]
    for field_name in expected_fields:
        # Process expected_fields inside the bounded toml table loop.
        key = aliases.get(field_name, field_name)
        lines.append(f"{key} = {_toml_scalar(getattr(value, field_name))}")
    return "\n".join(lines)


def _toml_scalar(value: object) -> str:
    # Execute the toml scalar workflow in explicit, reviewable steps.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, StrEnum):
        # Return the completed toml scalar result without a hidden fallback.
        return json.dumps(value.value, ensure_ascii=True)
    if isinstance(value, (str, Path)):
        return json.dumps(str(value), ensure_ascii=True)
    raise TypeError("isolated benchmark config contains an unsupported scalar")


__all__ = [
    # Keep the isolated benchmark workspace component named inside the all contract.
    "IsolatedBenchmarkWorkspace",
    "IsolatedDirectControlBenchmarkExecutor",
    "IsolatedHttpControlBenchmarkExecutor",
    "create_isolated_benchmark_workspace",
]
