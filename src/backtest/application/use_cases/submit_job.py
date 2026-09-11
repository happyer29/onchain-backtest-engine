"""Resolve and durably submit a versioned local job command."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from backtest.application.canonical_json import (
    canonicalize_job_payload,
    # Include resolved job spec hex so the canonical json dependency remains explicit.
    resolved_job_spec_hex,
)
from backtest.application.errors import InvalidIdempotencyKeyError, InvalidJobPayloadError
from backtest.application.job_commands import (
    ResolvedJobCommand,
    # Include resolved job command error so the job commands dependency remains explicit.
    ResolvedJobCommandError,
    prepare_dataset_job_draft_from_bytes,
    resolve_job_command,
)
from backtest.application.models import JobRecord, JobType, ResolvedJobSpec

# Import job resolution at the visible module dependency boundary.
from backtest.application.ports.job_resolution import PrepareDatasetJobResolver
from backtest.application.ports.jobs import JobQueue
from backtest.application.use_cases.research import ResearchUseCases
from backtest.domain.identifiers import ArtifactId, ContentDigest


# Keep the submit job request contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SubmitJobRequest:
    spec_version: int
    job_type: JobType
    payload_json: bytes
    # Declare idempotency key explicitly in the submit job request contract.
    idempotency_key: str
    input_artifact_ids: tuple[ArtifactId, ...] = ()


class SubmitJob:
    """Canonicalize a typed transport payload before crossing the queue port."""

    def __init__(
        self,
        queue: JobQueue,
        prepare_resolver: PrepareDatasetJobResolver | None = None,
        # Research needs exact-input preflight even when submitted through a generic transport.
        research: ResearchUseCases | None = None,
    ) -> None:
        # Execute the submit job init workflow in explicit, reviewable steps.
        self._queue = queue
        self._prepare_resolver = prepare_resolver
        self._research = research

    def execute(self, request: SubmitJobRequest) -> JobRecord:
        # Execute the submit job execute workflow in explicit, reviewable steps.
        _validate_request(request)
        try:
            # Perform the protected submit job execute operation before explicit failure
            # handling.
            canonical_payload = canonicalize_job_payload(request.payload_json)
            resolved = self._resolve_command(request.job_type, canonical_payload)
        except (ResolvedJobCommandError, TypeError, ValueError):
            raise InvalidJobPayloadError from None

        requested_inputs = tuple(sorted(request.input_artifact_ids, key=lambda item: item.hex))
        # Evaluate the complete submit job execute requested inputs condition before
        # guarded effects.
        if len(set(requested_inputs)) != len(requested_inputs):
            raise InvalidJobPayloadError
        if requested_inputs and requested_inputs != resolved.input_artifact_ids:
            raise InvalidJobPayloadError
        canonical_payload = resolved.canonical_payload
        # Assemble input ids once so the submit job execute workflow shares one value.
        input_ids = resolved.input_artifact_ids
        payload_digest = ContentDigest(sha256(canonical_payload).hexdigest())
        spec_id = ContentDigest(
            resolved_job_spec_hex(
                spec_version=request.spec_version,
                # Pass job type explicitly so resolved_job_spec_hex receives a reviewable
                # spec version and value input in submit job execute.
                job_type=request.job_type.value,
                payload_digest_hex=payload_digest.hex,
                input_artifact_hexes=(artifact_id.hex for artifact_id in input_ids),
            )
        )
        # Assemble spec once so the submit job execute workflow shares one value.
        spec = ResolvedJobSpec(
            spec_version=request.spec_version,
            spec_id=spec_id,
            job_type=request.job_type,
            canonical_payload=canonical_payload,
            # Pass payload digest explicitly so ResolvedJobSpec receives a reviewable spec
            # version and job type input in submit job execute.
            payload_digest=payload_digest,
            input_artifact_ids=input_ids,
        )
        return self._queue.submit(spec, request.idempotency_key)

    def _resolve_command(self, job_type: JobType, payload: bytes) -> ResolvedJobCommand:
        # Generic transports cannot bypass research's exact-input resolution boundary.
        if job_type in {JobType.PREPARE_RESEARCH, JobType.ANALYZE_WALLETS}:
            if self._research is None:
                raise ResolvedJobCommandError("research resolver is not configured")
            self._research.validate_command(payload, prepare=job_type is JobType.PREPARE_RESEARCH)
        # Execute the submit job resolve command workflow in explicit, reviewable steps.
        if job_type is not JobType.PREPARE_DATASET:
            return resolve_job_command(job_type, payload)
        resolver = self._prepare_resolver
        if resolver is None:
            # Handle the submit job resolve command resolver is None branch as a distinct
            # logical block.
            raise ResolvedJobCommandError(
                "prepare-dataset draft has no configured controller resolver"
            )
        draft = prepare_dataset_job_draft_from_bytes(payload)
        return resolve_job_command(job_type, resolver.resolve(draft).canonical_bytes())


# Define validate request as one focused operation with an explicit boundary.
def _validate_request(request: SubmitJobRequest) -> None:
    # Execute the validate request workflow in explicit, reviewable steps.
    if isinstance(request.spec_version, bool) or not isinstance(request.spec_version, int):
        raise InvalidJobPayloadError
    if request.spec_version != 1:
        raise InvalidJobPayloadError
    key = request.idempotency_key
    # Evaluate the complete validate request key, isinstance and strip condition before
    # guarded effects.
    if (
        not isinstance(key, str)
        or not key
        or key != key.strip()
        or len(key) > 512
        # Keep any visible while evaluating the key, isinstance and strip guard.
        or any(ord(character) < 32 for character in key)
    ):
        raise InvalidIdempotencyKeyError


__all__ = ["SubmitJob", "SubmitJobRequest"]
