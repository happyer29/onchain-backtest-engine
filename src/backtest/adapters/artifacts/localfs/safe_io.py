"""No-follow durable filesystem helpers shared by retention and backup adapters."""

from __future__ import annotations

import hashlib
import json
import os
import stat

# Import contextlib at the visible module dependency boundary.
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, NoReturn, cast


class SafeFilesystemError(RuntimeError):
    """A path, file type, link count, or durable write failed validation."""


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    sha256: str
    size: int

    # Define file record as json as one focused operation with an explicit boundary.
    def as_json(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


def canonical_json(value: object) -> bytes:
    # Execute the canonical json workflow in explicit, reviewable steps.
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        # Pass sort keys explicitly so encode receives a reviewable utf-8 input in
        # canonical json.
        sort_keys=True,
    ).encode("utf-8")


def parse_canonical_object(payload: bytes, *, label: str) -> dict[str, object]:
    # Execute the parse canonical object workflow in explicit, reviewable steps.
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        # Execute the no duplicates workflow in explicit, reviewable steps.
        result: dict[str, object] = {}
        for key, value in pairs:
            # Process pairs inside the bounded no duplicates loop.
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        # Fail the reject constant path with ValueError for non-finite number and value;
        # do not continue ambiguously.
        raise ValueError(f"non-finite number {value}")

    try:
        # Perform the protected parse canonical object operation before explicit failure
        # handling.
        parsed = json.loads(
            payload,
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    # Translate unicode decode error through the parse canonical object boundary without
    # hiding other errors.
    except (UnicodeDecodeError, ValueError) as error:
        raise SafeFilesystemError(f"{label} is not strict JSON") from error
    if not isinstance(parsed, dict) or canonical_json(parsed) != payload:
        raise SafeFilesystemError(f"{label} must be a canonical JSON object")
    return cast(dict[str, object], parsed)


# Define sha256 bytes as one focused operation with an explicit boundary.
def sha256_bytes(payload: bytes, *, domain: bytes = b"") -> str:
    return hashlib.sha256(domain + payload).hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    # Execute the safe relative path workflow in explicit, reviewable steps.
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        raise SafeFilesystemError("relative path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SafeFilesystemError("relative path escapes its configured root")
    # Guard this path with path.as_posix() != value before applying effects.
    if path.as_posix() != value:
        raise SafeFilesystemError("relative path is not canonical")
    return path


def require_real_directory(path: Path, *, label: str) -> None:
    # Execute the require real directory workflow in explicit, reviewable steps.
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SafeFilesystemError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        # Fail the require real directory path with SafeFilesystemError for must be a real
        # directory and label when s islnk, st mode and stat is true; do not continue
        # ambiguously.
        raise SafeFilesystemError(f"{label} must be a real directory")


def ensure_real_directory(path: Path, *, parent: Path | None = None) -> None:
    # Execute the ensure real directory workflow in explicit, reviewable steps.
    if parent is not None:
        # Handle the ensure real directory parent is not None branch as a distinct logical
        # block.
        require_real_directory(parent, label="parent directory")
        if path.parent != parent:
            raise SafeFilesystemError("directory is not an immediate configured child")
    with suppress(FileExistsError):
        path.mkdir(mode=0o700)
    # Invoke require_real_directory for directory and path as a visible ensure real
    # directory step.
    require_real_directory(path, label="directory")


def fsync_directory(path: Path) -> None:
    # Execute the fsync directory workflow in explicit, reviewable steps.
    require_real_directory(path, label="fsync directory")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        # Keep the os getattr step visible while building descriptor.
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        os.close(descriptor)


def read_regular(path: Path, *, label: str) -> bytes:
    # Execute the read regular workflow in explicit, reviewable steps.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SafeFilesystemError(f"{label} could not be opened safely") from error
    # Keep expected failures inside the read regular error boundary.
    try:
        # Perform the protected read regular operation before explicit failure handling.
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SafeFilesystemError(f"{label} must be a single-link regular file")
        with os.fdopen(descriptor, "rb") as stream:
            # Keep fdopen, descriptor and rb active only for the bounded read regular
            # operation.
            descriptor = -1
            return stream.read()
    finally:
        # Handle the cleanup path after the protected read regular operation.
        if descriptor >= 0:
            os.close(descriptor)


def write_durable_exclusive(path: Path, payload: bytes) -> None:
    # Execute the write durable exclusive workflow in explicit, reviewable steps.
    require_real_directory(path.parent, label="metadata parent")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        # Keep the os getattr step visible while building flags.
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        # Perform the protected write durable exclusive operation before explicit failure
        # handling.
        view = memoryview(payload)
        while view:
            # Keep the view loop body bounded within write durable exclusive.
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive kernel boundary
                raise OSError("short durable write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Define publish no replace as one focused operation with an explicit boundary.
def publish_no_replace(path: Path, payload: bytes, *, temporary_name: str) -> bool:
    """Publish bytes with an atomic no-overwrite link; return False if already present."""

    temporary = path.parent / temporary_name
    write_durable_exclusive(temporary, payload)
    published = False
    try:
        # Perform the protected publish no replace operation before explicit failure
        # handling.
        try:
            # Perform the protected publish no replace operation before explicit failure
            # handling.
            os.link(temporary, path, follow_symlinks=False)
            published = True
            fsync_directory(path.parent)
        except FileExistsError:
            published = False
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        # Handle the cleanup path after the protected publish no replace operation.
        os.unlink(temporary)
        fsync_directory(path.parent)
    return published


def file_records(root: Path) -> tuple[FileRecord, ...]:
    # Execute the file records workflow in explicit, reviewable steps.
    require_real_directory(root, label="inventory root")
    records: list[FileRecord] = []
    pending = [root]
    while pending:
        # Keep the pending loop body bounded within file records.
        directory = pending.pop()
        require_real_directory(directory, label="inventory directory")
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            # Fail the file records path with SafeFilesystemError for inventory directory
            # cannot be enumerated; do not continue ambiguously.
            raise SafeFilesystemError("inventory directory cannot be enumerated") from error
        for entry in entries:
            # Process entries inside the bounded file records loop.
            path = Path(entry.path)
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise SafeFilesystemError("symbolic links are forbidden")
            if stat.S_ISDIR(metadata.st_mode):
                # Handle the file records stat.S_ISDIR(metadata.st_mode) branch as a
                # distinct logical block.
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise SafeFilesystemError("only single-link regular files are supported")
            relative = path.relative_to(root).as_posix()
            # Assemble (digest, size) once so the file records workflow shares one value.
            digest, size = _sha256_file(path)
            records.append(FileRecord(path=relative, sha256=digest, size=size))
    return tuple(sorted(records, key=lambda item: item.path))


def records_digest(records: tuple[FileRecord, ...], *, domain: bytes) -> str:
    return sha256_bytes(canonical_json([record.as_json() for record in records]), domain=domain)


# Define copy tree verified as one focused operation with an explicit boundary.
def copy_tree_verified(
    source: Path,
    destination: Path,
    *,
    expected: tuple[FileRecord, ...] | None = None,
    # Keep the tuple input explicit in the copy tree verified contract.
) -> tuple[FileRecord, ...]:
    # Execute the copy tree verified workflow in explicit, reviewable steps.
    records = file_records(source)
    if expected is not None and records != expected:
        raise SafeFilesystemError("source tree changed after inventory")
    if destination.exists():
        raise SafeFilesystemError("copy destination already exists")
    # Invoke mkdir as a visible step within the copy tree verified workflow.
    destination.mkdir(mode=0o700)
    directories = {destination}
    try:
        # Perform the protected copy tree verified operation before explicit failure
        # handling.
        for record in records:
            # Process records inside the bounded copy tree verified loop.
            relative = safe_relative_path(record.path)
            parent = destination
            for part in relative.parts[:-1]:
                # Process relative.parts[:-1] inside the bounded copy tree verified loop.
                child = parent / part
                ensure_real_directory(child, parent=parent)
                directories.add(child)
                parent = child
            _copy_regular(source.joinpath(*relative.parts), parent / relative.name)
        # Traverse sorted, directories and parts explicitly so each copy tree verified
        # iteration remains traceable.
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            fsync_directory(directory)
    except BaseException:
        # Leave the incomplete private staging tree for crash recovery; callers
        # never treat a tree without its final marker as committed.
        raise
    copied = file_records(destination)
    if copied != records:
        raise SafeFilesystemError("copied tree failed content verification")
    return copied


# Define remove verified tree as one focused operation with an explicit boundary.
def remove_verified_tree(root: Path, expected: tuple[FileRecord, ...]) -> int:
    # Execute the remove verified tree workflow in explicit, reviewable steps.
    actual = file_records(root)
    if actual != expected:
        raise SafeFilesystemError("trash content changed before deletion")
    directories: set[Path] = {root}
    deleted_bytes = 0
    # Traverse actual explicitly so each remove verified tree iteration remains traceable.
    for record in actual:
        # Process actual inside the bounded remove verified tree loop.
        relative = safe_relative_path(record.path)
        path = root.joinpath(*relative.parts)
        os.unlink(path)
        deleted_bytes += record.size
        directories.update(path.parents)
    # Assemble contained once so the remove verified tree workflow shares one value.
    contained = [
        directory for directory in directories if directory == root or root in directory.parents
    ]
    for directory in sorted(contained, key=lambda item: len(item.parts), reverse=True):
        # Process sorted, contained and parts inside the bounded remove verified tree
        # loop.
        if directory.exists():
            directory.rmdir()
    return deleted_bytes


def records_from_json(value: object) -> tuple[FileRecord, ...]:
    # Execute the records from json workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise SafeFilesystemError("file inventory must be a list")
    records: list[FileRecord] = []
    for raw in value:
        # Process value inside the bounded records from json loop.
        if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "size"}:
            raise SafeFilesystemError("file inventory entry schema is invalid")
        path = raw["path"]
        digest = raw["sha256"]
        size = raw["size"]
        # Evaluate the complete records from json isinstance, size and path condition
        # before guarded effects.
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            # Keep isinstance visible while evaluating the isinstance, size and path
            # guard.
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise SafeFilesystemError("file inventory entry is invalid")
        # Invoke safe_relative_path for path as a visible records from json step.
        safe_relative_path(path)
        records.append(FileRecord(path=path, sha256=digest, size=size))
    ordered = tuple(sorted(records, key=lambda item: item.path))
    if tuple(records) != ordered or len({record.path for record in ordered}) != len(ordered):
        raise SafeFilesystemError("file inventory must be sorted and unique")
    # Return the completed records from json result without a hidden fallback.
    return ordered


def _sha256_file(path: Path) -> tuple[str, int]:
    # Execute the sha256 file workflow in explicit, reviewable steps.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        # Perform the protected sha256 file operation before explicit failure handling.
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SafeFilesystemError("inventory member is not a single-link regular file")
        digest = hashlib.sha256()
        size = 0
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
        return digest.hexdigest(), size
    finally:
        # Handle the cleanup path after the protected sha256 file operation.
        if descriptor >= 0:
            os.close(descriptor)


def _copy_regular(source: Path, destination: Path) -> None:
    # Execute the copy regular workflow in explicit, reviewable steps.
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        # Keep the os getattr step visible while building destination flags.
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    source_descriptor = os.open(source, source_flags)
    destination_descriptor = os.open(destination, destination_flags, 0o600)
    # Keep expected failures inside the copy regular error boundary.
    try:
        # Perform the protected copy regular operation before explicit failure handling.
        metadata = os.fstat(source_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SafeFilesystemError("copy source is not a single-link regular file")
        source_stream = cast(IO[bytes], os.fdopen(source_descriptor, "rb", buffering=0))
        destination_stream = cast(IO[bytes], os.fdopen(destination_descriptor, "wb", buffering=0))
        # Assemble source descriptor once so the copy regular workflow shares one value.
        source_descriptor = -1
        destination_descriptor = -1
        with source_stream, destination_stream:
            # Keep source stream active only for the bounded copy regular operation.
            while block := source_stream.read(1024 * 1024):
                destination_stream.write(block)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())
    finally:
        # Handle the cleanup path after the protected copy regular operation.
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if destination_descriptor >= 0:
            os.close(destination_descriptor)


__all__ = [
    # Keep the file record component named inside the all contract.
    "FileRecord",
    "SafeFilesystemError",
    "canonical_json",
    "copy_tree_verified",
    "ensure_real_directory",
    # Keep the file records component named inside the all contract.
    "file_records",
    "fsync_directory",
    "parse_canonical_object",
    "publish_no_replace",
    "read_regular",
    # Keep the records digest component named inside the all contract.
    "records_digest",
    "records_from_json",
    "remove_verified_tree",
    "require_real_directory",
    "safe_relative_path",
    # Keep the sha256 bytes component named inside the all contract.
    "sha256_bytes",
    "write_durable_exclusive",
]
