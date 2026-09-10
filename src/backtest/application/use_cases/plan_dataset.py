"""Compile logical requirements into a deterministic selective dataset plan."""

from __future__ import annotations

from collections import defaultdict

from backtest.application.copy_source import COPYBUY_SOURCE_CONTRACT
from backtest.application.copy_source_contracts import (
    # Copy planning requires independent signer coverage and its exact receipt binding.
    require_copy_inspection_receipts,
    resolve_copy_source_binding,
)
from backtest.application.errors import (
    BudgetExceededError,
    # Missing capability evidence remains a typed planning failure.
    CapabilityAmbiguousError,
    # Include capability not found error so the errors dependency remains explicit.
    CapabilityNotFoundError,
    FidelityMismatchError,
    ProtocolVersionMismatchError,
    RequiredColumnMissingError,
    SourceEvidenceMismatchError,
    # Include source inspection artifact invalid error so the errors dependency remains
    # explicit.
    SourceInspectionArtifactInvalidError,
)
from backtest.application.models import (
    DATASET_SPEC_VERSION,
    PUMPFUN_SNIPING_SOURCE_CONTRACT,
    # Include budget issue so the models dependency remains explicit.
    BudgetIssue,
    BudgetIssueKind,
    BudgetLimits,
    BudgetReport,
    BudgetStatus,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityDescriptor,
    CapabilityExtractionRange,
    CapabilityStream,
    CopyBuySettlementRequirement,
    # Declared copy settlement is distinct from ordinary single-sale settlement.
    DataRequirement,
    # Include dataset plan so the models dependency remains explicit.
    DatasetPlan,
    DatasetPlanningPolicy,
    DatasetShard,
    DatasetSpec,
    PlanDatasetRequest,
    # Include planned capability so the models dependency remains explicit.
    PlannedCapability,
    SettlementRequirement,
    SourceEstimate,
    dataset_spec_identity_digest,
)

# Import source at the visible module dependency boundary.
from backtest.application.ports.source import (
    DatasetEstimator,
    DiskCapacityProbe,
    SourceInspectionLoader,
)

# Import source contracts at the visible module dependency boundary.
from backtest.application.source_contracts import (
    require_pumpfun_sniping_inspection_receipts,
    require_pumpfun_sniping_source_contract,
    resolve_pumpfun_sniping_source_evidence_binding,
)

# The binding type fixes the dataset source family before identity is computed.
from backtest.application.source_evidence import (
    PumpfunCopyBuySourceEvidenceBinding,
    PumpfunSnipingSourceEvidenceBinding,
)
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    FidelityRequirement,
    IngestionCompleteness,
    SourceConsistency,
    SourceFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.identifiers import CapabilityId
from backtest.domain.time import BlockRange


class PlanDataset:
    """Pure requirement compilation plus optional metadata-only estimates."""

    def __init__(
        self,
        inspection_loader: SourceInspectionLoader,
        policy: DatasetPlanningPolicy,
        *,
        # Keep the estimator input explicit in the init contract.
        estimator: DatasetEstimator | None = None,
        disk_probe: DiskCapacityProbe | None = None,
    ) -> None:
        # Execute the plan dataset init workflow in explicit, reviewable steps.
        self._inspection_loader = inspection_loader
        self._policy = policy
        self._estimator = estimator
        self._disk_probe = disk_probe

    def execute(self, request: PlanDatasetRequest) -> DatasetPlan:
        # Execute the plan dataset execute workflow in explicit, reviewable steps.
        inspection = self._inspection_loader.load(request.source_inspection_artifact_id)
        metadata = inspection.metadata
        if metadata.source_id != request.source_id:
            raise SourceInspectionArtifactInvalidError(request.source_inspection_artifact_id)
        if (
            # Keep metadata visible while evaluating the network id, position schema id
            # and metadata guard.
            metadata.network_id != request.network_id
            or metadata.position_schema_id != request.position_schema_id
        ):
            raise SourceInspectionArtifactInvalidError(request.source_inspection_artifact_id)
        mapping_digest = metadata.capability_mapping_digest
        # Assemble query template digest once so the plan dataset execute workflow shares
        # one value.
        query_template_digest = metadata.query_template_digest
        if mapping_digest is None or query_template_digest is None:
            raise SourceInspectionArtifactInvalidError(request.source_inspection_artifact_id)

        evidence_by_id = {item.capability_id: item for item in metadata.cut_evidence}
        requirements = _group_requirements(request.requirements)
        # Assemble settlement requirement once so the plan dataset execute workflow shares
        # one value.
        settlement_requirement = _combine_settlement_requirements(request.requirements)
        settlement_tail_guard = _settlement_tail_guard(
            request,
            settlement_requirement=settlement_requirement,
        )
        # Assemble capability ranges values once so the plan dataset execute workflow
        # shares one value.
        capability_ranges_values: list[CapabilityExtractionRange] = []
        for capability_id, grouped in requirements:
            # Process requirements inside the bounded plan dataset execute loop.
            selected_stream = _selected_stream(
                capability_id,
                grouped,
                metadata.capabilities,
            )
            # Assemble is settlement stream once so the plan dataset execute workflow
            # shares one value.
            is_settlement_stream = (
                settlement_requirement is None
                or selected_stream in settlement_requirement.settlement_streams
            )
            capability_ranges_values.append(
                # Pass capability extraction range explicitly to append for capability
                # extraction range and required range.
                CapabilityExtractionRange(
                    capability_id=capability_id,
                    block_range=_required_range(
                        request,
                        grouped,
                        # Pass include declared settlement tail explicitly so
                        # _required_range receives a reviewable request and grouped input
                        # in plan dataset execute.
                        include_declared_settlement_tail=is_settlement_stream,
                        automatic_settlement_tail_blocks=(
                            settlement_tail_guard
                            if settlement_requirement is not None and is_settlement_stream
                            else 0
                            # Complete _required_range only after its request and grouped
                            # inputs are visible in plan dataset execute.
                        ),
                    ),
                )
            )
        capability_ranges = tuple(capability_ranges_values)
        # Assemble range by id once so the plan dataset execute workflow shares one value.
        range_by_id = {item.capability_id: item.block_range for item in capability_ranges}
        planned = tuple(
            _resolve_capability(
                capability_id,
                grouped,
                # Pass metadata explicitly so _resolve_capability receives a reviewable
                # capabilities and get input in plan dataset execute.
                metadata.capabilities,
                evidence=evidence_by_id.get(capability_id),
                requested_range=range_by_id[capability_id],
            )
            for capability_id, grouped in requirements
            # Complete tuple only after its capabilities and get inputs are visible in plan
            # dataset execute.
        )
        evidence_contracts = tuple(
            sorted(
                {
                    contract
                    # Pass requirement explicitly so sorted receives a reviewable
                    # requirements and evidence contracts input in plan dataset execute.
                    for requirement in request.requirements
                    for contract in requirement.evidence_contracts
                }
            )
        )
        # Assemble unsupported evidence contracts once so the plan dataset execute
        # workflow shares one value.
        unsupported_evidence_contracts = tuple(
            item
            for item in evidence_contracts
            if item not in (PUMPFUN_SNIPING_SOURCE_CONTRACT, COPYBUY_SOURCE_CONTRACT)
        )
        # Unknown evidence contracts cannot be ignored as optional annotations.
        if unsupported_evidence_contracts:
            # Handle the plan dataset execute unsupported_evidence_contracts branch as a
            # distinct logical block.
            raise ValueError(
                f"unsupported source evidence contract: {unsupported_evidence_contracts[0]}"
            )

        effective_budget = self._policy.effective_budget(request.budget_limits)
        effective_query = self._policy.effective_query(request.query_limits)
        # Assemble effective shard blocks once so the plan dataset execute workflow shares
        # one value.
        effective_shard_blocks = min(request.max_shard_blocks, self._policy.max_shard_blocks)
        shard_count = sum(
            (item.block_range.span + effective_shard_blocks - 1) // effective_shard_blocks
            for item in capability_ranges
        )
        # Assemble requested blocks once so the plan dataset execute workflow shares one
        # value.
        requested_blocks = sum(item.block_range.span for item in capability_ranges)
        disk = self._disk_probe.capacity() if self._disk_probe is not None else None
        free_disk_bytes = disk.free_bytes if disk is not None else None
        preflight_budget = _build_budget_report(
            request,
            # Keep the unknown and source estimate unknown step visible while building
            # preflight budget.
            SourceEstimate.unknown(),
            free_disk_bytes,
            limits=effective_budget,
            policy=self._policy,
            requested_blocks=requested_blocks,
            # Pass planned shards explicitly so _build_budget_report receives a reviewable
            # unknown and policy input in plan dataset execute.
            planned_shards=shard_count,
            effective_shard_blocks=effective_shard_blocks,
        )
        if preflight_budget.rejected:
            raise BudgetExceededError(preflight_budget)

        # Assemble shards once so the plan dataset execute workflow shares one value.
        shards: list[DatasetShard] = []
        ordinal = 0
        for capability in planned:
            # Process planned inside the bounded plan dataset execute loop.
            for block_range in range_by_id[capability.capability_id].split(effective_shard_blocks):
                # Process split, effective shard blocks and range by id inside the bounded
                # plan dataset execute loop.
                shards.append(
                    DatasetShard(
                        ordinal=ordinal,
                        capability_id=capability.capability_id,
                        block_range=block_range,
                        # Pass columns explicitly so DatasetShard receives a reviewable
                        # capability id and columns input in plan dataset execute.
                        columns=capability.columns,
                    )
                )
                ordinal += 1

        selected_evidence = tuple(
            # Pass evidence by id explicitly so tuple receives a reviewable capability id
            # and evidence by id input in plan dataset execute.
            evidence_by_id[item.capability_id]
            for item in planned
            if item.capability_id in evidence_by_id
        )
        maximum_tail_blocks = max(
            # Pass item explicitly so max receives a reviewable to block ordinal and block
            # range input in plan dataset execute.
            item.block_range.to_block_ordinal - request.decision_range.to_block_ordinal
            for item in capability_ranges
        )
        settlement_tail = (
            None
            # Keep the maximum tail blocks component named inside the settlement tail
            # contract.
            if maximum_tail_blocks == 0
            else BlockRange(
                request.network_id,
                request.position_schema_id,
                request.decision_range.to_block_ordinal,
                # Pass request explicitly so BlockRange receives a reviewable network id
                # and position schema id input in plan dataset execute.
                request.decision_range.to_block_ordinal + maximum_tail_blocks,
            )
        )
        resolved_shards = tuple(shards)
        # Source families resolve through distinct proof contracts before computing any ID.
        source_evidence_binding: (
            PumpfunCopyBuySourceEvidenceBinding | PumpfunSnipingSourceEvidenceBinding | None
        ) = None
        spec_version = DATASET_SPEC_VERSION
        if COPYBUY_SOURCE_CONTRACT in evidence_contracts:
            # A copy plan requires coverage for the exact selected wallets and decision cut.
            source_evidence_binding = resolve_copy_source_binding(
                metadata, planned, request.decision_range
            )
            spec_version = 6
        elif PUMPFUN_SNIPING_SOURCE_CONTRACT in evidence_contracts:
            # The original Sniping family retains its established binding and schema version.
            source_evidence_binding = resolve_pumpfun_sniping_source_evidence_binding(
                metadata, planned, request.decision_range
            )
        spec_id = dataset_spec_identity_digest(
            # Pass spec version explicitly so dataset_spec_identity_digest receives a
            # reviewable source id and source inspection artifact id input in plan dataset
            # execute.
            spec_version=spec_version,
            source_id=request.source_id,
            source_inspection_artifact_id=request.source_inspection_artifact_id,
            source_schema_fingerprint=inspection.schema_fingerprint,
            capability_mapping_digest=mapping_digest,
            # Pass query template digest explicitly so dataset_spec_identity_digest
            # receives a reviewable source id and source inspection artifact id input in
            # plan dataset execute.
            query_template_digest=query_template_digest,
            network_id=request.network_id,
            position_schema_id=request.position_schema_id,
            decision_range=request.decision_range,
            settlement_tail=settlement_tail,
            # Pass warmup blocks explicitly so dataset_spec_identity_digest receives a
            # reviewable source id and source inspection artifact id input in plan dataset
            # execute.
            warmup_blocks=request.warmup_blocks,
            evidence_contracts=evidence_contracts,
            capabilities=planned,
            capability_ranges=capability_ranges,
            cut_evidence=selected_evidence,
            # Pass shards explicitly so dataset_spec_identity_digest receives a reviewable
            # source id and source inspection artifact id input in plan dataset execute.
            shards=resolved_shards,
            settlement_requirement=settlement_requirement,
            source_evidence_binding=source_evidence_binding,
        )
        # Construct the immutable spec from the same operands used for its identity.
        spec = DatasetSpec(
            spec_version=spec_version,
            # Pass spec id explicitly so DatasetSpec receives a reviewable source id and
            # source inspection artifact id input in plan dataset execute.
            spec_id=spec_id,
            source_id=request.source_id,
            source_inspection_artifact_id=request.source_inspection_artifact_id,
            source_schema_fingerprint=inspection.schema_fingerprint,
            capability_mapping_digest=mapping_digest,
            # Pass query template digest explicitly so DatasetSpec receives a reviewable
            # source id and source inspection artifact id input in plan dataset execute.
            query_template_digest=query_template_digest,
            network_id=request.network_id,
            position_schema_id=request.position_schema_id,
            decision_range=request.decision_range,
            settlement_tail=settlement_tail,
            # Pass warmup blocks explicitly so DatasetSpec receives a reviewable source id
            # and source inspection artifact id input in plan dataset execute.
            warmup_blocks=request.warmup_blocks,
            evidence_contracts=evidence_contracts,
            capabilities=planned,
            capability_ranges=capability_ranges,
            cut_evidence=selected_evidence,
            # Pass shards explicitly so DatasetSpec receives a reviewable source id and
            # source inspection artifact id input in plan dataset execute.
            shards=resolved_shards,
            settlement_requirement=settlement_requirement,
            source_evidence_binding=source_evidence_binding,
        )
        if COPYBUY_SOURCE_CONTRACT in evidence_contracts:
            # Final receipt checks prevent mismatched source evidence from escaping the planner.
            require_copy_inspection_receipts(metadata, spec)
        if PUMPFUN_SNIPING_SOURCE_CONTRACT in evidence_contracts:
            # Handle the plan dataset execute pumpfun sniping source contract and evidence
            # contracts condition as a distinct block.
            require_pumpfun_sniping_inspection_receipts(metadata, spec)
            require_pumpfun_sniping_source_contract(spec)

        estimate = SourceEstimate.unknown()
        if request.request_remote_estimate and self._estimator is not None:
            estimate = self._estimator.estimate(spec)
        # Assemble budget once so the plan dataset execute workflow shares one value.
        budget = _build_budget_report(
            request,
            estimate,
            free_disk_bytes,
            limits=effective_budget,
            # Pass policy explicitly so _build_budget_report receives a reviewable policy
            # and request input in plan dataset execute.
            policy=self._policy,
            requested_blocks=requested_blocks,
            planned_shards=shard_count,
            effective_shard_blocks=effective_shard_blocks,
        )
        # Guard this path with budget.rejected before applying effects.
        if budget.rejected:
            raise BudgetExceededError(budget)
        return DatasetPlan(spec=spec, budget=budget, query_limits=effective_query)


def _group_requirements(
    requirements: tuple[DataRequirement, ...],
    # Keep the tuple input explicit in the group requirements contract.
) -> tuple[tuple[CapabilityId, tuple[DataRequirement, ...]], ...]:
    # Execute the group requirements workflow in explicit, reviewable steps.
    grouped: defaultdict[CapabilityId, list[DataRequirement]] = defaultdict(list)
    for requirement in requirements:
        grouped[requirement.capability_id].append(requirement)
    return tuple(
        (
            # Pass capability id explicitly so tuple receives a reviewable items and value
            # input in group requirements.
            capability_id,
            tuple(
                sorted(
                    items,
                    key=lambda item: (
                        # Pass item explicitly so sorted receives a reviewable value and
                        # origin id input in group requirements.
                        item.origin.value,
                        item.origin_id,
                        item.columns,
                        item.accepted_protocol_versions,
                    ),
                    # Complete sorted only after its value and origin id inputs are visible in
                    # group requirements.
                )
            ),
        )
        for capability_id, items in sorted(
            grouped.items(),
            # Pass key explicitly so sorted receives a reviewable items and value input in
            # group requirements.
            key=lambda item: item[0].value,
        )
    )


def _required_range(
    request: PlanDatasetRequest,
    # Keep the requirements input explicit in the required range contract.
    requirements: tuple[DataRequirement, ...],
    *,
    include_declared_settlement_tail: bool = True,
    automatic_settlement_tail_blocks: int = 0,
) -> BlockRange:
    # Execute the required range workflow in explicit, reviewable steps.
    warmup_blocks = max(
        request.warmup_blocks,
        *(item.warmup_blocks for item in requirements),
    )
    settlement_tail_blocks = automatic_settlement_tail_blocks
    # Guard this path with include_declared_settlement_tail before applying effects.
    if include_declared_settlement_tail:
        # Handle the required range include_declared_settlement_tail branch as a distinct
        # logical block.
        settlement_tail_blocks = max(
            settlement_tail_blocks,
            request.settlement_tail_blocks,
            *(item.settlement_tail_blocks for item in requirements),
        )
    # Return the completed required range result without a hidden fallback.
    return BlockRange(
        request.network_id,
        request.position_schema_id,
        max(0, request.decision_range.from_block_ordinal - warmup_blocks),
        request.decision_range.to_block_ordinal + settlement_tail_blocks,
        # Complete BlockRange only after its network id and position schema id inputs are
        # visible in required range.
    )


def _combine_settlement_requirements(
    requirements: tuple[DataRequirement, ...],
) -> SettlementRequirement | CopyBuySettlementRequirement | None:
    # Execute the combine settlement requirements workflow in explicit, reviewable steps.
    declared = tuple(
        item.settlement_requirement
        for item in requirements
        if item.settlement_requirement is not None
    )
    # Guard this path with not declared before applying effects.
    if not declared:
        return None
    try:
        # A copy dataset binds one explicit path; incompatible strategy families cannot merge.
        first = declared[0]
        if isinstance(first, CopyBuySettlementRequirement):
            if any(item != first for item in declared):
                raise ValueError("conflicting copy settlement paths")
            return first
        # Other strategy families retain their own settlement-merging rules.
        legacy = tuple(item for item in declared if isinstance(item, SettlementRequirement))
        # Preserve the existing conservative merge only for the legacy family.
        if len(legacy) != len(declared):
            raise ValueError("mixed settlement contract families")
        return SettlementRequirement.combine(legacy)
    except ValueError as error:
        # Translate the ValueError failure through the combine settlement requirements
        # boundary.
        fallback_id = min(requirements, key=lambda item: item.capability_id.value).capability_id
        raise SourceEvidenceMismatchError(
            fallback_id,
            ("settlement_contract_conflict",),
        ) from error


# Define settlement tail guard as one focused operation with an explicit boundary.
def _settlement_tail_guard(
    request: PlanDatasetRequest,
    *,
    settlement_requirement: SettlementRequirement | CopyBuySettlementRequirement | None,
) -> int:
    # Execute the settlement tail guard workflow in explicit, reviewable steps.
    declared = max(
        request.settlement_tail_blocks,
        *(item.settlement_tail_blocks for item in request.requirements),
    )
    if settlement_requirement is None:
        # Return the completed settlement tail guard result without a hidden fallback.
        return declared
    if declared > settlement_requirement.maximum_tail_blocks:
        # Handle the settlement tail guard declared, maximum tail blocks and settlement
        # requirement condition as a distinct block.
        fallback_id = min(
            request.requirements,
            key=lambda item: item.capability_id.value,
        ).capability_id
        raise SourceEvidenceMismatchError(
            # Pass fallback id explicitly so SourceEvidenceMismatchError receives a
            # reviewable settlement tail limit exceeded and fallback id input in
            # settlement tail guard.
            fallback_id,
            ("settlement_tail_limit_exceeded",),
        )
    # The current planner performs one bounded extraction instead of repeatedly
    # reopening the remote source.  Sufficiency is not assumed here: the
    # candidate snapshot validator proves each target's actual settlement path.
    return settlement_requirement.maximum_tail_blocks


def _selected_stream(
    capability_id: CapabilityId,
    requirements: tuple[DataRequirement, ...],
    available: tuple[CapabilityDescriptor, ...],
    # Keep the capability stream input explicit in the selected stream contract.
) -> CapabilityStream | None:
    # Execute the selected stream workflow in explicit, reviewable steps.
    compatible = tuple(
        descriptor
        for descriptor in available
        if descriptor.capability_id == capability_id
        and all(
            # Pass requirement explicitly so all receives a reviewable accepted protocol
            # versions and protocol version input in selected stream.
            not requirement.accepted_protocol_versions
            or descriptor.protocol_version in requirement.accepted_protocol_versions
            for requirement in requirements
        )
    )
    # Guard this path with len(compatible) != 1 before applying effects.
    if len(compatible) != 1:
        return None
    return compatible[0].stream


def _resolve_capability(
    capability_id: CapabilityId,
    # Keep the requirements input explicit in the resolve capability contract.
    requirements: tuple[DataRequirement, ...],
    available: tuple[CapabilityDescriptor, ...],
    *,
    evidence: CapabilityCutEvidence | None,
    requested_range: BlockRange,
    # Keep the planned capability input explicit in the resolve capability contract.
) -> PlannedCapability:
    # Execute the resolve capability workflow in explicit, reviewable steps.
    candidates = tuple(
        descriptor for descriptor in available if descriptor.capability_id == capability_id
    )
    if not candidates:
        raise CapabilityNotFoundError(capability_id)

    # Assemble compatible once so the resolve capability workflow shares one value.
    compatible = tuple(
        descriptor
        for descriptor in candidates
        if all(
            not requirement.accepted_protocol_versions
            # Pass descriptor explicitly so all receives a reviewable accepted protocol
            # versions and protocol version input in resolve capability.
            or descriptor.protocol_version in requirement.accepted_protocol_versions
            for requirement in requirements
        )
    )
    if not compatible:
        # Handle the resolve capability not compatible branch as a distinct logical block.
        accepted = tuple(
            sorted(
                {
                    version
                    for requirement in requirements
                    # Pass version explicitly so sorted receives a reviewable accepted
                    # protocol versions and version input in resolve capability.
                    for version in requirement.accepted_protocol_versions
                }
            )
        )
        raise ProtocolVersionMismatchError(capability_id, accepted)
    # Guard this path with len(compatible) > 1 before applying effects.
    if len(compatible) > 1:
        raise CapabilityAmbiguousError(capability_id)

    descriptor = compatible[0]
    requested_columns = tuple(
        sorted(
            # Keep the mandatory columns set step visible while building requested
            # columns.
            set(descriptor.mandatory_columns).union(
                *(set(requirement.columns) for requirement in requirements)
            )
        )
    )
    # Assemble missing once so the resolve capability workflow shares one value.
    missing = tuple(sorted(set(requested_columns) - set(descriptor.columns)))
    if missing:
        raise RequiredColumnMissingError(capability_id, missing)

    fidelity_requirement = FidelityRequirement.combine(
        tuple(requirement.minimum_fidelity for requirement in requirements)
        # Complete combine only after its minimum fidelity and tuple inputs are visible in
        # resolve capability.
    )
    effective_fidelity = _effective_fidelity(
        descriptor.fidelity,
        evidence,
        requested_range=requested_range,
        # Complete _effective_fidelity only after its fidelity and descriptor inputs are
        # visible in resolve capability.
    )
    gaps = effective_fidelity.gaps(fidelity_requirement)
    if gaps:
        raise FidelityMismatchError(capability_id, gaps)

    return PlannedCapability(
        # Pass capability id explicitly so PlannedCapability receives a reviewable
        # capability id and protocol input in resolve capability.
        capability_id=descriptor.capability_id,
        protocol=descriptor.protocol,
        protocol_version=descriptor.protocol_version,
        schema_version=descriptor.schema_version,
        stream=descriptor.stream,
        # Pass columns explicitly so PlannedCapability receives a reviewable capability id
        # and protocol input in resolve capability.
        columns=requested_columns,
        fidelity=effective_fidelity,
        proofs=descriptor.proofs,
        total_key=descriptor.total_key,
        keyset_key_is_proven=descriptor.keyset_key_is_proven,
        # Pass utc pruning column explicitly so PlannedCapability receives a reviewable
        # capability id and protocol input in resolve capability.
        utc_pruning_column=descriptor.utc_pruning_column,
        utc_pruning_is_proven=descriptor.utc_pruning_is_proven,
    )


def _effective_fidelity(
    advertised: SourceFidelity,
    # Keep the evidence input explicit in the effective fidelity contract.
    evidence: CapabilityCutEvidence | None,
    *,
    requested_range: BlockRange,
) -> SourceFidelity:
    # Execute the effective fidelity workflow in explicit, reviewable steps.
    if evidence is None or (
        evidence.block_range.network_id != requested_range.network_id
        or evidence.block_range.position_schema_id != requested_range.position_schema_id
        or evidence.block_range.from_block_ordinal > requested_range.from_block_ordinal
        or evidence.snapshot_cut_to_block < requested_range.to_block_ordinal
        # Evaluate the complete effective fidelity evidence, network id and position schema id
        # condition before guarded effects.
    ):
        # Handle the effective fidelity evidence, network id and position schema id
        # condition as a distinct block.
        proven_finality = ChainFinality.UNKNOWN
        proven_completeness = IngestionCompleteness.UNKNOWN
        proven_consistency = SourceConsistency.UNKNOWN
    else:
        # Handle the effective fidelity complement of evidence, network id and position
        # schema id explicitly.
        proven_finality = evidence.chain_finality
        if evidence.completeness is IngestionCompleteness.COMPLETE_TO_WATERMARK and (
            evidence.ingestion_watermark_to_block is None
            or evidence.ingestion_watermark_to_block < requested_range.to_block_ordinal
        ):
            # Assemble proven completeness once so the effective fidelity workflow shares
            # one value.
            proven_completeness = IngestionCompleteness.UNKNOWN
        else:
            proven_completeness = evidence.completeness
        proven_consistency = evidence.consistency

    return SourceFidelity(
        # Pass identity explicitly so SourceFidelity receives a reviewable identity and
        # ordering input in effective fidelity.
        identity=advertised.identity,
        ordering=advertised.ordering,
        state=advertised.state,
        fees=advertised.fees,
        chain_finality=min(
            # Pass advertised explicitly so min receives a reviewable chain finality and
            # index input in effective fidelity.
            advertised.chain_finality,
            proven_finality,
            key=tuple(ChainFinality).index,
        ),
        completeness=min(
            # Pass advertised explicitly so min receives a reviewable completeness and
            # index input in effective fidelity.
            advertised.completeness,
            proven_completeness,
            key=tuple(IngestionCompleteness).index,
        ),
        consistency=min(
            # Pass advertised explicitly so min receives a reviewable consistency and
            # index input in effective fidelity.
            advertised.consistency,
            proven_consistency,
            key=tuple(SourceConsistency).index,
        ),
    )


# Define build budget report as one focused operation with an explicit boundary.
def _build_budget_report(
    request: PlanDatasetRequest,
    estimate: SourceEstimate,
    free_disk_bytes: int | None,
    *,
    # Keep the limits input explicit in the build budget report contract.
    limits: BudgetLimits,
    policy: DatasetPlanningPolicy,
    requested_blocks: int,
    planned_shards: int,
    effective_shard_blocks: int,
    # Keep the budget report input explicit in the build budget report contract.
) -> BudgetReport:
    # Execute the build budget report workflow in explicit, reviewable steps.
    issues: list[BudgetIssue] = []

    _check_limit(
        issues,
        code="REQUESTED_DAYS",
        actual=request.requested_days,
        # Pass limit explicitly so _check_limit receives a reviewable requested days and
        # requested day count input in build budget report.
        limit=limits.max_days,
        label="requested day count",
    )
    _check_limit(
        issues,
        # Pass code explicitly so _check_limit receives a reviewable total blocks and
        # requested extraction block span input in build budget report.
        code="TOTAL_BLOCKS",
        actual=requested_blocks,
        limit=policy.max_total_blocks,
        label="requested extraction block span",
    )
    # Invoke _check_limit for total shards and planned shard count as a visible build
    # budget report step.
    _check_limit(
        issues,
        code="TOTAL_SHARDS",
        actual=planned_shards,
        limit=policy.max_total_shards,
        # Pass label explicitly so _check_limit receives a reviewable total shards and
        # planned shard count input in build budget report.
        label="planned shard count",
    )
    _check_limit(
        issues,
        code="REMOTE_BYTES",
        # Pass actual explicitly so _check_limit receives a reviewable remote bytes and
        # estimated source bytes input in build budget report.
        actual=estimate.estimated_source_bytes,
        limit=limits.max_remote_bytes,
        label="estimated source bytes",
    )
    _check_limit(
        # Pass issues explicitly so _check_limit receives a reviewable local bytes and
        # expected local parquet bytes input in build budget report.
        issues,
        code="LOCAL_BYTES",
        actual=estimate.expected_local_parquet_bytes,
        limit=limits.max_local_bytes,
        label="expected local Parquet bytes",
        # Complete _check_limit only after its local bytes and expected local parquet bytes
        # inputs are visible in build budget report.
    )

    known_spill_bytes = estimate.temporary_spill_bytes or 0
    temporary_reserve = limits.temporary_reserve_bytes + known_spill_bytes
    known_local_bytes = estimate.expected_local_parquet_bytes or 0
    known_required_disk = known_local_bytes + temporary_reserve + limits.disk_low_watermark_bytes
    # Guard this path with free_disk_bytes is None before applying effects.
    if free_disk_bytes is None:
        # Handle the build budget report free_disk_bytes is None branch as a distinct
        # logical block.
        issues.append(
            BudgetIssue(
                code="FREE_DISK",
                kind=BudgetIssueKind.UNKNOWN,
                message="current free disk is unknown",
                # Complete BudgetIssue only after its free disk and current free disk is
                # unknown inputs are visible in build budget report.
            )
        )
    else:
        # Handle the build budget report complement of free_disk_bytes is None explicitly.
        if free_disk_bytes < known_required_disk:
            # Handle the build budget report free_disk_bytes < known_required_disk branch
            # as a distinct logical block.
            issues.append(
                BudgetIssue(
                    code="FREE_DISK_LOWER_BOUND",
                    kind=BudgetIssueKind.LIMIT_EXCEEDED,
                    message="free disk is below the safe known lower bound",
                    # Pass actual explicitly so BudgetIssue receives a reviewable free
                    # disk lower bound and free disk is below the safe known lower bound
                    # input in build budget report.
                    actual=free_disk_bytes,
                    limit=known_required_disk,
                )
            )
    if free_disk_bytes is not None and (
        # Keep estimate visible while evaluating the free disk bytes, expected local
        # parquet bytes and temporary spill bytes guard.
        estimate.expected_local_parquet_bytes is None or estimate.temporary_spill_bytes is None
    ):
        # Handle the build budget report free disk bytes, expected local parquet bytes and
        # temporary spill bytes condition as a distinct block.
        issues.append(
            BudgetIssue(
                code="DISK_REQUIREMENT",
                kind=BudgetIssueKind.UNKNOWN,
                message="required local disk is unknown",
                # Pass actual explicitly so BudgetIssue receives a reviewable disk
                # requirement and required local disk is unknown input in build budget
                # report.
                actual=free_disk_bytes,
            )
        )
    # Handle the build budget report complement of free disk bytes, expected local parquet
    # bytes and temporary spill bytes explicitly.
    elif free_disk_bytes is not None:
        # Handle the build budget report free_disk_bytes is not None branch as a distinct
        # logical block.
        expected_local_bytes = estimate.expected_local_parquet_bytes
        if expected_local_bytes is None:
            raise AssertionError("known disk branch has no local byte estimate")
        required = expected_local_bytes + temporary_reserve + limits.disk_low_watermark_bytes
        if free_disk_bytes < required and not any(
            # Pass code explicitly so any receives a reviewable free disk lower bound and
            # code input in build budget report.
            issue.code == "FREE_DISK_LOWER_BOUND"
            for issue in issues
        ):
            # Handle the build budget report free disk bytes, required and code condition
            # as a distinct block.
            issues.append(
                BudgetIssue(
                    code="FREE_DISK",
                    kind=BudgetIssueKind.LIMIT_EXCEEDED,
                    message="free disk would fall below the configured low watermark",
                    # Pass actual explicitly so BudgetIssue receives a reviewable free
                    # disk and free disk would fall below the configured low watermark
                    # input in build budget report.
                    actual=free_disk_bytes,
                    limit=required,
                )
            )

    if any(issue.kind is BudgetIssueKind.LIMIT_EXCEEDED for issue in issues):
        # Assemble status once so the build budget report workflow shares one value.
        status = BudgetStatus.REJECTED
    # Handle the build budget report complement of kind, limit exceeded and issue
    # explicitly.
    elif issues:
        status = BudgetStatus.UNKNOWN
    else:
        status = BudgetStatus.PASS

    return BudgetReport(
        # Pass status explicitly so BudgetReport receives a reviewable estimated source
        # rows and estimated source bytes input in build budget report.
        status=status,
        estimated_source_rows=estimate.estimated_source_rows,
        estimated_source_bytes=estimate.estimated_source_bytes,
        requested_days=request.requested_days,
        requested_blocks=requested_blocks,
        # Pass planned shards explicitly so BudgetReport receives a reviewable estimated
        # source rows and estimated source bytes input in build budget report.
        planned_shards=planned_shards,
        expected_local_parquet_bytes=estimate.expected_local_parquet_bytes,
        temporary_reserve_bytes=temporary_reserve,
        current_free_disk_bytes=free_disk_bytes,
        disk_low_watermark_bytes=limits.disk_low_watermark_bytes,
        # Pass max remote bytes explicitly so BudgetReport receives a reviewable estimated
        # source rows and estimated source bytes input in build budget report.
        max_remote_bytes=limits.max_remote_bytes,
        max_local_bytes=limits.max_local_bytes,
        max_days=limits.max_days,
        max_total_blocks=policy.max_total_blocks,
        max_total_shards=policy.max_total_shards,
        # Pass max shard blocks explicitly so BudgetReport receives a reviewable estimated
        # source rows and estimated source bytes input in build budget report.
        max_shard_blocks=effective_shard_blocks,
        issues=tuple(issues),
    )


def _check_limit(
    issues: list[BudgetIssue],
    # Close the check limit signature after its explicit inputs.
    *,
    code: str,
    actual: int | None,
    limit: int,
    label: str,
    # Close the check limit signature after its explicit inputs.
) -> None:
    # Execute the check limit workflow in explicit, reviewable steps.
    if actual is None:
        # Handle the check limit actual is None branch as a distinct logical block.
        issues.append(
            BudgetIssue(
                code=code,
                kind=BudgetIssueKind.UNKNOWN,
                message=f"{label} is unknown",
                # Pass limit explicitly so BudgetIssue receives a reviewable is unknown
                # and unknown input in check limit.
                limit=limit,
            )
        )
    # Handle the check limit complement of actual is None explicitly.
    elif actual > limit:
        # Handle the check limit actual > limit branch as a distinct logical block.
        issues.append(
            BudgetIssue(
                code=code,
                kind=BudgetIssueKind.LIMIT_EXCEEDED,
                message=f"{label} exceeds its hard limit",
                # Pass actual explicitly so BudgetIssue receives a reviewable exceeds its
                # hard limit and limit exceeded input in check limit.
                actual=actual,
                limit=limit,
            )
        )


__all__ = ["PlanDataset"]
