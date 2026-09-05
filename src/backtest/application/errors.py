"""Stable typed errors at the application boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from backtest.application.models import AttemptState, BudgetReport, JobType
from backtest.domain.fidelity import FidelityGap
from backtest.domain.identifiers import ArtifactId, CapabilityId, JobId, SourceId


# Keep the error code contract and validation rules together.
class ErrorCode(StrEnum):
    SOURCE_INSPECTION_FAILED = "SOURCE_INSPECTION_FAILED"
    PROFILE_INVALID = "PROFILE_INVALID"
    REQUEST_IDENTITY_MISMATCH = "REQUEST_IDENTITY_MISMATCH"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    INCOMPLETE_BLOCK_RANGE = "INCOMPLETE_BLOCK_RANGE"
    TRANSACTION_CLOCK_MISMATCH = "TRANSACTION_CLOCK_MISMATCH"
    BUNDLED_BUY_CONTRACT_MISMATCH = "BUNDLED_BUY_CONTRACT_MISMATCH"
    CURVE_TRANSITION_MISMATCH = "CURVE_TRANSITION_MISMATCH"
    LIFECYCLE_CONTRACT_MISMATCH = "LIFECYCLE_CONTRACT_MISMATCH"
    SOURCE_INSPECTION_ARTIFACT_INVALID = "SOURCE_INSPECTION_ARTIFACT_INVALID"
    SOURCE_EVIDENCE_MISMATCH = "SOURCE_EVIDENCE_MISMATCH"
    SNAPSHOT_VALIDATION_FAILED = "SNAPSHOT_VALIDATION_FAILED"
    # Declare capability not found explicitly in the error code contract.
    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    CAPABILITY_AMBIGUOUS = "CAPABILITY_AMBIGUOUS"
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    REQUIRED_COLUMN_MISSING = "REQUIRED_COLUMN_MISSING"
    FIDELITY_MISMATCH = "FIDELITY_MISMATCH"
    # Declare budget exceeded explicitly in the error code contract.
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INVALID_JOB_PAYLOAD = "INVALID_JOB_PAYLOAD"
    INVALID_IDEMPOTENCY_KEY = "INVALID_IDEMPOTENCY_KEY"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    # Declare job state conflict explicitly in the error code contract.
    JOB_STATE_CONFLICT = "JOB_STATE_CONFLICT"
    LOCAL_STATE_UNAVAILABLE = "LOCAL_STATE_UNAVAILABLE"
    WORKFLOW_NOT_IMPLEMENTED = "WORKFLOW_NOT_IMPLEMENTED"
    REPREPARE_REQUIRED = "REPREPARE_REQUIRED"


_SOURCE_EVIDENCE_ERROR_MESSAGES: Final[dict[ErrorCode, str]] = {
    ErrorCode.PROFILE_INVALID: (
        "The installed source profile is not valid for bounded evidence inspection."
    ),
    ErrorCode.REQUEST_IDENTITY_MISMATCH: (
        "The bounded evidence request does not match the installed source contract."
    ),
    ErrorCode.SOURCE_READ_FAILED: (
        "Could not read bounded source evidence; adapter details were suppressed."
    ),
    ErrorCode.NORMALIZATION_FAILED: (
        "Bounded source rows do not match the installed normalization contract."
    ),
    ErrorCode.INCOMPLETE_BLOCK_RANGE: (
        "The bounded source range is incomplete or contains an invalid skipped-block record."
    ),
    ErrorCode.TRANSACTION_CLOCK_MISMATCH: (
        "The bounded source streams do not share the required global transaction clock."
    ),
    ErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH: (
        "The bounded source data does not prove the required creation-transaction ordering."
    ),
    ErrorCode.CURVE_TRANSITION_MISMATCH: (
        "The bounded source data does not form a complete valid curve-transition stream."
    ),
    ErrorCode.LIFECYCLE_CONTRACT_MISMATCH: (
        "The bounded source data does not form a complete valid lifecycle stream."
    ),
}


class ApplicationError(Exception):
    """Base error whose public message is safe for CLI/API transport."""

    code: ErrorCode

    def __init__(self, code: ErrorCode, message: str) -> None:
        # Execute the application error init workflow in explicit, reviewable steps.
        self.code = code
        self.safe_message = message
        super().__init__(message)


# Keep the source inspection failed error contract and validation rules together.
class SourceInspectionFailedError(ApplicationError):
    source_id: SourceId

    def __init__(self, source_id: SourceId) -> None:
        # Execute the source inspection failed error init workflow in explicit, reviewable
        # steps.
        self.source_id = source_id
        super().__init__(
            ErrorCode.SOURCE_INSPECTION_FAILED,
            f"Could not inspect source {source_id}; adapter details were suppressed.",
        )


class SourceEvidenceValidationError(ApplicationError):
    """A bounded source cut failed one safe, versioned evidence check."""

    def __init__(self, code: ErrorCode) -> None:
        if not isinstance(code, ErrorCode) or code not in _SOURCE_EVIDENCE_ERROR_MESSAGES:
            raise TypeError("code must be a source-evidence ErrorCode")
        super().__init__(code, _SOURCE_EVIDENCE_ERROR_MESSAGES[code])


# Keep the source inspection artifact invalid error contract and validation rules
# together.
class SourceInspectionArtifactInvalidError(ApplicationError):
    artifact_id: ArtifactId

    def __init__(self, artifact_id: ArtifactId) -> None:
        # Execute the source inspection artifact invalid error init workflow in explicit,
        # reviewable steps.
        self.artifact_id = artifact_id
        super().__init__(
            ErrorCode.SOURCE_INSPECTION_ARTIFACT_INVALID,
            "The requested source inspection is not a valid committed v5 artifact.",
        )


# Keep the source evidence mismatch error contract and validation rules together.
class SourceEvidenceMismatchError(ApplicationError):
    capability_id: CapabilityId
    missing_proofs: tuple[str, ...]

    def __init__(self, capability_id: CapabilityId, missing_proofs: tuple[str, ...]) -> None:
        # Execute the source evidence mismatch error init workflow in explicit, reviewable
        # steps.
        if not missing_proofs or tuple(sorted(set(missing_proofs))) != missing_proofs:
            raise ValueError("missing source proofs must be non-empty, sorted and unique")
        if any(
            not item or item != item.strip() or not item.replace("_", "").isalnum()
            for item in missing_proofs
            # Complete any only after its value and strip inputs are visible in source
            # evidence mismatch error init.
        ):
            raise ValueError("missing source proofs must be stable tokens")
        self.capability_id = capability_id
        self.missing_proofs = missing_proofs
        super().__init__(
            # Pass error code explicitly so __init__ receives a reviewable capability and
            # value input in source evidence mismatch error init.
            ErrorCode.SOURCE_EVIDENCE_MISMATCH,
            f"Capability {capability_id} does not prove the required cross-stream semantics.",
        )


# Keep the snapshot validation error code contract and validation rules together.
class SnapshotValidationErrorCode(StrEnum):
    VALIDATOR_REQUIRED = "VALIDATOR_REQUIRED"
    CLOCK_INVALID = "CLOCK_INVALID"
    EVENT_POSITION_INVALID = "EVENT_POSITION_INVALID"
    EVENT_STREAM_INVALID = "EVENT_STREAM_INVALID"
    # Declare transaction group invalid explicitly in the snapshot validation error code
    # contract.
    TRANSACTION_GROUP_INVALID = "TRANSACTION_GROUP_INVALID"
    PROTOCOL_STATE_INVALID = "PROTOCOL_STATE_INVALID"
    SETTLEMENT_TAIL_INSUFFICIENT = "SETTLEMENT_TAIL_INSUFFICIENT"


class SnapshotValidationError(ApplicationError):
    """A candidate distribution closure cannot become a snapshot root."""

    reason: SnapshotValidationErrorCode

    def __init__(self, reason: SnapshotValidationErrorCode) -> None:
        # Execute the snapshot validation error init workflow in explicit, reviewable
        # steps.
        if not isinstance(reason, SnapshotValidationErrorCode):
            raise TypeError("reason must be a SnapshotValidationErrorCode")
        self.reason = reason
        super().__init__(
            ErrorCode.SNAPSHOT_VALIDATION_FAILED,
            # Pass canonical distributions failed exact explicitly so __init__ receives a
            # reviewable snapshot validation failed and error code input in snapshot
            # validation error init.
            "Canonical distributions failed exact cross-stream snapshot validation.",
        )


# Keep the capability not found error contract and validation rules together.
class CapabilityNotFoundError(ApplicationError):
    capability_id: CapabilityId

    def __init__(self, capability_id: CapabilityId) -> None:
        # Execute the capability not found error init workflow in explicit, reviewable
        # steps.
        self.capability_id = capability_id
        super().__init__(
            ErrorCode.CAPABILITY_NOT_FOUND,
            f"Required capability {capability_id} is not available.",
        )


# Keep the capability ambiguous error contract and validation rules together.
class CapabilityAmbiguousError(ApplicationError):
    capability_id: CapabilityId

    def __init__(self, capability_id: CapabilityId) -> None:
        # Execute the capability ambiguous error init workflow in explicit, reviewable
        # steps.
        self.capability_id = capability_id
        super().__init__(
            ErrorCode.CAPABILITY_AMBIGUOUS,
            f"Capability {capability_id} resolves to multiple compatible versions.",
        )


# Keep the protocol version mismatch error contract and validation rules together.
class ProtocolVersionMismatchError(ApplicationError):
    capability_id: CapabilityId
    accepted_versions: tuple[str, ...]

    def __init__(
        self,
        # Keep the capability id input explicit in the init contract.
        capability_id: CapabilityId,
        accepted_versions: tuple[str, ...],
    ) -> None:
        # Execute the protocol version mismatch error init workflow in explicit,
        # reviewable steps.
        self.capability_id = capability_id
        self.accepted_versions = accepted_versions
        super().__init__(
            ErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"Capability {capability_id} has no accepted protocol version.",
            # Complete __init__ only after its capability and value inputs are visible in
            # protocol version mismatch error init.
        )


# Keep the required column missing error contract and validation rules together.
class RequiredColumnMissingError(ApplicationError):
    capability_id: CapabilityId
    missing_columns: tuple[str, ...]

    def __init__(
        self,
        # Keep the capability id input explicit in the init contract.
        capability_id: CapabilityId,
        missing_columns: tuple[str, ...],
    ) -> None:
        # Execute the required column missing error init workflow in explicit, reviewable
        # steps.
        self.capability_id = capability_id
        self.missing_columns = missing_columns
        super().__init__(
            ErrorCode.REQUIRED_COLUMN_MISSING,
            f"Capability {capability_id} is missing required logical columns.",
            # Complete __init__ only after its capability and value inputs are visible in
            # required column missing error init.
        )


# Keep the fidelity mismatch error contract and validation rules together.
class FidelityMismatchError(ApplicationError):
    capability_id: CapabilityId
    gaps: tuple[FidelityGap, ...]

    def __init__(self, capability_id: CapabilityId, gaps: tuple[FidelityGap, ...]) -> None:
        # Execute the fidelity mismatch error init workflow in explicit, reviewable steps.
        self.capability_id = capability_id
        self.gaps = gaps
        super().__init__(
            ErrorCode.FIDELITY_MISMATCH,
            f"Capability {capability_id} does not satisfy required fidelity.",
            # Complete __init__ only after its capability and value inputs are visible in
            # fidelity mismatch error init.
        )


# Keep the budget exceeded error contract and validation rules together.
class BudgetExceededError(ApplicationError):
    report: BudgetReport

    def __init__(self, report: BudgetReport) -> None:
        # Execute the budget exceeded error init workflow in explicit, reviewable steps.
        self.report = report
        super().__init__(
            ErrorCode.BUDGET_EXCEEDED,
            "Dataset plan exceeds one or more configured hard limits.",
        )


# Keep the invalid job payload error contract and validation rules together.
class InvalidJobPayloadError(ApplicationError):
    def __init__(self) -> None:
        # Execute the invalid job payload error init workflow in explicit, reviewable
        # steps.
        super().__init__(
            ErrorCode.INVALID_JOB_PAYLOAD,
            "Job payload is not valid canonical command data.",
        )


# Keep the invalid idempotency key error contract and validation rules together.
class InvalidIdempotencyKeyError(ApplicationError):
    def __init__(self) -> None:
        # Execute the invalid idempotency key error init workflow in explicit, reviewable
        # steps.
        super().__init__(
            ErrorCode.INVALID_IDEMPOTENCY_KEY,
            "Idempotency key must be non-empty, trimmed and at most 512 characters.",
        )


# Keep the idempotency conflict error contract and validation rules together.
class IdempotencyConflictError(ApplicationError):
    job_type: JobType
    idempotency_key: str

    def __init__(self, job_type: JobType, idempotency_key: str) -> None:
        # Execute the idempotency conflict error init workflow in explicit, reviewable
        # steps.
        self.job_type = job_type
        self.idempotency_key = idempotency_key
        super().__init__(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            f"Idempotency key conflicts with an existing {job_type.value} command.",
            # Complete __init__ only after its idempotency key conflicts with an existing and
            # value inputs are visible in idempotency conflict error init.
        )


# Keep the job not found error contract and validation rules together.
class JobNotFoundError(ApplicationError):
    job_id: JobId

    def __init__(self, job_id: JobId) -> None:
        # Execute the job not found error init workflow in explicit, reviewable steps.
        self.job_id = job_id
        super().__init__(ErrorCode.JOB_NOT_FOUND, f"Job does not exist: {job_id}.")


# Keep the job state conflict error contract and validation rules together.
class JobStateConflictError(ApplicationError):
    job_id: JobId
    current_state: AttemptState
    operation: str

    def __init__(self, job_id: JobId, current_state: AttemptState, operation: str) -> None:
        # Execute the job state conflict error init workflow in explicit, reviewable
        # steps.
        self.job_id = job_id
        self.current_state = current_state
        self.operation = operation
        super().__init__(
            ErrorCode.JOB_STATE_CONFLICT,
            # Pass cannot operation job job id explicitly so __init__ receives a
            # reviewable cannot and job input in job state conflict error init.
            f"Cannot {operation} job {job_id} in state {current_state.value}.",
        )


class LocalStateUnavailableError(ApplicationError):
    """The authoritative local operational store cannot safely accept work."""

    def __init__(self) -> None:
        # Execute the local state unavailable error init workflow in explicit, reviewable
        # steps.
        super().__init__(
            ErrorCode.LOCAL_STATE_UNAVAILABLE,
            "The local operational state database is temporarily unavailable.",
        )


# Keep the workflow not implemented error contract and validation rules together.
class WorkflowNotImplementedError(ApplicationError):
    workflow: str
    required_architecture_sections: tuple[int, ...]

    def __init__(self, workflow: str, required_architecture_sections: tuple[int, ...]) -> None:
        # Execute the workflow not implemented error init workflow in explicit, reviewable
        # steps.
        self.workflow = workflow
        self.required_architecture_sections = required_architecture_sections
        sections = ", ".join(str(section) for section in required_architecture_sections)
        super().__init__(
            ErrorCode.WORKFLOW_NOT_IMPLEMENTED,
            # Pass workflow is not implemented explicitly so __init__ receives a
            # reviewable is not implemented; it requires architecture sections and value
            # input in workflow not implemented error init.
            f"{workflow} is not implemented; it requires architecture sections {sections}.",
        )


class ReprepareRequiredError(ApplicationError):
    """A legacy artifact cannot be assigned a network identity retroactively."""

    artifact_contract: str

    def __init__(self, artifact_contract: str) -> None:
        # Execute the reprepare required error init workflow in explicit, reviewable
        # steps.
        if (
            not isinstance(artifact_contract, str)
            or not artifact_contract
            or artifact_contract != artifact_contract.strip()
        ):
            # Fail the reprepare required error init path with ValueError for artifact
            # contract must be a non-empty trimmed string when artifact contract,
            # isinstance and strip is true; do not continue ambiguously.
            raise ValueError("artifact_contract must be a non-empty trimmed string")
        self.artifact_contract = artifact_contract
        super().__init__(
            ErrorCode.REPREPARE_REQUIRED,
            "The artifact predates the network-aware position contract and must be "
            # Pass prepared again from a explicitly so __init__ receives a reviewable
            # reprepare required and error code input in reprepare required error init.
            "prepared again from a proven source.",
        )
