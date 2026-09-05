"""Bounded non-blocking child-to-supervisor progress pipe.

The pipe carries only a small allowlisted canonical JSON frame.  Backpressure,
a disconnected supervisor, or a malformed frame can drop operational progress
but can never block or change the semantic job result.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, MutableMapping

# Import contextlib at the visible module dependency boundary.
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final, cast

from backtest.application.models import ProgressEvent, ProgressLevel, ProgressStage
from backtest.application.ports.progress import ProgressSink

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AttemptId

PROGRESS_FD_ENV: Final = "BACKTEST_PROGRESS_FD"
_FRAME_SCHEMA: Final = "backtest.child-progress.v1"
_MAX_FRAME_BYTES: Final = 1_024
# Bind max drain bytes once as an explicit module-level contract.
_MAX_DRAIN_BYTES: Final = 32 * 1_024
_MAX_EVENTS_PER_DRAIN: Final = 32


class NullProgressSink:
    """No-op sink for synchronous/unit execution without a supervisor pipe."""

    def publish(self, event: ProgressEvent) -> None:
        del event


@dataclass(slots=True)
class FdProgressSink:
    """Best-effort writer; every frame is smaller than POSIX ``PIPE_BUF``."""

    descriptor: int
    _closed: bool = False

    def publish(self, event: ProgressEvent) -> None:
        # Execute the fd progress sink publish workflow in explicit, reviewable steps.
        if self._closed:
            return
        payload = (
            canonical_json_bytes(
                {
                    # Keep attempt id named so the attempt id and completed units payload
                    # passed to canonical_json_bytes remains self-describing within fd
                    # progress sink publish.
                    "attempt_id": event.attempt_id.value,
                    "completed_units": event.completed_units,
                    "level": event.level.value,
                    "schema": _FRAME_SCHEMA,
                    "sequence": event.sequence,
                    # Keep stage named so the attempt id and completed units payload
                    # passed to canonical_json_bytes remains self-describing within fd
                    # progress sink publish.
                    "stage": event.stage.value,
                    "total_units": event.total_units,
                }
            )
            + b"\n"
            # Complete the payload group only after its semantic components are visible.
        )
        if len(payload) > _MAX_FRAME_BYTES:
            # Handle the fd progress sink publish len(payload) > _MAX_FRAME_BYTES branch
            # as a distinct logical block.
            self.close()
            return
        try:
            # For a non-blocking pipe and a frame below PIPE_BUF, POSIX writes
            # either the complete frame or nothing.  Progress is disposable;
            # the canonical job output is not coupled to this write.
            written = os.write(self.descriptor, payload)
        except BlockingIOError:
            return
        except OSError:
            # Translate the OSError failure through the fd progress sink publish boundary.
            self.close()
            return
        if written != len(payload):
            self.close()

    def close(self) -> None:
        # Execute the fd progress sink close workflow in explicit, reviewable steps.
        if self._closed:
            return
        self._closed = True
        with suppress(OSError):
            os.close(self.descriptor)


# Apply dataclass semantics to the following progress pipe reader contract.
@dataclass(slots=True)
class ProgressPipeReader:
    """Supervisor-owned decoder with bounded memory and strict frame schema."""

    descriptor: int
    attempt_id: AttemptId
    _buffer: bytearray = field(default_factory=bytearray)
    _discard_until_newline: bool = False
    _last_sequence: int = 0
    # Declare dropped since drain explicitly in the progress pipe reader contract.
    _dropped_since_drain: int = 0
    _closed: bool = False

    def drain(self) -> tuple[tuple[ProgressEvent, ...], int]:
        # Execute the progress pipe reader drain workflow in explicit, reviewable steps.
        if self._closed:
            return (), 0
        events: list[ProgressEvent] = []
        read_bytes = 0
        reached_eof = False
        # Repeat the progress pipe reader drain step only while read_bytes <
        # _MAX_DRAIN_BYTES remains true.
        while read_bytes < _MAX_DRAIN_BYTES:
            # Keep the read_bytes < _MAX_DRAIN_BYTES loop body bounded within progress
            # pipe reader drain.
            try:
                # Perform the protected progress pipe reader drain operation before
                # explicit failure handling.
                chunk = os.read(
                    self.descriptor,
                    min(4_096, _MAX_DRAIN_BYTES - read_bytes),
                )
            except BlockingIOError:
                # Keep the break step explicit within the progress pipe reader drain
                # workflow.
                break
            except OSError:
                # Translate the OSError failure through the progress pipe reader drain
                # boundary.
                reached_eof = True
                break
            if not chunk:
                # Handle the progress pipe reader drain not chunk branch as a distinct
                # logical block.
                reached_eof = True
                break
            read_bytes += len(chunk)
            for frame in self._feed(chunk):
                # Process self._feed(chunk) inside the bounded progress pipe reader drain
                # loop.
                event = self._decode(frame)
                if event is None:
                    # Handle the progress pipe reader drain event is None branch as a
                    # distinct logical block.
                    self._dropped_since_drain += 1
                    continue
                if event.sequence <= self._last_sequence:
                    # Handle the progress pipe reader drain event.sequence <=
                    # self._last_sequence branch as a distinct logical block.
                    self._dropped_since_drain += 1
                    continue
                self._last_sequence = event.sequence
                events.append(event)

        if reached_eof:
            # Handle the progress pipe reader drain reached_eof branch as a distinct
            # logical block.
            if self._buffer or self._discard_until_newline:
                self._dropped_since_drain += 1
            self._buffer.clear()
            self._discard_until_newline = False
            self.close()

        # Guard this path with len(events) > _MAX_EVENTS_PER_DRAIN before applying
        # effects.
        if len(events) > _MAX_EVENTS_PER_DRAIN:
            # Handle the progress pipe reader drain len(events) > _MAX_EVENTS_PER_DRAIN
            # branch as a distinct logical block.
            self._dropped_since_drain += len(events) - _MAX_EVENTS_PER_DRAIN
            events = events[-_MAX_EVENTS_PER_DRAIN:]
        dropped = self._dropped_since_drain
        self._dropped_since_drain = 0
        return tuple(events), dropped

    # Define progress pipe reader close as one focused operation with an explicit
    # boundary.
    def close(self) -> None:
        # Execute the progress pipe reader close workflow in explicit, reviewable steps.
        if self._closed:
            return
        self._closed = True
        with suppress(OSError):
            os.close(self.descriptor)

    # Define progress pipe reader feed as one focused operation with an explicit boundary.
    def _feed(self, chunk: bytes) -> tuple[bytes, ...]:
        # Execute the progress pipe reader feed workflow in explicit, reviewable steps.
        if self._discard_until_newline:
            # Handle the progress pipe reader feed self._discard_until_newline branch as a
            # distinct logical block.
            newline = chunk.find(b"\n")
            if newline < 0:
                return ()
            self._discard_until_newline = False
            chunk = chunk[newline + 1 :]

        # Invoke extend for chunk as a visible progress pipe reader feed step.
        self._buffer.extend(chunk)
        frames: list[bytes] = []
        while True:
            # Keep the True loop body bounded within progress pipe reader feed.
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            frame = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            # Evaluate the complete progress pipe reader feed frame and max frame bytes
            # condition before guarded effects.
            if not frame or len(frame) > _MAX_FRAME_BYTES:
                self._dropped_since_drain += 1
            else:
                frames.append(frame)
        if len(self._buffer) > _MAX_FRAME_BYTES:
            # Handle the progress pipe reader feed len(self._buffer) > _MAX_FRAME_BYTES
            # branch as a distinct logical block.
            self._buffer.clear()
            self._discard_until_newline = True
            self._dropped_since_drain += 1
        return tuple(frames)

    def _decode(self, payload: bytes) -> ProgressEvent | None:
        # Execute the progress pipe reader decode workflow in explicit, reviewable steps.
        try:
            # Perform the protected progress pipe reader decode operation before explicit
            # failure handling.
            raw = json.loads(payload)
            if canonical_json_bytes(raw) != payload:
                return None
            if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
                return None
            # Assemble document once so the progress pipe reader decode workflow shares
            # one value.
            document = cast(dict[str, object], raw)
            if set(document) != {
                "attempt_id",
                "completed_units",
                "level",
                # Keep schema visible while evaluating the document, attempt id and
                # completed units guard.
                "schema",
                "sequence",
                "stage",
                "total_units",
            }:
                # Return explicit absence from the progress pipe reader decode path.
                return None
            if document["schema"] != _FRAME_SCHEMA:
                return None
            if document["attempt_id"] != self.attempt_id.value:
                return None
            # Assemble sequence once so the progress pipe reader decode workflow shares
            # one value.
            sequence = _integer(document["sequence"])
            completed = _optional_integer(document["completed_units"])
            total = _optional_integer(document["total_units"])
            return ProgressEvent(
                attempt_id=self.attempt_id,
                # Pass sequence explicitly so ProgressEvent receives a reviewable level
                # and stage input in progress pipe reader decode.
                sequence=sequence,
                level=ProgressLevel(_string(document["level"])),
                stage=ProgressStage(_string(document["stage"])),
                completed_units=completed,
                total_units=total,
                # Complete ProgressEvent only after its level and stage inputs are visible in
                # progress pipe reader decode.
            )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError):
            return None


def create_progress_pipe(attempt_id: AttemptId) -> tuple[ProgressPipeReader, int]:
    """Create one private non-blocking channel before spawning a trusted child."""

    read_descriptor, write_descriptor = os.pipe()
    try:
        # Perform the protected create progress pipe operation before explicit failure
        # handling.
        os.set_blocking(read_descriptor, False)
        os.set_blocking(write_descriptor, False)
        os.set_inheritable(read_descriptor, False)
        os.set_inheritable(write_descriptor, False)
    except BaseException:
        # Translate the BaseException failure through the create progress pipe boundary.
        os.close(read_descriptor)
        os.close(write_descriptor)
        raise
    return ProgressPipeReader(read_descriptor, attempt_id), write_descriptor


def progress_sink_from_environment(
    # Keep the environ input explicit in the progress sink from environment contract.
    environ: MutableMapping[str, str] | None = None,
) -> ProgressSink:
    """Consume the trusted inherited pipe descriptor without accepting a path."""

    source = os.environ if environ is None else environ
    raw = source.pop(PROGRESS_FD_ENV, None)
    if raw is None or not raw.isascii() or not raw.isdecimal():
        return NullProgressSink()
    descriptor = int(raw)
    # Guard this path with descriptor <= 2 before applying effects.
    if descriptor <= 2:
        return NullProgressSink()
    try:
        # Perform the protected progress sink from environment operation before explicit
        # failure handling.
        metadata = os.fstat(descriptor)
        if not stat.S_ISFIFO(metadata.st_mode):
            return NullProgressSink()
        os.set_blocking(descriptor, False)
        os.set_inheritable(descriptor, False)
    # Translate oserror through the progress sink from environment boundary without hiding
    # other errors.
    except OSError:
        return NullProgressSink()
    return FdProgressSink(descriptor)


def child_progress_environment(
    base: Mapping[str, str],
    # Keep the write descriptor input explicit in the child progress environment contract.
    write_descriptor: int,
) -> dict[str, str]:
    """Return a child-only environment containing the inherited descriptor number."""

    environment = dict(base)
    environment[PROGRESS_FD_ENV] = str(write_descriptor)
    return environment


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
    "PROGRESS_FD_ENV",
    "FdProgressSink",
    "NullProgressSink",
    "ProgressPipeReader",
    # Keep the child progress environment component named inside the all contract.
    "child_progress_environment",
    "create_progress_pipe",
    "progress_sink_from_environment",
]
