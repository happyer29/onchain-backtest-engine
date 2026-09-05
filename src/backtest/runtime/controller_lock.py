"""Exclusive controller lock for Direct CLI and ``backtest serve``."""

from __future__ import annotations

import json
import os
import time
import uuid

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from types import TracebackType
from typing import Any

from backtest.runtime.file_locks import FileLock, LockMode, LockUnavailableError


class ControllerAlreadyRunningError(RuntimeError):
    """Raised when another controller owns the local data root."""

    def __init__(self, owner: dict[str, Any] | None = None) -> None:
        # Execute the controller already running error init workflow in explicit,
        # reviewable steps.
        super().__init__("another local controller already owns controller.lock")
        self.owner = owner


class ControllerLock:
    """Fail-fast exclusive lock with non-authoritative owner diagnostics."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        instance_id: str | None = None,
        # Keep the timeout input explicit in the init contract.
        timeout: float = 0.0,
    ) -> None:
        # Execute the controller lock init workflow in explicit, reviewable steps.
        self.path = Path(path)
        self.instance_id = instance_id or str(uuid.uuid4())
        self.started_at_ns = time.time_ns()
        self._lock = FileLock(
            self.path,
            # Pass mode explicitly so FileLock receives a reviewable path and exclusive
            # input in controller lock init.
            mode=LockMode.EXCLUSIVE,
            timeout=timeout,
        )

    @property
    def locked(self) -> bool:
        # Return the completed controller lock locked result without a hidden fallback.
        return self._lock.locked

    def acquire(self) -> ControllerLock:
        # Execute the controller lock acquire workflow in explicit, reviewable steps.
        try:
            self._lock.acquire()
        except LockUnavailableError as exc:
            raise ControllerAlreadyRunningError(self.read_owner(self.path)) from exc

        record = {
            # Keep the instance id component named inside the record contract.
            "instance_id": self.instance_id,
            "pid": os.getpid(),
            "started_at_ns": self.started_at_ns,
            "version": 1,
        }
        # Assemble payload once so the controller lock acquire workflow shares one value.
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fd = self._lock.fileno()
        try:
            # Perform the protected controller lock acquire operation before explicit
            # failure handling.
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            view = memoryview(payload)
            while view:
                # Keep the view loop body bounded within controller lock acquire.
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except BaseException:
            # Translate the BaseException failure through the controller lock acquire
            # boundary.
            self._lock.release()
            raise
        return self

    def release(self) -> None:
        self._lock.release()

    # Apply staticmethod semantics to the following controller lock read owner contract.
    @staticmethod
    def read_owner(path: str | os.PathLike[str]) -> dict[str, Any] | None:
        """Read best-effort diagnostics; the returned bytes do not prove ownership."""

        try:
            # Perform the protected controller lock read owner operation before explicit
            # failure handling.
            raw = Path(path).read_bytes()
            value = json.loads(raw)
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            # Return explicit absence from the controller lock read owner path.
            return None
        return value

    def __enter__(self) -> ControllerLock:
        return self.acquire()

    def __exit__(
        # Keep the remaining exit inputs visible at the controller lock exit boundary.
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Invoke release as a visible step within the controller lock exit workflow.
        self.release()
