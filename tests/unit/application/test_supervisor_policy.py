# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest

from backtest.application.supervisor import (
    AttemptFailure,
    AttemptFailureCode,
    # Include attempt failure kind so the supervisor dependency remains explicit.
    AttemptFailureKind,
    HostResourceBudget,
    RetryPolicy,
)


def test_retry_policy_is_bounded_and_uses_capped_exponential_backoff() -> None:
    # Execute the test retry policy is bounded and uses capped exponential backoff
    # workflow in explicit, reviewable steps.
    policy = RetryPolicy(
        max_attempts=4,
        retryable_kinds=frozenset({AttemptFailureKind.TRANSIENT}),
        base_backoff_ns=10,
        max_backoff_ns=25,
        # Complete RetryPolicy only after its transient and frozenset inputs are visible in
        # test retry policy is bounded and uses capped exponential backoff.
    )
    retryable = AttemptFailure(
        AttemptFailureKind.TRANSIENT,
        AttemptFailureCode.CHILD_EXITED,
    )

    # Verify the retry not before ns, policy and retryable relationship before this
    # scenario is accepted.
    assert policy.retry_not_before_ns(attempt_number=1, failure=retryable, now_ns=100) == 110
    assert policy.retry_not_before_ns(attempt_number=2, failure=retryable, now_ns=100) == 120
    assert policy.retry_not_before_ns(attempt_number=3, failure=retryable, now_ns=100) == 125
    assert policy.retry_not_before_ns(attempt_number=4, failure=retryable, now_ns=100) is None


def test_retry_policy_rejects_non_retryable_failure_family() -> None:
    # Execute the test retry policy rejects non retryable failure family workflow in
    # explicit, reviewable steps.
    policy = RetryPolicy(
        max_attempts=2,
        retryable_kinds=frozenset({AttemptFailureKind.TRANSIENT}),
        base_backoff_ns=1,
        max_backoff_ns=1,
        # Complete RetryPolicy only after its transient and frozenset inputs are visible in
        # test retry policy rejects non retryable failure family.
    )

    assert (
        policy.retry_not_before_ns(
            attempt_number=1,
            failure=AttemptFailure(
                # Pass attempt failure kind explicitly so AttemptFailure receives a
                # reviewable user error and child exited input in test retry policy
                # rejects non retryable failure family.
                AttemptFailureKind.USER_ERROR,
                AttemptFailureCode.CHILD_EXITED,
            ),
            now_ns=100,
        )
        # Verify the retry not before ns, policy and attempt failure relationship before
        # this scenario is accepted.
        is None
    )


def test_single_host_budget_never_allows_multiple_builders() -> None:
    # Execute the test single host budget never allows multiple builders workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="at most one builder"):
        # Keep raises, value error and pytest active only for the bounded test single host
        # budget never allows multiple builders operation.
        HostResourceBudget(
            private_memory_bytes=1,
            physical_cores=1,
            io_units=1,
            max_children=2,
            # Pass max builders explicitly into HostResourceBudget within test single host
            # budget never allows multiple builders.
            max_builders=2,
            max_runs=0,
        )
