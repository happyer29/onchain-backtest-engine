"""Read-only source inspection and deterministic schema fingerprinting."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime

# Universe policy distinguishes creation-triggered Sniping from copy selection.
from backtest.application.copy_source import COPYBUY_UNIVERSE_POLICY_ID

# Import errors at the visible module dependency boundary.
from backtest.application.errors import (
    SourceEvidenceValidationError,
    SourceInspectionFailedError,
)
from backtest.application.models import (
    CAPABILITY_PROOF_FIELDS,
    BoundedSourceEvidenceReceipt,
    BoundedSourceEvidenceRequest,
    # Include evidence status so the models dependency remains explicit.
    EvidenceStatus,
    SourceInspection,
    SourceMetadata,
)
from backtest.application.ports.source import (
    # Include bounded source evidence reader so the source dependency remains explicit.
    BoundedSourceEvidenceReader,
    SourceMetadataReader,
)
from backtest.application.sniping_run_contract import (
    PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
)
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
)
from backtest.application.source_fingerprint import source_schema_fingerprint
from backtest.domain.identifiers import SourceId


# Keep the inspect source request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class InspectSourceRequest:
    source_id: SourceId
    evidence_request: BoundedSourceEvidenceRequest | None = None

    def __post_init__(self) -> None:
        # Execute the inspect source request post init workflow in explicit, reviewable
        # steps.
        if self.evidence_request is not None and (
            self.evidence_request.source_id != self.source_id
        ):
            raise ValueError("bounded evidence request uses a different source")


class InspectSource:
    """Inspect metadata without extracting or mutating source data."""

    def __init__(
        self,
        metadata_reader: SourceMetadataReader,
        *,
        evidence_reader: BoundedSourceEvidenceReader | None = None,
        # Keep the now input explicit in the init contract.
        now: Callable[[], datetime] | None = None,
    ) -> None:
        # Execute the inspect source init workflow in explicit, reviewable steps.
        self._metadata_reader = metadata_reader
        self._evidence_reader = evidence_reader
        self._now = now or (lambda: datetime.now(UTC))

    def execute(self, request: InspectSourceRequest) -> SourceInspection:
        # Execute the inspect source execute workflow in explicit, reviewable steps.
        metadata: SourceMetadata | None = None
        # Adapter errors can contain a DSN.  Suppression ends before the public
        # error is raised, so the original is neither copied nor kept as context.
        with suppress(Exception):
            metadata = self._metadata_reader.inspect_metadata(request.source_id)

        if metadata is None:
            raise SourceInspectionFailedError(request.source_id)

        if metadata.source_id != request.source_id:
            # Fail the inspect source execute path with SourceInspectionFailedError for
            # source id and request when source id, metadata and request is true; do not
            # continue ambiguously.
            raise SourceInspectionFailedError(request.source_id)
        if metadata.capability_mapping_digest is None or metadata.query_template_digest is None:
            raise SourceInspectionFailedError(request.source_id)
        if metadata.evidence_receipts or _has_generated_proof_claim(metadata):
            # Metadata discovery is declarative.  Dynamic claims may enter only
            # through the separate bounded-evidence port in this invocation.
            raise SourceInspectionFailedError(request.source_id)

        if request.evidence_request is not None:
            # Handle the inspect source execute request.evidence_request is not None
            # branch as a distinct logical block.
            evidence_request = request.evidence_request
            if (
                evidence_request.block_range.network_id != metadata.network_id
                or evidence_request.block_range.position_schema_id != metadata.position_schema_id
                or evidence_request.capability_mapping_digest != metadata.capability_mapping_digest
                # The request must use the inspected source mapping and exact query template.
                or evidence_request.query_template_digest != metadata.query_template_digest
                or evidence_request.launch_universe_policy_id
                != (
                    PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
                    if evidence_request.copy_selection is None
                    # Only an explicit copy selection may choose the separate copy universe policy.
                    else COPYBUY_UNIVERSE_POLICY_ID
                )
                or evidence_request.skipped_slot_sentinel_policy_id
                != SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID
                or evidence_request.terminal_lifecycle_ordering_policy_id
                # Atomic terminal ordering stays pinned independently of source selection.
                != PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID
                or self._evidence_reader is None
                # Evaluate the complete inspect source execute network id, position schema id
                # and evidence reader condition before guarded effects.
            ):
                raise SourceInspectionFailedError(request.source_id)
            receipts = None
            evidence_error = None
            try:
                receipts = self._evidence_reader.inspect_bounded_evidence(evidence_request)
            except SourceEvidenceValidationError as error:
                # Rebuild the safe application error outside this exception context below.
                # This prevents a lower adapter/driver cause from being retained.
                evidence_error = SourceEvidenceValidationError(error.code)
            except Exception:
                # Unknown adapter errors can contain credentials, endpoints or query text.
                pass
            if evidence_error is not None:
                raise evidence_error
            # Guard this path with not receipts before applying effects.
            if not receipts:
                raise SourceInspectionFailedError(request.source_id)
            promoted: SourceMetadata | None = None
            with suppress(Exception):
                _require_receipts_match_request(receipts, evidence_request)
                promoted = _with_generated_evidence(metadata, receipts)
            # Guard this path with promoted is None before applying effects.
            if promoted is None:
                raise SourceInspectionFailedError(request.source_id)
            metadata = promoted

        inspected_at = self._now()
        if inspected_at.tzinfo is None or inspected_at.utcoffset() is None:
            # Fail the inspect source execute path with ValueError for inspection clock
            # must return a timezone-aware datetime when tzinfo, inspected at and
            # utcoffset is true; do not continue ambiguously.
            raise ValueError("inspection clock must return a timezone-aware datetime")

        return SourceInspection(
            metadata=metadata,
            schema_fingerprint=source_schema_fingerprint(metadata),
            inspected_at=inspected_at,
            # Complete SourceInspection only after its source schema fingerprint and metadata
            # inputs are visible in inspect source execute.
        )


def _has_generated_proof_claim(metadata: SourceMetadata) -> bool:
    # Execute the has generated proof claim workflow in explicit, reviewable steps.
    return any(
        getattr(capability.proofs, field_name) is not EvidenceStatus.UNKNOWN
        for capability in metadata.capabilities
        for field_name in CAPABILITY_PROOF_FIELDS
    )


# Define with generated evidence as one focused operation with an explicit boundary.
def _with_generated_evidence(
    metadata: SourceMetadata,
    receipts: tuple[BoundedSourceEvidenceReceipt, ...],
) -> SourceMetadata:
    # Execute the with generated evidence workflow in explicit, reviewable steps.
    receipt_by_key = {
        (
            item.capability_id,
            item.protocol_version,
            item.capability_schema_version,
            # Keep the item component named inside the receipt by key contract.
        ): item
        for item in receipts
    }
    if len(receipt_by_key) != len(receipts):
        raise ValueError("bounded evidence contains duplicate capability versions")
    # Assemble capabilities once so the with generated evidence workflow shares one value.
    capabilities = tuple(
        replace(
            capability,
            proofs=receipt_by_key[
                (
                    # Pass capability explicitly so replace receives a reviewable proofs
                    # and capability id input in with generated evidence.
                    capability.capability_id,
                    capability.protocol_version,
                    capability.schema_version,
                )
            ].proofs,
            fidelity=receipt_by_key[
                (
                    capability.capability_id,
                    capability.protocol_version,
                    capability.schema_version,
                )
            ].source_fidelity,
            # Complete replace only after its proofs and capability id inputs are visible in
            # with generated evidence.
        )
        if (
            capability.capability_id,
            capability.protocol_version,
            capability.schema_version,
            # Complete tuple only after its capabilities and capability id inputs are visible
            # in with generated evidence.
        )
        in receipt_by_key
        else capability
        for capability in metadata.capabilities
    )
    # Assemble cuts once so the with generated evidence workflow shares one value.
    cuts = {item.capability_id: item for item in metadata.cut_evidence}
    for receipt in receipts:
        # Process receipts inside the bounded with generated evidence loop.
        existing = cuts.get(receipt.capability_id)
        if existing is not None and existing != receipt.cut_evidence:
            raise ValueError("bounded evidence conflicts with metadata cut")
        cuts[receipt.capability_id] = receipt.cut_evidence
    return replace(
        # Pass metadata explicitly so replace receives a reviewable values and tuple input
        # in with generated evidence.
        metadata,
        capabilities=capabilities,
        cut_evidence=tuple(cuts.values()),
        evidence_receipts=receipts,
    )


def _require_receipts_match_request(
    receipts: tuple[BoundedSourceEvidenceReceipt, ...],
    request: BoundedSourceEvidenceRequest,
) -> None:
    for receipt in receipts:
        # The same explicit signer selection must survive bounded evidence promotion.
        selection = None if receipt.copy_coverage is None else receipt.copy_coverage.selection
        if selection != request.copy_selection:
            raise ValueError("bounded evidence uses another copy selection")
        # Validate every request operand before promoting a returned bounded receipt.
        if (
            receipt.source_id != request.source_id
            or receipt.cut_evidence.block_range != request.block_range
            or receipt.decision_range != request.decision_range
            or receipt.capability_mapping_digest != request.capability_mapping_digest
            # Template, projector and normalizer digests must all match the requested proof.
            or receipt.query_template_digest != request.query_template_digest
            or receipt.projector_digest != request.projector_digest
            or receipt.normalizer_digest != request.normalizer_digest
        ):
            raise ValueError("bounded evidence receipt uses different request operands")
        # Legacy launch classification remains bound to its declared universe policy.
        if (
            receipt.launch_universe is not None
            and receipt.launch_universe.policy_id != request.launch_universe_policy_id
        ):
            raise ValueError("launch evidence uses another universe policy")
        # Sentinel evidence cannot substitute an unrecognized skipped-slot convention.
        if (
            receipt.skipped_slot_sentinel is not None
            and receipt.skipped_slot_sentinel.profile_id != request.skipped_slot_sentinel_policy_id
        ):
            raise ValueError("skipped-slot evidence uses another sentinel policy")
        # Lifecycle proof must retain the exact ordered terminal normalization policy.
        if (
            receipt.terminal_lifecycle_ordering is not None
            and receipt.terminal_lifecycle_ordering.profile_id
            != request.terminal_lifecycle_ordering_policy_id
        ):
            # A policy mismatch invalidates the entire receipt before publication.
            raise ValueError("terminal lifecycle evidence uses another ordering policy")


# Bind all once as an explicit module-level contract.
__all__ = ["InspectSource", "InspectSourceRequest"]
