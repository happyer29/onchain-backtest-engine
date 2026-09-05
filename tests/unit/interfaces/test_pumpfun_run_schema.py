# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backtest.application.run_contracts import PUMPFUN_SNIPING_CONTRACT
from backtest.application.run_drafts import PumpfunSnipingRunDraft
from backtest.domain.execution import ExecutionMode

# Import schemas at the visible module dependency boundary.
from backtest.interfaces.api.schemas import (
    PumpfunSnipingRunDraftCommand,
    RunContractListResponse,
    RunContractResponse,
    RunDraftReresolveRequiredError,
    run_draft_command_from_bytes,
    # Close the schemas import after its required symbols are visible.
)


def test_pumpfun_run_draft_uses_exact_closed_transport_contract() -> None:
    # Execute the test pumpfun run draft uses exact closed transport contract workflow in
    # explicit, reviewable steps.
    document = _document()

    command = PumpfunSnipingRunDraftCommand.model_validate(document)
    draft = command.to_domain()

    assert isinstance(draft, PumpfunSnipingRunDraft)
    assert draft.initial_sol_balance_lamports == 100_000_000_000
    # Verify the gross buy budget lamports and draft relationship before this scenario is
    # accepted.
    assert draft.gross_buy_budget_lamports == 100_000_000
    assert draft.root_seed == 42
    assert draft.delivery_schedule_id is not None
    assert draft.delivery_schedule_id.hex == "4" * 64
    # Nested account profile fields survive the strict transport conversion.
    assert draft.wallet_account_profile.initial_uva_state.value == "fresh"
    assert len(draft.wallet_account_profile.account_costs) == 3
    assert "cooldown_seconds" not in type(command).model_fields
    # Verify the buy delay transactions, model fields and type relationship before this
    # scenario is accepted.
    assert "buy_delay_transactions" not in type(command).model_fields
    assert draft.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
    assert "execution_mode" in type(command).model_fields


def test_pumpfun_run_draft_requires_supported_mode_and_rejects_legacy_v2() -> None:
    # V3 never guesses the mode omitted by the caller.
    missing_mode = {key: value for key, value in _document().items() if key != "execution_mode"}
    with pytest.raises(ValidationError):
        PumpfunSnipingRunDraftCommand.model_validate(missing_mode)

    # JSON transport accepts the reviewed virtual value and preserves its enum identity.
    virtual = {**_document(), "execution_mode": "EXOGENOUS_VIRTUAL_SETTLEMENT"}
    command = run_draft_command_from_bytes(json.dumps(virtual).encode("utf-8"))
    assert command.to_domain().execution_mode is ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT

    # Generic execution enum members remain outside the Pump.fun closed subset.
    unsupported = {**_document(), "execution_mode": ExecutionMode.SHADOW_STATE_REPLAY}
    with pytest.raises(ValidationError, match="execution_mode"):
        PumpfunSnipingRunDraftCommand.model_validate(unsupported)

    # V2 is recognized as legacy so callers receive a migration-specific failure.
    legacy = {**_document(), "contract_schema": "pumpfun-sniping-run-draft/v2"}
    with pytest.raises(RunDraftReresolveRequiredError) as captured:
        run_draft_command_from_bytes(json.dumps(legacy).encode("utf-8"))
    assert captured.value.code == "RERESOLVE_REQUIRED"


def test_pumpfun_run_draft_rejects_unsafe_or_noncanonical_atomic_numbers() -> None:
    # Execute the test pumpfun run draft rejects unsafe or noncanonical atomic numbers
    # workflow in explicit, reviewable steps.
    for field_name, value in (
        ("initial_sol_balance_lamports", 10),
        ("initial_sol_balance_lamports", "01"),
        ("gross_buy_budget_lamports", "0"),
        ("root_seed", "4.2"),
        # Traverse initial sol balance lamports, gross buy budget lamports and root seed
        # explicitly so each test pumpfun run draft rejects unsafe or noncanonical atomic
        # numbers iteration remains traceable.
    ):
        # Process initial sol balance lamports, gross buy budget lamports and root seed
        # inside the bounded test pumpfun run draft rejects unsafe or noncanonical atomic
        # numbers loop.
        document = {**_document(), field_name: value}
        with pytest.raises((TypeError, ValueError, ValidationError)):
            PumpfunSnipingRunDraftCommand.model_validate(document).to_domain()


def test_pumpfun_schedule_transport_requires_replay_pack() -> None:
    # Execute the test pumpfun schedule transport requires replay pack workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="requires a ReplayPack"):
        # Keep raises, value error and pytest active only for the bounded test pumpfun
        # schedule transport requires replay pack operation.
        PumpfunSnipingRunDraftCommand.model_validate(
            {**_document(), "replay_pack_id": None}
        ).to_domain()


def test_run_draft_dispatch_rejects_unknown_schema_and_extra_fields() -> None:
    # Execute the test run draft dispatch rejects unknown schema and extra fields workflow
    # in explicit, reviewable steps.
    payload = b'{"contract_schema":"arbitrary/v1"}'
    with pytest.raises(ValueError, match="unknown"):
        run_draft_command_from_bytes(payload)

    with pytest.raises(ValidationError):
        PumpfunSnipingRunDraftCommand.model_validate({**_document(), "raw_sql": "SELECT 1"})


# Define test run contract discovery response exposes fixed semantics separately as one
# focused operation with an explicit boundary.
def test_run_contract_discovery_response_exposes_fixed_semantics_separately() -> None:
    # Execute the test run contract discovery response exposes fixed semantics separately
    # workflow in explicit, reviewable steps.
    response = RunContractListResponse(
        items=(RunContractResponse.from_domain(PUMPFUN_SNIPING_CONTRACT),)
    )
    document = response.model_dump(by_alias=True)

    assert document["items"][0]["schema"] == "pumpfun-sniping-run-draft/v3"
    # Verify the buy delay transactions, fixed semantics and document relationship before
    # this scenario is accepted.
    assert document["items"][0]["fixed_semantics"]["buy_delay_transactions"] == "500"
    assert all(
        field["name"] != "cooldown_seconds" for field in document["items"][0]["editable_fields"]
    )


def _document() -> dict[str, object]:
    # Execute the document workflow in explicit, reviewable steps.
    solana_fee = {
        "profile_id": "solana-buy-v1",
        "formula_version": "solana-legacy-v0-base-priority-v1",
        "transaction_format": "V0",
        "effective_from_unix_s": 0,
        # Keep the effective until unix s component named inside the solana fee contract.
        "effective_until_unix_s": 4_102_444_800,
        "charged_signature_count": 1,
        "lamports_per_signature": "5000",
        "compute_unit_limit": 200_000,
        "micro_lamports_per_compute_unit": "1000",
        # Complete the solana fee group only after its semantic components are visible.
    }
    return {
        "contract_schema": "pumpfun-sniping-run-draft/v3",
        "dataset_revision_id": "1" * 64,
        "snapshot_id": "2" * 64,
        # Include replay pack id in the completed document result.
        "replay_pack_id": "3" * 64,
        "delivery_schedule_id": "4" * 64,
        "initial_sol_balance_lamports": "100000000000",
        "gross_buy_budget_lamports": "100000000",
        "buy_slippage_bps": 500,
        # Include sell slippage bps in the completed document result.
        "sell_slippage_bps": 500,
        "execution_mode": ExecutionMode.EXOGENOUS_REPLAY,
        "sell_delay_transactions": 1,
        "wallet_account_profile": {
            "schema": "pumpfun-solana-wallet-account-profile/v2",
            "profile_id": "fresh-v1",
            "initial_uva_state": "fresh",
            "effective_from_unix_s": 0,
            "effective_until_unix_s": 4_102_444_800,
            "account_costs": [
                {
                    "requirement_schema_id": "pumpfun-user-volume-accumulator-v1",
                    "deposit_lamports": "1844400",
                },
                {
                    "requirement_schema_id": "solana-associated-token-account-legacy-v1",
                    "deposit_lamports": "2039280",
                },
                {
                    "requirement_schema_id": (
                        "solana-associated-token-account-token-2022-immutable-owner-v1"
                    ),
                    "deposit_lamports": "2074080",
                },
            ],
        },
        "pump_fee_profile": {
            "profile_id": "pump-static-95-30-v1",
            # Include program version in the completed document result.
            "program_version": "pump-program-static-fee-v1",
            "buy_formula_version": "pump-buy-exact-gross-sol-v1",
            "sell_formula_version": "pump-sell-exact-token-in-v1",
            "effective_from_unix_s": 0,
            "effective_until_unix_s": 4_102_444_800,
            # Include protocol fee bps in the completed document result.
            "protocol_fee_bps": 95,
            "creator_fee_bps": 30,
        },
        "buy_solana_fee_profile": solana_fee,
        "sell_solana_fee_profile": {**solana_fee, "profile_id": "solana-sell-v1"},
        # Include root seed in the completed document result.
        "root_seed": "42",
    }
