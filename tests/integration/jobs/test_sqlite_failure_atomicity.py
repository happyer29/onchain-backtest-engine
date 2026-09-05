# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import backtest.adapters.catalog.sqlite.job_queue as job_queue_module

# Import job queue at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.job_queue import SQLiteJobQueue
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.errors import ErrorCode, LocalStateUnavailableError
from backtest.application.models import JobType, ResolvedJobSpec

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.use_cases.submit_job import SubmitJob
from backtest.domain.identifiers import ContentDigest
from backtest.interfaces.api import ControlUseCases, create_app

_SAFE_UNAVAILABLE_MESSAGE = "The local operational state database is temporarily unavailable."


# Define resolved spec as one focused operation with an explicit boundary.
def _resolved_spec(*, padding_bytes: int = 0) -> ResolvedJobSpec:
    # Execute the resolved spec workflow in explicit, reviewable steps.
    payload = json.dumps(
        {"padding": "x" * padding_bytes},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    # Assemble payload digest once so the resolved spec workflow shares one value.
    payload_digest = ContentDigest(hashlib.sha256(payload).hexdigest())
    spec_id = ContentDigest(
        resolved_job_spec_hex(
            spec_version=1,
            job_type=JobType.COMPILE_REPLAY.value,
            # Pass payload digest hex explicitly so resolved_job_spec_hex receives a
            # reviewable value and compile replay input in resolved spec.
            payload_digest_hex=payload_digest.hex,
            input_artifact_hexes=(),
        )
    )
    return ResolvedJobSpec(
        # Pass spec version explicitly so ResolvedJobSpec receives a reviewable compile
        # replay and spec id input in resolved spec.
        spec_version=1,
        spec_id=spec_id,
        job_type=JobType.COMPILE_REPLAY,
        canonical_payload=payload,
        payload_digest=payload_digest,
        # Complete ResolvedJobSpec only after its compile replay and spec id inputs are
        # visible in resolved spec.
    )


def _compile_replay_command(*, compiler_version: str = "numpy-mmap-v1") -> dict[str, object]:
    # Execute the compile replay command workflow in explicit, reviewable steps.
    return {
        "job_type": "COMPILE_REPLAY",
        "payload": {
            "compiler_version": compiler_version,
            "schema": "backtest.compile-replay-job/v1",
            # Include snapshot id in the completed compile replay command result.
            "snapshot_id": "1" * 64,
        },
    }


def _api_client(queue: SQLiteJobQueue) -> TestClient:
    # Execute the api client workflow in explicit, reviewable steps.
    unused = Mock()
    use_cases = ControlUseCases(
        inspect_source=unused,
        plan_dataset=unused,
        submit_job=SubmitJob(queue),
        # Pass cancel job explicitly so ControlUseCases receives a reviewable test and
        # reference python input in api client.
        cancel_job=unused,
        get_job=unused,
        list_jobs=unused,
        profile="test",
        default_run_physical_settings=RunPhysicalSettings(
            # Pass backend explicitly so RunPhysicalSettings receives a reviewable
            # reference python and run backend input in api client.
            backend=RunBackend.REFERENCE_PYTHON,
            reader_batch_rows=65_536,
            reader_readahead=1,
            output_buffer_rows=8_192,
            threads=1,
            # Complete RunPhysicalSettings only after its reference python and run backend
            # inputs are visible in api client.
        ),
    )
    return TestClient(
        create_app(
            use_cases,
            # Include control plane id in the completed api client result.
            control_plane_id=ContentDigest("f" * 64),
            allowed_hosts=("testserver",),
            enforce_session=False,
        )
    )


# Define assert empty and healthy as one focused operation with an explicit boundary.
def _assert_empty_and_healthy(database: Path) -> None:
    # Execute the assert empty and healthy workflow in explicit, reviewable steps.
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected assert empty and healthy operation before explicit failure
        # handling.
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM job_events").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert tuple(str(row[0]).lower() for row in connection.execute("PRAGMA quick_check")) == (
            "ok",
            # Verify the ok, lower and row relationship before this scenario is accepted.
        )
    finally:
        connection.close()


def _constrain_each_queue_connection_to_current_pages(
    monkeypatch: pytest.MonkeyPatch,
    # Close the constrain each queue connection to current pages signature after its explicit
    # inputs.
) -> None:
    # Execute the constrain each queue connection to current pages workflow in explicit,
    # reviewable steps.
    def constrained_connect(
        path: Path,
        *,
        busy_timeout_seconds: float,
    ) -> sqlite3.Connection:
        # Execute the constrained connect workflow in explicit, reviewable steps.
        connection = connect(path, busy_timeout_seconds=busy_timeout_seconds)
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        applied = connection.execute(f"PRAGMA max_page_count = {page_count}").fetchone()
        assert applied is not None and int(applied[0]) == page_count
        return connection

    # Invoke setattr for connect and job queue module as a visible constrain each queue
    # connection to current pages step.
    monkeypatch.setattr(job_queue_module, "connect", constrained_connect)


def _assert_safe_unavailable_response(response_text: str) -> None:
    # Execute the assert safe unavailable response workflow in explicit, reviewable steps.
    lowered = response_text.lower()
    assert "database is locked" not in lowered
    assert "database or disk is full" not in lowered
    assert "sqlite3" not in lowered
    assert "traceback" not in lowered
    # Verify '.sqlite' not in lowered before this scenario is accepted.
    assert ".sqlite" not in lowered


def test_busy_queue_write_is_bounded_atomic_and_retryable(tmp_path: Path) -> None:
    # Execute the test busy queue write is bounded atomic and retryable workflow in
    # explicit, reviewable steps.
    database = tmp_path / "queue.sqlite"
    queue = SQLiteJobQueue(database, busy_timeout_seconds=0.02)
    holder = connect(database, busy_timeout_seconds=1.0)
    holder.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    # Keep expected failures inside the test busy queue write is bounded atomic and
    # retryable error boundary.
    try:
        # Perform the protected test busy queue write is bounded atomic and retryable
        # operation before explicit failure handling.
        with pytest.raises(LocalStateUnavailableError) as raised:
            queue.submit(_resolved_spec(), "busy-direct")
    finally:
        # Handle the cleanup path after the protected test busy queue write is bounded
        # atomic and retryable operation.
        holder.rollback()
        holder.close()

    assert time.monotonic() - started < 1.0
    assert raised.value.code is ErrorCode.LOCAL_STATE_UNAVAILABLE
    assert raised.value.safe_message == _SAFE_UNAVAILABLE_MESSAGE
    # Invoke _assert_empty_and_healthy for database as a visible test busy queue write is
    # bounded atomic and retryable step.
    _assert_empty_and_healthy(database)
    assert queue.submit(_resolved_spec(), "busy-direct").state.value == "QUEUED"


def test_disk_full_queue_write_rolls_back_all_rows_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test disk full queue write rolls back all rows and can retry signature after
    # its explicit inputs.
) -> None:
    # Execute the test disk full queue write rolls back all rows and can retry workflow in
    # explicit, reviewable steps.
    database = tmp_path / "queue.sqlite"
    queue = SQLiteJobQueue(database, busy_timeout_seconds=0.05)

    with monkeypatch.context() as fault:
        # Keep context and monkeypatch active only for the bounded test disk full queue
        # write rolls back all rows and can retry operation.
        _constrain_each_queue_connection_to_current_pages(fault)
        with pytest.raises(LocalStateUnavailableError) as raised:
            queue.submit(_resolved_spec(padding_bytes=1_000_000), "full-direct")

    assert raised.value.code is ErrorCode.LOCAL_STATE_UNAVAILABLE
    assert raised.value.safe_message == _SAFE_UNAVAILABLE_MESSAGE
    # Invoke _assert_empty_and_healthy for database as a visible test disk full queue
    # write rolls back all rows and can retry step.
    _assert_empty_and_healthy(database)
    assert queue.submit(_resolved_spec(), "full-direct").state.value == "QUEUED"


def test_busy_api_write_returns_stable_503_without_partial_job(tmp_path: Path) -> None:
    # Execute the test busy api write returns stable 503 without partial job workflow in
    # explicit, reviewable steps.
    database = tmp_path / "queue.sqlite"
    queue = SQLiteJobQueue(database, busy_timeout_seconds=0.02)
    holder = connect(database, busy_timeout_seconds=1.0)
    holder.execute("BEGIN IMMEDIATE")
    try:
        # Perform the protected test busy api write returns stable 503 without partial job
        # operation before explicit failure handling.
        with _api_client(queue) as client:
            # Keep api client and queue active only for the bounded test busy api write
            # returns stable 503 without partial job operation.
            started = time.monotonic()
            response = client.post(
                "/api/v1/jobs",
                headers={"Idempotency-Key": "busy-api"},
                json=_compile_replay_command(),
                # Complete post only after its /api/v1/jobs and idempotency-key inputs are
                # visible in test busy api write returns stable 503 without partial job.
            )
            elapsed = time.monotonic() - started
    finally:
        # Handle the cleanup path after the protected test busy api write returns stable
        # 503 without partial job operation.
        holder.rollback()
        holder.close()

    assert elapsed < 1.0
    assert response.status_code == 503
    assert response.json() == {
        # Keep the code expectation tied to json, code and message in this scenario.
        "code": ErrorCode.LOCAL_STATE_UNAVAILABLE.value,
        "message": _SAFE_UNAVAILABLE_MESSAGE,
    }
    _assert_safe_unavailable_response(response.text)
    _assert_empty_and_healthy(database)
    # Acquire api client and queue at an explicit test busy api write returns stable 503
    # without partial job context boundary so cleanup remains scoped.
    with _api_client(queue) as client:
        # Keep api client and queue active only for the bounded test busy api write
        # returns stable 503 without partial job operation.
        retry = client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": "busy-api"},
            json=_compile_replay_command(),
        )
    # Verify retry.status_code == 202 before this scenario is accepted.
    assert retry.status_code == 202


def test_disk_full_api_write_returns_stable_503_without_partial_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test disk full api write returns stable 503 without partial job workflow
    # in explicit, reviewable steps.
    database = tmp_path / "queue.sqlite"
    queue = SQLiteJobQueue(database, busy_timeout_seconds=0.05)
    command = _compile_replay_command(compiler_version="v" + "x" * 1_000_000)

    with monkeypatch.context() as fault:
        # Keep context and monkeypatch active only for the bounded test disk full api
        # write returns stable 503 without partial job operation.
        _constrain_each_queue_connection_to_current_pages(fault)
        with _api_client(queue) as client:
            # Keep api client and queue active only for the bounded test disk full api
            # write returns stable 503 without partial job operation.
            response = client.post(
                "/api/v1/jobs",
                headers={"Idempotency-Key": "full-api"},
                json=command,
            )

    # Verify response.status_code == 503 before this scenario is accepted.
    assert response.status_code == 503
    assert response.json() == {
        "code": ErrorCode.LOCAL_STATE_UNAVAILABLE.value,
        "message": _SAFE_UNAVAILABLE_MESSAGE,
    }
    # Invoke _assert_safe_unavailable_response for text and response as a visible test
    # disk full api write returns stable 503 without partial job step.
    _assert_safe_unavailable_response(response.text)
    _assert_empty_and_healthy(database)
    with _api_client(queue) as client:
        # Keep api client and queue active only for the bounded test disk full api write
        # returns stable 503 without partial job operation.
        retry = client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": "full-api"},
            json=_compile_replay_command(),
        )
    # Verify retry.status_code == 202 before this scenario is accepted.
    assert retry.status_code == 202
