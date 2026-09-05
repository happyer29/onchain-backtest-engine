"""Composition-root behavior for the injected CLI backend."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

# Import pytest at the visible module dependency boundary.
import pytest

import backtest.bootstrap.cli as cli_module
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.control import ControlApiUnavailableError, ControlHealth
from backtest.adapters.source.clickhouse import CapabilityConfigError
from backtest.application.backups import BackupGeneration, BackupIntegrityError, RestoreReport

# Import models at the visible module dependency boundary.
from backtest.application.models import ListJobsRequest, PlanDatasetRequest
from backtest.application.retention import (
    GarbageCollectionBatch,
    GarbageCollectionPlan,
    GarbageCollectionReceipt,
    # Include pin record so the retention dependency remains explicit.
    PinRecord,
)
from backtest.application.use_cases.query_artifacts import ArtifactDetails, ArtifactLineage
from backtest.application.use_cases.query_runs import RunSummaryView
from backtest.application.use_cases.submit_job import SubmitJobRequest

# Import cli at the visible module dependency boundary.
from backtest.bootstrap.cli import (
    ControlApiCliBackend,
    RecoveryCliBackend,
    RuntimeCliBackend,
    build_cli_backend,
    # Include build cli recovery backend so the cli dependency remains explicit.
    build_cli_recovery_backend,
)
from backtest.bootstrap.config import (
    ConfigError,
    ControlSettings,
    # Include path settings so the config dependency remains explicit.
    PathSettings,
    Settings,
    SourceSettings,
)
from backtest.bootstrap.container import RuntimeContainer

# Import recovery at the visible module dependency boundary.
from backtest.bootstrap.recovery import RecoveryServices
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier, JobId, SourceId
from backtest.interfaces.cli import CliUsageError
from backtest.runtime.control_plane_identity import control_plane_identity
from backtest.runtime.controller_lock import ControllerAlreadyRunningError


def _settings(
    # Keep the data root input explicit in the settings contract.
    data_root: Path,
    *,
    capabilities_file: Path | None = None,
) -> Settings:
    # Execute the settings workflow in explicit, reviewable steps.
    return Settings(
        paths=PathSettings(data_root=data_root),
        control=ControlSettings(host="127.0.0.1", port=9_090, max_request_mb=3),
        source=SourceSettings(
            source_id="configured-indexer",
            # Pass capabilities file explicitly so SourceSettings receives a reviewable
            # configured-indexer and capabilities file input in settings.
            capabilities_file=capabilities_file,
        ),
    )


def _backend(settings: Settings, **executors: Mock) -> RuntimeCliBackend:
    # Execute the backend workflow in explicit, reviewable steps.
    defaults = {
        "inspect_source": Mock(),
        "plan_dataset": Mock(),
        "submit_job": Mock(),
        "list_jobs": Mock(),
        # Register mock through Mock so the defaults table remains scannable.
        "get_job": Mock(),
        "cancel_job": Mock(),
    }
    defaults.update(executors)
    artifacts = LocalArtifactRepository(settings.paths.data_root)
    catalog = Mock()
    # Unit backends exercise CLI authority, while focused tests cover reconciliation.
    catalog.begin_reconciliation_session.return_value = True
    catalog.finish_reconciliation_session.return_value = True
    container = SimpleNamespace(
        # Pass settings explicitly so SimpleNamespace receives a reviewable resolve and
        # data root input in backend.
        settings=settings,
        source=SimpleNamespace(
            chain_identity=Mock(
                return_value=(
                    SOLANA_MAINNET_NETWORK_ID,
                    # Pass block32 transaction32 position schema id explicitly so Mock
                    # receives a reviewable solana mainnet network id and block32
                    # transaction32 position schema id input in backend.
                    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                )
            ),
            build_evidence_request=Mock(side_effect=lambda **values: SimpleNamespace(**values)),
        ),
        control=SimpleNamespace(**defaults),
        # Keep the simple namespace and resolve SimpleNamespace step visible while
        # building container.
        artifacts=artifacts,
        catalog=catalog,
    )
    return RuntimeCliBackend(cast(RuntimeContainer, container))


def test_mutating_cli_delegation_is_inside_the_controller_lock(
    # Keep the tmp path input explicit in the test mutating cli delegation is inside the
    # controller lock contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test mutating cli delegation is inside the controller lock workflow in
    # explicit, reviewable steps.
    lock_depth = 0
    lock_paths: list[Path] = []

    # Keep the recording lock contract and validation rules together.
    class RecordingLock:
        def __init__(self, path: Path) -> None:
            lock_paths.append(path)

        def acquire(self) -> RecordingLock:
            # Execute the recording lock acquire workflow in explicit, reviewable steps.
            nonlocal lock_depth
            lock_depth += 1
            return self

        def release(self) -> None:
            # Execute the recording lock release workflow in explicit, reviewable steps.
            nonlocal lock_depth
            lock_depth -= 1

    def locked_result(value: object) -> Any:
        # Execute the locked result workflow in explicit, reviewable steps.
        assert lock_depth == 1
        return value

    inspection = SimpleNamespace(artifact=object())
    submitted = object()
    cancelled = object()
    # Assemble inspect use case once so the test mutating cli delegation is inside the
    # controller lock workflow shares one value.
    inspect_use_case = Mock()
    inspect_use_case.execute.side_effect = lambda request: locked_result(inspection)
    submit_use_case = Mock()
    submit_use_case.execute.side_effect = lambda request: locked_result(submitted)
    cancel_use_case = Mock()
    # Assemble cancel use case execute side effect once so the test mutating cli
    # delegation is inside the controller lock workflow shares one value.
    cancel_use_case.execute.side_effect = lambda request: locked_result(cancelled)
    settings = _settings(tmp_path / "relative" / ".." / "state")
    backend = _backend(
        settings,
        inspect_source=inspect_use_case,
        # Pass submit job explicitly so _backend receives a reviewable settings and
        # inspect use case input in test mutating cli delegation is inside the controller
        # lock.
        submit_job=submit_use_case,
        cancel_job=cancel_use_case,
    )
    monkeypatch.setattr(cli_module, "ControllerLock", RecordingLock)
    submit_request = cast(SubmitJobRequest, object())
    # Assemble job id once so the test mutating cli delegation is inside the controller
    # lock workflow shares one value.
    job_id = JobId("job-fixture")

    assert backend.inspect_source(None) is inspection
    assert backend.submit_job(submit_request) is submitted
    assert backend.cancel_job(job_id) is cancelled

    expected_lock = settings.paths.data_root.resolve() / "locks" / "controller.lock"
    # Verify the lock paths and expected lock relationship before this scenario is
    # accepted.
    assert lock_paths == [expected_lock, expected_lock, expected_lock]
    inspect_request = inspect_use_case.execute.call_args.args[0]
    assert inspect_request.source_id == SourceId("configured-indexer")
    submit_use_case.execute.assert_called_once_with(submit_request)
    cancel_request = cancel_use_case.execute.call_args.args[0]
    # Verify cancel_request.job_id == job_id before this scenario is accepted.
    assert cancel_request.job_id == job_id
    assert lock_depth == 0


def test_bounded_inspection_builds_an_exact_host_limited_request(tmp_path: Path) -> None:
    # Execute the test bounded inspection builds an exact host limited request workflow in
    # explicit, reviewable steps.
    inspection = SimpleNamespace(artifact=object())
    inspect_use_case = Mock()
    inspect_use_case.execute.return_value = inspection
    backend = _backend(
        _settings(tmp_path / "state"),
        # Pass inspect source explicitly so _backend receives a reviewable state and
        # settings input in test bounded inspection builds an exact host limited request.
        inspect_source=inspect_use_case,
    )

    assert (
        backend.inspect_source(
            None,
            # Pass evidence from block explicitly into inspect_source within test bounded
            # inspection builds an exact host limited request.
            evidence_from_block=100,
            evidence_to_block=120,
        )
        is inspection
    )
    # Assemble request once so the test bounded inspection builds an exact host limited
    # request workflow shares one value.
    request = inspect_use_case.execute.call_args.args[0]
    assert request.evidence_request.block_range.from_block_ordinal == 100
    assert request.evidence_request.block_range.to_block_ordinal == 120
    assert request.evidence_request.block_range.network_id == SOLANA_MAINNET_NETWORK_ID
    assert request.evidence_request.query_limits.max_result_rows == 10_000_000


# Define test read only cli delegation does not take the controller lock as one focused
# operation with an explicit boundary.
def test_read_only_cli_delegation_does_not_take_the_controller_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test read only cli delegation does not take the controller lock workflow
    # in explicit, reviewable steps.
    def reject_lock(_: Path) -> None:
        raise AssertionError("read-only CLI operations must not take the writer lock")

    plan = object()
    records = (object(),)
    record = object()
    # Assemble plan use case once so the test read only cli delegation does not take the
    # controller lock workflow shares one value.
    plan_use_case = Mock()
    plan_use_case.execute.return_value = plan
    list_use_case = Mock()
    list_use_case.execute.return_value = records
    get_use_case = Mock()
    # Assemble get use case execute return value once so the test read only cli delegation
    # does not take the controller lock workflow shares one value.
    get_use_case.execute.return_value = record
    backend = _backend(
        _settings(tmp_path / "state"),
        plan_dataset=plan_use_case,
        list_jobs=list_use_case,
        # Pass get job explicitly so _backend receives a reviewable state and settings
        # input in test read only cli delegation does not take the controller lock.
        get_job=get_use_case,
    )
    monkeypatch.setattr(cli_module, "ControllerLock", reject_lock)
    plan_request = cast(PlanDatasetRequest, object())
    list_request = ListJobsRequest(limit=5)
    # Assemble job id once so the test read only cli delegation does not take the
    # controller lock workflow shares one value.
    job_id = JobId("job-fixture")

    assert backend.plan_dataset(plan_request) is plan
    assert backend.list_jobs(list_request) == records
    assert backend.get_job(job_id) is record

    plan_use_case.execute.assert_called_once_with(plan_request)
    # Invoke assert_called_once_with for list request as a visible test read only cli
    # delegation does not take the controller lock step.
    list_use_case.execute.assert_called_once_with(list_request)
    get_request = get_use_case.execute.call_args.args[0]
    assert get_request.job_id == job_id


def test_serve_holds_controller_lock_and_passes_bounded_loopback_settings(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test serve holds controller lock and
    # passes bounded loopback settings contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test serve holds controller lock and passes bounded loopback settings
    # workflow in explicit, reviewable steps.
    lock_active = False

    # Keep the recording lock contract and validation rules together.
    class RecordingLock:
        def __init__(self, path: Path) -> None:
            # Execute the recording lock init workflow in explicit, reviewable steps.
            assert path == tmp_path / "state" / "locks" / "controller.lock"
            self.instance_id = "11111111-1111-4111-8111-111111111111"

        def acquire(self) -> RecordingLock:
            # Execute the recording lock acquire workflow in explicit, reviewable steps.
            nonlocal lock_active
            lock_active = True
            return self

        def release(self) -> None:
            # Execute the recording lock release workflow in explicit, reviewable steps.
            nonlocal lock_active
            lock_active = False

    settings = _settings(tmp_path / "state")
    backend = _backend(settings)
    asgi_app = object()
    # Assemble create calls once so the test serve holds controller lock and passes
    # bounded loopback settings workflow shares one value.
    create_calls: list[tuple[object, ContentDigest, int, bool]] = []
    run_calls: list[tuple[object, dict[str, object]]] = []
    supervisor = object()

    def create_app(
        control: object,
        # Close the create app signature after its explicit inputs.
        *,
        control_plane_id: ContentDigest,
        max_request_bytes: int,
        secure_cookie: bool,
    ) -> object:
        # Execute the create app workflow in explicit, reviewable steps.
        create_calls.append((control, control_plane_id, max_request_bytes, secure_cookie))
        return asgi_app

    def build_supervisor(*args: object, **kwargs: object) -> object:
        # Execute the build supervisor workflow in explicit, reviewable steps.
        assert lock_active is True
        assert args == (backend.container,)
        assert kwargs["authority"].__class__ is RecordingLock
        return supervisor

    def run(app: object, **kwargs: object) -> None:
        # Execute the run workflow in explicit, reviewable steps.
        assert lock_active is True
        assert kwargs["supervisor"] is supervisor
        run_calls.append((app, kwargs))

    monkeypatch.setattr(cli_module, "ControllerLock", RecordingLock)
    monkeypatch.setattr(cli_module, "create_app", create_app)
    # Invoke setattr for build single host supervisor and cli module as a visible test
    # serve holds controller lock and passes bounded loopback settings step.
    monkeypatch.setattr(cli_module, "build_single_host_supervisor", build_supervisor)
    monkeypatch.setattr(cli_module, "run_control_server", run)

    backend.serve()

    # The unchanged session uses bounded inventory evidence instead of a full rebuild.
    backend.container.catalog.begin_reconciliation_session.assert_called_once()
    backend.container.catalog.finish_reconciliation_session.assert_called_once()
    assert len(create_calls) == 1
    assert create_calls[0][0] is backend.container.control
    # Verify the control plane identity, data root and create calls relationship before
    # this scenario is accepted.
    assert create_calls[0][1] == control_plane_identity(
        settings.paths.data_root,
        "11111111-1111-4111-8111-111111111111",
    )
    assert create_calls[0][2:] == (3 * 1024 * 1024, False)
    # Verify the run calls, asgi app and host relationship before this scenario is
    # accepted.
    assert run_calls == [
        (
            asgi_app,
            {
                "host": "127.0.0.1",
                # Keep the port expectation tied to run calls, asgi app and host in this
                # scenario.
                "port": 9_090,
                "supervisor": supervisor,
                "cycle_interval_seconds": 0.5,
            },
        )
        # Verify the run calls, asgi app and host relationship before this scenario is
        # accepted.
    ]
    assert lock_active is False


def test_controller_contention_becomes_a_safe_cli_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test controller contention becomes a safe cli error signature after its
    # explicit inputs.
) -> None:
    # Execute the test controller contention becomes a safe cli error workflow in
    # explicit, reviewable steps.
    class ContendedLock:
        def __init__(self, _: Path) -> None:
            pass

        def acquire(self) -> ContendedLock:
            raise ControllerAlreadyRunningError({"password": "must-not-leak"})

        # Define contended lock release as one focused operation with an explicit
        # boundary.
        def release(self) -> None:
            raise AssertionError("an unacquired lock must not be released")

    monkeypatch.setattr(cli_module, "ControllerLock", ContendedLock)
    backend = _backend(_settings(tmp_path / "state"))

    with pytest.raises(CliUsageError) as caught:
        # Invoke submit_job for cast and object as a visible test controller contention
        # becomes a safe cli error step.
        backend.submit_job(cast(SubmitJobRequest, object()))

    assert caught.value.code == "CONTROLLER_ALREADY_RUNNING"
    assert caught.value.safe_message == "Another local controller already owns this data root."
    assert "must-not-leak" not in str(caught.value)
    assert caught.value.__context__ is None


# Define test controller error from delegated body is not misclassified and releases lock
# as one focused operation with an explicit boundary.
def test_controller_error_from_delegated_body_is_not_misclassified_and_releases_lock(
    tmp_path: Path,
) -> None:
    # Execute the test controller error from delegated body is not misclassified and
    # releases lock workflow in explicit, reviewable steps.
    body_error = ControllerAlreadyRunningError({"origin": "delegated-body"})
    submit_use_case = Mock()
    submit_use_case.execute.side_effect = body_error
    settings = _settings(tmp_path / "state")
    backend = _backend(settings, submit_job=submit_use_case)

    # Acquire raises, controller already running error and pytest at an explicit test
    # controller error from delegated body is not misclassified and releases lock context
    # boundary so cleanup remains scoped.
    with pytest.raises(ControllerAlreadyRunningError) as caught:
        backend.submit_job(cast(SubmitJobRequest, object()))

    assert caught.value is body_error
    lock_path = settings.paths.data_root.resolve() / "locks" / "controller.lock"
    with cli_module.ControllerLock(lock_path):
        # Keep this explicitly supported no-op branch visible.
        pass


def test_operator_mutations_delegate_under_one_controller_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test operator mutations delegate under one controller authority workflow
    # in explicit, reviewable steps.
    lock_depth = 0
    lock_paths: list[Path] = []

    # Keep the recording lock contract and validation rules together.
    class RecordingLock:
        def __init__(self, path: Path) -> None:
            lock_paths.append(path)

        def acquire(self) -> RecordingLock:
            # Execute the recording lock acquire workflow in explicit, reviewable steps.
            nonlocal lock_depth
            lock_depth += 1
            return self

        def release(self) -> None:
            # Execute the recording lock release workflow in explicit, reviewable steps.
            nonlocal lock_depth
            lock_depth -= 1

    def locked(value: object) -> object:
        # Execute the locked workflow in explicit, reviewable steps.
        assert lock_depth == 1
        return value

    retry = Mock()
    retry_record = object()
    retry.execute.side_effect = lambda request: locked(retry_record)
    # Assemble retention once so the test operator mutations delegate under one controller
    # authority workflow shares one value.
    retention = SimpleNamespace(
        create_pin=Mock(side_effect=lambda request: locked(pin)),
        retire_pin=Mock(side_effect=lambda pin_id: locked(pin)),
        plan_garbage_collection=Mock(side_effect=lambda request: locked(plan)),
        execute_garbage_collection=Mock(side_effect=lambda selected: locked(batch)),
        # Keep the mock and locked Mock step visible while building retention.
        purge_trash=Mock(side_effect=lambda batch_id: locked(receipt)),
    )
    pin = cast(PinRecord, object())
    plan = cast(GarbageCollectionPlan, object())
    batch = cast(GarbageCollectionBatch, object())
    # Assemble receipt once so the test operator mutations delegate under one controller
    # authority workflow shares one value.
    receipt = cast(GarbageCollectionReceipt, object())
    generation = cast(BackupGeneration, object())
    report = cast(RestoreReport, object())
    maintenance = SimpleNamespace(
        retention=retention,
        # Keep the mock and locked Mock step visible while building maintenance.
        create_backup=Mock(side_effect=lambda: locked(generation)),
        verify_restore=Mock(
            side_effect=lambda backup_cut_id: locked(
                SimpleNamespace(report=report, destination_name="restore-drill")
            )
            # Complete Mock only after its restore-drill and locked inputs are visible in test
            # operator mutations delegate under one controller authority.
        ),
    )
    settings = _settings(tmp_path / "state")
    backend = _backend(settings, retry_job=retry)
    cast(Any, backend.container).maintenance = maintenance
    # Invoke setattr for controller lock and cli module as a visible test operator
    # mutations delegate under one controller authority step.
    monkeypatch.setattr(cli_module, "ControllerLock", RecordingLock)

    job_id = JobId("retry-me")
    pin_id = Identifier("keep")
    artifact_id = ArtifactId("1" * 64)
    batch_id = ContentDigest("2" * 64)
    # Assemble cut id once so the test operator mutations delegate under one controller
    # authority workflow shares one value.
    cut_id = ContentDigest("3" * 64)
    assert backend.retry_job(job_id) is retry_record
    assert backend.create_pin(pin_id, (artifact_id,), "audit") is pin
    assert backend.retire_pin(pin_id) is pin
    assert backend.execute_garbage_collection((artifact_id,)) == (plan, batch)
    # Verify the receipt, purge trash and batch id relationship before this scenario is
    # accepted.
    assert backend.purge_trash(batch_id) is receipt
    assert backend.create_backup() is generation
    assert backend.verify_restore(cut_id) == (report, "restore-drill")

    expected_lock = settings.paths.data_root.resolve() / "locks" / "controller.lock"
    assert lock_paths == [expected_lock] * 7
    # Verify lock_depth == 0 before this scenario is accepted.
    assert lock_depth == 0
    retry_request = retry.execute.call_args.args[0]
    assert retry_request.job_id == job_id
    pin_request = retention.create_pin.call_args.args[0]
    assert (pin_request.pin_id, pin_request.roots, pin_request.reason) == (
        # Keep the pin id expectation tied to pin id, roots and reason in this scenario.
        pin_id,
        (artifact_id,),
        "audit",
    )
    retention.execute_garbage_collection.assert_called_once_with(plan)
    # Invoke assert_called_once_with for cut id as a visible test operator mutations
    # delegate under one controller authority step.
    maintenance.verify_restore.assert_called_once_with(cut_id)


def test_operator_metadata_and_gc_plan_are_read_only_delegations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test operator metadata and gc plan are read only delegations workflow in
    # explicit, reviewable steps.
    def reject_lock(_: Path) -> None:
        raise AssertionError("read-only operator queries must not take controller.lock")

    details = cast(ArtifactDetails, object())
    lineage = cast(ArtifactLineage, object())
    runs_result = cast(tuple[RunSummaryView, ...], (object(),))
    # Assemble plan once so the test operator metadata and gc plan are read only
    # delegations workflow shares one value.
    plan = cast(GarbageCollectionPlan, object())
    artifact_queries = SimpleNamespace(
        details=Mock(return_value=details),
        lineage=Mock(return_value=lineage),
    )
    # Assemble run queries once so the test operator metadata and gc plan are read only
    # delegations workflow shares one value.
    run_queries = SimpleNamespace(list=Mock(return_value=runs_result))
    retention = SimpleNamespace(plan_garbage_collection=Mock(return_value=plan))
    backend = _backend(
        _settings(tmp_path / "state"),
        query_artifacts=artifact_queries,
        # Pass query runs explicitly so _backend receives a reviewable state and settings
        # input in test operator metadata and gc plan are read only delegations.
        query_runs=run_queries,
    )
    cast(Any, backend.container).maintenance = SimpleNamespace(retention=retention)
    monkeypatch.setattr(cli_module, "ControllerLock", reject_lock)
    artifact_id = ArtifactId("1" * 64)

    # Verify the details, verify artifact and artifact id relationship before this
    # scenario is accepted.
    assert backend.verify_artifact(artifact_id) is details
    assert backend.show_lineage(artifact_id) is lineage
    assert backend.list_runs(limit=5, offset=2) is runs_result
    assert backend.plan_garbage_collection((artifact_id,)) is plan

    artifact_queries.details.assert_called_once_with(artifact_id)
    # Invoke assert_called_once_with for artifact id as a visible test operator metadata
    # and gc plan are read only delegations step.
    artifact_queries.lineage.assert_called_once_with(artifact_id)
    run_queries.list.assert_called_once_with(limit=5, offset=2)
    gc_request = retention.plan_garbage_collection.call_args.args[0]
    assert gc_request.additional_retained_roots == (artifact_id,)


def test_build_cli_backend_composes_profile_and_capability_override(
    # Keep the tmp path input explicit in the test build cli backend composes profile and
    # capability override contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test build cli backend composes profile and capability override workflow
    # in explicit, reviewable steps.
    config_path = tmp_path / "research.toml"
    configured_capabilities = tmp_path / "configured.toml"
    override = tmp_path / "override.toml"
    settings = _settings(tmp_path / "state", capabilities_file=configured_capabilities)
    artifacts = object()
    catalog = object()
    container = cast(
        RuntimeContainer,
        SimpleNamespace(artifacts=artifacts, catalog=catalog),
    )
    # Assemble calls once so the test build cli backend composes profile and capability
    # override workflow shares one value.
    calls: list[tuple[Settings, str, Path | None]] = []

    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)

    def build(
        selected_settings: Settings,
        *,
        # Keep the profile input explicit in the build contract.
        profile: str,
        capabilities_file: Path | None,
    ) -> RuntimeContainer:
        # Execute the build workflow in explicit, reviewable steps.
        calls.append((selected_settings, profile, capabilities_file))
        return container

    monkeypatch.setattr(cli_module, "build_runtime_container", build)
    reconciler = Mock()
    reconciler_factory = Mock(return_value=reconciler)
    monkeypatch.setattr(
        cli_module,
        "LocalArtifactCatalogReconciler",
        reconciler_factory,
    )

    backend = build_cli_backend(config_path, override, require_capabilities=True)

    assert isinstance(backend, RuntimeCliBackend)
    # Verify backend.container is container before this scenario is accepted.
    assert backend.container is container
    assert calls == [(settings, "research", override)]
    reconciler_factory.assert_called_once_with(artifacts, catalog)
    reconciler.reconcile_once.assert_called_once_with()


def test_build_cli_backend_holds_probe_authority_through_runtime_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test build cli backend holds probe authority through runtime composition
    # signature after its explicit inputs.
) -> None:
    # Execute the test build cli backend holds probe authority through runtime composition
    # workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")
    probe_active = False

    # Keep the free probe lock contract and validation rules together.
    class FreeProbeLock:
        def __init__(self, path: Path) -> None:
            assert path == settings.paths.data_root.resolve() / "locks" / "controller.lock"

        def acquire(self) -> FreeProbeLock:
            # Execute the free probe lock acquire workflow in explicit, reviewable steps.
            nonlocal probe_active
            assert probe_active is False
            probe_active = True
            return self

        def release(self) -> None:
            # Execute the free probe lock release workflow in explicit, reviewable steps.
            nonlocal probe_active
            assert probe_active is True
            probe_active = False

    artifacts = object()
    catalog = object()
    container = cast(
        RuntimeContainer,
        SimpleNamespace(artifacts=artifacts, catalog=catalog),
    )

    def build(*args: object, **kwargs: object) -> RuntimeContainer:
        # Execute the build workflow in explicit, reviewable steps.
        del args, kwargs
        assert probe_active is True
        return container

    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "ControllerLock", FreeProbeLock)
    # Invoke setattr for build runtime container and cli module as a visible test build
    # cli backend holds probe authority through runtime composition step.
    monkeypatch.setattr(cli_module, "build_runtime_container", build)
    reconciler = Mock()

    def reconciler_factory(selected_artifacts: object, selected_catalog: object) -> Mock:
        # Readiness must complete before the probe controller authority is released.
        assert probe_active is True
        assert (selected_artifacts, selected_catalog) == (artifacts, catalog)
        return reconciler

    monkeypatch.setattr(
        cli_module,
        "LocalArtifactCatalogReconciler",
        reconciler_factory,
    )

    backend = build_cli_backend(tmp_path / "research.toml", None)

    assert isinstance(backend, RuntimeCliBackend)
    assert backend.container is container
    assert probe_active is False
    reconciler.reconcile_once.assert_called_once_with()


# Define test build cli backend delegates to identity bound running controller without
# composition as one focused operation with an explicit boundary.
def test_build_cli_backend_delegates_to_identity_bound_running_controller_without_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test build cli backend delegates to identity bound running controller
    # without composition workflow in explicit, reviewable steps.
    config_path = tmp_path / "research.toml"
    settings = _settings(tmp_path / "state")
    instance_id = "11111111-1111-4111-8111-111111111111"
    expected_id = control_plane_identity(settings.paths.data_root, instance_id)

    # Keep the held lock contract and validation rules together.
    class HeldLock:
        def __init__(self, path: Path) -> None:
            assert path == settings.paths.data_root.resolve() / "locks" / "controller.lock"

        def acquire(self) -> HeldLock:
            raise ControllerAlreadyRunningError({"instance_id": instance_id})

    # Assemble client once so the test build cli backend delegates to identity bound
    # running controller without composition workflow shares one value.
    client = SimpleNamespace(
        health=Mock(
            return_value=ControlHealth(
                profile="research",
                version="1",
                # Pass control plane id explicitly so ControlHealth receives a reviewable
                # research and 1 input in test build cli backend delegates to identity
                # bound running controller without composition.
                control_plane_id=expected_id,
            )
        )
    )
    client_factory = Mock(return_value=client)
    # Assemble runtime builder once so the test build cli backend delegates to identity
    # bound running controller without composition workflow shares one value.
    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "ControllerLock", HeldLock)
    monkeypatch.setattr(cli_module, "LocalControlApiClient", client_factory)
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    # Assemble backend once so the test build cli backend delegates to identity bound
    # running controller without composition workflow shares one value.
    backend = build_cli_backend(config_path, None, prefer_running_controller=True)

    assert isinstance(backend, ControlApiCliBackend)
    assert backend.client is client
    runtime_builder.assert_not_called()
    client_factory.assert_called_once_with(
        # Pass declared text explicitly so assert_called_once_with receives a reviewable 1
        # input in test build cli backend delegates to identity bound running controller
        # without composition.
        "127.0.0.1",
        9_090,
        maximum_response_bytes=3 * 1024 * 1024,
    )
    assert not settings.paths.data_root.exists()


# Define test running controller serves supported queries without runtime composition as
# one focused operation with an explicit boundary.
def test_running_controller_serves_supported_queries_without_runtime_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test running controller serves supported queries without runtime
    # composition workflow in explicit, reviewable steps.
    config_path = tmp_path / "research.toml"
    settings = _settings(tmp_path / "state")
    instance_id = "11111111-1111-4111-8111-111111111111"
    details = cast(ArtifactDetails, object())
    lineage = cast(ArtifactLineage, object())
    # Assemble run once so the test running controller serves supported queries without
    # runtime composition workflow shares one value.
    run = cast(RunSummaryView, object())

    # Keep the held lock contract and validation rules together.
    class HeldLock:
        def __init__(self, path: Path) -> None:
            del path

        def acquire(self) -> HeldLock:
            raise ControllerAlreadyRunningError({"instance_id": instance_id})

    # Assemble client once so the test running controller serves supported queries without
    # runtime composition workflow shares one value.
    client = SimpleNamespace(
        health=Mock(
            return_value=ControlHealth(
                profile="research",
                version="1",
                # Keep the data root control_plane_identity step visible while building
                # client.
                control_plane_id=control_plane_identity(settings.paths.data_root, instance_id),
            )
        ),
        artifact_document=Mock(return_value=details),
        lineage_document=Mock(return_value=lineage),
        # Keep the mock and run Mock step visible while building client.
        run_documents=Mock(return_value=(run,)),
    )
    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "ControllerLock", HeldLock)
    # Invoke setattr for local control api client and mock as a visible test running
    # controller serves supported queries without runtime composition step.
    monkeypatch.setattr(cli_module, "LocalControlApiClient", Mock(return_value=client))
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    backend = build_cli_backend(config_path, None, prefer_running_controller=True)
    artifact_id = ArtifactId("a" * 64)

    assert backend.verify_artifact(artifact_id) is details
    # Verify the lineage, show lineage and artifact id relationship before this scenario
    # is accepted.
    assert backend.show_lineage(artifact_id) is lineage
    assert backend.list_runs(limit=1, offset=7) == (run,)
    runtime_builder.assert_not_called()
    client.artifact_document.assert_called_once_with(artifact_id)
    client.lineage_document.assert_called_once_with(artifact_id)
    # Invoke assert_called_once_with as a visible step within the test running controller
    # serves supported queries without runtime composition workflow.
    client.run_documents.assert_called_once_with(limit=1, offset=7)


@pytest.mark.parametrize("health_failure", [ControlApiUnavailableError(), None])
def test_build_cli_backend_fails_closed_for_unreachable_or_mismatched_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Keep the health failure input explicit in the test build cli backend fails closed
    # for unreachable or mismatched controller contract.
    health_failure: ControlApiUnavailableError | None,
) -> None:
    # Execute the test build cli backend fails closed for unreachable or mismatched
    # controller workflow in explicit, reviewable steps.
    config_path = tmp_path / "research.toml"
    settings = _settings(tmp_path / "state")
    instance_id = "11111111-1111-4111-8111-111111111111"

    # Keep the held lock contract and validation rules together.
    class HeldLock:
        def __init__(self, path: Path) -> None:
            del path

        def acquire(self) -> HeldLock:
            raise ControllerAlreadyRunningError({"instance_id": instance_id})

    # Assemble health once so the test build cli backend fails closed for unreachable or
    # mismatched controller workflow shares one value.
    health = Mock()
    if health_failure is None:
        # Handle the test build cli backend fails closed for unreachable or mismatched
        # controller health_failure is None branch as a distinct logical block.
        health.return_value = ControlHealth(
            profile="research",
            version="1",
            control_plane_id=control_plane_identity(tmp_path / "other-state", instance_id),
        )
        # Assemble expected code once so the test build cli backend fails closed for
        # unreachable or mismatched controller workflow shares one value.
        expected_code = "CONTROLLER_API_MISMATCH"
    else:
        # Handle the test build cli backend fails closed for unreachable or mismatched
        # controller complement of health_failure is None explicitly.
        health.side_effect = health_failure
        expected_code = "CONTROLLER_API_UNAVAILABLE"
    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "ControllerLock", HeldLock)
    # Invoke setattr for local control api client and mock as a visible test build cli
    # backend fails closed for unreachable or mismatched controller step.
    monkeypatch.setattr(
        cli_module,
        "LocalControlApiClient",
        Mock(return_value=SimpleNamespace(health=health)),
    )
    # Invoke setattr for build runtime container and cli module as a visible test build
    # cli backend fails closed for unreachable or mismatched controller step.
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    with pytest.raises(CliUsageError) as caught:
        build_cli_backend(config_path, None, prefer_running_controller=True)

    assert caught.value.code == expected_code
    runtime_builder.assert_not_called()
    # Verify not settings.paths.data_root.exists() before this scenario is accepted.
    assert not settings.paths.data_root.exists()


def test_build_cli_backend_rejects_running_controller_before_local_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test build cli backend rejects running controller before local
    # composition workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")

    # Keep the held lock contract and validation rules together.
    class HeldLock:
        def __init__(self, path: Path) -> None:
            del path

        def acquire(self) -> HeldLock:
            # Execute the held lock acquire workflow in explicit, reviewable steps.
            raise ControllerAlreadyRunningError(
                {"instance_id": "11111111-1111-4111-8111-111111111111"}
            )

    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    # Invoke setattr for controller lock and cli module as a visible test build cli
    # backend rejects running controller before local composition step.
    monkeypatch.setattr(cli_module, "ControllerLock", HeldLock)
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    with pytest.raises(CliUsageError) as caught:
        build_cli_backend(tmp_path / "research.toml", None)

    assert caught.value.code == "CONTROLLER_ALREADY_RUNNING"
    # Invoke assert_not_called as a visible step within the test build cli backend rejects
    # running controller before local composition workflow.
    runtime_builder.assert_not_called()
    assert not settings.paths.data_root.exists()


def test_build_cli_backend_rejects_held_lock_without_valid_owner_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test build cli backend rejects held lock without valid owner identity
    # signature after its explicit inputs.
) -> None:
    # Execute the test build cli backend rejects held lock without valid owner identity
    # workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")

    # Keep the held lock contract and validation rules together.
    class HeldLock:
        def __init__(self, path: Path) -> None:
            del path

        def acquire(self) -> HeldLock:
            raise ControllerAlreadyRunningError({"instance_id": "\nunsafe"})

    # Assemble runtime builder once so the test build cli backend rejects held lock
    # without valid owner identity workflow shares one value.
    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "ControllerLock", HeldLock)
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    with pytest.raises(CliUsageError) as caught:
        # Invoke build_cli_backend for toml and tmp path as a visible test build cli
        # backend rejects held lock without valid owner identity step.
        build_cli_backend(tmp_path / "research.toml", None, prefer_running_controller=True)

    assert caught.value.code == "CONTROLLER_IDENTITY_UNAVAILABLE"
    runtime_builder.assert_not_called()


def test_build_cli_backend_requires_a_capability_mapping_before_composition(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test build cli backend requires a
    # capability mapping before composition contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test build cli backend requires a capability mapping before composition
    # workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    build = Mock(side_effect=AssertionError("container must not be composed"))
    monkeypatch.setattr(cli_module, "build_runtime_container", build)

    with pytest.raises(CliUsageError) as caught:
        # Invoke build_cli_backend for toml and tmp path as a visible test build cli
        # backend requires a capability mapping before composition step.
        build_cli_backend(tmp_path / "local.toml", None, require_capabilities=True)

    assert caught.value.code == "CAPABILITY_CONFIG_REQUIRED"
    build.assert_not_called()


def test_build_cli_recovery_backend_uses_only_the_recovery_composition(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test build cli recovery backend uses only
    # the recovery composition contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test build cli recovery backend uses only the recovery composition
    # workflow in explicit, reviewable steps.
    config_path = tmp_path / "recovery.toml"
    settings = _settings(tmp_path / "corrupt-live-state")
    services = cast(RecoveryServices, object())
    recovery_builder = Mock(return_value=services)
    runtime_builder = Mock(side_effect=AssertionError("runtime container must not be composed"))
    # Invoke setattr for load settings and cli module as a visible test build cli recovery
    # backend uses only the recovery composition step.
    monkeypatch.setattr(cli_module, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli_module, "build_recovery_services", recovery_builder)
    monkeypatch.setattr(cli_module, "build_runtime_container", runtime_builder)

    backend = build_cli_recovery_backend(config_path)

    assert isinstance(backend, RecoveryCliBackend)
    # Verify backend.services is services before this scenario is accepted.
    assert backend.services is services
    recovery_builder.assert_called_once_with(settings)
    runtime_builder.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    # Open the failure and expected code payload explicitly for parametrize within test
    # build cli recovery backend maps local failures without leaking details.
    (
        (FileNotFoundError("/private/secret.toml"), "LOCAL_CONFIG_NOT_FOUND"),
        (ConfigError("secret environment name"), "LOCAL_CONFIG_INVALID"),
        (BackupIntegrityError("secret backup path"), "BACKUP_CONFIG_INVALID"),
    ),
    # Complete parametrize only after its failure and expected code inputs are visible in test
    # build cli recovery backend maps local failures without leaking details.
)
def test_build_cli_recovery_backend_maps_local_failures_without_leaking_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    # Keep the expected code input explicit in the test build cli recovery backend maps
    # local failures without leaking details contract.
    expected_code: str,
) -> None:
    # Execute the test build cli recovery backend maps local failures without leaking
    # details workflow in explicit, reviewable steps.
    def fail(_: Path) -> Settings:
        raise failure

    monkeypatch.setattr(cli_module, "load_settings", fail)

    with pytest.raises(CliUsageError) as caught:
        build_cli_recovery_backend(tmp_path / "local.toml")

    # Verify caught.value.code == expected_code before this scenario is accepted.
    assert caught.value.code == expected_code
    assert str(failure) not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    # Open the failure and expected code payload explicitly for parametrize within test
    # build cli backend maps local failures without leaking details.
    (
        (FileNotFoundError("/private/secret.toml"), "LOCAL_CONFIG_NOT_FOUND"),
        (CapabilityConfigError("secret capability value"), "CAPABILITY_CONFIG_INVALID"),
        (ConfigError("secret environment name"), "LOCAL_CONFIG_INVALID"),
        (BackupIntegrityError("secret backup path"), "BACKUP_CONFIG_INVALID"),
        # Complete parametrize only after its failure and expected code inputs are visible in
        # test build cli backend maps local failures without leaking details.
    ),
)
def test_build_cli_backend_maps_local_failures_without_leaking_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Keep the failure input explicit in the test build cli backend maps local failures
    # without leaking details contract.
    failure: Exception,
    expected_code: str,
) -> None:
    # Execute the test build cli backend maps local failures without leaking details
    # workflow in explicit, reviewable steps.
    def fail(_: Path) -> Settings:
        raise failure

    monkeypatch.setattr(cli_module, "load_settings", fail)

    with pytest.raises(CliUsageError) as caught:
        build_cli_backend(tmp_path / "local.toml", None)

    # Verify caught.value.code == expected_code before this scenario is accepted.
    assert caught.value.code == expected_code
    assert str(failure) not in str(caught.value)
    assert caught.value.__context__ is None
