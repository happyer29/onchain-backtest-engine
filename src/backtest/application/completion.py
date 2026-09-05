"""Durable attempt-receipt contracts used at the job completion boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest


# Keep the completion receipt error contract and validation rules together.
class CompletionReceiptError(RuntimeError):
    """Base failure while publishing or verifying an attempt receipt."""


class CompletionReceiptNotFoundError(CompletionReceiptError):
    """A terminal success cannot be recovered without its durable receipt."""


class CompletionReceiptConflictError(CompletionReceiptError):
    """One attempt ID was bound to different immutable receipt bytes."""


class CompletionVerificationError(CompletionReceiptError):
    """A receipt does not match the attempt or verified output artifacts."""


class UnverifiedJobCompletionError(CompletionReceiptError):
    """The generic queue transition API cannot attach a successful result."""


@dataclass(frozen=True, slots=True, order=True)
class CompletionOutput:
    artifact_id: ArtifactId
    manifest_digest: ContentDigest


# Keep the attempt completion receipt contract and validation rules together.
@dataclass(frozen=True, slots=True)
class AttemptCompletionReceipt:
    version: int
    attempt_id: AttemptId
    resolved_spec_id: ContentDigest
    # Declare result artifact id explicitly in the attempt completion receipt contract.
    result_artifact_id: ArtifactId
    outputs: tuple[CompletionOutput, ...]

    def __post_init__(self) -> None:
        # Execute the attempt completion receipt post init workflow in explicit,
        # reviewable steps.
        if self.version != 1:
            raise ValueError("unsupported completion receipt version")
        if not self.outputs:
            raise ValueError("completion receipt requires at least one output")
        if tuple(sorted(self.outputs, key=lambda item: item.artifact_id.hex)) != self.outputs:
            # Fail the attempt completion receipt post init path with ValueError for
            # completion outputs must be sorted by artifact id when outputs, sorted and
            # hex is true; do not continue ambiguously.
            raise ValueError("completion outputs must be sorted by artifact ID")
        output_ids = tuple(item.artifact_id.hex for item in self.outputs)
        if len(set(output_ids)) != len(output_ids):
            raise ValueError("completion receipt contains duplicate output artifact IDs")
        if self.result_artifact_id.hex not in output_ids:
            # Fail the attempt completion receipt post init path with ValueError for
            # result artifact must be included in completion outputs when hex, output ids
            # and result artifact id is true; do not continue ambiguously.
            raise ValueError("result artifact must be included in completion outputs")


def completion_receipt_bytes(receipt: AttemptCompletionReceipt) -> bytes:
    """Return the sole canonical serialization used by filesystem and SQLite."""

    return json.dumps(
        {
            "attempt_id": receipt.attempt_id.value,
            "outputs": [
                {
                    # Keep artifact id named so the utf-8 payload passed to encode remains
                    # self-describing within completion receipt bytes.
                    "artifact_id": output.artifact_id.hex,
                    "manifest_digest": output.manifest_digest.hex,
                }
                for output in receipt.outputs
            ],
            # Keep resolved spec id named so the utf-8 payload passed to encode remains
            # self-describing within completion receipt bytes.
            "resolved_spec_id": receipt.resolved_spec_id.hex,
            "result_artifact_id": receipt.result_artifact_id.hex,
            "version": receipt.version,
        },
        ensure_ascii=False,
        # Pass allow nan explicitly so encode receives a reviewable utf-8 input in
        # completion receipt bytes.
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def completion_receipt_digest(receipt: AttemptCompletionReceipt) -> ContentDigest:
    # Return the completed completion receipt digest result without a hidden fallback.
    return ContentDigest(hashlib.sha256(completion_receipt_bytes(receipt)).hexdigest())


__all__ = [
    "AttemptCompletionReceipt",
    "CompletionOutput",
    "CompletionReceiptConflictError",
    # Keep the completion receipt error component named inside the all contract.
    "CompletionReceiptError",
    "CompletionReceiptNotFoundError",
    "CompletionVerificationError",
    "UnverifiedJobCompletionError",
    "completion_receipt_bytes",
    # Keep the completion receipt digest component named inside the all contract.
    "completion_receipt_digest",
]
