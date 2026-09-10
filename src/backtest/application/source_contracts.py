"""Pure fail-closed validation of cross-capability source contracts."""

from __future__ import annotations

from backtest.application.errors import SourceEvidenceMismatchError
from backtest.application.models import (
    PUMPFUN_SNIPING_SOURCE_CONTRACT,
    SETTLEMENT_REQUIREMENT_SCHEMA,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityStream,
    DatasetSpec,
    PlannedCapability,
    SettlementRequirement,
    # Include source metadata so the models dependency remains explicit.
    SourceMetadata,
)
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS,
    PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS,
    PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
    # Close the sniping run contract import after its required symbols are visible.
)
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
    PumpfunSnipingSourceEvidenceBinding,
    SourceEvidenceReceiptRef,
)
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    StateFidelity,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import CapabilityId
from backtest.domain.time import BlockRange

_REQUIRED_PROOFS: dict[CapabilityStream, tuple[str, ...]] = {
    CapabilityStream.BLOCK_CLOCK: (
        "successful_transactions_included",
        "failed_transactions_included",
        # Keep the vote transactions included component named inside the required proofs
        # contract.
        "vote_transactions_included",
        "skipped_blocks_distinguished",
        "block_time_second_resolution",
        "block_time_monotone",
    ),
    # Keep the capability stream component named inside the required proofs contract.
    CapabilityStream.TOKEN_LAUNCH: (
        "global_zero_based_transaction_index",
        "creation_fields_immutable",
        "bundled_instruction_order",
        "launch_transaction_success_exact",
        # Complete the required proofs group only after its semantic components are visible.
    ),
    CapabilityStream.PUMP_CURVE_TRADE: (
        "global_zero_based_transaction_index",
        "curve_transitions_complete",
        "fee_component_rounding_exact",
        # Complete the required proofs group only after its semantic components are visible.
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: (
        "global_zero_based_transaction_index",
        "lifecycle_complete",
    ),
    # Complete the required proofs group only after its semantic components are visible.
}

_REQUIRED_COLUMNS: dict[CapabilityStream, frozenset[str]] = {
    CapabilityStream.BLOCK_CLOCK: frozenset(
        {"block_ordinal", "block_time", "transaction_count", "block_hash"}
    ),
    # Register frozenset and block ordinal through frozenset so the required columns table
    # remains scannable.
    CapabilityStream.TOKEN_LAUNCH: frozenset(
        {
            "block_ordinal",
            "transaction_index",
            "event_index",
            # Pass signature explicitly so frozenset receives a reviewable block ordinal
            # and transaction index input in module.
            "signature",
            "transaction_succeeded",
            "mint",
            "creator",
            "creation_user",
            # Pass venue explicitly so frozenset receives a reviewable block ordinal and
            # transaction index input in module.
            "venue",
            "quote_asset",
            "virtual_token_reserves_atomic",
            "virtual_sol_reserves_lamports",
            "real_token_reserves_atomic",
            # Pass real sol reserves lamports explicitly so frozenset receives a
            # reviewable block ordinal and transaction index input in module.
            "real_sol_reserves_lamports",
            "token_total_supply_atomic",
            "lifecycle",
            "mode",
        }
        # Complete frozenset only after its block ordinal and transaction index inputs are
        # visible in module.
    ),
    CapabilityStream.PUMP_CURVE_TRADE: frozenset(
        {
            "block_ordinal",
            "transaction_index",
            # Pass event index explicitly so frozenset receives a reviewable block ordinal
            # and transaction index input in module.
            "event_index",
            "signature",
            "mint",
            "venue",
            "quote_asset",
            # Pass side explicitly so frozenset receives a reviewable block ordinal and
            # transaction index input in module.
            "side",
            "base_amount_atomic",
            "quote_amount_atomic",
            "virtual_token_reserves_atomic",
            "virtual_sol_reserves_lamports",
            # Pass real token reserves atomic explicitly so frozenset receives a
            # reviewable block ordinal and transaction index input in module.
            "real_token_reserves_atomic",
            "real_sol_reserves_lamports",
            "token_total_supply_atomic",
            "protocol_fee_atomic",
            "creator_fee_atomic",
            # Pass mode explicitly so frozenset receives a reviewable block ordinal and
            # transaction index input in module.
            "mode",
            "lifecycle",
        }
    ),
    CapabilityStream.PUMP_CURVE_LIFECYCLE: frozenset(
        # Open the block ordinal and transaction index payload explicitly for frozenset
        # within module.
        {
            "block_ordinal",
            "transaction_index",
            "event_index",
            "signature",
            # Pass mint explicitly so frozenset receives a reviewable block ordinal and
            # transaction index input in module.
            "mint",
            "venue",
            "lifecycle_kind",
            "virtual_token_reserves_atomic",
            "virtual_sol_reserves_lamports",
            # Pass real token reserves atomic explicitly so frozenset receives a
            # reviewable block ordinal and transaction index input in module.
            "real_token_reserves_atomic",
            "real_sol_reserves_lamports",
            "token_total_supply_atomic",
            "lifecycle",
            "mode",
            # Close the block ordinal and transaction index payload only after all module
            # fields are present.
        }
    ),
}

_PUMPFUN_SETTLEMENT_STREAMS = tuple(
    sorted(
        # Open the block clock and pump curve trade payload explicitly for sorted within
        # module.
        (
            CapabilityStream.BLOCK_CLOCK,
            CapabilityStream.PUMP_CURVE_TRADE,
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
        ),
        # Pass key explicitly so sorted receives a reviewable block clock and pump curve
        # trade input in module.
        key=lambda item: item.value,
    )
)


def pumpfun_sniping_settlement_requirement(
    *,
    # Keep the maximum sell delay transactions input explicit in the pumpfun sniping
    # settlement requirement contract.
    maximum_sell_delay_transactions: int,
    maximum_tail_blocks: int,
) -> SettlementRequirement:
    """Build the exact Pump v1 causal requirement with a bounded tail guard."""

    return SettlementRequirement(
        schema=SETTLEMENT_REQUIREMENT_SCHEMA,
        target_stream=CapabilityStream.TOKEN_LAUNCH,
        settlement_streams=_PUMPFUN_SETTLEMENT_STREAMS,
        initial_delay_transactions=PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS,
        # Pass minimum duration ns explicitly so SettlementRequirement receives a
        # reviewable token launch and settlement requirement schema input in pumpfun
        # sniping settlement requirement.
        minimum_duration_ns=PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS * 1_000_000_000,
        maximum_followup_delay_transactions=maximum_sell_delay_transactions,
        maximum_tail_blocks=maximum_tail_blocks,
    )


def resolve_pumpfun_sniping_source_evidence_binding(
    metadata: SourceMetadata,
    capabilities: tuple[PlannedCapability, ...],
    decision_range: BlockRange,
) -> PumpfunSnipingSourceEvidenceBinding:
    """Resolve the complete, content-addressed live evidence dependency."""

    if not capabilities:
        raise ValueError("capabilities must not be empty")
    fallback_id = min(capabilities, key=lambda item: item.capability_id.value).capability_id
    by_stream = _unique_streams(capabilities, fallback_id=fallback_id)
    mapping_digest = metadata.capability_mapping_digest
    query_digest = metadata.query_template_digest
    if mapping_digest is None or query_digest is None:
        raise SourceEvidenceMismatchError(fallback_id, ("inspection_binding",))

    receipts_by_key = {
        (item.capability_id, item.protocol_version, item.capability_schema_version): item
        for item in metadata.evidence_receipts
    }
    selected = []
    for stream, capability in by_stream.items():
        receipt = receipts_by_key.get(
            (
                capability.capability_id,
                capability.protocol_version,
                capability.schema_version,
            )
        )
        if receipt is None:
            raise SourceEvidenceMismatchError(
                capability.capability_id,
                ("bounded_query_provenance",),
            )
        missing: list[str] = []
        if receipt.decision_range != decision_range:
            missing.append("decision_range_binding")
        if (
            receipt.capability_mapping_digest != mapping_digest
            or receipt.query_template_digest != query_digest
        ):
            missing.append("mapping_query_binding")
        if receipt.proofs != capability.proofs:
            missing.append("proof_receipt_binding")
        if stream is CapabilityStream.TOKEN_LAUNCH:
            if (
                receipt.launch_universe is None
                or receipt.launch_universe.policy_id != PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
                or receipt.launch_universe.decision_range != decision_range
            ):
                missing.append("launch_universe_evidence")
            if (
                receipt.skipped_slot_sentinel is not None
                or receipt.terminal_lifecycle_ordering is not None
            ):
                missing.append("stream_evidence_placement")
        elif stream is CapabilityStream.BLOCK_CLOCK:
            if (
                receipt.skipped_slot_sentinel is None
                or receipt.skipped_slot_sentinel.profile_id
                != SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID
            ):
                missing.append("skipped_slot_sentinel_evidence")
            if (
                receipt.launch_universe is not None
                or receipt.terminal_lifecycle_ordering is not None
            ):
                missing.append("stream_evidence_placement")
        elif stream is CapabilityStream.PUMP_CURVE_LIFECYCLE:
            if (
                receipt.terminal_lifecycle_ordering is None
                or receipt.terminal_lifecycle_ordering.profile_id
                != PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID
            ):
                missing.append("terminal_lifecycle_ordering_evidence")
            if receipt.launch_universe is not None or receipt.skipped_slot_sentinel is not None:
                missing.append("stream_evidence_placement")
        elif any(
            value is not None
            for value in (
                receipt.launch_universe,
                receipt.skipped_slot_sentinel,
                receipt.terminal_lifecycle_ordering,
            )
        ):
            missing.append("stream_evidence_placement")
        if missing:
            raise SourceEvidenceMismatchError(
                capability.capability_id,
                tuple(sorted(set(missing))),
            )
        selected.append(receipt)

    projector_digests = {item.projector_digest for item in selected}
    normalizer_digests = {item.normalizer_digest for item in selected}
    if len(projector_digests) != 1 or len(normalizer_digests) != 1:
        raise SourceEvidenceMismatchError(fallback_id, ("projection_contract_binding",))

    launch = next(
        item.launch_universe
        for item in selected
        if item.capability_id == by_stream[CapabilityStream.TOKEN_LAUNCH].capability_id
    )
    sentinel = next(
        item.skipped_slot_sentinel
        for item in selected
        if item.capability_id == by_stream[CapabilityStream.BLOCK_CLOCK].capability_id
    )
    lifecycle = next(
        item.terminal_lifecycle_ordering
        for item in selected
        if item.capability_id == by_stream[CapabilityStream.PUMP_CURVE_LIFECYCLE].capability_id
    )
    if launch is None or sentinel is None or lifecycle is None:  # pragma: no cover
        raise AssertionError("validated source evidence disappeared")
    return PumpfunSnipingSourceEvidenceBinding(
        receipt_refs=tuple(
            sorted(
                (
                    SourceEvidenceReceiptRef(item.capability_id, item.receipt_id)
                    for item in selected
                ),
                key=lambda item: item.capability_id.value,
            )
        ),
        capability_mapping_digest=mapping_digest,
        query_template_digest=query_digest,
        projector_digest=next(iter(projector_digests)),
        normalizer_digest=next(iter(normalizer_digests)),
        launch_universe=launch,
        skipped_slot_sentinel=sentinel,
        terminal_lifecycle_ordering=lifecycle,
    )


def require_pumpfun_sniping_source_contract(spec: DatasetSpec) -> None:
    """Require exact four-stream evidence before any sniping mutation.

    The check is reusable by planning and run preflight.  It trusts neither a
    successful local validation flag nor the mere presence of source columns.
    """

    if not isinstance(spec, DatasetSpec):
        raise TypeError("spec must be a DatasetSpec")
    fallback_id = min(spec.capabilities, key=lambda item: item.capability_id.value).capability_id
    if PUMPFUN_SNIPING_SOURCE_CONTRACT not in spec.evidence_contracts:
        raise SourceEvidenceMismatchError(fallback_id, ("sniping_evidence_contract",))
    # Assemble by stream once so the require pumpfun sniping source contract workflow
    # shares one value.
    by_stream = _unique_streams(spec.capabilities, fallback_id=fallback_id)
    binding = spec.source_evidence_binding
    if not isinstance(binding, PumpfunSnipingSourceEvidenceBinding):
        raise SourceEvidenceMismatchError(fallback_id, ("source_evidence_binding",))
    if (
        # The Sniping universe policy cannot be satisfied by a copy coverage binding.
        binding.launch_universe.policy_id != PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
        or binding.launch_universe.decision_range != spec.decision_range
        or binding.skipped_slot_sentinel.profile_id != SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID
        or binding.terminal_lifecycle_ordering.profile_id
        != PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID
        # Exact mapping and query operands remain mandatory even with all proof flags present.
        or binding.capability_mapping_digest != spec.capability_mapping_digest
        or binding.query_template_digest != spec.query_template_digest
    ):
        raise SourceEvidenceMismatchError(fallback_id, ("source_evidence_binding",))
    evidence_by_id = {item.capability_id: item for item in spec.cut_evidence}
    # Capability-specific extraction ranges retain authoritative typed bounds.
    range_by_id = {item.capability_id: item.block_range for item in spec.capability_ranges}

    if spec.settlement_tail is None:
        raise SourceEvidenceMismatchError(fallback_id, ("settlement_tail",))
    # Assemble requirement once so the require pumpfun sniping source contract workflow
    # shares one value.
    requirement = spec.settlement_requirement
    if not isinstance(requirement, SettlementRequirement):
        raise SourceEvidenceMismatchError(fallback_id, ("settlement_requirement",))
    if (
        requirement.schema != SETTLEMENT_REQUIREMENT_SCHEMA
        # Keep requirement visible while evaluating the schema, settlement requirement
        # schema and target stream guard.
        or requirement.target_stream is not CapabilityStream.TOKEN_LAUNCH
        or requirement.settlement_streams != _PUMPFUN_SETTLEMENT_STREAMS
        or requirement.initial_delay_transactions != PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS
        or requirement.minimum_duration_ns
        != PUMPFUN_SNIPING_SELL_DECISION_DELAY_SECONDS * 1_000_000_000
        # Evaluate the complete require pumpfun sniping source contract schema, settlement
        # requirement schema and target stream condition before guarded effects.
    ):
        raise SourceEvidenceMismatchError(fallback_id, ("settlement_contract",))
    cuts: list[CapabilityCutEvidence] = []
    for stream, required_proofs in _REQUIRED_PROOFS.items():
        # Process _REQUIRED_PROOFS.items() inside the bounded require pumpfun sniping
        # source contract loop.
        capability = by_stream[stream]
        evidence = evidence_by_id.get(capability.capability_id)
        missing = list(capability.proofs.require_proven(required_proofs))
        expected_protocol = "solana" if stream is CapabilityStream.BLOCK_CLOCK else "pumpfun"
        if capability.protocol != expected_protocol:
            # Invoke append for protocol family mismatch as a visible require pumpfun
            # sniping source contract step.
            missing.append("protocol_family_mismatch")
        if not _REQUIRED_COLUMNS[stream].issubset(capability.columns):
            missing.append("required_columns")
        _append_fidelity_failures(stream, capability, missing)

        requested_range = range_by_id[capability.capability_id]
        if (
            stream is CapabilityStream.TOKEN_LAUNCH
            and requested_range.to_block_ordinal != spec.decision_range.to_block_ordinal
        ):
            missing.append("tail_launch_targets")
        # Guard this path with evidence is None before applying effects.
        if evidence is None:
            missing.append("bounded_cut")
        else:
            # Handle the require pumpfun sniping source contract complement of evidence is
            # None explicitly.
            cuts.append(evidence)
            if (
                evidence.block_range.from_block_ordinal > requested_range.from_block_ordinal
                or evidence.snapshot_cut_to_block < requested_range.to_block_ordinal
            ):
                # Invoke append for bounded cut as a visible require pumpfun sniping
                # source contract step.
                missing.append("bounded_cut")
            if (
                evidence.completeness is not IngestionCompleteness.COMPLETE_TO_WATERMARK
                or evidence.ingestion_watermark_to_block is None
                or evidence.ingestion_watermark_to_block < requested_range.to_block_ordinal
                # Evaluate the complete require pumpfun sniping source contract completeness,
                # complete to watermark and ingestion watermark to block condition before
                # guarded effects.
            ):
                missing.append("complete_to_watermark")
            if evidence.consistency is not SourceConsistency.SNAPSHOT_CONSISTENT:
                missing.append("snapshot_consistent")

        if stream in {
            # Keep capability stream visible while evaluating the stream, to block ordinal
            # and block clock guard.
            CapabilityStream.BLOCK_CLOCK,
            CapabilityStream.PUMP_CURVE_TRADE,
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
        } and (requested_range.to_block_ordinal < spec.settlement_tail.to_block_ordinal):
            missing.append("settlement_tail_coverage")
        # Guard this path with missing before applying effects.
        if missing:
            # Handle the require pumpfun sniping source contract missing branch as a
            # distinct logical block.
            raise SourceEvidenceMismatchError(
                capability.capability_id,
                tuple(sorted(set(missing))),
            )

    cut_coordinates = {(item.snapshot_cut_to_block, item.upstream_revision) for item in cuts}
    # Guard this path with len(cut_coordinates) != 1 before applying effects.
    if len(cut_coordinates) != 1:
        raise SourceEvidenceMismatchError(fallback_id, ("network_consistent_cut",))


def require_pumpfun_sniping_inspection_receipts(
    metadata: SourceMetadata,
    spec: DatasetSpec,
    # Close the require pumpfun sniping inspection receipts signature after its explicit
    # inputs.
) -> None:
    """Bind a planned sniping contract to generated inspection-v5 receipts.

    ``DatasetSpec v5`` carries the explicit settlement and source-evidence contracts. Its
    exact source-inspection artifact ID is the provenance pin, while this
    planning-boundary check proves every selected capability claim came from a
    receipt in that exact inspection rather than from static configuration.
    """

    if not isinstance(metadata, SourceMetadata):
        raise TypeError("metadata must be SourceMetadata")
    if not isinstance(spec, DatasetSpec):
        raise TypeError("spec must be a DatasetSpec")
    fallback_id = min(spec.capabilities, key=lambda item: item.capability_id.value).capability_id
    # Evaluate the complete require pumpfun sniping inspection receipts source id,
    # capability mapping digest and query template digest condition before guarded
    # effects.
    if (
        metadata.source_id != spec.source_id
        or metadata.capability_mapping_digest != spec.capability_mapping_digest
        or metadata.query_template_digest != spec.query_template_digest
    ):
        # Fail the require pumpfun sniping inspection receipts path with
        # SourceEvidenceMismatchError for inspection binding and fallback id when source
        # id, capability mapping digest and query template digest is true; do not continue
        # ambiguously.
        raise SourceEvidenceMismatchError(fallback_id, ("inspection_binding",))

    resolved_binding = resolve_pumpfun_sniping_source_evidence_binding(
        metadata,
        spec.capabilities,
        spec.decision_range,
    )
    if spec.source_evidence_binding != resolved_binding:
        raise SourceEvidenceMismatchError(fallback_id, ("source_evidence_binding",))

    receipts = {
        (
            item.capability_id,
            item.protocol_version,
            # Keep the item component named inside the receipts contract.
            item.capability_schema_version,
        ): item
        for item in metadata.evidence_receipts
    }
    cuts = {item.capability_id: item for item in spec.cut_evidence}
    # Assemble ranges once so the require pumpfun sniping inspection receipts workflow
    # shares one value.
    ranges = {item.capability_id: item.block_range for item in spec.capability_ranges}
    by_stream = _unique_streams(spec.capabilities, fallback_id=fallback_id)
    for stream in _REQUIRED_PROOFS:
        # Process _REQUIRED_PROOFS inside the bounded require pumpfun sniping inspection
        # receipts loop.
        capability = by_stream[stream]
        receipt = receipts.get(
            (
                capability.capability_id,
                capability.protocol_version,
                # Pass capability explicitly so get receives a reviewable capability id
                # and protocol version input in require pumpfun sniping inspection
                # receipts.
                capability.schema_version,
            )
        )
        if receipt is None:
            # Handle the require pumpfun sniping inspection receipts receipt is None
            # branch as a distinct logical block.
            raise SourceEvidenceMismatchError(
                capability.capability_id,
                ("bounded_query_provenance",),
            )
        missing: list[str] = []
        # Guard this path with receipt.proofs != capability.proofs before applying
        # effects.
        if receipt.proofs != capability.proofs:
            missing.append("proof_receipt_binding")
        if cuts.get(capability.capability_id) != receipt.cut_evidence:
            missing.append("cut_receipt_binding")
        requested_range = ranges[capability.capability_id]
        # Evaluate the complete require pumpfun sniping inspection receipts from block
        # ordinal, snapshot cut to block and to block ordinal condition before guarded
        # effects.
        if (
            receipt.cut_evidence.block_range.from_block_ordinal > requested_range.from_block_ordinal
            or receipt.cut_evidence.snapshot_cut_to_block < requested_range.to_block_ordinal
        ):
            missing.append("bounded_query_provenance")
        # Guard this path with missing before applying effects.
        if missing:
            # Handle the require pumpfun sniping inspection receipts missing branch as a
            # distinct logical block.
            raise SourceEvidenceMismatchError(
                capability.capability_id,
                tuple(sorted(set(missing))),
            )


def _append_fidelity_failures(
    # Keep the stream input explicit in the append fidelity failures contract.
    stream: CapabilityStream,
    capability: PlannedCapability,
    missing: list[str],
) -> None:
    """Reject locally convenient columns that do not carry exact source fidelity."""

    fidelity = capability.fidelity
    if fidelity.identity is not IdentityFidelity.EXACT:
        missing.append("identity_exact")
    if fidelity.chain_finality is not ChainFinality.FINALIZED:
        missing.append("chain_finalized")
    # Evaluate the complete append fidelity failures completeness, complete to watermark
    # and fidelity condition before guarded effects.
    if fidelity.completeness is not IngestionCompleteness.COMPLETE_TO_WATERMARK:
        missing.append("complete_to_watermark")
    if fidelity.consistency is not SourceConsistency.SNAPSHOT_CONSISTENT:
        missing.append("snapshot_consistent")
    if stream is CapabilityStream.BLOCK_CLOCK:
        # Return explicit absence from the append fidelity failures path.
        return
    if fidelity.ordering is not OrderingFidelity.INSTRUCTION_EXACT:
        missing.append("instruction_order_exact")
    if fidelity.state not in {StateFidelity.AFTER_ONLY, StateFidelity.BEFORE_AFTER}:
        missing.append("after_state_exact")
    # Evaluate the complete append fidelity failures stream, pump curve trade and fees
    # condition before guarded effects.
    if stream is CapabilityStream.PUMP_CURVE_TRADE and fidelity.fees is not FeesFidelity.COMPONENTS:
        missing.append("fee_components_exact")


def _unique_streams(
    capabilities: tuple[PlannedCapability, ...],
    *,
    # Keep the fallback id input explicit in the unique streams contract.
    fallback_id: CapabilityId,
) -> dict[CapabilityStream, PlannedCapability]:
    # Execute the unique streams workflow in explicit, reviewable steps.
    by_stream: dict[CapabilityStream, PlannedCapability] = {}
    duplicate_streams: list[str] = []
    for capability in capabilities:
        # Process capabilities inside the bounded unique streams loop.
        if capability.stream in by_stream:
            duplicate_streams.append(f"duplicate_{capability.stream.value.lower()}_stream")
        else:
            by_stream[capability.stream] = capability
    missing_streams = [
        # Keep the lower and value lower step visible while building missing streams.
        f"missing_{stream.value.lower()}_stream"
        for stream in _REQUIRED_PROOFS
        if stream not in by_stream
    ]
    structural = tuple(sorted((*duplicate_streams, *missing_streams)))
    # Guard this path with structural before applying effects.
    if structural:
        raise SourceEvidenceMismatchError(fallback_id, structural)
    return by_stream


__all__ = [
    "pumpfun_sniping_settlement_requirement",
    # Keep the require pumpfun sniping inspection receipts component named inside the all
    # contract.
    "require_pumpfun_sniping_inspection_receipts",
    "require_pumpfun_sniping_source_contract",
    "resolve_pumpfun_sniping_source_evidence_binding",
]
