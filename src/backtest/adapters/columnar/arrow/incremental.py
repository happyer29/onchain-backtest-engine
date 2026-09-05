"""Gap-safe controller resolution of immutable canonical shard reuse."""

from __future__ import annotations

from backtest.adapters.columnar.arrow.canonical import (
    canonical_distribution_build_key,
    canonical_writer_bundle_id,
)

# Import build tool roles at the visible module dependency boundary.
from backtest.application.build_tool_roles import CANONICAL_WRITER_ROLE
from backtest.application.canonical_data import ValidationStatus, immutable_reuse_evidence
from backtest.application.code_bundles import (
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
    # Close the code bundles import after its required symbols are visible.
)
from backtest.application.job_commands import (
    PrepareDatasetJobDraft,
    ResolvedPrepareDatasetJob,
    ReusableCanonicalDistribution,
    # Close the job commands import after its required symbols are visible.
)
from backtest.application.models import DatasetShard, PlannedCapability
from backtest.application.ports.job_resolution import PrepareDatasetJobResolver
from backtest.application.ports.projectors import ProtocolProjector
from backtest.application.ports.shard_ledger import ShardLedger

# Import source ledger at the visible module dependency boundary.
from backtest.application.source_ledger import CommittedShardRevision
from backtest.domain.identifiers import ArtifactId, ContentDigest, SourceId


class IncrementalPrepareResolutionError(RuntimeError):
    """The rebuildable shard index contains an ambiguous exact reuse mapping."""


class GapSafePrepareDatasetJobResolver(PrepareDatasetJobResolver):
    """Resolve a public draft without letting a cached shard jump a gap."""

    def __init__(
        self,
        ledger: ShardLedger,
        projector: ProtocolProjector,
        *,
        # Keep the build tools input explicit in the init contract.
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the gap safe prepare dataset job resolver init workflow in explicit,
        # reviewable steps.
        self._ledger = ledger
        self._projector = projector
        self._build_tools = build_tools or PinnedCodeBundleSet(
            (
                PinnedCodeBundleIdentity.for_unit_tests(
                    # Pass canonical writer role explicitly so for_unit_tests receives a
                    # reviewable canonical writer bundle id and canonical writer role
                    # input in gap safe prepare dataset job resolver init.
                    CANONICAL_WRITER_ROLE,
                    canonical_writer_bundle_id(),
                ),
            )
        )

    # Define gap safe prepare dataset job resolver resolve as one focused operation with
    # an explicit boundary.
    def resolve(self, draft: PrepareDatasetJobDraft) -> ResolvedPrepareDatasetJob:
        # Execute the gap safe prepare dataset job resolver resolve workflow in explicit,
        # reviewable steps.
        plan = draft.plan
        writer_bundle_id = self._build_tools.require_current(CANONICAL_WRITER_ROLE)
        capabilities = {item.capability_id: item for item in plan.spec.capabilities}
        capability_ranges = {
            item.capability_id: item.block_range
            # Keep the item component named inside the capability ranges contract.
            for item in plan.spec.capability_ranges
            # Complete the capability ranges group only after its semantic components are
            # visible.
        }
        frontiers = {
            capability.capability_id: self._ledger.contiguous_frontier(
                source_id=plan.spec.source_id,
                capability_id=capability.capability_id,
                # Pass capability schema version explicitly so contiguous_frontier
                # receives a reviewable source id and spec input in gap safe prepare
                # dataset job resolver resolve.
                capability_schema_version=capability.schema_version,
                network_id=plan.spec.network_id,
                position_schema_id=plan.spec.position_schema_id,
                coverage_from_block_ordinal=capability_ranges[
                    capability.capability_id
                    # Close the source id and spec payload only after all gap safe prepare
                    # dataset job resolver resolve fields are present.
                ].from_block_ordinal,
            ).frontier_block_ordinal
            for capability in plan.spec.capabilities
        }
        reusable: list[ReusableCanonicalDistribution] = []
        # Traverse plan.spec.shards explicitly so each gap safe prepare dataset job
        # resolver resolve iteration remains traceable.
        for shard in plan.spec.shards:
            # Process plan.spec.shards inside the bounded gap safe prepare dataset job
            # resolver resolve loop.
            capability = capabilities[shard.capability_id]
            evidence = immutable_reuse_evidence(plan, shard)
            if (
                evidence is None
                or shard.block_range.to_block_ordinal > frontiers[shard.capability_id]
                # Evaluate the complete gap safe prepare dataset job resolver resolve
                # evidence, to block ordinal and block range condition before guarded effects.
            ):
                continue
            event_kind = self._projector.event_kind(shard.capability_id)
            expected_build_key = canonical_distribution_build_key(
                plan=plan,
                # Pass shard explicitly so canonical_distribution_build_key receives a
                # reviewable bundle id and projector input in gap safe prepare dataset job
                # resolver resolve.
                shard=shard,
                capability=capability,
                event_kind=event_kind,
                projector_bundle_id=self._projector.bundle_id,
                writer_bundle_id=writer_bundle_id,
                # Complete canonical_distribution_build_key only after its bundle id and
                # projector inputs are visible in gap safe prepare dataset job resolver
                # resolve.
            )
            candidates = tuple(
                item
                for item in self._ledger.committed_revisions(
                    source_id=plan.spec.source_id,
                    # Pass capability id explicitly so committed_revisions receives a
                    # reviewable source id and spec input in gap safe prepare dataset job
                    # resolver resolve.
                    capability_id=shard.capability_id,
                    capability_schema_version=capability.schema_version,
                    block_range=shard.block_range,
                )
                if _matches_exact_reuse(
                    # Pass item explicitly so _matches_exact_reuse receives a reviewable
                    # source id and spec input in gap safe prepare dataset job resolver
                    # resolve.
                    item,
                    source_id=plan.spec.source_id,
                    plan_source_inspection_id=plan.spec.source_inspection_artifact_id,
                    shard=shard,
                    capability=capability,
                    # Pass upstream revision explicitly so _matches_exact_reuse receives a
                    # reviewable source id and spec input in gap safe prepare dataset job
                    # resolver resolve.
                    upstream_revision=evidence.upstream_revision,
                    ingestion_watermark_to_block=evidence.ingestion_watermark_to_block,
                    expected_build_key=expected_build_key,
                )
            )
            # Guard this path with len(candidates) > 1 before applying effects.
            if len(candidates) > 1:
                # Handle the gap safe prepare dataset job resolver resolve len(candidates)
                # > 1 branch as a distinct logical block.
                raise IncrementalPrepareResolutionError(
                    "one immutable source shard resolves to multiple verified artifacts"
                )
            if candidates:
                # Handle the gap safe prepare dataset job resolver resolve candidates
                # branch as a distinct logical block.
                reusable.append(
                    ReusableCanonicalDistribution(
                        shard_ordinal=shard.ordinal,
                        artifact_id=candidates[0].artifact.artifact_id,
                    )
                    # Complete append only after its ordinal and artifact id inputs are
                    # visible in gap safe prepare dataset job resolver resolve.
                )
        return ResolvedPrepareDatasetJob(plan, tuple(reusable))


def _matches_exact_reuse(
    revision: CommittedShardRevision,
    *,
    # Keep the source id input explicit in the matches exact reuse contract.
    source_id: SourceId,
    plan_source_inspection_id: ArtifactId,
    shard: DatasetShard,
    capability: PlannedCapability,
    upstream_revision: str | None,
    # Keep the ingestion watermark to block input explicit in the matches exact reuse
    # contract.
    ingestion_watermark_to_block: int | None,
    expected_build_key: ContentDigest,
) -> bool:
    # Execute the matches exact reuse workflow in explicit, reviewable steps.
    boundary = revision.boundary
    return (
        boundary.source_id == source_id
        and boundary.capability_id == shard.capability_id
        and boundary.capability_schema_version == capability.schema_version
        # Include block range in the completed matches exact reuse result.
        and boundary.block_range == shard.block_range
        and boundary.chain_finality is capability.fidelity.chain_finality
        and boundary.completeness is capability.fidelity.completeness
        and boundary.source_consistency is capability.fidelity.consistency
        and boundary.ingestion_watermark_to_block == ingestion_watermark_to_block
        # Include upstream revision in the completed matches exact reuse result.
        and boundary.upstream_revision == upstream_revision
        and boundary.validation_status is ValidationStatus.PASS
        and revision.artifact.build_key == expected_build_key
        and revision.artifact.input_artifact_ids == (plan_source_inspection_id,)
    )


# Bind all once as an explicit module-level contract.
__all__ = ["GapSafePrepareDatasetJobResolver", "IncrementalPrepareResolutionError"]
