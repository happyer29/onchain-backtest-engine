# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import http.client
import importlib.util
import json
import os

# Import socket at the visible module dependency boundary.
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

# Import datetime at the visible module dependency boundary.
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from urllib.parse import quote

import pytest

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    LocalArtifactRepository,
    LocalCompletionReceiptStore,
)

# Import source inspection at the visible module dependency boundary.
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource, LocalArrowCanonicalStore
from backtest.adapters.control import (
    ControlApiProtocolError,
    ControlApiUnavailableError,
    # Include control health so the control dependency remains explicit.
    ControlHealth,
    LocalControlApiClient,
)
from backtest.application.job_commands import ResolvedBacktestJob
from backtest.application.models import AttemptState, JobType

# Import inspect source at the visible module dependency boundary.
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.prepare_dataset import PrepareDataset, PrepareDatasetRequest
from backtest.application.use_cases.run_backtest import RunBacktestRequest
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.cli import RuntimeCliBackend
from backtest.bootstrap.config import load_settings
from backtest.bootstrap.container import build_runtime_container

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ContentDigest, SourceId
from backtest.runtime.host_resources import HostMemoryMeasurement

_SECRET_MARKER = "control-e2e-secret-must-not-leak"
_TERMINAL_STATES = {
    AttemptState.FAILED,
    # Keep the attempt state component named inside the terminal states contract.
    AttemptState.CANCELLED,
    AttemptState.INTERRUPTED,
}


def _reference_fixture_module() -> ModuleType:
    # Execute the reference fixture module workflow in explicit, reviewable steps.
    fixture_path = Path(__file__).parents[1] / "data" / "test_prepare_dataset.py"
    spec = importlib.util.spec_from_file_location(
        "_backtest_real_http_reference_fixture",
        fixture_path,
    )
    # Guard this path with spec is None or spec.loader is None before applying effects.
    if spec is None or spec.loader is None:
        raise RuntimeError("reference integration fixture could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Return the completed reference fixture module result without a hidden fallback.
    return module


_REFERENCE_FIXTURE = _reference_fixture_module()
_source = _REFERENCE_FIXTURE._source
_plan_request = _REFERENCE_FIXTURE._plan_request
_planning_policy = _REFERENCE_FIXTURE._planning_policy
# Bind projector once as an explicit module-level contract.
_projector = _REFERENCE_FIXTURE._projector
_resolved_run_spec = _REFERENCE_FIXTURE._resolved_run_spec


# Keep the http response contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


# Define free loopback port as one focused operation with an explicit boundary.
def _free_loopback_port() -> int:
    # Execute the free loopback port workflow in explicit, reviewable steps.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # Keep socket, af inet and sock stream active only for the bounded free loopback
        # port operation.
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _write_config(
    config_path: Path,
    data_root: Path,
    # Keep the port input explicit in the write config contract.
    port: int,
    *,
    progress_interval_ms: int,
) -> None:
    # Execute the write config workflow in explicit, reviewable steps.
    config_path.write_text(
        "[paths]\n"
        f"data_root = {json.dumps(str(data_root))}\n"
        "[resources]\n"
        "max_aggregate_child_memory_mb = 1024\n"
        # Pass max builder memory mb n explicitly so write_text receives a reviewable
        # [paths] data root = and progress interval ms = input in write config.
        "max_builder_memory_mb = 256\n"
        "builder_peak_private_memory_mb = 512\n"
        "run_peak_private_memory_mb = 512\n"
        "max_parallel_runs = 1\n"
        "tmp_quota_gb = 1\n"
        # Pass max run tmp gb n explicitly so write_text receives a reviewable [paths]
        # data root = and progress interval ms = input in write config.
        "max_run_tmp_gb = 1\n"
        "max_run_output_gb = 1\n"
        "disk_low_watermark_gb = 1\n"
        "disk_emergency_watermark_gb = 1\n"
        "native_threads_per_process = 1\n"
        # Pass memory safety reserve mb n explicitly so write_text receives a reviewable
        # [paths] data root = and progress interval ms = input in write config.
        "memory_safety_reserve_mb = 64\n"
        "page_cache_floor_mb = 64\n"
        "host_staging_output_reserve_mb = 64\n"
        "fixed_shared_overhead_mb = 64\n"
        "memory_breach_samples = 2\n"
        # Pass swap activity samples n explicitly so write_text receives a reviewable
        # [paths] data root = and progress interval ms = input in write config.
        "swap_activity_samples = 3\n"
        "[control]\n"
        'host = "127.0.0.1"\n'
        f"port = {port}\n"
        f"progress_interval_ms = {progress_interval_ms}\n"
        # Pass max request mb n explicitly so write_text receives a reviewable [paths]
        # data root = and progress interval ms = input in write config.
        "max_request_mb = 2\n"
        "secure_cookie = false\n",
        encoding="utf-8",
    )


def _start_server(
    # Keep the config path input explicit in the start server contract.
    config_path: Path,
    port: int,
) -> tuple[subprocess.Popen[str], ControlHealth]:
    # Execute the start server workflow in explicit, reviewable steps.
    environment = dict(os.environ)
    environment["BACKTEST_INDEXER_PASSWORD"] = _SECRET_MARKER
    process = subprocess.Popen(
        (
            sys.executable,
            # Pass m explicitly so Popen receives a reviewable -m and cli input in start
            # server.
            "-m",
            "backtest.bootstrap.cli",
            "serve",
            "--config",
            str(config_path),
            # Complete Popen only after its -m and cli inputs are visible in start server.
        ),
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # Pass text explicitly so Popen receives a reviewable -m and cli input in start
        # server.
        text=True,
    )
    client = LocalControlApiClient("127.0.0.1", port, timeout_seconds=1.0)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        # Keep the time.monotonic() < deadline loop body bounded within start server.
        if process.poll() is not None:
            # Handle the start server process.poll() is not None branch as a distinct
            # logical block.
            output = process.communicate(timeout=1)[0]
            pytest.fail(f"control server exited before health: {output[-2000:]}")
        try:
            health = client.health()
        except (ControlApiProtocolError, ControlApiUnavailableError):
            # Translate the control api protocol error and control api unavailable error
            # failure through the start server boundary.
            time.sleep(0.05)
            continue
        return process, health
    output = _stop_server(process)
    pytest.fail(f"control server did not become healthy: {output[-2000:]}")


# Define stop server as one focused operation with an explicit boundary.
def _stop_server(process: subprocess.Popen[str]) -> str:
    # Execute the stop server workflow in explicit, reviewable steps.
    if process.poll() is None:
        process.terminate()
    try:
        output, _ = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        # Translate the subprocess.TimeoutExpired failure through the stop server
        # boundary.
        process.kill()
        output, _ = process.communicate(timeout=5)
    return output


def _http_request(
    port: int,
    # Keep the method input explicit in the http request contract.
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    # Keep the http response input explicit in the http request contract.
) -> _HttpResponse:
    # Execute the http request workflow in explicit, reviewable steps.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        # Perform the protected http request operation before explicit failure handling.
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read(4 * 1024 * 1024 + 1)
        assert len(payload) <= 4 * 1024 * 1024
        return _HttpResponse(
            # Pass response explicitly so _HttpResponse receives a reviewable status and
            # casefold input in http request.
            response.status,
            {name.casefold(): value for name, value in response.getheaders()},
            payload,
        )
    finally:
        # Invoke close as a visible step within the http request workflow.
        connection.close()


def _assert_safe_error(response: _HttpResponse, *, data_root: Path) -> dict[str, object]:
    # Execute the assert safe error workflow in explicit, reviewable steps.
    assert response.status >= 400
    lowered = response.body.decode("utf-8", errors="replace").casefold()
    for forbidden in (
        _SECRET_MARKER.casefold(),
        str(data_root).casefold(),
        # Traverse traceback, site-packages and casefold explicitly so each assert safe
        # error iteration remains traceable.
        "traceback",
        'file "',
        "site-packages",
        "<script>",
    ):
        # Verify forbidden not in lowered before this scenario is accepted.
        assert forbidden not in lowered
    value = json.loads(response.body)
    assert isinstance(value, dict)
    return value


def _real_http_security_and_static_smoke(port: int, data_root: Path) -> None:
    # Execute the real http security and static smoke workflow in explicit, reviewable
    # steps.
    root = _http_request(port, "GET", "/")
    assert root.status == 200
    assert b'id="root"' in root.body
    assert root.headers["content-security-policy"].startswith("default-src 'none'")
    assert "httponly" in root.headers["set-cookie"].casefold()
    # Verify the casefold, headers and set-cookie relationship before this scenario is
    # accepted.
    assert "samesite=strict" in root.headers["set-cookie"].casefold()
    assert "access-control-allow-origin" not in root.headers
    cookie = root.headers["set-cookie"].partition(";")[0]

    refreshed = _http_request(port, "GET", "/", headers={"Cookie": cookie})
    assert refreshed.status == 200
    # Verify the cookie, partition and headers relationship before this scenario is
    # accepted.
    assert refreshed.headers["set-cookie"].partition(";")[0] == cookie

    # Built entry scripts are external same-origin resources, including the React bootstrap.
    import re

    scripts = re.findall(rb'<script[^>]+src="([^"]+)"', root.body)
    assert scripts
    for path in scripts:
        assert path.startswith(b"/static/")
        assert _http_request(port, "GET", path.decode()).status == 200
    # Original result bookmarks and new SPA routes all share the same session-protected shell.
    for path in ("/sniping-results", "/copy-results", "/runs/" + "a" * 64, "/launch"):
        dashboard = _http_request(port, "GET", path, headers={"Cookie": cookie})
        assert dashboard.status == 200 and dashboard.body == root.body
        assert dashboard.headers["content-security-policy"].startswith("default-src 'none'")
        assert dashboard.headers["cache-control"] == "no-cache"
    # Old handlers cannot be served accidentally through a second static implementation.
    assert _http_request(port, "GET", "/static/app.js").status == 404
    assert _http_request(port, "GET", "/static/copy-results.js").status == 404

    bad_host = _http_request(
        port,
        "GET",
        "/api/v1/health",
        # Pass host explicitly so _http_request receives a reviewable get and
        # /api/v1/health input in real http security and static smoke.
        headers={"Host": "attacker.invalid"},
    )
    assert _assert_safe_error(bad_host, data_root=data_root)["code"] == "INVALID_HOST"

    cross_origin = _http_request(
        port,
        # Pass post explicitly so _http_request receives a reviewable post and
        # /api/v1/jobs input in real http security and static smoke.
        "POST",
        "/api/v1/jobs",
        body=b"{}",
        headers={
            "Content-Type": "application/json",
            # Keep origin named so the post and /api/v1/jobs payload passed to
            # _http_request remains self-describing within real http security and static
            # smoke.
            "Origin": "http://attacker.invalid",
        },
    )
    assert _assert_safe_error(cross_origin, data_root=data_root)["code"] == "FORBIDDEN_ORIGIN"

    missing_csrf = _http_request(
        # Pass port explicitly so _http_request receives a reviewable post and
        # /api/v1/jobs input in real http security and static smoke.
        port,
        "POST",
        "/api/v1/jobs",
        body=b"{}",
        headers={
            # Keep content-type named so the post and /api/v1/jobs payload passed to
            # _http_request remains self-describing within real http security and static
            # smoke.
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    # Verify the invalid session, code and assert safe error relationship before this
    # scenario is accepted.
    assert _assert_safe_error(missing_csrf, data_root=data_root)["code"] == "INVALID_SESSION"

    oversized = _http_request(
        port,
        "POST",
        "/api/v1/jobs",
        # Pass body explicitly so _http_request receives a reviewable post and
        # /api/v1/jobs input in real http security and static smoke.
        body=b"{}",
        headers={
            "Content-Length": str(3 * 1024 * 1024),
            "Content-Type": "application/json",
            "Cookie": cookie,
            # Keep origin named so the post and /api/v1/jobs payload passed to
            # _http_request remains self-describing within real http security and static
            # smoke.
            "Origin": f"http://127.0.0.1:{port}",
            "X-Backtest-CSRF": "1",
        },
    )
    _assert_safe_error(oversized, data_root=data_root)

    # Assemble traversal once so the real http security and static smoke workflow shares
    # one value.
    traversal = _http_request(port, "GET", "/static/%2e%2e/api/app.py")
    _assert_safe_error(traversal, data_root=data_root)
    assert b"create_app" not in traversal.body

    xss_job_id = quote("<script>alert(1)</script>", safe="")
    xss = _http_request(port, "GET", f"/api/v1/jobs/{xss_job_id}")
    # Invoke _assert_safe_error for xss and data root as a visible real http security and
    # static smoke step.
    _assert_safe_error(xss, data_root=data_root)


@pytest.mark.integration
def test_real_uvicorn_durable_http_restart_and_isolated_child_equivalence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test real uvicorn durable http restart and isolated child equivalence
    # signature after its explicit inputs.
) -> None:
    # Execute the test real uvicorn durable http restart and isolated child equivalence
    # workflow in explicit, reviewable steps.
    monkeypatch.setattr(
        "backtest.bootstrap.supervisor.measure_host_memory",
        lambda: HostMemoryMeasurement(16 * 1024**3, 12 * 1024**3, 256 * 1024**2),
    )
    port = _free_loopback_port()
    # Assemble data root once so the test real uvicorn durable http restart and isolated
    # child equivalence workflow shares one value.
    data_root = tmp_path / "var"
    config_path = tmp_path / "real-control.toml"
    _write_config(config_path, data_root, port, progress_interval_ms=60_000)

    source = _source()
    artifacts = LocalArtifactRepository(data_root)
    # Assemble inspection once so the test real uvicorn durable http restart and isolated
    # child equivalence workflow shares one value.
    inspection = StoreSourceInspection(
        InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)),
        artifacts,
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    plan = PlanDataset(
        # Keep the artifacts ArtifactSourceInspectionLoader step visible while building
        # plan.
        ArtifactSourceInspectionLoader(artifacts),
        _planning_policy(),
    ).execute(_plan_request(inspection.artifact.artifact_id))
    build_tools = BuildToolBundleRegistry().pin()
    prepared = PrepareDataset(
        # Pass source explicitly so execute receives a reviewable prepare dataset request
        # and plan input in test real uvicorn durable http restart and isolated child
        # equivalence.
        source,
        _projector(),
        LocalArrowCanonicalStore(
            artifacts,
            memory_limit_mb=256,
            # Pass build tools explicitly so LocalArrowCanonicalStore receives a
            # reviewable artifacts and build tools input in test real uvicorn durable http
            # restart and isolated child equivalence.
            build_tools=build_tools,
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    ).execute(PrepareDatasetRequest(plan))

    settings = load_settings(config_path)
    # Assemble container once so the test real uvicorn durable http restart and isolated
    # child equivalence workflow shares one value.
    container = build_runtime_container(settings, profile=config_path.stem)
    replay = CanonicalParquetReplaySource(
        artifacts,
        prepared.snapshot_id,
        build_tools=build_tools,
        # Complete CanonicalParquetReplaySource only after its snapshot id and artifacts
        # inputs are visible in test real uvicorn durable http restart and isolated child
        # equivalence.
    )
    resolved_spec = _resolved_run_spec(
        prepared,
        replay,
        container.runtime_manifest.runtime_lock_id,
        # Complete _resolved_run_spec only after its runtime lock id and runtime manifest
        # inputs are visible in test real uvicorn durable http restart and isolated child
        # equivalence.
    )
    request = RunBacktestRequest(resolved_spec, ContentDigest("8" * 64))
    command = ResolvedBacktestJob(
        request.resolved_spec,
        request.attempt_nonce,
        # Pass request explicitly so ResolvedBacktestJob receives a reviewable resolved
        # spec and attempt nonce input in test real uvicorn durable http restart and
        # isolated child equivalence.
        request.physical_settings,
    )
    direct = RuntimeCliBackend(container, config_path).run_backtest(request)
    direct_job = container.jobs.list_jobs(limit=10)[0]
    # The common result query must describe the real FirstSwap order without inventing PnL.
    _assert_generic_strategy_results(container, direct)

    server: subprocess.Popen[str] | None = None
    # Keep expected failures inside the test real uvicorn durable http restart and
    # isolated child equivalence error boundary.
    try:
        # Perform the protected test real uvicorn durable http restart and isolated child
        # equivalence operation before explicit failure handling.
        server, first_health = _start_server(config_path, port)
        first_client = LocalControlApiClient("127.0.0.1", port)
        queued = first_client.submit_job(
            SubmitJobRequest(
                spec_version=1,
                # Pass job type explicitly so SubmitJobRequest receives a reviewable real-
                # http-run-equivalence and run backtest input in test real uvicorn durable
                # http restart and isolated child equivalence.
                job_type=JobType.RUN_BACKTEST,
                payload_json=command.canonical_bytes(),
                idempotency_key="real-http-run-equivalence",
            )
        )
        # Verify queued.state is AttemptState.QUEUED before this scenario is accepted.
        assert queued.state is AttemptState.QUEUED
        _stop_server(server)
        server = None

        queued_record = container.jobs.get_job(queued.job_id)
        assert queued_record is not None
        # Verify the state, queued and queued record relationship before this scenario is
        # accepted.
        assert queued_record.state is AttemptState.QUEUED
        assert queued_record.spec == direct_job.spec
        assert queued_record.spec.canonical_payload == direct_job.spec.canonical_payload
        assert queued_record.spec.spec_id == direct_job.spec.spec_id == queued.spec_id

        _write_config(config_path, data_root, port, progress_interval_ms=50)
        # Assemble (server, second health) once so the test real uvicorn durable http
        # restart and isolated child equivalence workflow shares one value.
        server, second_health = _start_server(config_path, port)
        assert second_health.control_plane_id != first_health.control_plane_id

        # This is a new client/session after the submitter disconnected and the server restarted.
        client = LocalControlApiClient("127.0.0.1", port)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            # Keep the time.monotonic() < deadline loop body bounded within test real
            # uvicorn durable http restart and isolated child equivalence.
            status_view = client.get_job(queued.job_id)
            if status_view.state is AttemptState.SUCCEEDED:
                break
            if status_view.state in _TERMINAL_STATES:
                pytest.fail(f"real isolated child ended as {status_view.state.value}")
            # Invoke sleep as a visible step within the test real uvicorn durable http
            # restart and isolated child equivalence workflow.
            time.sleep(0.05)
        else:
            pytest.fail("real HTTP-queued child did not finish before timeout")

        events = client.list_job_events(queued.job_id, limit=1_000)
        event_types = {item.event_type for item in events}
        # Verify the event types, job submitted and attempt claimed relationship before
        # this scenario is accepted.
        assert {
            "JOB_SUBMITTED",
            "ATTEMPT_CLAIMED",
            "ATTEMPT_RUNNING",
            "ATTEMPT_PROGRESS",
            # Keep the attempt succeeded expectation tied to event types, job submitted
            # and attempt claimed in this scenario.
            "ATTEMPT_SUCCEEDED",
        } <= event_types
        progress = tuple(item.progress for item in events if item.progress is not None)
        assert progress
        assert progress[-1] is not None
        # Verify the value, completed and stage relationship before this scenario is
        # accepted.
        assert progress[-1].stage.value == "COMPLETED"
        succeeded = next(item for item in events if item.event_type == "ATTEMPT_SUCCEEDED")
        assert succeeded.attempt_id is not None

        views = client.run_documents(
            logical_run_id=direct.logical_run_id.hex,
            # Pass limit explicitly so run_documents receives a reviewable hex and logical
            # run id input in test real uvicorn durable http restart and isolated child
            # equivalence.
            limit=50,
            offset=0,
        )
        assert len(views) == 2
        assert {item.canonical_result_hash for item in views} == {direct.canonical_result_hash}
        # Verify the audit hash, item and views relationship before this scenario is
        # accepted.
        assert {item.audit_hash for item in views} == {direct.comparison.audit_hash}
        direct_view = next(
            item for item in views if item.run_artifact_id == direct.artifact.artifact_id
        )
        queued_view = next(item for item in views if item is not direct_view)
        # Verify the run artifact id, queued view and direct view relationship before this
        # scenario is accepted.
        assert queued_view.run_artifact_id != direct_view.run_artifact_id
        assert queued_view.execution_attempt_id != direct_view.execution_attempt_id

        details = client.artifact_document(queued_view.run_artifact_id)
        lineage = client.lineage_document(queued_view.run_artifact_id)
        assert details.descriptor.artifact_id == queued_view.run_artifact_id
        # Verify the hex, logical run id and loads relationship before this scenario is
        # accepted.
        assert json.loads(details.manifest_bytes)["logical_run_id"] == direct.logical_run_id.hex
        assert lineage.root_artifact_id == queued_view.run_artifact_id
        assert queued_view.run_artifact_id in {item.artifact_id for item in lineage.artifacts}

        receipt = LocalCompletionReceiptStore(DataRootLayout(data_root)).load(succeeded.attempt_id)
        assert receipt is not None
        # Verify the result artifact id, run artifact id and receipt relationship before
        # this scenario is accepted.
        assert receipt.result_artifact_id == queued_view.run_artifact_id

        delegated = subprocess.run(
            (
                sys.executable,
                "-m",
                # Pass version tag explicitly so run receives a reviewable -m and cli
                # input in test real uvicorn durable http restart and isolated child
                # equivalence.
                "backtest.bootstrap.cli",
                "get-job",
                queued.job_id.value,
                "--config",
                str(config_path),
                # Complete run only after its -m and cli inputs are visible in test real
                # uvicorn durable http restart and isolated child equivalence.
            ),
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
            # Pass timeout explicitly so run receives a reviewable -m and cli input in
            # test real uvicorn durable http restart and isolated child equivalence.
            timeout=10,
        )
        assert delegated.returncode == 0, delegated.stderr
        assert json.loads(delegated.stdout)["state"] == "SUCCEEDED"

        _real_http_security_and_static_smoke(port, data_root)

        # Invoke _stop_server for server as a visible test real uvicorn durable http
        # restart and isolated child equivalence step.
        _stop_server(server)
        server = None
        server, third_health = _start_server(config_path, port)
        assert third_health.control_plane_id != second_health.control_plane_id
        restarted = LocalControlApiClient("127.0.0.1", port)
        # Verify the state, succeeded and attempt state relationship before this scenario
        # is accepted.
        assert restarted.get_job(queued.job_id).state is AttemptState.SUCCEEDED
        assert restarted.list_job_events(queued.job_id, limit=1_000) == events
        assert (
            restarted.run_documents(
                logical_run_id=direct.logical_run_id.hex,
                # Pass limit explicitly so run_documents receives a reviewable hex and
                # logical run id input in test real uvicorn durable http restart and
                # isolated child equivalence.
                limit=50,
                offset=0,
            )
            == views
        )
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        # Handle the cleanup path after the protected test real uvicorn durable http
        # restart and isolated child equivalence operation.
        if server is not None:
            _stop_server(server)


def _assert_generic_strategy_results(container, result):
    """Exercise common presentation against a genuinely published FirstSwap artifact."""
    queries = container.control.query_strategy_results
    assert queries is not None
    dashboard = queries.dashboard(result.artifact.artifact_id, limit=1)
    assert dashboard.summary.family == "FIRST_SWAP"
    # A filled generic entry is an order outcome, without an invented exit or valuation policy.
    assert len(dashboard.entries.items) == 1
    assert dashboard.entries.items[0].status == "FILLED"
    assert dashboard.entries.items[0].signal_event_id is None
    assert dashboard.entries.items[0].details["fills"]
    assert dashboard.entries.items[0].asset_id is not None
    assert dashboard.entries.items[0].economic_pnl_atomic is None
    metrics = {item.key: item for item in dashboard.summary.metrics}
    assert metrics["economic_pnl_atomic"].availability == "NOT_APPLICABLE"
    # The bounded audit reduction reconciles the same actual order count.
    analytics = queries.analytics(result.artifact.artifact_id)
    assert analytics.entry_count == 1
    outcomes = next(item for item in analytics.distributions if item.key == "entry_outcomes")
    assert outcomes.items == (("FILLED", 1),)
