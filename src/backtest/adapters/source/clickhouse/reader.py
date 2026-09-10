"""Read-only, bounded and streaming ClickHouse ``SourceReader``."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Iterator, Mapping, Sequence

# Import contextlib at the visible module dependency boundary.
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from itertools import pairwise

# Import typing at the visible module dependency boundary.
from typing import Any, Protocol

from backtest.adapters.source.clickhouse.pumpfun_copybuy import PumpfunCopyBuyQueryProfile
from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PumpfunIndexerV1Profile,
    PumpfunIndexerV1Query,
    # Pinned source profiles keep query reconstruction independent of caller SQL.
    registered_pumpfun_indexer_v1_profile,
)
from backtest.adapters.source.clickhouse.query import (
    BoundedQuery,
    ClickHouseCapability,
    # Hard query limits apply before the driver can begin streaming results.
    ClickHouseQueryPolicy,
    # Include build evidence query so the query dependency remains explicit.
    build_evidence_query,
    build_scan_query,
    clickhouse_capability_mapping_digest,
    metadata_query_templates,
    query_template_digest,
    # Close the query import after its required symbols are visible.
)
from backtest.adapters.source.common import SourceAdapterError, SourceBatch
from backtest.application.copy_source import CopySourceSelection
from backtest.application.models import (
    BoundedSourceEvidenceReceipt,
    # Evidence and extraction use distinct typed request contracts.
    BoundedSourceEvidenceRequest,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    EvidenceStatus,
    # Include extraction request so the models dependency remains explicit.
    ExtractionRequest,
    SourceColumn,
    SourceMetadata,
    SourceTable,
    build_bounded_source_evidence_receipt,
    # Close the models import after its required symbols are visible.
)
from backtest.domain.fidelity import (
    ChainFinality,
    IngestionCompleteness,
    SourceConsistency,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange

_EVIDENCE_COLUMNS: dict[CapabilityStream, tuple[str, ...]] = {
    CapabilityStream.BLOCK_CLOCK: (
        # Keep the block ordinal component named inside the evidence columns contract.
        "block_ordinal",
        "block_time",
        "transaction_count",
        "block_hash",
    ),
    # Keep the capability stream component named inside the evidence columns contract.
    CapabilityStream.TOKEN_LAUNCH: (
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        # Keep the transaction succeeded component named inside the evidence columns
        # contract.
        "transaction_succeeded",
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "block_ordinal",
        "transaction_index",
        # Keep the event index component named inside the evidence columns contract.
        "event_index",
        "signature",
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "block_ordinal",
        # Keep the transaction index component named inside the evidence columns contract.
        "transaction_index",
        "event_index",
        "signature",
    ),
}
# Bind evidence result domain once as an explicit module-level contract.
_EVIDENCE_RESULT_DOMAIN = b"backtest.clickhouse.bounded-evidence-result.v1\x00"
_EVIDENCE_MAX_CANONICAL_BYTES = 64 * 1024**2
_PUMPFUN_INDEXER_V1_EVIDENCE_MAX_BLOCK_SPAN = 4_096

_QUERY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


# Keep the query result contract and validation rules together.
class _QueryResult(Protocol):
    @property
    def result_rows(self) -> Sequence[Sequence[Any]]: ...

    def close(self) -> None: ...


class ClickHouseClientProtocol(Protocol):
    """Narrow SDK surface required by the read-only source adapter."""

    def query(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        # Close the query signature after its explicit inputs.
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> _QueryResult: ...

    def query_row_block_stream(
        # Keep the remaining query row block stream inputs visible at the click house
        # client protocol query row block stream boundary.
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        *,
        # Keep the query tz input explicit in the query row block stream contract.
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]: ...


class _StreamingQuery(Protocol):
    """Common immutable shape accepted by the SDK streaming seam."""

    @property
    def sql(self) -> str: ...

    @property
    def parameters(self) -> Mapping[str, Any]: ...

    @property
    def columns(self) -> tuple[str, ...]: ...

    @property
    def block_ordinal_column_index(self) -> int: ...

    @property
    def fingerprint(self) -> ContentDigest: ...


class ClickHouseSourceReader:
    """A source-bound adapter; connection credentials remain in bootstrap.

    The reader accepts an already-created client and never stores host,
    username or password fields itself.  Its repr is intentionally constant so
    accidental structured logging cannot serialize the client's connection.
    """

    __slots__ = (
        "_capabilities",
        "_client",
        "_policy",
        "_query_id_factory",
        # Keep the source id component named inside the slots contract.
        "_source_id",
    )

    def __init__(
        self,
        *,
        # Keep the client input explicit in the init contract.
        client: ClickHouseClientProtocol,
        source_id: SourceId,
        capabilities: Sequence[ClickHouseCapability],
        policy: ClickHouseQueryPolicy | None = None,
        query_id_factory: Callable[[str], str] | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the click house source reader init workflow in explicit, reviewable
        # steps.
        if not capabilities:
            raise ValueError("at least one ClickHouse capability is required")
        by_id = {capability.descriptor.capability_id: capability for capability in capabilities}
        if len(by_id) != len(capabilities):
            raise ValueError("ClickHouse capabilities must have unique logical IDs")
        # Assemble chain identities once so the click house source reader init workflow
        # shares one value.
        chain_identities = {(item.network_id, item.position_schema_id) for item in capabilities}
        if len(chain_identities) != 1:
            raise ValueError("ClickHouse capabilities must use one exact chain identity")
        self._client = client
        self._source_id = source_id
        # Assemble self capabilities once so the click house source reader init workflow
        # shares one value.
        self._capabilities = by_id
        self._policy = policy or ClickHouseQueryPolicy()
        self._query_id_factory = query_id_factory or _default_query_id

    def __repr__(self) -> str:
        # Execute the click house source reader repr workflow in explicit, reviewable
        # steps.
        return (
            "ClickHouseSourceReader("
            f"source_id={self._source_id.value!r}, "
            f"capabilities={len(self._capabilities)})"
        )

    # Define click house source reader list capabilities as one focused operation with an
    # explicit boundary.
    def list_capabilities(self, source_id: SourceId) -> tuple[CapabilityDescriptor, ...]:
        # Execute the click house source reader list capabilities workflow in explicit,
        # reviewable steps.
        self._require_source(source_id)
        return tuple(
            sorted(
                (item.descriptor for item in self._capabilities.values()),
                key=lambda descriptor: descriptor.capability_id.value,
                # Complete sorted only after its descriptor and values inputs are visible in
                # click house source reader list capabilities.
            )
        )

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        """Read only small ``system`` metadata and return no connection data."""

        self._require_source(source_id)
        version_sql, table_sql, columns_sql = metadata_query_templates()
        server_version = self._single_scalar(version_sql, {}, operation="inspect-version")
        if not isinstance(server_version, str) or not server_version.strip():
            raise SourceAdapterError("inspect-version")

        # Assemble tables once so the click house source reader inspect metadata workflow
        # shares one value.
        tables: list[SourceTable] = []
        physical_tables = sorted(
            {(item.database, item.table) for item in self._capabilities.values()}
        )
        for database, table in physical_tables:
            # Process physical_tables inside the bounded click house source reader inspect
            # metadata loop.
            parameters = {"database": database, "table": table}
            table_rows = self._small_query(
                table_sql,
                parameters,
                operation="inspect-table",
                # Complete _small_query only after its inspect-table and table sql inputs are
                # visible in click house source reader inspect metadata.
            )
            if len(table_rows) != 1 or len(table_rows[0]) != 3:
                raise SourceAdapterError("inspect-table")
            engine, partition_key, sorting_key = table_rows[0]
            if not all(isinstance(value, str) for value in table_rows[0]):
                # Fail the click house source reader inspect metadata path with
                # SourceAdapterError for inspect-table when isinstance, value and table
                # rows is true; do not continue ambiguously.
                raise SourceAdapterError("inspect-table")

            column_rows = self._small_query(
                columns_sql,
                parameters,
                operation="inspect-columns",
                # Complete _small_query only after its inspect-columns and columns sql inputs
                # are visible in click house source reader inspect metadata.
            )
            columns = _parse_columns(column_rows)
            configured_physical = {
                physical
                for capability in self._capabilities.values()
                # Keep the database component named inside the configured physical
                # contract.
                if capability.database == database and capability.table == table
                for physical in capability.logical_to_physical.values()
            }
            discovered = {column.name for column in columns}
            if not configured_physical.issubset(discovered):
                # Fail the click house source reader inspect metadata path with
                # SourceAdapterError for inspect-schema-drift when issubset, discovered
                # and configured physical is true; do not continue ambiguously.
                raise SourceAdapterError("inspect-schema-drift")

            tables.append(
                SourceTable(
                    name=f"{database}.{table}",
                    engine=engine,
                    # Pass partition key explicitly so SourceTable receives a reviewable
                    # value and database input in click house source reader inspect
                    # metadata.
                    partition_key=partition_key,
                    sorting_key=sorting_key,
                    columns=columns,
                )
            )

        # Return the completed click house source reader inspect metadata result without a
        # hidden fallback.
        return SourceMetadata(
            source_id=self._source_id,
            network_id=next(iter(self._capabilities.values())).network_id,
            position_schema_id=next(iter(self._capabilities.values())).position_schema_id,
            server_version=server_version.strip(),
            # Include tables in the completed click house source reader inspect metadata
            # result.
            tables=tuple(tables),
            capabilities=self.list_capabilities(source_id),
            capability_mapping_digest=clickhouse_capability_mapping_digest(
                tuple(self._capabilities.values())
            ),
            # Include query template digest in the completed click house source reader
            # inspect metadata result.
            query_template_digest=query_template_digest(),
        )

    def scan(self, request: ExtractionRequest) -> Iterator[SourceBatch]:
        # Execute the click house source reader scan workflow in explicit, reviewable
        # steps.
        try:
            capability = self._capabilities[request.shard.capability_id]
        except KeyError:
            raise ValueError(f"unknown capability {request.shard.capability_id}") from None

        bounded_query = build_scan_query(capability, request, self._policy)
        # Assemble query id once so the click house source reader scan workflow shares one
        # value.
        query_id = self._safe_query_id("scan")
        settings = self._policy.scan_settings(request.query_limits)
        max_rows = int(settings["max_result_rows"])
        yield from self._stream_batches(
            bounded_query,
            capability_id=request.shard.capability_id,
            block_range=request.shard.block_range,
            settings=settings,
            query_id=query_id,
            max_rows=max_rows,
            operation="scan",
        )

    def scan_pumpfun_indexer_v1(
        self,
        request: ExtractionRequest,
        query: PumpfunIndexerV1Query,
    ) -> Iterator[SourceBatch]:
        """Execute one exact prebuilt Pump.fun profile query for a planned shard."""

        self._validate_pumpfun_indexer_v1_query(
            capability_id=request.shard.capability_id,
            block_range=request.shard.block_range,
            decision_range=request.decision_range,
            query=query,
        )
        settings = self._policy.scan_settings(request.query_limits)
        yield from self._stream_batches(
            query,
            capability_id=request.shard.capability_id,
            block_range=request.shard.block_range,
            settings=settings,
            query_id=self._safe_query_id("scan"),
            max_rows=int(settings["max_result_rows"]),
            operation="scan",
        )

    def stream_pumpfun_indexer_v1_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
        *,
        capability_id: CapabilityId,
        block_range: BlockRange,
        query: PumpfunIndexerV1Query,
    ) -> Iterator[SourceBatch]:
        """Stream one fixed-profile evidence subrange without materializing its rows."""

        self._require_source(request.source_id)
        _require_contained_subrange(block_range, request.block_range)
        maximum_span = min(
            _PUMPFUN_INDEXER_V1_EVIDENCE_MAX_BLOCK_SPAN,
            self._policy.evidence_max_block_span,
        )
        if block_range.span > maximum_span:
            raise ValueError("Pump.fun evidence subrange exceeds its hard span limit")
        capability, profile = self._validate_pumpfun_indexer_v1_query(
            capability_id=capability_id,
            block_range=block_range,
            decision_range=request.decision_range,
            query=query,
        )
        mapping_digest = clickhouse_capability_mapping_digest(tuple(self._capabilities.values()))
        if request.capability_mapping_digest != mapping_digest:
            raise ValueError("evidence request uses a different capability mapping contract")
        if request.query_template_digest != profile.template_digest:
            raise ValueError("evidence request uses a different Pump.fun query-template contract")
        settings = self._policy.evidence_settings(request.query_limits)
        operation = f"evidence_{capability.descriptor.stream.value.lower()}"
        yield from self._stream_batches(
            query,
            capability_id=capability_id,
            block_range=block_range,
            settings=settings,
            query_id=self._safe_query_id(operation),
            max_rows=int(settings["max_result_rows"]),
            operation="evidence-query",
        )

    def stream_pumpfun_copybuy_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
        *,
        selection: CopySourceSelection,
        # Each candidate or market query carries its own explicit capability and block range.
        capability_id: CapabilityId,
        block_range: BlockRange,
        query: PumpfunIndexerV1Query,
        # Candidate enumeration uses a separate fixed query on the same physical source.
        candidates: bool = False,
    ) -> Iterator[SourceBatch]:
        """Read one bounded copy evidence shard after rebuilding its exact fixed query."""
        self._require_source(request.source_id)
        _require_contained_subrange(block_range, request.block_range)
        if (
            selection.decision_range != request.decision_range
            or selection.history_range.from_block_ordinal != request.block_range.from_block_ordinal
            # A different lookback cannot reuse the decision range as a substitute for initial
            # state.
        ):
            raise ValueError("copy evidence selection differs from request ranges")
        # Hard query span and row/memory/time limits apply to the independent enumeration too.
        if block_range.span > min(
            _PUMPFUN_INDEXER_V1_EVIDENCE_MAX_BLOCK_SPAN, self._policy.evidence_max_block_span
        ):
            raise ValueError("copy evidence subrange exceeds its hard span limit")
        # Rebuild the query from fixed operands before accepting its SQL or fingerprint.
        profile = self._validate_pumpfun_copybuy_query(
            selection, capability_id, block_range, query, candidates=candidates
        )
        mapping = clickhouse_capability_mapping_digest(tuple(self._capabilities.values()))
        if (
            # Both physical mapping and query profile must match the requested evidence.
            request.capability_mapping_digest != mapping
            or request.query_template_digest != profile.template_digest
        ):
            raise ValueError("copy evidence mapping or query template differs from reader")
        # Only secret-free operation labels enter query IDs and error messages.
        settings = self._policy.evidence_settings(request.query_limits)
        yield from self._stream_batches(
            query,
            capability_id=capability_id,
            block_range=block_range,
            # Every bounded read receives a safe query identifier and a hard returned-row cap.
            settings=settings,
            query_id=self._safe_query_id("copy_evidence"),
            max_rows=int(settings["max_result_rows"]),
            operation="copy-evidence-query",
        )

    def scan_pumpfun_copybuy(
        self,
        request: ExtractionRequest,
        query: PumpfunIndexerV1Query,
        selection: CopySourceSelection,
        # Extraction accepts only the copy selection already bound to its DatasetSpec.
    ) -> Iterator[SourceBatch]:
        """Prepare a planned copy shard through the same bounded streaming source adapter."""
        if request.decision_range != selection.decision_range:
            raise ValueError("copy extraction decision range differs from its selection")
        self._validate_pumpfun_copybuy_query(
            selection,
            request.shard.capability_id,
            # The exact shard bounds are checked again when reconstructing the extraction query.
            request.shard.block_range,
            query,
            candidates=False,
        )
        # Reader policy enforces its own limits independently of composition input.
        settings = self._policy.scan_settings(request.query_limits)
        yield from self._stream_batches(
            query,
            capability_id=request.shard.capability_id,
            block_range=request.shard.block_range,
            # Extraction settings retain row and memory limits independently of evidence reads.
            settings=settings,
            query_id=self._safe_query_id("copy_scan"),
            max_rows=int(settings["max_result_rows"]),
            operation="copy-scan",
        )

    def _validate_pumpfun_copybuy_query(
        self,
        selection: CopySourceSelection,
        capability_id: CapabilityId,
        block_range: BlockRange,
        # Caller-supplied SQL is accepted only if it equals the rebuilt fixed query.
        query: PumpfunIndexerV1Query,
        *,
        candidates: bool,
    ) -> PumpfunCopyBuyQueryProfile:
        """No arbitrary or caller-modified SQL can pass this strategy-specific source seam."""
        capability = self._capabilities.get(capability_id)
        physical = registered_pumpfun_indexer_v1_profile(tuple(self._capabilities.values()))
        if capability is None or physical is None:
            raise ValueError("copy source requires the exact audited physical profile")
        # A numeric slot range from another chain cannot query this Solana source.
        if (capability.network_id, capability.position_schema_id) != (
            block_range.network_id,
            block_range.position_schema_id,
        ):
            raise ValueError("copy source range has a different network or position schema")
        # The query profile is instantiated only after immutable chain compatibility is established.
        profile = PumpfunCopyBuyQueryProfile(selection, physical)
        if candidates:
            if capability.descriptor.stream is not CapabilityStream.PUMP_CURVE_TRADE:
                raise ValueError("copy candidate enumeration requires the trade capability")
            # The independent query has no creation JOIN or inferred actor mapping.
            expected = profile.build_candidates(
                database=capability.database, block_range=block_range, policy=self._policy
            )
        else:
            expected = profile.build_query(
                # Non-candidate reads retain the authoritative stream and exact history interval.
                stream=capability.descriptor.stream,
                database=capability.database,
                block_range=block_range,
                policy=self._policy,
            )
        # Any SQL, column or parameter drift rejects the call before network access.
        if query != expected:
            raise ValueError("copy query does not match exact reader operands")
        return profile

    # Define click house source reader inspect bounded evidence as one focused operation
    # with an explicit boundary.
    def inspect_bounded_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        """Evaluate bounded checks without upgrading non-derivable claims."""

        self._require_source(request.source_id)
        by_stream: dict[CapabilityStream, ClickHouseCapability] = {}
        for capability in self._capabilities.values():
            # Process self._capabilities.values() inside the bounded click house source
            # reader inspect bounded evidence loop.
            stream = capability.descriptor.stream
            if stream in by_stream:
                raise SourceAdapterError("evidence-capability-structure")
            by_stream[stream] = capability
        if set(by_stream) != set(CapabilityStream):
            # Fail the click house source reader inspect bounded evidence path with
            # SourceAdapterError for evidence-capability-structure when by stream and
            # capability stream is true; do not continue ambiguously.
            raise SourceAdapterError("evidence-capability-structure")

        settings = self._policy.evidence_settings(request.query_limits)
        maximum_rows = int(settings["max_result_rows"])
        observations: dict[
            CapabilityStream,
            # Keep the tuple component named inside the observations contract.
            tuple[ClickHouseCapability, BoundedQuery, tuple[tuple[Any, ...], ...], ContentDigest],
        ] = {}
        for stream in CapabilityStream:
            # Process CapabilityStream inside the bounded click house source reader
            # inspect bounded evidence loop.
            capability = by_stream[stream]
            query = build_evidence_query(
                capability,
                request.block_range,
                _EVIDENCE_COLUMNS[stream],
                # Pass self explicitly so build_evidence_query receives a reviewable block
                # range and policy input in click house source reader inspect bounded
                # evidence.
                self._policy,
            )
            query_id = self._safe_query_id(f"evidence_{stream.value.lower()}")
            rows = self._read_bounded_rows(
                query,
                # Pass request explicitly so _read_bounded_rows receives a reviewable
                # block range and query input in click house source reader inspect bounded
                # evidence.
                request.block_range,
                settings=settings,
                query_id=query_id,
                max_rows=maximum_rows,
            )
            # Assemble observations[stream] once so the click house source reader inspect
            # bounded evidence workflow shares one value.
            observations[stream] = (
                capability,
                query,
                rows,
                _evidence_rows_digest(query.columns, rows),
                # Complete the observations[stream] group only after its semantic components
                # are visible.
            )

        block_query = observations[CapabilityStream.BLOCK_CLOCK][1]
        block_rows = observations[CapabilityStream.BLOCK_CLOCK][2]
        block_digest = observations[CapabilityStream.BLOCK_CLOCK][3]
        block_counts = _block_transaction_counts(block_query.columns, block_rows)
        # Assemble mapping digest once so the click house source reader inspect bounded
        # evidence workflow shares one value.
        mapping_digest = clickhouse_capability_mapping_digest(tuple(self._capabilities.values()))
        template_digest = query_template_digest()
        receipts: list[BoundedSourceEvidenceReceipt] = []
        for stream in CapabilityStream:
            # Process CapabilityStream inside the bounded click house source reader
            # inspect bounded evidence loop.
            capability, query, rows, result_digest = observations[stream]
            related_queries: tuple[ContentDigest, ...] = (query.fingerprint,)
            related_results: tuple[tuple[ContentDigest, ContentDigest], ...] = (
                (query.fingerprint, result_digest),
            )
            # Evaluate the complete click house source reader inspect bounded evidence
            # stream, block clock and capability stream condition before guarded effects.
            if stream is not CapabilityStream.BLOCK_CLOCK:
                # Handle the click house source reader inspect bounded evidence stream,
                # block clock and capability stream condition as a distinct block.
                related_queries = (block_query.fingerprint, query.fingerprint)
                related_results = (
                    (block_query.fingerprint, block_digest),
                    (query.fingerprint, result_digest),
                )
            # Assemble proofs once so the click house source reader inspect bounded
            # evidence workflow shares one value.
            proofs = _derive_proofs(stream, query.columns, rows, block_counts)
            cut = CapabilityCutEvidence(
                capability_id=capability.descriptor.capability_id,
                block_range=request.block_range,
                snapshot_cut_to_block=request.block_range.to_block_ordinal,
                # Pass chain finality explicitly so CapabilityCutEvidence receives a
                # reviewable capability id and descriptor input in click house source
                # reader inspect bounded evidence.
                chain_finality=ChainFinality.UNKNOWN,
                ingestion_watermark_to_block=None,
                completeness=IngestionCompleteness.UNKNOWN,
                consistency=SourceConsistency.UNKNOWN,
                upstream_revision=None,
                # Complete CapabilityCutEvidence only after its capability id and descriptor
                # inputs are visible in click house source reader inspect bounded evidence.
            )
            receipts.append(
                build_bounded_source_evidence_receipt(
                    source_id=self._source_id,
                    capability_id=capability.descriptor.capability_id,
                    # Pass protocol version explicitly so
                    # build_bounded_source_evidence_receipt receives a reviewable source
                    # id and capability id input in click house source reader inspect
                    # bounded evidence.
                    protocol_version=capability.descriptor.protocol_version,
                    capability_schema_version=capability.descriptor.schema_version,
                    capability_mapping_digest=mapping_digest,
                    query_template_digest=template_digest,
                    projector_digest=request.projector_digest,
                    normalizer_digest=request.normalizer_digest,
                    cut_evidence=cut,
                    decision_range=request.decision_range,
                    # Pass proofs explicitly so build_bounded_source_evidence_receipt
                    # receives a reviewable source id and capability id input in click
                    # house source reader inspect bounded evidence.
                    proofs=proofs,
                    # Generic evidence never promotes fidelity.  Its receipt records the
                    # same static UNKNOWN contract advertised by the descriptor.
                    source_fidelity=capability.descriptor.fidelity,
                    query_fingerprints=tuple(
                        sorted(set(related_queries), key=lambda item: item.hex)
                    ),
                    result_digest=_combined_result_digest(related_results),
                    # Pass observed rows explicitly to append for source id and capability
                    # id.
                    observed_rows=len(rows),
                )
            )
        return tuple(
            sorted(
                # Pass receipts explicitly so sorted receives a reviewable value and
                # protocol version input in click house source reader inspect bounded
                # evidence.
                receipts,
                key=lambda item: (
                    item.capability_id.value,
                    item.protocol_version,
                    item.capability_schema_version,
                    # Complete sorted only after its value and protocol version inputs are
                    # visible in click house source reader inspect bounded evidence.
                ),
            )
        )

    def _read_bounded_rows(
        self,
        # Keep the bounded query input explicit in the read bounded rows contract.
        bounded_query: BoundedQuery,
        block_range: BlockRange,
        *,
        settings: Mapping[str, Any],
        query_id: str,
        # Keep the max rows input explicit in the read bounded rows contract.
        max_rows: int,
    ) -> tuple[tuple[Any, ...], ...]:
        # Execute the click house source reader read bounded rows workflow in explicit,
        # reviewable steps.
        failure = False
        selected: list[tuple[Any, ...]] = []
        try:
            # Perform the protected click house source reader read bounded rows operation
            # before explicit failure handling.
            context = self._client.query_row_block_stream(
                bounded_query.sql,
                parameters=dict(bounded_query.parameters),
                settings=settings,
                query_tz="UTC",
                # Pass query id explicitly so query_row_block_stream receives a reviewable
                # utc and query id input in click house source reader read bounded rows.
                transport_settings={"query_id": query_id},
            )
            with context as blocks:
                # Keep context active only for the bounded click house source reader read
                # bounded rows operation.
                for block in blocks:
                    # Process blocks inside the bounded click house source reader read
                    # bounded rows loop.
                    rows = tuple(tuple(row) for row in block)
                    if len(selected) + len(rows) > max_rows:
                        # Handle the click house source reader read bounded rows
                        # len(selected) + len(rows) > max_rows branch as a distinct
                        # logical block.
                        failure = True
                        break
                    _validate_bounded_rows(
                        rows,
                        width=len(bounded_query.columns),
                        # Pass block ordinal index explicitly so _validate_bounded_rows
                        # receives a reviewable columns and block ordinal column index
                        # input in click house source reader read bounded rows.
                        block_ordinal_index=bounded_query.block_ordinal_column_index,
                        block_range=block_range,
                    )
                    selected.extend(rows)
        except Exception:
            # Assemble failure once so the click house source reader read bounded rows
            # workflow shares one value.
            failure = True
        if failure:
            raise SourceAdapterError("evidence-query", query_id)
        return tuple(selected)

    def _stream_batches(
        # Keep the remaining stream batches inputs visible at the click house source
        # reader stream batches boundary.
        self,
        bounded_query: _StreamingQuery,
        *,
        capability_id: CapabilityId,
        block_range: BlockRange,
        settings: Mapping[str, Any],
        # Keep the query id input explicit in the stream batches contract.
        query_id: str,
        max_rows: int,
        operation: str,
    ) -> Iterator[SourceBatch]:
        # Execute the click house source reader stream batches workflow in explicit,
        # reviewable steps.
        failure = False
        total_rows = 0
        try:
            # Perform the protected click house source reader stream batches operation
            # before explicit failure handling.
            context = self._client.query_row_block_stream(
                bounded_query.sql,
                parameters=_stream_driver_parameters(bounded_query),
                settings=settings,
                query_tz="UTC",
                # Pass query id explicitly so query_row_block_stream receives a reviewable
                # utc and query id input in click house source reader stream batches.
                transport_settings={"query_id": query_id},
            )
            with context as blocks:
                # Keep context active only for the bounded click house source reader
                # stream batches operation.
                for block in blocks:
                    # Process blocks inside the bounded click house source reader stream
                    # batches loop.
                    rows = tuple(tuple(row) for row in block)
                    if not rows:
                        continue
                    total_rows += len(rows)
                    if total_rows > max_rows:
                        # Handle the click house source reader stream batches total_rows >
                        # max_rows branch as a distinct logical block.
                        failure = True
                        break
                    _validate_bounded_rows(
                        rows,
                        width=len(bounded_query.columns),
                        # Pass block ordinal index explicitly so _validate_bounded_rows
                        # receives a reviewable columns and block ordinal column index
                        # input in click house source reader stream batches.
                        block_ordinal_index=bounded_query.block_ordinal_column_index,
                        block_range=block_range,
                    )
                    yield SourceBatch(
                        capability_id=capability_id,
                        # Pass covered range explicitly so SourceBatch receives a
                        # reviewable capability id and shard input in click house source
                        # reader stream batches.
                        covered_range=block_range,
                        columns=bounded_query.columns,
                        rows=rows,
                        query_fingerprint=bounded_query.fingerprint,
                    )
        # Translate exception through the click house source reader stream batches
        # boundary without hiding other errors.
        except Exception:
            # Do not retain or chain a driver error that may include its URL.
            failure = True
        if failure:
            raise SourceAdapterError(operation, query_id)

    def _validate_pumpfun_indexer_v1_query(
        self,
        *,
        capability_id: CapabilityId,
        block_range: BlockRange,
        decision_range: BlockRange,
        query: PumpfunIndexerV1Query,
    ) -> tuple[ClickHouseCapability, PumpfunIndexerV1Profile]:
        """Bind a fixed query to this reader, capability and exact range operands."""

        if not isinstance(query, PumpfunIndexerV1Query):
            raise TypeError("query must be a PumpfunIndexerV1Query")
        try:
            capability = self._capabilities[capability_id]
        except KeyError:
            raise ValueError(f"unknown capability {capability_id}") from None
        profile = registered_pumpfun_indexer_v1_profile(tuple(self._capabilities.values()))
        if profile is None:
            raise ValueError("reader does not have the Pump.fun indexer v1 profile installed")
        expected = profile.build_query(
            stream=capability.descriptor.stream,
            database=capability.database,
            block_range=block_range,
            decision_range=decision_range,
            policy=self._policy,
        )
        if query != expected:
            raise ValueError("prebuilt Pump.fun query does not match the exact reader operands")
        return capability, profile

    def _single_scalar(
        self,
        # Keep the sql input explicit in the single scalar contract.
        sql: str,
        parameters: Mapping[str, Any],
        *,
        operation: str,
    ) -> Any:
        # Execute the click house source reader single scalar workflow in explicit,
        # reviewable steps.
        rows = self._small_query(sql, parameters, operation=operation)
        if len(rows) != 1 or len(rows[0]) != 1:
            raise SourceAdapterError(operation)
        return rows[0][0]

    def _small_query(
        # Keep the remaining small query inputs visible at the click house source reader
        # small query boundary.
        self,
        sql: str,
        parameters: Mapping[str, Any],
        *,
        operation: str,
        # Keep the tuple input explicit in the small query contract.
    ) -> tuple[tuple[Any, ...], ...]:
        # Execute the click house source reader small query workflow in explicit,
        # reviewable steps.
        query_id = self._safe_query_id(operation)
        result: _QueryResult | None = None
        failure = False
        rows: tuple[tuple[Any, ...], ...] = ()
        try:
            # Perform the protected click house source reader small query operation before
            # explicit failure handling.
            result = self._client.query(
                sql,
                parameters=dict(parameters),
                settings=self._policy.metadata_settings(),
                query_tz="UTC",
                # Pass query id explicitly so query receives a reviewable utc and query id
                # input in click house source reader small query.
                transport_settings={"query_id": query_id},
            )
            rows = tuple(tuple(row) for row in result.result_rows)
        except Exception:
            failure = True
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            # Handle the cleanup path after the protected click house source reader small
            # query operation.
            if result is not None:
                # Handle the click house source reader small query result is not None
                # branch as a distinct logical block.
                try:
                    result.close()
                except Exception:
                    failure = True
        if failure:
            # Fail the click house source reader small query path with SourceAdapterError
            # for operation and query id when failure is true; do not continue
            # ambiguously.
            raise SourceAdapterError(operation, query_id)
        return rows

    def _safe_query_id(self, operation: str) -> str:
        # Execute the click house source reader safe query id workflow in explicit,
        # reviewable steps.
        query_id = self._query_id_factory(operation)
        if not isinstance(query_id, str) or _QUERY_ID_RE.fullmatch(query_id) is None:
            raise ValueError("query ID factory returned an unsafe identifier")
        return query_id

    def _require_source(self, source_id: SourceId) -> None:
        # Execute the click house source reader require source workflow in explicit,
        # reviewable steps.
        if source_id != self._source_id:
            raise ValueError(f"unknown source {source_id}")


def _stream_driver_parameters(query: _StreamingQuery) -> dict[str, Any]:
    """Immutable copy wallet tuples need the driver's Array(String) wire representation."""
    parameters = dict(query.parameters)
    wallets = parameters.get("copy_signing_wallets")
    if wallets is not None:
        # The fixed query builder validates these addresses before fingerprinting them.
        if not isinstance(wallets, tuple) or not all(isinstance(value, str) for value in wallets):
            raise ValueError("copy signing wallets require an immutable tuple")
        parameters["copy_signing_wallets"] = list(wallets)
    return parameters


def _parse_columns(rows: Sequence[Sequence[Any]]) -> tuple[SourceColumn, ...]:
    # Execute the parse columns workflow in explicit, reviewable steps.
    columns: list[SourceColumn] = []
    for row in rows:
        # Process rows inside the bounded parse columns loop.
        if len(row) != 2 or not all(isinstance(value, str) for value in row):
            raise SourceAdapterError("inspect-columns")
        name, type_name = row
        columns.append(
            SourceColumn(
                # Pass name explicitly so SourceColumn receives a reviewable nullable( and
                # startswith input in parse columns.
                name=name,
                type_name=type_name,
                nullable=type_name.startswith("Nullable("),
            )
        )
    # Guard this path with not columns before applying effects.
    if not columns:
        raise SourceAdapterError("inspect-columns")
    if len({column.name for column in columns}) != len(columns):
        raise SourceAdapterError("inspect-columns")
    return tuple(columns)


# Define validate bounded rows as one focused operation with an explicit boundary.
def _validate_bounded_rows(
    rows: tuple[tuple[Any, ...], ...],
    *,
    width: int,
    block_ordinal_index: int,
    # Keep the block range input explicit in the validate bounded rows contract.
    block_range: BlockRange,
) -> None:
    # Execute the validate bounded rows workflow in explicit, reviewable steps.
    for row in rows:
        # Process rows inside the bounded validate bounded rows loop.
        if len(row) != width:
            raise ValueError("ClickHouse returned a row with an unexpected width")
        block_ordinal = row[block_ordinal_index]
        if isinstance(block_ordinal, bool) or not isinstance(block_ordinal, int):
            raise ValueError("ClickHouse returned a non-integer block ordinal")
        # Evaluate the complete validate bounded rows contains block, block ordinal and
        # block range condition before guarded effects.
        if not block_range.contains_block(block_ordinal):
            raise ValueError("ClickHouse returned a row outside the requested shard")


def _require_contained_subrange(candidate: BlockRange, outer: BlockRange) -> None:
    """Require an evidence shard to be a typed half-open subset of its request."""

    if not isinstance(candidate, BlockRange):
        raise TypeError("evidence subrange must be a BlockRange")
    if (
        candidate.network_id != outer.network_id
        or candidate.position_schema_id != outer.position_schema_id
        or candidate.from_block_ordinal < outer.from_block_ordinal
        or candidate.to_block_ordinal > outer.to_block_ordinal
    ):
        raise ValueError("evidence subrange is outside the bounded evidence request")


def _derive_proofs(
    stream: CapabilityStream,
    columns: tuple[str, ...],
    # Keep the rows input explicit in the derive proofs contract.
    rows: tuple[tuple[Any, ...], ...],
    block_counts: Mapping[int, int],
) -> CapabilityProofs:
    # Execute the derive proofs workflow in explicit, reviewable steps.
    proofs = CapabilityProofs()
    if stream is CapabilityStream.BLOCK_CLOCK:
        # Handle the derive proofs stream is CapabilityStream.BLOCK_CLOCK branch as a
        # distinct logical block.
        resolution, monotone = _block_time_statuses(columns, rows)
        return replace(
            proofs,
            block_time_second_resolution=resolution,
            block_time_monotone=monotone,
            # Complete replace only after its proofs and resolution inputs are visible in
            # derive proofs.
        )
    transaction_status = _transaction_index_status(columns, rows, block_counts)
    proofs = replace(proofs, global_zero_based_transaction_index=transaction_status)
    if stream is CapabilityStream.TOKEN_LAUNCH:
        # Handle the derive proofs stream, token launch and capability stream condition as
        # a distinct block.
        success_index = columns.index("transaction_succeeded")
        success_values = tuple(row[success_index] for row in rows)
        if not success_values:
            success_status = EvidenceStatus.UNKNOWN
        # Handle the derive proofs complement of not success_values explicitly.
        elif all(type(value) is bool and value for value in success_values):
            success_status = EvidenceStatus.PROVEN
        else:
            success_status = EvidenceStatus.REFUTED
        proofs = replace(proofs, launch_transaction_success_exact=success_status)
    # Return the completed derive proofs result without a hidden fallback.
    return proofs


def _block_transaction_counts(
    columns: tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...],
) -> dict[int, int]:
    # Execute the block transaction counts workflow in explicit, reviewable steps.
    block_index = columns.index("block_ordinal")
    count_index = columns.index("transaction_count")
    counts: dict[int, int] = {}
    invalid: set[int] = set()
    for row in rows:
        # Process rows inside the bounded block transaction counts loop.
        block = row[block_index]
        count = row[count_index]
        if type(block) is not int or block < 0:
            continue
        if type(count) is not int or count < 0 or block in counts:
            # Handle the block transaction counts count, block and counts condition as a
            # distinct block.
            invalid.add(block)
            counts.pop(block, None)
            continue
        if block not in invalid:
            counts[block] = count
    # Return the completed block transaction counts result without a hidden fallback.
    return counts


def _transaction_index_status(
    columns: tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...],
    block_counts: Mapping[int, int],
    # Keep the evidence status input explicit in the transaction index status contract.
) -> EvidenceStatus:
    # Execute the transaction index status workflow in explicit, reviewable steps.
    if not rows:
        return EvidenceStatus.UNKNOWN
    block_index = columns.index("block_ordinal")
    transaction_index = columns.index("transaction_index")
    event_index = columns.index("event_index")
    # Traverse rows explicitly so each transaction index status iteration remains
    # traceable.
    for row in rows:
        # Process rows inside the bounded transaction index status loop.
        block = row[block_index]
        transaction = row[transaction_index]
        event = row[event_index]
        if (
            type(block) is not int
            # Keep type visible while evaluating the transaction, event and block guard.
            or type(transaction) is not int
            or type(event) is not int
            or transaction < 0
            or event < 0
            or block not in block_counts
            # Keep transaction visible while evaluating the transaction, event and block
            # guard.
            or transaction >= block_counts[block]
        ):
            return EvidenceStatus.REFUTED
    # Range checks can refute a claimed global position, but cannot prove that
    # the source index was derived from the full failed/vote-inclusive order.
    return EvidenceStatus.UNKNOWN


def _block_time_statuses(
    columns: tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...],
) -> tuple[EvidenceStatus, EvidenceStatus]:
    # Execute the block time statuses workflow in explicit, reviewable steps.
    if not rows:
        return EvidenceStatus.UNKNOWN, EvidenceStatus.UNKNOWN
    block_index = columns.index("block_ordinal")
    time_index = columns.index("block_time")
    converted: list[tuple[int, int]] = []
    # Traverse rows explicitly so each block time statuses iteration remains traceable.
    for row in rows:
        # Process rows inside the bounded block time statuses loop.
        block = row[block_index]
        time_ns = _second_resolution_time_ns(row[time_index])
        if type(block) is not int or block < 0 or time_ns is None:
            return EvidenceStatus.REFUTED, EvidenceStatus.REFUTED
        converted.append((block, time_ns))
    # Invoke sort as a visible step within the block time statuses workflow.
    converted.sort()
    if len({block for block, _ in converted}) != len(converted):
        return EvidenceStatus.PROVEN, EvidenceStatus.REFUTED
    monotone = all(
        current_time <= next_time
        # Keep the converted pairwise step visible while building monotone.
        for (_, current_time), (_, next_time) in pairwise(converted)
        # Complete all only after its pairwise and current time inputs are visible in block
        # time statuses.
    )
    return (
        EvidenceStatus.PROVEN,
        EvidenceStatus.PROVEN if monotone else EvidenceStatus.REFUTED,
    )


# Define second resolution time ns as one focused operation with an explicit boundary.
def _second_resolution_time_ns(value: object) -> int | None:
    # Execute the second resolution time ns workflow in explicit, reviewable steps.
    if type(value) is int:
        return value if value >= 0 and value % 1_000_000_000 == 0 else None
    if isinstance(value, datetime):
        # Handle the second resolution time ns isinstance(value, datetime) branch as a
        # distinct logical block.
        if value.tzinfo is None or value.utcoffset() is None or value.microsecond != 0:
            return None
        return int(value.timestamp()) * 1_000_000_000
    return None


def _evidence_rows_digest(
    # Keep the columns input explicit in the evidence rows digest contract.
    columns: tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...],
) -> ContentDigest:
    # Execute the evidence rows digest workflow in explicit, reviewable steps.
    encoded_rows: list[bytes] = []
    total_bytes = 0
    for row in rows:
        # Process rows inside the bounded evidence rows digest loop.
        encoded = json.dumps(
            [_canonical_evidence_value(value) for value in row],
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            # Complete encode only after its utf-8 inputs are visible in evidence rows digest.
        ).encode("utf-8")
        total_bytes += len(encoded)
        if total_bytes > _EVIDENCE_MAX_CANONICAL_BYTES:
            raise ValueError("bounded evidence result exceeds local byte limit")
        encoded_rows.append(encoded)
    # Invoke sort as a visible step within the evidence rows digest workflow.
    encoded_rows.sort()
    digest = sha256(_EVIDENCE_RESULT_DOMAIN)
    digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
    for encoded in encoded_rows:
        # Process encoded_rows inside the bounded evidence rows digest loop.
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return ContentDigest(digest.hexdigest())


def _canonical_evidence_value(value: object) -> object:
    # Execute the canonical evidence value workflow in explicit, reviewable steps.
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, bytes):
        # Return the completed canonical evidence value result without a hidden fallback.
        return {"bytes": value.hex()}
    raise ValueError("bounded evidence returned an unsupported value type")


def _combined_result_digest(
    values: tuple[tuple[ContentDigest, ContentDigest], ...],
) -> ContentDigest:
    # Execute the combined result digest workflow in explicit, reviewable steps.
    material = json.dumps(
        sorted((query.hex, result.hex) for query, result in values),
        separators=(",", ":"),
    ).encode("ascii")
    return ContentDigest(sha256(_EVIDENCE_RESULT_DOMAIN + material).hexdigest())


# Define default query id as one focused operation with an explicit boundary.
def _default_query_id(operation: str) -> str:
    # Execute the default query id workflow in explicit, reviewable steps.
    safe_operation = operation.replace("-", "_")
    if _QUERY_ID_RE.fullmatch(safe_operation) is None:
        raise ValueError("unsafe query operation")
    return f"bt_{safe_operation}_{secrets.token_hex(12)}"


__all__ = ["ClickHouseClientProtocol", "ClickHouseSourceReader"]
