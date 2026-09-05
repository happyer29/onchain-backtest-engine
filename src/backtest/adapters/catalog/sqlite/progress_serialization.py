"""Strict canonical SQLite representation for bounded progress details."""

from __future__ import annotations

import json
from typing import Final, cast

from backtest.adapters.catalog.sqlite.errors import QueueCorruptionError
from backtest.application.models import JobProgressDetails, ProgressLevel, ProgressStage

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes

MAX_PROGRESS_DETAILS_BYTES: Final = 2_048
_SCHEMA: Final = "backtest.job-progress.v1"
_FIELDS: Final = frozenset(
    {
        # Pass coalesced events explicitly so frozenset receives a reviewable coalesced
        # events and completed units input in module.
        "coalesced_events",
        "completed_units",
        "dropped_transport_frames",
        "level",
        "major_page_faults",
        # Pass private rss bytes explicitly so frozenset receives a reviewable coalesced
        # events and completed units input in module.
        "private_rss_bytes",
        "schema",
        "sequence",
        "stage",
        "temporary_disk_bytes",
        # Pass total rss bytes explicitly so frozenset receives a reviewable coalesced
        # events and completed units input in module.
        "total_rss_bytes",
        "total_units",
    }
)


def serialize_progress_details(details: JobProgressDetails) -> bytes:
    # Execute the serialize progress details workflow in explicit, reviewable steps.
    payload = canonical_json_bytes(
        {
            "coalesced_events": details.coalesced_events,
            "completed_units": details.completed_units,
            "dropped_transport_frames": details.dropped_transport_frames,
            # Keep level named so the coalesced events and completed units payload passed
            # to canonical_json_bytes remains self-describing within serialize progress
            # details.
            "level": details.level.value,
            "major_page_faults": details.major_page_faults,
            "private_rss_bytes": details.private_rss_bytes,
            "schema": _SCHEMA,
            "sequence": details.sequence,
            # Keep stage named so the coalesced events and completed units payload passed
            # to canonical_json_bytes remains self-describing within serialize progress
            # details.
            "stage": details.stage.value,
            "temporary_disk_bytes": details.temporary_disk_bytes,
            "total_rss_bytes": details.total_rss_bytes,
            "total_units": details.total_units,
        }
        # Complete canonical_json_bytes only after its coalesced events and completed units
        # inputs are visible in serialize progress details.
    )
    if len(payload) > MAX_PROGRESS_DETAILS_BYTES:
        raise ValueError("progress details exceed their bounded SQLite representation")
    return payload


def deserialize_progress_details(payload: bytes) -> JobProgressDetails:
    # Execute the deserialize progress details workflow in explicit, reviewable steps.
    if not payload or len(payload) > MAX_PROGRESS_DETAILS_BYTES:
        raise QueueCorruptionError("stored progress details exceed their bounded schema")
    try:
        # Perform the protected deserialize progress details operation before explicit
        # failure handling.
        raw = json.loads(payload)
        if canonical_json_bytes(raw) != payload:
            raise ValueError("progress details are not canonical")
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise TypeError("progress details root must be an object")
        # Assemble document once so the deserialize progress details workflow shares one
        # value.
        document = cast(dict[str, object], raw)
        if frozenset(document) != _FIELDS or document["schema"] != _SCHEMA:
            raise ValueError("progress details schema is invalid")
        result = JobProgressDetails(
            sequence=_integer(document["sequence"]),
            # Keep the progress level and string ProgressLevel step visible while building
            # result.
            level=ProgressLevel(_string(document["level"])),
            stage=ProgressStage(_string(document["stage"])),
            completed_units=_optional_integer(document["completed_units"]),
            total_units=_optional_integer(document["total_units"]),
            coalesced_events=_integer(document["coalesced_events"]),
            # Keep the integer and document _integer step visible while building result.
            dropped_transport_frames=_integer(document["dropped_transport_frames"]),
            private_rss_bytes=_optional_integer(document["private_rss_bytes"]),
            total_rss_bytes=_optional_integer(document["total_rss_bytes"]),
            major_page_faults=_optional_integer(document["major_page_faults"]),
            temporary_disk_bytes=_optional_integer(document["temporary_disk_bytes"]),
            # Complete JobProgressDetails only after its sequence and level inputs are visible
            # in deserialize progress details.
        )
    except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise QueueCorruptionError("stored progress details are invalid") from exc
    if serialize_progress_details(result) != payload:
        raise QueueCorruptionError("stored progress details are not canonical")
    # Return the completed deserialize progress details result without a hidden fallback.
    return result


def _string(value: object) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise TypeError("progress field must be a string")
    return value


def _integer(value: object) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("progress field must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


# Bind all once as an explicit module-level contract.
__all__ = [
    "MAX_PROGRESS_DETAILS_BYTES",
    "deserialize_progress_details",
    "serialize_progress_details",
]
