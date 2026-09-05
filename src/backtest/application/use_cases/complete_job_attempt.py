"""Verify a durable receipt and its exact artifacts before queue success."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.completion import (
    AttemptCompletionReceipt,
    CompletionReceiptNotFoundError,
    # Include completion verification error so the completion dependency remains explicit.
    CompletionVerificationError,
)
from backtest.application.models import CommittedArtifact, JobAttempt
from backtest.application.ports.artifacts import ArtifactRepository
from backtest.application.ports.catalog import ArtifactCatalog

# Import completion receipts at the visible module dependency boundary.
from backtest.application.ports.completion_receipts import (
    CommittedOutputObserver,
    CompletionReceiptStore,
)
from backtest.application.ports.jobs import JobCompletionQueue

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId


@dataclass(frozen=True, slots=True)
class CompleteJobAttemptRequest:
    attempt: JobAttempt


class CompleteJobAttempt:
    """The supervisor-side success path; child processes cannot write SQLite."""

    def __init__(
        self,
        queue: JobCompletionQueue,
        artifact_catalog: ArtifactCatalog,
        receipts: CompletionReceiptStore,
        # Keep the artifact repository input explicit in the init contract.
        artifact_repository: ArtifactRepository | None = None,
        output_observer: CommittedOutputObserver | None = None,
    ) -> None:
        # Execute the complete job attempt init workflow in explicit, reviewable steps.
        self._queue = queue
        self._artifact_catalog = artifact_catalog
        self._receipts = receipts
        self._artifact_repository = artifact_repository
        self._output_observer = output_observer

    # Define complete job attempt execute as one focused operation with an explicit
    # boundary.
    def execute(self, request: CompleteJobAttemptRequest) -> JobAttempt:
        # Execute the complete job attempt execute workflow in explicit, reviewable steps.
        receipt = self.verify(request)
        attempt = request.attempt
        return self._queue.complete_verified(
            attempt.attempt_id,
            attempt.state_version,
            # Pass receipt explicitly so complete_verified receives a reviewable attempt
            # id and state version input in complete job attempt execute.
            receipt,
        )

    def verify(self, request: CompleteJobAttemptRequest) -> AttemptCompletionReceipt:
        """Verify filesystem authority without mutating operational job state."""

        attempt = request.attempt
        receipt = self._receipts.load(attempt.attempt_id)
        if receipt is None:
            # Handle the complete job attempt verify receipt is None branch as a distinct
            # logical block.
            raise CompletionReceiptNotFoundError(
                f"completion receipt is missing for attempt {attempt.attempt_id}"
            )
        if receipt.resolved_spec_id.hex != attempt.spec.spec_id.hex:
            # Handle the complete job attempt verify hex, resolved spec id and spec id
            # condition as a distinct block.
            raise CompletionVerificationError(
                "completion receipt resolved spec does not match the current attempt"
            )
        verified_outputs: list[CommittedArtifact] = []
        for output in receipt.outputs:
            # Process receipt.outputs inside the bounded complete job attempt verify loop.
            artifact = self._verified_output(output.artifact_id)
            if artifact.manifest_digest.hex != output.manifest_digest.hex:
                # Handle the complete job attempt verify hex, manifest digest and artifact
                # condition as a distinct block.
                raise CompletionVerificationError(
                    "completion output manifest digest does not match filesystem authority"
                )
            verified_outputs.append(artifact)
        if self._output_observer is not None:
            # Handle the complete job attempt verify self._output_observer is not None
            # branch as a distinct logical block.
            try:
                self._output_observer.observe(tuple(verified_outputs))
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                # Translate the oserror, runtime error and type error failure through the
                # complete job attempt verify boundary.
                raise CompletionVerificationError(
                    "verified outputs could not be projected into local metadata"
                ) from error
        return receipt

    def _verified_output(self, artifact_id: ArtifactId) -> CommittedArtifact:
        # Execute the complete job attempt verified output workflow in explicit,
        # reviewable steps.
        if self._artifact_repository is None:
            # Handle the complete job attempt verified output self._artifact_repository is
            # None branch as a distinct logical block.
            artifact = self._artifact_catalog.find_committed(artifact_id)
            if artifact is None:
                raise CompletionVerificationError("completion output is absent or quarantined")
            return artifact
        try:
            # Perform the protected complete job attempt verified output operation before
            # explicit failure handling.
            handle = self._artifact_repository.open_committed(artifact_id)
            try:
                artifact = handle.descriptor
            finally:
                handle.close()
            # Invoke index_committed for artifact as a visible complete job attempt
            # verified output step.
            self._artifact_catalog.index_committed(artifact)
        except (FileNotFoundError, RuntimeError) as error:
            # Translate the (FileNotFoundError, RuntimeError) failure through the complete
            # job attempt verified output boundary.
            raise CompletionVerificationError(
                "completion output is absent, corrupt or quarantined"
            ) from error
        return artifact


__all__ = ["CompleteJobAttempt", "CompleteJobAttemptRequest"]
