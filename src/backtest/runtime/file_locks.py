"""Small POSIX file-lock primitives used by the single-host runtime.

The lock file is never deleted on release.  Removing a lock file while another
process has it open can create two independent inodes and therefore two lock
domains.  The bytes stored in the file are diagnostic only; ``flock`` is the
authority.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time

# Import enum at the visible module dependency boundary.
from enum import StrEnum
from pathlib import Path
from types import TracebackType


class LockMode(StrEnum):
    """Supported advisory-lock modes."""

    SHARED = "shared"
    EXCLUSIVE = "exclusive"


class FileLockError(RuntimeError):
    """Base class for lock failures."""


class FileLockAlreadyHeldError(FileLockError):
    """Raised when the same :class:`FileLock` object is acquired twice."""


class LockUnavailableError(FileLockError):
    """Raised when a lock cannot be acquired before its timeout."""


class FileLock:
    """A process-safe advisory lock backed by ``fcntl.flock``.

    The platform envelope in the architecture is macOS and Linux, so a POSIX
    primitive is preferable to a dependency with subtly different semantics.
    ``timeout=None`` waits indefinitely; ``timeout=0`` is fail-fast.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        mode: LockMode = LockMode.EXCLUSIVE,
        # Keep the timeout input explicit in the init contract.
        timeout: float | None = None,
        poll_interval: float = 0.05,
    ) -> None:
        # Execute the file lock init workflow in explicit, reviewable steps.
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.path = Path(path)
        # Assemble self mode once so the file lock init workflow shares one value.
        self.mode = mode
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: int | None = None

    @property
    # Define file lock locked as one focused operation with an explicit boundary.
    def locked(self) -> bool:
        return self._fd is not None

    def fileno(self) -> int:
        """Return the descriptor while the lock is held."""

        if self._fd is None:
            raise FileLockError("lock is not held")
        return self._fd

    def acquire(self) -> FileLock:
        # Execute the file lock acquire workflow in explicit, reviewable steps.
        if self._fd is not None:
            raise FileLockAlreadyHeldError(f"lock object is already held: {self.path}")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            # Assemble flags once so the file lock acquire workflow shares one value.
            flags |= os.O_CLOEXEC
        fd = os.open(self.path, flags, 0o600)
        operation = fcntl.LOCK_SH if self.mode is LockMode.SHARED else fcntl.LOCK_EX
        try:
            # Perform the protected file lock acquire operation before explicit failure
            # handling.
            if self.timeout is None:
                # Handle the file lock acquire self.timeout is None branch as a distinct
                # logical block.
                while True:
                    # Keep the True loop body bounded within file lock acquire.
                    try:
                        # Perform the protected file lock acquire operation before
                        # explicit failure handling.
                        fcntl.flock(fd, operation)
                        break
                    except OSError as exc:
                        # Translate the OSError failure through the file lock acquire
                        # boundary.
                        if exc.errno != errno.EINTR:
                            raise
            else:
                # Handle the file lock acquire complement of self.timeout is None
                # explicitly.
                deadline = time.monotonic() + self.timeout
                while True:
                    # Keep the True loop body bounded within file lock acquire.
                    try:
                        # Perform the protected file lock acquire operation before
                        # explicit failure handling.
                        fcntl.flock(fd, operation | fcntl.LOCK_NB)
                        break
                    except BlockingIOError as exc:
                        # Translate the BlockingIOError failure through the file lock
                        # acquire boundary.
                        if time.monotonic() >= deadline:
                            # Handle the file lock acquire time.monotonic() >= deadline
                            # branch as a distinct logical block.
                            raise LockUnavailableError(
                                f"lock is held by another process: {self.path}"
                            ) from exc
                        remaining = deadline - time.monotonic()
                        time.sleep(min(self.poll_interval, max(0.0, remaining)))
                    # Translate oserror through the file lock acquire boundary without
                    # hiding other errors.
                    except OSError as exc:
                        # Translate the OSError failure through the file lock acquire
                        # boundary.
                        if exc.errno == errno.EINTR:
                            continue
                        if exc.errno not in (errno.EACCES, errno.EAGAIN):
                            raise
                        if time.monotonic() >= deadline:
                            # Handle the file lock acquire time.monotonic() >= deadline
                            # branch as a distinct logical block.
                            raise LockUnavailableError(
                                f"lock is held by another process: {self.path}"
                            ) from exc
                        remaining = deadline - time.monotonic()
                        time.sleep(min(self.poll_interval, max(0.0, remaining)))
        # Translate base exception through the file lock acquire boundary without hiding
        # other errors.
        except BaseException:
            # Translate the BaseException failure through the file lock acquire boundary.
            os.close(fd)
            raise

        self._fd = fd
        return self

    def release(self) -> None:
        # Execute the file lock release workflow in explicit, reviewable steps.
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            # Invoke flock for lock un and fd as a visible file lock release step.
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> FileLock:
        return self.acquire()

    # Define file lock exit as one focused operation with an explicit boundary.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        # Close the exit signature after its explicit inputs.
    ) -> None:
        self.release()
