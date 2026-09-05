# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from itertools import pairwise

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.application.dataset_plans import (
    DatasetPlanCodecError,
    dataset_plan_bytes,
    dataset_plan_from_bytes,
    # Close the dataset plans import after its required symbols are visible.
)
from backtest.application.errors import (
    BudgetExceededError,
    FidelityMismatchError,
    InvalidJobPayloadError,
    # Close the errors import after its required symbols are visible.
)
from backtest.application.job_commands import (
    PrepareDatasetJobDraft,
    ResolvedJobCommandError,
    ResolvedPrepareDatasetJob,
    # Include reusable canonical distribution so the job commands dependency remains
    # explicit.
    ReusableCanonicalDistribution,
    resolve_job_command,
)
from backtest.application.models import (
    DATASET_SPEC_VERSION,
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    BudgetLimits,
    BudgetStatus,
    CapabilityCutEvidence,
    CapabilityDescriptor,
    # Include capability stream so the models dependency remains explicit.
    CapabilityStream,
    DataRequirement,
    DatasetPlanningPolicy,
    DiskCapacity,
    JobRecord,
    # Include job type so the models dependency remains explicit.
    JobType,
    PlanDatasetRequest,
    QueryLimits,
    RequirementOrigin,
    ResolvedJobSpec,
    # Include source estimate so the models dependency remains explicit.
    SourceEstimate,
    SourceInspection,
    SourceMetadata,
)
from backtest.application.use_cases.plan_dataset import PlanDataset

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    FidelityRequirement,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    CapabilityId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    JobId,
    SourceId,
)
from backtest.domain.time import BlockRange

# Bind capability id once as an explicit module-level contract.
CAPABILITY_ID = CapabilityId("pumpfun.swaps.v1")
SOURCE_ID = SourceId("readonly-indexer")
INSPECTION_ID = ArtifactId("a" * 64)
SECOND_INSPECTION_ID = ArtifactId("e" * 64)
REUSED_DISTRIBUTION_ID = ArtifactId("f" * 64)


# Keep the prepare queue contract and validation rules together.
class _PrepareQueue:
    def __init__(self) -> None:
        self.specs: list[ResolvedJobSpec] = []

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the prepare queue submit workflow in explicit, reviewable steps.
        del idempotency_key
        self.specs.append(spec)
        return JobRecord(
            job_id=JobId(f"prepare-{len(self.specs)}"),
            spec=spec,
            # Pass state explicitly so JobRecord receives a reviewable prepare- and specs
            # input in prepare queue submit.
            state=AttemptState.QUEUED,
            state_version=0,
        )


# Keep the prepare resolver contract and validation rules together.
class _PrepareResolver:
    def resolve(self, draft: PrepareDatasetJobDraft) -> ResolvedPrepareDatasetJob:
        # Execute the prepare resolver resolve workflow in explicit, reviewable steps.
        return ResolvedPrepareDatasetJob(
            draft.plan,
            (ReusableCanonicalDistribution(0, REUSED_DISTRIBUTION_ID),),
        )


def _fidelity() -> SourceFidelity:
    # Execute the fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.CANDIDATE,
        ordering=OrderingFidelity.TRANSACTION_EXACT,
        state=StateFidelity.BEFORE_AFTER,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable candidate
        # and transaction exact input in fidelity.
        chain_finality=ChainFinality.CONFIRMED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.BEST_EFFORT,
    )


def _descriptor() -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=CAPABILITY_ID,
        protocol="pumpfun",
        protocol_version="v2",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable pumpfun and
        # v2 input in descriptor.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("amount", "block_ordinal", "direction", "signature"),
        mandatory_columns=("block_ordinal", "signature"),
        fidelity=_fidelity(),
        total_key=("signature",),
        # Pass keyset key is proven explicitly so CapabilityDescriptor receives a
        # reviewable pumpfun and v2 input in descriptor.
        keyset_key_is_proven=False,
        utc_pruning_column="block_date_utc",
        utc_pruning_is_proven=True,
    )


def _evidence(
    # Close the evidence signature after its explicit inputs.
    *,
    watermark: int = 220,
    observed_cut: int = 220,
    from_block: int = 0,
) -> CapabilityCutEvidence:
    # Execute the evidence workflow in explicit, reviewable steps.
    return CapabilityCutEvidence(
        capability_id=CAPABILITY_ID,
        block_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Pass from block explicitly so BlockRange receives a reviewable solana
            # mainnet network id and block32 transaction32 position schema id input in
            # evidence.
            from_block,
            observed_cut,
        ),
        snapshot_cut_to_block=observed_cut,
        chain_finality=ChainFinality.CONFIRMED,
        # Pass ingestion watermark to block explicitly so CapabilityCutEvidence receives a
        # reviewable confirmed and complete to watermark input in evidence.
        ingestion_watermark_to_block=watermark,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.BEST_EFFORT,
    )


def _inspection(
    # Keep the descriptor input explicit in the inspection contract.
    descriptor: CapabilityDescriptor | None = None,
    *,
    evidence: tuple[CapabilityCutEvidence, ...] = (),
) -> SourceInspection:
    # Execute the inspection workflow in explicit, reviewable steps.
    return SourceInspection(
        metadata=SourceMetadata(
            source_id=SOURCE_ID,
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Pass server version explicitly so SourceMetadata receives a reviewable
            # fixture-v1 and b input in inspection.
            server_version="fixture-v1",
            tables=(),
            capabilities=(descriptor or _descriptor(),),
            capability_mapping_digest=ContentDigest("b" * 64),
            query_template_digest=ContentDigest("c" * 64),
            # Pass cut evidence explicitly so SourceMetadata receives a reviewable
            # fixture-v1 and b input in inspection.
            cut_evidence=evidence,
        ),
        schema_fingerprint=ContentDigest("d" * 64),
        inspected_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


# Keep the inspections contract and validation rules together.
class _Inspections:
    def __init__(self, inspections: dict[ArtifactId, SourceInspection]) -> None:
        self.inspections = inspections

    def load(self, artifact_id: ArtifactId) -> SourceInspection:
        return self.inspections[artifact_id]


# Keep the estimator contract and validation rules together.
class _Estimator:
    def __init__(self, estimate: SourceEstimate) -> None:
        # Execute the estimator init workflow in explicit, reviewable steps.
        self.estimate_value = estimate
        self.calls = 0

    def estimate(self, spec: object) -> SourceEstimate:
        # Execute the estimator estimate workflow in explicit, reviewable steps.
        del spec
        self.calls += 1
        return self.estimate_value


# Keep the disk contract and validation rules together.
class _Disk:
    def __init__(self, free_bytes: int) -> None:
        self.free_bytes = free_bytes

    def capacity(self) -> DiskCapacity:
        return DiskCapacity(self.free_bytes)


# Define requirements as one focused operation with an explicit boundary.
def _requirements() -> tuple[DataRequirement, ...]:
    # Execute the requirements workflow in explicit, reviewable steps.
    return (
        DataRequirement(
            origin=RequirementOrigin.STRATEGY,
            origin_id="simple-threshold-v1",
            capability_id=CAPABILITY_ID,
            # Pass columns explicitly so DataRequirement receives a reviewable simple-
            # threshold-v1 and direction input in requirements.
            columns=("direction", "amount"),
            minimum_fidelity=FidelityRequirement(
                ordering=OrderingFidelity.TRANSACTION_EXACT,
            ),
            accepted_protocol_versions=("v2",),
            # Complete DataRequirement only after its simple-threshold-v1 and direction inputs
            # are visible in requirements.
        ),
        DataRequirement(
            origin=RequirementOrigin.EXECUTION,
            origin_id="shadow-execution-v1",
            capability_id=CAPABILITY_ID,
            # Pass columns explicitly so DataRequirement receives a reviewable shadow-
            # execution-v1 and amount input in requirements.
            columns=("amount",),
            minimum_fidelity=FidelityRequirement(fees=FeesFidelity.COMPONENTS),
            accepted_protocol_versions=("v2",),
        ),
    )


# Define policy as one focused operation with an explicit boundary.
def _policy(
    *,
    max_remote_bytes: int = 10_000,
    max_local_bytes: int = 10_000,
    max_days: int = 7,
    # Keep the temporary reserve bytes input explicit in the policy contract.
    temporary_reserve_bytes: int = 0,
    disk_low_watermark_bytes: int = 0,
    max_total_blocks: int = 10_000,
    max_total_shards: int = 1_000,
    max_shard_blocks: int = 1_000,
    # Keep the query seconds input explicit in the policy contract.
    query_seconds: int = 300,
    query_memory: int = 10_000_000,
    query_rows: int = 10_000,
) -> DatasetPlanningPolicy:
    # Execute the policy workflow in explicit, reviewable steps.
    return DatasetPlanningPolicy(
        budget_limits=BudgetLimits(
            max_remote_bytes=max_remote_bytes,
            max_local_bytes=max_local_bytes,
            max_days=max_days,
            # Pass temporary reserve bytes explicitly so BudgetLimits receives a
            # reviewable max remote bytes and max local bytes input in policy.
            temporary_reserve_bytes=temporary_reserve_bytes,
            disk_low_watermark_bytes=disk_low_watermark_bytes,
        ),
        query_limits=QueryLimits(query_seconds, query_memory, query_rows),
        max_total_blocks=max_total_blocks,
        # Pass max total shards explicitly so DatasetPlanningPolicy receives a reviewable
        # budget limits and query limits input in policy.
        max_total_shards=max_total_shards,
        max_shard_blocks=max_shard_blocks,
    )


def _request(*, inspection_id: ArtifactId = INSPECTION_ID) -> PlanDatasetRequest:
    # Execute the request workflow in explicit, reviewable steps.
    return PlanDatasetRequest(
        source_id=SOURCE_ID,
        source_inspection_artifact_id=inspection_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include decision range in the completed request result.
        decision_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            100,
            220,
            # Complete BlockRange only after its solana mainnet network id and block32
            # transaction32 position schema id inputs are visible in request.
        ),
        warmup_blocks=20,
        settlement_tail_blocks=0,
        max_shard_blocks=50,
        requested_days=2,
        # Include requirements in the completed request result.
        requirements=_requirements(),
        budget_limits=BudgetLimits(
            max_remote_bytes=1_000,
            max_local_bytes=1_000,
            max_days=7,
            # Pass temporary reserve bytes explicitly into BudgetLimits within request.
            temporary_reserve_bytes=100,
            disk_low_watermark_bytes=100,
        ),
        query_limits=QueryLimits(
            max_execution_seconds=30,
            # Pass max memory bytes explicitly into QueryLimits within request.
            max_memory_bytes=1_000_000,
            max_result_rows=5_000,
        ),
        request_remote_estimate=True,
    )


# Define planner as one focused operation with an explicit boundary.
def _planner(
    inspection: SourceInspection | None = None,
    *,
    policy: DatasetPlanningPolicy | None = None,
    estimator: _Estimator | None = None,
    # Keep the disk input explicit in the planner contract.
    disk: _Disk | None = None,
) -> PlanDataset:
    # Execute the planner workflow in explicit, reviewable steps.
    return PlanDataset(
        _Inspections({INSPECTION_ID: inspection or _inspection()}),
        policy or _policy(),
        estimator=estimator,
        disk_probe=disk or _Disk(10_000),
        # Complete PlanDataset only after its inspections and inspection inputs are visible in
        # planner.
    )


def test_plan_merges_requirements_and_builds_gapless_half_open_shards() -> None:
    # Execute the test plan merges requirements and builds gapless half open shards
    # workflow in explicit, reviewable steps.
    estimator = _Estimator(SourceEstimate(100, 500, 250, 25, 1_000))
    plan = _planner(estimator=estimator).execute(_request())

    assert plan.budget.status is BudgetStatus.PASS
    assert plan.query_limits == _request().query_limits
    assert plan.spec.spec_version == DATASET_SPEC_VERSION
    # Verify the source inspection artifact id, inspection id and spec relationship before
    # this scenario is accepted.
    assert plan.spec.source_inspection_artifact_id == INSPECTION_ID
    assert plan.spec.capability_mapping_digest == ContentDigest("b" * 64)
    assert plan.spec.capability_ranges[0].block_range == BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Keep block range, solana mainnet network id and block32 transaction32 position
        # schema id visible while completing BlockRange within test plan merges
        # requirements and builds gapless half open shards.
        80,
        220,
    )
    assert plan.spec.capabilities[0].columns == (
        "amount",
        # Keep the block ordinal expectation tied to columns, amount and block ordinal in
        # this scenario.
        "block_ordinal",
        "direction",
        "signature",
    )
    assert plan.spec.capabilities[0].fidelity.completeness is IngestionCompleteness.UNKNOWN
    # Verify the block range, shard and shards relationship before this scenario is
    # accepted.
    assert [shard.block_range for shard in plan.spec.shards] == [
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            80,
            # Keep block range, solana mainnet network id and block32 transaction32
            # position schema id visible while completing BlockRange within test plan
            # merges requirements and builds gapless half open shards.
            130,
        ),
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Keep block range, solana mainnet network id and block32 transaction32
            # position schema id visible while completing BlockRange within test plan
            # merges requirements and builds gapless half open shards.
            130,
            180,
        ),
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            # Pass block32 transaction32 position schema id explicitly so BlockRange
            # receives a reviewable solana mainnet network id and block32 transaction32
            # position schema id input in test plan merges requirements and builds gapless
            # half open shards.
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            180,
            220,
        ),
    ]
    # Verify the to block ordinal, from block ordinal and block range relationship before
    # this scenario is accepted.
    assert all(
        left.block_range.to_block_ordinal == right.block_range.from_block_ordinal
        for left, right in pairwise(plan.spec.shards)
    )
    assert estimator.calls == 1


# Define test plan identity is versioned validated and requirement order independent as
# one focused operation with an explicit boundary.
def test_plan_identity_is_versioned_validated_and_requirement_order_independent() -> None:
    # Execute the test plan identity is versioned validated and requirement order
    # independent workflow in explicit, reviewable steps.
    estimator = _Estimator(SourceEstimate(100, 500, 250, 25))
    use_case = _planner(estimator=estimator)
    request = _request()

    first = use_case.execute(request)
    second = use_case.execute(replace(request, requirements=tuple(reversed(request.requirements))))

    # Verify first.spec == second.spec before this scenario is accepted.
    assert first.spec == second.spec
    with pytest.raises(ValueError, match="unsupported dataset spec version"):
        replace(first.spec, spec_version=1)
    with pytest.raises(ValueError, match="spec_id"):
        replace(first.spec, spec_id=ContentDigest("0" * 64))


# Define test exact inspection artifact pin participates in plan identity as one focused
# operation with an explicit boundary.
def test_exact_inspection_artifact_pin_participates_in_plan_identity() -> None:
    # Execute the test exact inspection artifact pin participates in plan identity
    # workflow in explicit, reviewable steps.
    inspection = _inspection()
    use_case = PlanDataset(
        _Inspections({INSPECTION_ID: inspection, SECOND_INSPECTION_ID: inspection}),
        _policy(),
        disk_probe=_Disk(10_000),
        # Complete PlanDataset only after its inspections and policy inputs are visible in
        # test exact inspection artifact pin participates in plan identity.
    )

    first = use_case.execute(replace(_request(), request_remote_estimate=False))
    second = use_case.execute(
        replace(
            _request(inspection_id=SECOND_INSPECTION_ID),
            # Pass request remote estimate explicitly so replace receives a reviewable
            # request and second inspection id input in test exact inspection artifact pin
            # participates in plan identity.
            request_remote_estimate=False,
        )
    )

    assert first.spec.spec_id != second.spec.spec_id


def test_remote_estimator_is_not_called_unless_explicitly_requested() -> None:
    # Execute the test remote estimator is not called unless explicitly requested workflow
    # in explicit, reviewable steps.
    estimator = _Estimator(SourceEstimate(100, 500, 250, 25))
    plan = _planner(estimator=estimator).execute(replace(_request(), request_remote_estimate=False))

    assert estimator.calls == 0
    assert plan.budget.status is BudgetStatus.UNKNOWN


def test_hard_budget_violation_fails_with_full_report() -> None:
    # Execute the test hard budget violation fails with full report workflow in explicit,
    # reviewable steps.
    estimator = _Estimator(SourceEstimate(100, 1_001, 250, 25))

    with pytest.raises(BudgetExceededError) as caught:
        _planner(estimator=estimator).execute(_request())

    assert caught.value.report.status is BudgetStatus.REJECTED
    assert any(issue.code == "REMOTE_BYTES" for issue in caught.value.report.issues)


# Define test insufficient structural fidelity fails before estimate as one focused
# operation with an explicit boundary.
def test_insufficient_structural_fidelity_fails_before_estimate() -> None:
    # Execute the test insufficient structural fidelity fails before estimate workflow in
    # explicit, reviewable steps.
    estimator = _Estimator(SourceEstimate(100, 500, 250, 25))
    descriptor = replace(
        _descriptor(),
        fidelity=replace(_fidelity(), ordering=OrderingFidelity.TRANSACTION_PARTIAL),
    )

    # Acquire raises, fidelity mismatch error and pytest at an explicit test insufficient
    # structural fidelity fails before estimate context boundary so cleanup remains
    # scoped.
    with pytest.raises(FidelityMismatchError) as caught:
        _planner(_inspection(descriptor), estimator=estimator).execute(_request())

    assert caught.value.capability_id == CAPABILITY_ID
    assert caught.value.gaps[0].field == "ordering"
    assert estimator.calls == 0


# Define test cut dependent fidelity requires exact committed watermark evidence as one
# focused operation with an explicit boundary.
def test_cut_dependent_fidelity_requires_exact_committed_watermark_evidence() -> None:
    # Execute the test cut dependent fidelity requires exact committed watermark evidence
    # workflow in explicit, reviewable steps.
    complete_requirement = replace(
        _requirements()[0],
        minimum_fidelity=FidelityRequirement(
            completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK
        ),
        # Complete replace only after its complete to watermark and requirements inputs are
        # visible in test cut dependent fidelity requires exact committed watermark evidence.
    )
    request = replace(
        _request(),
        requirements=(complete_requirement, _requirements()[1]),
        request_remote_estimate=False,
        # Complete replace only after its request and requirements inputs are visible in test
        # cut dependent fidelity requires exact committed watermark evidence.
    )

    with pytest.raises(FidelityMismatchError):
        _planner(_inspection()).execute(request)
    with pytest.raises(FidelityMismatchError):
        _planner(_inspection(evidence=(_evidence(watermark=219),))).execute(request)
    # Acquire raises, fidelity mismatch error and pytest at an explicit test cut dependent
    # fidelity requires exact committed watermark evidence context boundary so cleanup
    # remains scoped.
    with pytest.raises(FidelityMismatchError):
        _planner(_inspection(evidence=(_evidence(from_block=81),))).execute(request)

    plan = _planner(_inspection(evidence=(_evidence(),))).execute(request)

    assert plan.spec.capabilities[0].fidelity.completeness is (
        IngestionCompleteness.COMPLETE_TO_WATERMARK
        # Verify the completeness, complete to watermark and fidelity relationship before this
        # scenario is accepted.
    )
    assert plan.spec.cut_evidence == (_evidence(),)


def test_request_can_only_lower_host_budget_query_and_shard_ceilings() -> None:
    # Execute the test request can only lower host budget query and shard ceilings
    # workflow in explicit, reviewable steps.
    policy = _policy(
        max_remote_bytes=600,
        max_local_bytes=700,
        max_days=3,
        temporary_reserve_bytes=200,
        # Pass disk low watermark bytes explicitly into _policy within test request can
        # only lower host budget query and shard ceilings.
        disk_low_watermark_bytes=300,
        max_shard_blocks=40,
        query_seconds=20,
        query_memory=500_000,
        query_rows=2_000,
        # Complete _policy only after its declared inputs are visible in test request can only
        # lower host budget query and shard ceilings.
    )
    request = replace(
        _request(),
        budget_limits=BudgetLimits(5_000, 5_000, 10, 0, 0),
        query_limits=QueryLimits(100, 5_000_000, 9_000),
        # Pass requested days explicitly so replace receives a reviewable request and
        # budget limits input in test request can only lower host budget query and shard
        # ceilings.
        requested_days=2,
        request_remote_estimate=False,
    )

    plan = _planner(policy=policy, disk=_Disk(10_000)).execute(request)

    assert plan.budget.max_remote_bytes == 600
    # Verify plan.budget.max_local_bytes == 700 before this scenario is accepted.
    assert plan.budget.max_local_bytes == 700
    assert plan.budget.max_days == 3
    assert plan.budget.temporary_reserve_bytes == 200
    assert plan.budget.disk_low_watermark_bytes == 300
    assert plan.budget.max_shard_blocks == 40
    # Verify the span, shard and shards relationship before this scenario is accepted.
    assert all(shard.block_range.span <= 40 for shard in plan.spec.shards)
    assert plan.query_limits == QueryLimits(20, 500_000, 2_000)


def test_total_block_and_shard_hard_ceilings_are_independent() -> None:
    # Execute the test total block and shard hard ceilings are independent workflow in
    # explicit, reviewable steps.
    request = replace(_request(), requested_days=1, request_remote_estimate=False)

    with pytest.raises(BudgetExceededError) as blocks:
        _planner(policy=_policy(max_total_blocks=139)).execute(request)
    assert any(issue.code == "TOTAL_BLOCKS" for issue in blocks.value.report.issues)

    with pytest.raises(BudgetExceededError) as shards:
        # Invoke execute for request as a visible test total block and shard hard ceilings
        # are independent step.
        _planner(policy=_policy(max_total_blocks=1_000, max_total_shards=2)).execute(request)
    assert any(issue.code == "TOTAL_SHARDS" for issue in shards.value.report.issues)


def test_known_disk_lower_bound_rejects_even_when_estimates_are_unknown() -> None:
    # Execute the test known disk lower bound rejects even when estimates are unknown
    # workflow in explicit, reviewable steps.
    policy = _policy(temporary_reserve_bytes=400, disk_low_watermark_bytes=300)

    with pytest.raises(BudgetExceededError) as caught:
        # Keep raises, budget exceeded error and pytest active only for the bounded test
        # known disk lower bound rejects even when estimates are unknown operation.
        _planner(policy=policy, disk=_Disk(699)).execute(
            replace(_request(), request_remote_estimate=False)
        )

    assert any(issue.code == "FREE_DISK_LOWER_BOUND" for issue in caught.value.report.issues)


@pytest.mark.parametrize("start,end,max_span", [(0, 1, 1), (1, 101, 7), (99, 100, 1000)])
# Define test block split never creates gap or overlap as one focused operation with an
# explicit boundary.
def test_block_split_never_creates_gap_or_overlap(start: int, end: int, max_span: int) -> None:
    # Execute the test block split never creates gap or overlap workflow in explicit,
    # reviewable steps.
    original = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        start,
        end,
        # Complete BlockRange only after its solana mainnet network id and block32
        # transaction32 position schema id inputs are visible in test block split never
        # creates gap or overlap.
    )
    shards = original.split(max_span)

    assert shards[0].from_block_ordinal == start
    assert shards[-1].to_block_ordinal == end
    assert all(shard.span <= max_span for shard in shards)
    # Verify the to block ordinal, from block ordinal and left relationship before this
    # scenario is accepted.
    assert all(
        left.to_block_ordinal == right.from_block_ordinal for left, right in pairwise(shards)
    )


def test_dataset_plan_codec_round_trips_and_prepare_derives_exact_inspection_input() -> None:
    # Execute the test dataset plan codec round trips and prepare derives exact inspection
    # input workflow in explicit, reviewable steps.
    plan = _planner(estimator=_Estimator(SourceEstimate(100, 500, 250, 25, 1_000))).execute(
        _request()
    )
    payload = dataset_plan_bytes(plan)

    assert dataset_plan_from_bytes(payload) == plan
    # Assemble command once so the test dataset plan codec round trips and prepare derives
    # exact inspection input workflow shares one value.
    command = ResolvedPrepareDatasetJob(plan)
    resolved = resolve_job_command(JobType.PREPARE_DATASET, command.canonical_bytes())
    assert resolved.input_artifact_ids == (INSPECTION_ID,)


def test_prepare_v1_is_controller_resolved_to_one_canonical_v2_spec() -> None:
    # Execute the test prepare v1 is controller resolved to one canonical v2 spec workflow
    # in explicit, reviewable steps.
    plan = _planner(estimator=_Estimator(SourceEstimate(100, 500, 250, 25, 1_000))).execute(
        _request()
    )
    draft = PrepareDatasetJobDraft(plan)
    formatted = json.dumps(json.loads(draft.canonical_bytes()), indent=2).encode()
    # Assemble queue once so the test prepare v1 is controller resolved to one canonical
    # v2 spec workflow shares one value.
    queue = _PrepareQueue()
    submit = SubmitJob(queue, _PrepareResolver())

    first = submit.execute(
        SubmitJobRequest(1, JobType.PREPARE_DATASET, formatted, "prepare-formatted")
    )
    # Assemble second once so the test prepare v1 is controller resolved to one canonical
    # v2 spec workflow shares one value.
    second = submit.execute(
        SubmitJobRequest(1, JobType.PREPARE_DATASET, draft.canonical_bytes(), "prepare-canonical")
    )

    expected = ResolvedPrepareDatasetJob(
        plan,
        # Keep the reusable canonical distribution and reused distribution id
        # ReusableCanonicalDistribution step visible while building expected.
        (ReusableCanonicalDistribution(0, REUSED_DISTRIBUTION_ID),),
    )
    assert first.spec == second.spec
    assert first.spec.canonical_payload == expected.canonical_bytes()
    assert first.spec.input_artifact_ids == tuple(
        # Keep the key expectation tied to input artifact ids, spec and first in this
        # scenario.
        sorted((INSPECTION_ID, REUSED_DISTRIBUTION_ID), key=lambda item: item.hex)
    )
    with pytest.raises(ResolvedJobCommandError):
        resolve_job_command(JobType.PREPARE_DATASET, draft.canonical_bytes())
    with pytest.raises(InvalidJobPayloadError):
        # Keep raises, invalid job payload error and pytest active only for the bounded
        # test prepare v1 is controller resolved to one canonical v2 spec operation.
        submit.execute(
            SubmitJobRequest(
                1,
                JobType.PREPARE_DATASET,
                expected.canonical_bytes(),
                # Pass public-v2-forbidden explicitly so SubmitJobRequest receives a
                # reviewable public-v2-forbidden and prepare dataset input in test prepare
                # v1 is controller resolved to one canonical v2 spec.
                "public-v2-forbidden",
            )
        )


def test_dataset_plan_codec_rejects_noncanonical_unknown_and_forged_identity() -> None:
    # Execute the test dataset plan codec rejects noncanonical unknown and forged identity
    # workflow in explicit, reviewable steps.
    plan = _planner(estimator=_Estimator(SourceEstimate(100, 500, 250, 25, 1_000))).execute(
        _request()
    )
    payload = dataset_plan_bytes(plan)

    with pytest.raises(DatasetPlanCodecError, match="canonical"):
        # Invoke dataset_plan_from_bytes for encode and dumps as a visible test dataset
        # plan codec rejects noncanonical unknown and forged identity step.
        dataset_plan_from_bytes(json.dumps(json.loads(payload), indent=2).encode())

    unknown = json.loads(payload)
    unknown["opaque_path"] = "/tmp/not-executable"
    with pytest.raises(DatasetPlanCodecError, match="schema"):
        dataset_plan_from_bytes(canonical_json_bytes(unknown))

    # Assemble forged once so the test dataset plan codec rejects noncanonical unknown and
    # forged identity workflow shares one value.
    forged = json.loads(payload)
    forged["spec"]["spec_id"] = "f" * 64
    with pytest.raises(DatasetPlanCodecError, match="fields"):
        dataset_plan_from_bytes(canonical_json_bytes(forged))
