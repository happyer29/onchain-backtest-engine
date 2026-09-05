"""Deterministic in-memory ``SourceReader`` for tests and small examples."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from hashlib import sha256

# Import typing at the visible module dependency boundary.
from typing import Any

from backtest.adapters.source.common import SourceBatch
from backtest.application.models import (
    CapabilityDescriptor,
    ExtractionRequest,
    # Include source metadata so the models dependency remains explicit.
    SourceMetadata,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId


class InMemorySourceReader:
    """A strict fake that exercises the same bounded-read contract as SQL.

    Rows are never deduplicated.  Input order and multiplicity are preserved,
    which is important for sources whose event identity is only ambiguous or a
    candidate.
    """

    def __init__(
        self,
        metadata: SourceMetadata,
        rows: Mapping[CapabilityId, Sequence[Mapping[str, Any]]],
        *,
        # Keep the block ordinal columns input explicit in the init contract.
        block_ordinal_columns: Mapping[CapabilityId, str] | None = None,
        batch_size: int = 1024,
    ) -> None:
        # Execute the in memory source reader init workflow in explicit, reviewable steps.
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._batch_size = batch_size
        configured_block_columns = dict(block_ordinal_columns or {})
        self._metadata = _with_fake_source_digests(metadata, configured_block_columns)
        # Assemble self descriptors once so the in memory source reader init workflow
        # shares one value.
        self._descriptors = {
            descriptor.capability_id: descriptor for descriptor in self._metadata.capabilities
        }
        unknown = set(rows).difference(self._descriptors)
        if unknown:
            # Handle the in memory source reader init unknown branch as a distinct logical
            # block.
            names = ", ".join(sorted(capability.value for capability in unknown))
            raise ValueError(f"rows configured for unknown capabilities: {names}")
        self._rows: dict[CapabilityId, tuple[Mapping[str, Any], ...]] = {}
        self._block_ordinal_columns: dict[CapabilityId, str] = {}
        for capability_id, descriptor in self._descriptors.items():
            # Process self._descriptors.items() inside the bounded in memory source reader
            # init loop.
            block_column = configured_block_columns.get(
                capability_id,
                "block_ordinal",
            )
            if block_column not in descriptor.columns:
                # Fail the in memory source reader init path with ValueError for block
                # ordinal column and is not advertised when block column, columns and
                # descriptor is true; do not continue ambiguously.
                raise ValueError(f"block ordinal column {block_column!r} is not advertised")
            capability_rows = tuple(rows.get(capability_id, ()))
            for row in capability_rows:
                # Process capability_rows inside the bounded in memory source reader init
                # loop.
                missing = set(descriptor.mandatory_columns).difference(row)
                if missing:
                    raise ValueError(f"in-memory row misses mandatory columns: {sorted(missing)}")
                block_ordinal = row.get(block_column)
                if (
                    # Keep isinstance visible while evaluating the isinstance and block
                    # ordinal guard.
                    isinstance(block_ordinal, bool)
                    or not isinstance(block_ordinal, int)
                    or block_ordinal < 0
                ):
                    raise ValueError("in-memory row block ordinal must be a non-negative integer")
            # Assemble self rows[capability id] once so the in memory source reader init
            # workflow shares one value.
            self._rows[capability_id] = capability_rows
            self._block_ordinal_columns[capability_id] = block_column

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        # Execute the in memory source reader inspect metadata workflow in explicit,
        # reviewable steps.
        self._require_source(source_id)
        return self._metadata

    def list_capabilities(self, source_id: SourceId) -> tuple[CapabilityDescriptor, ...]:
        # Execute the in memory source reader list capabilities workflow in explicit,
        # reviewable steps.
        self._require_source(source_id)
        return self._metadata.capabilities

    def scan(self, request: ExtractionRequest) -> Iterator[SourceBatch]:
        # Execute the in memory source reader scan workflow in explicit, reviewable steps.
        descriptor = self._descriptor(request.shard.capability_id)
        columns = request.shard.columns
        _validate_projection(descriptor, columns)
        block_column = self._block_ordinal_columns[descriptor.capability_id]
        block_range = request.shard.block_range
        # Evaluate the complete in memory source reader scan network id, position schema
        # id and block range condition before guarded effects.
        if (
            block_range.network_id != self._metadata.network_id
            or block_range.position_schema_id != self._metadata.position_schema_id
        ):
            raise ValueError("requested shard uses a different chain identity")

        # Assemble selected once so the in memory source reader scan workflow shares one
        # value.
        selected: list[tuple[Any, ...]] = []
        for row in self._rows[descriptor.capability_id]:
            # Process self._rows[descriptor.capability_id] inside the bounded in memory
            # source reader scan loop.
            block_ordinal = row[block_column]
            if block_range.contains_block(block_ordinal):
                # Handle the in memory source reader scan contains block, block ordinal
                # and block range condition as a distinct block.
                try:
                    selected.append(tuple(row[column] for column in columns))
                except KeyError as error:
                    # Translate the KeyError failure through the in memory source reader
                    # scan boundary.
                    raise ValueError(
                        f"in-memory row misses projected column {error.args[0]!r}"
                    ) from None

        fingerprint = _fake_query_fingerprint(request)
        for offset in range(0, len(selected), self._batch_size):
            # Process batch size and selected inside the bounded in memory source reader
            # scan loop.
            yield SourceBatch(
                capability_id=descriptor.capability_id,
                covered_range=block_range,
                columns=columns,
                rows=tuple(selected[offset : offset + self._batch_size]),
                # Pass query fingerprint explicitly so SourceBatch receives a reviewable
                # capability id and batch size input in in memory source reader scan.
                query_fingerprint=fingerprint,
            )

    def _descriptor(self, capability_id: CapabilityId) -> CapabilityDescriptor:
        # Execute the in memory source reader descriptor workflow in explicit, reviewable
        # steps.
        try:
            return self._descriptors[capability_id]
        except KeyError:
            raise ValueError(f"unknown capability {capability_id}") from None

    def _require_source(self, source_id: SourceId) -> None:
        # Execute the in memory source reader require source workflow in explicit,
        # reviewable steps.
        if source_id != self._metadata.source_id:
            raise ValueError(f"unknown source {source_id}")


def _validate_projection(
    descriptor: CapabilityDescriptor,
    columns: tuple[str, ...],
    # Close the validate projection signature after its explicit inputs.
) -> None:
    # Execute the validate projection workflow in explicit, reviewable steps.
    if not columns:
        raise ValueError("source projection must not be empty")
    unknown = set(columns).difference(descriptor.columns)
    if unknown:
        raise ValueError(f"projection contains unadvertised columns: {sorted(unknown)}")
    # Assemble missing once so the validate projection workflow shares one value.
    missing = set(descriptor.mandatory_columns).difference(columns)
    if missing:
        raise ValueError(f"projection misses mandatory columns: {sorted(missing)}")


def _with_fake_source_digests(
    metadata: SourceMetadata,
    # Keep the block ordinal columns input explicit in the with fake source digests
    # contract.
    block_ordinal_columns: Mapping[CapabilityId, str],
) -> SourceMetadata:
    # Execute the with fake source digests workflow in explicit, reviewable steps.
    query_digest = metadata.query_template_digest or ContentDigest(
        sha256(b"in-memory-source-reader:v2:block-range").hexdigest()
    )
    mapping_digest = metadata.capability_mapping_digest
    if mapping_digest is None:
        # Handle the with fake source digests mapping_digest is None branch as a distinct
        # logical block.
        document = {
            "capabilities": [
                {
                    "capability_id": descriptor.capability_id.value,
                    "logical_columns": list(descriptor.columns),
                    # Register capability id through get so the document table remains
                    # scannable.
                    "logical_block_ordinal_column": block_ordinal_columns.get(
                        descriptor.capability_id,
                        "block_ordinal",
                    ),
                }
                # Keep the descriptor component named inside the document contract.
                for descriptor in metadata.capabilities
            ],
            "network_id": metadata.network_id.value,
            "position_schema_id": metadata.position_schema_id.value,
            "schema": "backtest.in-memory-source-mapping/v2",
            # Complete the document group only after its semantic components are visible.
        }
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            # Pass separators explicitly so encode receives a reviewable utf-8 input in
            # with fake source digests.
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        domain = b"backtest.in-memory-source-mapping.identity.v2\x00"
        mapping_digest = ContentDigest(sha256(domain + encoded).hexdigest())
    # Return the completed with fake source digests result without a hidden fallback.
    return replace(
        metadata,
        capability_mapping_digest=mapping_digest,
        query_template_digest=query_digest,
    )


# Define fake query fingerprint as one focused operation with an explicit boundary.
def _fake_query_fingerprint(request: ExtractionRequest) -> ContentDigest:
    # Execute the fake query fingerprint workflow in explicit, reviewable steps.
    material = "|".join(
        (
            request.dataset_spec_id.value,
            request.shard.capability_id.value,
            request.shard.block_range.network_id.value,
            # Pass request explicitly so join receives a reviewable , and value input in
            # fake query fingerprint.
            request.shard.block_range.position_schema_id.value,
            str(request.shard.block_range.from_block_ordinal),
            str(request.shard.block_range.to_block_ordinal),
            ",".join(request.shard.columns),
        )
        # Complete join only after its , and value inputs are visible in fake query
        # fingerprint.
    )
    return ContentDigest(f"sha256:{sha256(material.encode()).hexdigest()}")


__all__ = ["InMemorySourceReader"]
