# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import multiprocessing
from pathlib import Path
from queue import Empty

import pytest

# Import controller lock at the visible module dependency boundary.
from backtest.runtime.controller_lock import (
    ControllerAlreadyRunningError,
    ControllerLock,
)
from backtest.runtime.file_locks import FileLock, LockMode, LockUnavailableError


# Define try lock as one focused operation with an explicit boundary.
def _try_lock(path: str, mode: str, result: multiprocessing.Queue[str]) -> None:
    # Execute the try lock workflow in explicit, reviewable steps.
    try:
        # Perform the protected try lock operation before explicit failure handling.
        with FileLock(path, mode=LockMode(mode), timeout=0.0):
            result.put("acquired")
    except LockUnavailableError:
        result.put("unavailable")


def _child_lock_result(path: Path, mode: LockMode) -> str:
    # Execute the child lock result workflow in explicit, reviewable steps.
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=_try_lock, args=(str(path), mode.value, result))
    process.start()
    process.join(timeout=10)
    # Guard this path with process.is_alive() before applying effects.
    if process.is_alive():
        # Handle the child lock result process.is_alive() branch as a distinct logical
        # block.
        process.terminate()
        process.join(timeout=5)
        pytest.fail("child lock probe did not finish")
    assert process.exitcode == 0
    try:
        # Return the completed child lock result result without a hidden fallback.
        return result.get(timeout=2)
    except Empty:
        pytest.fail("child lock probe did not return a result")


@pytest.mark.integration
def test_exclusive_file_lock_blocks_another_process(tmp_path: Path) -> None:
    # Execute the test exclusive file lock blocks another process workflow in explicit,
    # reviewable steps.
    path = tmp_path / "locks" / "writer.lock"

    with FileLock(path, mode=LockMode.EXCLUSIVE):
        assert _child_lock_result(path, LockMode.EXCLUSIVE) == "unavailable"

    assert _child_lock_result(path, LockMode.EXCLUSIVE) == "acquired"


@pytest.mark.integration
# Define test shared file locks coexist but block exclusive as one focused operation with
# an explicit boundary.
def test_shared_file_locks_coexist_but_block_exclusive(tmp_path: Path) -> None:
    # Execute the test shared file locks coexist but block exclusive workflow in explicit,
    # reviewable steps.
    path = tmp_path / "locks" / "publication.lock"

    with FileLock(path, mode=LockMode.SHARED):
        # Keep file lock, path and shared active only for the bounded test shared file
        # locks coexist but block exclusive operation.
        assert _child_lock_result(path, LockMode.SHARED) == "acquired"
        assert _child_lock_result(path, LockMode.EXCLUSIVE) == "unavailable"


@pytest.mark.integration
def test_controller_lock_is_exclusive_and_persists_owner_diagnostics(tmp_path: Path) -> None:
    # Execute the test controller lock is exclusive and persists owner diagnostics
    # workflow in explicit, reviewable steps.
    path = tmp_path / "locks" / "controller.lock"

    with ControllerLock(path, instance_id="controller-a"):
        # Keep controller lock, path and controller-a active only for the bounded test
        # controller lock is exclusive and persists owner diagnostics operation.
        owner = ControllerLock.read_owner(path)
        assert owner is not None
        assert owner["instance_id"] == "controller-a"
        with pytest.raises(ControllerAlreadyRunningError) as raised:
            ControllerLock(path, instance_id="controller-b").acquire()
        # Verify raised.value.owner is not None before this scenario is accepted.
        assert raised.value.owner is not None
        assert raised.value.owner["instance_id"] == "controller-a"

    with ControllerLock(path, instance_id="controller-c"):
        # Keep controller lock, path and controller-c active only for the bounded test
        # controller lock is exclusive and persists owner diagnostics operation.
        owner = ControllerLock.read_owner(path)
        assert owner is not None
        assert owner["instance_id"] == "controller-c"
