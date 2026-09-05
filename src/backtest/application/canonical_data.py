"""Typed canonical distribution and snapshot contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

# Import dataset plans at the visible module dependency boundary.
from backtest.application.dataset_plans import dataset_spec_from_document
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import (
    CapabilityCutEvidence,
    CommittedArtifact,
    # Include dataset plan so the models dependency remains explicit.
    DatasetPlan,
    DatasetShard,
    DatasetSpec,
    PlannedCapability,
)

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    # Include ordering fidelity so the fidelity dependency remains explicit.
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    CapabilityId,
    ContentDigest,
    # Include dataset revision id so the identifiers dependency remains explicit.
    DatasetRevisionId,
    LogicalContentHash,
    NetworkId,
    PositionSchemaId,
    SnapshotId,
    # Include source id so the identifiers dependency remains explicit.
    SourceId,
)
from backtest.domain.market_events import CanonicalEvent, EventKind
from backtest.domain.time import BlockRange


# Keep the validation status contract and validation rules together.
class ValidationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    QUARANTINED = "QUARANTINED"


def immutable_reuse_evidence(
    # Keep the plan input explicit in the immutable reuse evidence contract.
    plan: DatasetPlan,
    shard: DatasetShard,
) -> CapabilityCutEvidence | None:
    """Return the exact strong proof that makes one source shard immutable.

    Local validation and content equality are deliberately insufficient.  A
    revision is reusable only when both the planned effective fidelity and the
    capability-scoped cut evidence prove a finalized, snapshot-consistent,
    complete upstream revision covering the whole half-open shard.
    """

    capability = next(
        (item for item in plan.spec.capabilities if item.capability_id == shard.capability_id),
        None,
    )
    evidence = next(
        # Open the cut evidence and spec payload explicitly for next within immutable
        # reuse evidence.
        (item for item in plan.spec.cut_evidence if item.capability_id == shard.capability_id),
        None,
    )
    if capability is None or evidence is None:
        return None
    # Assemble fidelity once so the immutable reuse evidence workflow shares one value.
    fidelity = capability.fidelity
    if (
        fidelity.chain_finality is not ChainFinality.FINALIZED
        or fidelity.completeness is not IngestionCompleteness.COMPLETE_TO_WATERMARK
        or fidelity.consistency is not SourceConsistency.SNAPSHOT_CONSISTENT
        # Keep evidence visible while evaluating the chain finality, finalized and
        # completeness guard.
        or evidence.chain_finality is not ChainFinality.FINALIZED
        or evidence.completeness is not IngestionCompleteness.COMPLETE_TO_WATERMARK
        or evidence.consistency is not SourceConsistency.SNAPSHOT_CONSISTENT
        or evidence.upstream_revision is None
        or evidence.ingestion_watermark_to_block is None
        # Keep evidence visible while evaluating the chain finality, finalized and
        # completeness guard.
        or evidence.block_range.from_block_ordinal > shard.block_range.from_block_ordinal
        or evidence.snapshot_cut_to_block < shard.block_range.to_block_ordinal
        or evidence.ingestion_watermark_to_block < shard.block_range.to_block_ordinal
    ):
        return None
    # Return the completed immutable reuse evidence result without a hidden fallback.
    return evidence


def covering_cut_evidence(
    plan: DatasetPlan,
    shard: DatasetShard,
) -> CapabilityCutEvidence | None:
    """Return capability evidence only when it covers the complete shard."""

    evidence = next(
        (item for item in plan.spec.cut_evidence if item.capability_id == shard.capability_id),
        None,
    )
    if evidence is None or (
        # Keep evidence visible while evaluating the evidence, from block ordinal and
        # snapshot cut to block guard.
        evidence.block_range.from_block_ordinal > shard.block_range.from_block_ordinal
        or evidence.snapshot_cut_to_block < shard.block_range.to_block_ordinal
    ):
        return None
    return evidence


# Define canonical distribution source contract as one focused operation with an explicit
# boundary.
def canonical_distribution_source_contract(
    plan: DatasetPlan,
    shard: DatasetShard,
    capability: PlannedCapability,
) -> dict[str, object]:
    """Exact source/query semantics needed to validate cross-plan reuse."""

    if shard.capability_id != capability.capability_id:
        raise ValueError("shard and capability do not match")
    evidence = covering_cut_evidence(plan, shard)
    return {
        "capability": {
            # Include capability id in the completed canonical distribution source
            # contract result.
            "capability_id": capability.capability_id.value,
            "columns": list(capability.columns),
            "fidelity": source_fidelity_document(capability.fidelity),
            "keyset_key_is_proven": capability.keyset_key_is_proven,
            "protocol": capability.protocol,
            # Include protocol version in the completed canonical distribution source
            # contract result.
            "protocol_version": capability.protocol_version,
            "schema_version": capability.schema_version,
            "total_key": list(capability.total_key),
            "utc_pruning_column": capability.utc_pruning_column,
            "utc_pruning_is_proven": capability.utc_pruning_is_proven,
            # Return the completed canonical distribution source contract result without a
            # hidden fallback.
        },
        "capability_mapping_digest": plan.spec.capability_mapping_digest.hex,
        "cut_evidence": (
            None
            if evidence is None
            # Route all remaining cases through the explicit alternative branch.
            else {
                "capability_id": evidence.capability_id.value,
                "chain_finality": evidence.chain_finality.value,
                "completeness": evidence.completeness.value,
                "consistency": evidence.consistency.value,
                # Include block range in the completed canonical distribution source
                # contract result.
                "block_range": _block_range_document(evidence.block_range),
                "ingestion_watermark_to_block": evidence.ingestion_watermark_to_block,
                "snapshot_cut_to_block": evidence.snapshot_cut_to_block,
                "upstream_revision": evidence.upstream_revision,
            }
            # Return the completed canonical distribution source contract result without a
            # hidden fallback.
        ),
        "query_template_digest": plan.spec.query_template_digest.hex,
        "shard": {
            "capability_id": shard.capability_id.value,
            "columns": list(shard.columns),
            # Include block range in the completed canonical distribution source contract
            # result.
            "block_range": _block_range_document(shard.block_range),
        },
        "source_id": plan.spec.source_id.value,
        "source_inspection_artifact_id": plan.spec.source_inspection_artifact_id.hex,
        "source_schema_fingerprint": plan.spec.source_schema_fingerprint.hex,
        # Return the completed canonical distribution source contract result without a hidden
        # fallback.
    }


# Keep the source boundary contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceBoundary:
    source_id: SourceId
    capability_id: CapabilityId
    capability_schema_version: str
    # Declare block range explicitly in the source boundary contract.
    block_range: BlockRange
    snapshot_cut_to_block: int
    chain_finality: ChainFinality
    ingestion_watermark_to_block: int | None
    upstream_revision: str | None
    # Declare internal revision explicitly in the source boundary contract.
    internal_revision: ContentDigest
    source_consistency: SourceConsistency
    completeness: IngestionCompleteness
    validation_status: ValidationStatus
    query_fingerprints: tuple[ContentDigest, ...]

    # Define source boundary post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the source boundary post init workflow in explicit, reviewable steps.
        if not self.capability_schema_version:
            raise ValueError("capability schema version must be non-empty")
        if self.snapshot_cut_to_block != self.block_range.to_block_ordinal:
            raise ValueError("source boundary cut must equal its half-open shard end")
        if self.ingestion_watermark_to_block is not None and self.ingestion_watermark_to_block < 0:
            # Fail the source boundary post init path with ValueError for ingestion
            # watermark must be non-negative when ingestion watermark to block is true; do
            # not continue ambiguously.
            raise ValueError("ingestion watermark must be non-negative")
        if self.completeness is IngestionCompleteness.COMPLETE_TO_WATERMARK:
            # Handle the source boundary post init completeness, complete to watermark and
            # ingestion completeness condition as a distinct block.
            if self.ingestion_watermark_to_block is None:
                raise ValueError("complete-to-watermark requires a proven watermark")
            if self.block_range.to_block_ordinal > self.ingestion_watermark_to_block:
                raise ValueError("source boundary extends past its completeness watermark")
        fingerprints = tuple(sorted(self.query_fingerprints, key=lambda item: item.hex))
        # Evaluate the complete source boundary post init fingerprints and query
        # fingerprints condition before guarded effects.
        if fingerprints != self.query_fingerprints or len(set(fingerprints)) != len(fingerprints):
            raise ValueError("query fingerprints must be sorted and unique")

    def identity_document(self) -> dict[str, object]:
        # Execute the source boundary identity document workflow in explicit, reviewable
        # steps.
        return {
            "capability_id": self.capability_id.value,
            "capability_schema_version": self.capability_schema_version,
            "chain_finality": self.chain_finality.value,
            "completeness": self.completeness.value,
            # Include block range in the completed source boundary identity document
            # result.
            "block_range": _block_range_document(self.block_range),
            "ingestion_watermark_to_block": self.ingestion_watermark_to_block,
            "internal_revision": self.internal_revision.hex,
            "query_fingerprints": [item.hex for item in self.query_fingerprints],
            "snapshot_cut_to_block": self.snapshot_cut_to_block,
            # Include source consistency in the completed source boundary identity
            # document result.
            "source_consistency": self.source_consistency.value,
            "source_id": self.source_id.value,
            "upstream_revision": self.upstream_revision,
            "validation_status": self.validation_status.value,
        }


# Apply dataclass semantics to the following effective source boundary contract.
@dataclass(frozen=True, slots=True)
class EffectiveSourceBoundary:
    """One exact source cut together with its non-promoted effective fidelity."""

    source_boundary: SourceBoundary
    event_kind: EventKind
    source_fidelity: SourceFidelity

    def __post_init__(self) -> None:
        # Execute the effective source boundary post init workflow in explicit, reviewable
        # steps.
        boundary = self.source_boundary
        fidelity = self.source_fidelity
        if (
            fidelity.chain_finality is not boundary.chain_finality
            or fidelity.completeness is not boundary.completeness
            # Keep fidelity visible while evaluating the chain finality, completeness and
            # consistency guard.
            or fidelity.consistency is not boundary.source_consistency
        ):
            # Handle the effective source boundary post init chain finality, completeness
            # and consistency condition as a distinct block.
            raise ValueError(
                "source fidelity cut-dependent fields must equal the exact source boundary"
            )

    def identity_document(self) -> dict[str, object]:
        # Execute the effective source boundary identity document workflow in explicit,
        # reviewable steps.
        return {
            **self.source_boundary.identity_document(),
            "event_kind": self.event_kind.name,
            "source_fidelity": source_fidelity_document(self.source_fidelity),
        }

    # Apply classmethod semantics to the following effective source boundary from document
    # contract.
    @classmethod
    def from_document(cls, value: object) -> EffectiveSourceBoundary:
        # Execute the effective source boundary from document workflow in explicit,
        # reviewable steps.
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("effective source boundary must be an object")
        document = cast(dict[str, object], value)
        expected = {
            "block_range",
            # Keep the capability id component named inside the expected contract.
            "capability_id",
            "capability_schema_version",
            "chain_finality",
            "completeness",
            "event_kind",
            # Keep the ingestion watermark to block component named inside the expected
            # contract.
            "ingestion_watermark_to_block",
            "internal_revision",
            "query_fingerprints",
            "snapshot_cut_to_block",
            "source_consistency",
            # Keep the source fidelity component named inside the expected contract.
            "source_fidelity",
            "source_id",
            "upstream_revision",
            "validation_status",
        }
        # Guard this path with set(document) != expected before applying effects.
        if set(document) != expected:
            raise ValueError("effective source boundary schema is invalid")
        block_range = _block_range_from_document(document["block_range"])
        watermark_value = document["ingestion_watermark_to_block"]
        if watermark_value is not None and (
            # Keep isinstance visible while evaluating the watermark value and isinstance
            # guard.
            isinstance(watermark_value, bool) or not isinstance(watermark_value, int)
        ):
            raise ValueError("source boundary watermark must be an integer or null")
        upstream_revision = document["upstream_revision"]
        if upstream_revision is not None and (
            # Keep isinstance visible while evaluating the upstream revision, isinstance
            # and strip guard.
            not isinstance(upstream_revision, str)
            or not upstream_revision
            or upstream_revision != upstream_revision.strip()
        ):
            raise ValueError("source boundary upstream revision must be a token or null")
        # Assemble fingerprint values once so the effective source boundary from document
        # workflow shares one value.
        fingerprint_values = document["query_fingerprints"]
        if not isinstance(fingerprint_values, list) or not all(
            isinstance(item, str) for item in fingerprint_values
        ):
            raise ValueError("source boundary query fingerprints must be a string list")
        # Keep expected failures inside the effective source boundary from document error
        # boundary.
        try:
            # Perform the protected effective source boundary from document operation
            # before explicit failure handling.
            boundary = SourceBoundary(
                source_id=SourceId(_text(document["source_id"], "source_id")),
                capability_id=CapabilityId(_text(document["capability_id"], "capability_id")),
                capability_schema_version=_text(
                    document["capability_schema_version"],
                    # Pass capability schema version explicitly so _text receives a
                    # reviewable capability schema version and document input in effective
                    # source boundary from document.
                    "capability_schema_version",
                ),
                block_range=block_range,
                snapshot_cut_to_block=_integer(
                    document["snapshot_cut_to_block"],
                    # Pass snapshot cut to block explicitly so _integer receives a
                    # reviewable snapshot cut to block and document input in effective
                    # source boundary from document.
                    "snapshot_cut_to_block",
                ),
                chain_finality=ChainFinality(_text(document["chain_finality"], "chain_finality")),
                ingestion_watermark_to_block=watermark_value,
                upstream_revision=upstream_revision,
                # Keep the content digest and text ContentDigest step visible while
                # building boundary.
                internal_revision=ContentDigest(
                    _text(document["internal_revision"], "internal_revision")
                ),
                source_consistency=SourceConsistency(
                    _text(document["source_consistency"], "source_consistency")
                    # Complete SourceConsistency only after its source consistency and text
                    # inputs are visible in effective source boundary from document.
                ),
                completeness=IngestionCompleteness(_text(document["completeness"], "completeness")),
                validation_status=ValidationStatus(
                    _text(document["validation_status"], "validation_status")
                ),
                # Keep the content digest and item tuple step visible while building
                # boundary.
                query_fingerprints=tuple(
                    ContentDigest(cast(str, item)) for item in fingerprint_values
                ),
            )
            return cls(
                # Pass source boundary explicitly so cls receives a reviewable event kind
                # and source fidelity input in effective source boundary from document.
                source_boundary=boundary,
                event_kind=EventKind[_text(document["event_kind"], "event_kind")],
                source_fidelity=source_fidelity_from_document(document["source_fidelity"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            # Fail the effective source boundary from document path with ValueError for
            # effective source boundary contains an invalid field; do not continue
            # ambiguously.
            raise ValueError("effective source boundary contains an invalid field") from error


def source_fidelity_document(value: SourceFidelity) -> dict[str, str]:
    # Execute the source fidelity document workflow in explicit, reviewable steps.
    return {
        "chain_finality": value.chain_finality.value,
        "completeness": value.completeness.value,
        "consistency": value.consistency.value,
        "fees": value.fees.value,
        # Include identity in the completed source fidelity document result.
        "identity": value.identity.value,
        "ordering": value.ordering.value,
        "state": value.state.value,
    }


def source_fidelity_from_document(value: object) -> SourceFidelity:
    # Execute the source fidelity from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("source fidelity must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {
        "chain_finality",
        # Keep completeness visible while evaluating the document, chain finality and
        # completeness guard.
        "completeness",
        "consistency",
        "fees",
        "identity",
        "ordering",
        # Keep state visible while evaluating the document, chain finality and
        # completeness guard.
        "state",
    }:
        raise ValueError("source fidelity schema is invalid")
    try:
        # Perform the protected source fidelity from document operation before explicit
        # failure handling.
        return SourceFidelity(
            identity=IdentityFidelity(_text(document["identity"], "identity")),
            ordering=OrderingFidelity(_text(document["ordering"], "ordering")),
            state=StateFidelity(_text(document["state"], "state")),
            fees=FeesFidelity(_text(document["fees"], "fees")),
            # Include chain finality in the completed source fidelity from document
            # result.
            chain_finality=ChainFinality(_text(document["chain_finality"], "chain_finality")),
            completeness=IngestionCompleteness(_text(document["completeness"], "completeness")),
            consistency=SourceConsistency(_text(document["consistency"], "consistency")),
        )
    except ValueError as error:
        # Fail the source fidelity from document path with ValueError for source fidelity
        # contains an unsupported value; do not continue ambiguously.
        raise ValueError("source fidelity contains an unsupported value") from error


def effective_source_boundaries_from_snapshot_document(
    value: object,
) -> tuple[EffectiveSourceBoundary, ...]:
    """Read snapshot v4 with canonical schema v3 and reject every legacy shape."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("snapshot manifest must be an object")
    document = cast(dict[str, object], value)
    artifact_schema = document.get("artifact_schema")
    if artifact_schema in {
        # Keep canonical-snapshot v1 visible while evaluating the artifact schema guard.
        "canonical-snapshot/v1",
        "canonical-snapshot/v2",
        "canonical-snapshot/v3",
    }:
        raise ReprepareRequiredError(artifact_schema)
    # Evaluate the complete effective source boundaries from snapshot document artifact
    # schema, get and canonical schema version condition before guarded effects.
    if artifact_schema != "canonical-snapshot/v4" or document.get("canonical_schema_version") != 3:
        raise ValueError("unsupported canonical snapshot fidelity contract")
    network_id = NetworkId(_text(document.get("network_id"), "network_id"))
    position_schema_id = PositionSchemaId(
        _text(document.get("position_schema_id"), "position_schema_id")
        # Complete PositionSchemaId only after its position schema id and get inputs are
        # visible in effective source boundaries from snapshot document.
    )
    raw_boundaries = document.get("source_boundaries")
    if not isinstance(raw_boundaries, list) or not raw_boundaries:
        raise ValueError("snapshot must contain effective source boundaries")
    boundaries = tuple(EffectiveSourceBoundary.from_document(item) for item in raw_boundaries)
    # Assemble identities once so the effective source boundaries from snapshot document
    # workflow shares one value.
    identities = tuple(
        (
            item.source_boundary.source_id,
            item.source_boundary.capability_id,
            item.source_boundary.capability_schema_version,
            # Pass item explicitly so tuple receives a reviewable source id and capability
            # id input in effective source boundaries from snapshot document.
            item.source_boundary.block_range,
        )
        for item in boundaries
    )
    if len(identities) != len(set(identities)):
        # Fail the effective source boundaries from snapshot document path with ValueError
        # for snapshot contains duplicate source boundary identities when identities is
        # true; do not continue ambiguously.
        raise ValueError("snapshot contains duplicate source boundary identities")
    if any(
        item.source_boundary.block_range.network_id != network_id
        or item.source_boundary.block_range.position_schema_id != position_schema_id
        for item in boundaries
        # Complete any only after its network id and position schema id inputs are visible in
        # effective source boundaries from snapshot document.
    ):
        raise ValueError("snapshot source boundaries use another chain identity")
    return boundaries


def decision_range_from_snapshot_document(value: object) -> BlockRange:
    """Read and cross-check the exact v4 decision range."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("snapshot manifest must be an object")
    document = cast(dict[str, object], value)
    artifact_schema = document.get("artifact_schema")
    if artifact_schema in {
        # Keep canonical-snapshot v1 visible while evaluating the artifact schema guard.
        "canonical-snapshot/v1",
        "canonical-snapshot/v2",
        "canonical-snapshot/v3",
    }:
        raise ReprepareRequiredError(artifact_schema)
    # Evaluate the complete decision range from snapshot document artifact schema, get and
    # canonical schema version condition before guarded effects.
    if artifact_schema != "canonical-snapshot/v4" or document.get("canonical_schema_version") != 3:
        raise ValueError("unsupported canonical snapshot decision-range contract")
    network_id = NetworkId(_text(document.get("network_id"), "network_id"))
    position_schema_id = PositionSchemaId(
        _text(document.get("position_schema_id"), "position_schema_id")
        # Complete PositionSchemaId only after its position schema id and get inputs are
        # visible in decision range from snapshot document.
    )
    result = _block_range_from_document(document.get("requested_decision_range"))
    if result.network_id != network_id or result.position_schema_id != position_schema_id:
        raise ValueError("snapshot decision range uses another chain identity")
    return result


# Define dataset spec from snapshot document as one focused operation with an explicit
# boundary.
def dataset_spec_from_snapshot_document(value: object) -> DatasetSpec:
    """Read and identity-check the exact DatasetSpec embedded by snapshot v4."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("snapshot manifest must be an object")
    document = cast(dict[str, object], value)
    artifact_schema = document.get("artifact_schema")
    if artifact_schema in {
        # Keep canonical-snapshot v1 visible while evaluating the artifact schema guard.
        "canonical-snapshot/v1",
        "canonical-snapshot/v2",
        "canonical-snapshot/v3",
    }:
        raise ReprepareRequiredError(artifact_schema)
    # Evaluate the complete dataset spec from snapshot document artifact schema, get and
    # canonical schema version condition before guarded effects.
    if artifact_schema != "canonical-snapshot/v4" or document.get("canonical_schema_version") != 3:
        raise ValueError("unsupported canonical snapshot dataset-spec contract")
    spec = dataset_spec_from_document(document.get("dataset_spec"))
    network_id = NetworkId(_text(document.get("network_id"), "network_id"))
    position_schema_id = PositionSchemaId(
        # Keep the text and position schema id _text step visible while building position
        # schema id.
        _text(document.get("position_schema_id"), "position_schema_id")
    )
    if spec.network_id != network_id or spec.position_schema_id != position_schema_id:
        raise ValueError("snapshot DatasetSpec uses another chain identity")
    if spec.decision_range != decision_range_from_snapshot_document(document):
        # Fail the dataset spec from snapshot document path with ValueError for snapshot
        # dataset spec decision range differs from its manifest when decision range, spec
        # and decision range from snapshot document is true; do not continue ambiguously.
        raise ValueError("snapshot DatasetSpec decision range differs from its manifest")
    if document.get("spec_id") != spec.spec_id.hex:
        raise ValueError("snapshot DatasetSpec ID differs from its manifest")
    return spec


def _block_range_document(value: BlockRange) -> dict[str, object]:
    # Execute the block range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed block range document result without a hidden fallback.
    }


def _block_range_from_document(value: object) -> BlockRange:
    # Execute the block range from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("block_range must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {
        "from_block_ordinal",
        # Keep network id visible while evaluating the document, from block ordinal and
        # network id guard.
        "network_id",
        "position_schema_id",
        "to_block_ordinal",
    }:
        raise ValueError("block_range schema is invalid")
    # Return the completed block range from document result without a hidden fallback.
    return BlockRange(
        network_id=NetworkId(_text(document["network_id"], "network_id")),
        position_schema_id=PositionSchemaId(
            _text(document["position_schema_id"], "position_schema_id")
        ),
        # Include from block ordinal in the completed block range from document result.
        from_block_ordinal=_integer(document["from_block_ordinal"], "from_block_ordinal"),
        to_block_ordinal=_integer(document["to_block_ordinal"], "to_block_ordinal"),
    )


def _text(value: object, field: str) -> str:
    # Execute the text workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


def _integer(value: object, field: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


# Keep the projected event batch contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProjectedEventBatch:
    events: tuple[CanonicalEvent, ...]
    query_fingerprint: ContentDigest | None


# Keep the canonical distribution ref contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CanonicalDistributionRef:
    artifact: CommittedArtifact
    logical_content_hash: LogicalContentHash
    capability_id: CapabilityId
    # Declare event kind explicitly in the canonical distribution ref contract.
    event_kind: EventKind
    shard: DatasetShard
    row_count: int
    minimum_boundary_ordinal: int | None
    maximum_boundary_ordinal: int | None
    # Declare source boundary explicitly in the canonical distribution ref contract.
    source_boundary: SourceBoundary
    source_fidelity: SourceFidelity

    def __post_init__(self) -> None:
        # Execute the canonical distribution ref post init workflow in explicit,
        # reviewable steps.
        EffectiveSourceBoundary(
            source_boundary=self.source_boundary,
            event_kind=self.event_kind,
            source_fidelity=self.source_fidelity,
        )

    # Apply property semantics to the following canonical distribution ref effective
    # source boundary contract.
    @property
    def effective_source_boundary(self) -> EffectiveSourceBoundary:
        # Execute the canonical distribution ref effective source boundary workflow in
        # explicit, reviewable steps.
        return EffectiveSourceBoundary(
            source_boundary=self.source_boundary,
            event_kind=self.event_kind,
            source_fidelity=self.source_fidelity,
        )

    # Apply property semantics to the following canonical distribution ref canonical
    # distribution id contract.
    @property
    def canonical_distribution_id(self) -> ArtifactId:
        return self.artifact.artifact_id


# Keep the prepared snapshot contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PreparedSnapshot:
    artifact: CommittedArtifact
    snapshot_id: SnapshotId
    dataset_revision_id: DatasetRevisionId
    # Declare logical content hash explicitly in the prepared snapshot contract.
    logical_content_hash: LogicalContentHash
    spec: DatasetSpec
    projector_bundle_id: BundleId
    distributions: tuple[CanonicalDistributionRef, ...]
    extracted_at: datetime

    # Define prepared snapshot post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the prepared snapshot post init workflow in explicit, reviewable steps.
        if self.snapshot_id.hex != self.artifact.artifact_id.hex:
            raise ValueError("snapshot ID must equal its committed artifact ID")
        if self.extracted_at.tzinfo is None or self.extracted_at.utcoffset() is None:
            raise ValueError("snapshot extracted_at must be timezone-aware")


__all__ = [
    # Keep the canonical distribution ref component named inside the all contract.
    "CanonicalDistributionRef",
    "EffectiveSourceBoundary",
    "PreparedSnapshot",
    "ProjectedEventBatch",
    "SourceBoundary",
    # Keep the validation status component named inside the all contract.
    "ValidationStatus",
    "canonical_distribution_source_contract",
    "covering_cut_evidence",
    "dataset_spec_from_snapshot_document",
    "decision_range_from_snapshot_document",
    # Keep the effective source boundaries from snapshot document component named inside
    # the all contract.
    "effective_source_boundaries_from_snapshot_document",
    "immutable_reuse_evidence",
    "source_fidelity_document",
    "source_fidelity_from_document",
]
