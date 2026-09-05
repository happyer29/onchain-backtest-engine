# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

# Import pytest at the visible module dependency boundary.
import pytest
from typer.testing import CliRunner

from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.errors import ErrorCode, SourceEvidenceValidationError
from backtest.application.job_views import job_input_artifact_ids_digest
from backtest.application.models import (
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    JobRecord,
    JobType,
    ListJobsRequest,
    ResolvedJobSpec,
    # Close the models import after its required symbols are visible.
)
from backtest.application.ports.run_results import RoundTripCursor, RoundTripPage
from backtest.application.run_contracts import PUMPFUN_SNIPING_CONTRACT, RunContractDescriptor
from backtest.application.use_cases.query_run_results import PumpfunSnipingRunSummaryView
from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.identifiers import (
    # Include account id so the identifiers dependency remains explicit.
    AccountId,
    ArtifactId,
    AssetId,
    ContentDigest,
    ExecutionAttemptId,
    # Include job id so the identifiers dependency remains explicit.
    JobId,
    LogicalRunId,
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
)
from backtest.engine.sniping import SnipingValuationStatus
from backtest.interfaces.cli import CliUsageError, create_cli


# Keep the jobs backend contract and validation rules together.
class _JobsBackend:
    def __init__(self) -> None:
        # Execute the jobs backend init workflow in explicit, reviewable steps.
        self.list_request: ListJobsRequest | None = None
        self.retry_id: JobId | None = None

    def list_jobs(self, request: ListJobsRequest) -> tuple[()]:
        # Execute the jobs backend list jobs workflow in explicit, reviewable steps.
        self.list_request = request
        return ()

    def retry_job(self, job_id: JobId) -> JobRecord:
        # Execute the jobs backend retry job workflow in explicit, reviewable steps.
        self.retry_id = job_id
        payload = b"{}"
        payload_digest = ContentDigest(sha256(payload).hexdigest())
        spec = ResolvedJobSpec(
            spec_version=1,
            # Keep the content digest and resolved job spec hex ContentDigest step visible
            # while building spec.
            spec_id=ContentDigest(
                resolved_job_spec_hex(
                    spec_version=1,
                    job_type=JobType.GC.value,
                    payload_digest_hex=payload_digest.hex,
                    # Pass input artifact hexes explicitly so resolved_job_spec_hex
                    # receives a reviewable value and gc input in jobs backend retry job.
                    input_artifact_hexes=(),
                )
            ),
            job_type=JobType.GC,
            canonical_payload=payload,
            # Pass payload digest explicitly so ResolvedJobSpec receives a reviewable
            # value and hex input in jobs backend retry job.
            payload_digest=payload_digest,
        )
        return JobRecord(job_id, spec, AttemptState.QUEUED, 2)


class _RejectedInspectionBackend(_JobsBackend):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__()
        self.code = code

    def inspect_source(
        self,
        source_id: object,
        *,
        evidence_from_block: int | None = None,
        evidence_to_block: int | None = None,
        decision_from_block: int | None = None,
        decision_to_block: int | None = None,
    ) -> object:
        del (
            source_id,
            evidence_from_block,
            evidence_to_block,
            decision_from_block,
            decision_to_block,
        )
        raise SourceEvidenceValidationError(self.code) from RuntimeError("password=cli-secret")


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
        realized_cash_pnl_atomic=-9_007_199_254_740_994,
        valuation_status=SnipingValuationStatus.COMPLETE,
        unvalued_open_position_count=0,
        valued_economic_pnl_subtotal_atomic=-9_007_199_254_740_995,
        economic_pnl_atomic=-9_007_199_254_740_995,
        # Pass cashback receivable atomic explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        cashback_receivable_atomic=9_007_199_254_740_993,
        protocol_fee_paid_atomic=9_007_199_254_740_996,
        creator_fee_paid_atomic=9_007_199_254_740_997,
        network_base_fee_paid_atomic=9_007_199_254_740_998,
        network_priority_fee_paid_atomic=9_007_199_254_740_999,
        # Pass account deposit paid atomic explicitly so PumpfunSnipingRunSummaryView
        # receives a reviewable 1 and 2 input in sniping summary.
        account_deposit_paid_atomic=9_007_199_254_741_000,
        account_deposit_refunded_atomic=9_007_199_254_741_000,
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
            block_ordinal=4_000_000,
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
            amount_in_atomic=9_007_199_254_740_993,
            reference_out_atomic=9_007_199_254_741_000,
            landing_out_atomic=9_007_199_254_740_900,
            minimum_out_atomic=9_007_199_254_740_900,
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
            amount_in_atomic=9_007_199_254_740_900,
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
        acquired_token_amount_atomic=9_007_199_254_740_900,
        cashback_receivable_atomic=9_007_199_254_740_993,
        realized_cash_pnl_atomic=-9_007_199_254_740_994,
        mtm_status=MtmStatus.NOT_APPLICABLE,
        # Pass mtm liquidation value atomic explicitly so RoundTripRecord receives a
        # reviewable a and b input in sniping roundtrip.
        mtm_liquidation_value_atomic=None,
        mtm_cash_pnl_atomic=None,
        economic_pnl_atomic=-9_007_199_254_740_995,
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


# Keep the results backend contract and validation rules together.
class _ResultsBackend(_JobsBackend):
    def __init__(self) -> None:
        # Execute the results backend init workflow in explicit, reviewable steps.
        super().__init__()
        record = _sniping_roundtrip()
        self.summary = _sniping_summary()
        self.page = RoundTripPage(
            (record,),
            # Keep the boundary ordinal RoundTripCursor step visible while building
            # self.page.
            RoundTripCursor(record.target_position.boundary_ordinal, record.roundtrip_id),
        )
        self.contract_schema: str | None = None
        self.summary_artifact_id: ArtifactId | None = None
        self.roundtrip_request: (
            # Keep the tuple component named inside the self roundtrip request contract.
            tuple[
                ArtifactId,
                RoundTripCursor | None,
                int,
            ]
            # Complete the self roundtrip request group only after its semantic components
            # are visible.
            | None
        ) = None

    def describe_run_contract(self, schema: str) -> RunContractDescriptor:
        # Execute the results backend describe run contract workflow in explicit,
        # reviewable steps.
        self.contract_schema = schema
        return PUMPFUN_SNIPING_CONTRACT

    def show_run_summary(self, artifact_id: ArtifactId) -> PumpfunSnipingRunSummaryView:
        # Execute the results backend show run summary workflow in explicit, reviewable
        # steps.
        self.summary_artifact_id = artifact_id
        return self.summary

    def list_roundtrips(
        self,
        artifact_id: ArtifactId,
        # Close the list roundtrips signature after its explicit inputs.
        *,
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        # Execute the results backend list roundtrips workflow in explicit, reviewable
        # steps.
        self.roundtrip_request = (artifact_id, after, limit)
        return self.page


# Keep the factory contract and validation rules together.
class _Factory:
    def __init__(self, backend: _JobsBackend) -> None:
        # Execute the factory init workflow in explicit, reviewable steps.
        self.backend = backend
        self.calls: list[tuple[Path, Path | None, bool, bool]] = []

    def __call__(
        self,
        config_path: Path,
        # Keep the capabilities file input explicit in the call contract.
        capabilities_file: Path | None,
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
    ) -> _JobsBackend:
        # Execute the factory call workflow in explicit, reviewable steps.
        self.calls.append(
            (
                config_path,
                capabilities_file,
                require_capabilities,
                # Pass prefer running controller explicitly so append receives a
                # reviewable config path and capabilities file input in factory call.
                prefer_running_controller,
            )
        )
        return self.backend


def test_cli_uses_injected_backend_without_composing_infrastructure(tmp_path: Path) -> None:
    # Execute the test cli uses injected backend without composing infrastructure workflow
    # in explicit, reviewable steps.
    backend = _JobsBackend()
    factory = _Factory(backend)
    config = tmp_path / "local.toml"

    result = CliRunner().invoke(create_cli(factory), ["jobs", "--config", str(config)])

    assert result.exit_code == 0, result.output
    # Verify the loads, stdout and items relationship before this scenario is accepted.
    assert json.loads(result.stdout) == {"items": []}
    assert factory.calls == [(config, None, False, True)]
    assert backend.list_request == ListJobsRequest(state=None, limit=100, offset=0)


def test_cli_prints_only_safe_composition_error() -> None:
    # Execute the test cli prints only safe composition error workflow in explicit,
    # reviewable steps.
    secret = "password=do-not-print /private/credentials.toml"

    def failing_factory(
        config_path: Path,
        capabilities_file: Path | None,
        *,
        # Keep the require capabilities input explicit in the failing factory contract.
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
    ) -> _JobsBackend:
        # Execute the failing factory workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities, prefer_running_controller
        raise CliUsageError("LOCAL_CONFIG_INVALID", "Local configuration is invalid.") from OSError(
            secret
        )

    result = CliRunner().invoke(create_cli(failing_factory), ["jobs"])

    # Verify result.exit_code == 2 before this scenario is accepted.
    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "code": "LOCAL_CONFIG_INVALID",
        "message": "Local configuration is invalid.",
    }
    # Verify secret not in result.output before this scenario is accepted.
    assert secret not in result.output


def test_cli_hides_os_error_details() -> None:
    # Execute the test cli hides os error details workflow in explicit, reviewable steps.
    secret = "api_key=do-not-print /private/credentials.toml"

    def failing_factory(
        config_path: Path,
        capabilities_file: Path | None,
        *,
        # Keep the require capabilities input explicit in the failing factory contract.
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
    ) -> _JobsBackend:
        # Execute the failing factory workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities, prefer_running_controller
        raise OSError(secret)

    result = CliRunner().invoke(create_cli(failing_factory), ["jobs"])

    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        # Keep the code expectation tied to loads, stderr and code in this scenario.
        "code": "LOCAL_INPUT_ERROR",
        "message": "A local input or configuration file could not be read.",
    }
    assert secret not in result.output


@pytest.mark.parametrize(
    # Pass flag value explicitly so parametrize receives a reviewable flag,value and
    # --evidence-from-block input in test inspect source cli rejects a half specified
    # evidence range.
    "flag,value",
    (
        ("--evidence-from-block", "100"),
        ("--evidence-to-block", "120"),
    ),
    # Complete parametrize only after its flag,value and --evidence-from-block inputs are
    # visible in test inspect source cli rejects a half specified evidence range.
)
def test_inspect_source_cli_rejects_a_half_specified_evidence_range(
    flag: str,
    value: str,
) -> None:
    # Execute the test inspect source cli rejects a half specified evidence range workflow
    # in explicit, reviewable steps.
    factory = _Factory(_JobsBackend())

    result = CliRunner().invoke(
        create_cli(factory),
        ["inspect-source", flag, value],
    )

    # Verify result.exit_code == 2 before this scenario is accepted.
    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "code": "INVALID_EVIDENCE_RANGE",
        "message": "Both bounded evidence block limits must be provided together.",
    }
    # Verify factory.calls == [] before this scenario is accepted.
    assert factory.calls == []


@pytest.mark.parametrize(
    "code",
    (ErrorCode.INCOMPLETE_BLOCK_RANGE, ErrorCode.CURVE_TRANSITION_MISMATCH),
)
def test_inspect_source_cli_prints_safe_typed_evidence_rejection(code: ErrorCode) -> None:
    result = CliRunner().invoke(
        create_cli(_Factory(_RejectedInspectionBackend(code))),
        [
            "inspect-source",
            "--evidence-from-block",
            "100",
            "--evidence-to-block",
            "120",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "code": code.value,
        "message": SourceEvidenceValidationError(code).safe_message,
    }
    assert "cli-secret" not in result.output


def test_retry_job_cli_delegates_a_typed_job_id_and_returns_operational_state() -> None:
    # Execute the test retry job cli delegates a typed job id and returns operational
    # state workflow in explicit, reviewable steps.
    backend = _JobsBackend()
    job_id = JobId("failed-job")

    result = CliRunner().invoke(create_cli(_Factory(backend)), ["retry-job", job_id.value])

    assert result.exit_code == 0, result.output
    assert backend.retry_id == job_id
    # Verify the loads, stdout and input artifact count relationship before this scenario
    # is accepted.
    assert json.loads(result.stdout) == {
        "input_artifact_count": 0,
        "input_artifact_ids_digest": job_input_artifact_ids_digest(()).hex,
        "job_id": job_id.value,
        "job_type": "GC",
        # Keep the payload digest expectation tied to loads, stdout and input artifact
        # count in this scenario.
        "payload_digest": sha256(b"{}").hexdigest(),
        "spec_id": resolved_job_spec_hex(
            spec_version=1,
            job_type=JobType.GC.value,
            payload_digest_hex=sha256(b"{}").hexdigest(),
            # Pass input artifact hexes explicitly so resolved_job_spec_hex receives a
            # reviewable value and gc input in test retry job cli delegates a typed job id
            # and returns operational state.
            input_artifact_hexes=(),
        ),
        "spec_version": 1,
        "state": "QUEUED",
        "state_version": 2,
        "submitted_at_ns": "0",
        "updated_at_ns": "0",
        # Verify the loads, stdout and input artifact count relationship before this scenario
        # is accepted.
    }


def test_describe_run_contract_cli_prints_the_closed_typed_contract() -> None:
    # Execute the test describe run contract cli prints the closed typed contract workflow
    # in explicit, reviewable steps.
    backend = _ResultsBackend()
    factory = _Factory(backend)

    result = CliRunner().invoke(
        create_cli(factory),
        ["describe-run-contract", PUMPFUN_SNIPING_CONTRACT.schema],
        # Complete invoke only after its describe-run-contract and schema inputs are visible
        # in test describe run contract cli prints the closed typed contract.
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == PUMPFUN_SNIPING_CONTRACT.document()
    assert backend.contract_schema == PUMPFUN_SNIPING_CONTRACT.schema
    assert factory.calls == [(Path("configs/local-16gb.toml"), None, False, True)]


# Define test show run summary cli keeps all atomic values as decimal strings as one
# focused operation with an explicit boundary.
def test_show_run_summary_cli_keeps_all_atomic_values_as_decimal_strings() -> None:
    # Execute the test show run summary cli keeps all atomic values as decimal strings
    # workflow in explicit, reviewable steps.
    backend = _ResultsBackend()
    factory = _Factory(backend)

    result = CliRunner().invoke(
        create_cli(factory),
        ["show-run-summary", backend.summary.run_artifact_id.hex],
        # Complete invoke only after its show-run-summary and hex inputs are visible in test
        # show run summary cli keeps all atomic values as decimal strings.
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["run_artifact_id"] == backend.summary.run_artifact_id.hex
    assert document["network_id"] == SOLANA_MAINNET_NETWORK_ID.value
    # Verify the value, document and position schema id relationship before this scenario
    # is accepted.
    assert document["position_schema_id"] == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value
    assert document["realized_cash_pnl_atomic"] == "-9007199254740994"
    assert document["valuation_status"] == "COMPLETE"
    assert document["unvalued_open_position_count"] == 0
    assert document["valued_economic_pnl_subtotal_atomic"] == "-9007199254740995"
    # Verify the document and economic pnl atomic relationship before this scenario is
    # accepted.
    assert document["economic_pnl_atomic"] == "-9007199254740995"
    assert document["cashback_receivable_atomic"] == "9007199254740993"
    assert document["protocol_fee_paid_atomic"] == "9007199254740996"
    assert document["creator_fee_paid_atomic"] == "9007199254740997"
    assert document["network_base_fee_paid_atomic"] == "9007199254740998"
    # Verify the document and network priority fee paid atomic relationship before this
    # scenario is accepted.
    assert document["network_priority_fee_paid_atomic"] == "9007199254740999"
    assert document["account_deposit_paid_atomic"] == "9007199254741000"
    assert document["account_deposit_refunded_atomic"] == "9007199254741000"
    assert document["account_deposit_locked_atomic"] == "0"
    assert document["favorable_slippage_count"] == 1
    # Verify the document and adverse slippage count relationship before this scenario is
    # accepted.
    assert document["adverse_slippage_count"] == 1
    assert document["buy_slippage_failure_count"] == 0
    assert document["sell_slippage_failure_count"] == 0
    assert document["summary_schema_id"] == "pumpfun-sniping-run-summary/v3"
    assert document["execution_mode"] == "EXOGENOUS_REPLAY"
    assert document["settlement_policy_id"] == "real-reserve-capped-v1"
    assert document["filled_sell_count"] == 1
    assert document["venue_funded_sell_atomic"] == "710"
    assert document["synthetic_funded_sell_atomic"] == "0"
    assert backend.summary_artifact_id == backend.summary.run_artifact_id
    assert factory.calls == [(Path("configs/local-16gb.toml"), None, False, True)]


# Define test show run summary cli preserves partial valuation as null as one focused
# operation with an explicit boundary.
def test_show_run_summary_cli_preserves_partial_valuation_as_null() -> None:
    # Execute the test show run summary cli preserves partial valuation as null workflow
    # in explicit, reviewable steps.
    backend = _ResultsBackend()
    backend.summary = replace(
        backend.summary,
        open_position_count=1,
        valuation_status=SnipingValuationStatus.PARTIAL_UNVALUED_OPEN_POSITIONS,
        # Pass unvalued open position count explicitly so replace receives a reviewable
        # summary and partial unvalued open positions input in test show run summary cli
        # preserves partial valuation as null.
        unvalued_open_position_count=1,
        economic_pnl_atomic=None,
    )

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        # Open the show-run-summary and hex payload explicitly for invoke within test show
        # run summary cli preserves partial valuation as null.
        ["show-run-summary", backend.summary.run_artifact_id.hex],
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["valuation_status"] == "PARTIAL_UNVALUED_OPEN_POSITIONS"
    # Verify the document and unvalued open position count relationship before this
    # scenario is accepted.
    assert document["unvalued_open_position_count"] == 1
    assert document["valued_economic_pnl_subtotal_atomic"] == "-9007199254740995"
    assert document["economic_pnl_atomic"] is None


def test_list_roundtrips_cli_parses_paired_cursor_and_is_bigint_safe() -> None:
    # Execute the test list roundtrips cli parses paired cursor and is bigint safe
    # workflow in explicit, reviewable steps.
    backend = _ResultsBackend()
    factory = _Factory(backend)
    record = backend.page.items[0]
    after = RoundTripCursor(record.target_position.boundary_ordinal, ContentDigest("0" * 64))

    result = CliRunner().invoke(
        # Keep the factory create_cli step visible while building result.
        create_cli(factory),
        [
            "list-roundtrips",
            backend.summary.run_artifact_id.hex,
            "--after",
            # Pass after target boundary ordinal after roundtrip id explicitly so invoke
            # receives a reviewable list-roundtrips and --after input in test list
            # roundtrips cli parses paired cursor and is bigint safe.
            f"{after.target_boundary_ordinal}:{after.roundtrip_id.hex}",
            "--limit",
            "17",
        ],
    )

    # Verify result.exit_code == 0 before this scenario is accepted.
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert backend.roundtrip_request == (backend.summary.run_artifact_id, after, 17)
    assert document["next_cursor"] == (
        f"{record.target_position.boundary_ordinal}:{record.roundtrip_id.hex}"
        # Verify the document, next cursor and boundary ordinal relationship before this
        # scenario is accepted.
    )
    item = document["items"][0]
    assert item["target_time_ns"] == "1800000000000000000"
    assert item["cooldown_until_ns"] == "1800000600000000000"
    assert item["target_position"]["boundary_ordinal"] == str(
        # Pass record explicitly so str receives a reviewable boundary ordinal and target
        # position input in test list roundtrips cli parses paired cursor and is bigint
        # safe.
        record.target_position.boundary_ordinal
    )
    assert item["buy"]["amount_in_atomic"] == "9007199254740993"
    assert item["acquired_token_amount_atomic"] == "9007199254740900"
    assert item["realized_cash_pnl_atomic"] == "-9007199254740994"
    assert item["account_components"][0]["paid_atomic"] == "9007199254740993"
    # Verify the item and economic pnl atomic relationship before this scenario is
    # accepted.
    assert item["economic_pnl_atomic"] == "-9007199254740995"
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
    assert factory.calls == [(Path("configs/local-16gb.toml"), None, False, True)]


@pytest.mark.parametrize(
    "cursor",
    (
        # Pass missing-separator explicitly so parametrize receives a reviewable cursor
        # and missing-separator input in test list roundtrips cli rejects malformed or
        # noncanonical cursor.
        "missing-separator",
        "01:" + "a" * 64,
        "+1:" + "a" * 64,
        str(1 << 64) + ":" + "a" * 64,
        "1:not-a-digest",
        # Complete parametrize only after its cursor and missing-separator inputs are visible
        # in test list roundtrips cli rejects malformed or noncanonical cursor.
    ),
)
def test_list_roundtrips_cli_rejects_malformed_or_noncanonical_cursor(cursor: str) -> None:
    # Execute the test list roundtrips cli rejects malformed or noncanonical cursor
    # workflow in explicit, reviewable steps.
    backend = _ResultsBackend()

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        [
            "list-roundtrips",
            # Pass backend explicitly so invoke receives a reviewable list-roundtrips and
            # --after input in test list roundtrips cli rejects malformed or noncanonical
            # cursor.
            backend.summary.run_artifact_id.hex,
            "--after",
            cursor,
        ],
    )

    # Verify result.exit_code == 2 before this scenario is accepted.
    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "code": "INVALID_ROUNDTRIP_CURSOR",
        "message": "Round-trip cursor must be BOUNDARY_ORDINAL:ROUNDTRIP_ID.",
    }
    # Verify backend.roundtrip_request is None before this scenario is accepted.
    assert backend.roundtrip_request is None


def test_list_roundtrips_cli_rejects_limit_above_200_before_backend() -> None:
    # Execute the test list roundtrips cli rejects limit above 200 before backend workflow
    # in explicit, reviewable steps.
    backend = _ResultsBackend()

    result = CliRunner().invoke(
        create_cli(_Factory(backend)),
        [
            "list-roundtrips",
            # Pass backend explicitly so invoke receives a reviewable list-roundtrips and
            # --limit input in test list roundtrips cli rejects limit above 200 before
            # backend.
            backend.summary.run_artifact_id.hex,
            "--limit",
            "201",
        ],
    )

    # Verify result.exit_code == 2 before this scenario is accepted.
    assert result.exit_code == 2
    assert backend.roundtrip_request is None
