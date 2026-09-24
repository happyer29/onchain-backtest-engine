# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import stat
import sys
import time

# Import hashlib at the visible module dependency boundary.
from hashlib import sha256
from pathlib import Path

import pytest

from backtest.adapters.process.local import LocalSubprocessRunner, ProcessSpawnError
from backtest.application.canonical_json import resolved_job_spec_hex

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    AttemptState,
    JobAttempt,
    JobType,
    ProcessHandle,
    # Include process state so the models dependency remains explicit.
    ProcessState,
    ProgressStage,
    ResolvedJobSpec,
)
from backtest.domain.identifiers import AttemptId, ContentDigest, JobId

# Import host resources at the visible module dependency boundary.
from backtest.runtime.host_resources import measure_process_resources


def _attempt(job_type: JobType = JobType.RUN_BACKTEST) -> JobAttempt:
    # Execute the attempt workflow in explicit, reviewable steps.
    payload = b'{"fixture":"subprocess"}'
    digest = ContentDigest(sha256(payload).hexdigest())
    spec = ResolvedJobSpec(
        spec_version=1,
        spec_id=ContentDigest(
            # Keep the resolved job spec hex and value resolved_job_spec_hex step visible
            # while building spec.
            resolved_job_spec_hex(
                spec_version=1,
                job_type=job_type.value,
                payload_digest_hex=digest.hex,
                input_artifact_hexes=(),
                # Complete resolved_job_spec_hex only after its value and hex inputs are
                # visible in attempt.
            )
        ),
        job_type=job_type,
        canonical_payload=payload,
        payload_digest=digest,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in attempt.
    )
    return JobAttempt(
        attempt_id=AttemptId("attempt-subprocess"),
        job_id=JobId("job-subprocess"),
        spec=spec,
        # Pass state explicitly so JobAttempt receives a reviewable attempt-subprocess and
        # job-subprocess input in attempt.
        state=AttemptState.STARTING,
        state_version=1,
    )


def _wait_for_exit(
    runner: LocalSubprocessRunner,
    # Keep the handle input explicit in the wait for exit contract.
    handle: ProcessHandle,
    *,
    timeout: float = 3.0,
) -> int | None:
    # Execute the wait for exit workflow in explicit, reviewable steps.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Keep the time.monotonic() < deadline loop body bounded within wait for exit.
        status = runner.probe(handle)
        if status.state is ProcessState.EXITED:
            return status.exit_code
        time.sleep(0.01)
    raise AssertionError("child process did not exit before test timeout")


# Apply integration semantics to the following test spawn passes small canonical envelope
# and bounded thread environment contract.
@pytest.mark.integration
def test_spawn_passes_small_canonical_envelope_and_bounded_thread_environment(
    tmp_path: Path,
) -> None:
    # Execute the test spawn passes small canonical envelope and bounded thread
    # environment workflow in explicit, reviewable steps.
    output = tmp_path / "observed.json"
    envelopes = tmp_path / "envelopes"
    code = """
import json
import os
import sys

with open(sys.argv[2], encoding="utf-8") as stream:
    envelope = json.load(stream)
names = (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "ARROW_NUM_THREADS",
    "BACKTEST_DUCKDB_THREADS", "BACKTEST_ONNX_INTRA_OP_THREADS",
    "BACKTEST_ONNX_INTER_OP_THREADS", "PYTHONHASHSEED",
)
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({
        "envelope": envelope,
        "env": {name: os.environ[name] for name in names},
        "pid": os.getpid(),
        "session_id": os.getsid(0),
    }, stream)
"""
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", code, str(output)),
        # Pass working directory explicitly so LocalSubprocessRunner receives a reviewable
        # -c and executable input in test spawn passes small canonical envelope and
        # bounded thread environment.
        working_directory=tmp_path,
        envelope_directory=envelopes,
    )

    handle = runner.spawn(_attempt(), native_threads=2)

    assert _wait_for_exit(runner, handle) == 0
    # Assemble observed once so the test spawn passes small canonical envelope and bounded
    # thread environment workflow shares one value.
    observed = json.loads(output.read_text())
    assert observed["envelope"]["schema"] == "backtest.local-job-envelope.v1"
    assert observed["envelope"]["attempt_id"] == "attempt-subprocess"
    assert observed["envelope"]["payload"] == {"fixture": "subprocess"}
    assert set(observed["env"].values()) == {"0", "2"}
    # Verify the pythonhashseed, observed and env relationship before this scenario is
    # accepted.
    assert observed["env"]["PYTHONHASHSEED"] == "0"
    assert observed["session_id"] == observed["pid"]
    assert tuple(envelopes.iterdir()) == ()


# Source preparation and local consumption have different inherited-secret permissions.
@pytest.mark.integration
@pytest.mark.parametrize(
    "preparation_type,execution_type",
    [
        # Both bounded source workflows receive secrets; local consumers never do.
        (JobType.PREPARE_DATASET, JobType.RUN_BACKTEST),
        (JobType.PREPARE_RESEARCH, JobType.ANALYZE_WALLETS),
    ],
)
def test_only_prepare_child_receives_configured_source_secret(
    # Keep the tmp path input explicit in the test only prepare child receives configured
    # source secret contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preparation_type: JobType,
    execution_type: JobType,
) -> None:
    # Execute the test only prepare child receives configured source secret workflow in
    # explicit, reviewable steps.
    output = tmp_path / "observed.json"
    secret_ref = "TEST_INDEXER_SECRET"
    secret = "must-not-reach-execution"
    monkeypatch.setenv(secret_ref, secret)
    code = """
import json
import os
import sys

with open(sys.argv[2], encoding="utf-8") as stream:
    envelope_text = stream.read()
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({
        "secret": os.environ.get("TEST_INDEXER_SECRET"),
        "secret_in_envelope": "must-not-reach-execution" in envelope_text,
    }, stream)
"""
    # Assemble runner once so the test only prepare child receives configured source
    # secret workflow shares one value.
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", code, str(output)),
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
        source_secret_refs=(secret_ref,),
        # Complete LocalSubprocessRunner only after its -c and envelopes inputs are visible in
        # test only prepare child receives configured source secret.
    )

    run_handle = runner.spawn(_attempt(execution_type), native_threads=1)
    assert _wait_for_exit(runner, run_handle) == 0
    observed = json.loads(output.read_text())
    assert observed == {"secret": None, "secret_in_envelope": False}

    # Assemble prepare handle once so the test only prepare child receives configured
    # source secret workflow shares one value.
    prepare_handle = runner.spawn(_attempt(preparation_type), native_threads=1)
    assert _wait_for_exit(runner, prepare_handle) == 0
    observed = json.loads(output.read_text())
    assert observed == {"secret": secret, "secret_in_envelope": False}


@pytest.mark.integration
# Define test envelope is owner only while child is running as one focused operation with
# an explicit boundary.
def test_envelope_is_owner_only_while_child_is_running(tmp_path: Path) -> None:
    # Execute the test envelope is owner only while child is running workflow in explicit,
    # reviewable steps.
    envelopes = tmp_path / "envelopes"
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", "import time; time.sleep(10)"),
        working_directory=tmp_path,
        envelope_directory=envelopes,
        # Complete LocalSubprocessRunner only after its -c and sleep(10) inputs are visible in
        # test envelope is owner only while child is running.
    )

    handle = runner.spawn(_attempt(), native_threads=1)
    envelope = next(envelopes.iterdir())
    try:
        assert stat.S_IMODE(envelope.stat().st_mode) == 0o600
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        runner.terminate(handle, grace_seconds=0.0)

    assert runner.probe(handle).state is ProcessState.EXITED
    assert tuple(envelopes.iterdir()) == ()


@pytest.mark.integration
# Define test terminate escalates from sigterm to sigkill as one focused operation with an
# explicit boundary.
def test_terminate_escalates_from_sigterm_to_sigkill(tmp_path: Path) -> None:
    # Execute the test terminate escalates from sigterm to sigkill workflow in explicit,
    # reviewable steps.
    runner = LocalSubprocessRunner(
        (
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)",
            # Complete LocalSubprocessRunner only after its -c and envelopes inputs are
            # visible in test terminate escalates from sigterm to sigkill.
        ),
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
    )
    handle = runner.spawn(_attempt(), native_threads=1)
    # Invoke sleep as a visible step within the test terminate escalates from sigterm to
    # sigkill workflow.
    time.sleep(0.05)

    runner.terminate(handle, grace_seconds=0.05)

    assert runner.probe(handle).state is ProcessState.EXITED


@pytest.mark.integration
def test_mismatched_start_token_never_signals_a_live_pid(tmp_path: Path) -> None:
    # Execute the test mismatched start token never signals a live pid workflow in
    # explicit, reviewable steps.
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", "import time; time.sleep(10)"),
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
    )
    # Assemble handle once so the test mismatched start token never signals a live pid
    # workflow shares one value.
    handle = runner.spawn(_attempt(), native_threads=1)

    runner.terminate(ProcessHandle(handle.process_id, "different-start-token"), 0.0)

    assert runner.probe(handle).state is ProcessState.RUNNING
    runner.terminate(handle, 0.0)


@pytest.mark.integration
# Define test new runner instance can reconcile exact persisted process identity as one
# focused operation with an explicit boundary.
def test_new_runner_instance_can_reconcile_exact_persisted_process_identity(
    tmp_path: Path,
) -> None:
    # Execute the test new runner instance can reconcile exact persisted process identity
    # workflow in explicit, reviewable steps.
    envelopes = tmp_path / "envelopes"
    command = (sys.executable, "-c", "import time; time.sleep(10)")
    original = LocalSubprocessRunner(
        command,
        working_directory=tmp_path,
        # Pass envelope directory explicitly so LocalSubprocessRunner receives a
        # reviewable command and tmp path input in test new runner instance can reconcile
        # exact persisted process identity.
        envelope_directory=envelopes,
    )
    handle = original.spawn(_attempt(), native_threads=1)
    restarted = LocalSubprocessRunner(
        command,
        # Pass working directory explicitly so LocalSubprocessRunner receives a reviewable
        # command and tmp path input in test new runner instance can reconcile exact
        # persisted process identity.
        working_directory=tmp_path,
        envelope_directory=envelopes,
    )

    assert restarted.probe(handle).state is ProcessState.RUNNING
    restarted.terminate(handle, 0.0)
    # Invoke cleanup_launch for attempt id and attempt as a visible test new runner
    # instance can reconcile exact persisted process identity step.
    restarted.cleanup_launch(_attempt().attempt_id)

    assert restarted.probe(handle).state is ProcessState.EXITED
    assert original.probe(handle).state is ProcessState.EXITED
    assert tuple(envelopes.iterdir()) == ()


@pytest.mark.integration
# Define test spawn failure removes unpublished envelope as one focused operation with an
# explicit boundary.
def test_spawn_failure_removes_unpublished_envelope(tmp_path: Path) -> None:
    # Execute the test spawn failure removes unpublished envelope workflow in explicit,
    # reviewable steps.
    envelopes = tmp_path / "envelopes"
    runner = LocalSubprocessRunner(
        (str(tmp_path / "missing-worker"),),
        working_directory=tmp_path,
        envelope_directory=envelopes,
        # Complete LocalSubprocessRunner only after its missing-worker and str inputs are
        # visible in test spawn failure removes unpublished envelope.
    )

    with pytest.raises(ProcessSpawnError):
        runner.spawn(_attempt(), native_threads=1)

    assert tuple(envelopes.iterdir()) == ()


@pytest.mark.integration
# Define test probe reports child rss swap faults and attempt tmp growth as one focused
# operation with an explicit boundary.
def test_probe_reports_child_rss_swap_faults_and_attempt_tmp_growth(tmp_path: Path) -> None:
    # Execute the test probe reports child rss swap faults and attempt tmp growth workflow
    # in explicit, reviewable steps.
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    ready = tmp_path / "ready"
    code = """
import pathlib
import sys
import time

root = pathlib.Path(sys.argv[1])
(root / "payload.bin").write_bytes(b"x" * 4096)
pathlib.Path(sys.argv[2]).write_text("ready", encoding="ascii")
time.sleep(10)
"""
    runner = LocalSubprocessRunner(
        # Keep the temporary str step visible while building runner.
        (sys.executable, "-c", code, str(temporary), str(ready)),
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
        temporary_roots=(temporary,),
    )
    # Assemble handle once so the test probe reports child rss swap faults and attempt tmp
    # growth workflow shares one value.
    handle = runner.spawn(_attempt(), native_threads=1)
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        # Perform the protected test probe reports child rss swap faults and attempt tmp
        # growth operation before explicit failure handling.
        status = runner.probe(handle)
        assert status.state is ProcessState.RUNNING
        assert status.private_rss_bytes is not None and status.private_rss_bytes > 0
        assert status.total_rss_bytes is not None
        assert status.total_rss_bytes >= status.private_rss_bytes
        # Verify the child swap bytes and status relationship before this scenario is
        # accepted.
        assert status.child_swap_bytes is not None and status.child_swap_bytes >= 0
        assert status.major_page_faults is not None and status.major_page_faults >= 0
        assert status.temporary_disk_bytes == 4096
    finally:
        runner.terminate(handle, 0.0)


# Apply integration semantics to the following test probe aggregates attempt process group
# descendants contract.
@pytest.mark.integration
def test_probe_aggregates_attempt_process_group_descendants(tmp_path: Path) -> None:
    # Execute the test probe aggregates attempt process group descendants workflow in
    # explicit, reviewable steps.
    ready = tmp_path / "grandchild-ready"
    grandchild_code = """
import pathlib
import sys
import time

allocation = bytearray(24 * 1024 * 1024)
allocation[0] = 1
pathlib.Path(sys.argv[1]).write_text("ready", encoding="ascii")
time.sleep(10)
"""
    parent_code = """
import subprocess
import sys
import time

subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
time.sleep(10)
"""
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", parent_code, grandchild_code, str(ready)),
        # Pass working directory explicitly so LocalSubprocessRunner receives a reviewable
        # -c and envelopes input in test probe aggregates attempt process group
        # descendants.
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
    )
    handle = runner.spawn(_attempt(), native_threads=1)
    deadline = time.monotonic() + 3
    # Repeat the test probe aggregates attempt process group descendants step only while
    # deadline, exists and monotonic remains true.
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        # Perform the protected test probe aggregates attempt process group descendants
        # operation before explicit failure handling.
        leader = measure_process_resources(handle.process_id)
        status = runner.probe(handle)

        assert ready.exists()
        assert leader is not None
        assert status.private_rss_bytes is not None
        # Verify the private rss bytes, status and leader relationship before this
        # scenario is accepted.
        assert status.private_rss_bytes > leader.private_rss_bytes
    finally:
        runner.terminate(handle, 0.0)


@pytest.mark.integration
def test_real_child_progress_pipe_is_drained_and_cleaned_on_exit(tmp_path: Path) -> None:
    # Execute the test real child progress pipe is drained and cleaned on exit workflow in
    # explicit, reviewable steps.
    output = tmp_path / "progress-environment.json"
    code = """
import json
import os
import sys

from backtest.adapters.process.progress_pipe import PROGRESS_FD_ENV, progress_sink_from_environment
from backtest.application.models import ProgressEvent, ProgressLevel, ProgressStage
from backtest.domain.identifiers import AttemptId

sink = progress_sink_from_environment()
attempt_id = AttemptId("attempt-subprocess")
sink.publish(ProgressEvent(attempt_id, 1, ProgressLevel.INFO, ProgressStage.VALIDATING_INPUTS))
sink.publish(ProgressEvent(attempt_id, 2, ProgressLevel.INFO, ProgressStage.RUNNING_BACKTEST))
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({"progress_fd_visible": PROGRESS_FD_ENV in os.environ}, stream)
"""
    runner = LocalSubprocessRunner(
        (sys.executable, "-c", code, str(output)),
        working_directory=tmp_path,
        # Pass envelope directory explicitly so LocalSubprocessRunner receives a
        # reviewable -c and envelopes input in test real child progress pipe is drained
        # and cleaned on exit.
        envelope_directory=tmp_path / "envelopes",
    )
    handle = runner.spawn(_attempt(), native_threads=1)
    observed = []
    deadline = time.monotonic() + 3
    # Repeat the test real child progress pipe is drained and cleaned on exit step only
    # while time.monotonic() < deadline remains true.
    while time.monotonic() < deadline:
        # Keep the time.monotonic() < deadline loop body bounded within test real child
        # progress pipe is drained and cleaned on exit.
        status = runner.probe(handle)
        observed.extend(status.progress_events)
        if status.state is ProcessState.EXITED:
            # Handle the test real child progress pipe is drained and cleaned on exit
            # status.state is ProcessState.EXITED branch as a distinct logical block.
            assert status.exit_code == 0
            break
        time.sleep(0.01)
    else:
        raise AssertionError("progress child did not exit before timeout")

    # Verify the validating inputs, running backtest and stage relationship before this
    # scenario is accepted.
    assert tuple(event.stage for event in observed) == (
        ProgressStage.VALIDATING_INPUTS,
        ProgressStage.RUNNING_BACKTEST,
    )
    assert json.loads(output.read_text()) == {"progress_fd_visible": False}
    # Verify the iterdir, tmp path and envelopes relationship before this scenario is
    # accepted.
    assert tuple((tmp_path / "envelopes").iterdir()) == ()
    assert runner.probe(handle).progress_events == ()
