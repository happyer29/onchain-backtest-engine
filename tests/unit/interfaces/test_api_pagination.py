"""Opaque list-continuation transport contract tests."""

from __future__ import annotations

import base64
import json

import pytest

from backtest.application.models import AttemptState
from backtest.application.ports.catalog import RunListCursor
from backtest.application.ports.jobs import JobListCursor
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId, JobId, LogicalRunId
from backtest.interfaces.api.pagination import (
    PageTokenError,
    decode_job_cursor,
    decode_run_cursor,
    encode_job_cursor,
    encode_run_cursor,
)


def _token(document: object, *, canonical: bool = True) -> str:
    """Encode a deliberate test document with or without canonical JSON bytes."""

    raw = (
        canonical_json_bytes(document)
        if canonical
        else json.dumps(document, indent=1).encode("utf-8")
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.parametrize("state", (None, AttemptState.QUEUED))
def test_job_cursor_round_trips_and_is_bound_to_state(state: AttemptState | None) -> None:
    """A job token preserves its exact descending key and filter scope."""

    cursor = JobListCursor(state, 123_456_789, JobId("job-42"))
    token = encode_job_cursor(cursor)

    assert decode_job_cursor(token, state=state) == cursor
    other_state = AttemptState.RUNNING if state is None else None
    with pytest.raises(PageTokenError, match="state filter"):
        decode_job_cursor(token, state=other_state)


@pytest.mark.parametrize("logical", (None, LogicalRunId("b" * 64)))
def test_run_cursor_round_trips_and_is_bound_to_route(
    logical: LogicalRunId | None,
) -> None:
    """A Run token preserves its mixed-direction key and route scope."""

    cursor = RunListCursor(987_654_321, ArtifactId("a" * 64), logical)
    token = encode_run_cursor(cursor)

    assert decode_run_cursor(token, logical_run_id=logical) == cursor
    other = LogicalRunId("c" * 64) if logical is None else None
    with pytest.raises(PageTokenError, match="logical scope"):
        decode_run_cursor(token, logical_run_id=other)


@pytest.mark.parametrize(
    "document",
    (
        # Boolean versions cannot exploit equality with integer one.
        {"i": "job", "k": "jobs", "s": None, "t": "1", "v": True},
        {"i": "job", "k": "jobs", "s": None, "t": "01", "v": 1},
        {"i": "job", "k": "jobs", "s": None, "t": str(2**63), "v": 1},
        {"i": "job", "k": "jobs", "s": None, "t": "1", "v": 1, "x": 0},
    ),
)
def test_job_cursor_rejects_noncanonical_or_out_of_domain_values(
    document: dict[str, object],
) -> None:
    """Only the closed v1 document and SQLite integer domain are accepted."""

    with pytest.raises(PageTokenError):
        decode_job_cursor(_token(document), state=None)


def test_cursor_rejects_alternate_json_and_base64_spellings() -> None:
    """Equivalent but noncanonical encodings cannot create token aliases."""

    document = {"i": "job", "k": "jobs", "s": None, "t": "1", "v": 1}
    with pytest.raises(PageTokenError, match="canonical"):
        decode_job_cursor(_token(document, canonical=False), state=None)
    with pytest.raises(PageTokenError):
        decode_job_cursor("not+a+urlsafe+token", state=None)
