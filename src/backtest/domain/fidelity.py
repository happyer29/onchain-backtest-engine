"""Capability fidelity vocabulary and compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import ClassVar


# Keep the identity fidelity contract and validation rules together.
class IdentityFidelity(StrEnum):
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"
    CANDIDATE = "CANDIDATE"
    EXACT = "EXACT"


# Keep the ordering fidelity contract and validation rules together.
class OrderingFidelity(StrEnum):
    UNKNOWN = "UNKNOWN"
    TRANSACTION_PARTIAL = "TRANSACTION_PARTIAL"
    TRANSACTION_EXACT = "TRANSACTION_EXACT"
    INSTRUCTION_EXACT = "INSTRUCTION_EXACT"


# Keep the state fidelity contract and validation rules together.
class StateFidelity(StrEnum):
    NONE = "NONE"
    AFTER_ONLY = "AFTER_ONLY"
    RECONSTRUCTABLE = "RECONSTRUCTABLE"
    BEFORE_AFTER = "BEFORE_AFTER"


# Keep the fees fidelity contract and validation rules together.
class FeesFidelity(StrEnum):
    UNKNOWN = "UNKNOWN"
    TOTAL_ONLY = "TOTAL_ONLY"
    COMPONENTS = "COMPONENTS"


# Keep the chain finality contract and validation rules together.
class ChainFinality(StrEnum):
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    FINALIZED = "FINALIZED"


# Keep the ingestion completeness contract and validation rules together.
class IngestionCompleteness(StrEnum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    COMPLETE_TO_WATERMARK = "COMPLETE_TO_WATERMARK"


# Keep the source consistency contract and validation rules together.
class SourceConsistency(StrEnum):
    UNKNOWN = "UNKNOWN"
    BEST_EFFORT = "BEST_EFFORT"
    SNAPSHOT_CONSISTENT = "SNAPSHOT_CONSISTENT"


# Keep the fidelity gap contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FidelityGap:
    field: str
    required: str
    available: str


# Keep the fidelity requirement contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FidelityRequirement:
    identity: IdentityFidelity = IdentityFidelity.UNKNOWN
    ordering: OrderingFidelity = OrderingFidelity.UNKNOWN
    state: StateFidelity = StateFidelity.NONE
    # Declare fees explicitly in the fidelity requirement contract.
    fees: FeesFidelity = FeesFidelity.UNKNOWN
    chain_finality: ChainFinality = ChainFinality.UNKNOWN
    completeness: IngestionCompleteness = IngestionCompleteness.UNKNOWN
    consistency: SourceConsistency = SourceConsistency.UNKNOWN

    _RANKS: ClassVar[dict[str, tuple[Enum, ...]]] = {
        # Register identity fidelity through tuple so the ranks table remains scannable.
        "identity": tuple(IdentityFidelity),
        "ordering": tuple(OrderingFidelity),
        "state": tuple(StateFidelity),
        "fees": tuple(FeesFidelity),
        "chain_finality": tuple(ChainFinality),
        # Register ingestion completeness through tuple so the ranks table remains
        # scannable.
        "completeness": tuple(IngestionCompleteness),
        "consistency": tuple(SourceConsistency),
    }

    @classmethod
    def combine(cls, requirements: tuple[FidelityRequirement, ...]) -> FidelityRequirement:
        # Execute the fidelity requirement combine workflow in explicit, reviewable steps.
        if not requirements:
            return cls()
        return cls(
            identity=max(
                (item.identity for item in requirements),
                # Include key in the completed fidelity requirement combine result.
                key=tuple(IdentityFidelity).index,
            ),
            ordering=max(
                (item.ordering for item in requirements),
                key=tuple(OrderingFidelity).index,
                # Complete max only after its ordering and index inputs are visible in
                # fidelity requirement combine.
            ),
            state=max(
                (item.state for item in requirements),
                key=tuple(StateFidelity).index,
            ),
            # Include fees in the completed fidelity requirement combine result.
            fees=max(
                (item.fees for item in requirements),
                key=tuple(FeesFidelity).index,
            ),
            chain_finality=max(
                # Open the chain finality and index payload explicitly for max within
                # fidelity requirement combine.
                (item.chain_finality for item in requirements),
                key=tuple(ChainFinality).index,
            ),
            completeness=max(
                (item.completeness for item in requirements),
                # Include key in the completed fidelity requirement combine result.
                key=tuple(IngestionCompleteness).index,
            ),
            consistency=max(
                (item.consistency for item in requirements),
                key=tuple(SourceConsistency).index,
                # Complete max only after its consistency and index inputs are visible in
                # fidelity requirement combine.
            ),
        )


# Keep the source fidelity contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceFidelity:
    identity: IdentityFidelity
    ordering: OrderingFidelity
    state: StateFidelity
    # Declare fees explicitly in the source fidelity contract.
    fees: FeesFidelity
    chain_finality: ChainFinality
    completeness: IngestionCompleteness
    consistency: SourceConsistency

    def gaps(self, requirement: FidelityRequirement) -> tuple[FidelityGap, ...]:
        # Execute the source fidelity gaps workflow in explicit, reviewable steps.
        gaps: list[FidelityGap] = []
        for field, ranking in FidelityRequirement._RANKS.items():
            # Process FidelityRequirement._RANKS.items() inside the bounded source
            # fidelity gaps loop.
            available = getattr(self, field)
            required = getattr(requirement, field)
            if ranking.index(available) < ranking.index(required):
                # Handle the source fidelity gaps index, available and required condition
                # as a distinct block.
                gaps.append(
                    FidelityGap(
                        field=field,
                        required=required.value,
                        available=available.value,
                        # Complete FidelityGap only after its value and field inputs are
                        # visible in source fidelity gaps.
                    )
                )
        return tuple(gaps)

    def satisfies(self, requirement: FidelityRequirement) -> bool:
        return not self.gaps(requirement)
