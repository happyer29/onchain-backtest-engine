# Declare this module's dependencies and contracts before execution.
import pytest

from backtest.application.errors import ErrorCode, WorkflowNotImplementedError
from backtest.application.run_specs import ResolvedComponent
from backtest.application.use_cases.compile_delivery_schedule import (
    CompileDeliverySchedule,
    # Include compile delivery schedule request so the compile delivery schedule
    # dependency remains explicit.
    CompileDeliveryScheduleRequest,
)
from backtest.application.use_cases.compile_replay import CompileReplay, CompileReplayRequest
from backtest.domain.identifiers import (
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    ReplayPackId,
    SnapshotId,
)


def _digest(character: str = "a") -> ContentDigest:
    # Return the completed digest result without a hidden fallback.
    return ContentDigest(character * 64)


def _delivery_components() -> tuple[ResolvedComponent, ...]:
    # Execute the delivery components workflow in explicit, reviewable steps.
    return tuple(
        ResolvedComponent.create(
            role=role,
            bundle_id=BundleId(str(index) * 64),
            config={"version": 1},
            # Complete create only after its version and bundle id inputs are visible in
            # delivery components.
        )
        for index, role in enumerate(("clock", "engine", "latency", "scheduler"), start=1)
    )


@pytest.mark.parametrize(
    ("use_case", "command", "workflow"),
    # Open the use case and command payload explicitly for parametrize within test
    # deferred workflow fails explicitly without fake success.
    [
        (
            CompileReplay(),
            CompileReplayRequest(SnapshotId("b" * 64), "compiler-v1"),
            "compile-replay",
            # Complete parametrize only after its use case and command inputs are visible in
            # test deferred workflow fails explicitly without fake success.
        ),
        (
            CompileDeliverySchedule(),
            CompileDeliveryScheduleRequest(
                replay_pack_id=ReplayPackId("c" * 64),
                # Define test deferred workflow fails explicitly without fake success as
                # one focused operation with an explicit boundary.
                replay_semantics_id=_digest("d"),
                replay_layout_schema_id=_digest("e"),
                components=_delivery_components(),
                rng_algorithm="hmac-sha256-keyed-v1",
                root_seed=42,
                # Pass compiler version explicitly so CompileDeliveryScheduleRequest
                # receives a reviewable c and d input in test deferred workflow fails
                # explicitly without fake success.
                compiler_version="numpy-delivery-mmap-v1",
            ),
            "compile-delivery-schedule",
        ),
    ],
    # Complete parametrize only after its use case and command inputs are visible in test
    # deferred workflow fails explicitly without fake success.
)
def test_deferred_workflow_fails_explicitly_without_fake_success(
    use_case: object,
    command: object,
    workflow: str,
    # Close the test deferred workflow fails explicitly without fake success signature after
    # its explicit inputs.
) -> None:
    # Execute the test deferred workflow fails explicitly without fake success workflow in
    # explicit, reviewable steps.
    with pytest.raises(WorkflowNotImplementedError) as caught:
        use_case.execute(command)  # type: ignore[attr-defined]

    assert caught.value.code is ErrorCode.WORKFLOW_NOT_IMPLEMENTED
    assert caught.value.workflow == workflow
    assert caught.value.required_architecture_sections
