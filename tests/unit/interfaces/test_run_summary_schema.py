# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import (
    MAX_RUN_WARNING_LENGTH,
    MAX_RUN_WARNINGS,
    RunBackend,
    RunComparisonProjection,
    # Include run physical settings so the run results dependency remains explicit.
    RunPhysicalSettings,
)
from backtest.application.run_specs import ReplayContract
from backtest.application.use_cases.query_runs import RunSummaryView
from backtest.domain.identifiers import (
    # Include artifact id so the identifiers dependency remains explicit.
    ArtifactId,
    ContentDigest,
    ExecutionAttemptId,
    LogicalRunId,
)

# Import schemas at the visible module dependency boundary.
from backtest.interfaces.api.schemas import RunListResponse, RunSummaryResponse


def _digest(character: str) -> ContentDigest:
    return ContentDigest(character * 64)


def _view() -> RunSummaryView:
    # Execute the view workflow in explicit, reviewable steps.
    comparison = RunComparisonProjection(
        canonical_result_hash=_digest("1"),
        audit_hash=_digest("2"),
        ledger_hash=_digest("3"),
        fill_hash=_digest("4"),
        # Pass historical group count explicitly so RunComparisonProjection receives a
        # reviewable 1 and 2 input in view.
        historical_group_count=7,
        historical_event_count=9,
        delivered_event_count=8,
        accepted_order_count=3,
        rejected_order_count=1,
        # Pass filled order count explicitly so RunComparisonProjection receives a
        # reviewable 1 and 2 input in view.
        filled_order_count=2,
        failed_order_count=0,
        ledger_transaction_count=2,
        fill_count=2,
        final_balances_count=1,
        # Keep the b _digest step visible while building comparison.
        final_balances_digest=_digest("b"),
    )
    return RunSummaryView(
        run_artifact_id=ArtifactId("5" * 64),
        logical_run_id=LogicalRunId("9" * 64),
        # Include execution attempt id in the completed view result.
        execution_attempt_id=ExecutionAttemptId("a" * 64),
        comparison=comparison,
        physical_settings=RunPhysicalSettings(
            RunBackend.REFERENCE_PYTHON,
            65_536,
            # Keep run physical settings, reference python and run backend visible while
            # completing RunPhysicalSettings within view.
            2,
            8_192,
            1,
        ),
        canonicality=ReplayContract.CANONICAL_EXACT,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        # Pass warnings explicitly so RunSummaryView receives a reviewable 5 and 9 input
        # in view.
        warnings=("<img src=x onerror=globalThis.pwned=true>",),
    )


def test_run_summary_response_round_trips_every_verified_projection_field() -> None:
    # Execute the test run summary response round trips every verified projection field
    # workflow in explicit, reviewable steps.
    view = _view()

    response = RunSummaryResponse.from_domain(view)

    assert response.to_domain() == view
    assert response.run_artifact_id == view.run_artifact_id.hex
    assert response.comparison.final_balances_count == 1
    # Verify the final balances digest, comparison and b relationship before this scenario
    # is accepted.
    assert response.comparison.final_balances_digest == "b" * 64
    assert response.physical_settings.reader_readahead == 2
    assert response.canonicality is ReplayContract.CANONICAL_EXACT
    assert response.started_at == view.started_at
    assert response.completed_at == view.completed_at
    assert response.warnings == ("<img src=x onerror=globalThis.pwned=true>",)


@pytest.mark.parametrize("field", ("canonical_result_hash", "audit_hash"))
# Define test run summary response rejects substituted alias as one focused operation with
# an explicit boundary.
def test_run_summary_response_rejects_substituted_alias(field: str) -> None:
    # Execute the test run summary response rejects substituted alias workflow in
    # explicit, reviewable steps.
    document = RunSummaryResponse.from_domain(_view()).model_dump(mode="json", by_alias=True)
    document[field] = "f" * 64
    response = RunSummaryResponse.model_validate_json(json.dumps(document))

    with pytest.raises(ValueError, match="aliases differ"):
        response.to_domain()


# Define test run summary response rejects malformed or unbounded transport fields as one
# focused operation with an explicit boundary.
def test_run_summary_response_rejects_malformed_or_unbounded_transport_fields() -> None:
    # Execute the test run summary response rejects malformed or unbounded transport
    # fields workflow in explicit, reviewable steps.
    document = RunSummaryResponse.from_domain(_view()).model_dump(mode="json", by_alias=True)
    document["comparison"]["fill_count"] = -1
    with pytest.raises(ValidationError):
        RunSummaryResponse.model_validate_json(json.dumps(document))

    document = RunSummaryResponse.from_domain(_view()).model_dump(mode="json", by_alias=True)
    # Assemble document['warnings'] once so the test run summary response rejects
    # malformed or unbounded transport fields workflow shares one value.
    document["warnings"] = ["warning"] * (MAX_RUN_WARNINGS + 1)
    with pytest.raises(ValidationError):
        RunSummaryResponse.model_validate_json(json.dumps(document))


def test_largest_legal_run_list_fits_the_control_client_response_bound() -> None:
    # Execute the test largest legal run list fits the control client response bound
    # workflow in explicit, reviewable steps.
    warnings = tuple(
        f"warning-{index:02d}-" + "x" * (MAX_RUN_WARNING_LENGTH - 11)
        for index in range(MAX_RUN_WARNINGS)
    )
    response = RunSummaryResponse.from_domain(replace(_view(), warnings=warnings))
    # Assemble payload once so the test largest legal run list fits the control client
    # response bound workflow shares one value.
    payload = RunListResponse(items=(response,) * 50).model_dump_json().encode()

    assert len(payload) < 2 * 1024 * 1024
    assert b"input_artifact_ids" not in payload

    document = RunSummaryResponse.from_domain(_view()).model_dump(mode="json", by_alias=True)
    document["opaque_metric"] = 1
    # Acquire raises, validation error and pytest at an explicit test largest legal run
    # list fits the control client response bound context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValidationError):
        RunSummaryResponse.model_validate_json(json.dumps(document))

    document = RunSummaryResponse.from_domain(_view()).model_dump(mode="json", by_alias=True)
    document["warnings"] = ["not printable\n"]
    with pytest.raises(ValidationError):
        # Invoke model_validate_json for dumps and document as a visible test largest
        # legal run list fits the control client response bound step.
        RunSummaryResponse.model_validate_json(json.dumps(document))
