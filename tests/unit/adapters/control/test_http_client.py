# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace

# Import message at the visible module dependency boundary.
from email.message import Message
from hashlib import sha256
from io import BytesIO
from typing import cast
from urllib.error import HTTPError

# Import parse at the visible module dependency boundary.
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, ProxyHandler, Request

import pytest

from backtest.adapters.control import (
    ControlApiError,
    # Include control api protocol error so the control dependency remains explicit.
    ControlApiProtocolError,
    LocalControlApiClient,
)
from backtest.application.job_views import job_input_artifact_ids_digest
from backtest.application.models import AttemptState, JobType, ListJobsRequest

# Import run results at the visible module dependency boundary.
from backtest.application.ports.run_results import RoundTripCursor
from backtest.application.run_contracts import PUMPFUN_SNIPING_CONTRACT
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.domain.account_requirements import (
    AccountComponentLifecycle,
    AccountComponentRecord,
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
    ChainPosition,
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    # Include account id so the identifiers dependency remains explicit.
    AccountId,
    ArtifactId,
    AssetId,
    ContentDigest,
    JobId,
    # Include venue id so the identifiers dependency remains explicit.
    VenueId,
)
from backtest.domain.ledger import LedgerCorrelationKind
from backtest.domain.roundtrips import (
    MtmStatus,
    QuoteLiquidityEvidenceRecord,
    RoundTripLegRecord,
    # Include round trip leg side so the roundtrips dependency remains explicit.
    RoundTripLegSide,
    RoundTripRecord,
    RoundTripStatus,
)

# Import sniping at the visible module dependency boundary.
from backtest.engine.sniping import SnipingValuationStatus
from backtest.interfaces.api.schemas import RoundTripResponse

_TOKEN = "session-token-0123456789-abcdefghijk"


# Keep the response contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    # Declare headers explicitly in the response contract.
    headers: tuple[tuple[str, str], ...] = ()


# Keep the opened response contract and validation rules together.
class _OpenedResponse:
    def __init__(self, response: _Response) -> None:
        # Execute the opened response init workflow in explicit, reviewable steps.
        self.status = response.status
        self.headers: Message[str, str] = Message()
        self.headers.add_header("Content-Type", response.content_type)
        if not any(name.casefold() == "content-length" for name, _ in response.headers):
            self.headers.add_header("Content-Length", str(len(response.body)))
        # Traverse response.headers explicitly so each opened response init iteration
        # remains traceable.
        for name, value in response.headers:
            self.headers.add_header(name, value)
        self._stream = BytesIO(response.body)

    def read(self, amount: int = -1) -> bytes:
        return self._stream.read(amount)

    # Define opened response enter as one focused operation with an explicit boundary.
    def __enter__(self) -> _OpenedResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args


# Keep the fake opener contract and validation rules together.
@dataclass(slots=True)
class _FakeOpener:
    responses: dict[tuple[str, str], _Response]
    requests: list[tuple[str, str, dict[str, str], bytes]] = field(default_factory=list)

    def open(self, request: Request, timeout: float) -> _OpenedResponse:
        # Execute the fake opener open workflow in explicit, reviewable steps.
        assert 0 < timeout <= 30
        parsed = urlsplit(request.full_url)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        headers = {key.casefold(): value for key, value in request.header_items()}
        body = request.data or b""
        # Invoke append for method and target as a visible fake opener open step.
        self.requests.append((request.method, target, headers, body))
        response = self.responses.get(
            (request.method, target),
            _Response(404, b'{"code":"NOT_FOUND","message":"Not found."}'),
        )
        # Assemble opened once so the fake opener open workflow shares one value.
        opened = _OpenedResponse(response)
        if response.status >= 300:
            # Handle the fake opener open response.status >= 300 branch as a distinct
            # logical block.
            raise HTTPError(
                request.full_url,
                response.status,
                "bounded fake response",
                opened.headers,
                # Pass opened explicitly so HTTPError receives a reviewable bounded fake
                # response and full url input in fake opener open.
                opened._stream,
            )
        return opened


def _client(
    opener: _FakeOpener,
    # Close the client signature after its explicit inputs.
    *,
    maximum_response_bytes: int = 2 * 1024 * 1024,
) -> LocalControlApiClient:
    # Execute the client workflow in explicit, reviewable steps.
    return LocalControlApiClient(
        "127.0.0.1",
        8080,
        maximum_response_bytes=maximum_response_bytes,
        opener=cast(OpenerDirector, opener),
        # Complete LocalControlApiClient only after its 1 and cast inputs are visible in
        # client.
    )


def _root(*, token: str = _TOKEN) -> _Response:
    # Execute the root workflow in explicit, reviewable steps.
    return _Response(
        200,
        b"<!doctype html><title>On-Chain Backtest Engine</title>",
        content_type="text/html; charset=utf-8",
        headers=(("Set-Cookie", f"backtest_session={token}; HttpOnly; SameSite=Strict; Path=/"),),
        # Complete _Response only after its text/html; charset=utf-8 and set-cookie inputs are
        # visible in root.
    )


def _job_document(*, state: str = "QUEUED") -> dict[str, object]:
    # Execute the job document workflow in explicit, reviewable steps.
    return {
        "job_id": "job-1",
        "spec_version": 1,
        "spec_id": "1" * 64,
        "job_type": "RUN_BACKTEST",
        # Include payload digest in the completed job document result.
        "payload_digest": "2" * 64,
        "input_artifact_count": 0,
        "input_artifact_ids_digest": job_input_artifact_ids_digest(()).hex,
        "state": state,
        "state_version": 0,
        "submitted_at_ns": "1800000000000000000",
        "updated_at_ns": "1800000000000000000",
        # Return the completed job document result without a hidden fallback.
    }


def _artifact_document(*, artifact_id: str = "a" * 64) -> dict[str, object]:
    # Execute the artifact document workflow in explicit, reviewable steps.
    manifest = {"artifact_schema": "fixture/v1"}
    manifest_bytes = canonical_json_bytes(manifest)
    return {
        "descriptor": {
            "artifact_id": artifact_id,
            # Include build key in the completed artifact document result.
            "build_key": "b" * 64,
            "input_artifact_ids": [],
            "kind": "RUN",
            "manifest_digest": sha256(manifest_bytes).hexdigest(),
        },
        # Include manifest in the completed artifact document result.
        "manifest": manifest,
    }


def _lineage_document(*, root_artifact_id: str = "a" * 64) -> dict[str, object]:
    # Execute the lineage document workflow in explicit, reviewable steps.
    descriptor = cast(
        dict[str, object], _artifact_document(artifact_id=root_artifact_id)["descriptor"]
    )
    return {
        "artifacts": [descriptor],
        # Include edges in the completed lineage document result.
        "edges": [],
        "root_artifact_id": root_artifact_id,
    }


def _run_document(*, logical_run_id: str = "c" * 64) -> dict[str, object]:
    # Execute the run document workflow in explicit, reviewable steps.
    comparison = {
        "accepted_order_count": 1,
        "audit_hash": "f" * 64,
        "canonical_result_hash": "e" * 64,
        "delivered_event_count": 1,
        # Keep the failed order count component named inside the comparison contract.
        "failed_order_count": 0,
        "fill_count": 1,
        "fill_hash": "1" * 64,
        "filled_order_count": 1,
        "final_balances_count": 2,
        # Keep the final balances digest component named inside the comparison contract.
        "final_balances_digest": "2" * 64,
        "historical_event_count": 2,
        "historical_group_count": 2,
        "ledger_hash": "3" * 64,
        "ledger_transaction_count": 2,
        # Keep the rejected order count component named inside the comparison contract.
        "rejected_order_count": 0,
    }
    return {
        "audit_hash": comparison["audit_hash"],
        "canonical_result_hash": comparison["canonical_result_hash"],
        # Include canonicality in the completed run document result.
        "canonicality": "CANONICAL_EXACT",
        "completed_at": "2026-01-01T00:00:01Z",
        "comparison": comparison,
        "execution_attempt_id": "d" * 64,
        "logical_run_id": logical_run_id,
        "physical_settings": {
            # Include backend in the completed run document result.
            "backend": "reference-python-v1",
            "output_buffer_rows": 8192,
            "reader_batch_rows": 65536,
            "reader_readahead": 1,
            "schema": "backtest.run-physical-settings/v2",
            # Include threads in the completed run document result.
            "threads": 1,
        },
        "run_artifact_id": "a" * 64,
        "started_at": "2026-01-01T00:00:00Z",
        "warnings": [],
    }


# Define sniping summary document as one focused operation with an explicit boundary.
def _sniping_summary_document() -> dict[str, object]:
    # Execute the sniping summary document workflow in explicit, reviewable steps.
    return {
        "accepted_buy_count": 1,
        "accepted_order_count": 2,
        "account_deposit_locked_atomic": "0",
        "account_deposit_paid_atomic": "9007199254741000",
        # Include account deposit refunded atomic in the completed sniping summary
        # document result.
        "account_deposit_refunded_atomic": "9007199254741000",
        "adverse_slippage_count": 1,
        "audit_hash": "5" * 64,
        "buy_slippage_failure_count": 0,
        "canonical_result_hash": "4" * 64,
        # Include cashback receivable atomic in the completed sniping summary document
        # result.
        "cashback_receivable_atomic": "9007199254740993",
        "closed_position_count": 1,
        "cooldown_skipped_count": 1,
        "creator_fee_paid_atomic": "9007199254740997",
        "delivered_event_count": 12,
        # Include economic pnl atomic in the completed sniping summary document result.
        "economic_pnl_atomic": "-9007199254740995",
        "execution_mode": "EXOGENOUS_REPLAY",
        "execution_attempt_id": "3" * 64,
        "failed_buy_count": 0,
        "failed_order_count": 0,
        "failed_sell_count": 0,
        # Include favorable slippage count in the completed sniping summary document
        # result.
        "favorable_slippage_count": 1,
        "fill_count": 2,
        "fill_hash": "7" * 64,
        "filled_order_count": 2,
        "filled_sell_count": 1,
        "final_balances_count": 16_385,
        # Include final balances digest in the completed sniping summary document result.
        "final_balances_digest": "9" * 64,
        "historical_event_count": 11,
        "historical_group_count": 10,
        "gross_sell_settlement_atomic": "700",
        "ledger_hash": "6" * 64,
        "ledger_transaction_count": 4,
        # Include logical run id in the completed sniping summary document result.
        "logical_run_id": "2" * 64,
        "network_base_fee_paid_atomic": "9007199254740998",
        "network_id": SOLANA_MAINNET_NETWORK_ID.value,
        "network_priority_fee_paid_atomic": "9007199254740999",
        "open_position_count": 0,
        # Include position schema id in the completed sniping summary document result.
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value,
        "protocol_fee_paid_atomic": "9007199254740996",
        "real_liquidity_sufficient_filled_sell_count": 1,
        "realized_cash_pnl_atomic": "-9007199254740994",
        "rejected_order_count": 0,
        "roundtrip_count": 2,
        # Include roundtrip digest in the completed sniping summary document result.
        "roundtrip_digest": "8" * 64,
        "run_artifact_id": "1" * 64,
        "sell_slippage_failure_count": 0,
        "settlement_policy_id": "real-reserve-capped-v1",
        "summary_schema_id": "pumpfun-sniping-run-summary/v3",
        "synthetic_funded_sell_atomic": "0",
        "synthetic_liquidity_used_sell_count": 0,
        "target_count": 2,
        "unvalued_open_position_count": 0,
        # Include valuation status in the completed sniping summary document result.
        "valuation_status": "COMPLETE",
        "valued_economic_pnl_subtotal_atomic": "-9007199254740995",
        "venue_funded_sell_atomic": "700",
    }


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
        cashback_receivable_atomic=21,
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


def _sniping_roundtrip_document() -> dict[str, object]:
    # Return the completed sniping roundtrip document result without a hidden fallback.
    return RoundTripResponse.from_domain(_sniping_roundtrip()).model_dump(mode="json")


def _json_response(value: object, *, status: int = 200) -> _Response:
    # Execute the json response workflow in explicit, reviewable steps.
    return _Response(
        status,
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    )


def test_submit_uses_session_and_canonical_typed_body() -> None:
    # Execute the test submit uses session and canonical typed body workflow in explicit,
    # reviewable steps.
    opener = _FakeOpener(
        {
            ("GET", "/"): _root(),
            ("POST", "/api/v1/jobs"): _json_response(_job_document(), status=202),
        }
        # Complete _FakeOpener only after its get and / inputs are visible in test submit uses
        # session and canonical typed body.
    )
    result = _client(opener).submit_job(
        SubmitJobRequest(
            spec_version=1,
            job_type=JobType.RUN_BACKTEST,
            # Pass z explicitly so SubmitJobRequest receives a reviewable exact-submit and
            # run backtest input in test submit uses session and canonical typed body.
            payload_json=b'{"z":2,"schema":"fixture/v1","a":1}',
            idempotency_key="exact-submit",
        )
    )

    assert result.job_id == JobId("job-1")
    # Verify result.state is AttemptState.QUEUED before this scenario is accepted.
    assert result.state is AttemptState.QUEUED
    assert len(opener.requests) == 2
    method, path, headers, body = opener.requests[-1]
    assert (method, path) == ("POST", "/api/v1/jobs")
    assert headers["cookie"] == f"backtest_session={_TOKEN}"
    # Verify headers['x-backtest-csrf'] == '1' before this scenario is accepted.
    assert headers["x-backtest-csrf"] == "1"
    assert headers["idempotency-key"] == "exact-submit"
    assert headers["origin"] == "http://127.0.0.1:8080"
    assert body == (
        b'{"input_artifact_ids":[],"job_type":"RUN_BACKTEST",'
        # Keep the payload expectation tied to body in this scenario.
        b'"payload":{"a":1,"schema":"fixture/v1","z":2},"spec_version":1}'
    )


def test_health_list_get_and_cursor_events_are_strictly_bounded() -> None:
    # Execute the test health list get and cursor events are strictly bounded workflow in
    # explicit, reviewable steps.
    event = {
        "event_id": 7,
        "job_id": "job-1",
        "attempt_id": "attempt-1",
        "event_type": "ATTEMPT_PROGRESS",
        # Keep the state version component named inside the event contract.
        "state_version": 2,
        "created_at_ns": 123,
        "progress": {
            "sequence": 3,
            "level": "INFO",
            # Keep the stage component named inside the event contract.
            "stage": "RUNNING_BACKTEST",
            "completed_units": 1,
            "total_units": 2,
            "coalesced_events": 1,
            "dropped_transport_frames": 0,
            # Keep the private rss bytes component named inside the event contract.
            "private_rss_bytes": 10,
            "total_rss_bytes": 20,
            "major_page_faults": 0,
            "temporary_disk_bytes": 0,
        },
        # Complete the event group only after its semantic components are visible.
    }
    opener = _FakeOpener(
        {
            ("GET", "/api/v1/health"): _json_response(
                {
                    # Keep control plane id named so the ok and control plane id payload
                    # passed to _json_response remains self-describing within test health
                    # list get and cursor events are strictly bounded.
                    "control_plane_id": "f" * 64,
                    "status": "ok",
                    "profile": "local-test",
                    "version": "1",
                }
                # Complete _json_response only after its ok and control plane id inputs are
                # visible in test health list get and cursor events are strictly bounded.
            ),
            ("GET", "/api/v1/run-physical-settings"): _json_response(
                {
                    "backend": "reference-python-v1",
                    "output_buffer_rows": 8192,
                    # Keep reader batch rows named so the backend and output buffer rows
                    # payload passed to _json_response remains self-describing within test
                    # health list get and cursor events are strictly bounded.
                    "reader_batch_rows": 65536,
                    "reader_readahead": 1,
                    "schema": "backtest.run-physical-settings/v2",
                    "threads": 1,
                }
                # Complete _json_response only after its backend and output buffer rows inputs
                # are visible in test health list get and cursor events are strictly bounded.
            ),
            ("GET", "/api/v1/jobs?limit=2&offset=0&state=QUEUED"): _json_response(
                {"items": [_job_document()], "next_cursor": None}
            ),
            ("GET", "/api/v1/jobs/job-1"): _json_response(_job_document()),
            # Keep the json response and items _json_response step visible while building
            # opener.
            ("GET", "/api/v1/jobs/job-1/events?after_event_id=6&limit=2"): _json_response(
                {"items": [event]}
            ),
        }
    )
    # Assemble client once so the test health list get and cursor events are strictly
    # bounded workflow shares one value.
    client = _client(opener)

    assert client.health().profile == "local-test"
    assert client.health().control_plane_id == ContentDigest("f" * 64)
    assert client.run_physical_settings().reader_batch_rows == 65_536
    assert len(client.list_jobs(ListJobsRequest(state=AttemptState.QUEUED, limit=2, offset=0))) == 1
    # Verify the spec id, content digest and get job relationship before this scenario is
    # accepted.
    assert client.get_job(JobId("job-1")).spec_id == ContentDigest("1" * 64)
    events = client.list_job_events(JobId("job-1"), after_event_id=6, limit=2)

    assert len(events) == 1
    assert events[0].event_id == 7
    assert events[0].progress is not None
    # Verify the value, running backtest and stage relationship before this scenario is
    # accepted.
    assert events[0].progress.stage.value == "RUNNING_BACKTEST"


def test_safe_api_error_is_typed_but_malformed_responses_fail_closed() -> None:
    # Execute the test safe api error is typed but malformed responses fail closed
    # workflow in explicit, reviewable steps.
    conflict = _FakeOpener(
        {
            ("GET", "/"): _root(),
            ("POST", "/api/v1/jobs"): _json_response(
                {"code": "IDEMPOTENCY_CONFLICT", "message": "The key is already in use."},
                # Pass status explicitly so _json_response receives a reviewable code and
                # message input in test safe api error is typed but malformed responses
                # fail closed.
                status=409,
            ),
        }
    )
    with pytest.raises(ControlApiError) as raised:
        # Keep raises, control api error and pytest active only for the bounded test safe
        # api error is typed but malformed responses fail closed operation.
        _client(conflict).submit_job(
            SubmitJobRequest(1, JobType.RUN_BACKTEST, b'{"schema":"fixture/v1"}', "same")
        )
    assert raised.value.status_code == 409
    assert raised.value.code == "IDEMPOTENCY_CONFLICT"
    # Verify the value and raised relationship before this scenario is accepted.
    assert str(raised.value) == "The key is already in use."

    duplicate = _FakeOpener(
        {
            ("GET", "/api/v1/health"): _Response(
                200,
                # Pass control plane id explicitly into _Response within test safe api
                # error is typed but malformed responses fail closed.
                b'{"control_plane_id":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",'
                b'"status":"ok","status":"ok","profile":"x","version":"1"}',
            )
        }
    )
    # Acquire raises, control api protocol error and pytest at an explicit test safe api
    # error is typed but malformed responses fail closed context boundary so cleanup
    # remains scoped.
    with pytest.raises(ControlApiProtocolError):
        _client(duplicate).health()

    extra = _job_document()
    extra["unexpected"] = "field"
    unexpected = _FakeOpener({("GET", "/api/v1/jobs/job-1"): _json_response(extra)})
    # Acquire raises, control api protocol error and pytest at an explicit test safe api
    # error is typed but malformed responses fail closed context boundary so cleanup
    # remains scoped.
    with pytest.raises(ControlApiProtocolError):
        _client(unexpected).get_job(JobId("job-1"))


def test_artifact_and_lineage_documents_are_exact_typed_views() -> None:
    # Execute the test artifact and lineage documents are exact typed views workflow in
    # explicit, reviewable steps.
    artifact_id = ArtifactId("a" * 64)
    opener = _FakeOpener(
        {
            ("GET", f"/api/v1/artifacts/{artifact_id.hex}"): _json_response(_artifact_document()),
            ("GET", f"/api/v1/lineage/{artifact_id.hex}"): _json_response(_lineage_document()),
            # Close the get and /api/v1/artifacts/ payload only after all test artifact and
            # lineage documents are exact typed views fields are present.
        }
    )
    client = _client(opener)

    details = client.artifact_document(artifact_id)
    lineage = client.lineage_document(artifact_id)

    # Verify the artifact id, descriptor and details relationship before this scenario is
    # accepted.
    assert details.descriptor.artifact_id == artifact_id
    assert json.loads(details.manifest_bytes) == {"artifact_schema": "fixture/v1"}
    assert lineage.root_artifact_id == artifact_id
    assert lineage.artifacts == (details.descriptor,)


@pytest.mark.parametrize(
    # Pass path and document explicitly so parametrize receives a reviewable path and
    # document and /api/v1/artifacts/ input in test artifact and lineage documents reject
    # wrong ids and shapes.
    "path_and_document",
    (
        (
            "/api/v1/artifacts/" + "a" * 64,
            {**_artifact_document(), "unexpected": True},
            # Complete parametrize only after its path and document and /api/v1/artifacts/
            # inputs are visible in test artifact and lineage documents reject wrong ids and
            # shapes.
        ),
        (
            "/api/v1/artifacts/" + "a" * 64,
            _artifact_document(artifact_id="b" * 64),
        ),
        # Open the path and document and /api/v1/artifacts/ payload explicitly for
        # parametrize within test artifact and lineage documents reject wrong ids and
        # shapes.
        (
            "/api/v1/artifacts/" + "a" * 64,
            {
                **_artifact_document(),
                "descriptor": {
                    # Define test artifact and lineage documents reject wrong ids and
                    # shapes as one focused operation with an explicit boundary.
                    **cast(dict[str, object], _artifact_document()["descriptor"]),
                    "unexpected": True,
                },
            },
        ),
        # Open the path and document and /api/v1/artifacts/ payload explicitly for
        # parametrize within test artifact and lineage documents reject wrong ids and
        # shapes.
        (
            "/api/v1/lineage/" + "a" * 64,
            {**_lineage_document(), "root_artifact_id": "b" * 64},
        ),
        (
            # Pass api v1 lineage explicitly so parametrize receives a reviewable path and
            # document and /api/v1/artifacts/ input in test artifact and lineage documents
            # reject wrong ids and shapes.
            "/api/v1/lineage/" + "a" * 64,
            {**_lineage_document(), "unexpected": True},
        ),
    ),
)
# Define test artifact and lineage documents reject wrong ids and shapes as one focused
# operation with an explicit boundary.
def test_artifact_and_lineage_documents_reject_wrong_ids_and_shapes(
    path_and_document: tuple[str, dict[str, object]],
) -> None:
    # Execute the test artifact and lineage documents reject wrong ids and shapes workflow
    # in explicit, reviewable steps.
    path, document = path_and_document
    client = _client(_FakeOpener({("GET", path): _json_response(document)}))

    with pytest.raises(ControlApiProtocolError):
        # Keep raises, control api protocol error and pytest active only for the bounded
        # test artifact and lineage documents reject wrong ids and shapes operation.
        if path.startswith("/api/v1/artifacts/"):
            client.artifact_document(ArtifactId("a" * 64))
        else:
            client.lineage_document(ArtifactId("a" * 64))


def test_lineage_document_rejects_oversized_collections_before_item_parsing() -> None:
    # Execute the test lineage document rejects oversized collections before item parsing
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("a" * 64)
    document = _lineage_document()
    document["edges"] = [{}] * 1_001
    client = _client(
        _FakeOpener(
            # Open the get and /api/v1/lineage/ payload explicitly for _FakeOpener within
            # test lineage document rejects oversized collections before item parsing.
            {
                ("GET", f"/api/v1/lineage/{artifact_id.hex}"): _json_response(document),
            }
        )
    )

    # Acquire raises, control api protocol error and pytest at an explicit test lineage
    # document rejects oversized collections before item parsing context boundary so
    # cleanup remains scoped.
    with pytest.raises(ControlApiProtocolError):
        client.lineage_document(artifact_id)


def test_run_documents_are_strict_typed_and_paginated_for_both_routes() -> None:
    # Execute the test run documents are strict typed and paginated for both routes
    # workflow in explicit, reviewable steps.
    logical_run_id = "c" * 64
    opener = _FakeOpener(
        {
            ("GET", "/api/v1/runs?limit=2&offset=3"): _json_response(
                {"items": [_run_document()], "next_cursor": None}
            ),
            (
                # Pass get explicitly so _FakeOpener receives a reviewable get and
                # /api/v1/runs?limit=2&offset=3 input in test run documents are strict
                # typed and paginated for both routes.
                "GET",
                f"/api/v1/runs/{logical_run_id}?limit=1&offset=4",
            ): _json_response({"items": [_run_document()], "next_cursor": None}),
        }
    )
    # Assemble client once so the test run documents are strict typed and paginated for
    # both routes workflow shares one value.
    client = _client(opener)

    listed = client.run_documents(limit=2, offset=3)
    logical = client.run_documents(logical_run_id=logical_run_id, limit=1, offset=4)

    assert listed[0].run_artifact_id == ArtifactId("a" * 64)
    assert listed[0].canonical_result_hash == ContentDigest("e" * 64)
    # Verify the final balances digest, comparison and content digest relationship before
    # this scenario is accepted.
    assert listed[0].comparison.final_balances_digest == ContentDigest("2" * 64)
    assert logical[0].logical_run_id.hex == logical_run_id


@pytest.mark.parametrize(
    "mutate",
    (
        # Define test run documents reject extra missing alias and noncanonical fields as
        # one focused operation with an explicit boundary.
        lambda document: document.update({"unexpected": True}),
        lambda document: document.pop("audit_hash"),
        lambda document: document.update({"run_artifact_id": "not-a-digest"}),
        lambda document: document.update({"started_at": "2026-01-01T00:00:00"}),
        lambda document: document.update({"completed_at": "2026-01-01T00:00:01+00:00"}),
        lambda document: cast(dict[str, object], document["comparison"]).update(
            {"unexpected": True}
            # Complete update only after its unexpected inputs are visible in test run
            # documents reject extra missing alias and noncanonical fields.
        ),
        lambda document: cast(dict[str, object], document["comparison"]).pop("fill_count"),
        lambda document: document.update({"warnings": ["z", "a"]}),
    ),
)
# Define test run documents reject extra missing alias and noncanonical fields as one
# focused operation with an explicit boundary.
def test_run_documents_reject_extra_missing_alias_and_noncanonical_fields(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    # Execute the test run documents reject extra missing alias and noncanonical fields
    # workflow in explicit, reviewable steps.
    document = _run_document()
    mutate(document)
    client = _client(
        _FakeOpener(
            {("GET", "/api/v1/runs?limit=1&offset=0"): _json_response({"items": [document]})}
            # Complete _FakeOpener only after its get and /api/v1/runs?limit=1&offset=0 inputs
            # are visible in test run documents reject extra missing alias and noncanonical
            # fields.
        )
    )

    with pytest.raises(ControlApiProtocolError):
        client.run_documents(limit=1)


def test_run_documents_reject_wrong_logical_id_and_oversized_page() -> None:
    # Execute the test run documents reject wrong logical id and oversized page workflow
    # in explicit, reviewable steps.
    logical_run_id = "c" * 64
    wrong = _FakeOpener(
        {
            (
                "GET",
                # Pass api v1 runs logical run id explicitly so _FakeOpener receives a
                # reviewable get and /api/v1/runs/ input in test run documents reject
                # wrong logical id and oversized page.
                f"/api/v1/runs/{logical_run_id}?limit=1&offset=0",
            ): _json_response({"items": [_run_document(logical_run_id="b" * 64)]}),
        }
    )
    with pytest.raises(ControlApiProtocolError):
        # Invoke run_documents for logical run id as a visible test run documents reject
        # wrong logical id and oversized page step.
        _client(wrong).run_documents(logical_run_id=logical_run_id, limit=1)

    oversized = _FakeOpener(
        {
            ("GET", "/api/v1/runs?limit=50&offset=0"): _json_response(
                {"items": [_run_document()] * 51}
                # Complete _json_response only after its items and run document inputs are
                # visible in test run documents reject wrong logical id and oversized page.
            ),
        }
    )
    with pytest.raises(ControlApiProtocolError):
        _client(oversized).run_documents(limit=50)


# Define test run contract is exact sorted and selected by schema as one focused operation
# with an explicit boundary.
def test_run_contract_is_exact_sorted_and_selected_by_schema() -> None:
    # Execute the test run contract is exact sorted and selected by schema workflow in
    # explicit, reviewable steps.
    path = "/api/v1/run-contracts"
    opener = _FakeOpener(
        {("GET", path): _json_response({"items": [PUMPFUN_SNIPING_CONTRACT.document()]})}
    )

    result = _client(opener).run_contract(PUMPFUN_SNIPING_CONTRACT.schema)

    # Verify result == PUMPFUN_SNIPING_CONTRACT before this scenario is accepted.
    assert result == PUMPFUN_SNIPING_CONTRACT
    assert opener.requests[-1][:2] == ("GET", path)


def test_run_contract_rejects_unknown_schema_without_fallback() -> None:
    # Execute the test run contract rejects unknown schema without fallback workflow in
    # explicit, reviewable steps.
    client = _client(
        _FakeOpener(
            {
                ("GET", "/api/v1/run-contracts"): _json_response(
                    {"items": [PUMPFUN_SNIPING_CONTRACT.document()]}
                    # Complete _json_response only after its items and document inputs are
                    # visible in test run contract rejects unknown schema without fallback.
                )
            }
        )
    )

    with pytest.raises(ControlApiError) as captured:
        # Invoke run_contract for unknown-run-draft/v1 as a visible test run contract
        # rejects unknown schema without fallback step.
        client.run_contract("unknown-run-draft/v1")

    assert captured.value.status_code == 404
    assert captured.value.code == "RUN_CONTRACT_NOT_FOUND"


def test_run_contract_rejects_non_exact_or_noncanonical_documents() -> None:
    # Execute the test run contract rejects non exact or noncanonical documents workflow
    # in explicit, reviewable steps.
    extra_outer = {"items": [PUMPFUN_SNIPING_CONTRACT.document()], "extra": True}
    extra_contract = PUMPFUN_SNIPING_CONTRACT.document()
    extra_contract["extra"] = True
    unsorted_fields = PUMPFUN_SNIPING_CONTRACT.document()
    fields = unsorted_fields["editable_fields"]
    # Verify isinstance(fields, list) before this scenario is accepted.
    assert isinstance(fields, list)
    unsorted_fields["editable_fields"] = list(reversed(fields))
    non_string_semantic = PUMPFUN_SNIPING_CONTRACT.document()
    semantics = non_string_semantic["fixed_semantics"]
    assert isinstance(semantics, dict)
    # Assemble semantics['buy delay transactions'] once so the test run contract rejects
    # non exact or noncanonical documents workflow shares one value.
    semantics["buy_delay_transactions"] = 500

    for response in (
        extra_outer,
        {"items": [extra_contract]},
        {"items": [unsorted_fields]},
        # Traverse extra outer, items and extra contract explicitly so each test run
        # contract rejects non exact or noncanonical documents iteration remains
        # traceable.
        {"items": [non_string_semantic]},
        {
            "items": [
                PUMPFUN_SNIPING_CONTRACT.document(),
                PUMPFUN_SNIPING_CONTRACT.document(),
                # Traverse extra outer, items and extra contract explicitly so each test run
                # contract rejects non exact or noncanonical documents iteration remains
                # traceable.
            ]
        },
    ):
        # Process extra outer, items and extra contract inside the bounded test run
        # contract rejects non exact or noncanonical documents loop.
        client = _client(_FakeOpener({("GET", "/api/v1/run-contracts"): _json_response(response)}))
        with pytest.raises(ControlApiProtocolError):
            client.run_contract(PUMPFUN_SNIPING_CONTRACT.schema)


def test_sniping_summary_is_lossless_and_bound_to_requested_artifact() -> None:
    # Execute the test sniping summary is lossless and bound to requested artifact
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/summary"
    opener = _FakeOpener({("GET", path): _json_response(_sniping_summary_document())})

    result = _client(opener).sniping_run_summary(artifact_id)

    assert result.run_artifact_id == artifact_id
    # Verify the network id, solana mainnet network id and result relationship before this
    # scenario is accepted.
    assert result.network_id == SOLANA_MAINNET_NETWORK_ID
    assert result.realized_cash_pnl_atomic == -9_007_199_254_740_994
    assert result.valuation_status is SnipingValuationStatus.COMPLETE
    assert result.unvalued_open_position_count == 0
    assert result.valued_economic_pnl_subtotal_atomic == -9_007_199_254_740_995
    # Verify the economic pnl atomic and result relationship before this scenario is
    # accepted.
    assert result.economic_pnl_atomic == -9_007_199_254_740_995
    assert result.cashback_receivable_atomic == 9_007_199_254_740_993
    assert result.protocol_fee_paid_atomic == 9_007_199_254_740_996
    assert result.creator_fee_paid_atomic == 9_007_199_254_740_997
    assert result.network_base_fee_paid_atomic == 9_007_199_254_740_998
    # Verify the network priority fee paid atomic and result relationship before this
    # scenario is accepted.
    assert result.network_priority_fee_paid_atomic == 9_007_199_254_740_999
    assert result.account_deposit_paid_atomic == 9_007_199_254_741_000
    assert result.account_deposit_refunded_atomic == 9_007_199_254_741_000
    assert result.account_deposit_locked_atomic == 0
    assert result.favorable_slippage_count == 1
    # Verify result.adverse_slippage_count == 1 before this scenario is accepted.
    assert result.adverse_slippage_count == 1
    assert result.buy_slippage_failure_count == 0
    assert result.sell_slippage_failure_count == 0
    assert opener.requests[-1][:2] == ("GET", path)


def test_sniping_summary_preserves_partial_valuation_as_null() -> None:
    # Execute the test sniping summary preserves partial valuation as null workflow in
    # explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/summary"
    document = _sniping_summary_document()
    document.update(
        {
            # Keep economic pnl atomic named so the economic pnl atomic and open position
            # count payload passed to update remains self-describing within test sniping
            # summary preserves partial valuation as null.
            "economic_pnl_atomic": None,
            "open_position_count": 1,
            "unvalued_open_position_count": 1,
            "valuation_status": "PARTIAL_UNVALUED_OPEN_POSITIONS",
        }
        # Complete update only after its economic pnl atomic and open position count inputs
        # are visible in test sniping summary preserves partial valuation as null.
    )

    result = _client(_FakeOpener({("GET", path): _json_response(document)})).sniping_run_summary(
        artifact_id
    )

    assert result.valuation_status is SnipingValuationStatus.PARTIAL_UNVALUED_OPEN_POSITIONS
    # Verify the unvalued open position count and result relationship before this scenario
    # is accepted.
    assert result.unvalued_open_position_count == 1
    assert result.valued_economic_pnl_subtotal_atomic == -9_007_199_254_740_995
    assert result.economic_pnl_atomic is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    # Open the field and invalid value payload explicitly for parametrize within test
    # sniping summary rejects lossy or noncanonical decimal fields.
    (
        ("cashback_receivable_atomic", 9_007_199_254_740_993),
        ("cashback_receivable_atomic", "01"),
        ("cashback_receivable_atomic", "-1"),
        ("realized_cash_pnl_atomic", "+1"),
        # Open the field and invalid value payload explicitly for parametrize within test
        # sniping summary rejects lossy or noncanonical decimal fields.
        ("realized_cash_pnl_atomic", "-0"),
        ("economic_pnl_atomic", "01"),
        ("valued_economic_pnl_subtotal_atomic", "-0"),
        ("protocol_fee_paid_atomic", 9_007_199_254_740_996),
        ("creator_fee_paid_atomic", "-1"),
        # Open the field and invalid value payload explicitly for parametrize within test
        # sniping summary rejects lossy or noncanonical decimal fields.
        ("network_base_fee_paid_atomic", "01"),
        ("network_priority_fee_paid_atomic", "+1"),
        ("account_deposit_paid_atomic", 9_007_199_254_741_000),
        ("account_deposit_refunded_atomic", "01"),
        ("account_deposit_locked_atomic", "-1"),
        # Complete parametrize only after its field and invalid value inputs are visible in
        # test sniping summary rejects lossy or noncanonical decimal fields.
    ),
)
def test_sniping_summary_rejects_lossy_or_noncanonical_decimal_fields(
    field: str,
    invalid_value: object,
    # Close the test sniping summary rejects lossy or noncanonical decimal fields signature
    # after its explicit inputs.
) -> None:
    # Execute the test sniping summary rejects lossy or noncanonical decimal fields
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    document = _sniping_summary_document()
    document[field] = invalid_value
    client = _client(
        _FakeOpener(
            # Open the get and /api/v1/run-artifacts/ payload explicitly for _FakeOpener
            # within test sniping summary rejects lossy or noncanonical decimal fields.
            {
                (
                    "GET",
                    f"/api/v1/run-artifacts/{artifact_id.hex}/summary",
                ): _json_response(document)
                # Close the get and /api/v1/run-artifacts/ payload only after all test sniping
                # summary rejects lossy or noncanonical decimal fields fields are present.
            }
        )
    )

    with pytest.raises(ControlApiProtocolError):
        client.sniping_run_summary(artifact_id)


# Define test sniping summary rejects wrong artifact and non exact schema as one focused
# operation with an explicit boundary.
def test_sniping_summary_rejects_wrong_artifact_and_non_exact_schema() -> None:
    # Execute the test sniping summary rejects wrong artifact and non exact schema
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    wrong_id = _sniping_summary_document()
    wrong_id["run_artifact_id"] = "0" * 64
    extra = _sniping_summary_document()
    extra["path"] = "/private/result.parquet"
    # Assemble missing once so the test sniping summary rejects wrong artifact and non
    # exact schema workflow shares one value.
    missing = _sniping_summary_document()
    missing.pop("roundtrip_digest")

    for document in (wrong_id, extra, missing):
        # Process (wrong_id, extra, missing) inside the bounded test sniping summary
        # rejects wrong artifact and non exact schema loop.
        client = _client(
            _FakeOpener(
                {
                    (
                        "GET",
                        # Pass api v1 run-artifacts artifact id explicitly so _FakeOpener
                        # receives a reviewable get and /api/v1/run-artifacts/ input in
                        # test sniping summary rejects wrong artifact and non exact
                        # schema.
                        f"/api/v1/run-artifacts/{artifact_id.hex}/summary",
                    ): _json_response(document)
                }
            )
        )
        # Acquire raises, control api protocol error and pytest at an explicit test
        # sniping summary rejects wrong artifact and non exact schema context boundary so
        # cleanup remains scoped.
        with pytest.raises(ControlApiProtocolError):
            client.sniping_run_summary(artifact_id)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("execution_mode", "EXOGENOUS_VIRTUAL_SETTLEMENT"),
        ("filled_sell_count", None),
        ("gross_sell_settlement_atomic", "701"),
        ("synthetic_funded_sell_atomic", "1"),
    ),
)
def test_sniping_summary_rejects_inconsistent_settlement_semantics(
    field: str,
    invalid_value: object,
) -> None:
    """The HTTP reader enforces the same cross-field contract as local readers."""

    artifact_id = ArtifactId("1" * 64)
    document = _sniping_summary_document()
    document[field] = invalid_value
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/summary"

    with pytest.raises(ControlApiProtocolError):
        _client(_FakeOpener({("GET", path): _json_response(document)})).sniping_run_summary(
            artifact_id
        )


def test_sniping_roundtrips_use_paired_keyset_and_lossless_documents() -> None:
    # Execute the test sniping roundtrips use paired keyset and lossless documents
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    record = _sniping_roundtrip()
    after = RoundTripCursor(record.target_position.boundary_ordinal, ContentDigest("0" * 64))
    response_cursor = {
        "roundtrip_id": record.roundtrip_id.hex,
        # Register boundary ordinal through str so the response cursor table remains
        # scannable.
        "target_boundary_ordinal": str(record.target_position.boundary_ordinal),
    }
    path = (
        f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=17"
        f"&after_target_boundary_ordinal={after.target_boundary_ordinal}"
        # Keep the after roundtrip id after roundtrip id hex component named inside the
        # path contract.
        f"&after_roundtrip_id={after.roundtrip_id.hex}"
    )
    opener = _FakeOpener(
        {
            ("GET", path): _json_response(
                # Keep the sniping roundtrip document _sniping_roundtrip_document step
                # visible while building opener.
                {"items": [_sniping_roundtrip_document()], "next_cursor": response_cursor}
            )
        }
    )

    result = _client(opener).sniping_roundtrips(artifact_id, after=after, limit=17)

    # Verify result.items == (record,) before this scenario is accepted.
    assert result.items == (record,)
    assert result.next_cursor == RoundTripCursor(
        record.target_position.boundary_ordinal, record.roundtrip_id
    )
    assert opener.requests[-1][:2] == ("GET", path)


def test_sniping_roundtrips_accept_suppressed_target_without_account_components() -> None:
    """Cooldown-suppressed launches never resolve account requirements."""

    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    record = replace(
        _sniping_roundtrip(),
        cooldown_consumed=False,
        status=RoundTripStatus.COOLDOWN_SKIPPED,
        buy=None,
        sell=None,
        acquired_token_amount_atomic=0,
        cashback_receivable_atomic=0,
        realized_cash_pnl_atomic=None,
        economic_pnl_atomic=None,
        account_components=(),
        sell_reference_liquidity=None,
        sell_landing_liquidity=None,
        settled_venue_funded_atomic=0,
    )
    response = {
        "items": [RoundTripResponse.from_domain(record).model_dump(mode="json")],
        "next_cursor": None,
    }

    result = _client(_FakeOpener({("GET", path): _json_response(response)})).sniping_roundtrips(
        artifact_id, after=None, limit=1
    )

    assert result.items == (record,)
    assert result.items[0].account_components == ()


# Apply parametrize semantics to the following test sniping roundtrips reject invalid
# limit before http contract.
@pytest.mark.parametrize("limit", (0, 201, True))
def test_sniping_roundtrips_reject_invalid_limit_before_http(limit: int) -> None:
    # Execute the test sniping roundtrips reject invalid limit before http workflow in
    # explicit, reviewable steps.
    opener = _FakeOpener({})

    with pytest.raises(ValueError, match="between 1 and 200"):
        _client(opener).sniping_roundtrips(ArtifactId("1" * 64), after=None, limit=limit)

    assert opener.requests == []


def test_sniping_roundtrips_reject_non_exact_nested_schemas() -> None:
    # Execute the test sniping roundtrips reject non exact nested schemas workflow in
    # explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    item_extra = _sniping_roundtrip_document()
    item_extra["raw_path"] = "/private/result.parquet"
    leg_extra = _sniping_roundtrip_document()
    # Assemble buy once so the test sniping roundtrips reject non exact nested schemas
    # workflow shares one value.
    buy = leg_extra["buy"]
    assert isinstance(buy, dict)
    buy["extra"] = True
    position_extra = _sniping_roundtrip_document()
    position = position_extra["target_position"]
    # Verify isinstance(position, dict) before this scenario is accepted.
    assert isinstance(position, dict)
    position["slot"] = 4_000_000

    for response in (
        {"items": [item_extra], "next_cursor": None},
        {"items": [leg_extra], "next_cursor": None},
        # Traverse items, next cursor and extra explicitly so each test sniping roundtrips
        # reject non exact nested schemas iteration remains traceable.
        {"items": [position_extra], "next_cursor": None},
        {"items": [_sniping_roundtrip_document()], "next_cursor": None, "extra": True},
        {"items": [_sniping_roundtrip_document()] * 2, "next_cursor": None},
    ):
        # Process items, next cursor and extra inside the bounded test sniping roundtrips
        # reject non exact nested schemas loop.
        client = _client(_FakeOpener({("GET", path): _json_response(response)}))
        with pytest.raises(ControlApiProtocolError):
            client.sniping_roundtrips(artifact_id, after=None, limit=1)


def test_sniping_roundtrips_reject_inconsistent_chain_position_identity_and_boundary() -> None:
    # Execute the test sniping roundtrips reject inconsistent chain position identity and
    # boundary workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    wrong_network = _sniping_roundtrip_document()
    target = wrong_network["target_position"]
    assert isinstance(target, dict)
    # Use a valid alternate genesis so the response still reaches cross-position checks.
    target["network_id"] = "solana:11111111111111111111111111111112"
    wrong_schema = _sniping_roundtrip_document()
    buy = wrong_schema["buy"]
    assert isinstance(buy, dict)
    decision = buy["decision_position"]
    # Verify isinstance(decision, dict) before this scenario is accepted.
    assert isinstance(decision, dict)
    decision["position_schema_id"] = "other-position-v1"
    wrong_boundary = _sniping_roundtrip_document()
    target = wrong_boundary["target_position"]
    assert isinstance(target, dict)
    # Assemble target['boundary ordinal'] once so the test sniping roundtrips reject
    # inconsistent chain position identity and boundary workflow shares one value.
    target["boundary_ordinal"] = str(int(cast(str, target["boundary_ordinal"])) + 1)

    for item in (wrong_network, wrong_schema, wrong_boundary):
        # Process wrong network, wrong schema and wrong boundary inside the bounded test
        # sniping roundtrips reject inconsistent chain position identity and boundary
        # loop.
        client = _client(
            _FakeOpener({("GET", path): _json_response({"items": [item], "next_cursor": None})})
        )
        with pytest.raises(ControlApiProtocolError):
            client.sniping_roundtrips(artifact_id, after=None, limit=1)


# Apply parametrize semantics to the following test sniping roundtrips require canonical
# decimal boundary string contract.
@pytest.mark.parametrize("invalid_boundary", (17_179_869_184_000_001, "01", "+1"))
def test_sniping_roundtrips_require_canonical_decimal_boundary_string(
    invalid_boundary: object,
) -> None:
    # Execute the test sniping roundtrips require canonical decimal boundary string
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    document = _sniping_roundtrip_document()
    target = document["target_position"]
    assert isinstance(target, dict)
    # Assemble target['boundary ordinal'] once so the test sniping roundtrips require
    # canonical decimal boundary string workflow shares one value.
    target["boundary_ordinal"] = invalid_boundary
    client = _client(
        _FakeOpener({("GET", path): _json_response({"items": [document], "next_cursor": None})})
    )

    with pytest.raises(ControlApiProtocolError):
        # Invoke sniping_roundtrips for artifact id as a visible test sniping roundtrips
        # require canonical decimal boundary string step.
        client.sniping_roundtrips(artifact_id, after=None, limit=1)


@pytest.mark.parametrize("invalid_amount", (9_007_199_254_740_993, "01", "+1", "-1"))
def test_sniping_roundtrips_require_canonical_decimal_leg_atomic_strings(
    invalid_amount: object,
) -> None:
    # Execute the test sniping roundtrips require canonical decimal leg atomic strings
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    document = _sniping_roundtrip_document()
    buy = document["buy"]
    assert isinstance(buy, dict)
    # Assemble buy['amount in atomic'] once so the test sniping roundtrips require
    # canonical decimal leg atomic strings workflow shares one value.
    buy["amount_in_atomic"] = invalid_amount
    client = _client(
        _FakeOpener({("GET", path): _json_response({"items": [document], "next_cursor": None})})
    )

    with pytest.raises(ControlApiProtocolError):
        # Invoke sniping_roundtrips for artifact id as a visible test sniping roundtrips
        # require canonical decimal leg atomic strings step.
        client.sniping_roundtrips(artifact_id, after=None, limit=1)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("target_time_ns", 1_800_000_000_000_000_000),
        # Open the field and invalid value payload explicitly for parametrize within test
        # sniping roundtrips reject lossy or noncanonical decimal fields.
        ("target_time_ns", "01"),
        ("target_time_ns", "+1"),
        ("cooldown_until_ns", "-1"),
        ("economic_pnl_atomic", "-0"),
        ("economic_pnl_atomic", "01"),
        # Open the field and invalid value payload explicitly for parametrize within test
        # sniping roundtrips reject lossy or noncanonical decimal fields.
        ("cashback_receivable_atomic", "-1"),
    ),
)
def test_sniping_roundtrips_reject_lossy_or_noncanonical_decimal_fields(
    field: str,
    # Keep the invalid value input explicit in the test sniping roundtrips reject lossy or
    # noncanonical decimal fields contract.
    invalid_value: object,
) -> None:
    # Execute the test sniping roundtrips reject lossy or noncanonical decimal fields
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    document = _sniping_roundtrip_document()
    document[field] = invalid_value
    client = _client(
        # Keep the fake opener and get _FakeOpener step visible while building client.
        _FakeOpener({("GET", path): _json_response({"items": [document], "next_cursor": None})})
    )

    with pytest.raises(ControlApiProtocolError):
        client.sniping_roundtrips(artifact_id, after=None, limit=1)


def test_sniping_roundtrips_reject_malformed_or_inconsistent_response_cursor() -> None:
    # Execute the test sniping roundtrips reject malformed or inconsistent response cursor
    # workflow in explicit, reviewable steps.
    artifact_id = ArtifactId("1" * 64)
    record = _sniping_roundtrip()
    path = f"/api/v1/run-artifacts/{artifact_id.hex}/roundtrips?limit=1"
    malformed = {
        "roundtrip_id": record.roundtrip_id.hex,
        # Keep the target boundary ordinal component named inside the malformed contract.
        "target_boundary_ordinal": "01",
    }
    not_last_row = {
        "roundtrip_id": "c" * 64,
        "target_boundary_ordinal": str(record.target_position.boundary_ordinal),
        # Complete the not last row group only after its semantic components are visible.
    }

    for cursor in (malformed, not_last_row):
        # Process (malformed, not_last_row) inside the bounded test sniping roundtrips
        # reject malformed or inconsistent response cursor loop.
        client = _client(
            _FakeOpener(
                {
                    ("GET", path): _json_response(
                        {"items": [_sniping_roundtrip_document()], "next_cursor": cursor}
                        # Complete _json_response only after its items and next cursor inputs
                        # are visible in test sniping roundtrips reject malformed or
                        # inconsistent response cursor.
                    )
                }
            )
        )
        with pytest.raises(ControlApiProtocolError):
            # Invoke sniping_roundtrips for artifact id as a visible test sniping
            # roundtrips reject malformed or inconsistent response cursor step.
            client.sniping_roundtrips(artifact_id, after=None, limit=1)


@pytest.mark.parametrize(
    ("headers", "body", "maximum"),
    [
        (("Content-Length", "128"), b"{}", 64),
        # Open the headers and body payload explicitly for parametrize within test
        # response content length is single exact and bounded.
        (("Content-Length", "100"), b"{}", 128),
        (("Content-Length", "2"), b"{}", 128),
    ],
)
def test_response_content_length_is_single_exact_and_bounded(
    # Keep the headers input explicit in the test response content length is single exact
    # and bounded contract.
    headers: tuple[str, str],
    body: bytes,
    maximum: int,
) -> None:
    # Execute the test response content length is single exact and bounded workflow in
    # explicit, reviewable steps.
    response_headers = (headers, headers) if headers == ("Content-Length", "2") else (headers,)
    opener = _FakeOpener(
        {
            ("GET", "/api/v1/health"): _Response(
                200,
                # Pass body explicitly so _Response receives a reviewable body and
                # response headers input in test response content length is single exact
                # and bounded.
                body,
                headers=response_headers,
            )
        }
    )
    # Acquire raises, control api protocol error and pytest at an explicit test response
    # content length is single exact and bounded context boundary so cleanup remains
    # scoped.
    with pytest.raises(ControlApiProtocolError):
        _client(opener, maximum_response_bytes=maximum).health()


@pytest.mark.parametrize(
    "unsafe_token",
    (
        # Pass short explicitly so parametrize receives a reviewable unsafe token and
        # short input in test unsafe session cookie never enters request header.
        "short",
        "a" * 31 + ";",
        "a" * 31 + ",",
        "a" * 31 + " ",
    ),
    # Complete parametrize only after its unsafe token and short inputs are visible in test
    # unsafe session cookie never enters request header.
)
def test_unsafe_session_cookie_never_enters_request_header(unsafe_token: str) -> None:
    # Execute the test unsafe session cookie never enters request header workflow in
    # explicit, reviewable steps.
    opener = _FakeOpener(
        {
            ("GET", "/"): _root(token=unsafe_token),
            ("POST", "/api/v1/jobs"): _json_response(_job_document(), status=202),
        }
        # Complete _FakeOpener only after its get and / inputs are visible in test unsafe
        # session cookie never enters request header.
    )
    with pytest.raises(ControlApiProtocolError):
        # Keep raises, control api protocol error and pytest active only for the bounded
        # test unsafe session cookie never enters request header operation.
        _client(opener).submit_job(
            SubmitJobRequest(1, JobType.RUN_BACKTEST, b'{"schema":"fixture/v1"}', "key")
        )
    assert len(opener.requests) == 1


def test_redirects_and_non_loopback_targets_are_rejected() -> None:
    # Execute the test redirects and non loopback targets are rejected workflow in
    # explicit, reviewable steps.
    redirected = _FakeOpener(
        {
            ("GET", "/api/v1/health"): _Response(
                302,
                b"",
                # Pass content type explicitly so _Response receives a reviewable
                # text/plain and location input in test redirects and non loopback targets
                # are rejected.
                content_type="text/plain",
                headers=(("Location", "http://example.invalid/steal"),),
            )
        }
    )
    # Acquire raises, control api protocol error and pytest at an explicit test redirects
    # and non loopback targets are rejected context boundary so cleanup remains scoped.
    with pytest.raises(ControlApiProtocolError):
        _client(redirected).health()

    for unsafe in ("0.0.0.0", "192.0.2.1", "example.invalid", "127.0.0.1/path"):
        # Process invalid inside the bounded test redirects and non loopback targets are
        # rejected loop.
        with pytest.raises(ValueError, match="loopback"):
            LocalControlApiClient(unsafe, 8080)


def test_default_opener_disables_environment_proxies_and_does_not_mutate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test default opener disables environment proxies and does not mutate
    # environment workflow in explicit, reviewable steps.
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    before = dict(os.environ)
    client = LocalControlApiClient("127.0.0.1", 8080)
    opener = client._opener
    proxy_handlers = [item for item in opener.handlers if isinstance(item, ProxyHandler)]

    # Verify proxy_handlers == [] before this scenario is accepted.
    assert proxy_handlers == []
    assert any(type(item).__name__ == "_NoRedirects" for item in opener.handlers)
    assert dict(os.environ) == before
