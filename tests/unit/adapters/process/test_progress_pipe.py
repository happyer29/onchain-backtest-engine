# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import os
from pathlib import Path

from backtest.adapters.process.progress_pipe import (
    PROGRESS_FD_ENV,
    # Include fd progress sink so the progress pipe dependency remains explicit.
    FdProgressSink,
    NullProgressSink,
    create_progress_pipe,
    progress_sink_from_environment,
)

# Import models at the visible module dependency boundary.
from backtest.application.models import ProgressEvent, ProgressLevel, ProgressStage
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AttemptId


def _event(attempt_id: AttemptId, sequence: int, stage: ProgressStage) -> ProgressEvent:
    # Execute the event workflow in explicit, reviewable steps.
    return ProgressEvent(
        attempt_id=attempt_id,
        sequence=sequence,
        level=ProgressLevel.INFO,
        stage=stage,
        # Complete ProgressEvent only after its info and attempt id inputs are visible in
        # event.
    )


def test_progress_pipe_accepts_only_canonical_allowlisted_monotone_frames() -> None:
    # Execute the test progress pipe accepts only canonical allowlisted monotone frames
    # workflow in explicit, reviewable steps.
    attempt_id = AttemptId("attempt-progress")
    reader, write_descriptor = create_progress_pipe(attempt_id)
    sink = FdProgressSink(write_descriptor)
    sink.publish(_event(attempt_id, 1, ProgressStage.VALIDATING_INPUTS))
    os.write(write_descriptor, b"not-json\n")
    # Invoke write for attempt id and completed units as a visible test progress pipe
    # accepts only canonical allowlisted monotone frames step.
    os.write(
        write_descriptor,
        canonical_json_bytes(
            {
                "attempt_id": "different-attempt",
                # Keep completed units named so the attempt id and completed units payload
                # passed to canonical_json_bytes remains self-describing within test
                # progress pipe accepts only canonical allowlisted monotone frames.
                "completed_units": None,
                "level": "INFO",
                "schema": "backtest.child-progress.v1",
                "sequence": 2,
                "stage": "RUNNING_BACKTEST",
                # Keep total units named so the attempt id and completed units payload
                # passed to canonical_json_bytes remains self-describing within test
                # progress pipe accepts only canonical allowlisted monotone frames.
                "total_units": None,
            }
        )
        + b"\n",
    )
    # Invoke write for write descriptor as a visible test progress pipe accepts only
    # canonical allowlisted monotone frames step.
    os.write(write_descriptor, b"x" * 1_100 + b"\n")
    sink.publish(_event(attempt_id, 1, ProgressStage.RUNNING_BACKTEST))
    sink.publish(_event(attempt_id, 3, ProgressStage.RUNNING_BACKTEST))
    sink.close()

    events, dropped = reader.drain()

    # Verify the sequence, event and events relationship before this scenario is accepted.
    assert tuple(event.sequence for event in events) == (1, 3)
    assert tuple(event.stage for event in events) == (
        ProgressStage.VALIDATING_INPUTS,
        ProgressStage.RUNNING_BACKTEST,
    )
    # Verify dropped == 4 before this scenario is accepted.
    assert dropped == 4


def test_progress_writer_never_blocks_when_pipe_is_full() -> None:
    # Execute the test progress writer never blocks when pipe is full workflow in
    # explicit, reviewable steps.
    attempt_id = AttemptId("attempt-backpressure")
    reader, write_descriptor = create_progress_pipe(attempt_id)
    try:
        # Perform the protected test progress writer never blocks when pipe is full
        # operation before explicit failure handling.
        while True:
            # Keep the True loop body bounded within test progress writer never blocks
            # when pipe is full.
            try:
                os.write(write_descriptor, b"x" * 512)
            except BlockingIOError:
                break
        FdProgressSink(write_descriptor).publish(
            # Pass event explicitly to publish for running backtest and event.
            _event(attempt_id, 1, ProgressStage.RUNNING_BACKTEST)
        )
    finally:
        # Handle the cleanup path after the protected test progress writer never blocks
        # when pipe is full operation.
        os.close(write_descriptor)
        reader.close()


def test_child_environment_rejects_arbitrary_file_descriptor(tmp_path: Path) -> None:
    # Execute the test child environment rejects arbitrary file descriptor workflow in
    # explicit, reviewable steps.
    target = tmp_path / "must-remain-empty"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    environment = {PROGRESS_FD_ENV: str(descriptor)}
    try:
        # Perform the protected test child environment rejects arbitrary file descriptor
        # operation before explicit failure handling.
        sink = progress_sink_from_environment(environment)
        assert isinstance(sink, NullProgressSink)
        sink.publish(_event(AttemptId("attempt-file"), 1, ProgressStage.RUNNING_BACKTEST))
    finally:
        os.close(descriptor)

    # Verify environment == {} before this scenario is accepted.
    assert environment == {}
    assert target.read_bytes() == b""
