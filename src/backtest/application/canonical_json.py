"""Strict canonical JSON for immutable application command payloads."""

from __future__ import annotations

import json
from collections.abc import Iterable
from hashlib import sha256
from typing import NoReturn

# Bind forbidden secret keys once as an explicit module-level contract.
_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        # Pass credentials explicitly so frozenset receives a reviewable access token and
        # api key input in module.
        "credentials",
        "dsn",
        "passwd",
        "password",
        "secret",
        # Close the access token and api key payload only after all module fields are present.
    }
)


def canonicalize_job_payload(payload_json: bytes) -> bytes:
    """Validate and canonicalize a command object.

    Floats, non-finite values, duplicate object keys and credential-like fields
    are rejected.  Exact numeric values must be represented as integers or
    strings by the typed inbound adapter.
    """

    if not isinstance(payload_json, bytes):
        raise TypeError("job payload must be UTF-8 JSON bytes")
    if not payload_json:
        raise ValueError("job payload must not be empty")
    try:
        # Perform the protected canonicalize job payload operation before explicit failure
        # handling.
        decoded = json.loads(
            payload_json,
            object_pairs_hook=_object_without_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
            # Complete loads only after its payload json and object without duplicates inputs
            # are visible in canonicalize job payload.
        )
    except UnicodeDecodeError as exc:
        raise ValueError("job payload must be valid UTF-8") from exc
    if not isinstance(decoded, dict):
        raise ValueError("job payload root must be an object")
    # Invoke _reject_secret_fields for decoded as a visible canonicalize job payload step.
    _reject_secret_fields(decoded)
    return json.dumps(
        decoded,
        allow_nan=False,
        ensure_ascii=False,
        # Pass separators explicitly so encode receives a reviewable utf-8 input in
        # canonicalize job payload.
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def resolved_job_spec_hex(
    *,
    # Keep the spec version input explicit in the resolved job spec hex contract.
    spec_version: int,
    job_type: str,
    payload_digest_hex: str,
    input_artifact_hexes: Iterable[str],
) -> str:
    """Return a domain-tagged digest for a fully resolved job envelope."""

    identity = json.dumps(
        {
            "input_artifact_ids": sorted(input_artifact_hexes),
            "job_type": job_type,
            "payload_digest": payload_digest_hex,
            # Keep spec version named so the utf-8 payload passed to encode remains self-
            # describing within resolved job spec hex.
            "spec_version": spec_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        # Complete encode only after its utf-8 inputs are visible in resolved job spec hex.
    ).encode("utf-8")
    return sha256(b"backtest.resolved-job-spec\x00" + identity).hexdigest()


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # Execute the object without duplicates workflow in explicit, reviewable steps.
    result: dict[str, object] = {}
    for key, value in pairs:
        # Process pairs inside the bounded object without duplicates loop.
        if key in result:
            raise ValueError(f"job payload contains duplicate field {key!r}")
        result[key] = value
    return result


def _reject_float(value: str) -> NoReturn:
    # Execute the reject float workflow in explicit, reviewable steps.
    del value
    raise ValueError("floating-point JSON numbers are not allowed in job payloads")


def _reject_constant(value: str) -> NoReturn:
    # Execute the reject constant workflow in explicit, reviewable steps.
    del value
    raise ValueError("non-finite JSON numbers are not allowed in job payloads")


def _reject_secret_fields(value: object) -> None:
    # Execute the reject secret fields workflow in explicit, reviewable steps.
    if isinstance(value, dict):
        # Handle the reject secret fields isinstance(value, dict) branch as a distinct
        # logical block.
        for key, nested in value.items():
            # Process value.items() inside the bounded reject secret fields loop.
            normalized = key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_SECRET_KEYS:
                raise ValueError(f"credential field {key!r} is forbidden in a job payload")
            _reject_secret_fields(nested)
    # Handle the reject secret fields complement of isinstance(value, dict) explicitly.
    elif isinstance(value, list):
        # Handle the reject secret fields isinstance(value, list) branch as a distinct
        # logical block.
        for nested in value:
            _reject_secret_fields(nested)


__all__ = ["canonicalize_job_payload", "resolved_job_spec_hex"]
