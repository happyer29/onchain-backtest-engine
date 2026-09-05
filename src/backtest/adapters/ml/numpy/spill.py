"""Bounded external sorter for fixed-schema canonical JSON row documents."""

from __future__ import annotations

import heapq
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from typing import IO, cast

from backtest.domain.hashing import canonical_json_bytes

RowKey = tuple[int, ...]


class SpillSortError(RuntimeError):
    """Input rows cannot be materialized within the bounded spill contract."""


@dataclass(frozen=True, slots=True)
class SpilledRows:
    path: Path
    count: int

    def documents(self) -> Iterator[dict[str, object]]:
        # Execute the spilled rows documents workflow in explicit, reviewable steps.
        with self.path.open("rb") as stream:
            # Keep open, rb and path active only for the bounded spilled rows documents
            # operation.
            for raw in stream:
                yield _document(raw.rstrip(b"\n"))


def spill_sort[T](
    rows: Iterable[T],
    *,
    # Keep the encode input explicit in the spill sort contract.
    encode: Callable[[T], dict[str, object]],
    key: Callable[[dict[str, object]], RowKey],
    root: Path,
    maximum_rows_in_memory: int,
    maximum_open_files: int,
    # Keep the spilled rows input explicit in the spill sort contract.
) -> SpilledRows:
    # Execute the spill sort workflow in explicit, reviewable steps.
    if maximum_rows_in_memory <= 0:
        raise ValueError("maximum_rows_in_memory must be positive")
    if maximum_open_files < 2:
        raise ValueError("maximum_open_files must be at least two")
    root.mkdir(parents=True, exist_ok=True)
    # Assemble chunks once so the spill sort workflow shares one value.
    chunks: list[Path] = []
    buffer: list[tuple[RowKey, bytes]] = []
    count = 0
    for row in rows:
        # Process rows inside the bounded spill sort loop.
        document = encode(row)
        encoded = canonical_json_bytes(document)
        buffer.append((key(document), encoded))
        count += 1
        if len(buffer) == maximum_rows_in_memory:
            # Handle the spill sort len(buffer) == maximum_rows_in_memory branch as a
            # distinct logical block.
            chunks.append(_flush_chunk(root, len(chunks), buffer))
            buffer = []
    if buffer or not chunks:
        chunks.append(_flush_chunk(root, len(chunks), buffer))

    pass_index = 0
    # Repeat the spill sort step only while len(chunks) > 1 remains true.
    while len(chunks) > 1:
        # Keep the len(chunks) > 1 loop body bounded within spill sort.
        merged: list[Path] = []
        for group_index, start in enumerate(range(0, len(chunks), maximum_open_files)):
            # Process maximum open files and chunks inside the bounded spill sort loop.
            group = chunks[start : start + maximum_open_files]
            destination = root / f"merge-{pass_index:04d}-{group_index:08d}.ndjson"
            _merge_chunks(group, destination, key)
            for path in group:
                path.unlink()
            # Invoke append for destination as a visible spill sort step.
            merged.append(destination)
        chunks = merged
        pass_index += 1
    return SpilledRows(chunks[0], count)


def _flush_chunk(
    # Keep the root input explicit in the flush chunk contract.
    root: Path,
    index: int,
    buffer: list[tuple[RowKey, bytes]],
) -> Path:
    # Execute the flush chunk workflow in explicit, reviewable steps.
    buffer.sort(key=lambda item: item[0])
    previous: RowKey | None = None
    path = root / f"chunk-{index:08d}.ndjson"
    with path.open("xb") as stream:
        # Keep open, xb and path active only for the bounded flush chunk operation.
        for row_key, encoded in buffer:
            # Process buffer inside the bounded flush chunk loop.
            if previous == row_key:
                raise SpillSortError("ML overlay row coordinates must be unique")
            stream.write(encoded)
            stream.write(b"\n")
            previous = row_key
    # Return the completed flush chunk result without a hidden fallback.
    return path


def _merge_chunks(
    sources: list[Path],
    destination: Path,
    key: Callable[[dict[str, object]], RowKey],
    # Close the merge chunks signature after its explicit inputs.
) -> None:
    # Execute the merge chunks workflow in explicit, reviewable steps.
    streams = [path.open("rb") for path in sources]
    heap: list[tuple[RowKey, bytes, int]] = []
    try:
        # Perform the protected merge chunks operation before explicit failure handling.
        for index, stream in enumerate(streams):
            # Process enumerate(streams) inside the bounded merge chunks loop.
            raw = stream.readline()
            if raw:
                # Handle the merge chunks raw branch as a distinct logical block.
                payload = raw.rstrip(b"\n")
                heapq.heappush(heap, (key(_document(payload)), payload, index))
        previous: RowKey | None = None
        with destination.open("xb") as output:
            # Keep open, xb and destination active only for the bounded merge chunks
            # operation.
            while heap:
                # Keep the heap loop body bounded within merge chunks.
                row_key, payload, index = heapq.heappop(heap)
                if previous == row_key:
                    raise SpillSortError("ML overlay row coordinates must be unique")
                output.write(payload)
                output.write(b"\n")
                # Assemble previous once so the merge chunks workflow shares one value.
                previous = row_key
                _push_next(heap, streams[index], index, key)
    finally:
        # Handle the cleanup path after the protected merge chunks operation.
        for stream in streams:
            stream.close()


def _push_next(
    heap: list[tuple[RowKey, bytes, int]],
    stream: IO[bytes],
    # Keep the index input explicit in the push next contract.
    index: int,
    key: Callable[[dict[str, object]], RowKey],
) -> None:
    # Execute the push next workflow in explicit, reviewable steps.
    raw = stream.readline()
    if not raw:
        return
    payload = raw.rstrip(b"\n")
    heapq.heappush(heap, (key(_document(payload)), payload, index))


# Define document as one focused operation with an explicit boundary.
def _document(payload: bytes) -> dict[str, object]:
    # Execute the document workflow in explicit, reviewable steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:  # pragma: no cover - writer-owned bytes
        raise SpillSortError("spilled ML row is invalid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value):
        raise SpillSortError("spilled ML row must be an object")
    document = cast(dict[str, object], value)
    if canonical_json_bytes(document) != payload:
        # Fail the document path with SpillSortError for spilled ml row is not canonical
        # json when payload, canonical json bytes and document is true; do not continue
        # ambiguously.
        raise SpillSortError("spilled ML row is not canonical JSON")
    return document


__all__ = ["SpillSortError", "SpilledRows", "spill_sort"]
