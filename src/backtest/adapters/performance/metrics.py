"""Portable process counters with explicit measurement provenance."""

from __future__ import annotations

import ctypes
import os
import resource
import sys

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from backtest.application.benchmarks import IoCounterBasis, PrivateRssBasis


# Keep the process io counters contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProcessIoCounters:
    read_bytes: int | None
    write_bytes: int | None
    basis: IoCounterBasis


# Keep the peak private rss sampler contract and validation rules together.
class PeakPrivateRssSampler:
    """Sample an instantaneous private-memory counter during one workload."""

    def __init__(self, interval_seconds: float = 0.005) -> None:
        # Execute the peak private rss sampler init workflow in explicit, reviewable
        # steps.
        if interval_seconds <= 0:
            raise ValueError("private RSS sampling interval must be positive")
        self._interval = interval_seconds
        self._stop = Event()
        self._peak: int | None = None
        # Assemble self basis once so the peak private rss sampler init workflow shares
        # one value.
        self._basis = PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK
        self._thread: Thread | None = None

    @property
    def peak_bytes(self) -> int | None:
        return self._peak

    # Apply property semantics to the following peak private rss sampler basis contract.
    @property
    def basis(self) -> PrivateRssBasis:
        return self._basis

    def start(self) -> None:
        # Execute the peak private rss sampler start workflow in explicit, reviewable
        # steps.
        if self._thread is not None:
            raise RuntimeError("private RSS sampler is already started")
        self._sample()
        self._thread = Thread(target=self._run, name="benchmark-private-rss", daemon=True)
        self._thread.start()

    # Define peak private rss sampler stop as one focused operation with an explicit
    # boundary.
    def stop(self) -> None:
        # Execute the peak private rss sampler stop workflow in explicit, reviewable
        # steps.
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._sample()
        # Assemble self thread once so the peak private rss sampler stop workflow shares
        # one value.
        self._thread = None

    def _run(self) -> None:
        # Execute the peak private rss sampler run workflow in explicit, reviewable steps.
        while not self._stop.wait(self._interval):
            self._sample()

    def _sample(self) -> None:
        # Execute the peak private rss sampler sample workflow in explicit, reviewable
        # steps.
        value, basis = current_private_rss_bytes()
        self._basis = basis
        if value is not None and (self._peak is None or value > self._peak):
            self._peak = value


def current_private_rss_bytes() -> tuple[int | None, PrivateRssBasis]:
    # Execute the current private rss bytes workflow in explicit, reviewable steps.
    if sys.platform.startswith("linux"):
        # Handle the current private rss bytes sys.platform.startswith('linux') branch as
        # a distinct logical block.
        try:
            # Perform the protected current private rss bytes operation before explicit
            # failure handling.
            values = _linux_key_values(Path("/proc/self/smaps_rollup"))
            private_kib = sum(
                values.get(name, 0)
                for name in ("Private_Clean", "Private_Dirty", "Private_Hugetlb")
            )
        # Translate oserror through the current private rss bytes boundary without hiding
        # other errors.
        except (OSError, UnicodeError, ValueError):
            pass
        else:
            return private_kib * 1024, PrivateRssBasis.LINUX_SMAPS_ROLLUP
    if sys.platform == "darwin":
        # Handle the current private rss bytes sys.platform == 'darwin' branch as a
        # distinct logical block.
        values = _darwin_proc_rusage()
        if values is not None:
            return values[0], PrivateRssBasis.DARWIN_PHYSICAL_FOOTPRINT
    return None, PrivateRssBasis.TOTAL_RSS_CONSERVATIVE_FALLBACK


def current_io_counters() -> ProcessIoCounters:
    # Execute the current io counters workflow in explicit, reviewable steps.
    if sys.platform.startswith("linux"):
        # Handle the current io counters sys.platform.startswith('linux') branch as a
        # distinct logical block.
        try:
            # Perform the protected current io counters operation before explicit failure
            # handling.
            values = _linux_key_values(Path("/proc/self/io"))
            return ProcessIoCounters(
                read_bytes=values["read_bytes"],
                write_bytes=values["write_bytes"],
                basis=IoCounterBasis.LINUX_PROC_IO,
                # Complete ProcessIoCounters only after its read bytes and write bytes inputs
                # are visible in current io counters.
            )
        except (KeyError, OSError, UnicodeError, ValueError):
            pass
    if sys.platform == "darwin":
        # Handle the current io counters sys.platform == 'darwin' branch as a distinct
        # logical block.
        values = _darwin_proc_rusage()
        if values is not None:
            # Handle the current io counters values is not None branch as a distinct
            # logical block.
            return ProcessIoCounters(
                read_bytes=values[1],
                write_bytes=values[2],
                basis=IoCounterBasis.DARWIN_PROC_PID_RUSAGE,
            )
    # Return the completed current io counters result without a hidden fallback.
    return ProcessIoCounters(None, None, IoCounterBasis.UNAVAILABLE)


def peak_total_rss_bytes() -> int:
    # Execute the peak total rss bytes workflow in explicit, reviewable steps.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def _linux_key_values(path: Path) -> dict[str, int]:
    # Execute the linux key values workflow in explicit, reviewable steps.
    result: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        # Process splitlines, read text and path inside the bounded linux key values loop.
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        token = remainder.strip().split(maxsplit=1)[0]
        result[key] = int(token)
    # Return the completed linux key values result without a hidden fallback.
    return result


def _darwin_proc_rusage() -> tuple[int, int, int] | None:
    """Return physical footprint and disk bytes from ``rusage_info_v2``.

    A generously sized byte buffer avoids depending on private SDK headers;
    offsets below are the stable public ``rusage_info_v2`` prefix.
    """

    buffer = ctypes.create_string_buffer(512)
    try:
        # Perform the protected darwin proc rusage operation before explicit failure
        # handling.
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        function = library.proc_pid_rusage
        function.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        function.restype = ctypes.c_int
        status = function(os.getpid(), 2, ctypes.byref(buffer))
    # Translate attribute error through the darwin proc rusage boundary without hiding
    # other errors.
    except (AttributeError, OSError):
        return None
    if status != 0:
        return None
    physical_footprint = ctypes.c_uint64.from_buffer(buffer, 72).value
    # Assemble disk read once so the darwin proc rusage workflow shares one value.
    disk_read = ctypes.c_uint64.from_buffer(buffer, 144).value
    disk_written = ctypes.c_uint64.from_buffer(buffer, 152).value
    return physical_footprint, disk_read, disk_written


__all__ = [
    "PeakPrivateRssSampler",
    # Keep the process io counters component named inside the all contract.
    "ProcessIoCounters",
    "current_io_counters",
    "current_private_rss_bytes",
    "peak_total_rss_bytes",
]
