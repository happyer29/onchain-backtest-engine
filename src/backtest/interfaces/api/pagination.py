"""Canonical opaque transport tokens for bounded Control API list pages."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping

from backtest.application.models import AttemptState
from backtest.application.ports.catalog import RunListCursor
from backtest.application.ports.jobs import JobListCursor
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId, JobId, LogicalRunId

# Tokens contain only unpadded URL-safe base64 and remain small enough for a query string.
PAGE_TOKEN_PATTERN = r"[A-Za-z0-9_-]{1,512}"
_PAGE_TOKEN_RE = re.compile(PAGE_TOKEN_PATTERN + r"\Z")
_CANONICAL_UNSIGNED_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_MAX_SQLITE_INTEGER = 2**63 - 1


class PageTokenError(ValueError):
    """A continuation token is malformed, noncanonical, or used in another scope."""


def encode_job_cursor(value: JobListCursor) -> str:
    """Encode a job key without exposing a client-defined query expression."""

    document = {
        "i": value.job_id.value,
        "k": "jobs",
        "s": None if value.state is None else value.state.value,
        # Decimal text avoids JSON number precision loss in browsers.
        "t": str(value.submitted_at_ns),
        "v": 1,
    }
    return _encode(document)


def decode_job_cursor(value: str, *, state: AttemptState | None) -> JobListCursor:
    """Decode and bind a job continuation to the exact state filter."""

    document = _decode(value)
    if set(document) != {"i", "k", "s", "t", "v"}:
        raise PageTokenError("job cursor fields are invalid")
    if document["k"] != "jobs" or type(document["v"]) is not int or document["v"] != 1:
        raise PageTokenError("job cursor kind or version is invalid")
    # The state filter is part of cursor scope and cannot change between pages.
    encoded_state = document["s"]
    expected_state = None if state is None else state.value
    if encoded_state != expected_state:
        raise PageTokenError("job cursor does not match the state filter")
    try:
        return JobListCursor(
            state=state,
            submitted_at_ns=_unsigned_sqlite_integer(document["t"]),
            job_id=JobId(_string(document["i"])),
        )
    except (TypeError, ValueError) as error:
        raise PageTokenError("job cursor values are invalid") from error


def encode_run_cursor(value: RunListCursor) -> str:
    """Encode a global/logical Run key as one opaque transport value."""

    document = {
        "i": value.artifact_id.hex,
        "k": "runs",
        "l": None if value.logical_run_id is None else value.logical_run_id.hex,
        # Decimal text preserves the exact integer completion epoch in JavaScript.
        "t": str(value.completed_at_ns),
        "v": 1,
    }
    return _encode(document)


def decode_run_cursor(
    value: str,
    *,
    logical_run_id: LogicalRunId | None,
) -> RunListCursor:
    """Decode and bind a Run continuation to global or logical scope."""

    document = _decode(value)
    if set(document) != {"i", "k", "l", "t", "v"}:
        raise PageTokenError("run cursor fields are invalid")
    if document["k"] != "runs" or type(document["v"]) is not int or document["v"] != 1:
        raise PageTokenError("run cursor kind or version is invalid")
    # A global token cannot enter a logical route and vice versa.
    encoded_logical = document["l"]
    expected_logical = None if logical_run_id is None else logical_run_id.hex
    if encoded_logical != expected_logical:
        raise PageTokenError("run cursor does not match the logical scope")
    try:
        return RunListCursor(
            completed_at_ns=_unsigned_sqlite_integer(document["t"]),
            artifact_id=ArtifactId(_string(document["i"])),
            logical_run_id=logical_run_id,
        )
    except (TypeError, ValueError) as error:
        raise PageTokenError("run cursor values are invalid") from error


def _encode(document: Mapping[str, object]) -> str:
    """Produce one canonical unpadded URL-safe base64 token."""

    encoded = base64.urlsafe_b64encode(canonical_json_bytes(document)).decode("ascii")
    return encoded.rstrip("=")


def _decode(value: str) -> dict[str, object]:
    """Reject alternate spellings before returning a canonical JSON object."""

    if not isinstance(value, str) or _PAGE_TOKEN_RE.fullmatch(value) is None:
        raise PageTokenError("page cursor syntax is invalid")
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        document = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PageTokenError("page cursor encoding is invalid") from error
    if not isinstance(document, dict):
        raise PageTokenError("page cursor must encode an object")
    # Canonical bytes make equivalent aliases and hidden duplicate forms impossible.
    try:
        if canonical_json_bytes(document) != raw or _encode(document) != value:
            raise PageTokenError("page cursor is not canonical")
    except (TypeError, ValueError) as error:
        raise PageTokenError("page cursor is not canonical") from error
    return document


def _unsigned_sqlite_integer(value: object) -> int:
    """Parse one canonical decimal in SQLite's non-negative integer range."""

    if not isinstance(value, str) or _CANONICAL_UNSIGNED_RE.fullmatch(value) is None:
        raise PageTokenError("cursor timestamp is not canonical decimal text")
    result = int(value)
    if result > _MAX_SQLITE_INTEGER:
        raise PageTokenError("cursor timestamp exceeds the SQLite integer range")
    return result


def _string(value: object) -> str:
    """Narrow an untrusted JSON scalar before identifier validation."""

    if not isinstance(value, str):
        raise PageTokenError("cursor identifier must be text")
    return value


__all__ = [
    "PAGE_TOKEN_PATTERN",
    "PageTokenError",
    "decode_job_cursor",
    "decode_run_cursor",
    "encode_job_cursor",
    "encode_run_cursor",
]
