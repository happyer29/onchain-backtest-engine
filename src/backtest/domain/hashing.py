"""Versioned domain-tagged hashing independent of paths and Python hashes."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import NoReturn

from backtest.domain.identifiers import ContentDigest


# Define canonical json bytes as one focused operation with an explicit boundary.
def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON-compatible semantic data with a single exact encoding."""

    _validate(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        # Pass separators explicitly so encode receives a reviewable utf-8 input in
        # canonical json bytes.
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def domain_digest(domain: str, value: object) -> ContentDigest:
    # Execute the domain digest workflow in explicit, reviewable steps.
    if not domain or domain != domain.strip() or "\x00" in domain:
        raise ValueError("hash domain must be non-empty, trimmed and NUL-free")
    material = domain.encode("utf-8") + b"\x00" + canonical_json_bytes(value)
    return ContentDigest(sha256(material).hexdigest())


def _validate(value: object) -> None:
    # Execute the validate workflow in explicit, reviewable steps.
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        _reject_float(value)
    if isinstance(value, list | tuple):
        # Handle the validate isinstance(value, list | tuple) branch as a distinct logical
        # block.
        for item in value:
            _validate(item)
        return
    if isinstance(value, dict):
        # Handle the validate isinstance(value, dict) branch as a distinct logical block.
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        for item in value.values():
            _validate(item)
        return
    # Fail the validate path with TypeError for unsupported canonical json value: and
    # name; do not continue ambiguously.
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _reject_float(value: float) -> NoReturn:
    # Execute the reject float workflow in explicit, reviewable steps.
    del value
    raise TypeError("floating-point values are forbidden in semantic identities")


__all__ = ["canonical_json_bytes", "domain_digest"]
