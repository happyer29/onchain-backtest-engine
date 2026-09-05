# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest

# Import dataset plans at the visible module dependency boundary.
from backtest.application.dataset_plans import (
    DatasetPlanCodecError,
    dataset_plan_bytes,
    dataset_plan_from_bytes,
    dataset_spec_document,
    # Include dataset spec from document so the dataset plans dependency remains explicit.
    dataset_spec_from_document,
)
from backtest.application.errors import ReprepareRequiredError, SourceEvidenceMismatchError
from backtest.application.models import (
    DATASET_SPEC_VERSION,
    # Include pumpfun sniping source contract so the models dependency remains explicit.
    PUMPFUN_SNIPING_SOURCE_CONTRACT,
    BudgetLimits,
    BudgetReport,
    BudgetStatus,
    CapabilityCutEvidence,
    # Include capability descriptor so the models dependency remains explicit.
    CapabilityDescriptor,
    CapabilityExtractionRange,
    CapabilityProofs,
    CapabilityStream,
    DataRequirement,
    # Include dataset plan so the models dependency remains explicit.
    DatasetPlan,
    DatasetPlanningPolicy,
    DatasetShard,
    DatasetSpec,
    DiskCapacity,
    # Include evidence status so the models dependency remains explicit.
    EvidenceStatus,
    PlanDatasetRequest,
    PlannedCapability,
    QueryLimits,
    RequirementOrigin,
    # Include source inspection so the models dependency remains explicit.
    SourceInspection,
    SourceMetadata,
    build_bounded_source_evidence_receipt,
    dataset_spec_identity_digest,
)
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID

# Import source contracts at the visible module dependency boundary.
from backtest.application.source_contracts import (
    pumpfun_sniping_settlement_requirement,
    require_pumpfun_sniping_inspection_receipts,
    require_pumpfun_sniping_source_contract,
)
from backtest.application.source_evidence import (
    MAYHEM_EXCLUSION_REASON,
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
    LaunchUniverseEvidence,
    PumpfunSnipingSourceEvidenceBinding,
    SkippedSlotSentinelEvidence,
    SourceEvidenceReceiptRef,
    TerminalLifecycleOrderingEvidence,
)
from backtest.application.source_fingerprint import source_schema_fingerprint

# Import source inspection document at the visible module dependency boundary.
from backtest.application.source_inspection_document import (
    canonical_json,
    decode_source_inspection,
    source_inspection_manifest,
    source_inspection_payload,
    # Close the source inspection document import after its required symbols are visible.
)
from backtest.application.use_cases.plan_dataset import PlanDataset
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
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    NetworkId,
    SourceId,
)
from backtest.domain.time import BlockRange

# Bind source id once as an explicit module-level contract.
SOURCE_ID = SourceId("readonly-indexer")
INSPECTION_ID = ArtifactId("a" * 64)
PROJECTOR_DIGEST = ContentDigest("e" * 64)
NORMALIZER_DIGEST = ContentDigest("f" * 64)

_COLUMNS = {
    CapabilityStream.BLOCK_CLOCK: (
        "block_hash",
        # Keep the block ordinal component named inside the columns contract.
        "block_ordinal",
        "block_time",
        "transaction_count",
    ),
    CapabilityStream.TOKEN_LAUNCH: (
        # Keep the block ordinal component named inside the columns contract.
        "block_ordinal",
        "creation_user",
        "creator",
        "event_index",
        "mint",
        # Keep the lifecycle component named inside the columns contract.
        "lifecycle",
        "mode",
        "quote_asset",
        "real_sol_reserves_lamports",
        "real_token_reserves_atomic",
        # Keep the signature component named inside the columns contract.
        "signature",
        "transaction_succeeded",
        "token_total_supply_atomic",
        "transaction_index",
        "venue",
        # Keep the virtual sol reserves lamports component named inside the columns
        # contract.
        "virtual_sol_reserves_lamports",
        "virtual_token_reserves_atomic",
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "base_amount_atomic",
        # Keep the block ordinal component named inside the columns contract.
        "block_ordinal",
        "creator_fee_atomic",
        "event_index",
        "lifecycle",
        "mint",
        # Keep the mode component named inside the columns contract.
        "mode",
        "protocol_fee_atomic",
        "quote_amount_atomic",
        "quote_asset",
        "real_sol_reserves_lamports",
        # Keep the real token reserves atomic component named inside the columns contract.
        "real_token_reserves_atomic",
        "side",
        "signature",
        "transaction_index",
        "venue",
        # Keep the token total supply atomic component named inside the columns contract.
        "token_total_supply_atomic",
        "virtual_sol_reserves_lamports",
        "virtual_token_reserves_atomic",
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        # Keep the block ordinal component named inside the columns contract.
        "block_ordinal",
        "event_index",
        "lifecycle_kind",
        "lifecycle",
        "mint",
        # Keep the mode component named inside the columns contract.
        "mode",
        "real_sol_reserves_lamports",
        "real_token_reserves_atomic",
        "signature",
        "token_total_supply_atomic",
        # Keep the transaction index component named inside the columns contract.
        "transaction_index",
        "venue",
        "virtual_sol_reserves_lamports",
        "virtual_token_reserves_atomic",
    ),
    # Complete the columns group only after its semantic components are visible.
}


def _capability_id(stream: CapabilityStream) -> CapabilityId:
    return CapabilityId(f"pumpfun.{stream.value.lower()}.v2")


def _proofs(status: EvidenceStatus = EvidenceStatus.PROVEN) -> CapabilityProofs:
    # Execute the proofs workflow in explicit, reviewable steps.
    return CapabilityProofs(
        successful_transactions_included=status,
        failed_transactions_included=status,
        vote_transactions_included=status,
        global_zero_based_transaction_index=status,
        # Pass skipped blocks distinguished explicitly so CapabilityProofs receives a
        # reviewable status input in proofs.
        skipped_blocks_distinguished=status,
        creation_fields_immutable=status,
        bundled_instruction_order=status,
        curve_transitions_complete=status,
        fee_component_rounding_exact=status,
        # Pass lifecycle complete explicitly so CapabilityProofs receives a reviewable
        # status input in proofs.
        lifecycle_complete=status,
        launch_transaction_success_exact=status,
        block_time_second_resolution=status,
        block_time_monotone=status,
    )


# Define fidelity as one focused operation with an explicit boundary.
def _fidelity() -> SourceFidelity:
    # Execute the fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=OrderingFidelity.INSTRUCTION_EXACT,
        state=StateFidelity.BEFORE_AFTER,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable exact and
        # instruction exact input in fidelity.
        chain_finality=ChainFinality.FINALIZED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
    )


def _planned(
    # Keep the stream input explicit in the planned contract.
    stream: CapabilityStream,
    *,
    proofs: CapabilityProofs | None = None,
) -> PlannedCapability:
    # Execute the planned workflow in explicit, reviewable steps.
    return PlannedCapability(
        capability_id=_capability_id(stream),
        protocol="solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun",
        protocol_version="v1",
        schema_version="2",
        # Pass stream explicitly so PlannedCapability receives a reviewable solana and
        # pumpfun input in planned.
        stream=stream,
        columns=_COLUMNS[stream],
        fidelity=_fidelity(),
        proofs=proofs or _proofs(),
        total_key=(),
        # Pass keyset key is proven explicitly so PlannedCapability receives a reviewable
        # solana and pumpfun input in planned.
        keyset_key_is_proven=False,
        utc_pruning_column=None,
        utc_pruning_is_proven=False,
    )


def _descriptor(
    # Keep the stream input explicit in the descriptor contract.
    stream: CapabilityStream,
    *,
    proofs: CapabilityProofs | None = None,
) -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    planned = _planned(stream, proofs=proofs)
    return CapabilityDescriptor(
        capability_id=planned.capability_id,
        protocol=planned.protocol,
        protocol_version=planned.protocol_version,
        # Pass schema version explicitly so CapabilityDescriptor receives a reviewable
        # capability id and protocol input in descriptor.
        schema_version=planned.schema_version,
        stream=planned.stream,
        columns=planned.columns,
        mandatory_columns=planned.columns,
        fidelity=planned.fidelity,
        # Pass proofs explicitly so CapabilityDescriptor receives a reviewable capability
        # id and protocol input in descriptor.
        proofs=planned.proofs,
    )


def _evidence(stream: CapabilityStream, *, to_block: int = 220) -> CapabilityCutEvidence:
    # Execute the evidence workflow in explicit, reviewable steps.
    return CapabilityCutEvidence(
        capability_id=_capability_id(stream),
        block_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Keep block range, solana mainnet network id and block32 transaction32
            # position schema id visible while completing BlockRange within evidence.
            0,
            to_block,
        ),
        snapshot_cut_to_block=to_block,
        chain_finality=ChainFinality.FINALIZED,
        # Pass ingestion watermark to block explicitly so CapabilityCutEvidence receives a
        # reviewable cut-1 and finalized input in evidence.
        ingestion_watermark_to_block=to_block,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
        upstream_revision="cut-1",
    )


def _decision_range() -> BlockRange:
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        100,
        200,
    )


def _launch_universe(
    decision_range: BlockRange,
    *,
    digest: ContentDigest | None = None,
) -> LaunchUniverseEvidence:
    return LaunchUniverseEvidence(
        decision_range=decision_range,
        policy_id=PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
        classified_count=3,
        eligible_count=2,
        excluded_count=1,
        ordered_exclusion_digest=digest or ContentDigest("3" * 64),
        exclusion_reason=MAYHEM_EXCLUSION_REASON,
    )


def _sentinel_evidence() -> SkippedSlotSentinelEvidence:
    return SkippedSlotSentinelEvidence(
        profile_id=SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
        recognized_count=1,
        ordered_sentinel_digest=ContentDigest("4" * 64),
    )


def _lifecycle_evidence() -> TerminalLifecycleOrderingEvidence:
    return TerminalLifecycleOrderingEvidence(
        profile_id=PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
        derived_group_count=1,
        ordered_group_digest=ContentDigest("5" * 64),
    )


def _binding(
    streams: tuple[CapabilityStream, ...],
    decision_range: BlockRange,
    *,
    normalizer_digest: ContentDigest = NORMALIZER_DIGEST,
) -> PumpfunSnipingSourceEvidenceBinding:
    refs = tuple(
        sorted(
            (
                SourceEvidenceReceiptRef(
                    _capability_id(stream),
                    ContentDigest(f"{index + 301:064x}"),
                )
                for index, stream in enumerate(streams)
            ),
            key=lambda item: item.capability_id.value,
        )
    )
    return PumpfunSnipingSourceEvidenceBinding(
        receipt_refs=refs,
        capability_mapping_digest=ContentDigest("c" * 64),
        query_template_digest=ContentDigest("d" * 64),
        projector_digest=PROJECTOR_DIGEST,
        normalizer_digest=normalizer_digest,
        launch_universe=_launch_universe(decision_range),
        skipped_slot_sentinel=_sentinel_evidence(),
        terminal_lifecycle_ordering=_lifecycle_evidence(),
    )


# Define spec as one focused operation with an explicit boundary.
def _spec(
    *,
    unknown_stream: CapabilityStream | None = None,
    include_tail: bool = True,
    include_contract: bool = True,
    # Keep the include settlement requirement input explicit in the spec contract.
    include_settlement_requirement: bool = True,
    streams: tuple[CapabilityStream, ...] = tuple(CapabilityStream),
    maximum_sell_delay_transactions: int = 25,
    normalizer_digest: ContentDigest = NORMALIZER_DIGEST,
) -> DatasetSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    decision_range = _decision_range()
    tail = (
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Keep block range, solana mainnet network id and block32 transaction32
            # position schema id visible while completing BlockRange within spec.
            200,
            220,
        )
        if include_tail
        else None
        # Complete the tail group only after its semantic components are visible.
    )
    capabilities = tuple(
        _planned(
            stream,
            proofs=_proofs(EvidenceStatus.UNKNOWN) if stream is unknown_stream else None,
            # Complete _planned only after its unknown and proofs inputs are visible in spec.
        )
        for stream in streams
    )
    capability_ranges = tuple(
        CapabilityExtractionRange(
            # Keep the stream _capability_id step visible while building capability
            # ranges.
            _capability_id(stream),
            BlockRange(
                SOLANA_MAINNET_NETWORK_ID,
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                100,
                # Open the block clock and pump curve trade payload explicitly for
                # BlockRange within spec.
                (
                    220
                    if include_tail
                    and stream
                    in {
                        # Pass capability stream explicitly so BlockRange receives a
                        # reviewable block clock and pump curve trade input in spec.
                        CapabilityStream.BLOCK_CLOCK,
                        CapabilityStream.PUMP_CURVE_TRADE,
                        CapabilityStream.PUMP_CURVE_LIFECYCLE,
                    }
                    else 200
                    # Complete BlockRange only after its block clock and pump curve trade
                    # inputs are visible in spec.
                ),
            ),
        )
        for stream in streams
    )
    # Assemble range by id once so the spec workflow shares one value.
    range_by_id = {item.capability_id: item.block_range for item in capability_ranges}
    evidence = tuple(_evidence(stream, to_block=220 if include_tail else 200) for stream in streams)
    shards = tuple(
        DatasetShard(index, item.capability_id, range_by_id[item.capability_id], item.columns)
        for index, item in enumerate(capabilities)
        # Complete tuple only after its capability id and columns inputs are visible in spec.
    )
    kwargs = {
        "spec_version": DATASET_SPEC_VERSION,
        "source_id": SOURCE_ID,
        "source_inspection_artifact_id": INSPECTION_ID,
        # Register content digest and b through ContentDigest so the kwargs table remains
        # scannable.
        "source_schema_fingerprint": ContentDigest("b" * 64),
        "capability_mapping_digest": ContentDigest("c" * 64),
        "query_template_digest": ContentDigest("d" * 64),
        "network_id": SOLANA_MAINNET_NETWORK_ID,
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Keep the decision range component named inside the kwargs contract.
        "decision_range": decision_range,
        "settlement_tail": tail,
        "warmup_blocks": 0,
        "evidence_contracts": ((PUMPFUN_SNIPING_SOURCE_CONTRACT,) if include_contract else ()),
        "capabilities": capabilities,
        # Keep the capability ranges component named inside the kwargs contract.
        "capability_ranges": capability_ranges,
        "cut_evidence": evidence,
        "shards": shards,
        "settlement_requirement": (
            pumpfun_sniping_settlement_requirement(
                # Pass maximum sell delay transactions explicitly so
                # pumpfun_sniping_settlement_requirement receives a reviewable maximum
                # sell delay transactions input in spec.
                maximum_sell_delay_transactions=maximum_sell_delay_transactions,
                maximum_tail_blocks=20,
            )
            if include_tail and include_settlement_requirement
            else None
            # Complete the kwargs group only after its semantic components are visible.
        ),
        "source_evidence_binding": _binding(
            streams,
            decision_range,
            normalizer_digest=normalizer_digest,
        ),
    }
    spec_id = dataset_spec_identity_digest(**kwargs)
    return DatasetSpec(spec_id=spec_id, **kwargs)


def _budget(shards: int) -> BudgetReport:
    # Execute the budget workflow in explicit, reviewable steps.
    return BudgetReport(
        status=BudgetStatus.PASS,
        estimated_source_rows=10,
        estimated_source_bytes=100,
        requested_days=1,
        # Pass requested blocks explicitly so BudgetReport receives a reviewable pass and
        # budget status input in budget.
        requested_blocks=100,
        planned_shards=shards,
        expected_local_parquet_bytes=50,
        temporary_reserve_bytes=10,
        current_free_disk_bytes=10_000,
        # Pass disk low watermark bytes explicitly so BudgetReport receives a reviewable
        # pass and budget status input in budget.
        disk_low_watermark_bytes=100,
        max_remote_bytes=10_000,
        max_local_bytes=10_000,
        max_days=7,
        max_total_blocks=10_000,
        # Pass max total shards explicitly so BudgetReport receives a reviewable pass and
        # budget status input in budget.
        max_total_shards=100,
        max_shard_blocks=100,
        issues=(),
    )


def _replace_source_binding(
    spec: DatasetSpec,
    binding: PumpfunSnipingSourceEvidenceBinding,
) -> DatasetSpec:
    kwargs = {
        item.name: getattr(spec, item.name)
        for item in fields(DatasetSpec)
        if item.name != "spec_id"
    }
    kwargs["source_evidence_binding"] = binding
    return DatasetSpec(
        spec_id=dataset_spec_identity_digest(**kwargs),
        **kwargs,
    )


def _inspection(
    # Close the inspection signature after its explicit inputs.
    *,
    unknown_stream: CapabilityStream | None = None,
) -> SourceInspection:
    # Execute the inspection workflow in explicit, reviewable steps.
    descriptors = tuple(
        _descriptor(
            stream,
            proofs=_proofs(EvidenceStatus.UNKNOWN) if stream is unknown_stream else None,
        )
        # Pass stream explicitly so tuple receives a reviewable unknown and descriptor
        # input in inspection.
        for stream in CapabilityStream
    )
    evidence = tuple(_evidence(stream) for stream in CapabilityStream)
    receipts = tuple(
        build_bounded_source_evidence_receipt(
            # Pass source id explicitly so build_bounded_source_evidence_receipt receives
            # a reviewable c and d input in inspection.
            source_id=SOURCE_ID,
            capability_id=descriptor.capability_id,
            protocol_version=descriptor.protocol_version,
            capability_schema_version=descriptor.schema_version,
            capability_mapping_digest=ContentDigest("c" * 64),
            # Keep the content digest and d ContentDigest step visible while building
            # receipts.
            query_template_digest=ContentDigest("d" * 64),
            projector_digest=PROJECTOR_DIGEST,
            normalizer_digest=NORMALIZER_DIGEST,
            cut_evidence=next(
                item for item in evidence if item.capability_id == descriptor.capability_id
            ),
            decision_range=_decision_range(),
            proofs=descriptor.proofs,
            source_fidelity=descriptor.fidelity,
            # Keep the content digest and index ContentDigest step visible while building
            # receipts.
            query_fingerprints=(ContentDigest(f"{index + 1:064x}"),),
            result_digest=ContentDigest(f"{index + 101:064x}"),
            observed_rows=1,
            launch_universe=(
                _launch_universe(_decision_range())
                if descriptor.stream is CapabilityStream.TOKEN_LAUNCH
                else None
            ),
            skipped_slot_sentinel=(
                _sentinel_evidence() if descriptor.stream is CapabilityStream.BLOCK_CLOCK else None
            ),
            terminal_lifecycle_ordering=(
                _lifecycle_evidence()
                if descriptor.stream is CapabilityStream.PUMP_CURVE_LIFECYCLE
                else None
            ),
        )
        for index, descriptor in enumerate(descriptors)
        # Complete tuple only after its c and d inputs are visible in inspection.
    )
    metadata = SourceMetadata(
        source_id=SOURCE_ID,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass server version explicitly so SourceMetadata receives a reviewable
        # fixture-v1 and c input in inspection.
        server_version="fixture-v1",
        tables=(),
        capabilities=descriptors,
        capability_mapping_digest=ContentDigest("c" * 64),
        query_template_digest=ContentDigest("d" * 64),
        # Pass cut evidence explicitly so SourceMetadata receives a reviewable fixture-v1
        # and c input in inspection.
        cut_evidence=evidence,
        evidence_receipts=receipts,
    )
    return SourceInspection(
        metadata=metadata,
        # Include schema fingerprint in the completed inspection result.
        schema_fingerprint=source_schema_fingerprint(metadata),
        inspected_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


# Keep the inspections contract and validation rules together.
class _Inspections:
    def __init__(self, inspection: SourceInspection) -> None:
        self.inspection = inspection

    def load(self, artifact_id: ArtifactId) -> SourceInspection:
        # Execute the inspections load workflow in explicit, reviewable steps.
        assert artifact_id == INSPECTION_ID
        return self.inspection


# Keep the disk contract and validation rules together.
class _Disk:
    def capacity(self) -> DiskCapacity:
        return DiskCapacity(1_000_000)


def _request() -> PlanDatasetRequest:
    # Execute the request workflow in explicit, reviewable steps.
    settlement_requirement = pumpfun_sniping_settlement_requirement(
        maximum_sell_delay_transactions=25,
        maximum_tail_blocks=20,
    )
    requirements = tuple(
        # Keep the data requirement and execution DataRequirement step visible while
        # building requirements.
        DataRequirement(
            origin=RequirementOrigin.EXECUTION,
            origin_id=f"sniping-{stream.value.lower()}-v1",
            capability_id=_capability_id(stream),
            columns=(),
            # Pass evidence contracts explicitly so DataRequirement receives a reviewable
            # sniping- and -v1 input in request.
            evidence_contracts=(PUMPFUN_SNIPING_SOURCE_CONTRACT,)
            if stream is CapabilityStream.BLOCK_CLOCK
            else (),
            warmup_blocks=20 if stream is CapabilityStream.TOKEN_LAUNCH else 0,
            settlement_requirement=(
                # Pass settlement requirement explicitly so DataRequirement receives a
                # reviewable sniping- and -v1 input in request.
                settlement_requirement if stream is CapabilityStream.BLOCK_CLOCK else None
            ),
        )
        for stream in CapabilityStream
    )
    # Return the completed request result without a hidden fallback.
    return PlanDatasetRequest(
        source_id=SOURCE_ID,
        source_inspection_artifact_id=INSPECTION_ID,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include decision range in the completed request result.
        decision_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            100,
            200,
            # Complete BlockRange only after its solana mainnet network id and block32
            # transaction32 position schema id inputs are visible in request.
        ),
        warmup_blocks=5,
        settlement_tail_blocks=0,
        max_shard_blocks=50,
        requested_days=1,
        # Pass requirements explicitly so PlanDatasetRequest receives a reviewable block
        # range and budget limits input in request.
        requirements=requirements,
        budget_limits=BudgetLimits(10_000, 10_000, 7, 0, 0),
        query_limits=QueryLimits(30, 1_000_000, 10_000),
    )


def _planner(inspection: SourceInspection) -> PlanDataset:
    # Execute the planner workflow in explicit, reviewable steps.
    return PlanDataset(
        _Inspections(inspection),
        DatasetPlanningPolicy(
            budget_limits=BudgetLimits(10_000, 10_000, 7, 0, 0),
            query_limits=QueryLimits(30, 1_000_000, 10_000),
            # Pass max total blocks explicitly so DatasetPlanningPolicy receives a
            # reviewable budget limits and query limits input in planner.
            max_total_blocks=10_000,
            max_total_shards=1_000,
            max_shard_blocks=100,
        ),
        disk_probe=_Disk(),
        # Complete PlanDataset only after its inspections and dataset planning policy inputs
        # are visible in planner.
    )


def test_exact_four_stream_contract_is_admitted() -> None:
    require_pumpfun_sniping_source_contract(_spec())


def test_unknown_proof_and_missing_stream_fail_closed_with_stable_tokens() -> None:
    # Execute the test unknown proof and missing stream fail closed with stable tokens
    # workflow in explicit, reviewable steps.
    with pytest.raises(SourceEvidenceMismatchError) as unknown:
        require_pumpfun_sniping_source_contract(_spec(unknown_stream=CapabilityStream.BLOCK_CLOCK))
    assert "failed_transactions_included" in unknown.value.missing_proofs

    with pytest.raises(SourceEvidenceMismatchError) as missing:
        # Keep raises, source evidence mismatch error and pytest active only for the
        # bounded test unknown proof and missing stream fail closed with stable tokens
        # operation.
        require_pumpfun_sniping_source_contract(
            _spec(
                streams=tuple(
                    stream
                    for stream in CapabilityStream
                    # Pass stream explicitly so tuple receives a reviewable pump curve
                    # lifecycle and stream input in test unknown proof and missing stream
                    # fail closed with stable tokens.
                    if stream is not CapabilityStream.PUMP_CURVE_LIFECYCLE
                )
            )
        )
    assert missing.value.missing_proofs == ("missing_pump_curve_lifecycle_stream",)


# Define test missing sniping evidence contract fails closed as one focused operation with
# an explicit boundary.
def test_missing_sniping_evidence_contract_fails_closed() -> None:
    # Execute the test missing sniping evidence contract fails closed workflow in
    # explicit, reviewable steps.
    with pytest.raises(SourceEvidenceMismatchError) as caught:
        require_pumpfun_sniping_source_contract(_spec(include_contract=False))
    assert caught.value.missing_proofs == ("sniping_evidence_contract",)


def test_missing_settlement_requirement_fails_closed() -> None:
    # Execute the test missing settlement requirement fails closed workflow in explicit,
    # reviewable steps.
    with pytest.raises(SourceEvidenceMismatchError) as caught:
        require_pumpfun_sniping_source_contract(_spec(include_settlement_requirement=False))
    assert caught.value.missing_proofs == ("settlement_requirement",)


def test_settlement_tail_is_mandatory_and_mixed_network_is_rejected() -> None:
    # Execute the test settlement tail is mandatory and mixed network is rejected workflow
    # in explicit, reviewable steps.
    with pytest.raises(SourceEvidenceMismatchError) as missing_tail:
        require_pumpfun_sniping_source_contract(_spec(include_tail=False))
    assert missing_tail.value.missing_proofs == ("settlement_tail",)

    with pytest.raises(ValueError, match="different network"):
        # Keep raises, value error and pytest active only for the bounded test settlement
        # tail is mandatory and mixed network is rejected operation.
        replace(
            _spec(),
            decision_range=BlockRange(
                NetworkId("solana:11111111111111111111111111111112"),
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                # Keep block range, block32 transaction32 position schema id and network
                # id visible while completing BlockRange within test settlement tail is
                # mandatory and mixed network is rejected.
                100,
                200,
            ),
        )


def test_plan_dataset_resolves_capability_ranges_and_right_tail() -> None:
    # Execute the test plan dataset resolves capability ranges and right tail workflow in
    # explicit, reviewable steps.
    plan = _planner(_inspection()).execute(_request())
    ranges = {item.capability_id: item.block_range for item in plan.spec.capability_ranges}

    assert plan.spec.decision_range.from_block_ordinal == 100
    assert plan.spec.decision_range.to_block_ordinal == 200
    assert plan.spec.settlement_tail is not None
    # Verify the from block ordinal, settlement tail and spec relationship before this
    # scenario is accepted.
    assert plan.spec.settlement_tail.from_block_ordinal == 200
    assert plan.spec.settlement_tail.to_block_ordinal == 220
    assert plan.spec.settlement_requirement == pumpfun_sniping_settlement_requirement(
        maximum_sell_delay_transactions=25,
        maximum_tail_blocks=20,
        # Complete pumpfun_sniping_settlement_requirement only after its declared inputs are
        # visible in test plan dataset resolves capability ranges and right tail.
    )
    assert ranges[_capability_id(CapabilityStream.TOKEN_LAUNCH)].from_block_ordinal == 80
    assert ranges[_capability_id(CapabilityStream.TOKEN_LAUNCH)].to_block_ordinal == 200
    assert plan.spec.source_evidence_binding is not None
    assert plan.spec.source_evidence_binding.launch_universe.decision_range == (
        plan.spec.decision_range
    )
    assert plan.spec.source_evidence_binding.launch_universe.classified_count == 3
    for stream in (
        CapabilityStream.BLOCK_CLOCK,
        # Traverse block clock, pump curve trade and pump curve lifecycle explicitly so
        # each test plan dataset resolves capability ranges and right tail iteration
        # remains traceable.
        CapabilityStream.PUMP_CURVE_TRADE,
        CapabilityStream.PUMP_CURVE_LIFECYCLE,
    ):
        assert ranges[_capability_id(stream)].to_block_ordinal == 220


def test_caller_settlement_tail_never_extracts_launch_targets() -> None:
    # Execute the test caller settlement tail never extracts launch targets workflow in
    # explicit, reviewable steps.
    request = replace(_request(), settlement_tail_blocks=10)

    plan = _planner(_inspection()).execute(request)
    ranges = {item.capability_id: item.block_range for item in plan.spec.capability_ranges}

    assert ranges[_capability_id(CapabilityStream.TOKEN_LAUNCH)].to_block_ordinal == 200
    for stream in (
        # Traverse block clock, pump curve trade and pump curve lifecycle explicitly so
        # each test caller settlement tail never extracts launch targets iteration remains
        # traceable.
        CapabilityStream.BLOCK_CLOCK,
        CapabilityStream.PUMP_CURVE_TRADE,
        CapabilityStream.PUMP_CURVE_LIFECYCLE,
    ):
        assert ranges[_capability_id(stream)].to_block_ordinal == 220


# Define test settlement tail hard guard rejects larger declared range as one focused
# operation with an explicit boundary.
def test_settlement_tail_hard_guard_rejects_larger_declared_range() -> None:
    # Execute the test settlement tail hard guard rejects larger declared range workflow
    # in explicit, reviewable steps.
    request = _request()

    with pytest.raises(SourceEvidenceMismatchError) as caught:
        _planner(_inspection()).execute(replace(request, settlement_tail_blocks=21))

    assert caught.value.missing_proofs == ("settlement_tail_limit_exceeded",)


def test_dataset_spec_rejects_tail_beyond_hard_guard() -> None:
    # Execute the test dataset spec rejects tail beyond hard guard workflow in explicit,
    # reviewable steps.
    spec = _spec()
    assert spec.settlement_tail is not None

    with pytest.raises(ValueError, match="exceeds its declared hard guard"):
        # Keep raises, value error and pytest active only for the bounded test dataset
        # spec rejects tail beyond hard guard operation.
        replace(
            spec,
            settlement_tail=BlockRange(
                spec.network_id,
                spec.position_schema_id,
                # Pass spec explicitly so BlockRange receives a reviewable network id and
                # position schema id input in test dataset spec rejects tail beyond hard
                # guard.
                spec.decision_range.to_block_ordinal,
                spec.decision_range.to_block_ordinal + 21,
            ),
        )


def test_settlement_requirement_changes_dataset_identity_and_is_serialized() -> None:
    # Execute the test settlement requirement changes dataset identity and is serialized
    # workflow in explicit, reviewable steps.
    first = _spec(maximum_sell_delay_transactions=25)
    second = _spec(maximum_sell_delay_transactions=26)

    assert first.spec_id != second.spec_id
    assert dataset_spec_document(second)["settlement_requirement"] == {
        "initial_delay_transactions": 500,
        # Keep the maximum followup delay transactions expectation tied to settlement
        # requirement, initial delay transactions and maximum followup delay transactions
        # in this scenario.
        "maximum_followup_delay_transactions": 26,
        "maximum_tail_blocks": 20,
        "minimum_duration_ns": 2_000_000_000,
        "schema": "global-transaction-duration-roundtrip/v1",
        "settlement_streams": [
            # Keep the block clock expectation tied to settlement requirement, initial
            # delay transactions and maximum followup delay transactions in this scenario.
            "BLOCK_CLOCK",
            "PUMP_CURVE_LIFECYCLE",
            "PUMP_CURVE_TRADE",
        ],
        "target_stream": "TOKEN_LAUNCH",
        # Verify the settlement requirement, initial delay transactions and maximum followup
        # delay transactions relationship before this scenario is accepted.
    }


def test_source_evidence_binding_changes_dataset_identity_and_round_trips() -> None:
    first = _spec()
    second = _spec(normalizer_digest=ContentDigest("6" * 64))

    assert first.spec_id != second.spec_id
    assert dataset_spec_from_document(dataset_spec_document(second)) == second
    binding_document = dataset_spec_document(second)["source_evidence_binding"]
    assert isinstance(binding_document, dict)
    assert binding_document["normalizer_digest"] == "6" * 64


def test_snapshot_preparation_rejects_mismatched_evidence_binding() -> None:
    inspection = _inspection()
    plan = _planner(inspection).execute(_request())
    binding = plan.spec.source_evidence_binding
    assert binding is not None
    forged = _replace_source_binding(
        plan.spec,
        replace(
            binding,
            launch_universe=replace(
                binding.launch_universe,
                ordered_exclusion_digest=ContentDigest("6" * 64),
            ),
        ),
    )

    with pytest.raises(SourceEvidenceMismatchError) as caught:
        require_pumpfun_sniping_inspection_receipts(inspection.metadata, forged)
    assert caught.value.missing_proofs == ("source_evidence_binding",)


def test_automatic_tail_guard_fails_closed_at_source_watermark() -> None:
    # Execute the test automatic tail guard fails closed at source watermark workflow in
    # explicit, reviewable steps.
    request = _request()
    requirements = tuple(
        replace(
            item,
            settlement_requirement=pumpfun_sniping_settlement_requirement(
                # Pass maximum sell delay transactions explicitly into
                # pumpfun_sniping_settlement_requirement within test automatic tail guard
                # fails closed at source watermark.
                maximum_sell_delay_transactions=25,
                maximum_tail_blocks=21,
            ),
        )
        if item.settlement_requirement is not None
        # Route all remaining cases through the explicit alternative branch.
        else item
        for item in request.requirements
    )

    with pytest.raises(SourceEvidenceMismatchError) as caught:
        _planner(_inspection()).execute(replace(request, requirements=requirements))
    # Verify the missing proofs, value and bounded query provenance relationship before
    # this scenario is accepted.
    assert caught.value.missing_proofs == ("bounded_query_provenance",)


def test_plan_dataset_does_not_upgrade_unknown_source_proof() -> None:
    # Execute the test plan dataset does not upgrade unknown source proof workflow in
    # explicit, reviewable steps.
    with pytest.raises(SourceEvidenceMismatchError):
        _planner(_inspection(unknown_stream=CapabilityStream.TOKEN_LAUNCH)).execute(_request())


def test_plan_dataset_requires_a_receipt_for_every_selected_capability() -> None:
    # Execute the test plan dataset requires a receipt for every selected capability
    # workflow in explicit, reviewable steps.
    inspection = _inspection(unknown_stream=CapabilityStream.TOKEN_LAUNCH)
    metadata = inspection.metadata
    missing_id = _capability_id(CapabilityStream.TOKEN_LAUNCH)
    without_launch_receipt = replace(
        metadata,
        # Keep the item and evidence receipts tuple step visible while building without
        # launch receipt.
        evidence_receipts=tuple(
            item for item in metadata.evidence_receipts if item.capability_id != missing_id
        ),
    )

    with pytest.raises(SourceEvidenceMismatchError) as caught:
        # Invoke execute for request as a visible test plan dataset requires a receipt for
        # every selected capability step.
        _planner(replace(inspection, metadata=without_launch_receipt)).execute(_request())
    assert caught.value.missing_proofs == ("bounded_query_provenance",)


@pytest.mark.parametrize("legacy_version", [1, 2, 3])
def test_dataset_plan_v3_round_trip_and_legacy_plan_requires_reprepare(
    legacy_version: int,
    # Close the test dataset plan v3 round trip and legacy plan requires reprepare signature
    # after its explicit inputs.
) -> None:
    # Execute the test dataset plan v3 round trip and legacy plan requires reprepare
    # workflow in explicit, reviewable steps.
    spec = _spec()
    plan = DatasetPlan(spec, _budget(len(spec.shards)), QueryLimits(30, 1_000_000, 10_000))
    payload = dataset_plan_bytes(plan)

    assert dataset_plan_from_bytes(payload) == plan
    legacy = canonical_json_bytes({"schema": f"backtest.dataset-plan/v{legacy_version}"})
    with pytest.raises(ReprepareRequiredError) as caught:
        dataset_plan_from_bytes(legacy)
    assert caught.value.artifact_contract == f"backtest.dataset-plan/v{legacy_version}"


# Define test dataset spec v5 document round trip recomputes identity as one focused
# operation with an explicit boundary.
def test_dataset_spec_v5_document_round_trip_recomputes_identity() -> None:
    # Execute the test dataset spec v4 document round trip recomputes identity workflow in
    # explicit, reviewable steps.
    spec = _spec()
    document = dataset_spec_document(spec)

    assert dataset_spec_from_document(document) == spec

    forged = dict(document)
    forged["spec_id"] = "f" * 64
    # Acquire raises, dataset plan codec error and pytest at an explicit test dataset spec
    # v4 document round trip recomputes identity context boundary so cleanup remains
    # scoped.
    with pytest.raises(DatasetPlanCodecError, match="fields are invalid"):
        dataset_spec_from_document(forged)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_dataset_spec_document_requires_reprepare(version: int) -> None:
    # Execute the test legacy dataset spec document requires reprepare workflow in
    # explicit, reviewable steps.
    document = dataset_spec_document(_spec())
    document["spec_version"] = version

    with pytest.raises(ReprepareRequiredError) as caught:
        dataset_spec_from_document(document)
    assert caught.value.artifact_contract == f"backtest.dataset-spec/v{version}"


# Define test source inspection v5 round trip and legacy requires reprepare as one focused
# operation with an explicit boundary.
def test_source_inspection_v5_round_trip_and_legacy_requires_reprepare() -> None:
    # Execute the test source inspection v4 round trip and legacy requires reprepare
    # workflow in explicit, reviewable steps.
    inspection = _inspection()
    manifest = source_inspection_manifest(inspection)
    payload = source_inspection_payload(inspection)

    assert decode_source_inspection(manifest, payload) == inspection
    with pytest.raises(ReprepareRequiredError) as caught:
        # Keep raises, reprepare required error and pytest active only for the bounded
        # test source inspection v4 round trip and legacy requires reprepare operation.
        decode_source_inspection(
            canonical_json({"artifact_schema": "source-inspection/v2"}),
            canonical_json({}),
        )
    assert caught.value.artifact_contract == "source-inspection/v2"


# Define test source inspection v5 rejects tampered receipt content as one focused
# operation with an explicit boundary.
def test_source_inspection_v5_rejects_tampered_receipt_content() -> None:
    # Execute the test source inspection v4 rejects tampered receipt content workflow in
    # explicit, reviewable steps.
    inspection = _inspection()
    manifest = source_inspection_manifest(inspection)
    raw = json.loads(source_inspection_payload(inspection))
    raw["evidence_receipts"][0]["result_digest"] = "f" * 64

    with pytest.raises(ValueError, match="receipt does not match"):
        # Invoke decode_source_inspection for canonical json and manifest as a visible
        # test source inspection v4 rejects tampered receipt content step.
        decode_source_inspection(manifest, canonical_json(raw))


def test_legacy_bounded_receipt_requires_reprepare() -> None:
    inspection = _inspection()
    raw = json.loads(source_inspection_payload(inspection))
    raw["evidence_receipts"][0]["schema"] = "bounded-source-evidence/v1"

    with pytest.raises(ReprepareRequiredError) as caught:
        decode_source_inspection(source_inspection_manifest(inspection), canonical_json(raw))
    assert caught.value.artifact_contract == "bounded-source-evidence/v1"


def test_evidence_artifacts_are_secret_free() -> None:
    marker = b"fixture-password-must-not-appear"
    inspection = _inspection()
    plan = _planner(inspection).execute(_request())

    assert marker not in source_inspection_payload(inspection)
    assert marker not in source_inspection_manifest(inspection)
    assert marker not in dataset_plan_bytes(plan)


def test_receipt_identity_binds_versions_cut_queries_results_and_row_count() -> None:
    # Execute the test receipt identity binds versions cut queries results and row count
    # workflow in explicit, reviewable steps.
    receipt = _inspection().metadata.evidence_receipts[0]
    changed_cut = replace(receipt.cut_evidence, chain_finality=ChainFinality.CONFIRMED)
    mutations = (
        {"protocol_version": "different"},
        {"capability_schema_version": "different"},
        # Register content digest through ContentDigest so the mutations table remains
        # scannable.
        {"capability_mapping_digest": ContentDigest("1" * 64)},
        {"query_template_digest": ContentDigest("2" * 64)},
        {"projector_digest": ContentDigest("6" * 64)},
        {"normalizer_digest": ContentDigest("7" * 64)},
        {"decision_range": replace(receipt.decision_range, from_block_ordinal=101)},
        {
            "cut_evidence": changed_cut,
            "source_fidelity": replace(
                receipt.source_fidelity,
                chain_finality=ChainFinality.CONFIRMED,
            ),
        },
        {"query_fingerprints": (ContentDigest("3" * 64),)},
        {"result_digest": ContentDigest("4" * 64)},
        # Keep the observed rows component named inside the mutations contract.
        {"observed_rows": receipt.observed_rows + 1},
        {
            "skipped_slot_sentinel": replace(
                receipt.skipped_slot_sentinel,
                recognized_count=2,
            )
            if receipt.skipped_slot_sentinel is not None
            else _sentinel_evidence()
        },
    )

    for mutation in mutations:
        # Process mutations inside the bounded test receipt identity binds versions cut
        # queries results and row count loop.
        with pytest.raises(ValueError, match="receipt does not match"):
            replace(receipt, **mutation)


@pytest.mark.parametrize(
    "legacy",
    ["source-inspection/v1", "source-inspection/v3", "source-inspection/v4"],
)
def test_all_legacy_source_inspections_require_reprepare(legacy: str) -> None:
    # Execute the test all legacy source inspections require reprepare workflow in
    # explicit, reviewable steps.
    with pytest.raises(ReprepareRequiredError) as caught:
        # Keep raises, reprepare required error and pytest active only for the bounded
        # test all legacy source inspections require reprepare operation.
        decode_source_inspection(
            canonical_json({"artifact_schema": legacy}),
            canonical_json({}),
        )
    assert caught.value.artifact_contract == legacy
