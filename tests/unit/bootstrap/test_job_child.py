# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.job_commands import ResolvedCompileReplayJob
from backtest.application.models import JobType, ResolvedJobSpec
from backtest.bootstrap.job_child import ChildEnvelopeError, load_launch_envelope
from backtest.domain.hashing import canonical_json_bytes

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    AttemptId,
    ContentDigest,
    SnapshotId,
    # Close the identifiers import after its required symbols are visible.
)


def _spec() -> ResolvedJobSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    command = ResolvedCompileReplayJob(SnapshotId("a" * 64))
    payload = command.canonical_bytes()
    payload_digest = ContentDigest(sha256(payload).hexdigest())
    inputs = (ArtifactId("a" * 64),)
    return ResolvedJobSpec(
        # Pass spec version explicitly so ResolvedJobSpec receives a reviewable value and
        # hex input in spec.
        spec_version=1,
        spec_id=ContentDigest(
            resolved_job_spec_hex(
                spec_version=1,
                job_type=JobType.COMPILE_REPLAY.value,
                # Pass payload digest hex explicitly so resolved_job_spec_hex receives a
                # reviewable value and compile replay input in spec.
                payload_digest_hex=payload_digest.hex,
                input_artifact_hexes=(item.hex for item in inputs),
            )
        ),
        job_type=JobType.COMPILE_REPLAY,
        # Pass canonical payload explicitly so ResolvedJobSpec receives a reviewable value
        # and hex input in spec.
        canonical_payload=payload,
        payload_digest=payload_digest,
        input_artifact_ids=inputs,
    )


def _document(spec: ResolvedJobSpec, attempt_id: AttemptId) -> dict[str, object]:
    # Execute the document workflow in explicit, reviewable steps.
    return {
        "attempt_id": attempt_id.value,
        "input_artifact_ids": [item.hex for item in spec.input_artifact_ids],
        "job_id": "job-child-fixture",
        "job_type": spec.job_type.value,
        # Include payload in the completed document result.
        "payload": json.loads(spec.canonical_payload),
        "payload_digest": spec.payload_digest.hex,
        "schema": "backtest.local-job-envelope.v1",
        "spec_id": spec.spec_id.hex,
        "spec_version": spec.spec_version,
        # Return the completed document result without a hidden fallback.
    }


def _write(directory: Path, document: dict[str, object], attempt_id: AttemptId) -> Path:
    # Execute the write workflow in explicit, reviewable steps.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sha256(attempt_id.value.encode()).hexdigest()}.json"
    path.write_bytes(canonical_json_bytes(document))
    return path


def test_launch_envelope_accepts_only_exact_canonical_resolved_closure(tmp_path: Path) -> None:
    # Execute the test launch envelope accepts only exact canonical resolved closure
    # workflow in explicit, reviewable steps.
    trusted = tmp_path / "job-launch"
    attempt_id = AttemptId("attempt-child-fixture")
    spec = _spec()
    path = _write(trusted, _document(spec, attempt_id), attempt_id)

    envelope = load_launch_envelope(path, trusted_directory=trusted)

    # Verify envelope.attempt_id == attempt_id before this scenario is accepted.
    assert envelope.attempt_id == attempt_id
    assert envelope.spec == spec


def test_launch_envelope_rejects_payload_input_filename_and_format_tampering(
    tmp_path: Path,
) -> None:
    # Execute the test launch envelope rejects payload input filename and format tampering
    # workflow in explicit, reviewable steps.
    trusted = tmp_path / "job-launch"
    attempt_id = AttemptId("attempt-child-fixture")
    spec = _spec()

    payload_tampered = _document(spec, attempt_id)
    payload_tampered["payload"] = {
        # Keep the compiler version component named inside the payload tampered['payload']
        # contract.
        "compiler_version": "numpy-mmap-v3",
        "schema": "backtest.compile-replay-job/v1",
        "snapshot_id": "b" * 64,
    }
    path = _write(trusted, payload_tampered, attempt_id)
    # Acquire raises, child envelope error and pytest at an explicit test launch envelope
    # rejects payload input filename and format tampering context boundary so cleanup
    # remains scoped.
    with pytest.raises(ChildEnvelopeError):
        load_launch_envelope(path, trusted_directory=trusted)
    path.unlink()

    wrong_inputs = (ArtifactId("b" * 64),)
    input_tampered = _document(spec, attempt_id)
    # Assemble input tampered['input artifact ids'] once so the test launch envelope
    # rejects payload input filename and format tampering workflow shares one value.
    input_tampered["input_artifact_ids"] = [wrong_inputs[0].hex]
    input_tampered["spec_id"] = resolved_job_spec_hex(
        spec_version=spec.spec_version,
        job_type=spec.job_type.value,
        payload_digest_hex=spec.payload_digest.hex,
        # Pass input artifact hexes explicitly so resolved_job_spec_hex receives a
        # reviewable spec version and value input in test launch envelope rejects payload
        # input filename and format tampering.
        input_artifact_hexes=(item.hex for item in wrong_inputs),
    )
    path = _write(trusted, input_tampered, attempt_id)
    with pytest.raises(ChildEnvelopeError, match="closure"):
        load_launch_envelope(path, trusted_directory=trusted)
    # Invoke unlink as a visible step within the test launch envelope rejects payload
    # input filename and format tampering workflow.
    path.unlink()

    path = _write(trusted, _document(spec, attempt_id), attempt_id)
    renamed = trusted / "wrong-name.json"
    path.rename(renamed)
    with pytest.raises(ChildEnvelopeError, match="filename"):
        # Invoke load_launch_envelope for renamed and trusted as a visible test launch
        # envelope rejects payload input filename and format tampering step.
        load_launch_envelope(renamed, trusted_directory=trusted)
    renamed.unlink()

    path = _write(trusted, _document(spec, attempt_id), attempt_id)
    path.write_bytes(json.dumps(_document(spec, attempt_id), indent=2).encode())
    with pytest.raises(ChildEnvelopeError, match="canonical"):
        # Invoke load_launch_envelope for path and trusted as a visible test launch
        # envelope rejects payload input filename and format tampering step.
        load_launch_envelope(path, trusted_directory=trusted)


def test_launch_envelope_rejects_outside_path_and_symlink(tmp_path: Path) -> None:
    # Execute the test launch envelope rejects outside path and symlink workflow in
    # explicit, reviewable steps.
    trusted = tmp_path / "job-launch"
    attempt_id = AttemptId("attempt-child-fixture")
    outside = _write(tmp_path / "outside", _document(_spec(), attempt_id), attempt_id)
    with pytest.raises(ChildEnvelopeError, match="outside"):
        load_launch_envelope(outside, trusted_directory=trusted)

    # Invoke mkdir as a visible step within the test launch envelope rejects outside path
    # and symlink workflow.
    trusted.mkdir(parents=True)
    link = trusted / f"{sha256(attempt_id.value.encode()).hexdigest()}.json"
    link.symlink_to(outside)
    with pytest.raises(ChildEnvelopeError, match="unavailable"):
        load_launch_envelope(link, trusted_directory=trusted)
