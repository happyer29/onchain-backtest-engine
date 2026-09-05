"""Atomic local-filesystem completion receipt store."""

from __future__ import annotations

import json
import os
import stat
import uuid

# Import contextlib at the visible module dependency boundary.
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from backtest.adapters.artifacts.localfs.layout import DataRootLayout

# Import completion at the visible module dependency boundary.
from backtest.application.completion import (
    AttemptCompletionReceipt,
    CompletionOutput,
    CompletionReceiptConflictError,
    CompletionReceiptError,
    # Include completion receipt bytes so the completion dependency remains explicit.
    completion_receipt_bytes,
)
from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest

_MAX_RECEIPT_BYTES = 64 * 1024


class LocalCompletionReceiptStore:
    """Publish one canonical, immutable and directory-fsynced receipt per attempt."""

    def __init__(self, layout: DataRootLayout) -> None:
        # Execute the local completion receipt store init workflow in explicit, reviewable
        # steps.
        self._layout = layout
        self._directory = layout.job_receipts_directory
        directory_was_missing = not self._directory.exists()
        self._directory.mkdir(parents=True, exist_ok=True)
        _require_directory(self._directory)
        # Guard this path with directory_was_missing before applying effects.
        if directory_was_missing:
            _fsync_directory(self._directory.parent)

    def publish(self, receipt: AttemptCompletionReceipt) -> ContentDigest:
        # Execute the local completion receipt store publish workflow in explicit,
        # reviewable steps.
        payload = _serialize(receipt)
        digest = ContentDigest(sha256(payload).hexdigest())
        destination = self._layout.job_receipt(receipt.attempt_id)
        attempt_tag = sha256(receipt.attempt_id.value.encode("utf-8")).hexdigest()[:24]
        temporary = self._directory / f".receipt-{attempt_tag}.tmp-{uuid.uuid4().hex}"
        # Assemble descriptor once so the local completion receipt store publish workflow
        # shares one value.
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            # Keep the os getattr step visible while building descriptor.
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            # Perform the protected local completion receipt store publish operation
            # before explicit failure handling.
            with os.fdopen(descriptor, "wb") as stream:
                # Keep fdopen, descriptor and wb active only for the bounded local
                # completion receipt store publish operation.
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            # Translate file exists error through the local completion receipt store
            # publish boundary without hiding other errors.
            except FileExistsError:
                # Translate the FileExistsError failure through the local completion
                # receipt store publish boundary.
                existing = self.load(receipt.attempt_id)
                if existing != receipt:
                    # Handle the local completion receipt store publish existing !=
                    # receipt branch as a distinct logical block.
                    raise CompletionReceiptConflictError(
                        "attempt receipt already exists with different bytes"
                    ) from None
            else:
                _fsync_directory(self._directory)
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            # Handle the cleanup path after the protected local completion receipt store
            # publish operation.
            with suppress(FileNotFoundError):
                temporary.unlink()
            _fsync_directory(self._directory)
        return digest

    def load(self, attempt_id: AttemptId) -> AttemptCompletionReceipt | None:
        # Execute the local completion receipt store load workflow in explicit, reviewable
        # steps.
        path = self._layout.job_receipt(attempt_id)
        try:
            # Perform the protected local completion receipt store load operation before
            # explicit failure handling.
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            # Return explicit absence from the local completion receipt store load path.
            return None
        except OSError as error:
            raise CompletionReceiptError("completion receipt is unavailable") from error
        try:
            # Perform the protected local completion receipt store load operation before
            # explicit failure handling.
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise CompletionReceiptError("completion receipt is not a private regular file")
            if metadata.st_size > _MAX_RECEIPT_BYTES:
                raise CompletionReceiptError("completion receipt exceeds its size limit")
            # Acquire fdopen, descriptor and rb at an explicit local completion receipt
            # store load context boundary so cleanup remains scoped.
            with os.fdopen(descriptor, "rb") as stream:
                # Keep fdopen, descriptor and rb active only for the bounded local
                # completion receipt store load operation.
                descriptor = -1
                payload = stream.read(_MAX_RECEIPT_BYTES + 1)
        finally:
            # Handle the cleanup path after the protected local completion receipt store
            # load operation.
            if descriptor >= 0:
                os.close(descriptor)
        return _deserialize(payload)


def _serialize(receipt: AttemptCompletionReceipt) -> bytes:
    return completion_receipt_bytes(receipt)


# Define deserialize as one focused operation with an explicit boundary.
def _deserialize(payload: bytes) -> AttemptCompletionReceipt:
    # Execute the deserialize workflow in explicit, reviewable steps.
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise CompletionReceiptError("completion receipt exceeds its size limit")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Fail the deserialize path with CompletionReceiptError for completion receipt is
        # not valid json; do not continue ambiguously.
        raise CompletionReceiptError("completion receipt is not valid JSON") from None
    if not isinstance(document, dict) or payload != _canonical_document(document):
        raise CompletionReceiptError("completion receipt is not canonical JSON")
    expected_keys = {
        "attempt_id",
        # Keep the outputs component named inside the expected keys contract.
        "outputs",
        "resolved_spec_id",
        "result_artifact_id",
        "version",
    }
    # Evaluate the complete deserialize expected keys, document and isinstance condition
    # before guarded effects.
    if set(document) != expected_keys or not isinstance(document["outputs"], list):
        raise CompletionReceiptError("completion receipt schema is invalid")
    try:
        # Perform the protected deserialize operation before explicit failure handling.
        outputs = tuple(
            CompletionOutput(
                artifact_id=ArtifactId(_required_string(item, "artifact_id")),
                manifest_digest=ContentDigest(_required_string(item, "manifest_digest")),
            )
            # Keep the cast and object cast step visible while building outputs.
            for item in cast(list[object], document["outputs"])
        )
        version = document["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("version is not an integer")
        # Return the completed deserialize result without a hidden fallback.
        return AttemptCompletionReceipt(
            version=version,
            attempt_id=AttemptId(_required_top_string(document, "attempt_id")),
            resolved_spec_id=ContentDigest(_required_top_string(document, "resolved_spec_id")),
            result_artifact_id=ArtifactId(_required_top_string(document, "result_artifact_id")),
            # Pass outputs explicitly so AttemptCompletionReceipt receives a reviewable
            # attempt id and resolved spec id input in deserialize.
            outputs=outputs,
        )
    except (KeyError, TypeError, ValueError):
        raise CompletionReceiptError("completion receipt fields are invalid") from None


def _canonical_document(document: dict[str, Any]) -> bytes:
    # Execute the canonical document workflow in explicit, reviewable steps.
    try:
        # Perform the protected canonical document operation before explicit failure
        # handling.
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            # Pass sort keys explicitly so encode receives a reviewable utf-8 input in
            # canonical document.
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise CompletionReceiptError("completion receipt JSON values are invalid") from None


def _required_string(item: object, field: str) -> str:
    # Execute the required string workflow in explicit, reviewable steps.
    if not isinstance(item, dict) or set(item) != {"artifact_id", "manifest_digest"}:
        raise TypeError("completion output schema is invalid")
    value = item[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} is not a string")
    # Return the completed required string result without a hidden fallback.
    return value


def _required_top_string(document: dict[str, Any], field: str) -> str:
    # Execute the required top string workflow in explicit, reviewable steps.
    value = document[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} is not a string")
    return value


def _require_directory(path: Path) -> None:
    # Execute the require directory workflow in explicit, reviewable steps.
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CompletionReceiptError("receipt directory is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        # Fail the require directory path with CompletionReceiptError for receipt
        # directory must be a real directory when s islnk, st mode and stat is true; do
        # not continue ambiguously.
        raise CompletionReceiptError("receipt directory must be a real directory")


def _fsync_directory(path: Path) -> None:
    # Execute the fsync directory workflow in explicit, reviewable steps.
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        # Invoke fsync for descriptor as a visible fsync directory step.
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["LocalCompletionReceiptStore"]
