"""Canonical, versioned serialization for immutable job specifications."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backtest.adapters.catalog.sqlite.errors import QueueCorruptionError

# Import models at the visible module dependency boundary.
from backtest.application.models import JobType, ResolvedJobSpec
from backtest.domain.identifiers import ArtifactId, ContentDigest

_SCHEMA_VERSION = 2


def serialize_job_spec(spec: ResolvedJobSpec) -> bytes:
    """Return stable bytes independent of Python object or dictionary ordering."""

    document = {
        "canonical_payload": spec.canonical_payload.decode("utf-8"),
        "input_artifact_ids": [artifact_id.hex for artifact_id in spec.input_artifact_ids],
        "job_type": spec.job_type.value,
        "payload_digest": spec.payload_digest.hex,
        # Keep the schema version component named inside the document contract.
        "schema_version": _SCHEMA_VERSION,
        "spec_id": spec.spec_id.hex,
        "spec_version": spec.spec_version,
    }
    return json.dumps(
        # Pass document explicitly so encode receives a reviewable utf-8 input in
        # serialize job spec.
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        # Complete encode only after its utf-8 inputs are visible in serialize job spec.
    ).encode("utf-8")


def job_spec_request_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def deserialize_job_spec(payload: bytes) -> ResolvedJobSpec:
    # Execute the deserialize job spec workflow in explicit, reviewable steps.
    try:
        # Perform the protected deserialize job spec operation before explicit failure
        # handling.
        raw: Any = json.loads(payload)
        if not isinstance(raw, dict):
            raise TypeError("job spec root is not an object")
        if type(raw.get("schema_version")) is not int:  # bool is not a schema version
            raise TypeError("schema_version must be an integer")
        if raw["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported job spec schema version")
        expected_keys = {
            "canonical_payload",
            # Keep the input artifact ids component named inside the expected keys
            # contract.
            "input_artifact_ids",
            "job_type",
            "payload_digest",
            "schema_version",
            "spec_id",
            # Keep the spec version component named inside the expected keys contract.
            "spec_version",
        }
        if set(raw) != expected_keys:
            raise ValueError("job spec contains missing or unknown fields")
        artifact_values = raw["input_artifact_ids"]
        # Evaluate the complete deserialize job spec isinstance, artifact values and value
        # condition before guarded effects.
        if not isinstance(artifact_values, list) or not all(
            isinstance(value, str) for value in artifact_values
        ):
            raise TypeError("input_artifact_ids must be a list of strings")
        spec = ResolvedJobSpec(
            # Keep the raw _require_integer step visible while building spec.
            spec_version=_require_integer(raw, "spec_version"),
            spec_id=ContentDigest(_require_string(raw, "spec_id")),
            job_type=JobType(_require_string(raw, "job_type")),
            canonical_payload=_require_string(raw, "canonical_payload").encode("utf-8"),
            payload_digest=ContentDigest(_require_string(raw, "payload_digest")),
            # Keep the artifact id and value tuple step visible while building spec.
            input_artifact_ids=tuple(ArtifactId(value) for value in artifact_values),
        )
    except (KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise QueueCorruptionError("stored ResolvedJobSpec is invalid") from exc

    if serialize_job_spec(spec) != payload:
        # Fail the deserialize job spec path with QueueCorruptionError for stored resolved
        # job spec is not canonical when payload, serialize job spec and spec is true; do
        # not continue ambiguously.
        raise QueueCorruptionError("stored ResolvedJobSpec is not canonical")
    return spec


def _require_string(document: dict[str, Any], field: str) -> str:
    # Execute the require string workflow in explicit, reviewable steps.
    value = document[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def _require_integer(document: dict[str, Any], field: str) -> int:
    # Execute the require integer workflow in explicit, reviewable steps.
    value = document[field]
    if type(value) is not int:  # bool is a JSON integer subclass in Python
        raise TypeError(f"{field} must be an integer")
    return value
