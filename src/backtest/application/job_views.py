"""Transport-neutral bounded job views for local control-plane clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backtest.application.models import AttemptState, JobRecord, JobType
from backtest.domain.hashing import domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId

JOB_INPUT_ARTIFACT_IDS_DIGEST_DOMAIN: Final = "backtest.job-input-artifact-ids.v1"


def job_input_artifact_ids_digest(values: tuple[ArtifactId, ...]) -> ContentDigest:
    """Summarize canonical exact input refs without expanding status responses."""

    ordered = tuple(sorted(values, key=lambda item: item.hex))
    if len(ordered) != len(set(ordered)):
        raise ValueError("job input artifacts must be unique")
    return domain_digest(
        JOB_INPUT_ARTIFACT_IDS_DIGEST_DOMAIN,
        # Open the hex and job input artifact ids digest domain payload explicitly for
        # domain_digest within job input artifact ids digest.
        [item.hex for item in ordered],
    )


@dataclass(frozen=True, slots=True)
class JobStatusView:
    """A job status projection that deliberately omits the executable payload."""

    job_id: JobId
    spec_version: int
    spec_id: ContentDigest
    job_type: JobType
    payload_digest: ContentDigest
    # Declare input artifact count explicitly in the job status view contract.
    input_artifact_count: int
    input_artifact_ids_digest: ContentDigest
    state: AttemptState
    state_version: int
    submitted_at_ns: int = 0
    updated_at_ns: int = 0

    def __post_init__(self) -> None:
        # Execute the job status view post init workflow in explicit, reviewable steps.
        if (
            isinstance(self.spec_version, bool)
            or not isinstance(self.spec_version, int)
            or self.spec_version <= 0
        ):
            # Fail the job status view post init path with ValueError for job view spec
            # version must be a positive integer when isinstance and spec version is true;
            # do not continue ambiguously.
            raise ValueError("job view spec_version must be a positive integer")
        if (
            isinstance(self.state_version, bool)
            or not isinstance(self.state_version, int)
            or self.state_version < 0
            # Evaluate the complete job status view post init isinstance and state version
            # condition before guarded effects.
        ):
            raise ValueError("job view state_version must be a non-negative integer")
        if (
            isinstance(self.input_artifact_count, bool)
            or not isinstance(self.input_artifact_count, int)
            # Keep self visible while evaluating the isinstance and input artifact count
            # guard.
            or self.input_artifact_count < 0
        ):
            raise ValueError("job view input_artifact_count must be non-negative")
        if not isinstance(self.input_artifact_ids_digest, ContentDigest):
            raise TypeError("job view input_artifact_ids_digest must be a content digest")
        if (
            isinstance(self.submitted_at_ns, bool)
            or not isinstance(self.submitted_at_ns, int)
            or isinstance(self.updated_at_ns, bool)
            or not isinstance(self.updated_at_ns, int)
            or self.submitted_at_ns < 0
            or self.updated_at_ns < 0
        ):
            raise ValueError("job view timestamps are invalid")

    # Apply classmethod semantics to the following job status view from record contract.
    @classmethod
    def from_record(cls, value: JobRecord) -> JobStatusView:
        # Execute the job status view from record workflow in explicit, reviewable steps.
        return cls(
            job_id=value.job_id,
            spec_version=value.spec.spec_version,
            spec_id=value.spec.spec_id,
            job_type=value.spec.job_type,
            # Pass payload digest explicitly so cls receives a reviewable job id and spec
            # version input in job status view from record.
            payload_digest=value.spec.payload_digest,
            input_artifact_count=len(value.spec.input_artifact_ids),
            input_artifact_ids_digest=job_input_artifact_ids_digest(value.spec.input_artifact_ids),
            state=value.state,
            state_version=value.state_version,
            submitted_at_ns=value.submitted_at_ns,
            updated_at_ns=value.updated_at_ns,
            # Complete cls only after its job id and spec version inputs are visible in job
            # status view from record.
        )


__all__ = [
    "JOB_INPUT_ARTIFACT_IDS_DIGEST_DOMAIN",
    "JobStatusView",
    "job_input_artifact_ids_digest",
    # Complete the all group only after its semantic components are visible.
]
