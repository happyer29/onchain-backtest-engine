"""Hermetic network-aware publication fixtures shared by replay adapter tests."""

from __future__ import annotations

from backtest.application.dataset_plans import dataset_spec_document
from backtest.application.models import (
    DATASET_SPEC_VERSION,
    CapabilityExtractionRange,
    # Include capability proofs so the models dependency remains explicit.
    CapabilityProofs,
    CapabilityStream,
    DatasetShard,
    DatasetSpec,
    PlannedCapability,
    # Include dataset spec identity digest so the models dependency remains explicit.
    dataset_spec_identity_digest,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
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
from backtest.domain.identifiers import ArtifactId, CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange

FIXTURE_CAPABILITY_ID = CapabilityId("fixture.events.v1")
FIXTURE_SOURCE_ID = SourceId("fixture-source")
# Bind fixture extraction range once as an explicit module-level contract.
FIXTURE_EXTRACTION_RANGE = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    0,
    106,
    # Complete BlockRange only after its solana mainnet network id and block32 transaction32
    # position schema id inputs are visible in module.
)
FIXTURE_DECISION_RANGE = BlockRange(
    SOLANA_MAINNET_NETWORK_ID,
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    100,
    # Keep block range, solana mainnet network id and block32 transaction32 position
    # schema id visible while completing BlockRange within module.
    106,
)


def fixture_source_fidelity() -> SourceFidelity:
    # Execute the fixture source fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=OrderingFidelity.INSTRUCTION_EXACT,
        state=StateFidelity.BEFORE_AFTER,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable exact and
        # instruction exact input in fixture source fidelity.
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )


def fixture_dataset_spec(
    # Close the fixture dataset spec signature after its explicit inputs.
    *,
    capability_id: CapabilityId = FIXTURE_CAPABILITY_ID,
    stream: CapabilityStream = CapabilityStream.PUMP_CURVE_TRADE,
    columns: tuple[str, ...] = ("block_ordinal", "event_index", "transaction_index"),
    extraction_range: BlockRange = FIXTURE_EXTRACTION_RANGE,
    # Keep the decision range input explicit in the fixture dataset spec contract.
    decision_range: BlockRange = FIXTURE_DECISION_RANGE,
    warmup_blocks: int = 100,
) -> DatasetSpec:
    # Execute the fixture dataset spec workflow in explicit, reviewable steps.
    capability = PlannedCapability(
        capability_id=capability_id,
        protocol="fixture",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so PlannedCapability receives a reviewable fixture and 1
        # input in fixture dataset spec.
        stream=stream,
        columns=columns,
        fidelity=fixture_source_fidelity(),
        proofs=CapabilityProofs(),
        total_key=(),
        # Pass keyset key is proven explicitly so PlannedCapability receives a reviewable
        # fixture and 1 input in fixture dataset spec.
        keyset_key_is_proven=False,
        utc_pruning_column=None,
        utc_pruning_is_proven=False,
    )
    capability_range = CapabilityExtractionRange(
        # Pass capability id explicitly so CapabilityExtractionRange receives a reviewable
        # capability id and extraction range input in fixture dataset spec.
        capability_id,
        extraction_range,
    )
    shard = DatasetShard(
        0,
        # Pass capability id explicitly so DatasetShard receives a reviewable columns and
        # capability id input in fixture dataset spec.
        capability_id,
        extraction_range,
        capability.columns,
    )
    inspection_artifact_id = ArtifactId("f" * 64)
    # Assemble source schema fingerprint once so the fixture dataset spec workflow shares
    # one value.
    source_schema_fingerprint = ContentDigest("e" * 64)
    capability_mapping_digest = ContentDigest("c" * 64)
    query_template_digest = ContentDigest("b" * 64)
    evidence_contracts = ("fixture-publication-v1",)
    spec_id = dataset_spec_identity_digest(
        # Pass spec version explicitly so dataset_spec_identity_digest receives a
        # reviewable dataset spec version and fixture source id input in fixture dataset
        # spec.
        spec_version=DATASET_SPEC_VERSION,
        source_id=FIXTURE_SOURCE_ID,
        source_inspection_artifact_id=inspection_artifact_id,
        source_schema_fingerprint=source_schema_fingerprint,
        capability_mapping_digest=capability_mapping_digest,
        # Pass query template digest explicitly so dataset_spec_identity_digest receives a
        # reviewable dataset spec version and fixture source id input in fixture dataset
        # spec.
        query_template_digest=query_template_digest,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        decision_range=decision_range,
        settlement_tail=None,
        # Pass warmup blocks explicitly so dataset_spec_identity_digest receives a
        # reviewable dataset spec version and fixture source id input in fixture dataset
        # spec.
        warmup_blocks=warmup_blocks,
        evidence_contracts=evidence_contracts,
        capabilities=(capability,),
        capability_ranges=(capability_range,),
        cut_evidence=(),
        # Pass shards explicitly so dataset_spec_identity_digest receives a reviewable
        # dataset spec version and fixture source id input in fixture dataset spec.
        shards=(shard,),
    )
    return DatasetSpec(
        spec_version=DATASET_SPEC_VERSION,
        spec_id=spec_id,
        # Pass source id explicitly so DatasetSpec receives a reviewable dataset spec
        # version and spec id input in fixture dataset spec.
        source_id=FIXTURE_SOURCE_ID,
        source_inspection_artifact_id=inspection_artifact_id,
        source_schema_fingerprint=source_schema_fingerprint,
        capability_mapping_digest=capability_mapping_digest,
        query_template_digest=query_template_digest,
        # Pass network id explicitly so DatasetSpec receives a reviewable dataset spec
        # version and spec id input in fixture dataset spec.
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        decision_range=decision_range,
        settlement_tail=None,
        warmup_blocks=warmup_blocks,
        # Pass evidence contracts explicitly so DatasetSpec receives a reviewable dataset
        # spec version and spec id input in fixture dataset spec.
        evidence_contracts=evidence_contracts,
        capabilities=(capability,),
        capability_ranges=(capability_range,),
        cut_evidence=(),
        shards=(shard,),
        # Complete DatasetSpec only after its dataset spec version and spec id inputs are
        # visible in fixture dataset spec.
    )


def fixture_source_boundary_document(
    fidelity: dict[str, str] | None = None,
    *,
    capability_id: CapabilityId = FIXTURE_CAPABILITY_ID,
    # Keep the block range input explicit in the fixture source boundary document
    # contract.
    block_range: BlockRange = FIXTURE_EXTRACTION_RANGE,
    event_kind: str = "VENUE_TRADE",
) -> dict[str, object]:
    # Execute the fixture source boundary document workflow in explicit, reviewable steps.
    values = fidelity or {
        "chain_finality": "UNKNOWN",
        "completeness": "UNKNOWN",
        "consistency": "UNKNOWN",
        "fees": "COMPONENTS",
        # Keep the identity component named inside the values contract.
        "identity": "EXACT",
        "ordering": "INSTRUCTION_EXACT",
        "state": "BEFORE_AFTER",
    }
    return {
        # Include block range in the completed fixture source boundary document result.
        "block_range": _range_document(block_range),
        "capability_id": capability_id.value,
        "capability_schema_version": "1",
        "chain_finality": values["chain_finality"],
        "completeness": values["completeness"],
        # Include event kind in the completed fixture source boundary document result.
        "event_kind": event_kind,
        "ingestion_watermark_to_block": None,
        "internal_revision": "1" * 64,
        "query_fingerprints": ["2" * 64],
        "snapshot_cut_to_block": block_range.to_block_ordinal,
        # Include source consistency in the completed fixture source boundary document
        # result.
        "source_consistency": values["consistency"],
        "source_fidelity": values,
        "source_id": FIXTURE_SOURCE_ID.value,
        "upstream_revision": None,
        "validation_status": "PASS",
        # Return the completed fixture source boundary document result without a hidden
        # fallback.
    }


def fixture_snapshot_manifest(
    *,
    spec: DatasetSpec | None = None,
    event_kind: str = "VENUE_TRADE",
    # Keep the dict input explicit in the fixture snapshot manifest contract.
) -> dict[str, object]:
    # Execute the fixture snapshot manifest workflow in explicit, reviewable steps.
    spec = fixture_dataset_spec() if spec is None else spec
    if len(spec.capabilities) != 1 or len(spec.capability_ranges) != 1:
        raise ValueError("fixture snapshot helper requires exactly one capability")
    capability = spec.capabilities[0]
    capability_range = spec.capability_ranges[0]
    # Return the completed fixture snapshot manifest result without a hidden fallback.
    return {
        "artifact_schema": "canonical-snapshot/v4",
        "canonical_schema_version": 3,
        "dataset_spec": dataset_spec_document(spec),
        "network_id": spec.network_id.value,
        # Include position schema id in the completed fixture snapshot manifest result.
        "position_schema_id": spec.position_schema_id.value,
        "requested_decision_range": _range_document(spec.decision_range),
        "source_boundaries": [
            fixture_source_boundary_document(
                capability_id=capability.capability_id,
                # Pass block range explicitly so fixture_source_boundary_document receives
                # a reviewable capability id and block range input in fixture snapshot
                # manifest.
                block_range=capability_range.block_range,
                event_kind=event_kind,
            )
        ],
        "spec_id": spec.spec_id.hex,
        # Return the completed fixture snapshot manifest result without a hidden fallback.
    }


def _range_document(value: BlockRange) -> dict[str, object]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


__all__ = [
    "FIXTURE_CAPABILITY_ID",
    "FIXTURE_DECISION_RANGE",
    "FIXTURE_EXTRACTION_RANGE",
    # Keep the fixture source id component named inside the all contract.
    "FIXTURE_SOURCE_ID",
    "fixture_dataset_spec",
    "fixture_snapshot_manifest",
    "fixture_source_boundary_document",
    "fixture_source_fidelity",
    # Complete the all group only after its semantic components are visible.
]
