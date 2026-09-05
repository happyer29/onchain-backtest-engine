"""Consistent SQLite backup checkpoints for authoritative local job state."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path

from backtest.adapters.catalog.sqlite.schema import (
    LATEST_SCHEMA_VERSION,
    connect,
    # Include schema version so the schema dependency remains explicit.
    schema_version,
)
from backtest.application.backups import BackupIntegrityError
from backtest.domain.identifiers import ArtifactId, ContentDigest


# Keep the sqlite checkpoint contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SQLiteCheckpoint:
    path: Path
    digest: ContentDigest
    successful_roots: tuple[ArtifactId, ...]
    # Declare schema version explicitly in the sqlite checkpoint contract.
    schema_version: int
    size_bytes: int


class SQLiteCheckpointRepository:
    """Uses ``sqlite3_backup`` rather than copying a live WAL database file."""

    def __init__(self, source_path: Path, *, busy_timeout_seconds: float = 5.0) -> None:
        # Execute the sqlite checkpoint repository init workflow in explicit, reviewable
        # steps.
        self._source_path = source_path
        self._busy_timeout_seconds = busy_timeout_seconds

    def create_checkpoint(self, destination: Path) -> SQLiteCheckpoint:
        # Execute the sqlite checkpoint repository create checkpoint workflow in explicit,
        # reviewable steps.
        self._require_database_file(self._source_path, label="source catalog")
        version = schema_version(
            self._source_path,
            busy_timeout_seconds=self._busy_timeout_seconds,
        )
        # Guard this path with version != LATEST_SCHEMA_VERSION before applying effects.
        if version != LATEST_SCHEMA_VERSION:
            # Handle the sqlite checkpoint repository create checkpoint version !=
            # LATEST_SCHEMA_VERSION branch as a distinct logical block.
            raise BackupIntegrityError(
                "backup requires the current catalog schema; migrate under normal startup first"
            )
        if destination.exists():
            raise BackupIntegrityError("SQLite checkpoint destination already exists")
        # Assemble source once so the sqlite checkpoint repository create checkpoint
        # workflow shares one value.
        source = connect(
            self._source_path,
            busy_timeout_seconds=self._busy_timeout_seconds,
        )
        try:
            # Perform the protected sqlite checkpoint repository create checkpoint
            # operation before explicit failure handling.
            target = sqlite3.connect(destination, isolation_level=None)
            try:
                # Perform the protected sqlite checkpoint repository create checkpoint
                # operation before explicit failure handling.
                self._verify_connection(source, label="source catalog")
                source.backup(target)
                # Make the checkpoint a single immutable file, independent of a
                # source WAL or sidecar files.
                mode = target.execute("PRAGMA journal_mode = DELETE").fetchone()
                if mode is None or str(mode[0]).lower() != "delete":
                    raise BackupIntegrityError("SQLite checkpoint is not self-contained")
                target.execute("PRAGMA synchronous = FULL")
                self._verify_connection(target, label="SQLite checkpoint")
            # Complete the required cleanup regardless of the protected outcome.
            finally:
                target.close()
        finally:
            source.close()
        self._require_database_file(destination, label="SQLite checkpoint")
        # Assemble (digest, size) once so the sqlite checkpoint repository create
        # checkpoint workflow shares one value.
        digest, size = _sha256_file(destination)
        roots = self.successful_roots(destination)
        return SQLiteCheckpoint(
            path=destination,
            digest=ContentDigest(digest),
            # Pass successful roots explicitly so SQLiteCheckpoint receives a reviewable
            # content digest and destination input in sqlite checkpoint repository create
            # checkpoint.
            successful_roots=roots,
            schema_version=version,
            size_bytes=size,
        )

    def verify_checkpoint(
        # Keep the remaining verify checkpoint inputs visible at the sqlite checkpoint
        # repository verify checkpoint boundary.
        self,
        path: Path,
        *,
        expected_digest: ContentDigest,
    ) -> tuple[ArtifactId, ...]:
        # Execute the sqlite checkpoint repository verify checkpoint workflow in explicit,
        # reviewable steps.
        self._require_database_file(path, label="restored SQLite checkpoint")
        actual_digest, _ = _sha256_file(path)
        if actual_digest != expected_digest.hex:
            raise BackupIntegrityError("restored SQLite checkpoint checksum mismatch")
        version = schema_version(path, busy_timeout_seconds=self._busy_timeout_seconds)
        # Guard this path with version > LATEST_SCHEMA_VERSION before applying effects.
        if version > LATEST_SCHEMA_VERSION:
            raise BackupIntegrityError("backup catalog schema is newer than this runtime")
        if version != LATEST_SCHEMA_VERSION:
            raise BackupIntegrityError("backup catalog schema is not the declared current schema")
        connection = connect(path, busy_timeout_seconds=self._busy_timeout_seconds)
        # Keep expected failures inside the sqlite checkpoint repository verify checkpoint
        # error boundary.
        try:
            self._verify_connection(connection, label="restored SQLite checkpoint")
        finally:
            connection.close()
        return self.successful_roots(path)

    # Define sqlite checkpoint repository successful roots as one focused operation with
    # an explicit boundary.
    def successful_roots(self, path: Path) -> tuple[ArtifactId, ...]:
        # Execute the sqlite checkpoint repository successful roots workflow in explicit,
        # reviewable steps.
        connection = connect(path, busy_timeout_seconds=self._busy_timeout_seconds)
        try:
            # Perform the protected sqlite checkpoint repository successful roots
            # operation before explicit failure handling.
            rows = connection.execute(
                """
                SELECT result_artifact_id AS artifact_id
                FROM job_attempts
                WHERE state = 'SUCCEEDED' AND result_artifact_id IS NOT NULL
                UNION
                SELECT artifact_id
                FROM completion_receipt_outputs
                ORDER BY artifact_id
                """
            ).fetchall()
        except sqlite3.Error as error:
            # Translate the sqlite3.Error failure through the sqlite checkpoint repository
            # successful roots boundary.
            raise BackupIntegrityError(
                "catalog cannot enumerate successful artifact roots"
            ) from error
        finally:
            connection.close()
        # Keep expected failures inside the sqlite checkpoint repository successful roots
        # error boundary.
        try:
            return tuple(ArtifactId(str(row["artifact_id"])) for row in rows)
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the sqlite checkpoint
            # repository successful roots boundary.
            raise BackupIntegrityError(
                "catalog contains an invalid successful artifact ID"
            ) from error

    @staticmethod
    def _verify_connection(connection: sqlite3.Connection, *, label: str) -> None:
        # Execute the sqlite checkpoint repository verify connection workflow in explicit,
        # reviewable steps.
        integrity = connection.execute("PRAGMA quick_check").fetchall()
        if len(integrity) != 1 or str(integrity[0][0]).lower() != "ok":
            raise BackupIntegrityError(f"{label} failed SQLite integrity verification")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupIntegrityError(f"{label} failed foreign-key verification")

    # Apply staticmethod semantics to the following sqlite checkpoint repository require
    # database file contract.
    @staticmethod
    def _require_database_file(path: Path, *, label: str) -> None:
        # Execute the sqlite checkpoint repository require database file workflow in
        # explicit, reviewable steps.
        try:
            metadata = path.lstat()
        except OSError as error:
            raise BackupIntegrityError(f"{label} is unavailable") from error
        if (
            # Keep stat visible while evaluating the s islnk, st mode and st nlink guard.
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise BackupIntegrityError(f"{label} must be a single-link regular file")


# Define sha256 file as one focused operation with an explicit boundary.
def _sha256_file(path: Path) -> tuple[str, int]:
    # Execute the sha256 file workflow in explicit, reviewable steps.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        # Perform the protected sha256 file operation before explicit failure handling.
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BackupIntegrityError("SQLite checkpoint is not a single-link regular file")
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


__all__ = ["SQLiteCheckpoint", "SQLiteCheckpointRepository"]
