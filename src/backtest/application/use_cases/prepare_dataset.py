"""Extract bounded source shards and publish one immutable canonical snapshot."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from backtest.application.canonical_data import (
    # Include prepared snapshot so the canonical data dependency remains explicit.
    PreparedSnapshot,
    ProjectedEventBatch,
    immutable_reuse_evidence,
)
from backtest.application.job_commands import ReusableCanonicalDistribution

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    DatasetPlan,
    DatasetShard,
    ExtractionRequest,
    PlannedCapability,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.canonical import CanonicalSnapshotStore
from backtest.application.ports.projectors import ProtocolProjector
from backtest.application.ports.source import SourceReader
from backtest.domain.identifiers import CapabilityId


# Keep the prepare dataset request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PrepareDatasetRequest:
    plan: DatasetPlan
    reusable_distributions: tuple[ReusableCanonicalDistribution, ...] = ()

    def __post_init__(self) -> None:
        # Execute the prepare dataset request post init workflow in explicit, reviewable
        # steps.
        ordered = tuple(sorted(self.reusable_distributions, key=lambda item: item.shard_ordinal))
        if ordered != self.reusable_distributions:
            raise ValueError("reusable distributions must follow planned shard order")
        ordinals = tuple(item.shard_ordinal for item in ordered)
        if len(ordinals) != len(set(ordinals)):
            # Fail the prepare dataset request post init path with ValueError for one
            # planned shard cannot have multiple reusable distributions when ordinals is
            # true; do not continue ambiguously.
            raise ValueError("one planned shard cannot have multiple reusable distributions")


class PrepareDataset:
    """The only production use case allowed to extract historical rows."""

    def __init__(
        self,
        source: SourceReader,
        projector: ProtocolProjector,
        store: CanonicalSnapshotStore,
        # Close the init signature after its explicit inputs.
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Execute the prepare dataset init workflow in explicit, reviewable steps.
        self._source = source
        self._projector = projector
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, request: PrepareDatasetRequest) -> PreparedSnapshot:
        # Execute the prepare dataset execute workflow in explicit, reviewable steps.
        plan = request.plan
        source_binding = plan.spec.source_evidence_binding
        if (
            source_binding is not None
            and source_binding.projector_digest != self._projector.config_digest
        ):
            raise ValueError("dataset source evidence uses another canonical projector")
        capabilities = {item.capability_id: item for item in plan.spec.capabilities}
        unsupported = tuple(
            capability_id
            for capability_id in capabilities
            # Keep the capability id supports step visible while building unsupported.
            if not self._projector.supports(capability_id)
        )
        if unsupported:
            # Handle the prepare dataset execute unsupported branch as a distinct logical
            # block.
            names = ", ".join(item.value for item in sorted(unsupported, key=str))
            raise ValueError(f"no protocol projector is registered for: {names}")

        extracted_at = self._clock()
        if extracted_at.tzinfo is None or extracted_at.utcoffset() is None:
            raise ValueError("prepare clock must return a timezone-aware datetime")
        # Assemble reuse by ordinal once so the prepare dataset execute workflow shares
        # one value.
        reuse_by_ordinal = {
            item.shard_ordinal: item.artifact_id for item in request.reusable_distributions
        }
        if any(ordinal >= len(plan.spec.shards) for ordinal in reuse_by_ordinal):
            raise ValueError("reusable distribution references an unknown planned shard")
        # Assemble distributions once so the prepare dataset execute workflow shares one
        # value.
        distributions = []
        for shard in plan.spec.shards:
            # Process plan.spec.shards inside the bounded prepare dataset execute loop.
            capability = _capability(capabilities, shard.capability_id)
            event_kind = self._projector.event_kind(shard.capability_id)
            reusable_id = reuse_by_ordinal.get(shard.ordinal)
            if reusable_id is not None:
                # Handle the prepare dataset execute reusable_id is not None branch as a
                # distinct logical block.
                if immutable_reuse_evidence(plan, shard) is None:
                    raise ValueError("resolved command attempts to reuse a mutable source shard")
                distributions.append(
                    self._store.open_reusable_distribution(
                        artifact_id=reusable_id,
                        # Pass plan explicitly so open_reusable_distribution receives a
                        # reviewable bundle id and projector input in prepare dataset
                        # execute.
                        plan=plan,
                        shard=shard,
                        capability=capability,
                        event_kind=event_kind,
                        projector_bundle_id=self._projector.bundle_id,
                        # Complete open_reusable_distribution only after its bundle id and
                        # projector inputs are visible in prepare dataset execute.
                    )
                )
                continue
            distributions.append(
                self._store.publish_distribution(
                    # Pass plan explicitly so publish_distribution receives a reviewable
                    # bundle id and projector input in prepare dataset execute.
                    plan=plan,
                    shard=shard,
                    capability=capability,
                    event_kind=event_kind,
                    projector_bundle_id=self._projector.bundle_id,
                    # Pass batches explicitly to append for publish distribution and
                    # store.
                    batches=self._projected_batches(plan, shard),
                    extracted_at=extracted_at,
                )
            )
        return self._store.publish_snapshot(
            # Pass plan explicitly so publish_snapshot receives a reviewable bundle id and
            # projector input in prepare dataset execute.
            plan=plan,
            projector_bundle_id=self._projector.bundle_id,
            distributions=tuple(distributions),
            extracted_at=extracted_at,
            validator=self._projector,
            # Complete publish_snapshot only after its bundle id and projector inputs are
            # visible in prepare dataset execute.
        )

    def _projected_batches(
        self,
        plan: DatasetPlan,
        shard: DatasetShard,
        # Keep the iterator input explicit in the projected batches contract.
    ) -> Iterator[ProjectedEventBatch]:
        # Execute the prepare dataset projected batches workflow in explicit, reviewable
        # steps.
        request = ExtractionRequest(
            dataset_spec_id=plan.spec.spec_id,
            shard=shard,
            decision_range=plan.spec.decision_range,
            query_limits=plan.query_limits,
        )
        # Assemble saw batch once so the prepare dataset projected batches workflow shares
        # one value.
        saw_batch = False
        for source_batch in self._source.scan(request):
            # Process self._source.scan(request) inside the bounded prepare dataset
            # projected batches loop.
            saw_batch = True
            yield ProjectedEventBatch(
                events=tuple(self._projector.project(source_batch)),
                query_fingerprint=source_batch.query_fingerprint,
            )
        # Guard this path with not saw_batch before applying effects.
        if not saw_batch:
            # Empty extraction remains a real, validated shard. Its missing
            # driver receipt is explicit and never upgrades source completeness.
            yield ProjectedEventBatch(events=(), query_fingerprint=None)


def _capability(
    capabilities: dict[CapabilityId, PlannedCapability],
    capability_id: CapabilityId,
) -> PlannedCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    try:
        return capabilities[capability_id]
    except KeyError:
        raise ValueError(f"planned shard references unknown capability {capability_id}") from None


__all__ = ["PrepareDataset", "PrepareDatasetRequest"]
