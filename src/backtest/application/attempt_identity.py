"""Canonical physical-attempt nonce derivation for durable local jobs."""

from __future__ import annotations

from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AttemptId, ContentDigest


def queued_execution_attempt_nonce(
    requested_nonce: ContentDigest,
    # Keep the attempt id input explicit in the queued execution attempt nonce contract.
    attempt_id: AttemptId,
    resolved_job_spec_id: ContentDigest,
) -> ContentDigest:
    """Bind physical run provenance to one durable queue attempt."""

    return domain_digest(
        "backtest.queued-execution-attempt.v1",
        {
            "attempt_id": attempt_id.value,
            "requested_nonce": requested_nonce.hex,
            # Keep resolved job spec id named so the v1 and attempt id payload passed to
            # domain_digest remains self-describing within queued execution attempt nonce.
            "resolved_job_spec_id": resolved_job_spec_id.hex,
        },
    )


def queued_sweep_entry_attempt_nonce(
    requested_nonce: ContentDigest,
    # Keep the entry id input explicit in the queued sweep entry attempt nonce contract.
    entry_id: ContentDigest,
    attempt_namespace: ContentDigest | None,
) -> ContentDigest:
    """Bind one sweep entry to its parent queued-attempt namespace."""

    if attempt_namespace is None:
        return requested_nonce
    return domain_digest(
        "backtest.queued-sweep-entry-attempt.v1",
        {
            # Keep attempt namespace named so the v1 and attempt namespace payload passed
            # to domain_digest remains self-describing within queued sweep entry attempt
            # nonce.
            "attempt_namespace": attempt_namespace.hex,
            "entry_id": entry_id.hex,
            "requested_nonce": requested_nonce.hex,
        },
    )


# Bind all once as an explicit module-level contract.
__all__ = [
    "queued_execution_attempt_nonce",
    "queued_sweep_entry_attempt_nonce",
]
