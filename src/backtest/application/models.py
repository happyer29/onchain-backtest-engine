"""Immutable application DTOs.

The module intentionally uses only the Python standard library and domain
types.  Transport, database and columnar-library objects must be converted at
an adapter boundary before they enter these contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# Import hashlib at the visible module dependency boundary.
from hashlib import sha256
from itertools import pairwise

from backtest.application.canonical_json import (
    canonicalize_job_payload,
    resolved_job_spec_hex,
    # Close the canonical json import after its required symbols are visible.
)
from backtest.application.source_evidence import (
    LaunchUniverseEvidence,
    PumpfunSnipingSourceEvidenceBinding,
    SkippedSlotSentinelEvidence,
    TerminalLifecycleOrderingEvidence,
)
from backtest.domain.fidelity import (
    ChainFinality,
    FidelityRequirement,
    IngestionCompleteness,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
    SourceFidelity,
)
from backtest.domain.identifiers import (
    ArtifactId,
    # Include attempt id so the identifiers dependency remains explicit.
    AttemptId,
    CapabilityId,
    ContentDigest,
    JobId,
    NetworkId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
    SourceId,
)
from backtest.domain.time import BlockRange


def _normalized_names(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    # Execute the normalized names workflow in explicit, reviewable steps.
    for value in values:
        # Process values inside the bounded normalized names loop.
        if not value or value != value.strip():
            raise ValueError(f"{field} values must be non-empty and trimmed")
    return tuple(sorted(set(values)))


def _ordered_unique_names(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    # Execute the ordered unique names workflow in explicit, reviewable steps.
    for value in values:
        # Process values inside the bounded ordered unique names loop.
        if not value or value != value.strip():
            raise ValueError(f"{field} values must be non-empty and trimmed")
    if len(set(values)) != len(values):
        raise ValueError(f"{field} values must be unique")
    return values


# Define require non negative as one focused operation with an explicit boundary.
def _require_non_negative(value: int | None, *, field: str) -> None:
    # Execute the require non negative workflow in explicit, reviewable steps.
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer or None")
    if value < 0:
        # Fail the require non negative path with ValueError for must be non-negative and
        # field when value is true; do not continue ambiguously.
        raise ValueError(f"{field} must be non-negative")


# Keep the source column contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class SourceColumn:
    name: str
    type_name: str
    nullable: bool

    # Define source column post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the source column post init workflow in explicit, reviewable steps.
        if not self.name or self.name != self.name.strip():
            raise ValueError("column name must be non-empty and trimmed")
        if not self.type_name or self.type_name != self.type_name.strip():
            raise ValueError("column type must be non-empty and trimmed")


# Keep the source table contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceTable:
    name: str
    engine: str
    partition_key: str
    # Declare sorting key explicitly in the source table contract.
    sorting_key: str
    columns: tuple[SourceColumn, ...]

    def __post_init__(self) -> None:
        # Execute the source table post init workflow in explicit, reviewable steps.
        if not self.name or self.name != self.name.strip():
            raise ValueError("table name must be non-empty and trimmed")
        ordered = tuple(sorted(self.columns, key=lambda column: column.name))
        if len({column.name for column in ordered}) != len(ordered):
            raise ValueError(f"table {self.name!r} has duplicate column names")
        # Invoke __setattr__ for columns and ordered as a visible source table post init
        # step.
        object.__setattr__(self, "columns", ordered)


class CapabilityStream(StrEnum):
    """Closed source-stream roles used by the network-aware acquisition contract."""

    BLOCK_CLOCK = "BLOCK_CLOCK"
    TOKEN_LAUNCH = "TOKEN_LAUNCH"
    PUMP_CURVE_TRADE = "PUMP_CURVE_TRADE"
    PUMP_CURVE_LIFECYCLE = "PUMP_CURVE_LIFECYCLE"


class EvidenceStatus(StrEnum):
    """Whether a bounded source claim has actually been established."""

    UNKNOWN = "UNKNOWN"
    PROVEN = "PROVEN"
    REFUTED = "REFUTED"


CAPABILITY_PROOF_FIELDS = (
    "block_time_monotone",
    # Keep the block time second resolution component named inside the capability proof
    # fields contract.
    "block_time_second_resolution",
    "bundled_instruction_order",
    "creation_fields_immutable",
    "curve_transitions_complete",
    "failed_transactions_included",
    # Keep the fee component rounding exact component named inside the capability proof
    # fields contract.
    "fee_component_rounding_exact",
    "global_zero_based_transaction_index",
    "lifecycle_complete",
    "launch_transaction_success_exact",
    "skipped_blocks_distinguished",
    # Keep the successful transactions included component named inside the capability
    # proof fields contract.
    "successful_transactions_included",
    "vote_transactions_included",
)


@dataclass(frozen=True, slots=True)
class CapabilityProofs:
    """Explicit evidence gates required for exact transaction-clock replay.

    Fields are deliberately tri-state.  An absent claim must serialize as
    ``UNKNOWN`` and can never be confused with a successful local check.
    """

    successful_transactions_included: EvidenceStatus = EvidenceStatus.UNKNOWN
    failed_transactions_included: EvidenceStatus = EvidenceStatus.UNKNOWN
    vote_transactions_included: EvidenceStatus = EvidenceStatus.UNKNOWN
    global_zero_based_transaction_index: EvidenceStatus = EvidenceStatus.UNKNOWN
    skipped_blocks_distinguished: EvidenceStatus = EvidenceStatus.UNKNOWN
    # Declare creation fields immutable explicitly in the capability proofs contract.
    creation_fields_immutable: EvidenceStatus = EvidenceStatus.UNKNOWN
    bundled_instruction_order: EvidenceStatus = EvidenceStatus.UNKNOWN
    curve_transitions_complete: EvidenceStatus = EvidenceStatus.UNKNOWN
    fee_component_rounding_exact: EvidenceStatus = EvidenceStatus.UNKNOWN
    lifecycle_complete: EvidenceStatus = EvidenceStatus.UNKNOWN
    # Declare launch transaction success exact explicitly in the capability proofs
    # contract.
    launch_transaction_success_exact: EvidenceStatus = EvidenceStatus.UNKNOWN
    block_time_second_resolution: EvidenceStatus = EvidenceStatus.UNKNOWN
    block_time_monotone: EvidenceStatus = EvidenceStatus.UNKNOWN

    def __post_init__(self) -> None:
        # Execute the capability proofs post init workflow in explicit, reviewable steps.
        for field_name in CAPABILITY_PROOF_FIELDS:
            # Process CAPABILITY_PROOF_FIELDS inside the bounded capability proofs post
            # init loop.
            if not isinstance(getattr(self, field_name), EvidenceStatus):
                raise TypeError(f"{field_name} must be an EvidenceStatus")

    def require_proven(self, fields: tuple[str, ...]) -> tuple[str, ...]:
        """Return canonical names of claims that are not explicitly proven."""

        unknown: list[str] = []
        for field_name in fields:
            # Process fields inside the bounded capability proofs require proven loop.
            if field_name not in CAPABILITY_PROOF_FIELDS:
                raise ValueError(f"unknown capability evidence field: {field_name}")
            if getattr(self, field_name) is not EvidenceStatus.PROVEN:
                unknown.append(field_name)
        return tuple(sorted(unknown))


# Apply dataclass semantics to the following capability descriptor contract.
@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """A logical capability advertised by a source adapter.

    Physical tables and SQL remain private to the adapter.  ``columns`` are
    logical capability columns available to requirement compilation.
    """

    capability_id: CapabilityId
    protocol: str
    protocol_version: str
    schema_version: str
    stream: CapabilityStream
    # Declare columns explicitly in the capability descriptor contract.
    columns: tuple[str, ...]
    mandatory_columns: tuple[str, ...]
    fidelity: SourceFidelity
    proofs: CapabilityProofs = field(default_factory=CapabilityProofs)
    total_key: tuple[str, ...] = ()
    # Declare keyset key is proven explicitly in the capability descriptor contract.
    keyset_key_is_proven: bool = False
    utc_pruning_column: str | None = None
    utc_pruning_is_proven: bool = False

    def __post_init__(self) -> None:
        # Execute the capability descriptor post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.stream, CapabilityStream):
            raise TypeError("stream must be a CapabilityStream")
        if not isinstance(self.proofs, CapabilityProofs):
            raise TypeError("proofs must be CapabilityProofs")
        for field_name in ("protocol", "protocol_version", "schema_version"):
            # Process protocol, protocol version and schema version inside the bounded
            # capability descriptor post init loop.
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty and trimmed")

        columns = _normalized_names(self.columns, field="columns")
        mandatory = _normalized_names(self.mandatory_columns, field="mandatory_columns")
        # Guard this path with not set(mandatory).issubset(columns) before applying
        # effects.
        if not set(mandatory).issubset(columns):
            raise ValueError("mandatory columns must be advertised capability columns")
        total_key = _ordered_unique_names(self.total_key, field="total_key")
        if not set(total_key).issubset(columns):
            raise ValueError("total-key columns must be advertised capability columns")
        # Evaluate the complete capability descriptor post init keyset key is proven and
        # total key condition before guarded effects.
        if self.keyset_key_is_proven and not total_key:
            raise ValueError("proven keyset pagination requires a non-empty total key")
        if self.utc_pruning_is_proven and not self.utc_pruning_column:
            raise ValueError("proven UTC pruning requires a pruning column")

        object.__setattr__(self, "columns", columns)
        # Invoke __setattr__ for mandatory columns and mandatory as a visible capability
        # descriptor post init step.
        object.__setattr__(self, "mandatory_columns", mandatory)
        object.__setattr__(self, "total_key", total_key)


@dataclass(frozen=True, slots=True)
class CapabilityCutEvidence:
    """An adapter assertion about cut-dependent source fidelity.

    Static capability configuration is not enough to prove finality,
    completeness or snapshot consistency for a requested historical cut.  A
    committed inspection may carry this explicit, capability-scoped evidence;
    absent or stale evidence is treated as ``UNKNOWN`` by dataset planning.
    """

    capability_id: CapabilityId
    block_range: BlockRange
    snapshot_cut_to_block: int
    chain_finality: ChainFinality
    ingestion_watermark_to_block: int | None
    # Declare completeness explicitly in the capability cut evidence contract.
    completeness: IngestionCompleteness
    consistency: SourceConsistency
    upstream_revision: str | None = None

    def __post_init__(self) -> None:
        # Execute the capability cut evidence post init workflow in explicit, reviewable
        # steps.
        if isinstance(self.snapshot_cut_to_block, bool) or not isinstance(
            self.snapshot_cut_to_block,
            int,
        ):
            raise TypeError("snapshot_cut_to_block must be an integer")
        # Evaluate the complete capability cut evidence post init snapshot cut to block,
        # to block ordinal and block range condition before guarded effects.
        if self.snapshot_cut_to_block != self.block_range.to_block_ordinal:
            raise ValueError("snapshot cut must equal the evidence block-range upper bound")
        _require_non_negative(
            self.ingestion_watermark_to_block,
            field="ingestion_watermark_to_block",
            # Complete _require_non_negative only after its ingestion watermark to block
            # inputs are visible in capability cut evidence post init.
        )
        if (
            self.ingestion_watermark_to_block is not None
            and self.ingestion_watermark_to_block > self.snapshot_cut_to_block
        ):
            # Fail the capability cut evidence post init path with ValueError for
            # ingestion watermark cannot exceed the observed source cut when ingestion
            # watermark to block and snapshot cut to block is true; do not continue
            # ambiguously.
            raise ValueError("ingestion watermark cannot exceed the observed source cut")
        if (
            self.completeness is IngestionCompleteness.COMPLETE_TO_WATERMARK
            and self.ingestion_watermark_to_block is None
        ):
            # Fail the capability cut evidence post init path with ValueError for
            # complete-to-watermark evidence requires an exact watermark when
            # completeness, complete to watermark and ingestion watermark to block is
            # true; do not continue ambiguously.
            raise ValueError("complete-to-watermark evidence requires an exact watermark")
        if self.upstream_revision is not None and (
            not self.upstream_revision or self.upstream_revision != self.upstream_revision.strip()
        ):
            raise ValueError("upstream_revision must be non-empty and trimmed when provided")
        # Evaluate the complete capability cut evidence post init consistency, snapshot
        # consistent and upstream revision condition before guarded effects.
        if (
            self.consistency is SourceConsistency.SNAPSHOT_CONSISTENT
            and self.upstream_revision is None
        ):
            raise ValueError("snapshot-consistent evidence requires an upstream revision")


# Bind bounded source evidence schema once as an explicit module-level contract.
BOUNDED_SOURCE_EVIDENCE_SCHEMA = "bounded-source-evidence/v2"
_SOURCE_EVIDENCE_RECEIPT_DOMAIN = b"backtest.bounded-source-evidence.receipt.v2\x00"


@dataclass(frozen=True, slots=True)
class BoundedSourceEvidenceReceipt:
    """Secret-free proof that bounded validation queries were evaluated.

    Static capability configuration may describe mappings, but it cannot
    create this receipt.  The receipt binds the exact source/mapping/query
    contract, cut, derived proof statuses and digest of observed rows.
    """

    receipt_id: ContentDigest
    source_id: SourceId
    capability_id: CapabilityId
    protocol_version: str
    capability_schema_version: str
    # Declare capability mapping digest explicitly in the bounded source evidence receipt
    # contract.
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    projector_digest: ContentDigest
    normalizer_digest: ContentDigest
    cut_evidence: CapabilityCutEvidence
    decision_range: BlockRange
    proofs: CapabilityProofs
    source_fidelity: SourceFidelity
    query_fingerprints: tuple[ContentDigest, ...]
    # Declare result digest explicitly in the bounded source evidence receipt contract.
    result_digest: ContentDigest
    observed_rows: int
    launch_universe: LaunchUniverseEvidence | None = None
    skipped_slot_sentinel: SkippedSlotSentinelEvidence | None = None
    terminal_lifecycle_ordering: TerminalLifecycleOrderingEvidence | None = None
    schema: str = BOUNDED_SOURCE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        # Execute the bounded source evidence receipt post init workflow in explicit,
        # reviewable steps.
        if self.schema != BOUNDED_SOURCE_EVIDENCE_SCHEMA:
            raise ValueError("unsupported bounded source evidence schema")
        for field_name in (
            "receipt_id",
            "capability_mapping_digest",
            "query_template_digest",
            "projector_digest",
            "normalizer_digest",
            "result_digest",
        ):
            if not isinstance(getattr(self, field_name), ContentDigest):
                raise TypeError(f"{field_name} must be a ContentDigest")
        if not isinstance(self.source_id, SourceId):
            raise TypeError("source_id must be a SourceId")
        if not isinstance(self.capability_id, CapabilityId):
            raise TypeError("capability_id must be a CapabilityId")
        if not isinstance(self.cut_evidence, CapabilityCutEvidence):
            raise TypeError("cut_evidence must be CapabilityCutEvidence")
        if self.cut_evidence.capability_id != self.capability_id:
            raise ValueError("evidence receipt capability differs from its cut")
        if not isinstance(self.decision_range, BlockRange):
            raise TypeError("evidence decision_range must be a BlockRange")
        cut_range = self.cut_evidence.block_range
        if (
            self.decision_range.network_id != cut_range.network_id
            or self.decision_range.position_schema_id != cut_range.position_schema_id
            or self.decision_range.from_block_ordinal < cut_range.from_block_ordinal
            or self.decision_range.to_block_ordinal > cut_range.to_block_ordinal
        ):
            raise ValueError("evidence decision range is outside its bounded source cut")
        for field_name in ("protocol_version", "capability_schema_version"):
            # Process protocol version and capability schema version inside the bounded
            # bounded source evidence receipt post init loop.
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty and trimmed")
        if not isinstance(self.proofs, CapabilityProofs):
            raise TypeError("evidence receipt proofs must be CapabilityProofs")
        if not isinstance(self.source_fidelity, SourceFidelity):
            raise TypeError("evidence receipt source_fidelity must be SourceFidelity")
        if (
            self.source_fidelity.chain_finality != self.cut_evidence.chain_finality
            or self.source_fidelity.completeness != self.cut_evidence.completeness
            or self.source_fidelity.consistency != self.cut_evidence.consistency
        ):
            raise ValueError("evidence receipt fidelity differs from its cut evidence")
        if self.launch_universe is not None:
            if not isinstance(self.launch_universe, LaunchUniverseEvidence):
                raise TypeError("launch_universe must be LaunchUniverseEvidence or None")
            if self.launch_universe.decision_range != self.decision_range:
                raise ValueError("launch universe uses another decision range")
        if self.skipped_slot_sentinel is not None and not isinstance(
            self.skipped_slot_sentinel,
            SkippedSlotSentinelEvidence,
        ):
            raise TypeError("skipped_slot_sentinel must be SkippedSlotSentinelEvidence or None")
        if self.terminal_lifecycle_ordering is not None and not isinstance(
            self.terminal_lifecycle_ordering,
            TerminalLifecycleOrderingEvidence,
        ):
            raise TypeError(
                "terminal_lifecycle_ordering must be TerminalLifecycleOrderingEvidence or None"
            )
        # Assemble ordered queries once so the bounded source evidence receipt post init
        # workflow shares one value.
        ordered_queries = tuple(sorted(self.query_fingerprints, key=lambda item: item.hex))
        if ordered_queries != self.query_fingerprints or len(
            {item.hex for item in ordered_queries}
        ) != len(ordered_queries):
            raise ValueError("evidence query fingerprints must be sorted and unique")
        # Guard this path with not ordered_queries before applying effects.
        if not ordered_queries:
            raise ValueError("evidence receipt requires at least one executed query")
        _require_non_negative(self.observed_rows, field="observed_rows")
        expected = bounded_source_evidence_receipt_digest(
            source_id=self.source_id,
            # Pass capability id explicitly so bounded_source_evidence_receipt_digest
            # receives a reviewable source id and capability id input in bounded source
            # evidence receipt post init.
            capability_id=self.capability_id,
            protocol_version=self.protocol_version,
            capability_schema_version=self.capability_schema_version,
            capability_mapping_digest=self.capability_mapping_digest,
            query_template_digest=self.query_template_digest,
            projector_digest=self.projector_digest,
            normalizer_digest=self.normalizer_digest,
            # Pass cut evidence explicitly so bounded_source_evidence_receipt_digest
            # receives a reviewable source id and capability id input in bounded source
            # evidence receipt post init.
            cut_evidence=self.cut_evidence,
            decision_range=self.decision_range,
            proofs=self.proofs,
            source_fidelity=self.source_fidelity,
            query_fingerprints=self.query_fingerprints,
            result_digest=self.result_digest,
            observed_rows=self.observed_rows,
            launch_universe=self.launch_universe,
            skipped_slot_sentinel=self.skipped_slot_sentinel,
            terminal_lifecycle_ordering=self.terminal_lifecycle_ordering,
            # Pass schema explicitly so bounded_source_evidence_receipt_digest receives a
            # reviewable source id and capability id input in bounded source evidence
            # receipt post init.
            schema=self.schema,
        )
        if self.receipt_id != expected:
            raise ValueError("bounded source evidence receipt does not match its contents")


def bounded_source_evidence_receipt_digest(
    # Close the bounded source evidence receipt digest signature after its explicit
    # inputs.
    *,
    source_id: SourceId,
    capability_id: CapabilityId,
    protocol_version: str,
    capability_schema_version: str,
    # Keep the capability mapping digest input explicit in the bounded source evidence
    # receipt digest contract.
    capability_mapping_digest: ContentDigest,
    query_template_digest: ContentDigest,
    cut_evidence: CapabilityCutEvidence,
    decision_range: BlockRange,
    proofs: CapabilityProofs,
    source_fidelity: SourceFidelity,
    query_fingerprints: tuple[ContentDigest, ...],
    # Keep the result digest input explicit in the bounded source evidence receipt digest
    # contract.
    result_digest: ContentDigest,
    observed_rows: int,
    projector_digest: ContentDigest,
    normalizer_digest: ContentDigest,
    launch_universe: LaunchUniverseEvidence | None = None,
    skipped_slot_sentinel: SkippedSlotSentinelEvidence | None = None,
    terminal_lifecycle_ordering: TerminalLifecycleOrderingEvidence | None = None,
    schema: str = BOUNDED_SOURCE_EVIDENCE_SCHEMA,
) -> ContentDigest:
    """Compute the domain-separated identity of one bounded receipt."""

    cut = cut_evidence
    document = {
        "capability_id": capability_id.value,
        "capability_schema_version": capability_schema_version,
        "capability_mapping_digest": capability_mapping_digest.hex,
        "decision_range": _block_range_identity(decision_range),
        # Keep the cut evidence component named inside the document contract.
        "cut_evidence": {
            "block_range": {
                "from_block_ordinal": cut.block_range.from_block_ordinal,
                "network_id": cut.block_range.network_id.value,
                "position_schema_id": cut.block_range.position_schema_id.value,
                # Keep the to block ordinal component named inside the document contract.
                "to_block_ordinal": cut.block_range.to_block_ordinal,
            },
            "chain_finality": cut.chain_finality.value,
            "completeness": cut.completeness.value,
            "consistency": cut.consistency.value,
            # Keep the ingestion watermark to block component named inside the document
            # contract.
            "ingestion_watermark_to_block": cut.ingestion_watermark_to_block,
            "snapshot_cut_to_block": cut.snapshot_cut_to_block,
            "upstream_revision": cut.upstream_revision,
        },
        "observed_rows": observed_rows,
        "normalizer_digest": normalizer_digest.hex,
        # Keep the proofs component named inside the document contract.
        "proofs": {
            field_name: getattr(proofs, field_name).value for field_name in CAPABILITY_PROOF_FIELDS
        },
        "query_fingerprints": [item.hex for item in query_fingerprints],
        "query_template_digest": query_template_digest.hex,
        "projector_digest": projector_digest.hex,
        # Keep the result digest component named inside the document contract.
        "result_digest": result_digest.hex,
        "protocol_version": protocol_version,
        "launch_universe": (
            None if launch_universe is None else launch_universe.identity_document()
        ),
        "skipped_slot_sentinel": (
            None if skipped_slot_sentinel is None else skipped_slot_sentinel.identity_document()
        ),
        "source_fidelity": {
            "chain_finality": source_fidelity.chain_finality.value,
            "completeness": source_fidelity.completeness.value,
            "consistency": source_fidelity.consistency.value,
            "fees": source_fidelity.fees.value,
            "identity": source_fidelity.identity.value,
            "ordering": source_fidelity.ordering.value,
            "state": source_fidelity.state.value,
        },
        "terminal_lifecycle_ordering": (
            None
            if terminal_lifecycle_ordering is None
            else terminal_lifecycle_ordering.identity_document()
        ),
        "schema": schema,
        "source_id": source_id.value,
    }
    # Assemble encoded once so the bounded source evidence receipt digest workflow shares
    # one value.
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        # Pass sort keys explicitly so encode receives a reviewable utf-8 input in bounded
        # source evidence receipt digest.
        sort_keys=True,
    ).encode("utf-8")
    return ContentDigest(sha256(_SOURCE_EVIDENCE_RECEIPT_DOMAIN + encoded).hexdigest())


def build_bounded_source_evidence_receipt(
    *,
    # Keep the source id input explicit in the build bounded source evidence receipt
    # contract.
    source_id: SourceId,
    capability_id: CapabilityId,
    protocol_version: str,
    capability_schema_version: str,
    capability_mapping_digest: ContentDigest,
    # Keep the query template digest input explicit in the build bounded source evidence
    # receipt contract.
    query_template_digest: ContentDigest,
    projector_digest: ContentDigest,
    normalizer_digest: ContentDigest,
    cut_evidence: CapabilityCutEvidence,
    decision_range: BlockRange,
    proofs: CapabilityProofs,
    source_fidelity: SourceFidelity,
    query_fingerprints: tuple[ContentDigest, ...],
    result_digest: ContentDigest,
    # Keep the observed rows input explicit in the build bounded source evidence receipt
    # contract.
    observed_rows: int,
    launch_universe: LaunchUniverseEvidence | None = None,
    skipped_slot_sentinel: SkippedSlotSentinelEvidence | None = None,
    terminal_lifecycle_ordering: TerminalLifecycleOrderingEvidence | None = None,
) -> BoundedSourceEvidenceReceipt:
    """Build a verified receipt from outcomes derived by a source adapter."""

    ordered_queries = tuple(sorted(query_fingerprints, key=lambda item: item.hex))
    receipt_id = bounded_source_evidence_receipt_digest(
        source_id=source_id,
        capability_id=capability_id,
        protocol_version=protocol_version,
        # Pass capability schema version explicitly so
        # bounded_source_evidence_receipt_digest receives a reviewable source id and
        # capability id input in build bounded source evidence receipt.
        capability_schema_version=capability_schema_version,
        capability_mapping_digest=capability_mapping_digest,
        query_template_digest=query_template_digest,
        projector_digest=projector_digest,
        normalizer_digest=normalizer_digest,
        cut_evidence=cut_evidence,
        decision_range=decision_range,
        proofs=proofs,
        source_fidelity=source_fidelity,
        # Pass query fingerprints explicitly so bounded_source_evidence_receipt_digest
        # receives a reviewable source id and capability id input in build bounded source
        # evidence receipt.
        query_fingerprints=ordered_queries,
        result_digest=result_digest,
        observed_rows=observed_rows,
        launch_universe=launch_universe,
        skipped_slot_sentinel=skipped_slot_sentinel,
        terminal_lifecycle_ordering=terminal_lifecycle_ordering,
    )
    return BoundedSourceEvidenceReceipt(
        # Pass receipt id explicitly so BoundedSourceEvidenceReceipt receives a reviewable
        # receipt id and source id input in build bounded source evidence receipt.
        receipt_id=receipt_id,
        source_id=source_id,
        capability_id=capability_id,
        protocol_version=protocol_version,
        capability_schema_version=capability_schema_version,
        # Pass capability mapping digest explicitly so BoundedSourceEvidenceReceipt
        # receives a reviewable receipt id and source id input in build bounded source
        # evidence receipt.
        capability_mapping_digest=capability_mapping_digest,
        query_template_digest=query_template_digest,
        projector_digest=projector_digest,
        normalizer_digest=normalizer_digest,
        cut_evidence=cut_evidence,
        decision_range=decision_range,
        proofs=proofs,
        source_fidelity=source_fidelity,
        query_fingerprints=ordered_queries,
        # Pass result digest explicitly so BoundedSourceEvidenceReceipt receives a
        # reviewable receipt id and source id input in build bounded source evidence
        # receipt.
        result_digest=result_digest,
        observed_rows=observed_rows,
        launch_universe=launch_universe,
        skipped_slot_sentinel=skipped_slot_sentinel,
        terminal_lifecycle_ordering=terminal_lifecycle_ordering,
    )


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Secret-free metadata returned by a source-inspection adapter."""

    source_id: SourceId
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    server_version: str
    tables: tuple[SourceTable, ...]
    # Declare capabilities explicitly in the source metadata contract.
    capabilities: tuple[CapabilityDescriptor, ...]
    capability_mapping_digest: ContentDigest | None = None
    query_template_digest: ContentDigest | None = None
    cut_evidence: tuple[CapabilityCutEvidence, ...] = ()
    evidence_receipts: tuple[BoundedSourceEvidenceReceipt, ...] = ()

    # Define source metadata post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the source metadata post init workflow in explicit, reviewable steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if not self.server_version or self.server_version != self.server_version.strip():
            # Fail the source metadata post init path with ValueError for server version
            # must be non-empty and trimmed when server version and strip is true; do not
            # continue ambiguously.
            raise ValueError("server_version must be non-empty and trimmed")
        tables = tuple(sorted(self.tables, key=lambda table: table.name))
        if len({table.name for table in tables}) != len(tables):
            raise ValueError("source metadata has duplicate table names")
        capabilities = tuple(
            # Keep the capabilities sorted step visible while building capabilities.
            sorted(
                self.capabilities,
                key=lambda item: (
                    item.capability_id.value,
                    item.protocol_version,
                    # Pass item explicitly so sorted receives a reviewable capabilities
                    # and value input in source metadata post init.
                    item.schema_version,
                ),
            )
        )
        capability_keys = {
            # Complete the capability keys group only after its semantic components are
            # visible.
            (
                item.capability_id,
                item.protocol_version,
                item.schema_version,
            )
            # Keep the item component named inside the capability keys contract.
            for item in capabilities
        }
        if len(capability_keys) != len(capabilities):
            raise ValueError("source metadata has duplicate capability versions")
        evidence = tuple(sorted(self.cut_evidence, key=lambda item: item.capability_id.value))
        # Assemble evidence ids once so the source metadata post init workflow shares one
        # value.
        evidence_ids = tuple(item.capability_id for item in evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("source metadata has duplicate cut evidence")
        advertised_ids = {item.capability_id for item in capabilities}
        if not set(evidence_ids).issubset(advertised_ids):
            # Fail the source metadata post init path with ValueError for cut evidence
            # references an unadvertised capability when issubset, advertised ids and
            # evidence ids is true; do not continue ambiguously.
            raise ValueError("cut evidence references an unadvertised capability")
        if any(
            item.block_range.network_id != self.network_id
            or item.block_range.position_schema_id != self.position_schema_id
            for item in evidence
            # Complete any only after its network id and position schema id inputs are visible
            # in source metadata post init.
        ):
            raise ValueError("cut evidence uses a different network or position schema")
        receipts = tuple(
            sorted(
                self.evidence_receipts,
                # Pass key explicitly so sorted receives a reviewable evidence receipts
                # and value input in source metadata post init.
                key=lambda item: (
                    item.capability_id.value,
                    item.protocol_version,
                    item.capability_schema_version,
                ),
                # Complete sorted only after its evidence receipts and value inputs are
                # visible in source metadata post init.
            )
        )
        receipt_keys = tuple(
            (
                item.capability_id,
                # Pass item explicitly so tuple receives a reviewable capability id and
                # protocol version input in source metadata post init.
                item.protocol_version,
                item.capability_schema_version,
            )
            for item in receipts
        )
        # Evaluate the complete source metadata post init receipt keys condition before
        # guarded effects.
        if len(set(receipt_keys)) != len(receipt_keys):
            raise ValueError("source metadata has duplicate bounded evidence receipts")
        if not {item[0] for item in receipt_keys}.issubset(advertised_ids):
            raise ValueError("bounded evidence references an unadvertised capability")
        evidence_by_id = {item.capability_id: item for item in evidence}
        # Assemble descriptor by key once so the source metadata post init workflow shares
        # one value.
        descriptor_by_key = {
            (item.capability_id, item.protocol_version, item.schema_version): item
            for item in capabilities
        }
        for receipt in receipts:
            # Process receipts inside the bounded source metadata post init loop.
            if receipt.source_id != self.source_id:
                raise ValueError("bounded evidence uses a different source identity")
            if (
                receipt.capability_mapping_digest != self.capability_mapping_digest
                or receipt.query_template_digest != self.query_template_digest
                # Evaluate the complete source metadata post init capability mapping digest,
                # query template digest and receipt condition before guarded effects.
            ):
                raise ValueError("bounded evidence uses a different mapping/query contract")
            if evidence_by_id.get(receipt.capability_id) != receipt.cut_evidence:
                raise ValueError("bounded evidence does not match capability cut evidence")
            descriptor = descriptor_by_key.get(
                # Open the capability id and protocol version payload explicitly for get
                # within source metadata post init.
                (
                    receipt.capability_id,
                    receipt.protocol_version,
                    receipt.capability_schema_version,
                )
                # Complete get only after its capability id and protocol version inputs are
                # visible in source metadata post init.
            )
            if descriptor is None:
                raise ValueError("bounded evidence references an unadvertised capability version")
            if descriptor.proofs != receipt.proofs:
                raise ValueError("bounded evidence does not match capability proof statuses")
            if descriptor.fidelity != receipt.source_fidelity:
                raise ValueError("bounded evidence does not match capability source fidelity")
            if (
                receipt.launch_universe is not None
                and descriptor.stream is not CapabilityStream.TOKEN_LAUNCH
            ):
                raise ValueError("launch universe evidence is attached to another stream")
            if (
                receipt.skipped_slot_sentinel is not None
                and descriptor.stream is not CapabilityStream.BLOCK_CLOCK
            ):
                raise ValueError("skipped-slot evidence is attached to another stream")
            if (
                receipt.terminal_lifecycle_ordering is not None
                and descriptor.stream is not CapabilityStream.PUMP_CURVE_LIFECYCLE
            ):
                raise ValueError("terminal lifecycle evidence is attached to another stream")
        if receipts:
            if len({item.decision_range for item in receipts}) != 1:
                raise ValueError("bounded evidence receipts use different decision ranges")
            if len({item.projector_digest for item in receipts}) != 1:
                raise ValueError("bounded evidence receipts use different projectors")
            if len({item.normalizer_digest for item in receipts}) != 1:
                raise ValueError("bounded evidence receipts use different normalizers")
        # Assemble receipt key set once so the source metadata post init workflow shares
        # one value.
        receipt_key_set = set(receipt_keys)
        for descriptor in capabilities:
            # Process capabilities inside the bounded source metadata post init loop.
            has_claim = any(
                getattr(descriptor.proofs, field_name) is not EvidenceStatus.UNKNOWN
                for field_name in CAPABILITY_PROOF_FIELDS
            )
            descriptor_key = (
                # Keep the descriptor component named inside the descriptor key contract.
                descriptor.capability_id,
                descriptor.protocol_version,
                descriptor.schema_version,
            )
            if has_claim and descriptor_key not in receipt_key_set:
                # Fail the source metadata post init path with ValueError for capability
                # proof status lacks bounded evidence provenance when has claim,
                # descriptor key and receipt key set is true; do not continue ambiguously.
                raise ValueError("capability proof status lacks bounded evidence provenance")
        object.__setattr__(self, "tables", tables)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "cut_evidence", evidence)
        object.__setattr__(self, "evidence_receipts", receipts)


# Keep the source inspection contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceInspection:
    metadata: SourceMetadata
    schema_fingerprint: ContentDigest
    inspected_at: datetime

    # Define source inspection post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the source inspection post init workflow in explicit, reviewable steps.
        if self.inspected_at.tzinfo is None or self.inspected_at.utcoffset() is None:
            raise ValueError("inspected_at must be timezone-aware")
        if self.metadata.capability_mapping_digest is None:
            raise ValueError("source inspection requires a capability mapping digest")
        if self.metadata.query_template_digest is None:
            # Fail the source inspection post init path with ValueError for source
            # inspection requires a query template digest when query template digest and
            # metadata is true; do not continue ambiguously.
            raise ValueError("source inspection requires a query template digest")


# Keep the requirement origin contract and validation rules together.
class RequirementOrigin(StrEnum):
    STRATEGY = "STRATEGY"
    EXECUTION = "EXECUTION"
    FEATURE = "FEATURE"
    MODEL = "MODEL"
    # Declare universe explicitly in the requirement origin contract.
    UNIVERSE = "UNIVERSE"


LEGACY_PUMPFUN_SNIPING_SOURCE_CONTRACT = "pumpfun-sniping-source-v1"
PUMPFUN_SNIPING_SOURCE_CONTRACT = "pumpfun-sniping-source-v2"
SETTLEMENT_REQUIREMENT_SCHEMA = "global-transaction-duration-roundtrip/v1"


@dataclass(frozen=True, slots=True)
# Keep the settlement requirement contract and validation rules together.
class SettlementRequirement:
    """Versioned, strategy-neutral bound for causal post-decision settlement.

    ``maximum_tail_blocks`` is a hard acquisition guard, not an estimate that
    the caller claims is sufficient.  The current one-shot planner expands the
    selected settlement streams up to that bound; snapshot validation still
    has to prove every target actually settles inside the resulting compact
    transaction clock.
    """

    schema: str
    target_stream: CapabilityStream
    settlement_streams: tuple[CapabilityStream, ...]
    initial_delay_transactions: int
    minimum_duration_ns: int
    # Declare maximum followup delay transactions explicitly in the settlement requirement
    # contract.
    maximum_followup_delay_transactions: int
    maximum_tail_blocks: int

    def __post_init__(self) -> None:
        # Execute the settlement requirement post init workflow in explicit, reviewable
        # steps.
        if self.schema != SETTLEMENT_REQUIREMENT_SCHEMA:
            raise ValueError(f"unsupported settlement requirement schema: {self.schema}")
        if not isinstance(self.target_stream, CapabilityStream):
            raise TypeError("target_stream must be a CapabilityStream")
        ordered = tuple(sorted(set(self.settlement_streams), key=lambda item: item.value))
        # Evaluate the complete settlement requirement post init ordered and settlement
        # streams condition before guarded effects.
        if ordered != self.settlement_streams or not ordered:
            raise ValueError("settlement_streams must be non-empty, sorted and unique")
        if self.target_stream in ordered:
            raise ValueError("target_stream cannot also be a settlement stream")
        for field_name in (
            # Traverse initial delay transactions, minimum duration ns and maximum
            # followup delay transactions explicitly so each settlement requirement post
            # init iteration remains traceable.
            "initial_delay_transactions",
            "minimum_duration_ns",
            "maximum_followup_delay_transactions",
            "maximum_tail_blocks",
        ):
            # Process initial delay transactions, minimum duration ns and maximum followup
            # delay transactions inside the bounded settlement requirement post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")

    # Apply classmethod semantics to the following settlement requirement combine
    # contract.
    @classmethod
    def combine(cls, values: tuple[SettlementRequirement, ...]) -> SettlementRequirement:
        # Execute the settlement requirement combine workflow in explicit, reviewable
        # steps.
        if not values:
            raise ValueError("at least one settlement requirement is required")
        first = values[0]
        invariant = (
            first.schema,
            # Keep the first component named inside the invariant contract.
            first.target_stream,
            first.settlement_streams,
            first.initial_delay_transactions,
            first.minimum_duration_ns,
        )
        # Evaluate the complete settlement requirement combine invariant, item and schema
        # condition before guarded effects.
        if any(
            (
                item.schema,
                item.target_stream,
                item.settlement_streams,
                # Pass item explicitly so any receives a reviewable schema and target
                # stream input in settlement requirement combine.
                item.initial_delay_transactions,
                item.minimum_duration_ns,
            )
            != invariant
            for item in values[1:]
            # Complete any only after its schema and target stream inputs are visible in
            # settlement requirement combine.
        ):
            raise ValueError("settlement requirements use incompatible causal contracts")
        return cls(
            schema=first.schema,
            target_stream=first.target_stream,
            # Pass settlement streams explicitly so cls receives a reviewable schema and
            # target stream input in settlement requirement combine.
            settlement_streams=first.settlement_streams,
            initial_delay_transactions=first.initial_delay_transactions,
            minimum_duration_ns=first.minimum_duration_ns,
            maximum_followup_delay_transactions=max(
                item.maximum_followup_delay_transactions
                # Pass item explicitly so max receives a reviewable maximum followup delay
                # transactions and item input in settlement requirement combine.
                for item in values
                # Complete max only after its maximum followup delay transactions and item
                # inputs are visible in settlement requirement combine.
            ),
            maximum_tail_blocks=min(item.maximum_tail_blocks for item in values),
        )


# Keep the data requirement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DataRequirement:
    origin: RequirementOrigin
    origin_id: str
    capability_id: CapabilityId
    # Declare columns explicitly in the data requirement contract.
    columns: tuple[str, ...]
    minimum_fidelity: FidelityRequirement = field(default_factory=FidelityRequirement)
    accepted_protocol_versions: tuple[str, ...] = ()
    evidence_contracts: tuple[str, ...] = ()
    warmup_blocks: int = 0
    # Declare settlement tail blocks explicitly in the data requirement contract.
    settlement_tail_blocks: int = 0
    settlement_requirement: SettlementRequirement | None = None

    def __post_init__(self) -> None:
        # Execute the data requirement post init workflow in explicit, reviewable steps.
        if not self.origin_id or self.origin_id != self.origin_id.strip():
            raise ValueError("origin_id must be non-empty and trimmed")
        object.__setattr__(
            self,
            "columns",
            # Pass field explicitly to __setattr__ for columns and requirement columns.
            _normalized_names(self.columns, field="requirement columns"),
        )
        object.__setattr__(
            self,
            "accepted_protocol_versions",
            # Pass normalized names explicitly to __setattr__ for accepted protocol
            # versions and normalized names.
            _normalized_names(
                self.accepted_protocol_versions,
                field="accepted_protocol_versions",
            ),
        )
        # Invoke __setattr__ for evidence contracts and normalized names as a visible data
        # requirement post init step.
        object.__setattr__(
            self,
            "evidence_contracts",
            _normalized_names(self.evidence_contracts, field="evidence_contracts"),
        )
        # Traverse warmup blocks and settlement tail blocks explicitly so each data
        # requirement post init iteration remains traceable.
        for field_name in ("warmup_blocks", "settlement_tail_blocks"):
            # Process warmup blocks and settlement tail blocks inside the bounded data
            # requirement post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        # Evaluate the complete data requirement post init settlement requirement and
        # isinstance condition before guarded effects.
        if self.settlement_requirement is not None and not isinstance(
            self.settlement_requirement, SettlementRequirement
        ):
            raise TypeError("settlement_requirement must be a SettlementRequirement or None")


# Keep the query limits contract and validation rules together.
@dataclass(frozen=True, slots=True)
class QueryLimits:
    max_execution_seconds: int
    max_memory_bytes: int
    max_result_rows: int | None = None

    # Define query limits post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the query limits post init workflow in explicit, reviewable steps.
        if self.max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")
        if self.max_memory_bytes <= 0:
            raise ValueError("max_memory_bytes must be positive")
        if self.max_result_rows is not None and self.max_result_rows <= 0:
            # Fail the query limits post init path with ValueError for max result rows
            # must be positive when provided when max result rows is true; do not continue
            # ambiguously.
            raise ValueError("max_result_rows must be positive when provided")


@dataclass(frozen=True, slots=True)
class BoundedSourceEvidenceRequest:
    """Explicit bounded validation request for one source inspection."""

    source_id: SourceId
    block_range: BlockRange
    decision_range: BlockRange
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    projector_digest: ContentDigest
    normalizer_digest: ContentDigest
    launch_universe_policy_id: str
    skipped_slot_sentinel_policy_id: str
    terminal_lifecycle_ordering_policy_id: str
    query_limits: QueryLimits

    def __post_init__(self) -> None:
        # Execute the bounded source evidence request post init workflow in explicit,
        # reviewable steps.
        if not isinstance(self.block_range, BlockRange):
            raise TypeError("evidence block_range must be a BlockRange")
        if not isinstance(self.decision_range, BlockRange):
            raise TypeError("evidence decision_range must be a BlockRange")
        if (
            self.decision_range.network_id != self.block_range.network_id
            or self.decision_range.position_schema_id != self.block_range.position_schema_id
            or self.decision_range.from_block_ordinal < self.block_range.from_block_ordinal
            or self.decision_range.to_block_ordinal > self.block_range.to_block_ordinal
        ):
            raise ValueError("evidence decision range is outside its extraction range")
        for field_name in (
            "capability_mapping_digest",
            "query_template_digest",
            "projector_digest",
            "normalizer_digest",
        ):
            if not isinstance(getattr(self, field_name), ContentDigest):
                raise TypeError(f"{field_name} must be a ContentDigest")
        for field_name in (
            "launch_universe_policy_id",
            "skipped_slot_sentinel_policy_id",
            "terminal_lifecycle_ordering_policy_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty trimmed string")
        if not isinstance(self.query_limits, QueryLimits):
            raise TypeError("evidence query_limits must be QueryLimits")
        if self.query_limits.max_result_rows is None:
            # Fail the bounded source evidence request post init path with ValueError for
            # bounded evidence requires an explicit result-row limit when max result rows
            # and query limits is true; do not continue ambiguously.
            raise ValueError("bounded evidence requires an explicit result-row limit")


# Keep the budget limits contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BudgetLimits:
    max_remote_bytes: int
    max_local_bytes: int
    max_days: int
    # Declare temporary reserve bytes explicitly in the budget limits contract.
    temporary_reserve_bytes: int
    disk_low_watermark_bytes: int

    def __post_init__(self) -> None:
        # Execute the budget limits post init workflow in explicit, reviewable steps.
        for field_name in ("max_remote_bytes", "max_local_bytes", "max_days"):
            # Process max remote bytes, max local bytes and max days inside the bounded
            # budget limits post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        # Traverse temporary reserve bytes and disk low watermark bytes explicitly so each
        # budget limits post init iteration remains traceable.
        for field_name in ("temporary_reserve_bytes", "disk_low_watermark_bytes"):
            # Process temporary reserve bytes and disk low watermark bytes inside the
            # bounded budget limits post init loop.
            value = getattr(self, field_name)
            _require_non_negative(value, field=field_name)


@dataclass(frozen=True, slots=True)
class DatasetPlanningPolicy:
    """Host-owned admission ceilings for one dataset planning process.

    Request budgets and query limits may only make these limits stricter.  The
    temporary reserve and low watermark are protective floors, so a request may
    only raise them.
    """

    budget_limits: BudgetLimits
    query_limits: QueryLimits
    max_total_blocks: int
    max_total_shards: int
    max_shard_blocks: int

    # Define dataset planning policy post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the dataset planning policy post init workflow in explicit, reviewable
        # steps.
        for field_name in ("max_total_blocks", "max_total_shards", "max_shard_blocks"):
            # Process max total blocks, max total shards and max shard blocks inside the
            # bounded dataset planning policy post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        # Evaluate the complete dataset planning policy post init max result rows and
        # query limits condition before guarded effects.
        if self.query_limits.max_result_rows is None:
            raise ValueError("host query policy requires max_result_rows")

    def effective_budget(self, requested: BudgetLimits) -> BudgetLimits:
        # Execute the dataset planning policy effective budget workflow in explicit,
        # reviewable steps.
        return BudgetLimits(
            max_remote_bytes=min(
                requested.max_remote_bytes,
                self.budget_limits.max_remote_bytes,
            ),
            # Include max local bytes in the completed dataset planning policy effective
            # budget result.
            max_local_bytes=min(
                requested.max_local_bytes,
                self.budget_limits.max_local_bytes,
            ),
            max_days=min(requested.max_days, self.budget_limits.max_days),
            # Include temporary reserve bytes in the completed dataset planning policy
            # effective budget result.
            temporary_reserve_bytes=max(
                requested.temporary_reserve_bytes,
                self.budget_limits.temporary_reserve_bytes,
            ),
            disk_low_watermark_bytes=max(
                # Pass requested explicitly so max receives a reviewable disk low
                # watermark bytes and budget limits input in dataset planning policy
                # effective budget.
                requested.disk_low_watermark_bytes,
                self.budget_limits.disk_low_watermark_bytes,
            ),
        )

    def effective_query(self, requested: QueryLimits) -> QueryLimits:
        # Execute the dataset planning policy effective query workflow in explicit,
        # reviewable steps.
        policy_rows = self.query_limits.max_result_rows
        if policy_rows is None:  # guarded by __post_init__; narrows for mypy
            raise AssertionError("host query row limit is absent")
        requested_rows = requested.max_result_rows or policy_rows
        return QueryLimits(
            max_execution_seconds=min(
                requested.max_execution_seconds,
                # Pass self explicitly so min receives a reviewable max execution seconds
                # and query limits input in dataset planning policy effective query.
                self.query_limits.max_execution_seconds,
            ),
            max_memory_bytes=min(
                requested.max_memory_bytes,
                self.query_limits.max_memory_bytes,
                # Complete min only after its max memory bytes and query limits inputs are
                # visible in dataset planning policy effective query.
            ),
            max_result_rows=min(requested_rows, policy_rows),
        )


# Keep the source estimate contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceEstimate:
    estimated_source_rows: int | None
    estimated_source_bytes: int | None
    expected_local_parquet_bytes: int | None
    # Declare temporary spill bytes explicitly in the source estimate contract.
    temporary_spill_bytes: int | None
    estimated_events_per_second: int | None = None

    def __post_init__(self) -> None:
        # Execute the source estimate post init workflow in explicit, reviewable steps.
        for field_name in (
            "estimated_source_rows",
            "estimated_source_bytes",
            "expected_local_parquet_bytes",
            "temporary_spill_bytes",
            # Traverse estimated source rows, estimated source bytes and expected local
            # parquet bytes explicitly so each source estimate post init iteration remains
            # traceable.
            "estimated_events_per_second",
        ):
            _require_non_negative(getattr(self, field_name), field=field_name)

    @classmethod
    def unknown(cls) -> SourceEstimate:
        # Return the completed source estimate unknown result without a hidden fallback.
        return cls(None, None, None, None, None)


# Keep the disk capacity contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DiskCapacity:
    free_bytes: int

    def __post_init__(self) -> None:
        _require_non_negative(self.free_bytes, field="free_bytes")


# Keep the budget issue kind contract and validation rules together.
class BudgetIssueKind(StrEnum):
    UNKNOWN = "UNKNOWN"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


# Keep the budget issue contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BudgetIssue:
    code: str
    kind: BudgetIssueKind
    message: str
    # Declare actual explicitly in the budget issue contract.
    actual: int | None = None
    limit: int | None = None


# Keep the budget status contract and validation rules together.
class BudgetStatus(StrEnum):
    PASS = "PASS"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


# Keep the budget report contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BudgetReport:
    status: BudgetStatus
    estimated_source_rows: int | None
    estimated_source_bytes: int | None
    # Declare requested days explicitly in the budget report contract.
    requested_days: int | None
    requested_blocks: int
    planned_shards: int
    expected_local_parquet_bytes: int | None
    temporary_reserve_bytes: int | None
    # Declare current free disk bytes explicitly in the budget report contract.
    current_free_disk_bytes: int | None
    disk_low_watermark_bytes: int
    max_remote_bytes: int
    max_local_bytes: int
    max_days: int
    # Declare max total blocks explicitly in the budget report contract.
    max_total_blocks: int
    max_total_shards: int
    max_shard_blocks: int
    issues: tuple[BudgetIssue, ...]

    @property
    # Define budget report rejected as one focused operation with an explicit boundary.
    def rejected(self) -> bool:
        return self.status is BudgetStatus.REJECTED


# Keep the planned capability contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PlannedCapability:
    capability_id: CapabilityId
    protocol: str
    protocol_version: str
    # Declare schema version explicitly in the planned capability contract.
    schema_version: str
    stream: CapabilityStream
    columns: tuple[str, ...]
    fidelity: SourceFidelity
    proofs: CapabilityProofs
    # Declare total key explicitly in the planned capability contract.
    total_key: tuple[str, ...]
    keyset_key_is_proven: bool
    utc_pruning_column: str | None
    utc_pruning_is_proven: bool

    def __post_init__(self) -> None:
        # Execute the planned capability post init workflow in explicit, reviewable steps.
        if not isinstance(self.stream, CapabilityStream):
            raise TypeError("stream must be a CapabilityStream")
        if not isinstance(self.proofs, CapabilityProofs):
            raise TypeError("proofs must be CapabilityProofs")
        for field_name in ("protocol", "protocol_version", "schema_version"):
            # Process protocol, protocol version and schema version inside the bounded
            # planned capability post init loop.
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty and trimmed")
        columns = _normalized_names(self.columns, field="planned columns")
        total_key = _ordered_unique_names(self.total_key, field="planned total_key")
        # Guard this path with not set(total_key).issubset(columns) before applying
        # effects.
        if not set(total_key).issubset(columns):
            raise ValueError("planned total-key columns must be selected columns")
        if self.keyset_key_is_proven and not total_key:
            raise ValueError("proven keyset pagination requires a non-empty total key")
        if self.utc_pruning_is_proven and not self.utc_pruning_column:
            # Fail the planned capability post init path with ValueError for proven utc
            # pruning requires a pruning column when utc pruning is proven and utc pruning
            # column is true; do not continue ambiguously.
            raise ValueError("proven UTC pruning requires a pruning column")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "total_key", total_key)


# Keep the dataset shard contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class DatasetShard:
    ordinal: int
    capability_id: CapabilityId
    block_range: BlockRange
    # Declare columns explicitly in the dataset shard contract.
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        # Execute the dataset shard post init workflow in explicit, reviewable steps.
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            raise TypeError("shard ordinal must be an integer")
        if self.ordinal < 0:
            raise ValueError("shard ordinal must be non-negative")
        if not isinstance(self.block_range, BlockRange):
            # Fail the dataset shard post init path with TypeError for shard block range
            # must be a block range when isinstance and block range is true; do not
            # continue ambiguously.
            raise TypeError("shard block_range must be a BlockRange")
        object.__setattr__(
            self,
            "columns",
            _normalized_names(self.columns, field="shard columns"),
            # Complete __setattr__ only after its columns and shard columns inputs are visible
            # in dataset shard post init.
        )


@dataclass(frozen=True, slots=True, order=True)
class CapabilityExtractionRange:
    """The exact bounded extraction range for one planned capability."""

    capability_id: CapabilityId
    block_range: BlockRange

    def __post_init__(self) -> None:
        # Execute the capability extraction range post init workflow in explicit,
        # reviewable steps.
        if not isinstance(self.capability_id, CapabilityId):
            raise TypeError("capability_id must be a CapabilityId")
        if not isinstance(self.block_range, BlockRange):
            raise TypeError("block_range must be a BlockRange")


def _require_same_chain(
    # Keep the value input explicit in the require same chain contract.
    value: BlockRange,
    *,
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
    field: str,
    # Close the require same chain signature after its explicit inputs.
) -> None:
    # Execute the require same chain workflow in explicit, reviewable steps.
    if value.network_id != network_id or value.position_schema_id != position_schema_id:
        raise ValueError(f"{field} uses a different network or position schema")


DATASET_SPEC_VERSION = 5
_DATASET_SPEC_IDENTITY_DOMAIN = b"backtest.dataset-spec.identity.v5\x00"


# Keep the dataset spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DatasetSpec:
    spec_version: int
    spec_id: ContentDigest
    source_id: SourceId
    # Declare source inspection artifact id explicitly in the dataset spec contract.
    source_inspection_artifact_id: ArtifactId
    source_schema_fingerprint: ContentDigest
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    network_id: NetworkId
    # Declare position schema id explicitly in the dataset spec contract.
    position_schema_id: PositionSchemaId
    decision_range: BlockRange
    settlement_tail: BlockRange | None
    warmup_blocks: int
    evidence_contracts: tuple[str, ...]
    # Declare capabilities explicitly in the dataset spec contract.
    capabilities: tuple[PlannedCapability, ...]
    capability_ranges: tuple[CapabilityExtractionRange, ...]
    cut_evidence: tuple[CapabilityCutEvidence, ...]
    shards: tuple[DatasetShard, ...]
    settlement_requirement: SettlementRequirement | None = None
    source_evidence_binding: PumpfunSnipingSourceEvidenceBinding | None = None

    # Define dataset spec post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the dataset spec post init workflow in explicit, reviewable steps.
        if isinstance(self.spec_version, bool) or not isinstance(self.spec_version, int):
            raise TypeError("dataset spec_version must be an integer")
        if self.spec_version != DATASET_SPEC_VERSION:
            raise ValueError(f"unsupported dataset spec version: {self.spec_version}")
        if not isinstance(self.network_id, NetworkId):
            # Fail the dataset spec post init path with TypeError for network id must be a
            # network id when isinstance and network id is true; do not continue
            # ambiguously.
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if isinstance(self.warmup_blocks, bool) or not isinstance(self.warmup_blocks, int):
            raise TypeError("warmup_blocks must be an integer")
        # Guard this path with self.warmup_blocks < 0 before applying effects.
        if self.warmup_blocks < 0:
            raise ValueError("warmup_blocks must be non-negative")
        evidence_contracts = _normalized_names(
            self.evidence_contracts,
            field="evidence_contracts",
            # Complete _normalized_names only after its evidence contracts inputs are visible
            # in dataset spec post init.
        )
        object.__setattr__(self, "evidence_contracts", evidence_contracts)
        _require_same_chain(
            self.decision_range,
            network_id=self.network_id,
            # Pass position schema id explicitly so _require_same_chain receives a
            # reviewable decision range and network id input in dataset spec post init.
            position_schema_id=self.position_schema_id,
            field="decision_range",
        )
        if self.settlement_tail is not None:
            # Handle the dataset spec post init self.settlement_tail is not None branch as
            # a distinct logical block.
            _require_same_chain(
                self.settlement_tail,
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                field="settlement_tail",
                # Complete _require_same_chain only after its settlement tail and network id
                # inputs are visible in dataset spec post init.
            )
            if self.settlement_tail.from_block_ordinal != self.decision_range.to_block_ordinal:
                raise ValueError("settlement tail must start at the decision range upper bound")
        if not self.capabilities:
            raise ValueError("dataset spec requires at least one capability")
        # Guard this path with not self.shards before applying effects.
        if not self.shards:
            raise ValueError("dataset spec requires at least one shard")

        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.capability_id.value))
        capability_ids = tuple(item.capability_id for item in capabilities)
        if len(set(capability_ids)) != len(capability_ids):
            # Fail the dataset spec post init path with ValueError for dataset spec has
            # duplicate capabilities when capability ids is true; do not continue
            # ambiguously.
            raise ValueError("dataset spec has duplicate capabilities")
        object.__setattr__(self, "capabilities", capabilities)

        requirement = self.settlement_requirement
        if requirement is not None:
            # Handle the dataset spec post init requirement is not None branch as a
            # distinct logical block.
            if not isinstance(requirement, SettlementRequirement):
                raise TypeError("settlement_requirement must be a SettlementRequirement or None")
            if self.settlement_tail is None:
                raise ValueError("a settlement requirement requires a bounded settlement tail")
            if self.settlement_tail.span > requirement.maximum_tail_blocks:
                # Fail the dataset spec post init path with ValueError for settlement tail
                # exceeds its declared hard guard when span, maximum tail blocks and
                # settlement tail is true; do not continue ambiguously.
                raise ValueError("settlement tail exceeds its declared hard guard")

        capability_ranges = tuple(
            sorted(self.capability_ranges, key=lambda item: item.capability_id.value)
        )
        range_ids = tuple(item.capability_id for item in capability_ranges)
        # Guard this path with range_ids != capability_ids before applying effects.
        if range_ids != capability_ids:
            raise ValueError("capability ranges must cover exactly the planned capabilities")
        for item in capability_ranges:
            # Process capability_ranges inside the bounded dataset spec post init loop.
            _require_same_chain(
                item.block_range,
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                field="capability extraction range",
                # Complete _require_same_chain only after its capability extraction range and
                # block range inputs are visible in dataset spec post init.
            )
            if item.block_range.from_block_ordinal > self.decision_range.from_block_ordinal:
                raise ValueError("capability range cannot start after the decision range")
            if item.block_range.to_block_ordinal < self.decision_range.to_block_ordinal:
                raise ValueError("capability range cannot end before the decision range")
            # Assemble extraction end once so the dataset spec post init workflow shares
            # one value.
            extraction_end = (
                self.decision_range.to_block_ordinal
                if self.settlement_tail is None
                else self.settlement_tail.to_block_ordinal
            )
            # Evaluate the complete dataset spec post init to block ordinal, extraction
            # end and block range condition before guarded effects.
            if item.block_range.to_block_ordinal > extraction_end:
                raise ValueError("capability range exceeds the declared settlement tail")
        object.__setattr__(self, "capability_ranges", capability_ranges)
        if requirement is not None:
            # Handle the dataset spec post init requirement is not None branch as a
            # distinct logical block.
            tail = self.settlement_tail
            if tail is None:  # pragma: no cover - guarded above
                raise AssertionError("settlement requirement lost its declared tail")
            streams_by_id = {item.capability_id: item.stream for item in capabilities}
            tail_end = tail.to_block_ordinal
            for item in capability_ranges:
                # Process capability_ranges inside the bounded dataset spec post init
                # loop.
                if (
                    streams_by_id[item.capability_id] in requirement.settlement_streams
                    and item.block_range.to_block_ordinal < tail_end
                ):
                    # Handle the dataset spec post init settlement streams, to block
                    # ordinal and tail end condition as a distinct block.
                    raise ValueError(
                        "a settlement capability does not reach the declared tail bound"
                    )

        evidence = tuple(sorted(self.cut_evidence, key=lambda item: item.capability_id.value))
        evidence_ids = tuple(item.capability_id for item in evidence)
        # Evaluate the complete dataset spec post init evidence ids condition before
        # guarded effects.
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("dataset spec has duplicate cut evidence")
        if not set(evidence_ids).issubset(capability_ids):
            raise ValueError("dataset cut evidence references an unplanned capability")
        if any(
            # Pass item explicitly so any receives a reviewable network id and position
            # schema id input in dataset spec post init.
            item.block_range.network_id != self.network_id
            or item.block_range.position_schema_id != self.position_schema_id
            for item in evidence
        ):
            raise ValueError("dataset cut evidence uses a different chain identity")
        # Invoke __setattr__ for cut evidence and evidence as a visible dataset spec post
        # init step.
        object.__setattr__(self, "cut_evidence", evidence)

        binding = self.source_evidence_binding
        if binding is not None:
            if not isinstance(binding, PumpfunSnipingSourceEvidenceBinding):
                raise TypeError(
                    "source_evidence_binding must be a PumpfunSnipingSourceEvidenceBinding or None"
                )
            if binding.launch_universe.decision_range != self.decision_range:
                raise ValueError("source evidence binding uses another decision range")
            if (
                binding.capability_mapping_digest != self.capability_mapping_digest
                or binding.query_template_digest != self.query_template_digest
            ):
                raise ValueError("source evidence binding uses another mapping/query contract")
            binding_capability_ids = tuple(item.capability_id for item in binding.receipt_refs)
            if binding_capability_ids != capability_ids:
                raise ValueError(
                    "source evidence binding must cover exactly the planned capabilities"
                )

        if tuple(shard.ordinal for shard in self.shards) != tuple(range(len(self.shards))):
            raise ValueError("dataset shard ordinals must be contiguous and zero-based")
        planned_by_id = {item.capability_id: item for item in capabilities}
        ranges_by_id = {item.capability_id: item.block_range for item in capability_ranges}
        # Evaluate the complete dataset spec post init capability id, capability ids and
        # shard condition before guarded effects.
        if {shard.capability_id for shard in self.shards} != set(capability_ids):
            raise ValueError("dataset shards must cover exactly the planned capabilities")
        for shard in self.shards:
            # Process self.shards inside the bounded dataset spec post init loop.
            planned = planned_by_id[shard.capability_id]
            if shard.columns != planned.columns:
                raise ValueError("each shard must select its capability's planned columns")
            _require_same_chain(
                shard.block_range,
                # Pass network id explicitly so _require_same_chain receives a reviewable
                # dataset shard and block range input in dataset spec post init.
                network_id=self.network_id,
                position_schema_id=self.position_schema_id,
                field="dataset shard",
            )
            capability_range = ranges_by_id[shard.capability_id]
            # Evaluate the complete dataset spec post init from block ordinal, to block
            # ordinal and block range condition before guarded effects.
            if (
                shard.block_range.from_block_ordinal < capability_range.from_block_ordinal
                or shard.block_range.to_block_ordinal > capability_range.to_block_ordinal
            ):
                raise ValueError("dataset shard is outside its capability extraction range")
        # Traverse capability_ids explicitly so each dataset spec post init iteration
        # remains traceable.
        for capability_id in capability_ids:
            # Process capability_ids inside the bounded dataset spec post init loop.
            ranges = tuple(
                shard.block_range for shard in self.shards if shard.capability_id == capability_id
            )
            expected_range = ranges_by_id[capability_id]
            if ranges[0].from_block_ordinal != expected_range.from_block_ordinal:
                # Fail the dataset spec post init path with ValueError for capability
                # shards do not start at the extraction frontier when from block ordinal,
                # expected range and ranges is true; do not continue ambiguously.
                raise ValueError("capability shards do not start at the extraction frontier")
            if ranges[-1].to_block_ordinal != expected_range.to_block_ordinal:
                raise ValueError("capability shards do not reach the extraction frontier")
            if any(
                left.to_block_ordinal != right.from_block_ordinal
                # Keep left visible while evaluating the to block ordinal, from block
                # ordinal and left guard.
                for left, right in pairwise(ranges)
            ):
                raise ValueError("capability shards contain a gap or overlap")

        expected_id = dataset_spec_identity_digest(
            spec_version=self.spec_version,
            # Pass source id explicitly so dataset_spec_identity_digest receives a
            # reviewable spec version and source id input in dataset spec post init.
            source_id=self.source_id,
            source_inspection_artifact_id=self.source_inspection_artifact_id,
            source_schema_fingerprint=self.source_schema_fingerprint,
            capability_mapping_digest=self.capability_mapping_digest,
            query_template_digest=self.query_template_digest,
            # Pass network id explicitly so dataset_spec_identity_digest receives a
            # reviewable spec version and source id input in dataset spec post init.
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            decision_range=self.decision_range,
            settlement_tail=self.settlement_tail,
            warmup_blocks=self.warmup_blocks,
            # Pass evidence contracts explicitly so dataset_spec_identity_digest receives
            # a reviewable spec version and source id input in dataset spec post init.
            evidence_contracts=self.evidence_contracts,
            capabilities=self.capabilities,
            capability_ranges=self.capability_ranges,
            cut_evidence=self.cut_evidence,
            shards=self.shards,
            # Pass settlement requirement explicitly so dataset_spec_identity_digest
            # receives a reviewable spec version and source id input in dataset spec post
            # init.
            settlement_requirement=self.settlement_requirement,
            source_evidence_binding=self.source_evidence_binding,
        )
        if self.spec_id.hex != expected_id.hex:
            raise ValueError("spec_id does not match the versioned dataset spec identity")


def dataset_spec_identity_digest(
    # Close the dataset spec identity digest signature after its explicit inputs.
    *,
    spec_version: int,
    source_id: SourceId,
    source_inspection_artifact_id: ArtifactId,
    source_schema_fingerprint: ContentDigest,
    # Keep the capability mapping digest input explicit in the dataset spec identity
    # digest contract.
    capability_mapping_digest: ContentDigest,
    query_template_digest: ContentDigest,
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
    decision_range: BlockRange,
    # Keep the settlement tail input explicit in the dataset spec identity digest
    # contract.
    settlement_tail: BlockRange | None,
    warmup_blocks: int,
    evidence_contracts: tuple[str, ...],
    capabilities: tuple[PlannedCapability, ...],
    capability_ranges: tuple[CapabilityExtractionRange, ...],
    # Keep the cut evidence input explicit in the dataset spec identity digest contract.
    cut_evidence: tuple[CapabilityCutEvidence, ...],
    shards: tuple[DatasetShard, ...],
    settlement_requirement: SettlementRequirement | None = None,
    source_evidence_binding: PumpfunSnipingSourceEvidenceBinding | None = None,
) -> ContentDigest:
    """Resolve the domain-tagged identity of a versioned dataset plan."""

    if spec_version != DATASET_SPEC_VERSION:
        raise ValueError(f"unsupported dataset spec version: {spec_version}")
    document = {
        "network_id": network_id.value,
        "position_schema_id": position_schema_id.value,
        # Register decision range through _block_range_identity so the document table
        # remains scannable.
        "decision_range": _block_range_identity(decision_range),
        "evidence_contracts": sorted(evidence_contracts),
        "settlement_tail": (
            None if settlement_tail is None else _block_range_identity(settlement_tail)
        ),
        # Register settlement requirement through _settlement_requirement_identity so the
        # document table remains scannable.
        "settlement_requirement": _settlement_requirement_identity(settlement_requirement),
        "source_evidence_binding": (
            None if source_evidence_binding is None else source_evidence_binding.identity_document()
        ),
        "capabilities": [
            _planned_capability_identity(item)
            for item in sorted(capabilities, key=lambda item: item.capability_id.value)
        ],
        # Keep the cut evidence component named inside the document contract.
        "cut_evidence": [
            _cut_evidence_identity(item)
            for item in sorted(cut_evidence, key=lambda item: item.capability_id.value)
        ],
        "capability_ranges": [
            # Complete the document group only after its semantic components are visible.
            {
                "block_range": _block_range_identity(item.block_range),
                "capability_id": item.capability_id.value,
            }
            for item in sorted(capability_ranges, key=lambda item: item.capability_id.value)
            # Complete the document group only after its semantic components are visible.
        ],
        "schema": "backtest.dataset-spec",
        "shards": [
            {
                "capability_id": shard.capability_id.value,
                # Register columns through list so the document table remains scannable.
                "columns": list(shard.columns),
                "block_range": _block_range_identity(shard.block_range),
                "ordinal": shard.ordinal,
            }
            for shard in shards
            # Complete the document group only after its semantic components are visible.
        ],
        "source": {
            "capability_mapping_digest": capability_mapping_digest.hex,
            "inspection_artifact_id": source_inspection_artifact_id.hex,
            "query_template_digest": query_template_digest.hex,
            # Keep the schema fingerprint component named inside the document contract.
            "schema_fingerprint": source_schema_fingerprint.hex,
            "source_id": source_id.value,
        },
        "spec_version": spec_version,
        "warmup_blocks": warmup_blocks,
        # Complete the document group only after its semantic components are visible.
    }
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        # Pass separators explicitly so encode receives a reviewable utf-8 input in
        # dataset spec identity digest.
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ContentDigest(sha256(_DATASET_SPEC_IDENTITY_DOMAIN + encoded).hexdigest())


def _settlement_requirement_identity(
    # Keep the value input explicit in the settlement requirement identity contract.
    value: SettlementRequirement | None,
) -> dict[str, object] | None:
    # Execute the settlement requirement identity workflow in explicit, reviewable steps.
    if value is None:
        return None
    return {
        "initial_delay_transactions": value.initial_delay_transactions,
        "maximum_followup_delay_transactions": value.maximum_followup_delay_transactions,
        # Include maximum tail blocks in the completed settlement requirement identity
        # result.
        "maximum_tail_blocks": value.maximum_tail_blocks,
        "minimum_duration_ns": value.minimum_duration_ns,
        "schema": value.schema,
        "settlement_streams": [item.value for item in value.settlement_streams],
        "target_stream": value.target_stream.value,
        # Return the completed settlement requirement identity result without a hidden
        # fallback.
    }


def _planned_capability_identity(capability: PlannedCapability) -> dict[str, object]:
    # Execute the planned capability identity workflow in explicit, reviewable steps.
    return {
        "capability_id": capability.capability_id.value,
        "columns": list(capability.columns),
        "fidelity": {
            "chain_finality": capability.fidelity.chain_finality.value,
            # Include completeness in the completed planned capability identity result.
            "completeness": capability.fidelity.completeness.value,
            "consistency": capability.fidelity.consistency.value,
            "fees": capability.fidelity.fees.value,
            "identity": capability.fidelity.identity.value,
            "ordering": capability.fidelity.ordering.value,
            # Include state in the completed planned capability identity result.
            "state": capability.fidelity.state.value,
        },
        "keyset_key_is_proven": capability.keyset_key_is_proven,
        "protocol": capability.protocol,
        "protocol_version": capability.protocol_version,
        # Include proofs in the completed planned capability identity result.
        "proofs": _capability_proofs_identity(capability.proofs),
        "schema_version": capability.schema_version,
        "stream": capability.stream.value,
        "total_key": list(capability.total_key),
        "utc_pruning_column": capability.utc_pruning_column,
        # Include utc pruning is proven in the completed planned capability identity
        # result.
        "utc_pruning_is_proven": capability.utc_pruning_is_proven,
    }


def _cut_evidence_identity(evidence: CapabilityCutEvidence) -> dict[str, object]:
    # Execute the cut evidence identity workflow in explicit, reviewable steps.
    return {
        "block_range": _block_range_identity(evidence.block_range),
        "capability_id": evidence.capability_id.value,
        "chain_finality": evidence.chain_finality.value,
        "completeness": evidence.completeness.value,
        # Include consistency in the completed cut evidence identity result.
        "consistency": evidence.consistency.value,
        "ingestion_watermark_to_block": evidence.ingestion_watermark_to_block,
        "snapshot_cut_to_block": evidence.snapshot_cut_to_block,
        "upstream_revision": evidence.upstream_revision,
    }


# Define block range identity as one focused operation with an explicit boundary.
def _block_range_identity(value: BlockRange) -> dict[str, object]:
    # Execute the block range identity workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed block range identity result without a hidden fallback.
    }


def _capability_proofs_identity(value: CapabilityProofs) -> dict[str, str]:
    return {field_name: getattr(value, field_name).value for field_name in CAPABILITY_PROOF_FIELDS}


# Keep the plan dataset request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PlanDatasetRequest:
    source_id: SourceId
    source_inspection_artifact_id: ArtifactId
    network_id: NetworkId
    # Declare position schema id explicitly in the plan dataset request contract.
    position_schema_id: PositionSchemaId
    decision_range: BlockRange
    warmup_blocks: int
    settlement_tail_blocks: int
    max_shard_blocks: int
    # Declare requested days explicitly in the plan dataset request contract.
    requested_days: int | None
    requirements: tuple[DataRequirement, ...]
    budget_limits: BudgetLimits
    query_limits: QueryLimits
    request_remote_estimate: bool = False

    # Define plan dataset request post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the plan dataset request post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            raise TypeError("position_schema_id must be a PositionSchemaId")
        _require_same_chain(
            # Pass self explicitly so _require_same_chain receives a reviewable decision
            # range and network id input in plan dataset request post init.
            self.decision_range,
            network_id=self.network_id,
            position_schema_id=self.position_schema_id,
            field="decision_range",
        )
        # Traverse warmup blocks and settlement tail blocks explicitly so each plan
        # dataset request post init iteration remains traceable.
        for field_name in ("warmup_blocks", "settlement_tail_blocks"):
            # Process warmup blocks and settlement tail blocks inside the bounded plan
            # dataset request post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        # Guard this path with self.max_shard_blocks <= 0 before applying effects.
        if self.max_shard_blocks <= 0:
            raise ValueError("max_shard_blocks must be positive")
        if self.requested_days is not None and self.requested_days <= 0:
            raise ValueError("requested_days must be positive when provided")
        if not self.requirements:
            # Fail the plan dataset request post init path with ValueError for at least
            # one data requirement is required when requirements is true; do not continue
            # ambiguously.
            raise ValueError("at least one data requirement is required")


# Keep the dataset plan contract and validation rules together.
@dataclass(frozen=True, slots=True)
class DatasetPlan:
    spec: DatasetSpec
    budget: BudgetReport
    query_limits: QueryLimits


# Keep the extraction request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    dataset_spec_id: ContentDigest
    shard: DatasetShard
    decision_range: BlockRange
    query_limits: QueryLimits

    def __post_init__(self) -> None:
        if not isinstance(self.decision_range, BlockRange):
            raise TypeError("decision_range must be a BlockRange")
        if (
            self.decision_range.network_id != self.shard.block_range.network_id
            or self.decision_range.position_schema_id != self.shard.block_range.position_schema_id
        ):
            raise ValueError("decision range and shard use different chain identities")
        if not isinstance(self.query_limits, QueryLimits):
            raise TypeError("query_limits must be QueryLimits")


# Keep the artifact kind contract and validation rules together.
class ArtifactKind(StrEnum):
    # Observational research artifacts are never executable snapshot/run substitutes.
    RESEARCH_SNAPSHOT = "RESEARCH_SNAPSHOT"
    RESEARCH_RESULT = "RESEARCH_RESULT"
    # Existing source and execution artifact generations retain their original values.
    SOURCE_INSPECTION = "SOURCE_INSPECTION"
    CANONICAL_DISTRIBUTION = "CANONICAL_DISTRIBUTION"
    SNAPSHOT = "SNAPSHOT"
    REPLAY_PACK = "REPLAY_PACK"
    # Declare delivery schedule explicitly in the artifact kind contract.
    DELIVERY_SCHEDULE = "DELIVERY_SCHEDULE"
    FEATURE_SET = "FEATURE_SET"
    LABEL_SET = "LABEL_SET"
    UNIVERSE = "UNIVERSE"
    MODEL_BUNDLE = "MODEL_BUNDLE"
    # Declare model schedule explicitly in the artifact kind contract.
    MODEL_SCHEDULE = "MODEL_SCHEDULE"
    PREDICTION_SET = "PREDICTION_SET"
    STRATEGY_BUNDLE = "STRATEGY_BUNDLE"
    SWEEP = "SWEEP"
    BENCHMARK = "BENCHMARK"
    # Declare run explicitly in the artifact kind contract.
    RUN = "RUN"


# Keep the artifact draft contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ArtifactDraft:
    kind: ArtifactKind
    build_key: ContentDigest
    input_artifact_ids: tuple[ArtifactId, ...] = ()


# Keep the committed artifact contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CommittedArtifact:
    artifact_id: ArtifactId
    kind: ArtifactKind
    manifest_digest: ContentDigest
    # Declare build key explicitly in the committed artifact contract.
    build_key: ContentDigest
    input_artifact_ids: tuple[ArtifactId, ...] = ()


# Keep the job type contract and validation rules together.
class JobType(StrEnum):
    # Research has separate strict acquisition and local-analysis payload decoders.
    PREPARE_RESEARCH = "PREPARE_RESEARCH"
    ANALYZE_WALLETS = "ANALYZE_WALLETS"
    # Existing jobs continue through their unchanged schema contracts.
    PREPARE_DATASET = "PREPARE_DATASET"
    COMPILE_REPLAY = "COMPILE_REPLAY"
    COMPILE_DELIVERY_SCHEDULE = "COMPILE_DELIVERY_SCHEDULE"
    RUN_BACKTEST = "RUN_BACKTEST"
    # Declare run sweep explicitly in the job type contract.
    RUN_SWEEP = "RUN_SWEEP"
    BUILD_FEATURES = "BUILD_FEATURES"
    BUILD_LABELS = "BUILD_LABELS"
    BUILD_UNIVERSE = "BUILD_UNIVERSE"
    TRAIN_MODEL = "TRAIN_MODEL"
    # Declare build model schedule explicitly in the job type contract.
    BUILD_MODEL_SCHEDULE = "BUILD_MODEL_SCHEDULE"
    PREDICT = "PREDICT"
    VERIFY_ARTIFACT = "VERIFY_ARTIFACT"
    GC = "GC"
    BACKUP = "BACKUP"
    # Declare benchmark explicitly in the job type contract.
    BENCHMARK = "BENCHMARK"


# Keep the attempt state contract and validation rules together.
class AttemptState(StrEnum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    # Declare failed explicitly in the attempt state contract.
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


# Keep the resolved job spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedJobSpec:
    spec_version: int
    spec_id: ContentDigest
    job_type: JobType
    # Declare canonical payload explicitly in the resolved job spec contract.
    canonical_payload: bytes
    payload_digest: ContentDigest
    input_artifact_ids: tuple[ArtifactId, ...] = ()

    def __post_init__(self) -> None:
        # Execute the resolved job spec post init workflow in explicit, reviewable steps.
        if isinstance(self.spec_version, bool) or not isinstance(self.spec_version, int):
            raise TypeError("spec_version must be an integer")
        if self.spec_version <= 0:
            raise ValueError("spec_version must be positive")
        canonical = canonicalize_job_payload(self.canonical_payload)
        # Guard this path with canonical != self.canonical_payload before applying
        # effects.
        if canonical != self.canonical_payload:
            raise ValueError("canonical_payload is not canonical JSON")
        if sha256(canonical).hexdigest() != self.payload_digest.hex:
            raise ValueError("payload_digest does not match canonical_payload")

        input_ids = tuple(sorted(self.input_artifact_ids, key=lambda item: item.hex))
        # Guard this path with len(set(input_ids)) != len(input_ids) before applying
        # effects.
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("input_artifact_ids must not contain duplicates")
        object.__setattr__(self, "input_artifact_ids", input_ids)
        expected_spec_id = resolved_job_spec_hex(
            spec_version=self.spec_version,
            # Pass job type explicitly so resolved_job_spec_hex receives a reviewable spec
            # version and value input in resolved job spec post init.
            job_type=self.job_type.value,
            payload_digest_hex=self.payload_digest.hex,
            input_artifact_hexes=(artifact_id.hex for artifact_id in input_ids),
        )
        if self.spec_id.hex != expected_spec_id:
            # Fail the resolved job spec post init path with ValueError for spec id does
            # not match the resolved job envelope when hex, expected spec id and spec id
            # is true; do not continue ambiguously.
            raise ValueError("spec_id does not match the resolved job envelope")


# Keep the list jobs request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ListJobsRequest:
    state: AttemptState | None = None
    limit: int = 100
    offset: int = 0

    # Define list jobs request post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the list jobs request post init workflow in explicit, reviewable steps.
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            # Fail the list jobs request post init path with TypeError for offset must be
            # an integer when isinstance and offset is true; do not continue ambiguously.
            raise TypeError("offset must be an integer")
        # Legacy positional scans remain bounded; interactive clients use keysets.
        if not 0 <= self.offset <= 10_000:
            raise ValueError("offset must be between 0 and 10000")


# Keep the job record contract and validation rules together.
@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: JobId
    spec: ResolvedJobSpec
    state: AttemptState
    # Declare state version explicitly in the job record contract.
    state_version: int
    submitted_at_ns: int = 0
    updated_at_ns: int = 0

    def __post_init__(self) -> None:
        # Validate independently: operational wall time may move backwards after an
        # NTP/manual clock step and neither timestamp participates in causal identity.
        for value, field_name in (
            (self.state_version, "state_version"),
            (self.submitted_at_ns, "submitted_at_ns"),
            (self.updated_at_ns, "updated_at_ns"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"job {field_name} must be a non-negative integer")


# Keep the progress level contract and validation rules together.
class ProgressLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ProgressStage(StrEnum):
    """Finite, safe lifecycle stages emitted outside execution hot loops."""

    VALIDATING_INPUTS = "VALIDATING_INPUTS"
    # Research phases identify bounded offline work without pretending to execute replay.
    PREPARING_RESEARCH = "PREPARING_RESEARCH"
    ANALYZING_WALLETS = "ANALYZING_WALLETS"
    # Existing canonical preparation/compilation phases keep their original interpretation.
    PREPARING_DATASET = "PREPARING_DATASET"
    COMPILING_REPLAY = "COMPILING_REPLAY"
    COMPILING_DELIVERY_SCHEDULE = "COMPILING_DELIVERY_SCHEDULE"
    BUILDING_FEATURES = "BUILDING_FEATURES"
    # Declare building universe explicitly in the progress stage contract.
    BUILDING_UNIVERSE = "BUILDING_UNIVERSE"
    BUILDING_LABELS = "BUILDING_LABELS"
    TRAINING_MODEL = "TRAINING_MODEL"
    BUILDING_MODEL_SCHEDULE = "BUILDING_MODEL_SCHEDULE"
    BUILDING_PREDICTIONS = "BUILDING_PREDICTIONS"
    # Declare running backtest explicitly in the progress stage contract.
    RUNNING_BACKTEST = "RUNNING_BACKTEST"
    RUNNING_SWEEP = "RUNNING_SWEEP"
    VERIFYING_OUTPUTS = "VERIFYING_OUTPUTS"
    PUBLISHING_RECEIPT = "PUBLISHING_RECEIPT"
    COMPLETED = "COMPLETED"


# Apply dataclass semantics to the following progress event contract.
@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One allowlisted child lifecycle update; never one market event."""

    attempt_id: AttemptId
    sequence: int
    level: ProgressLevel
    stage: ProgressStage
    completed_units: int | None = None
    # Declare total units explicitly in the progress event contract.
    total_units: int | None = None

    def __post_init__(self) -> None:
        # Execute the progress event post init workflow in explicit, reviewable steps.
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or not 1 <= self.sequence <= 2**63 - 1
        ):
            # Fail the progress event post init path with ValueError for progress sequence
            # must be a positive sqlite integer when isinstance and sequence is true; do
            # not continue ambiguously.
            raise ValueError("progress sequence must be a positive SQLite integer")
        _validate_progress_units(self.completed_units, self.total_units)


@dataclass(frozen=True, slots=True)
class JobProgressDetails:
    """Bounded supervisor-owned read model persisted for polling/SSE adapters."""

    sequence: int
    level: ProgressLevel
    stage: ProgressStage
    completed_units: int | None = None
    total_units: int | None = None
    # Declare coalesced events explicitly in the job progress details contract.
    coalesced_events: int = 1
    dropped_transport_frames: int = 0
    private_rss_bytes: int | None = None
    total_rss_bytes: int | None = None
    major_page_faults: int | None = None
    # Declare temporary disk bytes explicitly in the job progress details contract.
    temporary_disk_bytes: int | None = None

    def __post_init__(self) -> None:
        # Execute the job progress details post init workflow in explicit, reviewable
        # steps.
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or not 1 <= self.sequence <= 2**63 - 1
        ):
            # Fail the job progress details post init path with ValueError for progress
            # sequence must be a positive sqlite integer when isinstance and sequence is
            # true; do not continue ambiguously.
            raise ValueError("progress sequence must be a positive SQLite integer")
        _validate_progress_units(self.completed_units, self.total_units)
        for value, field_name in (
            (self.coalesced_events, "coalesced_events"),
            (self.dropped_transport_frames, "dropped_transport_frames"),
            # Traverse coalesced events and dropped transport frames explicitly so each job
            # progress details post init iteration remains traceable.
        ):
            # Process coalesced events and dropped transport frames inside the bounded job
            # progress details post init loop.
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**31 - 1:
                raise ValueError(f"{field_name} must be a bounded non-negative integer")
        if self.coalesced_events == 0:
            raise ValueError("coalesced_events must be positive")
        for counter, counter_name in (
            # Traverse private rss bytes, total rss bytes and major page faults explicitly
            # so each job progress details post init iteration remains traceable.
            (self.private_rss_bytes, "private_rss_bytes"),
            (self.total_rss_bytes, "total_rss_bytes"),
            (self.major_page_faults, "major_page_faults"),
            (self.temporary_disk_bytes, "temporary_disk_bytes"),
        ):
            # Process private rss bytes, total rss bytes and major page faults inside the
            # bounded job progress details post init loop.
            _require_non_negative(counter, field=counter_name)
            if counter is not None and counter > 2**63 - 1:
                raise ValueError(f"{counter_name} exceeds the SQLite integer range")
        if (
            self.private_rss_bytes is not None
            # Keep self visible while evaluating the private rss bytes and total rss bytes
            # guard.
            and self.total_rss_bytes is not None
            and self.private_rss_bytes > self.total_rss_bytes
        ):
            raise ValueError("private RSS cannot exceed total RSS")


# Keep the job event record contract and validation rules together.
@dataclass(frozen=True, slots=True)
class JobEventRecord:
    event_id: int
    job_id: JobId
    attempt_id: AttemptId | None
    # Declare event type explicitly in the job event record contract.
    event_type: str
    state_version: int
    created_at_ns: int
    progress: JobProgressDetails | None = None

    def __post_init__(self) -> None:
        # Execute the job event record post init workflow in explicit, reviewable steps.
        if self.event_id <= 0:
            raise ValueError("job event ID must be positive")
        if not self.event_type or self.event_type != self.event_type.strip():
            raise ValueError("job event type must be non-empty and trimmed")
        if self.state_version < 0 or self.created_at_ns < 0:
            # Fail the job event record post init path with ValueError for job event
            # version and timestamp must be non-negative when state version and created at
            # ns is true; do not continue ambiguously.
            raise ValueError("job event version and timestamp must be non-negative")
        if (self.event_type == "ATTEMPT_PROGRESS") != (self.progress is not None):
            raise ValueError("only ATTEMPT_PROGRESS events carry progress details")


# Keep the list job events request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ListJobEventsRequest:
    job_id: JobId
    after_event_id: int = 0
    limit: int = 200

    # Define list job events request post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the list job events request post init workflow in explicit, reviewable
        # steps.
        if self.after_event_id < 0:
            raise ValueError("after_event_id must be non-negative")
        if not 1 <= self.limit <= 1_000:
            raise ValueError("job event limit must be between 1 and 1000")


# Keep the job attempt contract and validation rules together.
@dataclass(frozen=True, slots=True)
class JobAttempt:
    attempt_id: AttemptId
    job_id: JobId
    spec: ResolvedJobSpec
    # Declare state explicitly in the job attempt contract.
    state: AttemptState
    state_version: int


# Keep the resource capacity contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResourceCapacity:
    available_memory_bytes: int
    available_process_slots: int


# Keep the process state contract and validation rules together.
class ProcessState(StrEnum):
    RUNNING = "RUNNING"
    EXITED = "EXITED"


# Keep the process handle contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProcessHandle:
    process_id: int
    start_token: str


# Keep the process status contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProcessStatus:
    state: ProcessState
    exit_code: int | None = None
    private_rss_bytes: int | None = None
    # Declare total rss bytes explicitly in the process status contract.
    total_rss_bytes: int | None = None
    child_swap_bytes: int | None = None
    host_swap_in_bytes: int | None = None
    host_swap_out_bytes: int | None = None
    major_page_faults: int | None = None
    # Declare temporary disk bytes explicitly in the process status contract.
    temporary_disk_bytes: int | None = None
    progress_events: tuple[ProgressEvent, ...] = ()
    dropped_progress_frames: int = 0

    def __post_init__(self) -> None:
        # Execute the process status post init workflow in explicit, reviewable steps.
        counters = (
            self.private_rss_bytes,
            self.total_rss_bytes,
            self.child_swap_bytes,
            self.host_swap_in_bytes,
            # Keep the self component named inside the counters contract.
            self.host_swap_out_bytes,
            self.major_page_faults,
            self.temporary_disk_bytes,
        )
        if any(
            # Pass value explicitly so any receives a reviewable isinstance and value
            # input in process status post init.
            value is not None
            and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
            for value in counters
        ):
            raise ValueError("process resource counters must be non-negative integers")
        # Evaluate the complete process status post init state, running and exit code
        # condition before guarded effects.
        if self.state is ProcessState.RUNNING and self.exit_code is not None:
            raise ValueError("a running process cannot have an exit code")
        if len(self.progress_events) > 32:
            raise ValueError("one process probe returns at most 32 progress events")
        if any(
            # Pass current explicitly so any receives a reviewable sequence and progress
            # events input in process status post init.
            current.sequence >= following.sequence
            for current, following in pairwise(self.progress_events)
        ):
            raise ValueError("process progress events must have increasing sequences")
        if (
            # Keep isinstance visible while evaluating the isinstance and dropped progress
            # frames guard.
            isinstance(self.dropped_progress_frames, bool)
            or not isinstance(self.dropped_progress_frames, int)
            or self.dropped_progress_frames < 0
        ):
            raise ValueError("dropped progress frame count must be non-negative")


# Define validate progress units as one focused operation with an explicit boundary.
def _validate_progress_units(completed: int | None, total: int | None) -> None:
    # Execute the validate progress units workflow in explicit, reviewable steps.
    _require_non_negative(completed, field="completed_units")
    _require_non_negative(total, field="total_units")
    if completed is not None and total is not None and completed > total:
        raise ValueError("completed_units cannot exceed total_units")


@dataclass(frozen=True, slots=True)
# Keep the strategy requirements contract and validation rules together.
class StrategyRequirements:
    data_requirements: tuple[DataRequirement, ...]
