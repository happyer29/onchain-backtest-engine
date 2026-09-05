"""Measured, conservative host and child resource counters for Mac/Linux.

The module deliberately uses only the standard library.  Admission consumes
private/physical counters, while mmap/page-cache bytes remain protected by an
explicit floor instead of being presented as free child memory.
"""

from __future__ import annotations

import ctypes
import os
import platform
import resource

# Import stat at the visible module dependency boundary.
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


class HostResourceMeasurementError(RuntimeError):
    """A supported host could not provide a safe resource measurement."""


@dataclass(frozen=True, slots=True)
class HostMemoryMeasurement:
    total_physical_bytes: int
    available_physical_bytes: int
    controller_private_rss_bytes: int

    # Define host memory measurement post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the host memory measurement post init workflow in explicit, reviewable
        # steps.
        values = (
            self.total_physical_bytes,
            self.available_physical_bytes,
            self.controller_private_rss_bytes,
        )
        # Evaluate the complete host memory measurement post init value, values and
        # isinstance condition before guarded effects.
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("host memory counters must be non-negative")
        if self.total_physical_bytes <= 0:
            raise ValueError("total physical memory must be positive")
        if self.available_physical_bytes > self.total_physical_bytes:
            # Fail the host memory measurement post init path with ValueError for
            # available memory cannot exceed total physical memory when available physical
            # bytes and total physical bytes is true; do not continue ambiguously.
            raise ValueError("available memory cannot exceed total physical memory")


# Keep the host memory reserves contract and validation rules together.
@dataclass(frozen=True, slots=True)
class HostMemoryReserves:
    configured_child_ceiling_bytes: int
    safety_reserve_bytes: int
    page_cache_floor_bytes: int
    # Declare host staging output reserve bytes explicitly in the host memory reserves
    # contract.
    host_staging_output_reserve_bytes: int
    fixed_shared_overhead_bytes: int

    def __post_init__(self) -> None:
        # Execute the host memory reserves post init workflow in explicit, reviewable
        # steps.
        values = (
            self.configured_child_ceiling_bytes,
            self.safety_reserve_bytes,
            self.page_cache_floor_bytes,
            self.host_staging_output_reserve_bytes,
            # Keep the self component named inside the values contract.
            self.fixed_shared_overhead_bytes,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("host memory reserves must be non-negative")
        if self.configured_child_ceiling_bytes <= 0:
            # Fail the host memory reserves post init path with ValueError for configured
            # child memory ceiling must be positive when configured child ceiling bytes is
            # true; do not continue ambiguously.
            raise ValueError("configured child memory ceiling must be positive")


# Keep the host memory budget measurement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class HostMemoryBudgetMeasurement:
    total_physical_bytes: int
    measured_os_baseline_bytes: int
    measured_controller_overhead_bytes: int
    # Declare safety reserve bytes explicitly in the host memory budget measurement
    # contract.
    safety_reserve_bytes: int
    page_cache_floor_bytes: int
    host_staging_output_reserve_bytes: int
    fixed_shared_overhead_bytes: int
    configured_child_ceiling_bytes: int
    # Declare available child private bytes explicitly in the host memory budget
    # measurement contract.
    available_child_private_bytes: int

    def __post_init__(self) -> None:
        # Execute the host memory budget measurement post init workflow in explicit,
        # reviewable steps.
        values = tuple(getattr(self, field) for field in self.__dataclass_fields__)
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("host memory budget values must be non-negative")


# Keep the process resource measurement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProcessResourceMeasurement:
    private_rss_bytes: int
    total_rss_bytes: int
    child_swap_bytes: int
    # Declare major page faults explicitly in the process resource measurement contract.
    major_page_faults: int

    def __post_init__(self) -> None:
        # Execute the process resource measurement post init workflow in explicit,
        # reviewable steps.
        values = (
            self.private_rss_bytes,
            self.total_rss_bytes,
            self.child_swap_bytes,
            self.major_page_faults,
            # Complete the values group only after its semantic components are visible.
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("process resource counters must be non-negative")


# Keep the host swap measurement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class HostSwapMeasurement:
    swap_in_bytes: int
    swap_out_bytes: int

    def __post_init__(self) -> None:
        # Execute the host swap measurement post init workflow in explicit, reviewable
        # steps.
        if min(self.swap_in_bytes, self.swap_out_bytes) < 0:
            raise ValueError("host swap counters must be non-negative")


# Keep the darwin rusage info v2 contract and validation rules together.
class _DarwinRusageInfoV2(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("user_time", ctypes.c_uint64),
        ("system_time", ctypes.c_uint64),
        # Keep the pkg idle wkups component named inside the fields contract.
        ("pkg_idle_wkups", ctypes.c_uint64),
        ("interrupt_wkups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        # Keep the phys footprint component named inside the fields contract.
        ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64),
        ("proc_exit_abstime", ctypes.c_uint64),
        ("child_user_time", ctypes.c_uint64),
        ("child_system_time", ctypes.c_uint64),
        # Keep the child pkg idle wkups component named inside the fields contract.
        ("child_pkg_idle_wkups", ctypes.c_uint64),
        ("child_interrupt_wkups", ctypes.c_uint64),
        ("child_pageins", ctypes.c_uint64),
        ("child_elapsed_abstime", ctypes.c_uint64),
        ("diskio_bytesread", ctypes.c_uint64),
        # Keep the diskio byteswritten component named inside the fields contract.
        ("diskio_byteswritten", ctypes.c_uint64),
    ]


# Keep the darwin vm statistics64 contract and validation rules together.
class _DarwinVmStatistics64(ctypes.Structure):
    _fields_ = [
        ("free_count", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("inactive_count", ctypes.c_uint32),
        # Keep the wire count component named inside the fields contract.
        ("wire_count", ctypes.c_uint32),
        ("zero_fill_count", ctypes.c_uint64),
        ("reactivations", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("pageouts", ctypes.c_uint64),
        # Keep the faults component named inside the fields contract.
        ("faults", ctypes.c_uint64),
        ("cow_faults", ctypes.c_uint64),
        ("lookups", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("purges", ctypes.c_uint64),
        # Keep the purgeable count component named inside the fields contract.
        ("purgeable_count", ctypes.c_uint32),
        ("speculative_count", ctypes.c_uint32),
        ("decompressions", ctypes.c_uint64),
        ("compressions", ctypes.c_uint64),
        ("swapins", ctypes.c_uint64),
        # Keep the swapouts component named inside the fields contract.
        ("swapouts", ctypes.c_uint64),
        ("compressor_page_count", ctypes.c_uint32),
        ("throttled_count", ctypes.c_uint32),
        ("external_page_count", ctypes.c_uint32),
        ("internal_page_count", ctypes.c_uint32),
        # Keep the total uncompressed pages in compressor component named inside the
        # fields contract.
        ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
    ]


def derive_host_memory_budget(
    measurement: HostMemoryMeasurement,
    reserves: HostMemoryReserves,
    # Keep the host memory budget measurement input explicit in the derive host memory budget
    # contract.
) -> HostMemoryBudgetMeasurement:
    """Apply the normative aggregate-private-memory formula conservatively."""

    measured_os_baseline = max(
        0,
        measurement.total_physical_bytes
        - measurement.available_physical_bytes
        - measurement.controller_private_rss_bytes,
        # Complete max only after its controller private rss bytes and total physical bytes
        # inputs are visible in derive host memory budget.
    )
    fixed_reserves = (
        reserves.safety_reserve_bytes
        + reserves.page_cache_floor_bytes
        + reserves.host_staging_output_reserve_bytes
        # Keep the reserves component named inside the fixed reserves contract.
        + reserves.fixed_shared_overhead_bytes
    )
    measured_available = max(
        0,
        measurement.total_physical_bytes
        # Pass measured os baseline explicitly so max receives a reviewable controller
        # private rss bytes and total physical bytes input in derive host memory budget.
        - measured_os_baseline
        - measurement.controller_private_rss_bytes
        - fixed_reserves,
    )
    return HostMemoryBudgetMeasurement(
        # Pass total physical bytes explicitly so HostMemoryBudgetMeasurement receives a
        # reviewable total physical bytes and controller private rss bytes input in derive
        # host memory budget.
        total_physical_bytes=measurement.total_physical_bytes,
        measured_os_baseline_bytes=measured_os_baseline,
        measured_controller_overhead_bytes=measurement.controller_private_rss_bytes,
        safety_reserve_bytes=reserves.safety_reserve_bytes,
        page_cache_floor_bytes=reserves.page_cache_floor_bytes,
        # Pass host staging output reserve bytes explicitly so HostMemoryBudgetMeasurement
        # receives a reviewable total physical bytes and controller private rss bytes
        # input in derive host memory budget.
        host_staging_output_reserve_bytes=reserves.host_staging_output_reserve_bytes,
        fixed_shared_overhead_bytes=reserves.fixed_shared_overhead_bytes,
        configured_child_ceiling_bytes=reserves.configured_child_ceiling_bytes,
        available_child_private_bytes=min(
            reserves.configured_child_ceiling_bytes,
            # Pass measured available explicitly so min receives a reviewable configured
            # child ceiling bytes and reserves input in derive host memory budget.
            measured_available,
        ),
    )


def measure_host_memory() -> HostMemoryMeasurement:
    """Measure current host capacity and this controller's private footprint."""

    system = platform.system()
    if system == "Linux":
        # Handle the measure host memory system == 'Linux' branch as a distinct logical
        # block.
        fields = _linux_key_values(Path("/proc/meminfo"))
        try:
            # Perform the protected measure host memory operation before explicit failure
            # handling.
            total = fields["MemTotal"] * 1024
            available = fields["MemAvailable"] * 1024
        except KeyError as error:
            # Translate the KeyError failure through the measure host memory boundary.
            raise HostResourceMeasurementError(
                "Linux memory availability is unavailable"
            ) from error
    # Handle the measure host memory complement of system == 'Linux' explicitly.
    elif system == "Darwin":
        # Handle the measure host memory system == 'Darwin' branch as a distinct logical
        # block.
        total = _darwin_total_memory()
        available = _darwin_available_memory()
    else:  # pragma: no cover - deployment contract supports Mac/Linux only
        raise HostResourceMeasurementError("resource admission supports only Mac and Linux")

    process = measure_process_resources(os.getpid())
    private = process.private_rss_bytes if process is not None else _peak_process_rss_bytes()
    return HostMemoryMeasurement(total, min(total, available), private)


def measure_process_resources(process_id: int) -> ProcessResourceMeasurement | None:
    """Return a conservative current sample, or ``None`` after process exit."""

    if process_id <= 0:
        raise ValueError("process_id must be positive")
    system = platform.system()
    if system == "Linux":
        return _linux_process_resources(process_id)
    # Guard this path with system == 'Darwin' before applying effects.
    if system == "Darwin":
        return _darwin_process_resources(process_id)
    return None  # pragma: no cover - deployment contract supports Mac/Linux only


def measure_process_group_resources(
    process_group_id: int,
) -> ProcessResourceMeasurement | None:
    """Return aggregate counters for an isolated child process group.

    The local runner creates one new session/process group per attempt.  A
    sweep may add worker descendants inside that group, so sampling only its
    leader would under-report the resource demand that admission reserved.
    Private RSS and cumulative counters are summed conservatively.
    """

    if process_group_id <= 0:
        raise ValueError("process_group_id must be positive")
    system = platform.system()
    if system == "Linux":
        process_ids = _linux_process_group_ids(process_group_id)
    # Handle the measure process group resources complement of system == 'Linux'
    # explicitly.
    elif system == "Darwin":
        process_ids = _darwin_process_group_ids(process_group_id)
    else:  # pragma: no cover - deployment contract supports Mac/Linux only
        return None
    measurements = tuple(
        measurement
        for process_id in process_ids
        if (measurement := measure_process_resources(process_id)) is not None
        # Complete tuple only after its measure process resources and measurement inputs are
        # visible in measure process group resources.
    )
    if not measurements:
        return None
    return ProcessResourceMeasurement(
        private_rss_bytes=sum(item.private_rss_bytes for item in measurements),
        # Include total rss bytes in the completed measure process group resources result.
        total_rss_bytes=sum(item.total_rss_bytes for item in measurements),
        child_swap_bytes=sum(item.child_swap_bytes for item in measurements),
        major_page_faults=sum(item.major_page_faults for item in measurements),
    )


def measure_host_swap() -> HostSwapMeasurement | None:
    """Return cumulative swap activity counters for sustained-delta detection."""

    system = platform.system()
    if system == "Linux":
        # Handle the measure host swap system == 'Linux' branch as a distinct logical
        # block.
        try:
            # Perform the protected measure host swap operation before explicit failure
            # handling.
            fields = _linux_key_values(Path("/proc/vmstat"))
            page_size = os.sysconf("SC_PAGE_SIZE")
            return HostSwapMeasurement(
                fields["pswpin"] * page_size,
                fields["pswpout"] * page_size,
                # Complete HostSwapMeasurement only after its pswpin and pswpout inputs are
                # visible in measure host swap.
            )
        except (KeyError, OSError, ValueError):
            return None
    if system == "Darwin":
        # Handle the measure host swap system == 'Darwin' branch as a distinct logical
        # block.
        try:
            page_size, statistics = _darwin_vm_statistics()
        except HostResourceMeasurementError:
            return None
        return HostSwapMeasurement(
            # Pass statistics explicitly so HostSwapMeasurement receives a reviewable
            # swapins and swapouts input in measure host swap.
            statistics.swapins * page_size,
            statistics.swapouts * page_size,
        )
    return None  # pragma: no cover - deployment contract supports Mac/Linux only


def directory_tree_bytes(roots: tuple[Path, ...]) -> int:
    """Measure regular bytes beneath trusted local roots without following links."""

    total = 0
    seen_files: set[tuple[int, int]] = set()
    stack = list(roots)
    while stack:
        # Keep the stack loop body bounded within directory tree bytes.
        current = stack.pop()
        try:
            # Perform the protected directory tree bytes operation before explicit failure
            # handling.
            current_info = current.lstat()
            if not stat.S_ISDIR(current_info.st_mode):
                continue
            entries = tuple(os.scandir(current))
        except FileNotFoundError:
            # Keep the continue step explicit within the directory tree bytes workflow.
            continue
        except NotADirectoryError:
            entries = ()
        for entry in entries:
            # Process entries inside the bounded directory tree bytes loop.
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(info.st_mode):
                # Invoke append for path and entry as a visible directory tree bytes step.
                stack.append(Path(entry.path))
            # Handle the directory tree bytes complement of stat.S_ISDIR(info.st_mode)
            # explicitly.
            elif stat.S_ISREG(info.st_mode):
                # Handle the directory tree bytes stat.S_ISREG(info.st_mode) branch as a
                # distinct logical block.
                identity = (info.st_dev, info.st_ino)
                if identity not in seen_files:
                    # Handle the directory tree bytes identity not in seen_files branch as
                    # a distinct logical block.
                    seen_files.add(identity)
                    total += info.st_size
    return total


def _linux_process_resources(process_id: int) -> ProcessResourceMeasurement | None:
    # Execute the linux process resources workflow in explicit, reviewable steps.
    root = Path(f"/proc/{process_id}")
    try:
        rollup = _linux_key_values(root / "smaps_rollup")
    except FileNotFoundError:
        return None
    # Translate oserror through the linux process resources boundary without hiding other
    # errors.
    except (OSError, UnicodeDecodeError, ValueError):
        rollup = {}
    try:
        # Perform the protected linux process resources operation before explicit failure
        # handling.
        total = rollup["Rss"] * 1024
        private = (
            rollup.get("Private_Clean", 0)
            + rollup.get("Private_Dirty", 0)
            + rollup.get("Private_Hugetlb", 0)
            # Complete the private group only after its semantic components are visible.
        ) * 1024
        swap = rollup.get("Swap", 0) * 1024
    except KeyError:
        # Translate the KeyError failure through the linux process resources boundary.
        try:
            # Perform the protected linux process resources operation before explicit
            # failure handling.
            status = _linux_key_values(root / "status")
            total = status["VmRSS"] * 1024
            # Total RSS is a safe upper bound when private accounting is not
            # available; admission must never assume sharing optimistically.
            private = total
            swap = status.get("VmSwap", 0) * 1024
        except FileNotFoundError:
            return None
        except (KeyError, OSError, UnicodeDecodeError, ValueError):
            # Return explicit absence from the linux process resources path.
            return None
    major_faults = _linux_major_faults(root / "stat")
    return ProcessResourceMeasurement(private, total, swap, major_faults)


def _linux_process_group_ids(process_group_id: int) -> tuple[int, ...]:
    # Execute the linux process group ids workflow in explicit, reviewable steps.
    process_ids: list[int] = []
    try:
        entries = os.scandir("/proc")
    except OSError:
        return ()
    # Acquire entries at an explicit linux process group ids context boundary so cleanup
    # remains scoped.
    with entries:
        # Keep entries active only for the bounded linux process group ids operation.
        for entry in entries:
            # Process entries inside the bounded linux process group ids loop.
            if not entry.name.isascii() or not entry.name.isdecimal():
                continue
            try:
                # Perform the protected linux process group ids operation before explicit
                # failure handling.
                raw = Path(entry.path, "stat").read_text(encoding="ascii")
                fields = raw[raw.rfind(")") + 2 :].split()
                process_id = int(entry.name)
                group_id = int(fields[2])
                state = fields[0]
            # Translate file not found error through the linux process group ids boundary
            # without hiding other errors.
            except (FileNotFoundError, OSError, UnicodeDecodeError, IndexError, ValueError):
                continue
            if group_id == process_group_id and state != "Z":
                process_ids.append(process_id)
    return tuple(process_ids)


# Define linux major faults as one focused operation with an explicit boundary.
def _linux_major_faults(path: Path) -> int:
    # Execute the linux major faults workflow in explicit, reviewable steps.
    try:
        # Perform the protected linux major faults operation before explicit failure
        # handling.
        raw = path.read_text(encoding="ascii")
        fields = raw[raw.rfind(")") + 2 :].split()
        return int(fields[9])
    except (FileNotFoundError, OSError, UnicodeDecodeError, IndexError, ValueError):
        return 0


# Define linux key values as one focused operation with an explicit boundary.
def _linux_key_values(path: Path) -> dict[str, int]:
    # Execute the linux key values workflow in explicit, reviewable steps.
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        # Process splitlines, read text and path inside the bounded linux key values loop.
        if ":" in line:
            # Handle the linux key values ':' in line branch as a distinct logical block.
            key, raw_value = line.split(":", 1)
            token = raw_value.strip().split(maxsplit=1)[0]
        else:
            # Handle the linux key values complement of ':' in line explicitly.
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            key, token = parts
        try:
            # Assemble values[key] once so the linux key values workflow shares one value.
            values[key] = int(token)
        except ValueError:
            continue
    return values


def _darwin_total_memory() -> int:
    # Execute the darwin total memory workflow in explicit, reviewable steps.
    try:
        # Perform the protected darwin total memory operation before explicit failure
        # handling.
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError) as error:
        raise HostResourceMeasurementError("macOS physical memory is unavailable") from error
    if pages <= 0 or page_size <= 0:
        # Fail the darwin total memory path with HostResourceMeasurementError for mac os
        # physical memory is unavailable when pages and page size is true; do not continue
        # ambiguously.
        raise HostResourceMeasurementError("macOS physical memory is unavailable")
    return int(pages) * page_size


def _darwin_available_memory() -> int:
    # Execute the darwin available memory workflow in explicit, reviewable steps.
    page_size, statistics = _darwin_vm_statistics()
    # Keep admission conservative: only free and inactive resident queues are
    # treated as reclaimable child headroom. ``vm_statistics64.free_count``
    # already includes speculative pages, while purgeable pages already
    # belong to a resident queue, so adding either counter again would
    # double-count physical pages.
    pages = statistics.free_count + statistics.inactive_count
    return int(pages) * page_size


def _darwin_process_resources(process_id: int) -> ProcessResourceMeasurement | None:
    # Execute the darwin process resources workflow in explicit, reviewable steps.
    usage = _DarwinRusageInfoV2()
    try:
        # Perform the protected darwin process resources operation before explicit failure
        # handling.
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pid_rusage = library.proc_pid_rusage
        proc_pid_rusage.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        proc_pid_rusage.restype = ctypes.c_int
        result = proc_pid_rusage(process_id, 2, ctypes.byref(usage))
    # Translate attribute error through the darwin process resources boundary without
    # hiding other errors.
    except (AttributeError, OSError):
        return None
    if result != 0:
        return None
    private = int(usage.phys_footprint)
    # Assemble total once so the darwin process resources workflow shares one value.
    total = max(private, int(usage.resident_size))
    return ProcessResourceMeasurement(private, total, 0, int(usage.pageins))


def _darwin_process_group_ids(process_group_id: int) -> tuple[int, ...]:
    # Execute the darwin process group ids workflow in explicit, reviewable steps.
    try:
        # Perform the protected darwin process group ids operation before explicit failure
        # handling.
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_listpids = library.proc_listpids
        proc_listpids.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint32,
            # Keep the ctypes component named inside the proc listpids argtypes contract.
            ctypes.c_void_p,
            ctypes.c_int,
        )
        proc_listpids.restype = ctypes.c_int
        required_bytes = proc_listpids(2, process_group_id, None, 0)
    # Translate attribute error through the darwin process group ids boundary without
    # hiding other errors.
    except (AttributeError, OSError):
        return ()
    if required_bytes <= 0:
        return ()
    # Leave spare entries for a descendant created between the sizing and
    # collection calls.  A full buffer is retried once with double capacity.
    capacity = required_bytes // ctypes.sizeof(ctypes.c_int) + 16
    for _ in range(2):
        # Process range(2) inside the bounded darwin process group ids loop.
        process_ids = (ctypes.c_int * capacity)()
        written = proc_listpids(
            2,  # PROC_PGRP_ONLY
            process_group_id,
            ctypes.byref(process_ids),
            ctypes.sizeof(process_ids),
        )
        if written <= 0:
            # Return an explicit empty result from the darwin process group ids path.
            return ()
        count = min(capacity, written // ctypes.sizeof(ctypes.c_int))
        if written < ctypes.sizeof(process_ids):
            return tuple(process_id for process_id in process_ids[:count] if process_id > 0)
        capacity *= 2
    # Return the completed darwin process group ids result without a hidden fallback.
    return tuple(process_id for process_id in process_ids if process_id > 0)


def _darwin_vm_statistics() -> tuple[int, _DarwinVmStatistics64]:
    # Execute the darwin vm statistics workflow in explicit, reviewable steps.
    try:
        # Perform the protected darwin vm statistics operation before explicit failure
        # handling.
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        mach_host_self = library.mach_host_self
        mach_host_self.argtypes = ()
        mach_host_self.restype = ctypes.c_uint32
        host_page_size = library.host_page_size
        # Assemble host page size argtypes once so the darwin vm statistics workflow
        # shares one value.
        host_page_size.argtypes = (
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        host_page_size.restype = ctypes.c_int
        # Assemble host statistics64 once so the darwin vm statistics workflow shares one
        # value.
        host_statistics64 = library.host_statistics64
        host_statistics64.argtypes = (
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_void_p,
            # Register c uint32 through POINTER so the host statistics64.argtypes table
            # remains scannable.
            ctypes.POINTER(ctypes.c_uint32),
        )
        host_statistics64.restype = ctypes.c_int
    except (AttributeError, OSError) as error:
        raise HostResourceMeasurementError("macOS VM counters are unavailable") from error
    # Assemble host once so the darwin vm statistics workflow shares one value.
    host = mach_host_self()
    page_size = ctypes.c_uint32()
    if host_page_size(host, ctypes.byref(page_size)) != 0 or page_size.value <= 0:
        raise HostResourceMeasurementError("macOS VM page size is unavailable")
    statistics = _DarwinVmStatistics64()
    # Assemble count once so the darwin vm statistics workflow shares one value.
    count = ctypes.c_uint32(ctypes.sizeof(statistics) // ctypes.sizeof(ctypes.c_int))
    if host_statistics64(host, 4, ctypes.byref(statistics), ctypes.byref(count)) != 0:
        raise HostResourceMeasurementError("macOS VM counters are unavailable")
    return int(page_size.value), statistics


def _peak_process_rss_bytes() -> int:
    # Execute the peak process rss bytes workflow in explicit, reviewable steps.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


__all__ = [
    "HostMemoryBudgetMeasurement",
    "HostMemoryMeasurement",
    # Keep the host memory reserves component named inside the all contract.
    "HostMemoryReserves",
    "HostResourceMeasurementError",
    "HostSwapMeasurement",
    "ProcessResourceMeasurement",
    "derive_host_memory_budget",
    # Keep the directory tree bytes component named inside the all contract.
    "directory_tree_bytes",
    "measure_host_memory",
    "measure_host_swap",
    "measure_process_group_resources",
    "measure_process_resources",
    # Complete the all group only after its semantic components are visible.
]
