"""Outbound boundaries for filesystem-authoritative retention state."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, runtime_checkable

from backtest.application.retention import (
    ArtifactLeaseInfo,
    # Include garbage collection batch so the retention dependency remains explicit.
    GarbageCollectionBatch,
    GarbageCollectionPlan,
    GarbageCollectionPolicy,
    GarbageCollectionReceipt,
    PinRecord,
    # Close the retention import after its required symbols are visible.
)
from backtest.domain.identifiers import ArtifactId, Identifier


# Keep the artifact lease contract and validation rules together.
@runtime_checkable
class ArtifactLease(Protocol):
    @property
    def info(self) -> ArtifactLeaseInfo: ...

    def close(self) -> None: ...

    # Define artifact lease enter as one focused operation with an explicit boundary.
    def __enter__(self) -> ArtifactLease: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        # Keep the traceback input explicit in the exit contract.
        traceback: TracebackType | None,
    ) -> None: ...


# Keep the retention repository contract and validation rules together.
@runtime_checkable
class RetentionRepository(Protocol):
    def create_pin(
        self,
        *,
        # Keep the pin id input explicit in the create pin contract.
        pin_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
        created_at_ns: int,
    ) -> PinRecord: ...

    # Define retention repository retire pin as one focused operation with an explicit
    # boundary.
    def retire_pin(self, pin_id: Identifier, *, retired_at_ns: int) -> PinRecord: ...

    def active_pins(self) -> tuple[PinRecord, ...]: ...

    def acquire_lease(
        self,
        *,
        # Keep the lease id input explicit in the acquire lease contract.
        lease_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
    ) -> ArtifactLease: ...

    def plan_garbage_collection(
        # Keep the remaining plan garbage collection inputs visible at the retention
        # repository plan garbage collection boundary.
        self,
        *,
        retained_roots: tuple[ArtifactId, ...],
        policy: GarbageCollectionPolicy,
        now_ns: int,
        # Keep the garbage collection plan step explicit within the retention repository plan
        # garbage collection workflow.
    ) -> GarbageCollectionPlan: ...

    def execute_garbage_collection(
        self,
        plan: GarbageCollectionPlan,
        *,
        # Keep the now ns input explicit in the execute garbage collection contract.
        now_ns: int,
    ) -> GarbageCollectionBatch: ...

    def purge_trash(
        self,
        batch_id: Identifier,
        # Close the purge trash signature after its explicit inputs.
        *,
        now_ns: int,
    ) -> GarbageCollectionReceipt: ...


@runtime_checkable
class RetentionIndex(Protocol):
    """Rebuildable SQLite projection; never pin or GC authority."""

    def index_active(self, pin: PinRecord) -> None: ...

    def index_retired(self, pin: PinRecord) -> None: ...

    def rebuild(self, active_pins: tuple[PinRecord, ...]) -> None: ...


@runtime_checkable
class RetentionRootProvider(Protocol):
    """Authoritative host roots that a GC request is never allowed to omit."""

    def retained_roots(self) -> tuple[ArtifactId, ...]: ...


__all__ = [
    "ArtifactLease",
    "RetentionIndex",
    "RetentionRepository",
    # Keep the retention root provider component named inside the all contract.
    "RetentionRootProvider",
]
