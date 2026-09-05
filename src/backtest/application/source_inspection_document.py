"""Versioned, canonical source-inspection artifact documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256

# Import typing at the visible module dependency boundary.
from typing import Any, cast

from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import (
    CAPABILITY_PROOF_FIELDS,
    BoundedSourceEvidenceReceipt,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    EvidenceStatus,
    # Include source column so the models dependency remains explicit.
    SourceColumn,
    SourceInspection,
    SourceMetadata,
    SourceTable,
)
from backtest.application.source_evidence import (
    LaunchUniverseEvidence,
    SkippedSlotSentinelEvidence,
    TerminalLifecycleOrderingEvidence,
)

# Import source fingerprint at the visible module dependency boundary.
from backtest.application.source_fingerprint import source_schema_fingerprint
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.identifiers import (
    CapabilityId,
    ContentDigest,
    NetworkId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
    SourceId,
)
from backtest.domain.time import BlockRange

SOURCE_INSPECTION_ARTIFACT_SCHEMA = "source-inspection/v5"
# Bind source inspection document version once as an explicit module-level contract.
SOURCE_INSPECTION_DOCUMENT_VERSION = 5
_BUILD_KEY_DOMAIN = b"backtest.source-inspection.build-key.v5\x00"


def canonical_json(value: object) -> bytes:
    # Execute the canonical json workflow in explicit, reviewable steps.
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        # Pass sort keys explicitly so encode receives a reviewable utf-8 input in
        # canonical json.
        sort_keys=True,
    ).encode("utf-8")


def source_inspection_payload(inspection: SourceInspection) -> bytes:
    # Execute the source inspection payload workflow in explicit, reviewable steps.
    metadata = inspection.metadata
    mapping_digest = metadata.capability_mapping_digest
    query_digest = metadata.query_template_digest
    if mapping_digest is None or query_digest is None:
        raise ValueError("source inspection is missing required mapping/query digests")
    # Return the completed source inspection payload result without a hidden fallback.
    return canonical_json(
        {
            "capabilities": [_capability_payload(item) for item in metadata.capabilities],
            "capability_mapping_digest": mapping_digest.hex,
            "cut_evidence": [_cut_evidence_payload(item) for item in metadata.cut_evidence],
            # Keep evidence receipts named so the capabilities and capability mapping
            # digest payload passed to canonical_json remains self-describing within
            # source inspection payload.
            "evidence_receipts": [
                _evidence_receipt_payload(item) for item in metadata.evidence_receipts
            ],
            "inspected_at": inspection.inspected_at.isoformat(),
            "network_id": metadata.network_id.value,
            # Keep position schema id named so the capabilities and capability mapping
            # digest payload passed to canonical_json remains self-describing within
            # source inspection payload.
            "position_schema_id": metadata.position_schema_id.value,
            "query_template_digest": query_digest.hex,
            "schema_fingerprint": inspection.schema_fingerprint.hex,
            "server_version": metadata.server_version,
            "source_id": metadata.source_id.value,
            # Include tables in the completed source inspection payload result.
            "tables": [_table_payload(item) for item in metadata.tables],
            "version": SOURCE_INSPECTION_DOCUMENT_VERSION,
        }
    )


def source_inspection_manifest(inspection: SourceInspection) -> bytes:
    # Execute the source inspection manifest workflow in explicit, reviewable steps.
    metadata = inspection.metadata
    mapping_digest = metadata.capability_mapping_digest
    query_digest = metadata.query_template_digest
    if mapping_digest is None or query_digest is None:
        raise ValueError("source inspection is missing required mapping/query digests")
    # Return the completed source inspection manifest result without a hidden fallback.
    return canonical_json(
        {
            "artifact_schema": SOURCE_INSPECTION_ARTIFACT_SCHEMA,
            "capability_mapping_digest": mapping_digest.hex,
            "evidence_receipt_ids": [item.receipt_id.hex for item in metadata.evidence_receipts],
            # Include inspected at in the completed source inspection manifest result.
            "inspected_at": inspection.inspected_at.isoformat(),
            "inspection_file": "inspection.json",
            "network_id": metadata.network_id.value,
            "position_schema_id": metadata.position_schema_id.value,
            "query_template_digest": query_digest.hex,
            # Keep schema fingerprint named so the artifact schema and capability mapping
            # digest payload passed to canonical_json remains self-describing within
            # source inspection manifest.
            "schema_fingerprint": inspection.schema_fingerprint.hex,
            "source_id": metadata.source_id.value,
        }
    )


def source_inspection_build_key(inspection: SourceInspection) -> ContentDigest:
    # Execute the source inspection build key workflow in explicit, reviewable steps.
    metadata = inspection.metadata
    mapping_digest = metadata.capability_mapping_digest
    query_digest = metadata.query_template_digest
    if mapping_digest is None or query_digest is None:
        raise ValueError("source inspection is missing required mapping/query digests")
    # Assemble material once so the source inspection build key workflow shares one value.
    material = canonical_json(
        {
            "capability_mapping_digest": mapping_digest.hex,
            "evidence_receipt_ids": [item.receipt_id.hex for item in metadata.evidence_receipts],
            "inspected_at": inspection.inspected_at.isoformat(),
            # Keep query template digest named so the capability mapping digest and
            # evidence receipt ids payload passed to canonical_json remains self-
            # describing within source inspection build key.
            "query_template_digest": query_digest.hex,
            "schema": SOURCE_INSPECTION_ARTIFACT_SCHEMA,
            "schema_fingerprint": inspection.schema_fingerprint.hex,
            "network_id": metadata.network_id.value,
            "position_schema_id": metadata.position_schema_id.value,
            # Keep source id named so the capability mapping digest and evidence receipt
            # ids payload passed to canonical_json remains self-describing within source
            # inspection build key.
            "source_id": metadata.source_id.value,
        }
    )
    return ContentDigest(sha256(_BUILD_KEY_DOMAIN + material).hexdigest())


def decode_source_inspection(manifest_bytes: bytes, inspection_bytes: bytes) -> SourceInspection:
    """Decode a canonical v5 inspection and verify every committed pin."""

    raw_manifest = _canonical_object(manifest_bytes, label="source inspection manifest")
    artifact_schema = raw_manifest.get("artifact_schema")
    if artifact_schema in {
        "source-inspection/v1",
        "source-inspection/v2",
        # Keep source-inspection v3 visible while evaluating the artifact schema guard.
        "source-inspection/v3",
        "source-inspection/v4",
    }:
        raise ReprepareRequiredError(str(artifact_schema))
    _exact_keys(
        raw_manifest,
        # Open the artifact schema and capability mapping digest payload explicitly for
        # _exact_keys within decode source inspection.
        {
            "artifact_schema",
            "capability_mapping_digest",
            "evidence_receipt_ids",
            "inspected_at",
            # Pass inspection file explicitly so _exact_keys receives a reviewable
            # artifact schema and capability mapping digest input in decode source
            # inspection.
            "inspection_file",
            "network_id",
            "position_schema_id",
            "query_template_digest",
            "schema_fingerprint",
            # Pass source id explicitly so _exact_keys receives a reviewable artifact
            # schema and capability mapping digest input in decode source inspection.
            "source_id",
        },
        label="source inspection manifest",
    )
    if raw_manifest["artifact_schema"] != SOURCE_INSPECTION_ARTIFACT_SCHEMA:
        # Fail the decode source inspection path with ValueError for unsupported source
        # inspection artifact schema when source inspection artifact schema, raw manifest
        # and artifact schema is true; do not continue ambiguously.
        raise ValueError("unsupported source inspection artifact schema")
    if raw_manifest["inspection_file"] != "inspection.json":
        raise ValueError("source inspection payload reference is invalid")

    raw = _canonical_object(inspection_bytes, label="source inspection payload")
    _exact_keys(
        # Pass raw explicitly so _exact_keys receives a reviewable capabilities and
        # capability mapping digest input in decode source inspection.
        raw,
        {
            "capabilities",
            "capability_mapping_digest",
            "cut_evidence",
            # Pass evidence receipts explicitly so _exact_keys receives a reviewable
            # capabilities and capability mapping digest input in decode source
            # inspection.
            "evidence_receipts",
            "inspected_at",
            "network_id",
            "position_schema_id",
            "query_template_digest",
            # Pass schema fingerprint explicitly so _exact_keys receives a reviewable
            # capabilities and capability mapping digest input in decode source
            # inspection.
            "schema_fingerprint",
            "server_version",
            "source_id",
            "tables",
            "version",
            # Close the capabilities and capability mapping digest payload only after all
            # decode source inspection fields are present.
        },
        label="source inspection payload",
    )
    if raw["version"] != SOURCE_INSPECTION_DOCUMENT_VERSION:
        raise ValueError("unsupported source inspection document version")

    # Assemble source id once so the decode source inspection workflow shares one value.
    source_id = SourceId(_string(raw, "source_id"))
    mapping_digest = _digest(raw, "capability_mapping_digest")
    query_digest = _digest(raw, "query_template_digest")
    metadata = SourceMetadata(
        source_id=source_id,
        # Keep the network id and string NetworkId step visible while building metadata.
        network_id=NetworkId(_string(raw, "network_id")),
        position_schema_id=PositionSchemaId(_string(raw, "position_schema_id")),
        server_version=_string(raw, "server_version"),
        tables=tuple(_parse_table(item) for item in _object_list(raw, "tables")),
        capabilities=tuple(_parse_capability(item) for item in _object_list(raw, "capabilities")),
        # Pass capability mapping digest explicitly so SourceMetadata receives a
        # reviewable network id and position schema id input in decode source inspection.
        capability_mapping_digest=mapping_digest,
        query_template_digest=query_digest,
        cut_evidence=tuple(_parse_cut_evidence(item) for item in _object_list(raw, "cut_evidence")),
        evidence_receipts=tuple(
            _parse_evidence_receipt(item)
            # Keep the raw _object_list step visible while building metadata.
            for item in _object_list(raw, "evidence_receipts")
            # Complete tuple only after its evidence receipts and parse evidence receipt
            # inputs are visible in decode source inspection.
        ),
    )
    inspection = SourceInspection(
        metadata=metadata,
        schema_fingerprint=_digest(raw, "schema_fingerprint"),
        # Keep the raw _datetime step visible while building inspection.
        inspected_at=_datetime(raw, "inspected_at"),
    )
    if source_schema_fingerprint(metadata).hex != inspection.schema_fingerprint.hex:
        raise ValueError("source inspection schema fingerprint does not match its payload")
    if source_inspection_payload(inspection) != inspection_bytes:
        # Fail the decode source inspection path with ValueError for source inspection
        # payload is not semantically canonical when inspection bytes, source inspection
        # payload and inspection is true; do not continue ambiguously.
        raise ValueError("source inspection payload is not semantically canonical")
    if source_inspection_manifest(inspection) != manifest_bytes:
        raise ValueError("source inspection manifest does not match its payload")
    return inspection


def _capability_payload(capability: CapabilityDescriptor) -> dict[str, object]:
    # Execute the capability payload workflow in explicit, reviewable steps.
    return {
        "capability_id": capability.capability_id.value,
        "columns": list(capability.columns),
        "fidelity": _fidelity_payload(capability.fidelity),
        "keyset_key_is_proven": capability.keyset_key_is_proven,
        # Include mandatory columns in the completed capability payload result.
        "mandatory_columns": list(capability.mandatory_columns),
        "protocol": capability.protocol,
        "protocol_version": capability.protocol_version,
        "proofs": _proofs_payload(capability.proofs),
        "schema_version": capability.schema_version,
        # Include stream in the completed capability payload result.
        "stream": capability.stream.value,
        "total_key": list(capability.total_key),
        "utc_pruning_column": capability.utc_pruning_column,
        "utc_pruning_is_proven": capability.utc_pruning_is_proven,
    }


# Define fidelity payload as one focused operation with an explicit boundary.
def _fidelity_payload(fidelity: SourceFidelity) -> dict[str, str]:
    # Execute the fidelity payload workflow in explicit, reviewable steps.
    return {
        "chain_finality": fidelity.chain_finality.value,
        "completeness": fidelity.completeness.value,
        "consistency": fidelity.consistency.value,
        "fees": fidelity.fees.value,
        # Include identity in the completed fidelity payload result.
        "identity": fidelity.identity.value,
        "ordering": fidelity.ordering.value,
        "state": fidelity.state.value,
    }


def _proofs_payload(proofs: CapabilityProofs) -> dict[str, str]:
    # Return the completed proofs payload result without a hidden fallback.
    return {field_name: getattr(proofs, field_name).value for field_name in CAPABILITY_PROOF_FIELDS}


def _cut_evidence_payload(evidence: CapabilityCutEvidence) -> dict[str, object]:
    # Execute the cut evidence payload workflow in explicit, reviewable steps.
    return {
        "block_range": _block_range_payload(evidence.block_range),
        "capability_id": evidence.capability_id.value,
        "chain_finality": evidence.chain_finality.value,
        "completeness": evidence.completeness.value,
        # Include consistency in the completed cut evidence payload result.
        "consistency": evidence.consistency.value,
        "ingestion_watermark_to_block": evidence.ingestion_watermark_to_block,
        "snapshot_cut_to_block": evidence.snapshot_cut_to_block,
        "upstream_revision": evidence.upstream_revision,
    }


# Define evidence receipt payload as one focused operation with an explicit boundary.
def _evidence_receipt_payload(receipt: BoundedSourceEvidenceReceipt) -> dict[str, object]:
    # Execute the evidence receipt payload workflow in explicit, reviewable steps.
    return {
        "capability_id": receipt.capability_id.value,
        "capability_schema_version": receipt.capability_schema_version,
        "capability_mapping_digest": receipt.capability_mapping_digest.hex,
        "cut_evidence": _cut_evidence_payload(receipt.cut_evidence),
        "decision_range": _block_range_payload(receipt.decision_range),
        "launch_universe": (
            None if receipt.launch_universe is None else receipt.launch_universe.identity_document()
        ),
        "normalizer_digest": receipt.normalizer_digest.hex,
        # Include observed rows in the completed evidence receipt payload result.
        "observed_rows": receipt.observed_rows,
        "proofs": _proofs_payload(receipt.proofs),
        "projector_digest": receipt.projector_digest.hex,
        "protocol_version": receipt.protocol_version,
        "query_fingerprints": [item.hex for item in receipt.query_fingerprints],
        "query_template_digest": receipt.query_template_digest.hex,
        # Include receipt id in the completed evidence receipt payload result.
        "receipt_id": receipt.receipt_id.hex,
        "result_digest": receipt.result_digest.hex,
        "schema": receipt.schema,
        "skipped_slot_sentinel": (
            None
            if receipt.skipped_slot_sentinel is None
            else receipt.skipped_slot_sentinel.identity_document()
        ),
        "source_id": receipt.source_id.value,
        "source_fidelity": _fidelity_payload(receipt.source_fidelity),
        "terminal_lifecycle_ordering": (
            None
            if receipt.terminal_lifecycle_ordering is None
            else receipt.terminal_lifecycle_ordering.identity_document()
        ),
    }


# Define block range payload as one focused operation with an explicit boundary.
def _block_range_payload(value: BlockRange) -> dict[str, object]:
    # Execute the block range payload workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed block range payload result without a hidden fallback.
    }


def _table_payload(table: SourceTable) -> dict[str, object]:
    # Execute the table payload workflow in explicit, reviewable steps.
    return {
        "columns": [
            {
                "name": column.name,
                "nullable": column.nullable,
                # Include type name in the completed table payload result.
                "type_name": column.type_name,
            }
            for column in table.columns
        ],
        "engine": table.engine,
        # Include name in the completed table payload result.
        "name": table.name,
        "partition_key": table.partition_key,
        "sorting_key": table.sorting_key,
    }


def _parse_capability(raw: Mapping[str, Any]) -> CapabilityDescriptor:
    # Execute the parse capability workflow in explicit, reviewable steps.
    _exact_keys(
        raw,
        {
            "capability_id",
            "columns",
            # Pass fidelity explicitly so _exact_keys receives a reviewable capability id
            # and columns input in parse capability.
            "fidelity",
            "keyset_key_is_proven",
            "mandatory_columns",
            "protocol",
            "protocol_version",
            # Pass proofs explicitly so _exact_keys receives a reviewable capability id
            # and columns input in parse capability.
            "proofs",
            "schema_version",
            "stream",
            "total_key",
            "utc_pruning_column",
            # Pass utc pruning is proven explicitly so _exact_keys receives a reviewable
            # capability id and columns input in parse capability.
            "utc_pruning_is_proven",
        },
        label="capability",
    )
    fidelity_raw = raw["fidelity"]
    # Guard this path with not isinstance(fidelity_raw, dict) before applying effects.
    if not isinstance(fidelity_raw, dict):
        raise ValueError("capability fidelity must be an object")
    _exact_keys(
        fidelity_raw,
        {"chain_finality", "completeness", "consistency", "fees", "identity", "ordering", "state"},
        # Pass label explicitly so _exact_keys receives a reviewable chain finality and
        # completeness input in parse capability.
        label="capability fidelity",
    )
    utc_column = raw["utc_pruning_column"]
    if utc_column is not None and not isinstance(utc_column, str):
        raise ValueError("UTC pruning column must be a string or null")
    # Return the completed parse capability result without a hidden fallback.
    return CapabilityDescriptor(
        capability_id=CapabilityId(_string(raw, "capability_id")),
        protocol=_string(raw, "protocol"),
        protocol_version=_string(raw, "protocol_version"),
        schema_version=_string(raw, "schema_version"),
        # Include stream in the completed parse capability result.
        stream=CapabilityStream(_string(raw, "stream")),
        columns=_string_tuple(raw, "columns"),
        mandatory_columns=_string_tuple(raw, "mandatory_columns"),
        fidelity=_parse_fidelity(fidelity_raw),
        proofs=_parse_proofs(raw["proofs"]),
        total_key=_string_tuple(raw, "total_key"),
        keyset_key_is_proven=_boolean(raw, "keyset_key_is_proven"),
        # Pass utc pruning column explicitly so CapabilityDescriptor receives a reviewable
        # capability id and protocol input in parse capability.
        utc_pruning_column=utc_column,
        utc_pruning_is_proven=_boolean(raw, "utc_pruning_is_proven"),
    )


def _parse_proofs(raw: object) -> CapabilityProofs:
    # Execute the parse proofs workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise ValueError("capability proofs must be an object")
    _exact_keys(raw, set(CAPABILITY_PROOF_FIELDS), label="capability proofs")
    return CapabilityProofs(
        **{
            # Include field name in the completed parse proofs result.
            field_name: EvidenceStatus(_string(raw, field_name))
            for field_name in CAPABILITY_PROOF_FIELDS
        }
    )


def _parse_cut_evidence(raw: Mapping[str, Any]) -> CapabilityCutEvidence:
    # Execute the parse cut evidence workflow in explicit, reviewable steps.
    _exact_keys(
        raw,
        {
            "capability_id",
            "chain_finality",
            # Pass completeness explicitly so _exact_keys receives a reviewable capability
            # id and chain finality input in parse cut evidence.
            "completeness",
            "consistency",
            "block_range",
            "ingestion_watermark_to_block",
            "snapshot_cut_to_block",
            # Pass upstream revision explicitly so _exact_keys receives a reviewable
            # capability id and chain finality input in parse cut evidence.
            "upstream_revision",
        },
        label="cut evidence",
    )
    watermark = raw["ingestion_watermark_to_block"]
    # Evaluate the complete parse cut evidence watermark and isinstance condition before
    # guarded effects.
    if watermark is not None and (isinstance(watermark, bool) or not isinstance(watermark, int)):
        raise ValueError("ingestion watermark must be an integer or null")
    revision = raw["upstream_revision"]
    if revision is not None and not isinstance(revision, str):
        raise ValueError("upstream revision must be a string or null")
    # Assemble block range once so the parse cut evidence workflow shares one value.
    block_range = _parse_block_range(raw["block_range"])
    return CapabilityCutEvidence(
        capability_id=CapabilityId(_string(raw, "capability_id")),
        block_range=block_range,
        snapshot_cut_to_block=_integer(raw, "snapshot_cut_to_block"),
        # Include chain finality in the completed parse cut evidence result.
        chain_finality=ChainFinality(_string(raw, "chain_finality")),
        ingestion_watermark_to_block=watermark,
        completeness=IngestionCompleteness(_string(raw, "completeness")),
        consistency=SourceConsistency(_string(raw, "consistency")),
        upstream_revision=revision,
        # Complete CapabilityCutEvidence only after its capability id and snapshot cut to
        # block inputs are visible in parse cut evidence.
    )


def _parse_evidence_receipt(raw: Mapping[str, Any]) -> BoundedSourceEvidenceReceipt:
    # Execute the parse evidence receipt workflow in explicit, reviewable steps.
    if raw.get("schema") == "bounded-source-evidence/v1":
        raise ReprepareRequiredError("bounded-source-evidence/v1")
    _exact_keys(
        raw,
        {
            "capability_id",
            "capability_schema_version",
            # Pass capability mapping digest explicitly so _exact_keys receives a
            # reviewable capability id and capability schema version input in parse
            # evidence receipt.
            "capability_mapping_digest",
            "cut_evidence",
            "decision_range",
            "launch_universe",
            "normalizer_digest",
            "observed_rows",
            "proofs",
            "projector_digest",
            "protocol_version",
            # Pass query fingerprints explicitly so _exact_keys receives a reviewable
            # capability id and capability schema version input in parse evidence receipt.
            "query_fingerprints",
            "query_template_digest",
            "receipt_id",
            "result_digest",
            "schema",
            "skipped_slot_sentinel",
            # Pass source id explicitly so _exact_keys receives a reviewable capability id
            # and capability schema version input in parse evidence receipt.
            "source_id",
            "source_fidelity",
            "terminal_lifecycle_ordering",
        },
        label="bounded source evidence receipt",
    )
    schema = _string(raw, "schema")
    return BoundedSourceEvidenceReceipt(
        # Include receipt id in the completed parse evidence receipt result.
        receipt_id=_digest(raw, "receipt_id"),
        source_id=SourceId(_string(raw, "source_id")),
        capability_id=CapabilityId(_string(raw, "capability_id")),
        protocol_version=_string(raw, "protocol_version"),
        capability_schema_version=_string(raw, "capability_schema_version"),
        # Include capability mapping digest in the completed parse evidence receipt
        # result.
        capability_mapping_digest=_digest(raw, "capability_mapping_digest"),
        query_template_digest=_digest(raw, "query_template_digest"),
        projector_digest=_digest(raw, "projector_digest"),
        normalizer_digest=_digest(raw, "normalizer_digest"),
        cut_evidence=_parse_cut_evidence(_object(raw, "cut_evidence")),
        decision_range=_parse_block_range(raw["decision_range"]),
        proofs=_parse_proofs(raw["proofs"]),
        source_fidelity=_parse_fidelity(_object(raw, "source_fidelity")),
        query_fingerprints=tuple(
            # Include content digest in the completed parse evidence receipt result.
            ContentDigest(value)
            for value in _string_tuple(raw, "query_fingerprints")
        ),
        result_digest=_digest(raw, "result_digest"),
        observed_rows=_integer(raw, "observed_rows"),
        launch_universe=_parse_launch_universe(raw["launch_universe"]),
        skipped_slot_sentinel=_parse_skipped_slot_sentinel(raw["skipped_slot_sentinel"]),
        terminal_lifecycle_ordering=_parse_terminal_lifecycle_ordering(
            raw["terminal_lifecycle_ordering"]
        ),
        # Include schema in the completed parse evidence receipt result.
        schema=schema,
        # Complete BoundedSourceEvidenceReceipt only after its receipt id and source id inputs
        # are visible in parse evidence receipt.
    )


def _parse_fidelity(raw: Mapping[str, Any]) -> SourceFidelity:
    _exact_keys(
        raw,
        {"chain_finality", "completeness", "consistency", "fees", "identity", "ordering", "state"},
        label="source fidelity",
    )
    return SourceFidelity(
        identity=IdentityFidelity(_string(raw, "identity")),
        ordering=OrderingFidelity(_string(raw, "ordering")),
        state=StateFidelity(_string(raw, "state")),
        fees=FeesFidelity(_string(raw, "fees")),
        chain_finality=ChainFinality(_string(raw, "chain_finality")),
        completeness=IngestionCompleteness(_string(raw, "completeness")),
        consistency=SourceConsistency(_string(raw, "consistency")),
    )


def _parse_launch_universe(raw: object) -> LaunchUniverseEvidence | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("launch universe evidence must be an object or null")
    _exact_keys(
        raw,
        {
            "classified_count",
            "decision_range",
            "eligible_count",
            "excluded_count",
            "exclusion_reason",
            "ordered_exclusion_digest",
            "policy_id",
            "schema",
        },
        label="launch universe evidence",
    )
    return LaunchUniverseEvidence(
        decision_range=_parse_block_range(raw["decision_range"]),
        policy_id=_string(raw, "policy_id"),
        classified_count=_integer(raw, "classified_count"),
        eligible_count=_integer(raw, "eligible_count"),
        excluded_count=_integer(raw, "excluded_count"),
        ordered_exclusion_digest=_digest(raw, "ordered_exclusion_digest"),
        exclusion_reason=_string(raw, "exclusion_reason"),
        schema=_string(raw, "schema"),
    )


def _parse_skipped_slot_sentinel(raw: object) -> SkippedSlotSentinelEvidence | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("skipped-slot sentinel evidence must be an object or null")
    _exact_keys(
        raw,
        {"ordered_sentinel_digest", "profile_id", "recognized_count", "schema"},
        label="skipped-slot sentinel evidence",
    )
    return SkippedSlotSentinelEvidence(
        profile_id=_string(raw, "profile_id"),
        recognized_count=_integer(raw, "recognized_count"),
        ordered_sentinel_digest=_digest(raw, "ordered_sentinel_digest"),
        schema=_string(raw, "schema"),
    )


def _parse_terminal_lifecycle_ordering(
    raw: object,
) -> TerminalLifecycleOrderingEvidence | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("terminal lifecycle ordering evidence must be an object or null")
    _exact_keys(
        raw,
        {"derived_group_count", "ordered_group_digest", "profile_id", "schema"},
        label="terminal lifecycle ordering evidence",
    )
    return TerminalLifecycleOrderingEvidence(
        profile_id=_string(raw, "profile_id"),
        derived_group_count=_integer(raw, "derived_group_count"),
        ordered_group_digest=_digest(raw, "ordered_group_digest"),
        schema=_string(raw, "schema"),
    )


def _parse_block_range(raw: object) -> BlockRange:
    # Execute the parse block range workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise ValueError("block range must be an object")
    _exact_keys(
        raw,
        {
            # Pass from block ordinal explicitly so _exact_keys receives a reviewable from
            # block ordinal and network id input in parse block range.
            "from_block_ordinal",
            "network_id",
            "position_schema_id",
            "to_block_ordinal",
        },
        # Pass label explicitly so _exact_keys receives a reviewable from block ordinal
        # and network id input in parse block range.
        label="block range",
    )
    return BlockRange(
        NetworkId(_string(raw, "network_id")),
        PositionSchemaId(_string(raw, "position_schema_id")),
        # Include integer in the completed parse block range result.
        _integer(raw, "from_block_ordinal"),
        _integer(raw, "to_block_ordinal"),
    )


def _parse_table(raw: Mapping[str, Any]) -> SourceTable:
    # Execute the parse table workflow in explicit, reviewable steps.
    _exact_keys(
        raw,
        {"columns", "engine", "name", "partition_key", "sorting_key"},
        label="source table",
    )
    # Assemble columns once so the parse table workflow shares one value.
    columns = []
    for column in _object_list(raw, "columns"):
        # Process _object_list(raw, 'columns') inside the bounded parse table loop.
        _exact_keys(column, {"name", "nullable", "type_name"}, label="source column")
        columns.append(
            SourceColumn(
                name=_string(column, "name"),
                type_name=_string(column, "type_name"),
                # Pass nullable explicitly to append for name and type name.
                nullable=_boolean(column, "nullable"),
            )
        )
    return SourceTable(
        name=_string(raw, "name"),
        # Include engine in the completed parse table result.
        engine=_string(raw, "engine", allow_empty=True),
        partition_key=_string(raw, "partition_key", allow_empty=True),
        sorting_key=_string(raw, "sorting_key", allow_empty=True),
        columns=tuple(columns),
    )


# Define canonical object as one focused operation with an explicit boundary.
def _canonical_object(encoded: bytes, *, label: str) -> dict[str, Any]:
    # Execute the canonical object workflow in explicit, reviewable steps.
    if not isinstance(encoded, bytes):
        raise TypeError(f"{label} must be bytes")
    try:
        # Perform the protected canonical object operation before explicit failure
        # handling.
        decoded = encoded.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"{label} is not valid canonical JSON") from None
    if not isinstance(value, dict):
        # Fail the canonical object path with ValueError for must be a json object and
        # label when isinstance and value is true; do not continue ambiguously.
        raise ValueError(f"{label} must be a JSON object")
    if canonical_json(value) != encoded:
        raise ValueError(f"{label} is not canonical JSON")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Execute the unique object workflow in explicit, reviewable steps.
    result: dict[str, Any] = {}
    for key, value in pairs:
        # Process pairs inside the bounded unique object loop.
        if key in result:
            raise ValueError("JSON object contains duplicate keys")
        result[key] = value
    return result


def _exact_keys(raw: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    # Execute the exact keys workflow in explicit, reviewable steps.
    if set(raw) != expected:
        raise ValueError(f"{label} schema is invalid")


def _string(raw: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    if not allow_empty and (not value or value != value.strip()):
        raise ValueError(f"{key} must be non-empty and trimmed")
    # Return the completed string result without a hidden fallback.
    return value


def _boolean(raw: Mapping[str, Any], key: str) -> bool:
    # Execute the boolean workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _integer(raw: Mapping[str, Any], key: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _string_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    # Execute the string tuple workflow in explicit, reviewable steps.
    values = raw[key]
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(values)


def _object_list(raw: Mapping[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    # Execute the object list workflow in explicit, reviewable steps.
    values = raw[key]
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise ValueError(f"{key} must be an array of objects")
    return tuple(cast(dict[str, Any], item) for item in values)


def _object(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    # Execute the object workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return cast(dict[str, Any], value)


def _digest(raw: Mapping[str, Any], key: str) -> ContentDigest:
    # Execute the digest workflow in explicit, reviewable steps.
    value = ContentDigest(_string(raw, key))
    if value.value != value.hex:
        raise ValueError(f"{key} must use canonical unprefixed digest form")
    return value


def _datetime(raw: Mapping[str, Any], key: str) -> datetime:
    # Execute the datetime workflow in explicit, reviewable steps.
    try:
        return datetime.fromisoformat(_string(raw, key))
    except ValueError:
        raise ValueError(f"{key} must be an ISO-8601 datetime") from None


__all__ = [
    # Keep the source inspection artifact schema component named inside the all contract.
    "SOURCE_INSPECTION_ARTIFACT_SCHEMA",
    "SOURCE_INSPECTION_DOCUMENT_VERSION",
    "canonical_json",
    "decode_source_inspection",
    "source_inspection_build_key",
    # Keep the source inspection manifest component named inside the all contract.
    "source_inspection_manifest",
    "source_inspection_payload",
]
