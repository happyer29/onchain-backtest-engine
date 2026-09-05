"""Use cases for durable pins, leases, and two-phase garbage collection."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from backtest.application.ports.retention import (
    # Include artifact lease so the retention dependency remains explicit.
    ArtifactLease,
    RetentionIndex,
    RetentionRepository,
    RetentionRootProvider,
)

# Import retention at the visible module dependency boundary.
from backtest.application.retention import (
    GarbageCollectionBatch,
    GarbageCollectionPlan,
    GarbageCollectionPlanStaleError,
    GarbageCollectionPolicy,
    # Include garbage collection receipt so the retention dependency remains explicit.
    GarbageCollectionReceipt,
    PinRecord,
)
from backtest.domain.identifiers import ArtifactId, Identifier


# Keep the create pin request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class CreatePinRequest:
    pin_id: Identifier
    roots: tuple[ArtifactId, ...]
    reason: str


# Keep the acquire lease request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class AcquireLeaseRequest:
    lease_id: Identifier
    roots: tuple[ArtifactId, ...]
    reason: str


# Apply dataclass semantics to the following plan garbage collection request contract.
@dataclass(frozen=True, slots=True)
class PlanGarbageCollectionRequest:
    additional_retained_roots: tuple[ArtifactId, ...] = ()


class ManageRetention:
    """Coordinates authoritative filesystem state with a rebuildable index."""

    def __init__(
        self,
        repository: RetentionRepository,
        index: RetentionIndex,
        root_provider: RetentionRootProvider,
        # Close the init signature after its explicit inputs.
        *,
        policy: GarbageCollectionPolicy,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the manage retention init workflow in explicit, reviewable steps.
        self._repository = repository
        self._index = index
        self._root_provider = root_provider
        self._policy = policy
        self._clock_ns = clock_ns

    # Define manage retention create pin as one focused operation with an explicit
    # boundary.
    def create_pin(self, request: CreatePinRequest) -> PinRecord:
        # Execute the manage retention create pin workflow in explicit, reviewable steps.
        pin = self._repository.create_pin(
            pin_id=request.pin_id,
            roots=request.roots,
            reason=request.reason,
            created_at_ns=self._clock_ns(),
            # Complete create_pin only after its pin id and roots inputs are visible in manage
            # retention create pin.
        )
        # The durable pin is already authoritative.  If indexing fails, the
        # request fails and an idempotent retry repairs the projection.
        self._index.index_active(pin)
        return pin

    def retire_pin(self, pin_id: Identifier) -> PinRecord:
        # Execute the manage retention retire pin workflow in explicit, reviewable steps.
        pin = self._repository.retire_pin(pin_id, retired_at_ns=self._clock_ns())
        self._index.index_retired(pin)
        return pin

    def acquire_lease(self, request: AcquireLeaseRequest) -> ArtifactLease:
        # Execute the manage retention acquire lease workflow in explicit, reviewable
        # steps.
        return self._repository.acquire_lease(
            lease_id=request.lease_id,
            roots=request.roots,
            reason=request.reason,
        )

    # Define manage retention rebuild pin index as one focused operation with an explicit
    # boundary.
    def rebuild_pin_index(self) -> None:
        self._index.rebuild(self._repository.active_pins())

    def plan_garbage_collection(
        self,
        request: PlanGarbageCollectionRequest,
        # Keep the garbage collection plan input explicit in the plan garbage collection
        # contract.
    ) -> GarbageCollectionPlan:
        # Execute the manage retention plan garbage collection workflow in explicit,
        # reviewable steps.
        retained_roots = tuple(
            ArtifactId(value)
            for value in sorted(
                {
                    item.hex
                    # Pass item explicitly so sorted receives a reviewable hex and
                    # additional retained roots input in manage retention plan garbage
                    # collection.
                    for item in (
                        *self._root_provider.retained_roots(),
                        *request.additional_retained_roots,
                    )
                }
                # Complete sorted only after its hex and additional retained roots inputs are
                # visible in manage retention plan garbage collection.
            )
        )
        return self._repository.plan_garbage_collection(
            retained_roots=retained_roots,
            policy=self._policy,
            # Include now ns in the completed manage retention plan garbage collection
            # result.
            now_ns=self._clock_ns(),
        )

    def execute_garbage_collection(
        self,
        plan: GarbageCollectionPlan,
        # Keep the garbage collection batch input explicit in the execute garbage collection
        # contract.
    ) -> GarbageCollectionBatch:
        # Execute the manage retention execute garbage collection workflow in explicit,
        # reviewable steps.
        if plan.policy != self._policy:
            raise ValueError("GC plan does not use the configured host retention policy")
        planned_roots = {item.hex for item in plan.retained_roots}
        current_roots = {item.hex for item in self._root_provider.retained_roots()}
        if not current_roots.issubset(planned_roots):
            # Handle the manage retention execute garbage collection issubset, planned
            # roots and current roots condition as a distinct block.
            raise GarbageCollectionPlanStaleError(
                "host-retained roots changed after dry run; create a new plan"
            )
        return self._repository.execute_garbage_collection(plan, now_ns=self._clock_ns())

    def purge_trash(self, batch_id: Identifier) -> GarbageCollectionReceipt:
        # Return the completed manage retention purge trash result without a hidden
        # fallback.
        return self._repository.purge_trash(batch_id, now_ns=self._clock_ns())


__all__ = [
    "AcquireLeaseRequest",
    "CreatePinRequest",
    "ManageRetention",
    # Keep the plan garbage collection request component named inside the all contract.
    "PlanGarbageCollectionRequest",
]
