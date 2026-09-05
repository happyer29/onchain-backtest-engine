"""Crash-aware artifact publication on one local filesystem.

The adapter deliberately keeps operational paths and lock mechanics out of the
application layer.  A directory becomes visible only after its content identity
has been verified and a durable ``COMMITTED`` marker has been published.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil

# Import stat at the visible module dependency boundary.
import stat
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import suppress

# Import pathlib at the visible module dependency boundary.
from pathlib import Path, PurePosixPath
from threading import Lock
from types import TracebackType
from typing import IO, Any, Final, cast

# Keep physical paths in one manifest-derived localfs contract.
from backtest.adapters.artifacts.localfs.placement import (
    ArtifactPlacementError,
    artifact_leaf_names_artifact_id,
    artifact_path_depth,
    artifact_relative_path,
    artifact_subdirectory,
    is_canonical_digest_segment,
)
from backtest.application.models import (
    ArtifactDraft,
    # Include artifact kind so the models dependency remains explicit.
    ArtifactKind,
    CommittedArtifact,
)
from backtest.application.ports.artifacts import ArtifactHandle, ArtifactWriter
from backtest.domain.identifiers import ArtifactId, ContentDigest

# Import file locks at the visible module dependency boundary.
from backtest.runtime.file_locks import FileLock, LockMode

_DESCRIPTOR_NAME: Final = "artifact.json"
_MANIFEST_NAME: Final = "manifest.json"
_IDENTITY_MANIFEST_NAME: Final = "manifest.identity.json"
_MARKER_NAME: Final = "COMMITTED"
# Bind reserved names once as an explicit module-level contract.
_RESERVED_NAMES: Final = frozenset(
    {_DESCRIPTOR_NAME, _IDENTITY_MANIFEST_NAME, _MANIFEST_NAME, _MARKER_NAME}
)
_TEMPORARY_MARKER_PREFIX: Final = ".COMMITTED.tmp-"
_IDENTITY_DOMAIN_V1: Final = b"local-backtest/artifact/v1\x00"
# Bind identity domain v2 once as an explicit module-level contract.
_IDENTITY_DOMAIN_V2: Final = b"local-backtest/artifact/v2\x00"
_IDENTITY_DOMAIN_V3: Final = b"local-backtest/artifact/v3\x00"
_DEFAULT_VERIFICATION_CACHE_BYTES: Final = 8 * 1024 * 1024
_VERIFICATION_LOCK_STRIPES: Final = 16


class ArtifactRepositoryError(RuntimeError):
    """Base class for public local-artifact failures."""


class InvalidArtifactPathError(ArtifactRepositoryError, ValueError):
    """Raised when a payload path could escape or shadow repository metadata."""


class ArtifactNotCommittedError(ArtifactRepositoryError, FileNotFoundError):
    """Raised when an artifact has no fully verified commit point."""


class ArtifactIntegrityError(ArtifactRepositoryError):
    """Raised when committed bytes do not match their descriptor."""


class ArtifactWriterStateError(ArtifactRepositoryError):
    """Raised for an invalid stage/commit/abort lifecycle transition."""


class StagingQuotaExceededError(ArtifactRepositoryError):
    """A staged artifact exceeded its host-owned hard byte quota."""


class _StagingQuota:
    def __init__(self, limit_bytes: int | None) -> None:
        # Execute the staging quota init workflow in explicit, reviewable steps.
        self._limit_bytes = limit_bytes
        self._reserved_bytes = 0

    def reserve(self, byte_count: int) -> None:
        # Execute the staging quota reserve workflow in explicit, reviewable steps.
        if byte_count < 0:
            raise ValueError("quota reservation must be non-negative")
        next_total = self._reserved_bytes + byte_count
        if self._limit_bytes is not None and next_total > self._limit_bytes:
            raise StagingQuotaExceededError("artifact staging quota would be exceeded")
        # Assemble self reserved bytes once so the staging quota reserve workflow shares
        # one value.
        self._reserved_bytes = next_total

    def release(self, byte_count: int) -> None:
        # Execute the staging quota release workflow in explicit, reviewable steps.
        if byte_count < 0 or byte_count > self._reserved_bytes:
            raise ValueError("quota release is outside the current reservation")
        self._reserved_bytes -= byte_count

    def verify_physical_bytes(self, byte_count: int) -> None:
        # Execute the staging quota verify physical bytes workflow in explicit, reviewable
        # steps.
        if self._limit_bytes is not None and byte_count > self._limit_bytes:
            raise StagingQuotaExceededError("artifact staging quota was exceeded")


class _QuotaBinaryStream:
    """Small file-like proxy that rejects a write before it crosses quota."""

    def __init__(self, stream: IO[bytes], quota: _StagingQuota) -> None:
        # Execute the quota binary stream init workflow in explicit, reviewable steps.
        self._stream = stream
        self._quota = quota

    @property
    def closed(self) -> bool:
        return self._stream.closed

    # Define quota binary stream write as one focused operation with an explicit boundary.
    def write(self, value: bytes | bytearray | memoryview) -> int:
        # Execute the quota binary stream write workflow in explicit, reviewable steps.
        byte_count = len(value)
        self._quota.reserve(byte_count)
        try:
            written = self._stream.write(value)
        except BaseException:
            # A failed buffered write may still have reached the file partly.
            # Keep the whole reservation so a caller cannot catch the error
            # and continue with an under-counted hard quota.
            raise
        if written != byte_count:
            self._quota.release(byte_count - written)
        return written

    def writelines(self, lines: Any) -> None:
        # Execute the quota binary stream writelines workflow in explicit, reviewable
        # steps.
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._stream.flush()

    def close(self) -> None:
        # Invoke close as a visible step within the quota binary stream close workflow.
        self._stream.close()

    def fileno(self) -> int:
        return self._stream.fileno()

    def tell(self) -> int:
        return self._stream.tell()

    # Define quota binary stream seek as one focused operation with an explicit boundary.
    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._stream.seek(offset, whence)

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        # Return the completed quota binary stream readable result without a hidden
        # fallback.
        return False

    def seekable(self) -> bool:
        return self._stream.seekable()

    def __enter__(self) -> _QuotaBinaryStream:
        return self

    # Define quota binary stream exit as one focused operation with an explicit boundary.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        # Close the exit signature after its explicit inputs.
    ) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _sha256_bytes(value: bytes) -> str:
    # Return the completed sha256 bytes result without a hidden fallback.
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    # Execute the sha256 file workflow in explicit, reviewable steps.
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    # Translate oserror through the sha256 file boundary without hiding other errors.
    except OSError as error:
        raise ArtifactIntegrityError("artifact member could not be opened safely") from error
    try:
        # Perform the protected sha256 file operation before explicit failure handling.
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactIntegrityError("artifact member must be a regular file")
        if file_stat.st_nlink != 1:
            raise ArtifactIntegrityError("hard-linked artifact members are forbidden")
        # Acquire fdopen, descriptor and rb at an explicit sha256 file context boundary so
        # cleanup remains scoped.
        with os.fdopen(descriptor, "rb", buffering=0) as stream:
            # Keep fdopen, descriptor and rb active only for the bounded sha256 file
            # operation.
            descriptor = -1
            while block := stream.read(1024 * 1024):
                # Keep the (block := stream.read(1024 * 1024)) loop body bounded within
                # sha256 file.
                digest.update(block)
                size += len(block)
    finally:
        # Handle the cleanup path after the protected sha256 file operation.
        if descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest(), size


def _read_regular_file(path: Path, *, label: str) -> bytes:
    # Execute the read regular file workflow in explicit, reviewable steps.
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    # Translate oserror through the read regular file boundary without hiding other
    # errors.
    except OSError as error:
        raise ArtifactIntegrityError(f"{label} could not be opened safely") from error
    try:
        # Perform the protected read regular file operation before explicit failure
        # handling.
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactIntegrityError(f"{label} must be a regular file")
        if file_stat.st_nlink != 1:
            raise ArtifactIntegrityError(f"{label} must not be hard linked")
        # Acquire fdopen, descriptor and rb at an explicit read regular file context
        # boundary so cleanup remains scoped.
        with os.fdopen(descriptor, "rb") as stream:
            # Keep fdopen, descriptor and rb active only for the bounded read regular file
            # operation.
            descriptor = -1
            return stream.read()
    finally:
        # Handle the cleanup path after the protected read regular file operation.
        if descriptor >= 0:
            os.close(descriptor)


def _canonical_json(value: object) -> bytes:
    # Execute the canonical json workflow in explicit, reviewable steps.
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        # Pass separators explicitly so encode receives a reviewable utf-8 input in
        # canonical json.
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_relative_path(relative_name: str, *, allow_reserved: bool = False) -> PurePosixPath:
    # Execute the safe relative path workflow in explicit, reviewable steps.
    if (
        not relative_name
        or "\\" in relative_name
        or any(ord(character) < 32 for character in relative_name)
    ):
        # Fail the safe relative path path with InvalidArtifactPathError for artifact path
        # must be a non-empty posix path when relative name, character and ord is true; do
        # not continue ambiguously.
        raise InvalidArtifactPathError("artifact path must be a non-empty POSIX path")
    relative = PurePosixPath(relative_name)
    if (
        not relative.parts
        or relative.is_absolute()
        # Keep any visible while evaluating the parts, is absolute and relative guard.
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise InvalidArtifactPathError("artifact path must stay below the artifact root")
    root_name = relative.parts[0]
    if not allow_reserved and (
        # Keep root name visible while evaluating the allow reserved, root name and
        # reserved names guard.
        root_name in _RESERVED_NAMES or root_name.startswith(_TEMPORARY_MARKER_PREFIX)
    ):
        raise InvalidArtifactPathError(f"{relative_name!r} is repository metadata")
    return relative


def _fsync_directory(path: Path) -> None:
    # Execute the fsync directory workflow in explicit, reviewable steps.
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        # Keep the os getattr step visible while building descriptor.
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        # Invoke close for descriptor as a visible fsync directory step.
        os.close(descriptor)


def _require_real_directory(path: Path, *, label: str) -> None:
    # Execute the require real directory workflow in explicit, reviewable steps.
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise ArtifactRepositoryError(f"{label} is unavailable") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        # Fail the require real directory path with ArtifactRepositoryError for must be a
        # real directory and label when s islnk, st mode and stat is true; do not continue
        # ambiguously.
        raise ArtifactRepositoryError(f"{label} must be a real directory")


def _ensure_real_directory(path: Path, *, label: str, mode: int = 0o700) -> None:
    # Execute the ensure real directory workflow in explicit, reviewable steps.
    with suppress(FileExistsError):
        path.mkdir(mode=mode)
    _require_real_directory(path, label=label)


def _ensure_directories_beneath(root: Path, parts: tuple[str, ...]) -> Path:
    # Execute the ensure directories beneath workflow in explicit, reviewable steps.
    current = root
    _require_real_directory(current, label="artifact staging root")
    for part in parts:
        # Process parts inside the bounded ensure directories beneath loop.
        current = current / part
        _ensure_real_directory(current, label="artifact payload directory")
    return current


def _ensure_directories_beneath_for_read(root: Path, parts: tuple[str, ...]) -> Path:
    # Execute the ensure directories beneath for read workflow in explicit, reviewable
    # steps.
    current = root
    _require_real_directory(current, label="artifact root")
    for part in parts:
        # Process parts inside the bounded ensure directories beneath for read loop.
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise InvalidArtifactPathError("artifact directory is unavailable") from error
        # Evaluate the complete ensure directories beneath for read s islnk, st mode and
        # stat condition before guarded effects.
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise InvalidArtifactPathError("artifact path crosses a non-directory or symlink")
    return current


def _ensure_artifact_root_chain_for_read(data_root: Path, root: Path) -> None:
    """Revalidate every repository ancestor before following a handle path."""

    try:
        relative = root.relative_to(data_root)
    except ValueError as error:  # pragma: no cover - repository construction invariant
        raise InvalidArtifactPathError("artifact root escaped its data root") from error
    current = data_root
    _require_real_directory(current, label="artifact data root")
    for part in relative.parts:
        _require_exact_child_name(current, part, label="artifact path")
        current /= part
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise InvalidArtifactPathError("artifact path is unavailable") from error
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise InvalidArtifactPathError("artifact path crosses a non-directory or symlink")


def _ensure_repository_parent(root: Path, parts: tuple[str, ...]) -> Path:
    """Create a trusted manifest-derived parent one real segment at a time."""

    current = root
    _require_real_directory(current, label="artifact data root")
    for part in parts:
        child = current / part
        missing = not _exists_no_follow(child)
        _ensure_real_directory(child, label="artifact final parent")
        _require_exact_child_name(current, part, label="artifact final parent")
        if missing:
            _fsync_directory(current)
        current = child
    return current


def _require_exact_child_name(parent: Path, name: str, *, label: str) -> None:
    """Reject case-folding aliases that would violate canonical path spelling."""

    try:
        entries = os.scandir(parent)
    except OSError as error:
        raise ArtifactRepositoryError(f"{label} parent could not be enumerated") from error
    with entries:
        if any(entry.name == name for entry in entries):
            return
    raise ArtifactRepositoryError(f"{label} has non-canonical on-disk spelling")


def _require_same_filesystem(first: Path, second: Path) -> None:
    # Execute the require same filesystem workflow in explicit, reviewable steps.
    if first.stat().st_dev != second.stat().st_dev:
        raise ArtifactRepositoryError("staging and final artifact paths must share a filesystem")


def _exists_no_follow(path: Path) -> bool:
    # Execute the exists no follow workflow in explicit, reviewable steps.
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _quarantine_path(
    repository: LocalArtifactRepository,
    path: Path,
    *,
    prefix: str,
) -> Path:
    """Atomically remove a conflicting tree from the committed namespace."""

    trash_was_missing = not _exists_no_follow(repository.trash_root)
    _ensure_real_directory(repository.trash_root, label="artifact trash root")
    if trash_was_missing:
        _fsync_directory(repository.data_root)
    _require_same_filesystem(path.parent, repository.trash_root)
    quarantine = repository.trash_root / f"{prefix}-{time.time_ns()}-{uuid.uuid4().hex}"
    os.rename(path, quarantine)
    _fsync_directory(path.parent)
    _fsync_directory(repository.trash_root)
    return quarantine


# Define write durable exclusive as one focused operation with an explicit boundary.
def _write_durable_exclusive(path: Path, payload: bytes) -> None:
    # Execute the write durable exclusive workflow in explicit, reviewable steps.
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    # Keep expected failures inside the write durable exclusive error boundary.
    try:
        # Perform the protected write durable exclusive operation before explicit failure
        # handling.
        view = memoryview(payload)
        while view:
            # Keep the view loop body bounded within write durable exclusive.
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive kernel boundary
                raise OSError("short write while publishing artifact metadata")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Define artifact subdirectory as one focused operation with an explicit boundary.
def _artifact_subdirectory(kind: ArtifactKind) -> str:
    """Compatibility alias for local adapters that have not imported placement."""

    return artifact_subdirectory(kind)


def _regular_files(root: Path) -> tuple[Path, ...]:
    # Execute the regular files workflow in explicit, reviewable steps.
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise ArtifactIntegrityError("artifact root is unavailable") from error
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        # Fail the regular files path with ArtifactIntegrityError for artifact root must
        # be a real directory when s islnk, st mode and stat is true; do not continue
        # ambiguously.
        raise ArtifactIntegrityError("artifact root must be a real directory")
    files: list[Path] = []
    for candidate in root.rglob("*"):
        # Process root.rglob('*') inside the bounded regular files loop.
        file_stat = candidate.lstat()
        if stat.S_ISLNK(file_stat.st_mode):
            raise ArtifactIntegrityError("symbolic links are forbidden in artifacts")
        if stat.S_ISREG(file_stat.st_mode):
            # Handle the regular files stat.S_ISREG(file_stat.st_mode) branch as a
            # distinct logical block.
            if file_stat.st_nlink != 1:
                raise ArtifactIntegrityError("hard-linked artifact members are forbidden")
            files.append(candidate)
        # Handle the regular files complement of stat.S_ISREG(file_stat.st_mode)
        # explicitly.
        elif not stat.S_ISDIR(file_stat.st_mode):
            raise ArtifactIntegrityError("only regular files and directories are supported")
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _payload_entries(root: Path) -> list[dict[str, object]]:
    # Execute the payload entries workflow in explicit, reviewable steps.
    entries: list[dict[str, object]] = []
    for path in _regular_files(root):
        # Process _regular_files(root) inside the bounded payload entries loop.
        relative = path.relative_to(root).as_posix()
        if relative in _RESERVED_NAMES:
            continue
        digest, size = _sha256_file(path)
        entries.append({"path": relative, "sha256": digest, "size": size})
    # Return the completed payload entries result without a hidden fallback.
    return entries


_ArtifactFingerprint = tuple[tuple[str, int, int, int, int, int, int, int], ...]
_CachedVerification = tuple[_ArtifactFingerprint, bytes, int]


def _stat_fingerprint(
    relative_name: str, metadata: os.stat_result
) -> tuple[str, int, int, int, int, int, int, int]:
    """Bind a canonical relative name to mutation-relevant filesystem metadata."""

    return (
        relative_name,
        metadata.st_dev,
        metadata.st_ino,
        # Mode and link count expose replacement/link attacks beyond timestamp checks.
        metadata.st_mode,
        metadata.st_nlink,
        # Size plus nanosecond timestamps catch ordinary in-place payload mutation.
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _artifact_file_fingerprint(root: Path) -> _ArtifactFingerprint:
    """Return cheap mutation evidence for one already-verified immutable tree."""

    try:
        # The root itself must remain the same non-symlink directory across cache hits.
        root_stat = root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ArtifactIntegrityError("artifact root must be a real directory")
        values = [_stat_fingerprint(".", root_stat)]

        # Sorted regular-file discovery also detects additions, removals, and symlinks.
        for path in _regular_files(root):
            file_stat = path.lstat()
            relative_name = path.relative_to(root).as_posix()
            values.append(_stat_fingerprint(relative_name, file_stat))
    except OSError as error:
        raise ArtifactIntegrityError("artifact changed while collecting its fingerprint") from error
    return tuple(values)


def _cached_verification_weight(
    fingerprint: _ArtifactFingerprint,
    descriptor_bytes: bytes,
) -> int:
    """Conservatively bound retained path, tuple, integer, and descriptor storage."""

    # The fixed allowance intentionally overestimates tuple and integer object overhead.
    fingerprint_bytes = sum(256 + len(item[0].encode("utf-8")) for item in fingerprint)
    return len(descriptor_bytes) + fingerprint_bytes


def _verify_cached_control_files(
    root: Path,
    descriptor: Mapping[str, object],
    descriptor_bytes: bytes,
) -> None:
    """Re-authenticate small authority files even when payload hashes are cached."""

    try:
        # These bounded files authenticate cached evidence; payload files stay unopened.
        current_descriptor = _read_regular_file(
            root / _DESCRIPTOR_NAME, label="artifact descriptor"
        )
        marker_bytes = _read_regular_file(root / _MARKER_NAME, label="commit marker")
        manifest_bytes = _read_regular_file(root / _MANIFEST_NAME, label="root manifest")
    except FileNotFoundError as error:
        raise ArtifactNotCommittedError(f"artifact directory is incomplete: {root}") from error
    if current_descriptor != descriptor_bytes:
        raise ArtifactIntegrityError("cached artifact descriptor changed")

    # The marker must still authenticate the exact cached canonical descriptor bytes.
    expected_marker = {
        "artifact_id": descriptor.get("artifact_id"),
        "descriptor_sha256": _sha256_bytes(descriptor_bytes),
        "version": descriptor.get("version"),
    }
    if marker_bytes != _canonical_json(expected_marker):
        raise ArtifactIntegrityError("commit marker does not authenticate cached descriptor")
    manifest_sha256 = descriptor.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or _sha256_bytes(manifest_bytes) != manifest_sha256:
        raise ArtifactIntegrityError("cached artifact manifest digest mismatch")

    # Descriptor v3 separates placement identity; authenticate that small sidecar too.
    if descriptor.get("version") == 3:
        identity_digest = descriptor.get("manifest_identity_sha256")
        try:
            identity_bytes = _read_regular_file(
                root / _IDENTITY_MANIFEST_NAME,
                label="manifest identity",
            )
        except FileNotFoundError as error:
            raise ArtifactNotCommittedError(f"artifact directory is incomplete: {root}") from error
        if not isinstance(identity_digest, str) or _sha256_bytes(identity_bytes) != identity_digest:
            raise ArtifactIntegrityError("cached manifest identity digest mismatch")


def _require_cached_descriptor_identity(
    descriptor: Mapping[str, object],
    *,
    expected_id: ArtifactId | None,
    expected_kind: ArtifactKind | None,
) -> None:
    """Re-apply caller-specific identity checks to cached verification evidence."""

    try:
        artifact_id = ArtifactId(cast(str, descriptor["artifact_id"]))
        artifact_kind = ArtifactKind(cast(str, descriptor["kind"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ArtifactIntegrityError("cached artifact descriptor identity is invalid") from error
    if expected_id is not None and artifact_id.hex != expected_id.hex:
        raise ArtifactIntegrityError("artifact id does not match requested id")
    if expected_kind is not None and artifact_kind is not expected_kind:
        raise ArtifactIntegrityError("artifact kind does not match its repository directory")


def _parse_json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    # Execute the parse json object workflow in explicit, reviewable steps.
    def reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        value = json.loads(payload, parse_constant=reject_non_finite)
    except (UnicodeDecodeError, ValueError) as error:
        # Fail the parse json object path with ArtifactIntegrityError for invalid and
        # json; do not continue ambiguously.
        raise ArtifactIntegrityError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise ArtifactIntegrityError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _is_json_projection(identity: object, manifest: object) -> bool:
    """Return whether identity is an exact recursive projection of manifest."""

    if isinstance(identity, dict):
        # Handle the is json projection isinstance(identity, dict) branch as a distinct
        # logical block.
        if not isinstance(manifest, dict) or not set(identity).issubset(manifest):
            return False
        return all(_is_json_projection(value, manifest[key]) for key, value in identity.items())
    if isinstance(identity, list):
        # Handle the is json projection isinstance(identity, list) branch as a distinct
        # logical block.
        if not isinstance(manifest, list) or len(identity) != len(manifest):
            return False
        return all(
            _is_json_projection(left, right) for left, right in zip(identity, manifest, strict=True)
        )
    # Return the completed is json projection result without a hidden fallback.
    return identity == manifest


def _validate_descriptor_files(value: object) -> None:
    # Execute the validate descriptor files workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise ArtifactIntegrityError("descriptor files must be a list")
    paths: list[str] = []
    for entry in value:
        # Process value inside the bounded validate descriptor files loop.
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise ArtifactIntegrityError("descriptor file entry schema is invalid")
        path_value = entry["path"]
        digest_value = entry["sha256"]
        size_value = entry["size"]
        # Guard this path with not isinstance(path_value, str) before applying effects.
        if not isinstance(path_value, str):
            raise ArtifactIntegrityError("descriptor file path must be a string")
        try:
            # Perform the protected validate descriptor files operation before explicit
            # failure handling.
            canonical_path = _safe_relative_path(path_value)
            digest = ContentDigest(cast(str, digest_value))
        except (InvalidArtifactPathError, TypeError, ValueError) as error:
            raise ArtifactIntegrityError("descriptor file entry is invalid") from error
        if canonical_path.as_posix() != path_value:
            # Fail the validate descriptor files path with ArtifactIntegrityError for
            # descriptor file path is not canonical when path value, as posix and
            # canonical path is true; do not continue ambiguously.
            raise ArtifactIntegrityError("descriptor file path is not canonical")
        if digest.value != digest.hex:
            raise ArtifactIntegrityError("descriptor file digest is not canonical")
        if isinstance(size_value, bool) or not isinstance(size_value, int) or size_value < 0:
            raise ArtifactIntegrityError("descriptor file size must be a non-negative integer")
        # Invoke append for path value as a visible validate descriptor files step.
        paths.append(path_value)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ArtifactIntegrityError("descriptor file paths must be sorted and unique")


class LocalArtifactRepository:
    """Content-addressed repository rooted on one local mount."""

    def __init__(
        self,
        data_root: Path,
        *,
        staging_quota_bytes: int | None = None,
        verification_cache_entries: int = 128,
        verification_cache_bytes: int = _DEFAULT_VERIFICATION_CACHE_BYTES,
    ) -> None:
        # Execute the local artifact repository init workflow in explicit, reviewable
        # steps.
        if staging_quota_bytes is not None and (
            isinstance(staging_quota_bytes, bool) or staging_quota_bytes <= 0
        ):
            raise ValueError("staging_quota_bytes must be positive or None")
        if (
            isinstance(verification_cache_entries, bool)
            or not isinstance(verification_cache_entries, int)
            or verification_cache_entries < 1
        ):
            # A zero entry limit would silently disable the configured reuse contract.
            raise ValueError("verification_cache_entries must be a positive integer")
        if (
            isinstance(verification_cache_bytes, bool)
            or not isinstance(verification_cache_bytes, int)
            or verification_cache_bytes < 1
        ):
            # Byte bounds remain explicit even though entries contain no payload bytes.
            raise ValueError("verification_cache_bytes must be a positive integer")
        self.data_root = data_root.resolve()
        # Assemble self staging quota bytes once so the local artifact repository init
        # workflow shares one value.
        self.staging_quota_bytes = staging_quota_bytes
        self.staging_root = self.data_root / "staging"
        self.trash_root = self.data_root / "trash"
        self.locks_root = self.data_root / "locks"
        self._verification_cache_entries = verification_cache_entries
        self._verification_cache_max_bytes = verification_cache_bytes
        self._verification_cache_current_bytes = 0
        # LRU state stores only fingerprints and canonical descriptor bytes.
        self._verification_cache: OrderedDict[
            str,
            _CachedVerification,
        ] = OrderedDict()
        self._verification_cache_lock = Lock()
        # Stable striped single-flight avoids one cold multi-GB hash blocking every ID.
        self._verification_locks = tuple(Lock() for _ in range(_VERIFICATION_LOCK_STRIPES))
        root_was_missing = not self.data_root.exists()
        # Invoke mkdir as a visible step within the local artifact repository init
        # workflow.
        self.data_root.mkdir(parents=True, exist_ok=True)
        _require_real_directory(self.data_root, label="artifact data root")
        if root_was_missing:
            _fsync_directory(self.data_root.parent)
        _ensure_real_directory(self.staging_root, label="artifact staging root")
        # Invoke _ensure_real_directory for artifact locks root and locks root as a
        # visible local artifact repository init step.
        _ensure_real_directory(self.locks_root, label="artifact locks root")
        _fsync_directory(self.data_root)

    def stage(self, spec: ArtifactDraft) -> ArtifactWriter:
        return _LocalArtifactWriter(self, spec)

    def open_committed(self, artifact_id: ArtifactId) -> ArtifactHandle:
        # Execute the local artifact repository open committed workflow in explicit,
        # reviewable steps.
        retention_lock = FileLock(
            self.locks_root / "retention.lock",
            mode=LockMode.SHARED,
        ).acquire()
        publication_lock = FileLock(
            # Pass self explicitly so FileLock receives a reviewable lock and locks root
            # input in local artifact repository open committed.
            self.locks_root / "publication.lock",
            mode=LockMode.SHARED,
        )
        try:
            # Perform the protected local artifact repository open committed operation
            # before explicit failure handling.
            publication_lock.acquire()
            artifact_kind, artifact_root = self._find_artifact_root(artifact_id)
            descriptor = self._verify_committed(
                artifact_root,
                expected_id=artifact_id,
                # Pass expected kind explicitly so _verify_committed receives a reviewable
                # artifact root and artifact id input in local artifact repository open
                # committed.
                expected_kind=artifact_kind,
            )
            # A process may have crashed after publishing the marker but before
            # the final directory fsync.  Repeating these fsyncs before handing
            # bytes to a consumer safely adopts that otherwise valid state.
            _fsync_directory(artifact_root)
            _fsync_directory(artifact_root.parent)
            committed = _committed_from_descriptor(descriptor)
            # Retention is the long-lived read lease.  Publication protects the
            # short verification window only; keeping it for an hours-long run
            # would prevent unrelated artifacts from being published.
            publication_lock.release()
            return _LocalArtifactHandle(
                data_root=self.data_root,
                root=artifact_root,
                descriptor=committed,
                retention_lock=retention_lock,
                # Complete _LocalArtifactHandle only after its artifact root and committed
                # inputs are visible in local artifact repository open committed.
            )
        except BaseException:
            # Translate the BaseException failure through the local artifact repository
            # open committed boundary.
            publication_lock.release()
            retention_lock.release()
            raise

    def _find_artifact_root(self, artifact_id: ArtifactId) -> tuple[ArtifactKind, Path]:
        """Find candidate roots by shape; verification remains a separate authority step."""

        matches: list[tuple[ArtifactKind, Path]] = []
        for kind in ArtifactKind:
            for candidate in self._candidate_roots(kind):
                # A final-path orphan without the durable commit point is recovery
                # state, not a competing artifact location.  Presence of the marker is
                # only a candidate filter; _verify_committed authenticates it below.
                if not _exists_no_follow(candidate / _MARKER_NAME):
                    continue
                candidate_id: ArtifactId | None
                if artifact_leaf_names_artifact_id(kind):
                    candidate_id = ArtifactId(candidate.name)
                else:
                    candidate_id = self._candidate_descriptor_id(candidate)
                    if candidate_id is None:
                        continue
                # Identifier wrappers intentionally preserve domain type at call sites
                # (for example ``SnapshotId`` and ``ReplayPackId``).  Physical lookup is
                # keyed by their canonical digest bytes, not by dataclass runtime type.
                if candidate_id.hex == artifact_id.hex:
                    matches.append((kind, candidate))
        if not matches:
            raise ArtifactNotCommittedError(f"artifact {artifact_id} is not committed")
        if len(matches) > 1:
            raise ArtifactIntegrityError("artifact id exists in more than one physical location")
        return matches[0]

    def _candidate_roots(self, kind: ArtifactKind) -> tuple[Path, ...]:
        """Enumerate only canonical-shape leaves without treating them as committed."""

        parent = self.data_root / artifact_subdirectory(kind)
        if not _exists_no_follow(parent):
            return ()
        _require_real_directory(parent, label="artifact kind directory")
        _require_exact_child_name(
            self.data_root,
            artifact_subdirectory(kind),
            label="artifact kind directory",
        )
        current: tuple[Path, ...] = (parent,)
        for _ in range(artifact_path_depth(kind)):
            next_level: list[Path] = []
            for directory in current:
                try:
                    entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
                except OSError as error:
                    raise ArtifactIntegrityError(
                        "artifact directory could not be enumerated"
                    ) from error
                for entry in entries:
                    if not is_canonical_digest_segment(entry.name):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                        raise ArtifactIntegrityError(
                            "artifact candidate path is not a real directory"
                        )
                    next_level.append(Path(entry.path))
            current = tuple(next_level)
        return tuple(sorted(current, key=lambda path: path.as_posix()))

    @staticmethod
    def _candidate_descriptor_id(root: Path) -> ArtifactId | None:
        """Read only the canonical descriptor ID used to locate a Run candidate."""

        try:
            payload = _read_regular_file(root / _DESCRIPTOR_NAME, label="artifact descriptor")
        except FileNotFoundError:
            return None
        descriptor = _parse_json_object(payload, label="artifact descriptor")
        if payload != _canonical_json(descriptor):
            raise ArtifactIntegrityError("artifact descriptor is not canonical JSON")
        value = descriptor.get("artifact_id")
        if not isinstance(value, str):
            raise ArtifactIntegrityError("descriptor has no artifact_id")
        try:
            artifact_id = ArtifactId(value)
        except (TypeError, ValueError) as error:
            raise ArtifactIntegrityError("descriptor artifact_id is invalid") from error
        if value != artifact_id.hex:
            raise ArtifactIntegrityError("descriptor artifact_id is not canonical")
        return artifact_id

    def _verify_committed(
        self,
        root: Path,
        *,
        # Identity constraints are checked equally on a cache hit and a full hash.
        expected_id: ArtifactId | None = None,
        expected_kind: ArtifactKind | None = None,
    ) -> dict[str, Any]:
        """Reuse full verification only while cheap mutation evidence is unchanged."""

        cache_key = str(root)
        # Serialize the same ID while allowing unrelated artifacts to verify concurrently.
        stripe = self._verification_lock_for(cache_key)
        with stripe:
            # Fingerprint collection is cheap and occurs under same-ID single-flight.
            before = _artifact_file_fingerprint(root)
            with self._verification_cache_lock:
                cached = self._verification_cache.get(cache_key)
                # Changed metadata invalidates the old proof and its memory charge.
                if cached is not None and cached[0] == before:
                    self._verification_cache.move_to_end(cache_key)
                else:
                    cached = self._verification_cache.pop(cache_key, None)
                    # The byte count tracks only evidence still resident in the LRU.
                    if cached is not None:
                        self._verification_cache_current_bytes -= cached[2]
                    cached = None
            # Cache hits still re-authenticate all small filesystem authority files.
            if cached is not None:
                descriptor = _parse_json_object(cached[1], label="artifact descriptor")
                _verify_cached_control_files(root, descriptor, cached[1])
                # Cached proofs remain subject to each caller's exact identity request.
                _require_cached_descriptor_identity(
                    descriptor,
                    expected_id=expected_id,
                    expected_kind=expected_kind,
                )
                # Recheck after control-file reads so a concurrent mutation cannot
                # borrow evidence captured before this cached verification finished.
                if _artifact_file_fingerprint(root) != before:
                    raise ArtifactIntegrityError("artifact changed during verification")
                return descriptor

            # No matching evidence exists, so the ordinary full-hash path is mandatory.
            descriptor = self._verify_committed_uncached(
                root,
                expected_id=expected_id,
                expected_kind=expected_kind,
            )
            # A full hash can be cached only if the tree stayed unchanged throughout.
            after = _artifact_file_fingerprint(root)
            if after != before:
                raise ArtifactIntegrityError("artifact changed during verification")
            descriptor_bytes = _canonical_json(descriptor)
            # Reuse the same bounded insertion path as clean-restart evidence.
            self._remember_verification(cache_key, after, descriptor_bytes)
            return descriptor

    def _seed_verification_cache(
        self,
        root: Path,
        fingerprint: _ArtifactFingerprint,
        # Canonical descriptor bytes were re-authenticated by the exact inventory pass.
        descriptor_bytes: bytes,
    ) -> None:
        """Seed receipt-backed evidence; later opens still authenticate files and identity."""

        try:
            relative = root.relative_to(self.data_root)
        except ValueError as error:
            raise ArtifactIntegrityError("verification seed is outside the data root") from error
        if not relative.parts or ".." in relative.parts:
            # Reject noncanonical roots before they can become process-local cache keys.
            raise ArtifactIntegrityError("verification seed path is not canonical")
        descriptor = _parse_json_object(descriptor_bytes, label="artifact descriptor")
        if descriptor_bytes != _canonical_json(descriptor):
            raise ArtifactIntegrityError("verification seed descriptor is not canonical")

        # The caller supplies clean-receipt proof; same-ID serialization prevents races.
        cache_key = str(root)
        with self._verification_lock_for(cache_key):
            self._remember_verification(cache_key, fingerprint, descriptor_bytes)

    def _verification_lock_for(self, cache_key: str) -> Lock:
        """Select the same bounded single-flight stripe for opens and receipt seeds."""

        stripe_digest = hashlib.sha256(cache_key.encode("utf-8")).digest()
        return self._verification_locks[stripe_digest[0] % len(self._verification_locks)]

    def _remember_verification(
        self,
        cache_key: str,
        fingerprint: _ArtifactFingerprint,
        # Retained bytes are immutable and carry their own conservative memory charge.
        descriptor_bytes: bytes,
    ) -> None:
        """Insert metadata-only evidence while enforcing both existing LRU bounds."""

        weight = _cached_verification_weight(fingerprint, descriptor_bytes)
        if weight > self._verification_cache_max_bytes:
            return
        with self._verification_cache_lock:
            previous = self._verification_cache.pop(cache_key, None)
            # Replacement must remove the prior charge, including repeated receipt seeds.
            if previous is not None:
                self._verification_cache_current_bytes -= previous[2]
            self._verification_cache[cache_key] = (fingerprint, descriptor_bytes, weight)
            self._verification_cache_current_bytes += weight
            # New evidence becomes most recently used before applying both hard limits.
            self._verification_cache.move_to_end(cache_key)
            # Evict oldest evidence until both independent bounds hold.
            while (
                len(self._verification_cache) > self._verification_cache_entries
                or self._verification_cache_current_bytes > self._verification_cache_max_bytes
            ):
                # Drop metadata only; cache eviction holds no handle or retention lease.
                _, evicted = self._verification_cache.popitem(last=False)
                self._verification_cache_current_bytes -= evicted[2]

    def _verify_committed_uncached(
        self,
        # Keep the root input explicit in the verify committed contract.
        root: Path,
        *,
        expected_id: ArtifactId | None = None,
        expected_kind: ArtifactKind | None = None,
    ) -> dict[str, Any]:
        # Execute the local artifact repository verify committed workflow in explicit,
        # reviewable steps.
        try:
            root_stat = root.lstat()
        except OSError as error:
            raise ArtifactNotCommittedError(f"artifact directory is unavailable: {root}") from error
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            # Fail the local artifact repository verify committed path with
            # ArtifactIntegrityError for artifact root must be a real directory when s
            # islnk, st mode and stat is true; do not continue ambiguously.
            raise ArtifactIntegrityError("artifact root must be a real directory")
        try:
            # Perform the protected local artifact repository verify committed operation
            # before explicit failure handling.
            descriptor_bytes = _read_regular_file(
                root / _DESCRIPTOR_NAME,
                label="artifact descriptor",
            )
            marker_bytes = _read_regular_file(root / _MARKER_NAME, label="commit marker")
            # Assemble manifest bytes once so the local artifact repository verify
            # committed workflow shares one value.
            manifest_bytes = _read_regular_file(root / _MANIFEST_NAME, label="root manifest")
        except FileNotFoundError as error:
            raise ArtifactNotCommittedError(f"artifact directory is incomplete: {root}") from error

        descriptor = _parse_json_object(descriptor_bytes, label="artifact descriptor")
        marker = _parse_json_object(marker_bytes, label="commit marker")
        # Evaluate the complete local artifact repository verify committed descriptor
        # bytes, canonical json and descriptor condition before guarded effects.
        if descriptor_bytes != _canonical_json(descriptor):
            raise ArtifactIntegrityError("artifact descriptor is not canonical JSON")
        if marker_bytes != _canonical_json(marker):
            raise ArtifactIntegrityError("commit marker is not canonical JSON")
        base_descriptor_keys = {
            # Keep the artifact id component named inside the base descriptor keys
            # contract.
            "artifact_id",
            "build_key",
            "files",
            "input_artifact_ids",
            "kind",
            # Keep the manifest sha256 component named inside the base descriptor keys
            # contract.
            "manifest_sha256",
            "version",
        }
        descriptor_version = descriptor.get("version")
        expected_descriptor_keys = (
            # Keep the base descriptor keys component named inside the expected descriptor
            # keys contract.
            base_descriptor_keys | {"manifest_identity_sha256"}
            if descriptor_version == 3
            else base_descriptor_keys
        )
        if (
            # Keep set visible while evaluating the expected descriptor keys, isinstance
            # and descriptor version guard.
            set(descriptor) != expected_descriptor_keys
            or isinstance(descriptor_version, bool)
            or descriptor_version not in {1, 2, 3}
        ):
            raise ArtifactIntegrityError("artifact descriptor schema is invalid")
        # Assemble artifact id once so the local artifact repository verify committed
        # workflow shares one value.
        artifact_id = descriptor.get("artifact_id")
        if not isinstance(artifact_id, str):
            raise ArtifactIntegrityError("descriptor has no artifact_id")
        try:
            parsed_id = ArtifactId(artifact_id)
        # Translate type error through the local artifact repository verify committed
        # boundary without hiding other errors.
        except (TypeError, ValueError) as error:
            raise ArtifactIntegrityError("descriptor artifact_id is invalid") from error
        if artifact_id != parsed_id.hex:
            raise ArtifactIntegrityError("descriptor artifact_id is not canonical")
        if expected_id is not None and parsed_id.hex != expected_id.hex:
            # Fail the local artifact repository verify committed path with
            # ArtifactIntegrityError for artifact id does not match requested id when
            # expected id, hex and parsed id is true; do not continue ambiguously.
            raise ArtifactIntegrityError("artifact id does not match requested id")
        try:
            # Perform the protected local artifact repository verify committed operation
            # before explicit failure handling.
            descriptor_kind = ArtifactKind(descriptor["kind"])
            build_key = ContentDigest(cast(str, descriptor["build_key"]))
            manifest_digest = ContentDigest(cast(str, descriptor["manifest_sha256"]))
            manifest_identity_digest = (
                ContentDigest(cast(str, descriptor["manifest_identity_sha256"]))
                # Keep the descriptor version component named inside the manifest identity
                # digest contract.
                if descriptor_version == 3
                else None
            )
            input_values = descriptor["input_artifact_ids"]
            if not isinstance(input_values, list) or not all(
                # Keep isinstance visible while evaluating the isinstance, input values
                # and value guard.
                isinstance(value, str)
                for value in input_values
            ):
                raise TypeError("input_artifact_ids must be a list of strings")
            input_ids = tuple(ArtifactId(value) for value in input_values)
        # Translate key error through the local artifact repository verify committed
        # boundary without hiding other errors.
        except (KeyError, TypeError, ValueError) as error:
            # Fail the local artifact repository verify committed path with
            # ArtifactIntegrityError for artifact descriptor fields are invalid; do not
            # continue ambiguously.
            raise ArtifactIntegrityError("artifact descriptor fields are invalid") from error
        if build_key.value != build_key.hex or manifest_digest.value != manifest_digest.hex:
            raise ArtifactIntegrityError("descriptor digests are not canonical")
        if (
            manifest_identity_digest is not None
            # Keep manifest identity digest visible while evaluating the manifest identity
            # digest, value and hex guard.
            and manifest_identity_digest.value != manifest_identity_digest.hex
        ):
            raise ArtifactIntegrityError("manifest identity digest is not canonical")
        if any(item.value != item.hex for item in input_ids):
            raise ArtifactIntegrityError("descriptor input IDs are not canonical")
        # Assemble input hexes once so the local artifact repository verify committed
        # workflow shares one value.
        input_hexes = [item.hex for item in input_ids]
        if input_hexes != sorted(input_hexes) or len(input_hexes) != len(set(input_hexes)):
            raise ArtifactIntegrityError("descriptor input IDs must be sorted and unique")
        _validate_descriptor_files(descriptor["files"])
        if expected_kind is not None and descriptor_kind is not expected_kind:
            # Fail the local artifact repository verify committed path with
            # ArtifactIntegrityError for artifact kind does not match its repository
            # directory when expected kind and descriptor kind is true; do not continue
            # ambiguously.
            raise ArtifactIntegrityError("artifact kind does not match its repository directory")
        identity = dict(descriptor)
        identity.pop("artifact_id", None)
        # Guard this path with descriptor_version == 1 before applying effects.
        if descriptor_version == 1:
            identity_domain = _IDENTITY_DOMAIN_V1
        # Handle the local artifact repository verify committed complement of
        # descriptor_version == 1 explicitly.
        elif descriptor_version == 2:
            # Handle the local artifact repository verify committed descriptor_version ==
            # 2 branch as a distinct logical block.
            identity.pop("build_key", None)
            identity_domain = _IDENTITY_DOMAIN_V2
        else:
            # Handle the local artifact repository verify committed complement of
            # descriptor_version == 2 explicitly.
            identity.pop("build_key", None)
            identity.pop("manifest_sha256", None)
            identity_domain = _IDENTITY_DOMAIN_V3
        recomputed = _sha256_bytes(identity_domain + _canonical_json(identity))
        if recomputed != parsed_id.hex:
            # Fail the local artifact repository verify committed path with
            # ArtifactIntegrityError for artifact descriptor identity mismatch when
            # recomputed, hex and parsed id is true; do not continue ambiguously.
            raise ArtifactIntegrityError("artifact descriptor identity mismatch")
        marker_version = marker.get("version")
        if (
            isinstance(marker_version, bool)
            or marker_version != descriptor_version
            # Keep marker visible while evaluating the isinstance, marker version and
            # descriptor version guard.
            or marker
            != {
                "artifact_id": parsed_id.hex,
                "descriptor_sha256": _sha256_bytes(descriptor_bytes),
                "version": descriptor_version,
                # Evaluate the complete local artifact repository verify committed isinstance,
                # marker version and descriptor version condition before guarded effects.
            }
        ):
            raise ArtifactIntegrityError("commit marker does not authenticate descriptor")
        if manifest_digest.hex != _sha256_bytes(manifest_bytes):
            raise ArtifactIntegrityError("manifest digest mismatch")
        # Assemble manifest once so the local artifact repository verify committed
        # workflow shares one value.
        manifest = _parse_json_object(manifest_bytes, label="root manifest")
        placement_identity: Mapping[str, object] = manifest
        if descriptor_version == 3:
            # Handle the local artifact repository verify committed descriptor_version ==
            # 3 branch as a distinct logical block.
            try:
                # Perform the protected local artifact repository verify committed
                # operation before explicit failure handling.
                manifest_identity_bytes = _read_regular_file(
                    root / _IDENTITY_MANIFEST_NAME,
                    label="manifest identity",
                )
            except FileNotFoundError as error:
                # Fail the local artifact repository verify committed path with
                # ArtifactNotCommittedError for artifact has no manifest identity when
                # descriptor version is true; do not continue ambiguously.
                raise ArtifactNotCommittedError("artifact has no manifest identity") from error
            manifest_identity = _parse_json_object(
                manifest_identity_bytes,
                label="manifest identity",
            )
            # Evaluate the complete local artifact repository verify committed manifest
            # identity bytes, canonical json and manifest identity condition before
            # guarded effects.
            if manifest_identity_bytes != _canonical_json(manifest_identity):
                raise ArtifactIntegrityError("manifest identity is not canonical JSON")
            if manifest_identity_digest is None or (
                manifest_identity_digest.hex != _sha256_bytes(manifest_identity_bytes)
            ):
                # Fail the local artifact repository verify committed path with
                # ArtifactIntegrityError for manifest identity digest mismatch when
                # manifest identity digest, hex and sha256 bytes is true; do not continue
                # ambiguously.
                raise ArtifactIntegrityError("manifest identity digest mismatch")
            if not _is_json_projection(manifest_identity, manifest):
                raise ArtifactIntegrityError("manifest identity is not a projection of manifest")
            placement_identity = manifest_identity
        try:
            expected_relative = artifact_relative_path(
                descriptor_kind,
                parsed_id,
                placement_identity,
            )
            actual_relative = root.relative_to(self.data_root)
        except (ArtifactPlacementError, ValueError) as error:
            raise ArtifactIntegrityError("artifact physical placement is invalid") from error
        if actual_relative.as_posix() != expected_relative.as_posix():
            raise ArtifactIntegrityError("artifact physical placement does not match identity")
        if descriptor.get("files") != _payload_entries(root):
            raise ArtifactIntegrityError("artifact payload differs from its descriptor")
        # Return the completed local artifact repository verify committed result without a
        # hidden fallback.
        return descriptor


# Keep the local artifact writer contract and validation rules together.
class _LocalArtifactWriter:
    def __init__(self, repository: LocalArtifactRepository, draft: ArtifactDraft) -> None:
        # Execute the local artifact writer init workflow in explicit, reviewable steps.
        self._repository = repository
        self._draft = draft
        self._writer_lock = FileLock(
            repository.locks_root / "writer.lock",
            mode=LockMode.EXCLUSIVE,
            # Complete acquire only after its declared inputs are visible in local artifact
            # writer init.
        ).acquire()
        self._state = "open"
        self._open_streams: list[IO[bytes]] = []
        self._quota = _StagingQuota(repository.staging_quota_bytes)
        self._root = repository.staging_root / f"artifact-{uuid.uuid4().hex}"
        # Keep expected failures inside the local artifact writer init error boundary.
        try:
            # Perform the protected local artifact writer init operation before explicit
            # failure handling.
            self._root.mkdir(mode=0o700)
            _fsync_directory(repository.staging_root)
        except BaseException:
            # Translate the BaseException failure through the local artifact writer init
            # boundary.
            self._writer_lock.release()
            raise

    @property
    def draft(self) -> ArtifactDraft:
        return self._draft

    # Define local artifact writer open binary as one focused operation with an explicit
    # boundary.
    def open_binary(self, relative_name: str) -> IO[bytes]:
        # Execute the local artifact writer open binary workflow in explicit, reviewable
        # steps.
        self._require_open()
        relative = _safe_relative_path(relative_name)
        destination = self._root.joinpath(*relative.parts)
        _ensure_directories_beneath(self._root, relative.parts[:-1])
        flags = (
            # Keep the os component named inside the flags contract.
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            # Complete the flags group only after its semantic components are visible.
        )
        descriptor = os.open(destination, flags, 0o600)
        try:
            stream = cast(IO[bytes], os.fdopen(descriptor, "wb"))
        except BaseException:
            # Translate the BaseException failure through the local artifact writer open
            # binary boundary.
            os.close(descriptor)
            raise
        quota_stream = cast(IO[bytes], _QuotaBinaryStream(stream, self._quota))
        self._open_streams.append(quota_stream)
        return quota_stream

    # Define local artifact writer commit as one focused operation with an explicit
    # boundary.
    def commit(
        self,
        manifest_bytes: bytes,
        *,
        identity_manifest_bytes: bytes | None = None,
        # Keep the committed artifact input explicit in the commit contract.
    ) -> CommittedArtifact:
        # Execute the local artifact writer commit workflow in explicit, reviewable steps.
        self._require_open()
        if not isinstance(manifest_bytes, bytes):
            raise TypeError("manifest_bytes must be bytes")
        if any(not stream.closed for stream in self._open_streams):
            raise ArtifactWriterStateError("close all artifact payload streams before commit")

        # Keep expected failures inside the local artifact writer commit error boundary.
        try:
            # Perform the protected local artifact writer commit operation before explicit
            # failure handling.
            manifest = _parse_json_object(manifest_bytes, label="root manifest")
            selected_identity_bytes = (
                manifest_bytes if identity_manifest_bytes is None else identity_manifest_bytes
            )
            if not isinstance(selected_identity_bytes, bytes):
                # Fail the local artifact writer commit path with TypeError for identity
                # manifest bytes must be bytes or none when isinstance, selected identity
                # bytes and bytes is true; do not continue ambiguously.
                raise TypeError("identity_manifest_bytes must be bytes or None")
            manifest_identity = _parse_json_object(
                selected_identity_bytes,
                label="manifest identity",
            )
            # Evaluate the complete local artifact writer commit selected identity bytes,
            # canonical json and manifest identity condition before guarded effects.
            if selected_identity_bytes != _canonical_json(manifest_identity):
                raise ArtifactIntegrityError("manifest identity must be canonical JSON")
            if not _is_json_projection(manifest_identity, manifest):
                raise ArtifactIntegrityError("manifest identity must project the root manifest")
            self._verify_staging_quota()
            # Invoke reserve for len and manifest bytes as a visible local artifact writer
            # commit step.
            self._quota.reserve(len(manifest_bytes))
            _write_durable_exclusive(self._root / _MANIFEST_NAME, manifest_bytes)
            self._quota.reserve(len(selected_identity_bytes))
            _write_durable_exclusive(
                self._root / _IDENTITY_MANIFEST_NAME,
                # Pass selected identity bytes explicitly so _write_durable_exclusive
                # receives a reviewable root and identity manifest name input in local
                # artifact writer commit.
                selected_identity_bytes,
            )
            files = _payload_entries(self._root)
            input_artifact_ids = sorted(item.hex for item in self._draft.input_artifact_ids)
            if len(input_artifact_ids) != len(set(input_artifact_ids)):
                # Fail the local artifact writer commit path with ArtifactIntegrityError
                # for artifact inputs must not contain duplicates when input artifact ids
                # is true; do not continue ambiguously.
                raise ArtifactIntegrityError("artifact inputs must not contain duplicates")
            identity: dict[str, object] = {
                "build_key": self._draft.build_key.hex,
                "files": files,
                "input_artifact_ids": input_artifact_ids,
                # Keep the kind component named inside the identity contract.
                "kind": self._draft.kind.value,
                "manifest_identity_sha256": _sha256_bytes(selected_identity_bytes),
                "manifest_sha256": _sha256_bytes(manifest_bytes),
                "version": 3,
            }
            # Assemble content identity once so the local artifact writer commit workflow
            # shares one value.
            content_identity = dict(identity)
            content_identity.pop("build_key")
            content_identity.pop("manifest_sha256")
            artifact_id = ArtifactId(
                _sha256_bytes(_IDENTITY_DOMAIN_V3 + _canonical_json(content_identity))
                # Complete ArtifactId only after its sha256 bytes and canonical json inputs
                # are visible in local artifact writer commit.
            )
            try:
                relative_root = artifact_relative_path(
                    self._draft.kind,
                    artifact_id,
                    manifest_identity,
                )
            except ArtifactPlacementError as error:
                raise ArtifactIntegrityError(
                    "artifact identity cannot be placed in the local data root"
                ) from error
            descriptor = {"artifact_id": artifact_id.value, **identity}
            descriptor_bytes = _canonical_json(descriptor)
            self._quota.reserve(len(descriptor_bytes))
            _write_durable_exclusive(self._root / _DESCRIPTOR_NAME, descriptor_bytes)
            # Invoke _verify_staging_quota as a visible step within the local artifact
            # writer commit workflow.
            self._verify_staging_quota()
            self._sync_staging_tree()

            committed = CommittedArtifact(
                artifact_id=artifact_id,
                kind=self._draft.kind,
                # Keep the content digest and cast ContentDigest step visible while
                # building committed.
                manifest_digest=ContentDigest(cast(str, identity["manifest_sha256"])),
                build_key=ContentDigest(self._draft.build_key.hex),
                input_artifact_ids=tuple(ArtifactId(value) for value in input_artifact_ids),
            )
            committed = self._publish(committed, descriptor_bytes, relative_root)
            # Assemble self state once so the local artifact writer commit workflow shares
            # one value.
            self._state = "committed"
            return committed
        except BaseException:
            # Translate the BaseException failure through the local artifact writer commit
            # boundary.
            if self._state == "open":
                self._state = "failed"
            raise
        finally:
            self._writer_lock.release()

    # Define local artifact writer abort as one focused operation with an explicit
    # boundary.
    def abort(self) -> None:
        # Execute the local artifact writer abort workflow in explicit, reviewable steps.
        if self._state in {"aborted", "committed"}:
            return
        self._state = "aborting"
        try:
            # Perform the protected local artifact writer abort operation before explicit
            # failure handling.
            for stream in self._open_streams:
                # Process self._open_streams inside the bounded local artifact writer
                # abort loop.
                if not stream.closed:
                    stream.close()
            if self._root.exists():
                # Handle the local artifact writer abort self._root.exists() branch as a
                # distinct logical block.
                shutil.rmtree(self._root)
                _fsync_directory(self._repository.staging_root)
        except BaseException:
            # Translate the BaseException failure through the local artifact writer abort
            # boundary.
            self._state = "failed"
            raise
        else:
            self._state = "aborted"
        finally:
            # Invoke release as a visible step within the local artifact writer abort
            # workflow.
            self._writer_lock.release()

    def _publish(
        self,
        committed: CommittedArtifact,
        descriptor_bytes: bytes,
        relative_root: PurePosixPath,
        # Keep the committed artifact input explicit in the publish contract.
    ) -> CommittedArtifact:
        # Execute the local artifact writer publish workflow in explicit, reviewable
        # steps.
        repository = self._repository
        final_parent = _ensure_repository_parent(repository.data_root, relative_root.parts[:-1])
        _require_same_filesystem(repository.staging_root, final_parent)
        final_root = final_parent / relative_root.name
        retention_lock = FileLock(
            repository.locks_root / "retention.lock",
            # Pass mode explicitly so FileLock receives a reviewable lock and locks root
            # input in local artifact writer publish.
            mode=LockMode.SHARED,
        )
        publication_lock = FileLock(
            repository.locks_root / "publication.lock",
            mode=LockMode.EXCLUSIVE,
            # Complete FileLock only after its lock and locks root inputs are visible in local
            # artifact writer publish.
        )
        needs_exclusive_retention = False
        with retention_lock, publication_lock:
            self._verify_inputs_locked()
            if _exists_no_follow(final_root):
                _require_exact_child_name(
                    final_parent,
                    relative_root.name,
                    label="artifact final root",
                )
                try:
                    existing_descriptor = repository._verify_committed(
                        final_root,
                        expected_kind=committed.kind,
                    )
                except ArtifactRepositoryError:
                    needs_exclusive_retention = True
                else:
                    existing = _committed_from_descriptor(existing_descriptor)
                    if existing.artifact_id == committed.artifact_id:
                        self._discard_staging()
                        return existing
                    needs_exclusive_retention = True
            else:
                return self._install_staged_locked(
                    committed,
                    descriptor_bytes,
                    final_root=final_root,
                    final_parent=final_parent,
                )

        if not needs_exclusive_retention:  # pragma: no cover - defensive state guard
            raise ArtifactRepositoryError("artifact publication state is inconsistent")
        return self._resolve_existing_path_under_exclusive_retention(
            committed,
            descriptor_bytes,
            final_root=final_root,
            final_parent=final_parent,
        )

    def _resolve_existing_path_under_exclusive_retention(
        self,
        committed: CommittedArtifact,
        descriptor_bytes: bytes,
        *,
        final_root: Path,
        final_parent: Path,
    ) -> CommittedArtifact:
        repository = self._repository
        retention_lock = FileLock(
            repository.locks_root / "retention.lock",
            mode=LockMode.EXCLUSIVE,
        )
        publication_lock = FileLock(
            repository.locks_root / "publication.lock",
            mode=LockMode.EXCLUSIVE,
        )
        with retention_lock, publication_lock:
            self._verify_inputs_locked()
            if not _exists_no_follow(final_root):
                return self._install_staged_locked(
                    committed,
                    descriptor_bytes,
                    final_root=final_root,
                    final_parent=final_parent,
                )
            _require_exact_child_name(
                final_parent,
                final_root.name,
                label="artifact final root",
            )
            try:
                existing_descriptor = repository._verify_committed(
                    final_root,
                    expected_kind=committed.kind,
                )
            except ArtifactRepositoryError:
                _quarantine_path(
                    repository,
                    final_root,
                    prefix=f"uncommitted-{committed.kind.value.lower()}",
                )
                return self._install_staged_locked(
                    committed,
                    descriptor_bytes,
                    final_root=final_root,
                    final_parent=final_parent,
                )
            existing = _committed_from_descriptor(existing_descriptor)
            if existing.artifact_id == committed.artifact_id:
                self._discard_staging()
                return existing
            _quarantine_path(
                repository,
                final_root,
                prefix=f"conflict-existing-{committed.kind.value.lower()}",
            )
            _quarantine_path(
                repository,
                self._root,
                prefix=f"conflict-incoming-{committed.kind.value.lower()}",
            )
            raise ArtifactIntegrityError(
                "artifact final path resolves to different committed content"
            )

    def _verify_inputs_locked(self) -> None:
        repository = self._repository
        for input_artifact_id in self._draft.input_artifact_ids:
            input_kind, input_root = repository._find_artifact_root(input_artifact_id)
            repository._verify_committed(
                input_root,
                expected_id=input_artifact_id,
                expected_kind=input_kind,
            )
            _fsync_directory(input_root)
            _fsync_directory(input_root.parent)

    def _install_staged_locked(
        self,
        committed: CommittedArtifact,
        descriptor_bytes: bytes,
        *,
        final_root: Path,
        final_parent: Path,
    ) -> CommittedArtifact:
        repository = self._repository
        os.rename(self._root, final_root)
        _fsync_directory(repository.staging_root)
        _fsync_directory(final_parent)
        marker = _canonical_json(
            {
                "artifact_id": committed.artifact_id.hex,
                "descriptor_sha256": _sha256_bytes(descriptor_bytes),
                "version": 3,
            }
        )
        temporary_marker = final_root / f".COMMITTED.tmp-{uuid.uuid4().hex}"
        _write_durable_exclusive(temporary_marker, marker)
        os.replace(temporary_marker, final_root / _MARKER_NAME)
        _fsync_directory(final_root)
        _fsync_directory(final_parent)
        repository._verify_committed(
            final_root,
            expected_id=committed.artifact_id,
            expected_kind=committed.kind,
        )
        return committed

    def _discard_staging(self) -> None:
        shutil.rmtree(self._root)
        _fsync_directory(self._repository.staging_root)

    def _sync_staging_tree(self) -> None:
        # Execute the local artifact writer sync staging tree workflow in explicit,
        # reviewable steps.
        directories = {self._root}
        for path in _regular_files(self._root):
            # Process _regular_files(self._root) inside the bounded local artifact writer
            # sync staging tree loop.
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                # Invoke fsync for descriptor as a visible local artifact writer sync
                # staging tree step.
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            directories.add(path.parent)
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            # Invoke _fsync_directory for directory as a visible local artifact writer
            # sync staging tree step.
            _fsync_directory(directory)

    def _verify_staging_quota(self) -> None:
        # Execute the local artifact writer verify staging quota workflow in explicit,
        # reviewable steps.
        self._quota.verify_physical_bytes(
            sum(file.stat().st_size for file in _regular_files(self._root))
        )

    def _require_open(self) -> None:
        # Execute the local artifact writer require open workflow in explicit, reviewable
        # steps.
        if self._state != "open":
            raise ArtifactWriterStateError(f"artifact writer is {self._state}")

    def __del__(self) -> None:
        # Execute the local artifact writer del workflow in explicit, reviewable steps.
        if getattr(self, "_state", None) == "open":
            # Handle the local artifact writer del open and getattr condition as a
            # distinct block.
            with suppress(BaseException):
                self.abort()


# Keep the local artifact handle contract and validation rules together.
class _LocalArtifactHandle:
    def __init__(
        self,
        *,
        data_root: Path,
        root: Path,
        # Keep the descriptor input explicit in the init contract.
        descriptor: CommittedArtifact,
        retention_lock: FileLock,
    ) -> None:
        # Execute the local artifact handle init workflow in explicit, reviewable steps.
        self._data_root = data_root
        self._root = root
        self._descriptor = descriptor
        self._retention_lock = retention_lock
        self._closed = False

    @property
    # Define local artifact handle descriptor as one focused operation with an explicit
    # boundary.
    def descriptor(self) -> CommittedArtifact:
        return self._descriptor

    def open_binary(self, relative_name: str) -> IO[bytes]:
        # Execute the local artifact handle open binary workflow in explicit, reviewable
        # steps.
        if self._closed:
            raise ArtifactRepositoryError("artifact handle is closed")
        relative = _safe_relative_path(relative_name, allow_reserved=True)
        source = self._root.joinpath(*relative.parts)
        _ensure_artifact_root_chain_for_read(self._data_root, self._root)
        _ensure_directories_beneath_for_read(self._root, relative.parts[:-1])
        # Keep expected failures inside the local artifact handle open binary error
        # boundary.
        try:
            file_stat = source.lstat()
        except FileNotFoundError as error:
            raise FileNotFoundError(relative_name) from error
        if not stat.S_ISREG(file_stat.st_mode):
            # Fail the local artifact handle open binary path with
            # InvalidArtifactPathError for artifact member must be a regular file when s
            # isreg, st mode and stat is true; do not continue ambiguously.
            raise InvalidArtifactPathError("artifact member must be a regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(source, flags)
        except OSError as error:
            # Fail the local artifact handle open binary path with
            # InvalidArtifactPathError for artifact member could not be opened safely; do
            # not continue ambiguously.
            raise InvalidArtifactPathError("artifact member could not be opened safely") from error
        try:
            # Perform the protected local artifact handle open binary operation before
            # explicit failure handling.
            file_stat = os.fstat(descriptor)
            is_regular = stat.S_ISREG(file_stat.st_mode) and file_stat.st_nlink == 1
        except BaseException:
            # Translate the BaseException failure through the local artifact handle open
            # binary boundary.
            os.close(descriptor)
            raise
        if not is_regular:
            # Handle the local artifact handle open binary not is_regular branch as a
            # distinct logical block.
            os.close(descriptor)
            raise InvalidArtifactPathError("artifact member must be a regular file")
        try:
            return cast(IO[bytes], os.fdopen(descriptor, "rb"))
        except BaseException:
            # Translate the BaseException failure through the local artifact handle open
            # binary boundary.
            os.close(descriptor)
            raise

    def local_path(self, relative_name: str) -> Path:
        """Return a verified member path while this handle owns its read lease.

        This adapter-specific method is used only by local mmap/DuckDB adapters;
        it is intentionally absent from the infrastructure-neutral port.
        """

        if self._closed:
            raise ArtifactRepositoryError("artifact handle is closed")
        relative = _safe_relative_path(relative_name, allow_reserved=True)
        source = self._root.joinpath(*relative.parts)
        _ensure_artifact_root_chain_for_read(self._data_root, self._root)
        _ensure_directories_beneath_for_read(self._root, relative.parts[:-1])
        # Keep expected failures inside the local artifact handle local path error
        # boundary.
        try:
            file_stat = source.lstat()
        except FileNotFoundError as error:
            raise FileNotFoundError(relative_name) from error
        if (
            # Keep stat visible while evaluating the st nlink, s islnk and st mode guard.
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or stat.S_ISLNK(file_stat.st_mode)
        ):
            raise InvalidArtifactPathError("artifact member must be a regular file")
        # Return the completed local artifact handle local path result without a hidden
        # fallback.
        return source

    def close(self) -> None:
        # Execute the local artifact handle close workflow in explicit, reviewable steps.
        if self._closed:
            return
        self._closed = True
        self._retention_lock.release()

    def __enter__(self) -> _LocalArtifactHandle:
        # Return the completed local artifact handle enter result without a hidden
        # fallback.
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        # Keep the traceback input explicit in the exit contract.
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        # Execute the local artifact handle del workflow in explicit, reviewable steps.
        if getattr(self, "_closed", True):
            return
        with suppress(BaseException):
            self.close()


def _committed_from_descriptor(descriptor: Mapping[str, object]) -> CommittedArtifact:
    # Execute the committed from descriptor workflow in explicit, reviewable steps.
    try:
        # Perform the protected committed from descriptor operation before explicit
        # failure handling.
        artifact_id = ArtifactId(cast(str, descriptor["artifact_id"]))
        kind = ArtifactKind(cast(str, descriptor["kind"]))
        manifest_digest = ContentDigest(cast(str, descriptor["manifest_sha256"]))
        build_key = ContentDigest(cast(str, descriptor["build_key"]))
        raw_input_ids = cast(list[str], descriptor["input_artifact_ids"])
        # Assemble input artifact ids once so the committed from descriptor workflow
        # shares one value.
        input_artifact_ids = tuple(ArtifactId(value) for value in raw_input_ids)
    except (KeyError, TypeError, ValueError) as error:
        raise ArtifactIntegrityError("invalid committed-artifact descriptor") from error
    return CommittedArtifact(
        artifact_id=artifact_id,
        # Pass kind explicitly so CommittedArtifact receives a reviewable artifact id and
        # kind input in committed from descriptor.
        kind=kind,
        manifest_digest=manifest_digest,
        build_key=build_key,
        input_artifact_ids=input_artifact_ids,
    )


# Bind all once as an explicit module-level contract.
__all__ = [
    "ArtifactIntegrityError",
    "ArtifactNotCommittedError",
    "ArtifactRepositoryError",
    "ArtifactWriterStateError",
    # Keep the invalid artifact path error component named inside the all contract.
    "InvalidArtifactPathError",
    "LocalArtifactRepository",
    "StagingQuotaExceededError",
]
