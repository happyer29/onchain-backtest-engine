# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from pathlib import Path

import backtest.runtime.runtime_lock as runtime_lock
from backtest.runtime.runtime_lock import build_runtime_manifest


# Define test runtime manifest is repeatable and secret free as one focused operation with
# an explicit boundary.
def test_runtime_manifest_is_repeatable_and_secret_free(monkeypatch) -> None:
    # Execute the test runtime manifest is repeatable and secret free workflow in
    # explicit, reviewable steps.
    monkeypatch.setenv("BACKTEST_INDEXER_PASSWORD", "must-never-appear")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")

    first = build_runtime_manifest(native_threads_per_process=1)
    second = build_runtime_manifest(native_threads_per_process=1)

    assert first == second
    # Assemble payload once so the test runtime manifest is repeatable and secret free
    # workflow shares one value.
    payload = first.bytes()
    assert b"must-never-appear" not in payload
    document = json.loads(payload)
    assert document["artifact_schema"] == "runtime-lock/v2"
    assert document["runtime_lock_id"] == first.runtime_lock_id.hex
    # Verify the file count, application package and document relationship before this
    # scenario is accepted.
    assert document["runtime"]["application_package"]["file_count"] > 0
    assert document["runtime"]["python"]["executable"]["total_bytes"] > 0


def test_determinism_environment_and_thread_count_are_part_of_physical_identity(
    monkeypatch,
) -> None:
    # Execute the test determinism environment and thread count are part of physical
    # identity workflow in explicit, reviewable steps.
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    first = build_runtime_manifest(native_threads_per_process=1)
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    changed_environment = build_runtime_manifest(native_threads_per_process=1)
    changed_threads = build_runtime_manifest(native_threads_per_process=2)

    # Verify the runtime lock id, first and changed environment relationship before this
    # scenario is accepted.
    assert (
        len(
            {
                first.runtime_lock_id,
                changed_environment.runtime_lock_id,
                # Pass changed threads explicitly so len receives a reviewable runtime
                # lock id and first input in test determinism environment and thread count
                # are part of physical identity.
                changed_threads.runtime_lock_id,
            }
        )
        == 3
    )


# Define test runtime manifest can fingerprint the declared child environment as one
# focused operation with an explicit boundary.
def test_runtime_manifest_can_fingerprint_the_declared_child_environment() -> None:
    # Execute the test runtime manifest can fingerprint the declared child environment
    # workflow in explicit, reviewable steps.
    declared = {
        "MKL_NUM_THREADS": "2",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONHASHSEED": "0",
        # Complete the declared group only after its semantic components are visible.
    }

    first = build_runtime_manifest(native_threads_per_process=2, environ=declared)
    second = build_runtime_manifest(native_threads_per_process=2, environ=dict(declared))

    assert first == second
    assert first.document["environment"] == declared


# Define test runtime identity tracks actual application source bytes as one focused
# operation with an explicit boundary.
def test_runtime_identity_tracks_actual_application_source_bytes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Execute the test runtime identity tracks actual application source bytes workflow in
    # explicit, reviewable steps.
    package = tmp_path / "backtest"
    package.mkdir()
    source = package / "worker.py"
    source.write_text("RESULT = 1\n", encoding="utf-8")
    monkeypatch.setattr(runtime_lock, "_APPLICATION_PACKAGE_ROOT", package)

    # Assemble first once so the test runtime identity tracks actual application source
    # bytes workflow shares one value.
    first = build_runtime_manifest(native_threads_per_process=1)
    source.write_text("RESULT = 2\n", encoding="utf-8")
    second = build_runtime_manifest(native_threads_per_process=1)

    assert first.runtime_lock_id != second.runtime_lock_id
    first_package = first.document["application_package"]
    # Assemble second package once so the test runtime identity tracks actual application
    # source bytes workflow shares one value.
    second_package = second.document["application_package"]
    assert first_package != second_package
