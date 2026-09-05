"""Portable regressions for Linux exit state and persisted-process termination."""

from __future__ import annotations

import signal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

# Isolated module substitutions exercise Linux kernel records on every supported host.
import pytest

from backtest.adapters.process import local
from backtest.application.models import ProcessHandle, ProcessState


@pytest.mark.parametrize("state", ("Z", "X", "x"))
def test_linux_exited_process_has_no_live_start_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """An unreaped process must not be adopted or signalled as a live attempt."""

    _linux_process_files(tmp_path, monkeypatch, state)
    assert local._read_process_start_token(123, require_live=True) is None


@pytest.mark.parametrize("state", ("R", "S", "D", "T", "t", "I"))
def test_linux_live_process_preserves_exact_start_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """Sleeping, stopped and uninterruptible processes retain their exact identity."""

    _linux_process_files(tmp_path, monkeypatch, state)
    expected = sha256(b"linux:fixture-boot:123:456789").hexdigest()
    assert local._read_process_start_token(123) == expected
    assert local._read_process_start_token(123, require_live=True) == expected


def _linux_process_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    """Provide Linux kernel-format records without depending on the host platform."""

    stat_path, boot_path = tmp_path / "stat", tmp_path / "boot_id"
    fields = [state, *("0" for _ in range(18)), "456789"]
    stat_path.write_text("123 (worker (bounded)) " + " ".join(fields), encoding="ascii")
    boot_path.write_text("fixture-boot\n", encoding="ascii")
    # Keep the tested parser's platform and filesystem view local to its module.
    paths = {"/proc/123/stat": stat_path, "/proc/sys/kernel/random/boot_id": boot_path}
    monkeypatch.setattr(local, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(local, "Path", paths.__getitem__)


@pytest.mark.parametrize("final_token", (None, "replacement-process"))
def test_persisted_termination_waits_until_exact_identity_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_token: str | None
) -> None:
    """A delayed exit or PID replacement ends the bounded wait without more signals."""

    runner = _runner(tmp_path)
    handle = ProcessHandle(123, "persisted-process")
    clock, sleeps = _controlled_clock(monkeypatch)
    sent: list[tuple[int, signal.Signals]] = []
    # The kernel keeps the old identity briefly after accepting SIGKILL.
    monkeypatch.setattr(
        local,
        "_read_process_start_token",
        lambda pid, **kwargs: handle.start_token if clock[0] < 0.1 else final_token,
    )
    # Signals are recorded independently of the synthetic kernel exit transition.
    monkeypatch.setattr(runner, "_signal_process_group", lambda pid, sig: sent.append((pid, sig)))
    runner.terminate(handle, 0.0)
    # Completion requires observing disappearance, not assuming signal delivery was exit.
    assert clock[0] >= 0.1
    assert sleeps
    assert runner.probe(handle).state is ProcessState.EXITED
    assert sent == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_persisted_termination_timeout_does_not_invent_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uninterruptible process remains live after the existing one-second bound."""

    runner = _runner(tmp_path)
    handle = ProcessHandle(123, "persisted-process")
    clock, sleeps = _controlled_clock(monkeypatch)
    # The same OS identity remains present even after both termination signals.
    monkeypatch.setattr(
        local, "_read_process_start_token", lambda pid, **kwargs: handle.start_token
    )
    # Resource absence is valid and does not constitute process exit evidence.
    monkeypatch.setattr(local, "measure_process_group_resources", lambda pid: None)
    monkeypatch.setattr(local, "measure_host_swap", lambda: None)
    monkeypatch.setattr(runner, "_signal_process_group", lambda pid, sig: None)
    runner.terminate(handle, 0.0)
    # Check both a finite poll budget and honest state after that budget expires.
    assert clock[0] == pytest.approx(1.0)
    assert 1 <= len(sleeps) <= 21
    assert runner.probe(handle).state is ProcessState.RUNNING


def test_persisted_termination_never_signals_or_waits_for_reused_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unrelated process cannot be stopped through a persisted stale handle."""

    runner = _runner(tmp_path)
    clock, sleeps = _controlled_clock(monkeypatch)
    sent: list[tuple[int, signal.Signals]] = []
    # A reused PID differs before termination has authority to send its first signal.
    monkeypatch.setattr(
        local, "_read_process_start_token", lambda pid, **kwargs: "replacement-process"
    )
    # Record attempted signals even though this test never creates a real OS process.
    monkeypatch.setattr(runner, "_signal_process_group", lambda pid, sig: sent.append((pid, sig)))
    runner.terminate(ProcessHandle(123, "persisted-process"), 0.0)
    assert sent == []
    assert sleeps == []
    assert clock == [0.0]


@pytest.mark.parametrize("grace_seconds", (0.0, 0.1))
def test_zombie_identity_still_authorizes_exact_process_group_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grace_seconds: float
) -> None:
    """A dead leader must not prevent signalling surviving members of its exact group."""

    runner = _runner(tmp_path)
    sent: list[tuple[int, signal.Signals]] = []
    clock, sleeps = _controlled_clock(monkeypatch)
    _linux_process_files(tmp_path, monkeypatch, "Z")
    expected = sha256(b"linux:fixture-boot:123:456789").hexdigest()
    # Start identity remains intact even though this leader can no longer execute.
    assert local._read_process_start_token(123) == expected
    monkeypatch.setattr(runner, "_signal_process_group", lambda pid, sig: sent.append((pid, sig)))
    handle = ProcessHandle(123, expected)
    runner.terminate(handle, grace_seconds)
    # Group cleanup and leader liveness are deliberately separate observations.
    assert sent == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert runner.probe(handle).state is ProcessState.EXITED
    assert clock[0] == pytest.approx(grace_seconds)
    assert bool(sleeps) is (grace_seconds > 0.0)


def _runner(tmp_path: Path) -> local.LocalSubprocessRunner:
    """Construct an empty runner, matching a restart with only a persisted handle."""

    return local.LocalSubprocessRunner(
        ("unused-worker",),
        working_directory=tmp_path,
        envelope_directory=tmp_path / "envelopes",
    )


def _controlled_clock(monkeypatch: pytest.MonkeyPatch) -> tuple[list[float], list[float]]:
    """Advance bounded poll time deterministically without any wall-clock sleeps."""

    clock, sleeps = [0.0], []

    def sleep(seconds: float) -> None:
        # Time moves only when the implementation yields between identity observations.
        assert 0.0 < seconds <= 0.05
        sleeps.append(seconds)
        clock[0] += seconds

    # Replacing the module reference leaves pytest and other runtime clocks untouched.
    monkeypatch.setattr(local, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    return clock, sleeps
