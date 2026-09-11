# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import replace
from inspect import iscoroutinefunction
from pathlib import Path
from typing import cast

import pytest

# Import testclient at the visible module dependency boundary.
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backtest.adapters.artifacts.localfs import LocalArtifactRepository, LocalDiskCapacityProbe
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.source.in_memory import InMemorySourceReader

# Import errors at the visible module dependency boundary.
from backtest.application.errors import (
    ErrorCode,
    IdempotencyConflictError,
    JobStateConflictError,
    SourceEvidenceValidationError,
)
from backtest.application.job_commands import (
    ResolvedBacktestJob,
    resolved_backtest_job_from_bytes,
)

# Import job views at the visible module dependency boundary.
from backtest.application.job_views import JobStatusView, job_input_artifact_ids_digest
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.ml_reference import ReferenceMlContract
from backtest.application.models import (
    AttemptState,
    # Include budget limits so the models dependency remains explicit.
    BudgetLimits,
    CapabilityDescriptor,
    CapabilityStream,
    DatasetPlanningPolicy,
    JobAttempt,
    # Include job event record so the models dependency remains explicit.
    JobEventRecord,
    JobProgressDetails,
    JobRecord,
    JobType,
    ProgressLevel,
    # Include progress stage so the models dependency remains explicit.
    ProgressStage,
    QueryLimits,
    ResolvedJobSpec,
    ResourceCapacity,
    SourceMetadata,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.jobs import JobListCursor
from backtest.application.ports.run_results import RoundTripCursor, RoundTripPage
from backtest.application.run_drafts import ReferenceRunDraft
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import (
    # Include asset balance so the run specs dependency remains explicit.
    AssetBalance,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.use_cases.cancel_job import CancelJob
from backtest.application.use_cases.inspect_source import InspectSource
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.query_job_events import ListJobEvents

# Import query jobs at the visible module dependency boundary.
from backtest.application.use_cases.query_jobs import GetJob, ListJobs
from backtest.application.use_cases.query_run_results import (
    PumpfunSnipingDashboardView,
    PumpfunSnipingRunSummaryView,
    QueryRunResults,
    RunResultQueryError,
    # Close the query run results import after its required symbols are visible.
)
from backtest.application.use_cases.query_runs import QueryRuns, RunIndexQueryError
from backtest.application.use_cases.query_strategy_results import QueryStrategyResults
from backtest.application.use_cases.resolve_run_spec import ResolveRunSpec
from backtest.application.use_cases.resolve_sweep_spec import ResolveSweepSpec
from backtest.application.use_cases.retry_job import RetryJob
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJob
from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    # Include attempt id so the identifiers dependency remains explicit.
    AttemptId,
    BundleId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    # Include execution attempt id so the identifiers dependency remains explicit.
    ExecutionAttemptId,
    JobId,
    LogicalContentHash,
    LogicalRunId,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
    SourceId,
    VenueId,
)
from backtest.domain.ledger import LedgerCorrelationKind
from backtest.domain.roundtrips import (
    # Include mtm status so the roundtrips dependency remains explicit.
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    RoundTripLegSide,
    RoundTripRecord,
    RoundTripStatus,
    # Include token account lifecycle so the roundtrips dependency remains explicit.
)
from backtest.engine.sniping import SnipingValuationStatus
from backtest.interfaces.api import ControlUseCases, create_app
from backtest.interfaces.api.schemas import (
    # Include job list response so the schemas dependency remains explicit.
    JobListResponse,
    JobResponse,
    RequirementInput,
    RoundTripResponse,
)


# Keep the memory jobs contract and validation rules together.
class MemoryJobs:
    def __init__(self) -> None:
        # Execute the memory jobs init workflow in explicit, reviewable steps.
        self.records: dict[JobId, JobRecord] = {}
        self.idempotency: dict[tuple[JobType, str], JobRecord] = {}
        self.events: dict[JobId, tuple[JobEventRecord, ...]] = {}

    def submit(self, spec: ResolvedJobSpec, idempotency_key: str) -> JobRecord:
        # Execute the memory jobs submit workflow in explicit, reviewable steps.
        idempotency_scope = (spec.job_type, idempotency_key)
        existing = self.idempotency.get(idempotency_scope)
        if existing is not None:
            # Handle the memory jobs submit existing is not None branch as a distinct
            # logical block.
            if existing.spec.spec_id != spec.spec_id:
                raise IdempotencyConflictError(spec.job_type, idempotency_key)
            return existing
        job_id = JobId(f"job_{len(self.records) + 1}")
        record = JobRecord(job_id, spec, AttemptState.QUEUED, 0)
        # Assemble self records[job id] once so the memory jobs submit workflow shares one
        # value.
        self.records[job_id] = record
        self.idempotency[idempotency_scope] = record
        return record

    def request_cancel(self, job_id: JobId) -> None:
        # Execute the memory jobs request cancel workflow in explicit, reviewable steps.
        current = self.records[job_id]
        self.records[job_id] = JobRecord(
            job_id=current.job_id,
            spec=current.spec,
            state=AttemptState.CANCELLED,
            # Pass state version explicitly so JobRecord receives a reviewable job id and
            # spec input in memory jobs request cancel.
            state_version=current.state_version + 1,
        )

    def get_job(self, job_id: JobId) -> JobRecord | None:
        return self.records.get(job_id)

    def list_jobs(
        # Keep the remaining list jobs inputs visible at the memory jobs list jobs
        # boundary.
        self,
        *,
        state: AttemptState | None = None,
        limit: int = 100,
        offset: int = 0,
        after: JobListCursor | None = None,
        # Keep the tuple input explicit in the list jobs contract.
    ) -> tuple[JobRecord, ...]:
        # Execute the memory jobs list jobs workflow in explicit, reviewable steps.
        records = tuple(
            sorted(
                self.records.values(),
                key=lambda item: (item.submitted_at_ns, item.job_id.value),
                reverse=True,
            )
        )
        if state is not None:
            records = tuple(item for item in records if item.state is state)
        if after is not None:
            # Resume only below the exclusive descending composite key.
            cursor_key = (after.submitted_at_ns, after.job_id.value)
            records = tuple(
                item for item in records if (item.submitted_at_ns, item.job_id.value) < cursor_key
            )
        return records[offset : offset + limit]

    def claim_next(
        # Keep the remaining claim next inputs visible at the memory jobs claim next
        # boundary.
        self,
        supervisor_instance_id: str,
        capacity: ResourceCapacity,
    ) -> JobAttempt | None:
        # Execute the memory jobs claim next workflow in explicit, reviewable steps.
        del supervisor_instance_id, capacity
        raise NotImplementedError

    def transition(
        self,
        attempt_id: AttemptId,
        # Keep the expected version input explicit in the transition contract.
        expected_version: int,
        new_state: AttemptState,
        result_artifact_id: ArtifactId | None = None,
    ) -> JobAttempt:
        # Execute the memory jobs transition workflow in explicit, reviewable steps.
        del attempt_id, expected_version, new_state, result_artifact_id
        raise NotImplementedError

    def request_retry(self, job_id: JobId) -> JobRecord:
        # Execute the memory jobs request retry workflow in explicit, reviewable steps.
        current = self.records[job_id]
        if current.state not in {AttemptState.FAILED, AttemptState.INTERRUPTED}:
            raise JobStateConflictError(job_id, current.state, "retry")
        retried = JobRecord(
            current.job_id,
            # Pass current explicitly so JobRecord receives a reviewable job id and spec
            # input in memory jobs request retry.
            current.spec,
            AttemptState.QUEUED,
            current.state_version + 1,
        )
        self.records[job_id] = retried
        # Return the completed memory jobs request retry result without a hidden fallback.
        return retried

    def list_job_events(
        self,
        job_id: JobId,
        *,
        # Keep the after event id input explicit in the list job events contract.
        after_event_id: int = 0,
        limit: int = 200,
    ) -> tuple[JobEventRecord, ...]:
        # Execute the memory jobs list job events workflow in explicit, reviewable steps.
        return tuple(
            event for event in self.events.get(job_id, ()) if event.event_id > after_event_id
        )[:limit]


def _resolved_spec() -> ResolvedRunSpec:
    # Execute the resolved spec workflow in explicit, reviewable steps.
    roles = (
        "clock",
        "engine",
        "execution",
        "inference",
        # Keep the latency component named inside the roles contract.
        "latency",
        "protocol:reference",
        "risk",
        "scheduler",
        "strategy",
        # Keep the universe component named inside the roles contract.
        "universe",
        "valuation:price_source",
    )
    components = tuple(
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable x and inference input
            # in resolved spec.
            role=role,
            bundle_id=BundleId(f"{index:x}" * 64),
            config=(
                ExactInferencePolicy.disabled().document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
        )
        # Keep the roles enumerate step visible while building components.
        for index, role in enumerate(roles, start=1)
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include dataset revision id in the completed resolved spec result.
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable 1 and 2 input in
        # resolved spec.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
    )


# Define job command as one focused operation with an explicit boundary.
def _job_command(*, attempt: str = "a") -> dict[str, object]:
    # Execute the job command workflow in explicit, reviewable steps.
    payload = ResolvedBacktestJob(
        _resolved_spec(),
        ContentDigest(attempt * 64),
        RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1),
    ).canonical_bytes()
    # Return the completed job command result without a hidden fallback.
    return {"job_type": "RUN_BACKTEST", "payload": json.loads(payload)}


def _run_draft_document() -> dict[str, object]:
    # Execute the run draft document workflow in explicit, reviewable steps.
    return {
        "snapshot_id": "3" * 64,
        "replay_pack_id": None,
        "delivery_schedule_id": None,
        "pool_id": "pool-1",
        # Include sold asset id in the completed run draft document result.
        "sold_asset_id": "SOL",
        "bought_asset_id": "TOKEN",
        "amount_in_atomic": 100,
        "minimum_amount_out_atomic": 1,
        "fee_bps": 30,
        # Include execution mode in the completed run draft document result.
        "execution_mode": "SHADOW_STATE_REPLAY",
        "maximum_order_input_atomic": 1_000,
        "observation_slots": 1,
        "order_slots": 1,
        "initial_portfolio": [{"asset_id": "SOL", "amount_atomic": 10_000}],
        # Include root seed in the completed run draft document result.
        "root_seed": 42,
        "maximum_dynamic_items": 10_000,
        "feature_set_ids": [],
        "prediction_set_ids": [],
    }


# Keep the static run resolver contract and validation rules together.
class _StaticRunResolver:
    def resolve(self, draft: ReferenceRunDraft) -> ResolvedRunSpec:
        # Execute the static run resolver resolve workflow in explicit, reviewable steps.
        del draft
        return _resolved_spec()


# Keep the stub run results contract and validation rules together.
class _StubRunResults(QueryRunResults):
    def __init__(
        self,
        summary: PumpfunSnipingRunSummaryView,
        page: RoundTripPage,
        # Close the init signature after its explicit inputs.
        *,
        error: RunResultQueryError | None = None,
    ) -> None:
        # Execute the stub run results init workflow in explicit, reviewable steps.
        self.summary_value = summary
        self.page = page
        self.error = error
        self.summary_artifact_id: ArtifactId | None = None
        self.roundtrip_request: tuple[ArtifactId, RoundTripCursor | None, int] | None = None

    # Define stub run results summary as one focused operation with an explicit boundary.
    def summary(self, artifact_id: ArtifactId) -> PumpfunSnipingRunSummaryView:
        # Execute the stub run results summary workflow in explicit, reviewable steps.
        self.summary_artifact_id = artifact_id
        if self.error is not None:
            raise self.error
        return self.summary_value

    def roundtrips(
        # Keep the remaining roundtrips inputs visible at the stub run results roundtrips
        # boundary.
        self,
        artifact_id: ArtifactId,
        *,
        after: RoundTripCursor | None = None,
        limit: int = 200,
        # Keep the round trip page input explicit in the roundtrips contract.
    ) -> RoundTripPage:
        # Execute the stub run results roundtrips workflow in explicit, reviewable steps.
        self.roundtrip_request = (artifact_id, after, limit)
        if self.error is not None:
            raise self.error
        return self.page

    def dashboard(
        self,
        artifact_id: ArtifactId,
        *,
        limit: int = 200,
    ) -> PumpfunSnipingDashboardView:
        """Mirror the combined application projection without a concrete reader."""

        summary = self.summary(artifact_id)
        page = self.roundtrips(artifact_id, after=None, limit=limit)
        # Keep interface-route tests independent from Parquet adapter wiring.
        return PumpfunSnipingDashboardView(summary=summary, roundtrips=page)


def _sniping_summary() -> PumpfunSnipingRunSummaryView:
    # Execute the sniping summary workflow in explicit, reviewable steps.
    return PumpfunSnipingRunSummaryView(
        run_artifact_id=ArtifactId("1" * 64),
        logical_run_id=LogicalRunId("2" * 64),
        execution_attempt_id=ExecutionAttemptId("3" * 64),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so PumpfunSnipingRunSummaryView receives a
        # reviewable 1 and 2 input in sniping summary.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        canonical_result_hash=ContentDigest("4" * 64),
        audit_hash=ContentDigest("5" * 64),
        ledger_hash=ContentDigest("6" * 64),
        fill_hash=ContentDigest("7" * 64),
        # Include roundtrip digest in the completed sniping summary result.
        roundtrip_digest=ContentDigest("8" * 64),
        final_balances_digest=ContentDigest("9" * 64),
        historical_group_count=10,
        historical_event_count=11,
        delivered_event_count=12,
        # Pass target count explicitly so PumpfunSnipingRunSummaryView receives a
        # reviewable 1 and 2 input in sniping summary.
        target_count=2,
        cooldown_skipped_count=1,
        accepted_buy_count=1,
        accepted_order_count=2,
        rejected_order_count=0,
        # Pass filled order count explicitly so PumpfunSnipingRunSummaryView receives a
        # reviewable 1 and 2 input in sniping summary.
        filled_order_count=2,
        failed_order_count=0,
        failed_buy_count=0,
        failed_sell_count=0,
        closed_position_count=1,
        # Pass open position count explicitly so PumpfunSnipingRunSummaryView receives a
        # reviewable 1 and 2 input in sniping summary.
        open_position_count=0,
        ledger_transaction_count=4,
        fill_count=2,
        roundtrip_count=2,
        final_balances_count=16_385,
        # Pass realized cash pnl atomic explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        realized_cash_pnl_atomic=-321,
        valuation_status=SnipingValuationStatus.COMPLETE,
        unvalued_open_position_count=0,
        valued_economic_pnl_subtotal_atomic=-300,
        economic_pnl_atomic=-300,
        # Pass cashback receivable atomic explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        cashback_receivable_atomic=21,
        protocol_fee_paid_atomic=16,
        creator_fee_paid_atomic=5,
        network_base_fee_paid_atomic=10_000,
        network_priority_fee_paid_atomic=2,
        # Pass account deposit paid atomic explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        account_deposit_paid_atomic=2_039_280,
        account_deposit_refunded_atomic=2_039_280,
        account_deposit_locked_atomic=0,
        favorable_slippage_count=1,
        adverse_slippage_count=1,
        # Pass buy slippage failure count explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        buy_slippage_failure_count=0,
        sell_slippage_failure_count=0,
        summary_schema_id="pumpfun-sniping-run-summary/v3",
        execution_mode=ExecutionMode.EXOGENOUS_REPLAY,
        settlement_policy_id="real-reserve-capped-v1",
        filled_sell_count=1,
        real_liquidity_sufficient_filled_sell_count=1,
        synthetic_liquidity_used_sell_count=0,
        gross_sell_settlement_atomic=710,
        venue_funded_sell_atomic=710,
        synthetic_funded_sell_atomic=0,
    )


def _sniping_roundtrip() -> RoundTripRecord:
    # Execute the sniping roundtrip workflow in explicit, reviewable steps.
    def position(transaction_index: int, event_index: int | None = None) -> ChainPosition:
        # Execute the position workflow in explicit, reviewable steps.
        return ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=7,
            transaction_index=transaction_index,
            # Pass event index explicitly so ChainPosition receives a reviewable solana
            # mainnet network id and block32 transaction32 position schema id input in
            # position.
            event_index=event_index,
        )

    roundtrip_id = ContentDigest("a" * 64)
    return RoundTripRecord(
        roundtrip_id=roundtrip_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so RoundTripRecord receives a reviewable a
        # and b input in sniping roundtrip.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        target_event_id=ContentDigest("b" * 64),
        target_position=position(0, 2),
        target_time_ns=1_800_000_000_000_000_000,
        developer_id=AccountId("developer"),
        # Include creation user id in the completed sniping roundtrip result.
        creation_user_id=AccountId("creation-user"),
        asset_id=AssetId("token"),
        quote_asset_id=AssetId("SOL"),
        venue_id=VenueId("pumpfun-bonding-curve"),
        cooldown_consumed=True,
        # Pass cooldown until ns explicitly so RoundTripRecord receives a reviewable a and
        # b input in sniping roundtrip.
        cooldown_until_ns=1_800_000_600_000_000_000,
        status=RoundTripStatus.CLOSED,
        buy=RoundTripLegRecord(
            side=RoundTripLegSide.BUY,
            decision_position=position(0),
            # Include landing position in the completed sniping roundtrip result.
            landing_position=position(1),
            amount_in_atomic=999,
            reference_out_atomic=1_000,
            landing_out_atomic=900,
            minimum_out_atomic=900,
            # Pass signed slippage atomic explicitly so RoundTripLegRecord receives a
            # reviewable buy and position input in sniping roundtrip.
            signed_slippage_atomic=-100,
            protocol_fee_atomic=9,
            creator_fee_atomic=3,
            network_base_fee_atomic=5_000,
            network_priority_fee_atomic=1,
            # Complete RoundTripLegRecord only after its buy and position inputs are visible
            # in sniping roundtrip.
        ),
        sell=RoundTripLegRecord(
            side=RoundTripLegSide.SELL,
            decision_position=position(2),
            landing_position=position(3),
            # Pass amount in atomic explicitly so RoundTripLegRecord receives a reviewable
            # sell and position input in sniping roundtrip.
            amount_in_atomic=900,
            reference_out_atomic=700,
            landing_out_atomic=701,
            minimum_out_atomic=690,
            signed_slippage_atomic=1,
            # Pass protocol fee atomic explicitly so RoundTripLegRecord receives a
            # reviewable sell and position input in sniping roundtrip.
            protocol_fee_atomic=7,
            creator_fee_atomic=2,
            network_base_fee_atomic=5_000,
            network_priority_fee_atomic=1,
        ),
        # Pass acquired token amount atomic explicitly so RoundTripRecord receives a
        # reviewable a and b input in sniping roundtrip.
        acquired_token_amount_atomic=900,
        cashback_receivable_atomic=21,
        realized_cash_pnl_atomic=-321,
        mtm_status=MtmStatus.NOT_APPLICABLE,
        # Pass mtm liquidation value atomic explicitly so RoundTripRecord receives a
        # reviewable a and b input in sniping roundtrip.
        mtm_liquidation_value_atomic=None,
        mtm_cash_pnl_atomic=None,
        economic_pnl_atomic=-300,
        account_profile_id="test-fresh-v1",
        account_components=_closed_account_components(roundtrip_id),
        sell_reference_liquidity=QuoteLiquidityEvidenceRecord(
            policy_id="real-reserve-capped-v1",
            asset_id=AssetId("SOL"),
            required_output_atomic=709,
            observed_available_output_atomic=1_000,
            synthetic_shortfall_atomic=0,
        ),
        sell_landing_liquidity=QuoteLiquidityEvidenceRecord(
            policy_id="real-reserve-capped-v1",
            asset_id=AssetId("SOL"),
            required_output_atomic=710,
            observed_available_output_atomic=1_000,
            synthetic_shortfall_atomic=0,
        ),
        settled_venue_funded_atomic=710,
    )


def _closed_account_components(
    roundtrip_id: ContentDigest,
) -> tuple[AccountComponentRecord, ...]:
    """Build a large-integer ATA vector plus an existing wallet UVA."""

    rent = 9_007_199_254_740_993
    return (
        AccountComponentRecord(
            "pump-token-account-v1",
            AssetId("SOL"),
            AccountRequirementScope.MINT,
            AccountReleasePolicy.CLOSE_ON_SUCCESSFUL_SELL,
            rent,
            rent,
            0,
            rent,
            0,
            AccountComponentLifecycle.CLOSED_REFUNDED,
            LedgerCorrelationKind.ROUNDTRIP,
            roundtrip_id,
        ),
        AccountComponentRecord(
            "pumpfun-user-volume-accumulator-v1",
            AssetId("SOL"),
            AccountRequirementScope.WALLET,
            AccountReleasePolicy.RUN_LOCKED,
            0,
            0,
            0,
            0,
            0,
            AccountComponentLifecycle.PREWARMED,
            LedgerCorrelationKind.ROUNDTRIP,
            roundtrip_id,
        ),
    )


def _client(
    # Keep the tmp path input explicit in the client contract.
    tmp_path: Path,
    *,
    enforce_session: bool = False,
    write_rate_limit_per_minute: int = 120,
    secure_cookie: bool = False,
    # Keep the jobs input explicit in the client contract.
    jobs: MemoryJobs | None = None,
    default_run_settings: RunPhysicalSettings | None = None,
    max_request_bytes: int = 2 * 1024 * 1024,
    query_run_results: QueryRunResults | None = None,
    query_strategy_results: QueryStrategyResults | None = None,
    query_runs: QueryRuns | None = None,
    inspect_source: StoreSourceInspection | None = None,
) -> TestClient:
    # Execute the client workflow in explicit, reviewable steps.
    source_id = SourceId("test-indexer")
    capability_id = CapabilityId("swaps.v1")
    fidelity = SourceFidelity(
        identity=IdentityFidelity.CANDIDATE,
        ordering=OrderingFidelity.TRANSACTION_PARTIAL,
        # Pass state explicitly so SourceFidelity receives a reviewable candidate and
        # transaction partial input in client.
        state=StateFidelity.AFTER_ONLY,
        fees=FeesFidelity.UNKNOWN,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.BEST_EFFORT,
        # Complete SourceFidelity only after its candidate and transaction partial inputs are
        # visible in client.
    )
    metadata = SourceMetadata(
        source_id=source_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass server version explicitly so SourceMetadata receives a reviewable test-1
        # and test input in client.
        server_version="test-1",
        tables=(),
        capabilities=(
            CapabilityDescriptor(
                capability_id=capability_id,
                # Pass protocol explicitly so CapabilityDescriptor receives a reviewable
                # test and 1 input in client.
                protocol="test",
                protocol_version="1",
                schema_version="1",
                stream=CapabilityStream.PUMP_CURVE_TRADE,
                columns=("amount", "block_ordinal", "signature"),
                # Pass mandatory columns explicitly so CapabilityDescriptor receives a
                # reviewable test and 1 input in client.
                mandatory_columns=("block_ordinal", "signature"),
                fidelity=fidelity,
            ),
        ),
    )
    # Assemble source once so the client workflow shares one value.
    source = InMemorySourceReader(metadata, {capability_id: ()})
    artifacts = LocalArtifactRepository(tmp_path / "var")
    selected_jobs = jobs or MemoryJobs()
    use_cases = ControlUseCases(
        inspect_source=(
            inspect_source
            if inspect_source is not None
            else StoreSourceInspection(InspectSource(source), artifacts)
        ),
        # Keep the plan dataset and artifact source inspection loader PlanDataset step
        # visible while building use cases.
        plan_dataset=PlanDataset(
            ArtifactSourceInspectionLoader(artifacts),
            DatasetPlanningPolicy(
                budget_limits=BudgetLimits(10**9, 10**9, 7, 0, 0),
                query_limits=QueryLimits(300, 10**9, 10**7),
                # Pass max total blocks explicitly so DatasetPlanningPolicy receives a
                # reviewable budget limits and query limits input in client.
                max_total_blocks=10**7,
                max_total_shards=10_000,
                max_shard_blocks=10**6,
            ),
            disk_probe=LocalDiskCapacityProbe(tmp_path / "var"),
            # Complete PlanDataset only after its var and artifact source inspection loader
            # inputs are visible in client.
        ),
        submit_job=SubmitJob(selected_jobs),
        cancel_job=CancelJob(selected_jobs, selected_jobs),
        get_job=GetJob(selected_jobs),
        list_jobs=ListJobs(selected_jobs),
        # Pass profile explicitly so ControlUseCases receives a reviewable var and test
        # input in client.
        profile="test",
        default_run_physical_settings=(
            default_run_settings
            if default_run_settings is not None
            else RunPhysicalSettings(
                # Pass run backend explicitly so RunPhysicalSettings receives a reviewable
                # reference python and run backend input in client.
                RunBackend.REFERENCE_PYTHON,
                65_536,
                1,
                8_192,
                1,
                # Complete RunPhysicalSettings only after its reference python and run backend
                # inputs are visible in client.
            )
        ),
        resolve_run_spec=ResolveRunSpec(_StaticRunResolver()),
        resolve_sweep_spec=ResolveSweepSpec(_StaticRunResolver()),
        retry_job=RetryJob(selected_jobs),
        # Keep the selected jobs ListJobEvents step visible while building use cases.
        list_job_events=ListJobEvents(selected_jobs, selected_jobs),
        query_run_results=query_run_results,
        query_strategy_results=query_strategy_results,
        query_runs=query_runs,
        ml_reference_contract=ReferenceMlContract(
            runtime_lock_id=RuntimeLockId("1" * 64),
            compiler_version="numpy-point-in-time-ml-v1",
            # Keep the bundle id BundleId step visible while building use cases.
            feature_builder_bundle_id=BundleId("2" * 64),
            supported_feature_names=("event_boundary_ordinal", "event_slot"),
            universe_builder_bundle_id=BundleId("3" * 64),
            universe_spec_id=ContentDigest("4" * 64),
            universe_config_digest=ContentDigest("5" * 64),
            # Keep the bundle id BundleId step visible while building use cases.
            label_builder_bundle_id=BundleId("6" * 64),
            label_spec_id=ContentDigest("7" * 64),
            label_config_digest=ContentDigest("8" * 64),
            trainer_bundle_id=BundleId("9" * 64),
            trainer_framework="exact-rational-linear-v1",
            # Keep the bundle id and a BundleId step visible while building use cases.
            frozen_inference_bundle_id=BundleId("a" * 64),
        ),
    )
    return TestClient(
        create_app(
            use_cases,
            control_plane_id=ContentDigest("f" * 64),
            max_request_bytes=max_request_bytes,
            allowed_hosts=("testserver",),
            # Tests opt into mutation-session behavior explicitly per scenario.
            enforce_session=enforce_session,
            secure_cookie=secure_cookie,
            write_rate_limit_per_minute=write_rate_limit_per_minute,
        )
    )


def test_run_index_failure_has_typed_service_unavailable_response(tmp_path: Path) -> None:
    """A broken ordering projection is not misreported as an absent Run artifact."""

    class _BrokenRunQueries:
        def list(self, *, limit: int, offset: int) -> tuple[object, ...]:
            del limit, offset
            raise RunIndexQueryError

        def page(self, *, limit: int, offset: int, after: object) -> object:
            del limit, offset, after
            raise RunIndexQueryError

    client = _client(tmp_path, query_runs=cast(QueryRuns, _BrokenRunQueries()))
    response = client.get("/api/v1/runs?limit=1&offset=0")

    assert response.status_code == 503
    assert response.json() == {
        "code": "RUN_INDEX_UNAVAILABLE",
        "message": "The verified Run ordering index is unavailable and must be rebuilt.",
    }


def test_health_and_packaged_web_ui(tmp_path: Path) -> None:
    # Execute the test health and packaged web ui workflow in explicit, reviewable steps.
    client = _client(tmp_path)

    health = client.get("/api/v1/health")
    ui = client.get("/")
    # The shipped React shell is shared by every deep link and historical bookmark.
    assert health.status_code == 200
    assert health.json()["profile"] == "test"
    assert health.json()["control_plane_id"] == "f" * 64
    assert health.headers["cache-control"] == "no-store"
    assert ui.status_code == 200 and 'id="root"' in ui.text
    # Every executable asset must be external and same-origin under the unchanged CSP.
    import re

    scripts = re.findall(r'<script[^>]+src="([^"]+)"', ui.text)
    assert scripts and all(path.startswith("/static/") for path in scripts)
    assert all(client.get(path).status_code == 200 for path in scripts)
    assert "unsafe-inline" not in ui.headers["content-security-policy"]
    # Deep-link refreshes set the same session; no second result UI remains packaged.
    paths = ("/runs", "/runs/" + "a" * 64, "/launch", "/jobs", "/data", "/ml")
    paths += ("/resources", "/artifacts", "/artifacts/" + "a" * 64)
    paths += ("/sniping-results", "/copy-results", "/research", "/research?artifact=" + "a" * 64)
    for path in paths:
        response = client.get(path)
        # Route aliases serve identical bytes instead of a retained legacy renderer.
        assert response.status_code == 200 and response.content == ui.content
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["content-security-policy"] == ui.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/api/v1/unknown-react-route").status_code == 404

    ml_contract = client.get("/api/v1/ml/reference-contract")
    # Verify ml_contract.status_code == 200 before this scenario is accepted.
    assert ml_contract.status_code == 200
    assert ml_contract.json()["runtime_lock_id"] == "1" * 64
    assert ml_contract.json()["supported_feature_names"] == [
        "event_boundary_ordinal",
        "event_slot",
        # Verify the supported feature names, event boundary ordinal and event slot
        # relationship before this scenario is accepted.
    ]

    physical = client.get("/api/v1/run-physical-settings")
    assert physical.status_code == 200
    assert physical.json() == {
        "backend": "reference-python-v1",
        # Keep the output buffer rows expectation tied to json, backend and output buffer
        # rows in this scenario.
        "output_buffer_rows": 8192,
        "reader_batch_rows": 65536,
        "reader_readahead": 1,
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
        # Verify the json, backend and output buffer rows relationship before this scenario is
        # accepted.
    }


def test_job_list_status_projection_has_a_proven_two_mib_transport_bound() -> None:
    # Execute the test job list status projection has a proven two mib transport bound
    # workflow in explicit, reviewable steps.
    item = JobResponse.from_view(
        JobStatusView(
            job_id=JobId("job-bounded"),
            spec_version=1,
            spec_id=ContentDigest("1" * 64),
            # Pass job type explicitly so JobStatusView receives a reviewable job-bounded
            # and 1 input in test job list status projection has a proven two mib
            # transport bound.
            job_type=JobType.RUN_BACKTEST,
            payload_digest=ContentDigest("2" * 64),
            input_artifact_count=1_000,
            input_artifact_ids_digest=ContentDigest("3" * 64),
            state=AttemptState.QUEUED,
            # Pass state version explicitly so JobStatusView receives a reviewable job-
            # bounded and 1 input in test job list status projection has a proven two mib
            # transport bound.
            state_version=0,
        )
    )
    response = JobListResponse(items=(item,) * 1_000)

    assert len(response.model_dump_json().encode("utf-8")) < 2 * 1024 * 1024
    # Acquire raises, validation error and pytest at an explicit test job list status
    # projection has a proven two mib transport bound context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValidationError):
        JobListResponse(items=(item,) * 1_001)


def test_inspection_is_persisted_and_returned(tmp_path: Path) -> None:
    # Execute the test inspection is persisted and returned workflow in explicit,
    # reviewable steps.
    response = _client(tmp_path).post("/api/v1/sources/test-indexer/inspect")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == "test-indexer"
    assert payload["capabilities"][0]["capability_id"] == "swaps.v1"
    # Verify the unknown, launch transaction success exact and proofs relationship before
    # this scenario is accepted.
    assert payload["capabilities"][0]["proofs"]["launch_transaction_success_exact"] == "UNKNOWN"
    assert payload["evidence_receipt_ids"] == []
    assert len(ArtifactId(payload["artifact_id"]).hex) == 64


class _RejectedSourceInspection(StoreSourceInspection):
    def __init__(self, code: ErrorCode) -> None:
        self._code = code

    def execute(self, request: object) -> object:
        del request
        raise SourceEvidenceValidationError(self._code) from RuntimeError("password=api-secret")


@pytest.mark.parametrize(
    "code",
    (ErrorCode.INCOMPLETE_BLOCK_RANGE, ErrorCode.CURVE_TRANSITION_MISMATCH),
)
def test_source_evidence_rejection_has_safe_bad_gateway_response(
    tmp_path: Path,
    code: ErrorCode,
) -> None:
    response = _client(
        tmp_path,
        inspect_source=_RejectedSourceInspection(code),
    ).post("/api/v1/sources/test-indexer/inspect")

    assert response.status_code == 502
    assert response.json() == {
        "code": code.value,
        "message": SourceEvidenceValidationError(code).safe_message,
    }
    assert "api-secret" not in response.text


def test_plan_compiles_selective_half_open_shards(tmp_path: Path) -> None:
    # Execute the test plan compiles selective half open shards workflow in explicit,
    # reviewable steps.
    client = _client(tmp_path)
    inspection = client.post("/api/v1/sources/test-indexer/inspect")
    assert inspection.status_code == 200
    response = client.post(
        "/api/v1/datasets/plan",
        # Pass json explicitly so post receives a reviewable /api/v1/datasets/plan and
        # source id input in test plan compiles selective half open shards.
        json={
            "source_id": "test-indexer",
            "source_inspection_artifact_id": inspection.json()["artifact_id"],
            "network_id": SOLANA_MAINNET_NETWORK_ID.value,
            "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value,
            # Keep from block ordinal named so the /api/v1/datasets/plan and source id
            # payload passed to post remains self-describing within test plan compiles
            # selective half open shards.
            "from_block_ordinal": 100,
            "to_block_ordinal": 125,
            "warmup_blocks": 10,
            "settlement_tail_blocks": 0,
            "max_shard_blocks": 20,
            # Keep requested days named so the /api/v1/datasets/plan and source id payload
            # passed to post remains self-describing within test plan compiles selective
            # half open shards.
            "requested_days": 1,
            "requirements": [
                {
                    "origin": "STRATEGY",
                    "origin_id": "strategy-a",
                    # Keep capability id named so the /api/v1/datasets/plan and source id
                    # payload passed to post remains self-describing within test plan
                    # compiles selective half open shards.
                    "capability_id": "swaps.v1",
                    "columns": ["amount"],
                }
            ],
            "budget": {
                # Keep max remote bytes named so the /api/v1/datasets/plan and source id
                # payload passed to post remains self-describing within test plan compiles
                # selective half open shards.
                "max_remote_bytes": 1000000,
                "max_local_bytes": 1000000,
                "max_days": 7,
                "temporary_reserve_bytes": 0,
                "disk_low_watermark_bytes": 0,
                # Close the /api/v1/datasets/plan and source id payload only after all test
                # plan compiles selective half open shards fields are present.
            },
            "query": {
                "max_execution_seconds": 30,
                "max_memory_bytes": 1000000,
                "max_result_rows": 10000,
                # Close the /api/v1/datasets/plan and source id payload only after all test
                # plan compiles selective half open shards fields are present.
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    # Assemble identity once so the test plan compiles selective half open shards workflow
    # shares one value.
    identity = {
        "network_id": SOLANA_MAINNET_NETWORK_ID.value,
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value,
    }
    assert payload["decision_range"] == {
        # Keep the identity expectation tied to payload, decision range and from block
        # ordinal in this scenario.
        **identity,
        "from_block_ordinal": 100,
        "to_block_ordinal": 125,
    }
    assert payload["capability_ranges"] == [
        # Verify the payload, capability ranges and capability id relationship before this
        # scenario is accepted.
        {
            "capability_id": "swaps.v1",
            "block_range": {
                **identity,
                "from_block_ordinal": 90,
                # Keep the to block ordinal expectation tied to payload, capability ranges
                # and capability id in this scenario.
                "to_block_ordinal": 125,
            },
        }
    ]
    assert [item["block_range"] for item in payload["shards"]] == [
        # Keep the from block ordinal expectation tied to item, block range and from block
        # ordinal in this scenario.
        {**identity, "from_block_ordinal": 90, "to_block_ordinal": 110},
        {**identity, "from_block_ordinal": 110, "to_block_ordinal": 125},
    ]
    assert payload["budget"]["status"] == "UNKNOWN"
    assert payload["resolved_plan"]["spec"]["spec_id"] == payload["spec_id"]
    # Verify the unknown, status and budget relationship before this scenario is accepted.
    assert payload["resolved_plan"]["budget"]["status"] == "UNKNOWN"


def test_settlement_requirement_input_preserves_exact_integer_contract() -> None:
    # Execute the test settlement requirement input preserves exact integer contract
    # workflow in explicit, reviewable steps.
    value = RequirementInput.model_validate_json(
        json.dumps(
            {
                "origin": "EXECUTION",
                "origin_id": "pumpfun-sniping-v1",
                # Keep capability id named so the origin and origin id payload passed to
                # dumps remains self-describing within test settlement requirement input
                # preserves exact integer contract.
                "capability_id": "clock.v1",
                "columns": ["transaction_count"],
                "settlement_requirement": {
                    "schema": "global-transaction-duration-roundtrip/v1",
                    "target_stream": "TOKEN_LAUNCH",
                    # Keep settlement streams named so the origin and origin id payload
                    # passed to dumps remains self-describing within test settlement
                    # requirement input preserves exact integer contract.
                    "settlement_streams": [
                        "BLOCK_CLOCK",
                        "PUMP_CURVE_LIFECYCLE",
                        "PUMP_CURVE_TRADE",
                    ],
                    # Keep initial delay transactions named so the origin and origin id
                    # payload passed to dumps remains self-describing within test
                    # settlement requirement input preserves exact integer contract.
                    "initial_delay_transactions": 500,
                    "minimum_duration_ns": 2_000_000_000,
                    "maximum_followup_delay_transactions": 17,
                    "maximum_tail_blocks": 64,
                },
                # Close the origin and origin id payload only after all test settlement
                # requirement input preserves exact integer contract fields are present.
            }
        )
    ).to_domain()

    assert value.settlement_requirement is not None
    assert value.settlement_requirement.initial_delay_transactions == 500
    # Verify the minimum duration ns, settlement requirement and value relationship before
    # this scenario is accepted.
    assert value.settlement_requirement.minimum_duration_ns == 2_000_000_000
    assert value.settlement_requirement.maximum_followup_delay_transactions == 17
    assert value.settlement_requirement.maximum_tail_blocks == 64


def test_typed_run_draft_resolves_to_an_exact_spec(tmp_path: Path) -> None:
    # Execute the test typed run draft resolves to an exact spec workflow in explicit,
    # reviewable steps.
    draft = _run_draft_document()
    response = _client(tmp_path).post("/api/v1/run-specs/resolve", json=draft)

    assert response.status_code == 200, response.text
    assert response.json()["spec_id"] == _resolved_spec().spec_id.hex
    assert response.json()["resolved_spec"] == _resolved_spec().document()

    # Assemble physical settings once so the test typed run draft resolves to an exact
    # spec workflow shares one value.
    physical_settings = {
        "backend": "reference-python-v1",
        "output_buffer_rows": 8_192,
        "reader_batch_rows": 65_536,
        "reader_readahead": 2,
        # Keep the schema component named inside the physical settings contract.
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
    }
    sweep = _client(tmp_path).post(
        "/api/v1/sweep-specs/resolve",
        # Pass json explicitly so post receives a reviewable /api/v1/sweep-specs/resolve
        # and entries input in test typed run draft resolves to an exact spec.
        json={
            "entries": [
                {
                    "draft": draft,
                    "attempt_nonce": "a" * 64,
                    # Keep physical settings named so the /api/v1/sweep-specs/resolve and
                    # entries payload passed to post remains self-describing within test
                    # typed run draft resolves to an exact spec.
                    "physical_settings": physical_settings,
                },
                {
                    "draft": {**draft, "root_seed": 43},
                    "attempt_nonce": "b" * 64,
                    # Keep physical settings named so the /api/v1/sweep-specs/resolve and
                    # entries payload passed to post remains self-describing within test
                    # typed run draft resolves to an exact spec.
                    "physical_settings": physical_settings,
                },
            ],
            "comparison_metrics": ["canonical_result_hash"],
        },
        # Complete post only after its /api/v1/sweep-specs/resolve and entries inputs are
        # visible in test typed run draft resolves to an exact spec.
    )
    assert sweep.status_code == 200, sweep.text
    assert len(sweep.json()["resolved_sweep_spec"]["entries"]) == 2
    assert sweep.json()["resolved_sweep_spec"]["spec_version"] == 2
    assert all(
        # Pass item explicitly so all receives a reviewable reader readahead and entries
        # input in test typed run draft resolves to an exact spec.
        item["physical_settings"]["reader_readahead"] == 2
        for item in sweep.json()["resolved_sweep_spec"]["entries"]
    )


def test_resolvers_fail_with_stable_413_when_output_cannot_round_trip(tmp_path: Path) -> None:
    # Execute the test resolvers fail with stable 413 when output cannot round trip
    # workflow in explicit, reviewable steps.
    maximum = 2_048
    client = _client(tmp_path, max_request_bytes=maximum)
    draft = _run_draft_document()
    physical_settings = {
        "backend": "reference-python-v1",
        # Keep the output buffer rows component named inside the physical settings
        # contract.
        "output_buffer_rows": 8_192,
        "reader_batch_rows": 65_536,
        "reader_readahead": 1,
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
        # Complete the physical settings group only after its semantic components are visible.
    }
    sweep_command = {
        "entries": [
            {
                "draft": draft,
                # Keep the attempt nonce component named inside the sweep command
                # contract.
                "attempt_nonce": "a" * 64,
                "physical_settings": physical_settings,
            }
        ],
        "comparison_metrics": ["canonical_result_hash"],
        # Complete the sweep command group only after its semantic components are visible.
    }
    assert len(json.dumps(draft).encode("utf-8")) < maximum
    assert len(json.dumps(sweep_command).encode("utf-8")) < maximum

    run = client.post("/api/v1/run-specs/resolve", json=draft)
    sweep = client.post("/api/v1/sweep-specs/resolve", json=sweep_command)

    # Traverse (run, sweep) explicitly so each test resolvers fail with stable 413 when
    # output cannot round trip iteration remains traceable.
    for response in (run, sweep):
        # Process (run, sweep) inside the bounded test resolvers fail with stable 413 when
        # output cannot round trip loop.
        assert response.status_code == 413
        assert response.json() == {
            "code": "RESPONSE_TOO_LARGE",
            "message": "The resolved response exceeds the configured local transport bound.",
        }


# Define test typed backtest endpoint queues exact v2 physical settings as one focused
# operation with an explicit boundary.
def test_typed_backtest_endpoint_queues_exact_v2_physical_settings(tmp_path: Path) -> None:
    # Execute the test typed backtest endpoint queues exact v2 physical settings workflow
    # in explicit, reviewable steps.
    jobs = MemoryJobs()
    client = _client(
        tmp_path,
        jobs=jobs,
        default_run_settings=RunPhysicalSettings(
            # Pass run backend explicitly so RunPhysicalSettings receives a reviewable
            # reference python and run backend input in test typed backtest endpoint
            # queues exact v2 physical settings.
            RunBackend.REFERENCE_PYTHON,
            65_536,
            1,
            8_192,
            2,
            # Complete RunPhysicalSettings only after its reference python and run backend
            # inputs are visible in test typed backtest endpoint queues exact v2 physical
            # settings.
        ),
    )
    response = client.post(
        "/api/v1/backtests",
        headers={"Idempotency-Key": "typed-run-v2"},
        # Pass json explicitly so post receives a reviewable /api/v1/backtests and
        # idempotency-key input in test typed backtest endpoint queues exact v2 physical
        # settings.
        json={
            "attempt_nonce": "a" * 64,
            "physical_settings": {
                "backend": "numpy-mmap-first-swap-exact-v1",
                "output_buffer_rows": 16_384,
                # Keep reader batch rows named so the /api/v1/backtests and idempotency-
                # key payload passed to post remains self-describing within test typed
                # backtest endpoint queues exact v2 physical settings.
                "reader_batch_rows": 131_072,
                "reader_readahead": 4,
                "schema": "backtest.run-physical-settings/v2",
                "threads": 2,
            },
            # Keep the document and resolved spec document step visible while building
            # response.
            "resolved_run_spec": _resolved_spec().document(),
        },
    )

    assert response.status_code == 202, response.text
    record = next(iter(jobs.records.values()))
    # Assemble command once so the test typed backtest endpoint queues exact v2 physical
    # settings workflow shares one value.
    command = resolved_backtest_job_from_bytes(record.spec.canonical_payload)
    assert command.physical_settings == RunPhysicalSettings(
        RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT,
        131_072,
        4,
        # Pass 384 explicitly so RunPhysicalSettings receives a reviewable numpy mmap
        # first swap exact and run backend input in test typed backtest endpoint queues
        # exact v2 physical settings.
        16_384,
        2,
    )
    assert command.resolved_spec.logical_run_id == _resolved_spec().logical_run_id


@pytest.mark.parametrize(
    # Open the field and value payload explicitly for parametrize within test typed
    # backtest endpoint rejects unsupported physical settings.
    ("field", "value"),
    (
        ("backend", "silent-fallback"),
        ("reader_readahead", 3),
        ("reader_readahead", True),
        # Open the field and value payload explicitly for parametrize within test typed
        # backtest endpoint rejects unsupported physical settings.
        ("threads", 0),
        ("threads", 2),
    ),
)
def test_typed_backtest_endpoint_rejects_unsupported_physical_settings(
    # Keep the tmp path input explicit in the test typed backtest endpoint rejects
    # unsupported physical settings contract.
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    # Execute the test typed backtest endpoint rejects unsupported physical settings
    # workflow in explicit, reviewable steps.
    jobs = MemoryJobs()
    settings: dict[str, object] = {
        "backend": "reference-python-v1",
        "output_buffer_rows": 8_192,
        "reader_batch_rows": 65_536,
        # Keep the reader readahead component named inside the settings contract.
        "reader_readahead": 1,
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
    }
    settings[field] = value

    # Assemble response once so the test typed backtest endpoint rejects unsupported
    # physical settings workflow shares one value.
    response = _client(tmp_path, jobs=jobs).post(
        "/api/v1/backtests",
        headers={"Idempotency-Key": "invalid-physical"},
        json={
            "attempt_nonce": "a" * 64,
            # Keep physical settings named so the /api/v1/backtests and idempotency-key
            # payload passed to post remains self-describing within test typed backtest
            # endpoint rejects unsupported physical settings.
            "physical_settings": settings,
            "resolved_run_spec": _resolved_spec().document(),
        },
    )

    assert response.status_code == 422
    # Verify jobs.records == {} before this scenario is accepted.
    assert jobs.records == {}


def test_submit_list_and_cancel_job(tmp_path: Path) -> None:
    # Execute the test submit list and cancel job workflow in explicit, reviewable steps.
    client = _client(tmp_path)
    submitted = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "browser-click-1"},
        json=_job_command(),
        # Complete post only after its /api/v1/jobs and idempotency-key inputs are visible in
        # test submit list and cancel job.
    )

    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["job_id"]
    listed = client.get("/api/v1/jobs").json()["items"]
    assert [item["job_id"] for item in listed] == [job_id]

    # Assemble cancelled once so the test submit list and cancel job workflow shares one
    # value.
    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"


def test_job_api_cursor_page_is_stable_across_newer_submit(tmp_path: Path) -> None:
    """Browser continuation cannot duplicate an older row after a concurrent insert."""

    jobs = MemoryJobs()
    client = _client(tmp_path, jobs=jobs)
    for index, character in enumerate(("a", "b", "c", "d"), start=1):
        # Populate one deterministic same-timestamp page ordered by descending job ID.
        response = client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": f"cursor-{index}"},
            json=_job_command(attempt=character),
        )
        assert response.status_code == 202

    first = client.get("/api/v1/jobs", params={"limit": 2}).json()
    assert [item["job_id"] for item in first["items"]] == ["job_4", "job_3"]
    assert isinstance(first["next_cursor"], str)

    # The next durable job sorts ahead of the already-issued continuation.
    inserted = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "cursor-5"},
        json=_job_command(attempt="e"),
    )
    assert inserted.status_code == 202
    second = client.get(
        "/api/v1/jobs",
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()

    assert [item["job_id"] for item in second["items"]] == ["job_2", "job_1"]
    assert second["next_cursor"] is None


def test_list_api_rejects_ambiguous_or_pathological_pagination(tmp_path: Path) -> None:
    """Cursor scope, duplicate fields, and legacy offset cost fail closed."""

    client = _client(tmp_path)
    submitted = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "cursor-validation"},
        json=_job_command(),
    )
    assert submitted.status_code == 202
    first_page = client.get("/api/v1/jobs", params={"limit": 1}).json()
    assert first_page["next_cursor"] is None
    # One row has no lookahead, so add a second row before obtaining a continuation.
    client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "cursor-validation-2"},
        json=_job_command(attempt="b"),
    )
    token = client.get("/api/v1/jobs", params={"limit": 1}).json()["next_cursor"]
    assert isinstance(token, str)

    assert (
        client.get(
            "/api/v1/jobs",
            params={"limit": 1, "offset": 1, "cursor": token},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/jobs",
            params={"limit": 1, "state": "QUEUED", "cursor": token},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/jobs?limit=1&limit=2").status_code == 422
    assert client.get("/api/v1/jobs?limit=1&unknown=true").status_code == 422
    assert client.get("/api/v1/jobs?offset=10001").status_code == 422
    assert client.get("/api/v1/runs?offset=10001").status_code == 422


def test_typed_ml_endpoint_submits_exact_resolved_command_without_rows_or_paths(
    tmp_path: Path,
    # Close the test typed ml endpoint submits exact resolved command without rows or paths
    # signature after its explicit inputs.
) -> None:
    # Execute the test typed ml endpoint submits exact resolved command without rows or
    # paths workflow in explicit, reviewable steps.
    payload = {
        "spec_version": 1,
        "replay_pack_id": "1" * 64,
        "replay_semantics_id": "2" * 64,
        "replay_layout_schema_id": "3" * 64,
        # Keep the feature specs component named inside the payload contract.
        "feature_specs": [
            {
                "name": "event_boundary_ordinal",
                "version": 1,
                "entity_key": "replay_row_id",
                # Keep the input ids component named inside the payload contract.
                "input_ids": [],
                "effective_time_semantics": "replay-event-boundary-v1",
                "available_time_semantics": "event-boundary-plus-warmup-v1",
                "warmup_boundaries": 0,
                "dtype": "<i8",
                # Keep the null policy component named inside the payload contract.
                "null_policy": "FORBID",
                "code_bundle_id": "4" * 64,
                "runtime_lock_id": "5" * 64,
            }
        ],
        # Keep the input feature set ids component named inside the payload contract.
        "input_feature_set_ids": [],
        "compiler_version": "numpy-point-in-time-ml-v1",
    }
    client = _client(tmp_path)

    accepted = client.post(
        # Pass api v1 ml features explicitly so post receives a reviewable
        # /api/v1/ml/features and idempotency-key input in test typed ml endpoint submits
        # exact resolved command without rows or paths.
        "/api/v1/ml/features",
        headers={"Idempotency-Key": "typed-feature-build"},
        json=payload,
    )
    forbidden_transport = client.post(
        # Pass api v1 ml features explicitly so post receives a reviewable
        # /api/v1/ml/features and idempotency-key input in test typed ml endpoint submits
        # exact resolved command without rows or paths.
        "/api/v1/ml/features",
        headers={"Idempotency-Key": "typed-feature-path"},
        json={**payload, "path": "/tmp/untrusted.py"},
    )

    assert accepted.status_code == 202, accepted.text
    # Verify the build features, job type and json relationship before this scenario is
    # accepted.
    assert accepted.json()["job_type"] == "BUILD_FEATURES"
    assert forbidden_transport.status_code == 422
    queued = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}").json()
    assert queued["input_artifact_count"] == 1
    assert (
        # Keep the queued expectation tied to hex, queued and input artifact ids digest in
        # this scenario.
        queued["input_artifact_ids_digest"]
        == job_input_artifact_ids_digest((ArtifactId("1" * 64),)).hex
    )


def test_job_retry_and_bounded_event_history_use_application_services(tmp_path: Path) -> None:
    # Execute the test job retry and bounded event history use application services
    # workflow in explicit, reviewable steps.
    jobs = MemoryJobs()
    client = _client(tmp_path, jobs=jobs)
    submitted = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "retry-through-api"},
        # Keep the job command _job_command step visible while building submitted.
        json=_job_command(),
    )
    assert submitted.status_code == 202
    job_id = JobId(submitted.json()["job_id"])
    current = jobs.records[job_id]
    # Assemble jobs records[job id] once so the test job retry and bounded event history
    # use application services workflow shares one value.
    jobs.records[job_id] = JobRecord(
        current.job_id,
        current.spec,
        AttemptState.FAILED,
        current.state_version + 1,
        # Complete JobRecord only after its job id and spec inputs are visible in test job
        # retry and bounded event history use application services.
    )
    jobs.events[job_id] = (
        JobEventRecord(
            event_id=7,
            job_id=job_id,
            # Register attempt-api-progress through AttemptId so the jobs.events[job id]
            # table remains scannable.
            attempt_id=AttemptId("attempt-api-progress"),
            event_type="ATTEMPT_PROGRESS",
            state_version=current.state_version + 1,
            created_at_ns=123,
            progress=JobProgressDetails(
                # Pass sequence explicitly so JobProgressDetails receives a reviewable
                # info and running backtest input in test job retry and bounded event
                # history use application services.
                sequence=4,
                level=ProgressLevel.INFO,
                stage=ProgressStage.RUNNING_BACKTEST,
                coalesced_events=2,
                private_rss_bytes=100,
                # Pass total rss bytes explicitly so JobProgressDetails receives a
                # reviewable info and running backtest input in test job retry and bounded
                # event history use application services.
                total_rss_bytes=120,
            ),
        ),
    )

    retried = client.post(f"/api/v1/jobs/{job_id.value}/retry")
    # Assemble events once so the test job retry and bounded event history use application
    # services workflow shares one value.
    events = client.get(f"/api/v1/jobs/{job_id.value}/events?after_event_id=0&limit=10")

    assert retried.status_code == 200
    assert retried.json()["state"] == "QUEUED"
    assert events.status_code == 200
    assert events.json()["items"] == [
        # Verify the items, json and attempt id relationship before this scenario is
        # accepted.
        {
            "attempt_id": "attempt-api-progress",
            "created_at_ns": 123,
            "event_id": 7,
            "event_type": "ATTEMPT_PROGRESS",
            # Keep the job id expectation tied to items, json and attempt id in this
            # scenario.
            "job_id": job_id.value,
            "progress": {
                "coalesced_events": 2,
                "completed_units": None,
                "dropped_transport_frames": 0,
                # Keep the level expectation tied to items, json and attempt id in this
                # scenario.
                "level": "INFO",
                "major_page_faults": None,
                "private_rss_bytes": 100,
                "sequence": 4,
                "stage": "RUNNING_BACKTEST",
                # Keep the temporary disk bytes expectation tied to items, json and
                # attempt id in this scenario.
                "temporary_disk_bytes": None,
                "total_rss_bytes": 120,
                "total_units": None,
            },
            "state_version": current.state_version + 1,
            # Verify the items, json and attempt id relationship before this scenario is
            # accepted.
        }
    ]
    assert client.get(f"/api/v1/jobs/{job_id.value}/events?after_event_id=7&limit=10").json() == {
        "items": []
    }


# Define test job submit is retry safe and conflict is stable as one focused operation
# with an explicit boundary.
def test_job_submit_is_retry_safe_and_conflict_is_stable(tmp_path: Path) -> None:
    # Execute the test job submit is retry safe and conflict is stable workflow in
    # explicit, reviewable steps.
    client = _client(tmp_path)
    headers = {"Idempotency-Key": "retry-key-private"}
    command = _job_command()

    first = client.post("/api/v1/jobs", headers=headers, json=command)
    retry = client.post("/api/v1/jobs", headers=headers, json=command)
    # Assemble conflict once so the test job submit is retry safe and conflict is stable
    # workflow shares one value.
    conflict = client.post(
        "/api/v1/jobs",
        headers=headers,
        json=_job_command(attempt="b"),
    )

    # Verify the status code, first and retry relationship before this scenario is
    # accepted.
    assert first.status_code == retry.status_code == 202
    assert retry.json()["job_id"] == first.json()["job_id"]
    assert first.headers["location"] == f"/api/v1/jobs/{first.json()['job_id']}"
    assert retry.headers["location"] == first.headers["location"]
    assert conflict.status_code == 409
    # Verify the idempotency conflict, code and json relationship before this scenario is
    # accepted.
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert "retry-key-private" not in conflict.text
    assert len(client.get("/api/v1/jobs").json()["items"]) == 1


def test_api_rejects_ambiguous_or_cross_origin_mutations(tmp_path: Path) -> None:
    # Execute the test api rejects ambiguous or cross origin mutations workflow in
    # explicit, reviewable steps.
    client = _client(tmp_path)
    body = json.dumps(_job_command(), separators=(",", ":"))

    wrong_media = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "key", "Content-Type": "text/plain"},
        # Pass content explicitly so post receives a reviewable /api/v1/jobs and
        # idempotency-key input in test api rejects ambiguous or cross origin mutations.
        content=body,
    )
    duplicate_key = client.post(
        "/api/v1/jobs",
        headers=[
            # Open the /api/v1/jobs and idempotency-key payload explicitly for post within
            # test api rejects ambiguous or cross origin mutations.
            ("Idempotency-Key", "key-one"),
            ("Idempotency-Key", "key-two"),
            ("Content-Type", "application/json"),
        ],
        content=body,
        # Complete post only after its /api/v1/jobs and idempotency-key inputs are visible in
        # test api rejects ambiguous or cross origin mutations.
    )
    cross_origin = client.post(
        "/api/v1/jobs",
        headers={
            "Idempotency-Key": "key",
            # Keep origin named so the /api/v1/jobs and idempotency-key payload passed to
            # post remains self-describing within test api rejects ambiguous or cross
            # origin mutations.
            "Origin": "http://attacker.invalid",
            "Content-Type": "application/json",
        },
        content=body,
    )
    # Assemble bad host once so the test api rejects ambiguous or cross origin mutations
    # workflow shares one value.
    bad_host = client.get("/api/v1/health", headers={"Host": "attacker.invalid"})

    assert wrong_media.status_code == 415
    assert wrong_media.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert duplicate_key.status_code == 422
    assert duplicate_key.json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    # Verify cross_origin.status_code == 403 before this scenario is accepted.
    assert cross_origin.status_code == 403
    assert cross_origin.json()["code"] == "FORBIDDEN_ORIGIN"
    assert bad_host.status_code == 400
    assert bad_host.json()["code"] == "INVALID_HOST"


def test_browser_mutations_require_session_cookie_and_csrf_header(tmp_path: Path) -> None:
    # Execute the test browser mutations require session cookie and csrf header workflow
    # in explicit, reviewable steps.
    client = _client(tmp_path, enforce_session=True)
    command = _job_command()

    missing_session = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "before-root"},
        # Pass json explicitly so post receives a reviewable /api/v1/jobs and idempotency-
        # key input in test browser mutations require session cookie and csrf header.
        json=command,
    )
    root = client.get("/")
    missing_csrf = client.post(
        "/api/v1/jobs",
        # Pass idempotency-key explicitly so post receives a reviewable /api/v1/jobs and
        # idempotency-key input in test browser mutations require session cookie and csrf
        # header.
        headers={"Idempotency-Key": "without-csrf"},
        json=command,
    )
    accepted = client.post(
        "/api/v1/jobs",
        # Pass idempotency-key explicitly so post receives a reviewable /api/v1/jobs and
        # idempotency-key input in test browser mutations require session cookie and csrf
        # header.
        headers={"Idempotency-Key": "with-csrf", "X-Backtest-CSRF": "1"},
        json=command,
    )

    assert missing_session.status_code == 403
    assert root.status_code == 200
    # Assemble cookie once so the test browser mutations require session cookie and csrf
    # header workflow shares one value.
    cookie = root.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert missing_csrf.status_code == 403
    assert accepted.status_code == 202


def test_reverse_proxy_profile_can_require_a_secure_session_cookie(tmp_path: Path) -> None:
    # Execute the test reverse proxy profile can require a secure session cookie workflow
    # in explicit, reviewable steps.
    client = _client(tmp_path, enforce_session=True, secure_cookie=True)

    cookie = client.get("/").headers["set-cookie"]

    assert "Secure" in cookie


def test_write_rate_limit_is_bounded_and_safe(tmp_path: Path) -> None:
    # Execute the test write rate limit is bounded and safe workflow in explicit,
    # reviewable steps.
    client = _client(tmp_path, write_rate_limit_per_minute=1)
    first = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "first"},
        json=_job_command(),
        # Complete post only after its /api/v1/jobs and idempotency-key inputs are visible in
        # test write rate limit is bounded and safe.
    )
    limited = client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": "second"},
        json=_job_command(attempt="b"),
        # Complete post only after its /api/v1/jobs and idempotency-key inputs are visible in
        # test write rate limit is bounded and safe.
    )
    assert first.status_code == 202
    assert limited.status_code == 429
    assert limited.json()["code"] == "WRITE_RATE_LIMITED"


def test_api_models_are_strict_and_forbid_unknown_fields(tmp_path: Path) -> None:
    # Execute the test api models are strict and forbid unknown fields workflow in
    # explicit, reviewable steps.
    client = _client(tmp_path)
    invalid_commands = (
        {"job_type": "PREPARE_DATASET", "payload": {}, "unknown": True},
        {"spec_version": "1", "job_type": "PREPARE_DATASET", "payload": {}},
    )

    # Traverse enumerate(invalid_commands) explicitly so each test api models are strict
    # and forbid unknown fields iteration remains traceable.
    for index, command in enumerate(invalid_commands):
        # Process enumerate(invalid_commands) inside the bounded test api models are
        # strict and forbid unknown fields loop.
        response = client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": f"strict-{index}"},
            json=command,
        )
        # Verify response.status_code == 422 before this scenario is accepted.
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_JOB_PAYLOAD"


def test_job_command_rejects_duplicates_floats_and_secrets(tmp_path: Path) -> None:
    # Execute the test job command rejects duplicates floats and secrets workflow in
    # explicit, reviewable steps.
    client = _client(tmp_path)
    invalid_bodies = (
        '{"job_type":"RUN_BACKTEST","payload":{"x":1,"x":2}}',
        '{"job_type":"RUN_BACKTEST","payload":{"threshold":1.2}}',
        '{"job_type":"RUN_BACKTEST","payload":{"password":"nope"}}',
        # Complete the invalid bodies group only after its semantic components are visible.
    )

    for body in invalid_bodies:
        # Process invalid_bodies inside the bounded test job command rejects duplicates
        # floats and secrets loop.
        response = client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": "key", "Content-Type": "application/json"},
            content=body,
        )
        # Verify response.status_code == 422 before this scenario is accepted.
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_JOB_PAYLOAD"


def test_unknown_job_has_stable_error_shape(tmp_path: Path) -> None:
    # Execute the test unknown job has stable error shape workflow in explicit, reviewable
    # steps.
    response = _client(tmp_path).get("/api/v1/jobs/job_missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "JOB_NOT_FOUND",
        "message": "Job does not exist: job_missing.",
        # Verify the json, code and message relationship before this scenario is accepted.
    }


def test_sync_control_queries_do_not_block_the_asgi_event_loop(tmp_path: Path) -> None:
    """SQLite/probe handlers must enter FastAPI's bounded worker threadpool."""

    client = _client(tmp_path)
    protected_routes = {
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("GET", "/api/v1/jobs/{job_id}/events"),
        ("POST", "/api/v1/jobs/{job_id}/cancel"),
        ("POST", "/api/v1/jobs/{job_id}/retry"),
        # Resource probes may perform filesystem and process measurements.
        ("GET", "/api/v1/system/resources"),
    }
    checked: set[tuple[str, str]] = set()

    for route in client.app.routes:
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", ()):
            key = (method, path)
            if key not in protected_routes:
                continue
            # A regular def endpoint is dispatched outside the single ASGI event loop.
            assert not iscoroutinefunction(route.endpoint)
            checked.add(key)

    assert checked == protected_routes


def test_sniping_result_routes_are_exact_bounded_and_lossless(tmp_path: Path) -> None:
    # Execute the test sniping result routes are exact bounded and lossless workflow in
    # explicit, reviewable steps.
    record = _sniping_roundtrip()
    cursor = RoundTripCursor(record.target_position.boundary_ordinal, record.roundtrip_id)
    queries = _StubRunResults(_sniping_summary(), RoundTripPage((record,), cursor))
    client = _client(tmp_path, query_run_results=queries)

    summary_response = client.get(
        # Pass api v1 run-artifacts queries explicitly so get receives a reviewable
        # /api/v1/run-artifacts/ and /summary input in test sniping result routes are
        # exact bounded and lossless.
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/summary"
    )
    page_response = client.get(
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/roundtrips",
        params={"limit": 1},
        # Complete get only after its /api/v1/run-artifacts/ and /roundtrips inputs are
        # visible in test sniping result routes are exact bounded and lossless.
    )
    dashboard_response = client.get(
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/dashboard",
        params={"limit": 1},
    )

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["final_balances_count"] == 16_385
    assert summary["realized_cash_pnl_atomic"] == "-321"
    # Verify the complete, summary and valuation status relationship before this scenario
    # is accepted.
    assert summary["valuation_status"] == "COMPLETE"
    assert summary["unvalued_open_position_count"] == 0
    assert summary["valued_economic_pnl_subtotal_atomic"] == "-300"
    assert summary["economic_pnl_atomic"] == "-300"
    assert summary["cashback_receivable_atomic"] == "21"
    # Verify the summary and protocol fee paid atomic relationship before this scenario is
    # accepted.
    assert summary["protocol_fee_paid_atomic"] == "16"
    assert summary["creator_fee_paid_atomic"] == "5"
    assert summary["network_base_fee_paid_atomic"] == "10000"
    assert summary["network_priority_fee_paid_atomic"] == "2"
    assert summary["account_deposit_paid_atomic"] == "2039280"
    # Verify the summary and account deposit refunded atomic relationship before this
    # scenario is accepted.
    assert summary["account_deposit_refunded_atomic"] == "2039280"
    assert summary["account_deposit_locked_atomic"] == "0"
    assert summary["favorable_slippage_count"] == 1
    assert summary["adverse_slippage_count"] == 1
    assert summary["buy_slippage_failure_count"] == 0
    # Verify the summary and sell slippage failure count relationship before this scenario
    # is accepted.
    assert summary["sell_slippage_failure_count"] == 0
    assert summary["summary_schema_id"] == "pumpfun-sniping-run-summary/v3"
    assert summary["execution_mode"] == "EXOGENOUS_REPLAY"
    assert summary["settlement_policy_id"] == "real-reserve-capped-v1"
    assert summary["filled_sell_count"] == 1
    assert summary["venue_funded_sell_atomic"] == "710"
    assert summary["synthetic_funded_sell_atomic"] == "0"
    assert "path" not in summary and "manifest" not in summary
    assert queries.summary_artifact_id == queries.summary_value.run_artifact_id

    assert page_response.status_code == 200
    page = page_response.json()
    # Assemble item once so the test sniping result routes are exact bounded and lossless
    # workflow shares one value.
    item = page["items"][0]
    assert item["target_time_ns"] == "1800000000000000000"
    assert item["cooldown_until_ns"] == "1800000600000000000"
    assert item["target_position"] == {
        "network_id": SOLANA_MAINNET_NETWORK_ID.value,
        # Keep the position schema id expectation tied to item, target position and
        # network id in this scenario.
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value,
        "block_ordinal": 7,
        "transaction_index": 0,
        "event_index": 2,
        "boundary_ordinal": str(record.target_position.boundary_ordinal),
        # Verify the item, target position and network id relationship before this scenario is
        # accepted.
    }
    assert item["buy"]["amount_in_atomic"] == "999"
    assert item["buy"]["signed_slippage_atomic"] == "-100"
    assert item["sell"]["landing_out_atomic"] == "701"
    assert item["account_components"][0]["paid_atomic"] == "9007199254740993"
    assert item["account_components"][0]["lifecycle"] == "CLOSED_REFUNDED"
    assert item["economic_pnl_atomic"] == "-300"
    assert item["result_schema_id"] == "pumpfun-roundtrips/v4"
    assert item["execution_mode"] == "EXOGENOUS_REPLAY"
    assert item["sell_landing_liquidity"] == {
        "asset_id": "SOL",
        "observed_available_output_atomic": "1000",
        "policy_id": "real-reserve-capped-v1",
        "required_output_atomic": "710",
        "synthetic_shortfall_atomic": "0",
    }
    assert item["settled_venue_funded_atomic"] == "710"
    assert item["settled_synthetic_funded_atomic"] == "0"
    # Verify the page, next cursor and target boundary ordinal relationship before this
    # scenario is accepted.
    assert page["next_cursor"] == {
        "target_boundary_ordinal": str(cursor.target_boundary_ordinal),
        "roundtrip_id": cursor.roundtrip_id.hex,
    }
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["summary"] == summary
    assert dashboard["roundtrips"] == page

    continued = client.get(
        # Pass api v1 run-artifacts queries explicitly so get receives a reviewable
        # /api/v1/run-artifacts/ and /roundtrips input in test sniping result routes are
        # exact bounded and lossless.
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/roundtrips",
        params={
            "after_target_boundary_ordinal": page["next_cursor"]["target_boundary_ordinal"],
            "after_roundtrip_id": page["next_cursor"]["roundtrip_id"],
            "limit": 17,
            # Close the /api/v1/run-artifacts/ and /roundtrips payload only after all test
            # sniping result routes are exact bounded and lossless fields are present.
        },
    )
    assert continued.status_code == 200
    assert queries.roundtrip_request == (queries.summary_value.run_artifact_id, cursor, 17)


@pytest.mark.parametrize(
    "params",
    [
        [("after_target_boundary_ordinal", "1")],
        [("limit", "1"), ("limit", "2")],
    ],
)
def test_sniping_dashboard_rejects_noncanonical_query(
    tmp_path: Path,
    params: list[tuple[str, str]],
) -> None:
    """The combined first-page route must not silently accept cursor or duplicates."""

    queries = _StubRunResults(_sniping_summary(), RoundTripPage((), None))
    artifact_id = queries.summary_value.run_artifact_id.hex
    response = _client(tmp_path, query_run_results=queries).get(
        f"/api/v1/run-artifacts/{artifact_id}/dashboard",
        params=params,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    # Validation occurs before the application query can open an artifact.
    assert queries.summary_artifact_id is None


def test_sniping_result_routes_expose_virtual_settlement_funding(tmp_path: Path) -> None:
    """The UI receives the exact synthetic assumption without lossy integers."""

    policy_id = "virtual-reserve-output-with-explicit-synthetic-shortfall-v1"
    summary = replace(
        _sniping_summary(),
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        settlement_policy_id=policy_id,
        real_liquidity_sufficient_filled_sell_count=0,
        synthetic_liquidity_used_sell_count=1,
        venue_funded_sell_atomic=3,
        synthetic_funded_sell_atomic=707,
    )
    record = replace(
        _sniping_roundtrip(),
        execution_mode=ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        sell_reference_liquidity=QuoteLiquidityEvidenceRecord(
            policy_id=policy_id,
            asset_id=AssetId("SOL"),
            required_output_atomic=709,
            observed_available_output_atomic=3,
            synthetic_shortfall_atomic=706,
        ),
        sell_landing_liquidity=QuoteLiquidityEvidenceRecord(
            policy_id=policy_id,
            asset_id=AssetId("SOL"),
            required_output_atomic=710,
            observed_available_output_atomic=3,
            synthetic_shortfall_atomic=707,
        ),
        settled_venue_funded_atomic=3,
        settled_synthetic_funded_atomic=707,
    )
    queries = _StubRunResults(summary, RoundTripPage((record,), None))
    client = _client(tmp_path, query_run_results=queries)
    prefix = f"/api/v1/run-artifacts/{summary.run_artifact_id.hex}"

    summary_document = client.get(f"{prefix}/summary").json()
    page_document = client.get(f"{prefix}/roundtrips", params={"limit": 1}).json()

    assert summary_document["execution_mode"] == "EXOGENOUS_VIRTUAL_SETTLEMENT"
    assert summary_document["venue_funded_sell_atomic"] == "3"
    assert summary_document["synthetic_funded_sell_atomic"] == "707"
    item = page_document["items"][0]
    assert item["sell_landing_liquidity"]["observed_available_output_atomic"] == "3"
    assert item["sell_landing_liquidity"]["synthetic_shortfall_atomic"] == "707"
    assert item["settled_venue_funded_atomic"] == "3"
    assert item["settled_synthetic_funded_atomic"] == "707"


def test_sniping_summary_response_preserves_partial_valuation_as_null(tmp_path: Path) -> None:
    # Execute the test sniping summary response preserves partial valuation as null
    # workflow in explicit, reviewable steps.
    summary = replace(
        _sniping_summary(),
        open_position_count=1,
        valuation_status=SnipingValuationStatus.PARTIAL_UNVALUED_OPEN_POSITIONS,
        unvalued_open_position_count=1,
        # Pass economic pnl atomic explicitly so replace receives a reviewable partial
        # unvalued open positions and sniping summary input in test sniping summary
        # response preserves partial valuation as null.
        economic_pnl_atomic=None,
    )
    queries = _StubRunResults(summary, RoundTripPage((), None))

    response = _client(tmp_path, query_run_results=queries).get(
        f"/api/v1/run-artifacts/{summary.run_artifact_id.hex}/summary"
        # Complete get only after its /api/v1/run-artifacts/ and /summary inputs are visible
        # in test sniping summary response preserves partial valuation as null.
    )

    assert response.status_code == 200
    document = response.json()
    assert document["valuation_status"] == "PARTIAL_UNVALUED_OPEN_POSITIONS"
    assert document["unvalued_open_position_count"] == 1
    # Verify the document and valued economic pnl subtotal atomic relationship before this
    # scenario is accepted.
    assert document["valued_economic_pnl_subtotal_atomic"] == "-300"
    assert document["economic_pnl_atomic"] is None


@pytest.mark.parametrize(
    ("params", "expected_code"),
    [
        # Open the params and expected code payload explicitly for parametrize within test
        # sniping roundtrip cursor and limit fail closed.
        ({"after_target_boundary_ordinal": "1"}, "VALIDATION_ERROR"),
        ({"after_roundtrip_id": "a" * 64}, "VALIDATION_ERROR"),
        (
            {
                "after_target_boundary_ordinal": "01",
                # Keep after roundtrip id named so the params and expected code payload
                # passed to parametrize remains self-describing within test sniping
                # roundtrip cursor and limit fail closed.
                "after_roundtrip_id": "a" * 64,
            },
            "VALIDATION_ERROR",
        ),
        (
            # Open the params and expected code payload explicitly for parametrize within
            # test sniping roundtrip cursor and limit fail closed.
            {
                "after_target_boundary_ordinal": str(1 << 64),
                "after_roundtrip_id": "a" * 64,
            },
            "VALIDATION_ERROR",
            # Complete parametrize only after its params and expected code inputs are visible
            # in test sniping roundtrip cursor and limit fail closed.
        ),
        ({"limit": 201}, "VALIDATION_ERROR"),
        ({"unknown": "true"}, "VALIDATION_ERROR"),
        ([("limit", "1"), ("limit", "2")], "VALIDATION_ERROR"),
    ],
)
def test_sniping_roundtrip_cursor_and_limit_fail_closed(
    # Keep the tmp path input explicit in the test sniping roundtrip cursor and limit fail
    # closed contract.
    tmp_path: Path,
    params: dict[str, object] | list[tuple[str, str]],
    expected_code: str,
) -> None:
    # Execute the test sniping roundtrip cursor and limit fail closed workflow in
    # explicit, reviewable steps.
    record = _sniping_roundtrip()
    queries = _StubRunResults(_sniping_summary(), RoundTripPage((record,), None))

    response = _client(tmp_path, query_run_results=queries).get(
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/roundtrips",
        params=params,
        # Complete get only after its /api/v1/run-artifacts/ and /roundtrips inputs are
        # visible in test sniping roundtrip cursor and limit fail closed.
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code
    assert queries.roundtrip_request is None


@pytest.mark.parametrize(
    # Open the error code and expected status payload explicitly for parametrize within
    # test sniping result errors have stable safe responses.
    ("error_code", "expected_status", "expected_message"),
    [
        (
            "RUN_RESULT_UNAVAILABLE",
            404,
            # Pass the requested verified run explicitly so parametrize receives a
            # reviewable error code and expected status input in test sniping result
            # errors have stable safe responses.
            "The requested verified Run result is unavailable.",
        ),
        (
            "RUN_HAS_NO_PUMPFUN_SNIPING_RESULTS",
            409,
            # Pass the exact run artifact explicitly so parametrize receives a reviewable
            # error code and expected status input in test sniping result errors have
            # stable safe responses.
            "The exact Run artifact does not contain Pump.fun Sniping results.",
        ),
    ],
)
def test_sniping_result_errors_have_stable_safe_responses(
    # Keep the tmp path input explicit in the test sniping result errors have stable safe
    # responses contract.
    tmp_path: Path,
    error_code: str,
    expected_status: int,
    expected_message: str,
) -> None:
    # Execute the test sniping result errors have stable safe responses workflow in
    # explicit, reviewable steps.
    queries = _StubRunResults(
        _sniping_summary(),
        RoundTripPage((), None),
        error=RunResultQueryError(error_code),
    )

    # Assemble response once so the test sniping result errors have stable safe responses
    # workflow shares one value.
    response = _client(tmp_path, query_run_results=queries).get(
        f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/summary"
    )

    assert response.status_code == expected_status
    assert response.json() == {"code": error_code, "message": expected_message}
    # Verify '/Users/' not in response.text before this scenario is accepted.
    assert "/Users/" not in response.text


def test_sniping_result_response_obeys_transport_size_limit(tmp_path: Path) -> None:
    # Execute the test sniping result response obeys transport size limit workflow in
    # explicit, reviewable steps.
    queries = _StubRunResults(_sniping_summary(), RoundTripPage((), None))

    response = _client(
        tmp_path,
        query_run_results=queries,
        max_request_bytes=128,
        # Complete get only after its /api/v1/run-artifacts/ and /summary inputs are visible
        # in test sniping result response obeys transport size limit.
    ).get(f"/api/v1/run-artifacts/{queries.summary_value.run_artifact_id.hex}/summary")

    assert response.status_code == 413
    assert response.json()["code"] == "RESPONSE_TOO_LARGE"


def test_sniping_roundtrip_response_rejects_lossy_integer_transport() -> None:
    # Execute the test sniping roundtrip response rejects lossy integer transport workflow
    # in explicit, reviewable steps.
    response = RoundTripResponse.from_domain(_sniping_roundtrip())
    document = response.model_dump(mode="json")
    document["target_time_ns"] = 1_800_000_000_000_000_000

    with pytest.raises(ValidationError):
        RoundTripResponse.model_validate(document)

    # Assemble document once so the test sniping roundtrip response rejects lossy integer
    # transport workflow shares one value.
    document = response.model_dump(mode="json")
    target_position = document["target_position"]
    assert isinstance(target_position, dict)
    target_position["boundary_ordinal"] = 30_064_771_073
    with pytest.raises(ValidationError):
        # Invoke model_validate for document as a visible test sniping roundtrip response
        # rejects lossy integer transport step.
        RoundTripResponse.model_validate(document)
