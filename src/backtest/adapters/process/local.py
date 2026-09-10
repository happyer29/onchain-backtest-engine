"""Spawn-safe local child process runner with PID-reuse protection."""

from __future__ import annotations

import ctypes
import json
import os
import signal

# Import subprocess at the visible module dependency boundary.
import subprocess
import sys
import time
import uuid
from contextlib import suppress

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

from backtest.adapters.process.progress_pipe import (
    # Include progress pipe reader so the progress pipe dependency remains explicit.
    ProgressPipeReader,
    child_progress_environment,
    create_progress_pipe,
)
from backtest.application.models import (
    # Include job attempt so the models dependency remains explicit.
    JobAttempt,
    JobType,
    ProcessHandle,
    ProcessState,
    ProcessStatus,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.processes import ProcessIdentityError, ProcessSpawnError
from backtest.domain.identifiers import AttemptId
from backtest.runtime.host_resources import (
    directory_tree_bytes,
    # Include measure host swap so the host resources dependency remains explicit.
    measure_host_swap,
    measure_process_group_resources,
)
from backtest.runtime.thread_limits import apply_child_process_determinism


# Keep the owned process contract and validation rules together.
@dataclass(slots=True)
class _OwnedProcess:
    process: subprocess.Popen[bytes]
    start_token: str
    envelope_path: Path
    # Declare temporary baseline bytes explicitly in the owned process contract.
    temporary_baseline_bytes: int | None
    progress: ProgressPipeReader


class _ProcBsdInfo(ctypes.Structure):
    """Darwin ``proc_bsdinfo`` layout used only for PID start identity."""

    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        # Keep the ppid component named inside the fields contract.
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        # Keep the svuid component named inside the fields contract.
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        # Keep the nfiles component named inside the fields contract.
        ("nfiles", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        # Keep the nice component named inside the fields contract.
        ("nice", ctypes.c_int32),
        ("start_tvsec", ctypes.c_uint64),
        ("start_tvusec", ctypes.c_uint64),
    ]


class LocalSubprocessRunner:
    """Run one attempt in a new OS session without shell interpretation.

    ``command`` and both directories are trusted composition-root settings.
    The queued/API payload can neither replace the executable nor choose a
    filesystem path.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        working_directory: Path,
        # Keep the envelope directory input explicit in the init contract.
        envelope_directory: Path,
        source_secret_refs: tuple[str, ...] = (),
        temporary_roots: tuple[Path, ...] = (),
    ) -> None:
        # Execute the local subprocess runner init workflow in explicit, reviewable steps.
        if not command:
            raise ValueError("worker command must not be empty")
        if any(not item or "\x00" in item for item in command):
            raise ValueError("worker command arguments must be non-empty")
        if any(
            # Keep item visible while evaluating the item, source secret refs and strip
            # guard.
            not item or item != item.strip() or "\x00" in item or "=" in item
            for item in source_secret_refs
        ):
            raise ValueError("source secret references must be valid environment keys")
        if len(source_secret_refs) != len(set(source_secret_refs)):
            # Fail the local subprocess runner init path with ValueError for source secret
            # references must be unique when source secret refs is true; do not continue
            # ambiguously.
            raise ValueError("source secret references must be unique")
        self._command = command
        self._source_secret_refs = source_secret_refs
        self._working_directory = working_directory.resolve(strict=True)
        if not self._working_directory.is_dir():
            # Fail the local subprocess runner init path with ValueError for working
            # directory must be a directory when is dir and working directory is true; do
            # not continue ambiguously.
            raise ValueError("working_directory must be a directory")
        self._envelope_directory = envelope_directory.resolve()
        self._envelope_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._envelope_directory.is_dir():
            raise ValueError("envelope directory must be a directory")
        # Assemble resolved temporary roots once so the local subprocess runner init
        # workflow shares one value.
        resolved_temporary_roots = tuple(path.resolve() for path in temporary_roots)
        if len(resolved_temporary_roots) != len(set(resolved_temporary_roots)):
            raise ValueError("temporary resource roots must be unique")
        self._temporary_roots = resolved_temporary_roots
        self._owned: dict[int, _OwnedProcess] = {}
        # Assemble self lock once so the local subprocess runner init workflow shares one
        # value.
        self._lock = Lock()

    def spawn(self, attempt: JobAttempt, *, native_threads: int) -> ProcessHandle:
        # Execute the local subprocess runner spawn workflow in explicit, reviewable
        # steps.
        if native_threads <= 0:
            raise ValueError("native_threads must be positive")
        try:
            envelope_path = self._write_envelope(attempt)
        except OSError as exc:
            # Fail the local subprocess runner spawn path with ProcessSpawnError for
            # launch envelope could not be published; do not continue ambiguously.
            raise ProcessSpawnError("launch envelope could not be published") from exc
        try:
            progress, progress_write_descriptor = create_progress_pipe(attempt.attempt_id)
        except OSError as exc:
            # Translate the OSError failure through the local subprocess runner spawn
            # boundary.
            _unlink_quietly(envelope_path)
            raise ProcessSpawnError("progress channel could not be created") from exc
        environment = child_progress_environment(os.environ, progress_write_descriptor)
        # Only the two bounded source-acquisition jobs may receive source secrets.
        if attempt.spec.job_type not in {JobType.PREPARE_DATASET, JobType.PREPARE_RESEARCH}:
            # Handle the local subprocess runner spawn job type, prepare dataset and spec
            # condition as a distinct block.
            for secret_ref in self._source_secret_refs:
                environment.pop(secret_ref, None)
        apply_child_process_determinism(native_threads, environment)
        temporary_baseline = self._temporary_bytes()
        try:
            # Perform the protected local subprocess runner spawn operation before
            # explicit failure handling.
            process = subprocess.Popen(
                (*self._command, os.fspath(envelope_path)),
                cwd=self._working_directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                # Pass stdout explicitly so Popen receives a reviewable command and fspath
                # input in local subprocess runner spawn.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                pass_fds=(progress_write_descriptor,),
                # Pass start new session explicitly so Popen receives a reviewable command
                # and fspath input in local subprocess runner spawn.
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # Translate the (OSError, subprocess.SubprocessError) failure through the
            # local subprocess runner spawn boundary.
            progress.close()
            _unlink_quietly(envelope_path)
            raise ProcessSpawnError("isolated worker process could not be started") from exc
        finally:
            # Handle the cleanup path after the protected local subprocess runner spawn
            # operation.
            with suppress(OSError):
                os.close(progress_write_descriptor)

        start_token = _read_process_start_token(process.pid)
        if start_token is None:
            # Handle the local subprocess runner spawn start_token is None branch as a
            # distinct logical block.
            if process.poll() is None:
                # Handle the local subprocess runner spawn process.poll() is None branch
                # as a distinct logical block.
                self._signal_process_group(process.pid, signal.SIGKILL)
                process.wait()
                progress.close()
                _unlink_quietly(envelope_path)
                raise ProcessIdentityError("live child process has no stable OS start token")
            # Assemble start token once so the local subprocess runner spawn workflow
            # shares one value.
            start_token = f"owned-exited:{uuid.uuid4().hex}"
        with self._lock:
            # Keep lock active only for the bounded local subprocess runner spawn
            # operation.
            self._owned[process.pid] = _OwnedProcess(
                process,
                start_token,
                envelope_path,
                temporary_baseline,
                # Pass progress explicitly so _OwnedProcess receives a reviewable process
                # and start token input in local subprocess runner spawn.
                progress,
            )
        return ProcessHandle(process_id=process.pid, start_token=start_token)

    def probe(self, handle: ProcessHandle) -> ProcessStatus:
        # Execute the local subprocess runner probe workflow in explicit, reviewable
        # steps.
        owned = self._owned_process(handle)
        if owned is not None:
            # Handle the local subprocess runner probe owned is not None branch as a
            # distinct logical block.
            exit_code = owned.process.poll()
            if exit_code is None:
                # Handle the local subprocess runner probe exit_code is None branch as a
                # distinct logical block.
                return self._running_status(
                    handle,
                    owned.temporary_baseline_bytes,
                    owned.progress,
                )
            # Assemble (progress events, dropped frames) once so the local subprocess
            # runner probe workflow shares one value.
            progress_events, dropped_frames = owned.progress.drain()
            self._forget(handle, owned)
            return ProcessStatus(
                ProcessState.EXITED,
                exit_code,
                # Pass progress events explicitly so ProcessStatus receives a reviewable
                # exited and process state input in local subprocess runner probe.
                progress_events=progress_events,
                dropped_progress_frames=dropped_frames,
            )

        current_token = _read_process_start_token(handle.process_id, require_live=True)
        if current_token != handle.start_token:
            # Return the completed local subprocess runner probe result without a hidden
            # fallback.
            return ProcessStatus(ProcessState.EXITED)
        return self._running_status(handle, None, None)

    def terminate(self, handle: ProcessHandle, grace_seconds: float) -> None:
        # Execute the local subprocess runner terminate workflow in explicit, reviewable
        # steps.
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be non-negative")
        owned = self._owned_process(handle)
        if owned is not None and owned.process.poll() is not None:
            # Handle the local subprocess runner terminate owned, poll and process
            # condition as a distinct block.
            self._forget(handle, owned)
            return
        if _read_process_start_token(handle.process_id) != handle.start_token:
            # Handle the local subprocess runner terminate start token, read process start
            # token and process id condition as a distinct block.
            if owned is not None:
                self._forget(handle, owned)
            return

        self._signal_process_group(handle.process_id, signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        # Repeat the local subprocess runner terminate step only while time.monotonic() <
        # deadline remains true.
        while time.monotonic() < deadline:
            # Owned children retain their established Popen polling and cleanup behavior.
            if owned is not None:
                exited = self.probe(handle).state is ProcessState.EXITED
            else:
                # A zombie leader may still have group members that ignore cooperative stop.
                exited = _read_process_start_token(handle.process_id) != handle.start_token
            if exited:
                return
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if _read_process_start_token(handle.process_id) == handle.start_token:
            self._signal_process_group(handle.process_id, signal.SIGKILL)
        # Guard this path with owned is not None before applying effects.
        if owned is not None:
            # Handle the local subprocess runner terminate owned is not None branch as a
            # distinct logical block.
            with suppress(subprocess.TimeoutExpired):
                owned.process.wait(timeout=1.0)
            self._forget(handle, owned)
        else:
            # A restarted runner has no Popen waiter but must still observe delayed exit.
            self._wait_for_persisted_exit(handle)

    def _wait_for_persisted_exit(self, handle: ProcessHandle) -> None:
        """Use the same one-second post-kill bound as the owned-child wait."""

        deadline = time.monotonic() + 1.0
        while _read_process_start_token(handle.process_id, require_live=True) == handle.start_token:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            # Observe only identity; absent resource measurements cannot prove exit.
            time.sleep(min(0.05, remaining))

    def cleanup_launch(self, attempt_id: AttemptId) -> None:
        _unlink_quietly(self._envelope_path(attempt_id))

    # Define local subprocess runner write envelope as one focused operation with an
    # explicit boundary.
    def _write_envelope(self, attempt: JobAttempt) -> Path:
        # Execute the local subprocess runner write envelope workflow in explicit,
        # reviewable steps.
        document = {
            "attempt_id": attempt.attempt_id.value,
            "input_artifact_ids": [item.hex for item in attempt.spec.input_artifact_ids],
            "job_id": attempt.job_id.value,
            "job_type": attempt.spec.job_type.value,
            # Register canonical payload through loads so the document table remains
            # scannable.
            "payload": json.loads(attempt.spec.canonical_payload),
            "payload_digest": attempt.spec.payload_digest.hex,
            "schema": "backtest.local-job-envelope.v1",
            "spec_id": attempt.spec.spec_id.hex,
            "spec_version": attempt.spec.spec_version,
            # Complete the document group only after its semantic components are visible.
        }
        payload = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            # Pass separators explicitly so encode receives a reviewable utf-8 input in
            # local subprocess runner write envelope.
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        path = self._envelope_path(attempt.attempt_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        # Assemble fd once so the local subprocess runner write envelope workflow shares
        # one value.
        fd = os.open(path, flags, 0o600)
        try:
            # Perform the protected local subprocess runner write envelope operation
            # before explicit failure handling.
            view = memoryview(payload)
            while view:
                # Keep the view loop body bounded within local subprocess runner write
                # envelope.
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while publishing launch envelope")
                view = view[written:]
            os.fsync(fd)
        # Translate base exception through the local subprocess runner write envelope
        # boundary without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the local subprocess runner
            # write envelope boundary.
            os.close(fd)
            _unlink_quietly(path)
            raise
        else:
            os.close(fd)
        # Invoke _fsync_directory for envelope directory as a visible local subprocess
        # runner write envelope step.
        _fsync_directory(self._envelope_directory)
        return path

    def _running_status(
        self,
        handle: ProcessHandle,
        # Keep the temporary baseline bytes input explicit in the running status contract.
        temporary_baseline_bytes: int | None,
        progress: ProgressPipeReader | None,
    ) -> ProcessStatus:
        # ``start_new_session`` makes the attempt PID its process-group ID.
        # Aggregate the whole group so sweep grandchildren cannot evade the
        # resource reservation held for their parent attempt.
        resources = measure_process_group_resources(handle.process_id)
        swap = measure_host_swap()
        current_temporary = self._temporary_bytes()
        temporary = (
            None
            # Keep the current temporary component named inside the temporary contract.
            if current_temporary is None or temporary_baseline_bytes is None
            else max(0, current_temporary - temporary_baseline_bytes)
        )
        progress_events, dropped_frames = ((), 0) if progress is None else progress.drain()
        if resources is None:
            # The process may have exited between ``poll``/identity validation
            # and the resource read.  A following cycle will observe exit.
            return ProcessStatus(
                ProcessState.RUNNING,
                temporary_disk_bytes=temporary,
                progress_events=progress_events,
                dropped_progress_frames=dropped_frames,
                # Complete ProcessStatus only after its running and process state inputs are
                # visible in local subprocess runner running status.
            )
        return ProcessStatus(
            ProcessState.RUNNING,
            private_rss_bytes=resources.private_rss_bytes,
            total_rss_bytes=resources.total_rss_bytes,
            # Pass child swap bytes explicitly so ProcessStatus receives a reviewable
            # running and private rss bytes input in local subprocess runner running
            # status.
            child_swap_bytes=resources.child_swap_bytes,
            host_swap_in_bytes=None if swap is None else swap.swap_in_bytes,
            host_swap_out_bytes=None if swap is None else swap.swap_out_bytes,
            major_page_faults=resources.major_page_faults,
            temporary_disk_bytes=temporary,
            # Pass progress events explicitly so ProcessStatus receives a reviewable
            # running and private rss bytes input in local subprocess runner running
            # status.
            progress_events=progress_events,
            dropped_progress_frames=dropped_frames,
        )

    def _temporary_bytes(self) -> int | None:
        # Execute the local subprocess runner temporary bytes workflow in explicit,
        # reviewable steps.
        if not self._temporary_roots:
            return None
        try:
            return directory_tree_bytes(self._temporary_roots)
        except OSError:
            # Return explicit absence from the local subprocess runner temporary bytes
            # path.
            return None

    def _envelope_path(self, attempt_id: AttemptId) -> Path:
        # Execute the local subprocess runner envelope path workflow in explicit,
        # reviewable steps.
        basename = sha256(attempt_id.value.encode("utf-8")).hexdigest()
        return self._envelope_directory / f"{basename}.json"

    def _owned_process(self, handle: ProcessHandle) -> _OwnedProcess | None:
        # Execute the local subprocess runner owned process workflow in explicit,
        # reviewable steps.
        with self._lock:
            owned = self._owned.get(handle.process_id)
        if owned is None or owned.start_token != handle.start_token:
            return None
        return owned

    # Define local subprocess runner forget as one focused operation with an explicit
    # boundary.
    def _forget(self, handle: ProcessHandle, owned: _OwnedProcess) -> None:
        # Execute the local subprocess runner forget workflow in explicit, reviewable
        # steps.
        with self._lock:
            # Keep lock active only for the bounded local subprocess runner forget
            # operation.
            if self._owned.get(handle.process_id) is owned:
                self._owned.pop(handle.process_id, None)
        owned.progress.close()
        _unlink_quietly(owned.envelope_path)

    @staticmethod
    # Define local subprocess runner signal process group as one focused operation with an
    # explicit boundary.
    def _signal_process_group(process_id: int, sig: signal.Signals) -> None:
        # Execute the local subprocess runner signal process group workflow in explicit,
        # reviewable steps.
        try:
            os.killpg(process_id, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            # Some restricted local launch environments deny group signalling
            # while still allowing the owner to signal the exact verified PID.
            with suppress(ProcessLookupError):
                os.kill(process_id, sig)


def _read_process_start_token(process_id: int, *, require_live: bool = False) -> str | None:
    """Preserve exact OS identity, optionally excluding processes that cannot execute."""
    if process_id <= 0:
        return None
    if sys.platform.startswith("linux"):
        # Handle the read process start token sys.platform.startswith('linux') branch as a
        # distinct logical block.
        try:
            # Perform the protected read process start token operation before explicit
            # failure handling.
            stat = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
            close_paren = stat.rfind(")")
            fields_after_name = stat[close_paren + 2 :].split()
            # A zombie's identity can still authorize cleanup of its surviving process group.
            if require_live and fields_after_name[0] in {"Z", "X", "x"}:
                return None
            start_ticks = fields_after_name[19]
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        # Translate file not found error through the read process start token boundary
        # without hiding other errors.
        except (FileNotFoundError, OSError, UnicodeDecodeError, IndexError):
            return None
        identity = f"linux:{boot_id}:{process_id}:{start_ticks}".encode("ascii")
    # Handle the read process start token complement of sys.platform.startswith('linux')
    # explicitly.
    elif sys.platform == "darwin":
        # Handle the read process start token sys.platform == 'darwin' branch as a
        # distinct logical block.
        info = _ProcBsdInfo()
        try:
            # Perform the protected read process start token operation before explicit
            # failure handling.
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            proc_pidinfo = libproc.proc_pidinfo
            proc_pidinfo.argtypes = (
                ctypes.c_int,
                ctypes.c_int,
                # Keep the ctypes component named inside the proc pidinfo argtypes
                # contract.
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            )
            proc_pidinfo.restype = ctypes.c_int
            # Assemble size once so the read process start token workflow shares one
            # value.
            size = ctypes.sizeof(info)
            written = proc_pidinfo(
                process_id,
                3,  # PROC_PIDTBSDINFO
                0,
                ctypes.byref(info),
                size,
            )
        except (AttributeError, OSError):
            # Return explicit absence from the read process start token path.
            return None
        if written != size or info.pid != process_id:
            return None
        identity = f"darwin:{process_id}:{info.start_tvsec}:{info.start_tvusec}".encode("ascii")
    else:
        # Handle the read process start token complement of sys.platform == 'darwin'
        # explicitly.
        try:
            # Perform the protected read process start token operation before explicit
            # failure handling.
            result = subprocess.run(
                ("/bin/ps", "-p", str(process_id), "-o", "lstart="),
                check=False,
                capture_output=True,
                text=True,
                # Pass timeout explicitly so run receives a reviewable /bin/ps and -p
                # input in read process start token.
                timeout=1.0,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        started = result.stdout.strip()
        # Guard this path with result.returncode != 0 or not started before applying
        # effects.
        if result.returncode != 0 or not started:
            return None
        identity = f"posix:{process_id}:{started}".encode()
    return sha256(identity).hexdigest()


def _fsync_directory(directory: Path) -> None:
    # Execute the fsync directory workflow in explicit, reviewable steps.
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Define unlink quietly as one focused operation with an explicit boundary.
def _unlink_quietly(path: Path) -> None:
    # Execute the unlink quietly workflow in explicit, reviewable steps.
    with suppress(FileNotFoundError):
        path.unlink()


__all__ = ["LocalSubprocessRunner", "ProcessIdentityError", "ProcessSpawnError"]
