"""Typed, secret-free evidence for exact Pump.fun source admission."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.copy_source import CopyBuyCoverageEvidence
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange

# Each evidence family keeps a separate schema and identity meaning.
LAUNCH_UNIVERSE_EVIDENCE_SCHEMA = "pumpfun-launch-universe-evidence/v1"
SKIPPED_SLOT_SENTINEL_EVIDENCE_SCHEMA = "solana-skipped-slot-sentinel-evidence/v1"
TERMINAL_LIFECYCLE_ORDERING_EVIDENCE_SCHEMA = "pumpfun-terminal-lifecycle-ordering-evidence/v1"
PUMPFUN_SNIPING_SOURCE_EVIDENCE_BINDING_SCHEMA = "pumpfun-sniping-source-evidence-binding/v1"

MAYHEM_EXCLUSION_REASON = "MAYHEM_EXCLUDED"
# Policy identifiers describe normalization behavior rather than endpoint capabilities.
SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID = "solana-skipped-slot-epoch-zero-pinned-fingerprint-v1"
PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID = "pumpfun-terminal-buy-completion-migration-order-v1"


def _require_policy_id(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


def _require_count(value: int, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_digest(value: ContentDigest, *, field: str) -> None:
    if not isinstance(value, ContentDigest):
        raise TypeError(f"{field} must be a ContentDigest")


@dataclass(frozen=True, slots=True)
class LaunchUniverseEvidence:
    """Decision-range-only classification evidence for the Sniping launch universe."""

    decision_range: BlockRange
    policy_id: str
    classified_count: int
    eligible_count: int
    excluded_count: int
    ordered_exclusion_digest: ContentDigest
    exclusion_reason: str = MAYHEM_EXCLUSION_REASON
    schema: str = LAUNCH_UNIVERSE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LAUNCH_UNIVERSE_EVIDENCE_SCHEMA:
            raise ValueError("unsupported launch universe evidence schema")
        if not isinstance(self.decision_range, BlockRange):
            raise TypeError("launch universe decision_range must be a BlockRange")
        _require_policy_id(self.policy_id, field="launch universe policy_id")
        for field_name in ("classified_count", "eligible_count", "excluded_count"):
            _require_count(getattr(self, field_name), field=field_name)
        if self.classified_count != self.eligible_count + self.excluded_count:
            raise ValueError("classified_count must equal eligible_count plus excluded_count")
        _require_digest(
            self.ordered_exclusion_digest,
            field="ordered_exclusion_digest",
        )
        if self.exclusion_reason != MAYHEM_EXCLUSION_REASON:
            raise ValueError("unsupported launch exclusion reason")

    def identity_document(self) -> dict[str, object]:
        return {
            "classified_count": self.classified_count,
            "decision_range": _range_document(self.decision_range),
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "exclusion_reason": self.exclusion_reason,
            "ordered_exclusion_digest": self.ordered_exclusion_digest.hex,
            "policy_id": self.policy_id,
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True)
class SkippedSlotSentinelEvidence:
    """Evidence for exact skipped-slot sentinels observed in one bounded source cut."""

    profile_id: str
    recognized_count: int
    ordered_sentinel_digest: ContentDigest
    schema: str = SKIPPED_SLOT_SENTINEL_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SKIPPED_SLOT_SENTINEL_EVIDENCE_SCHEMA:
            raise ValueError("unsupported skipped-slot sentinel evidence schema")
        _require_policy_id(self.profile_id, field="skipped-slot sentinel profile_id")
        _require_count(self.recognized_count, field="recognized_count")
        _require_digest(self.ordered_sentinel_digest, field="ordered_sentinel_digest")

    def identity_document(self) -> dict[str, object]:
        return {
            "ordered_sentinel_digest": self.ordered_sentinel_digest.hex,
            "profile_id": self.profile_id,
            "recognized_count": self.recognized_count,
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True)
class TerminalLifecycleOrderingEvidence:
    """Evidence for same-transaction terminal trade/completion/migration ordering."""

    profile_id: str
    derived_group_count: int
    ordered_group_digest: ContentDigest
    schema: str = TERMINAL_LIFECYCLE_ORDERING_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TERMINAL_LIFECYCLE_ORDERING_EVIDENCE_SCHEMA:
            raise ValueError("unsupported terminal lifecycle ordering evidence schema")
        _require_policy_id(self.profile_id, field="terminal lifecycle profile_id")
        _require_count(self.derived_group_count, field="derived_group_count")
        _require_digest(self.ordered_group_digest, field="ordered_group_digest")

    def identity_document(self) -> dict[str, object]:
        return {
            "derived_group_count": self.derived_group_count,
            "ordered_group_digest": self.ordered_group_digest.hex,
            "profile_id": self.profile_id,
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True, order=True)
class SourceEvidenceReceiptRef:
    """Capability-addressed reference to one receipt embedded in an inspection."""

    capability_id: CapabilityId
    receipt_id: ContentDigest


@dataclass(frozen=True, slots=True)
class PumpfunSnipingSourceEvidenceBinding:
    """Exact source-evidence operands carried into DatasetSpec and snapshot validation."""

    receipt_refs: tuple[SourceEvidenceReceiptRef, ...]
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    projector_digest: ContentDigest
    normalizer_digest: ContentDigest
    launch_universe: LaunchUniverseEvidence
    skipped_slot_sentinel: SkippedSlotSentinelEvidence
    terminal_lifecycle_ordering: TerminalLifecycleOrderingEvidence
    schema: str = PUMPFUN_SNIPING_SOURCE_EVIDENCE_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PUMPFUN_SNIPING_SOURCE_EVIDENCE_BINDING_SCHEMA:
            raise ValueError("unsupported Pump.fun Sniping source evidence binding schema")
        for field_name in (
            "capability_mapping_digest",
            "query_template_digest",
            "projector_digest",
            "normalizer_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.launch_universe, LaunchUniverseEvidence):
            raise TypeError("launch_universe must be LaunchUniverseEvidence")
        if not isinstance(self.skipped_slot_sentinel, SkippedSlotSentinelEvidence):
            raise TypeError("skipped_slot_sentinel must be SkippedSlotSentinelEvidence")
        if not isinstance(
            self.terminal_lifecycle_ordering,
            TerminalLifecycleOrderingEvidence,
        ):
            raise TypeError("terminal_lifecycle_ordering must be TerminalLifecycleOrderingEvidence")
        if not all(isinstance(item, SourceEvidenceReceiptRef) for item in self.receipt_refs):
            raise TypeError("receipt_refs must contain SourceEvidenceReceiptRef values")
        ordered = tuple(sorted(self.receipt_refs, key=lambda item: item.capability_id.value))
        if ordered != self.receipt_refs or not ordered:
            raise ValueError("source evidence receipt refs must be non-empty and sorted")
        if len({item.capability_id for item in ordered}) != len(ordered):
            raise ValueError("source evidence receipt refs must have unique capabilities")
        if len({item.receipt_id for item in ordered}) != len(ordered):
            raise ValueError("source evidence receipt refs must have unique receipt IDs")

    def identity_document(self) -> dict[str, object]:
        return {
            "capability_mapping_digest": self.capability_mapping_digest.hex,
            "launch_universe": self.launch_universe.identity_document(),
            "normalizer_digest": self.normalizer_digest.hex,
            "projector_digest": self.projector_digest.hex,
            "query_template_digest": self.query_template_digest.hex,
            "receipt_refs": [
                {
                    "capability_id": item.capability_id.value,
                    "receipt_id": item.receipt_id.hex,
                }
                for item in self.receipt_refs
            ],
            "schema": self.schema,
            "skipped_slot_sentinel": self.skipped_slot_sentinel.identity_document(),
            "terminal_lifecycle_ordering": (self.terminal_lifecycle_ordering.identity_document()),
        }


@dataclass(frozen=True, slots=True)
class PumpfunCopyBuySourceEvidenceBinding:
    """Copy coverage is a separate proof, never a reinterpretation of launch-only evidence."""

    receipt_refs: tuple[SourceEvidenceReceiptRef, ...]
    capability_mapping_digest: ContentDigest
    query_template_digest: ContentDigest
    projector_digest: ContentDigest
    normalizer_digest: ContentDigest
    # Creation lookback and independent purchase enumeration travel together.
    copy_coverage: CopyBuyCoverageEvidence
    skipped_slot_sentinel: SkippedSlotSentinelEvidence
    terminal_lifecycle_ordering: TerminalLifecycleOrderingEvidence
    schema: str = "pumpfun-copybuy-source-evidence-binding/v1"

    def __post_init__(self) -> None:
        """Reject partial, reordered or cross-contract source bindings before planning."""
        if self.schema != "pumpfun-copybuy-source-evidence-binding/v1":
            raise ValueError("unsupported copy source evidence binding")
        if not isinstance(self.copy_coverage, CopyBuyCoverageEvidence):
            raise TypeError("copy binding requires reconciled coverage")
        # Shared mathematical proofs retain their original exact typed meaning.
        if not isinstance(self.skipped_slot_sentinel, SkippedSlotSentinelEvidence):
            raise TypeError("copy binding requires skipped-slot evidence")
        if not isinstance(self.terminal_lifecycle_ordering, TerminalLifecycleOrderingEvidence):
            raise TypeError("copy binding requires lifecycle evidence")
        # All transform operands, not only the source result, are identity-bearing.
        for value in (
            self.capability_mapping_digest,
            self.query_template_digest,
            self.projector_digest,
            self.normalizer_digest,
            # No copy binding operand may be an unresolved string alias.
        ):
            _require_digest(value, field="copy binding operand")
        # Each capability must have one authoritative bounded receipt.
        refs = self.receipt_refs
        if not isinstance(refs, tuple) or not refs or len(refs) > 128:
            raise ValueError("copy binding requires bounded receipt refs")
        if any(not isinstance(ref, SourceEvidenceReceiptRef) for ref in refs):
            raise TypeError("copy binding receipt reference has an invalid type")
        # Canonical ordering and uniqueness prevent ambiguous capability selection.
        if tuple(sorted(refs, key=lambda ref: ref.capability_id.value)) != refs:
            raise ValueError("copy binding receipt refs must be sorted")
        if len({ref.capability_id for ref in refs}) != len(refs):
            raise ValueError("copy binding repeats a capability")
        if len({ref.receipt_id for ref in refs}) != len(refs):
            # One receipt cannot claim authority for several distinct required capabilities.
            raise ValueError("copy binding repeats a receipt")

    def identity_document(self) -> dict[str, object]:
        """Bind exact receipts and coverage to every downstream dataset and run."""
        return {
            "schema": self.schema,
            "capability_mapping_digest": self.capability_mapping_digest.hex,
            "query_template_digest": self.query_template_digest.hex,
            "projector_digest": self.projector_digest.hex,
            # Repreparation is mandatory whenever normalization or coverage changes.
            "normalizer_digest": self.normalizer_digest.hex,
            "copy_coverage": self.copy_coverage.identity_document(),
            "skipped_slot_sentinel": self.skipped_slot_sentinel.identity_document(),
            "terminal_lifecycle_ordering": self.terminal_lifecycle_ordering.identity_document(),
            # References are bounded independently of the number of source events.
            "receipt_refs": [
                {"capability_id": ref.capability_id.value, "receipt_id": ref.receipt_id.hex}
                for ref in self.receipt_refs
            ],
        }


def _range_document(value: BlockRange) -> dict[str, object]:
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
    }


__all__ = [
    "LAUNCH_UNIVERSE_EVIDENCE_SCHEMA",
    "MAYHEM_EXCLUSION_REASON",
    "PUMPFUN_SNIPING_SOURCE_EVIDENCE_BINDING_SCHEMA",
    "PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID",
    "SKIPPED_SLOT_SENTINEL_EVIDENCE_SCHEMA",
    "SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID",
    "TERMINAL_LIFECYCLE_ORDERING_EVIDENCE_SCHEMA",
    "LaunchUniverseEvidence",
    "PumpfunSnipingSourceEvidenceBinding",
    "SkippedSlotSentinelEvidence",
    "SourceEvidenceReceiptRef",
    "TerminalLifecycleOrderingEvidence",
]
