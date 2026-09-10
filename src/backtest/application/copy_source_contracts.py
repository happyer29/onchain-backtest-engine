"""Fail-closed admission of independently enumerated copy-buy histories."""

from typing import NoReturn

from backtest.application.copy_source import COPYBUY_SOURCE_CONTRACT
from backtest.application.errors import SourceEvidenceMismatchError
from backtest.application.models import (
    # The copy receipt and settlement types cannot be replaced by old Sniping versions.
    COPYBUY_SOURCE_EVIDENCE_SCHEMA,
    BoundedSourceEvidenceReceipt,
    CapabilityStream,
    CopyBuySettlementRequirement,
    DatasetSpec,
    # Dataset and inspection contracts preserve exact capability and source identities.
    PlannedCapability,
    SourceMetadata,
)

# The shared proof vocabulary does not imply shared strategy or settlement semantics.
from backtest.application.source_contracts import (
    _REQUIRED_COLUMNS,
    _REQUIRED_PROOFS,
    _append_fidelity_failures,
    _unique_streams,
    # Fidelity checks reuse shared proofs without upgrading unknown source claims.
)
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
    PumpfunCopyBuySourceEvidenceBinding,
    # Content-addressed receipt references bind the four streams to one source cut.
    SourceEvidenceReceiptRef,
)

# Receipt claims must agree with the exact prepared range and authoritative source cut.
from backtest.domain.fidelity import IngestionCompleteness, SourceConsistency
from backtest.domain.identifiers import CapabilityId
from backtest.domain.time import BlockRange


def resolve_copy_source_binding(
    metadata: SourceMetadata,
    capabilities: tuple[PlannedCapability, ...],
    decision: BlockRange,
) -> PumpfunCopyBuySourceEvidenceBinding:
    """Only generated v3 receipts can admit a copy source; static proof claims cannot."""
    fallback = min(capabilities, key=lambda item: item.capability_id.value).capability_id
    streams = _unique_streams(capabilities, fallback_id=fallback)
    mapping, query = metadata.capability_mapping_digest, metadata.query_template_digest
    if mapping is None or query is None:
        _reject(fallback, "copy_mapping_query_binding")
    # Resolve each exact capability version without aliases or alternative sources.
    selected: dict[CapabilityStream, BoundedSourceEvidenceReceipt] = {}
    for stream, capability in streams.items():
        matches = tuple(
            receipt
            for receipt in metadata.evidence_receipts
            # A receipt is selected by the entire versioned capability tuple, not a name alone.
            if (receipt.capability_id, receipt.protocol_version, receipt.capability_schema_version)
            == (capability.capability_id, capability.protocol_version, capability.schema_version)
        )
        # One and only one exact receipt is authoritative for each stream.
        if len(matches) != 1:
            _reject(capability.capability_id, "copy_bounded_query_provenance")
        receipt = matches[0]
        coverage = receipt.copy_coverage
        # Signer coverage is mandatory in the new copy-only receipt schema.
        if receipt.schema != COPYBUY_SOURCE_EVIDENCE_SCHEMA or coverage is None:
            _reject(capability.capability_id, "copy_coverage_required")
        # Receipt construction already verifies its own ID; bind it to this inspection too.
        if (
            receipt.source_id,
            receipt.capability_mapping_digest,
            receipt.query_template_digest,
        ) != (
            # The inspected source and physical mapping must match the receipt operands exactly.
            metadata.source_id,
            mapping,
            query,
        ):
            _reject(capability.capability_id, "copy_inspection_binding")
        # A proof for another decision range cannot authorize this copy selection.
        if receipt.decision_range != decision or receipt.proofs != capability.proofs:
            _reject(capability.capability_id, "copy_proof_range_binding")
        # A caller cannot promote fidelity separately from the evaluated source proof.
        if receipt.source_fidelity != capability.fidelity or receipt.launch_universe is not None:
            _reject(capability.capability_id, "copy_fidelity_binding")
        if (receipt.skipped_slot_sentinel is not None) != (stream is CapabilityStream.BLOCK_CLOCK):
            _reject(capability.capability_id, "copy_sentinel_placement")
        # Lifecycle ordering evidence belongs exclusively to the lifecycle capability.
        if (receipt.terminal_lifecycle_ordering is not None) != (
            stream is CapabilityStream.PUMP_CURVE_LIFECYCLE
        ):
            _reject(capability.capability_id, "copy_lifecycle_placement")
        selected[stream] = receipt
    # Cross-stream consistency uses a receipt only after every required stream is present.
    first = next(iter(selected.values()))
    coverage = first.copy_coverage
    # All streams must have been checked together with identical transform operands.
    for receipt in selected.values():
        if (
            receipt.projector_digest,
            receipt.normalizer_digest,
            receipt.copy_coverage,
            # All streams must describe the same bounded read and query fingerprint set.
            receipt.result_digest,
            receipt.query_fingerprints,
        ) != (
            first.projector_digest,
            first.normalizer_digest,
            # No stream may silently substitute another wallet selection or result digest.
            coverage,
            first.result_digest,
            first.query_fingerprints,
        ):
            _reject(fallback, "copy_cross_stream_proof_binding")
    # Clock sentinel and terminal lifecycle evidence have separate authoritative streams.
    sentinel = selected[CapabilityStream.BLOCK_CLOCK].skipped_slot_sentinel
    lifecycle = selected[CapabilityStream.PUMP_CURVE_LIFECYCLE].terminal_lifecycle_ordering
    if coverage is None or sentinel is None or lifecycle is None:
        _reject(fallback, "copy_incomplete_binding")
    # The closed profiles retain skipped-slot and same-transaction ordering semantics.
    if sentinel.profile_id != SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID:
        _reject(fallback, "copy_sentinel_profile")
    if lifecycle.profile_id != PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID:
        _reject(fallback, "copy_lifecycle_profile")
    # Versioned normalization policies become immutable dataset dependencies.
    return PumpfunCopyBuySourceEvidenceBinding(
        receipt_refs=tuple(
            sorted(
                (
                    SourceEvidenceReceiptRef(item.capability_id, item.receipt_id)
                    # Receipt ordering is canonical regardless of inspection response order.
                    for item in selected.values()
                ),
                key=lambda ref: ref.capability_id.value,
            )
        ),
        # Exact content operands persist into DatasetSpec and snapshot-root validation.
        capability_mapping_digest=mapping,
        query_template_digest=query,
        projector_digest=first.projector_digest,
        normalizer_digest=first.normalizer_digest,
        copy_coverage=coverage,
        # Skipped-slot and atomic migration policies remain explicit parts of source identity.
        skipped_slot_sentinel=sentinel,
        terminal_lifecycle_ordering=lifecycle,
    )


def require_copy_source_contract(spec: DatasetSpec) -> None:
    """Check exact clock, signer, initialization and settlement coverage before replay."""
    fallback = min(spec.capabilities, key=lambda item: item.capability_id.value).capability_id
    binding, requirement, tail = (
        spec.source_evidence_binding,
        spec.settlement_requirement,
        spec.settlement_tail,
        # Copy artifacts have a schema boundary because signer and settlement semantics differ.
    )
    if spec.spec_version != 6 or COPYBUY_SOURCE_CONTRACT not in spec.evidence_contracts:
        _reject(fallback, "copy_dataset_version")
    # The target trade stream also settles positions, under its separate typed contract.
    if not isinstance(binding, PumpfunCopyBuySourceEvidenceBinding):
        _reject(fallback, "copy_source_binding")
    if not isinstance(requirement, CopyBuySettlementRequirement) or tail is None:
        _reject(fallback, "copy_settlement_contract")
    selection = binding.copy_coverage.selection
    # Run decisions must stay inside the exact signer-coverage selection.
    if selection.decision_range != spec.decision_range:
        _reject(fallback, "copy_decision_binding")
    # Dataset identity validates transform digests; range coverage is checked independently.
    streams = _unique_streams(spec.capabilities, fallback_id=fallback)
    ranges = {item.capability_id: item.block_range for item in spec.capability_ranges}
    cuts = {item.capability_id: item for item in spec.cut_evidence}
    for stream, capability in streams.items():
        missing = list(capability.proofs.require_proven(_REQUIRED_PROOFS[stream]))
        # Source fidelity is checked independently of required column presence.
        _append_fidelity_failures(stream, capability, missing)
        # Actor-bearing trades retain every existing exact reserve and fee requirement.
        columns = _REQUIRED_COLUMNS[stream]
        if stream is CapabilityStream.PUMP_CURVE_TRADE:
            columns = columns | {"signing_wallet"}
        if not columns.issubset(capability.columns):
            missing.append("copy_required_columns")
        # A similarly named capability from another protocol cannot satisfy this contract.
        if capability.protocol != (
            "solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun"
        ):
            missing.append("copy_protocol_family")
        # Every stream starts at the explicit initialization frontier; only launch stops early.
        wanted_end = (
            selection.history_range.to_block_ordinal
            if stream is CapabilityStream.TOKEN_LAUNCH
            else tail.to_block_ordinal
        )
        # Launch initialization ends before the non-target settlement extension.
        actual = ranges[capability.capability_id]
        if (actual.from_block_ordinal, actual.to_block_ordinal) != (
            selection.history_range.from_block_ordinal,
            wanted_end,
        ):
            # Every market stream must cover the whole initial state and four-attempt tail.
            missing.append("copy_initialization_settlement_range")
        # Proven source coverage cannot jump a missing range or incomplete watermark.
        cut = cuts.get(capability.capability_id)
        if cut is None:
            missing.append("copy_bounded_cut")
        elif (
            cut.block_range.from_block_ordinal != actual.from_block_ordinal
            # The source watermark must close the same hard extraction cap as the snapshot cut.
            or cut.snapshot_cut_to_block != tail.to_block_ordinal
            or cut.ingestion_watermark_to_block != tail.to_block_ordinal
        ):
            missing.append("copy_complete_cut")
        # The new strategy does not relax source consistency or completeness fidelity.
        if cut is not None and (
            cut.completeness is not IngestionCompleteness.COMPLETE_TO_WATERMARK
            or cut.consistency is not SourceConsistency.SNAPSHOT_CONSISTENT
        ):
            missing.append("copy_cut_fidelity")
        # Report every failed proof together while preserving typed fail-closed behavior.
        if missing:
            raise SourceEvidenceMismatchError(capability.capability_id, tuple(sorted(set(missing))))
    if len({(cut.snapshot_cut_to_block, cut.upstream_revision) for cut in cuts.values()}) != 1:
        _reject(fallback, "copy_consistent_source_cut")


def require_copy_inspection_receipts(metadata: SourceMetadata, spec: DatasetSpec) -> None:
    """Match a resolved plan to the exact inspection and its immutable receipt contents."""
    fallback = min(spec.capabilities, key=lambda item: item.capability_id.value).capability_id
    binding = resolve_copy_source_binding(metadata, spec.capabilities, spec.decision_range)
    if metadata.source_id != spec.source_id or spec.source_evidence_binding != binding:
        _reject(fallback, "copy_inspection_binding")
    cuts = {receipt.capability_id: receipt.cut_evidence for receipt in metadata.evidence_receipts}
    # Exact cut equality rejects a substituted watermark even if every ID string looks valid.
    if any(cuts.get(cut.capability_id) != cut for cut in spec.cut_evidence):
        _reject(fallback, "copy_receipt_cut_binding")
    require_copy_source_contract(spec)


def _reject(capability: CapabilityId, reason: str) -> NoReturn:
    """Keep source errors typed and free of raw rows, endpoints and driver exceptions."""
    raise SourceEvidenceMismatchError(capability, (reason,))
