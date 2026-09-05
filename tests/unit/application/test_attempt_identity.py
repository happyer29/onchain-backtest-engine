# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from backtest.application.attempt_identity import (
    queued_execution_attempt_nonce,
    queued_sweep_entry_attempt_nonce,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AttemptId, ContentDigest


def test_queued_execution_nonce_preserves_the_versioned_identity_formula() -> None:
    # Execute the test queued execution nonce preserves the versioned identity formula
    # workflow in explicit, reviewable steps.
    requested = ContentDigest("1" * 64)
    attempt_id = AttemptId("attempt-1")
    spec_id = ContentDigest("2" * 64)

    actual = queued_execution_attempt_nonce(requested, attempt_id, spec_id)

    assert actual == domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and
        # attempt id input in test queued execution nonce preserves the versioned identity
        # formula.
        "backtest.queued-execution-attempt.v1",
        {
            "attempt_id": attempt_id.value,
            "requested_nonce": requested.hex,
            "resolved_job_spec_id": spec_id.hex,
            # Close the v1 and attempt id payload only after all test queued execution nonce
            # preserves the versioned identity formula fields are present.
        },
    )


def test_sweep_entry_nonce_is_stable_with_and_without_attempt_namespace() -> None:
    # Execute the test sweep entry nonce is stable with and without attempt namespace
    # workflow in explicit, reviewable steps.
    requested = ContentDigest("3" * 64)
    entry_id = ContentDigest("4" * 64)
    namespace = ContentDigest("5" * 64)

    assert queued_sweep_entry_attempt_nonce(requested, entry_id, None) == requested
    assert queued_sweep_entry_attempt_nonce(
        # Pass requested explicitly so queued_sweep_entry_attempt_nonce receives a
        # reviewable requested and entry id input in test sweep entry nonce is stable with
        # and without attempt namespace.
        requested,
        entry_id,
        namespace,
    ) == domain_digest(
        "backtest.queued-sweep-entry-attempt.v1",
        # Open the v1 and attempt namespace payload explicitly for domain_digest within
        # test sweep entry nonce is stable with and without attempt namespace.
        {
            "attempt_namespace": namespace.hex,
            "entry_id": entry_id.hex,
            "requested_nonce": requested.hex,
        },
        # Complete domain_digest only after its v1 and attempt namespace inputs are visible in
        # test sweep entry nonce is stable with and without attempt namespace.
    )
