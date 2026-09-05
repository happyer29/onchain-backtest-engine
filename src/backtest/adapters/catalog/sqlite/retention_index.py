"""Rebuildable SQLite projection of filesystem-authoritative pin records."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from backtest.adapters.catalog.sqlite.errors import QueueCorruptionError

# Import schema at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.schema import connect, initialize
from backtest.adapters.catalog.sqlite.serialization import deserialize_job_spec
from backtest.application.retention import (
    PinRecord,
    RetentionConflictError,
    RetentionIntegrityError,
    # Close the retention import after its required symbols are visible.
)
from backtest.domain.identifiers import ArtifactId


# Keep the sqlite retention index contract and validation rules together.
class SQLiteRetentionIndex:
    def __init__(
        self,
        path: Path,
        *,
        # Keep the busy timeout seconds input explicit in the init contract.
        busy_timeout_seconds: float = 5.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the sqlite retention index init workflow in explicit, reviewable steps.
        self._path = path
        self._busy_timeout_seconds = busy_timeout_seconds
        self._clock_ns = clock_ns
        initialize(path, busy_timeout_seconds=busy_timeout_seconds)

    def index_active(self, pin: PinRecord) -> None:
        # Execute the sqlite retention index index active workflow in explicit, reviewable
        # steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite retention index index active operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_digest FROM pins WHERE pin_id = ?",
                (pin.pin_id.value,),
            ).fetchone()
            # Evaluate the complete sqlite retention index index active row, hex and
            # record digest condition before guarded effects.
            if row is not None and str(row["record_digest"]) != pin.record_digest.hex:
                raise RetentionConflictError("SQLite pin identity maps to a different checksum")
            connection.execute(
                """
                INSERT INTO pins (pin_id, record_digest, status, reason, indexed_at_ns)
                VALUES (?, ?, 'ACTIVE', ?, ?)
                ON CONFLICT(pin_id) DO UPDATE SET
                    record_digest = excluded.record_digest,
                    status = 'ACTIVE',
                    reason = excluded.reason,
                    indexed_at_ns = excluded.indexed_at_ns
                """,
                (
                    # Pass pin explicitly so execute receives a reviewable value and hex
                    # input in sqlite retention index index active.
                    pin.pin_id.value,
                    pin.record_digest.hex,
                    pin.reason,
                    self._clock_ns(),
                ),
                # Complete execute only after its value and hex inputs are visible in sqlite
                # retention index index active.
            )
            connection.execute("DELETE FROM pin_roots WHERE pin_id = ?", (pin.pin_id.value,))
            connection.executemany(
                """
                INSERT INTO pin_roots (pin_id, artifact_id, ordinal)
                VALUES (?, ?, ?)
                """,
                ((pin.pin_id.value, root.hex, ordinal) for ordinal, root in enumerate(pin.roots)),
                # Complete executemany only after its value and hex inputs are visible in
                # sqlite retention index index active.
            )
            connection.execute("COMMIT")
        except BaseException:
            # Translate the BaseException failure through the sqlite retention index index
            # active boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # Define sqlite retention index index retired as one focused operation with an
    # explicit boundary.
    def index_retired(self, pin: PinRecord) -> None:
        # Execute the sqlite retention index index retired workflow in explicit,
        # reviewable steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite retention index index retired operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT record_digest FROM pins WHERE pin_id = ?",
                (pin.pin_id.value,),
            ).fetchone()
            # Evaluate the complete sqlite retention index index retired row, hex and
            # record digest condition before guarded effects.
            if row is not None and str(row["record_digest"]) != pin.record_digest.hex:
                raise RetentionConflictError("SQLite pin identity maps to a different checksum")
            connection.execute(
                """
                INSERT INTO pins (pin_id, record_digest, status, reason, indexed_at_ns)
                VALUES (?, ?, 'RETIRED', ?, ?)
                ON CONFLICT(pin_id) DO UPDATE SET
                    status = 'RETIRED', indexed_at_ns = excluded.indexed_at_ns
                """,
                (
                    # Pass pin explicitly so execute receives a reviewable value and hex
                    # input in sqlite retention index index retired.
                    pin.pin_id.value,
                    pin.record_digest.hex,
                    pin.reason,
                    self._clock_ns(),
                ),
                # Complete execute only after its value and hex inputs are visible in sqlite
                # retention index index retired.
            )
            connection.execute("COMMIT")
        except BaseException:
            # Translate the BaseException failure through the sqlite retention index index
            # retired boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # Define sqlite retention index rebuild as one focused operation with an explicit
    # boundary.
    def rebuild(self, active_pins: tuple[PinRecord, ...]) -> None:
        # Execute the sqlite retention index rebuild workflow in explicit, reviewable
        # steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite retention index rebuild operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM pin_roots")
            connection.execute("DELETE FROM pins")
            now_ns = self._clock_ns()
            for pin in active_pins:
                # Process active_pins inside the bounded sqlite retention index rebuild
                # loop.
                connection.execute(
                    """
                    INSERT INTO pins (pin_id, record_digest, status, reason, indexed_at_ns)
                    VALUES (?, ?, 'ACTIVE', ?, ?)
                    """,
                    (pin.pin_id.value, pin.record_digest.hex, pin.reason, now_ns),
                )
                connection.executemany(
                    # Keep executemany, connection and value visible while completing
                    # executemany within sqlite retention index rebuild.
                    """
                    INSERT INTO pin_roots (pin_id, artifact_id, ordinal)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (pin.pin_id.value, root.hex, ordinal)
                        for ordinal, root in enumerate(pin.roots)
                    ),
                    # Complete executemany only after its value and hex inputs are visible in
                    # sqlite retention index rebuild.
                )
            connection.execute("COMMIT")
        except BaseException:
            # Translate the BaseException failure through the sqlite retention index
            # rebuild boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # Define sqlite retention index connect as one focused operation with an explicit
    # boundary.
    def _connect(self) -> sqlite3.Connection:
        return connect(self._path, busy_timeout_seconds=self._busy_timeout_seconds)


class SQLiteRetentionRootProvider:
    """Reads live job inputs and successful outputs from authoritative job state."""

    def __init__(self, path: Path, *, busy_timeout_seconds: float = 5.0) -> None:
        # Execute the sqlite retention root provider init workflow in explicit, reviewable
        # steps.
        self._path = path
        self._busy_timeout_seconds = busy_timeout_seconds
        initialize(path, busy_timeout_seconds=busy_timeout_seconds)

    def retained_roots(self) -> tuple[ArtifactId, ...]:
        # Execute the sqlite retention root provider retained roots workflow in explicit,
        # reviewable steps.
        connection = connect(self._path, busy_timeout_seconds=self._busy_timeout_seconds)
        try:
            # Perform the protected sqlite retention root provider retained roots
            # operation before explicit failure handling.
            output_rows = connection.execute(
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
            live_job_rows = connection.execute(
                """
                SELECT resolved_spec
                FROM jobs
                WHERE state IN ('QUEUED', 'STARTING', 'RUNNING')
                ORDER BY job_id
                """
            ).fetchall()
            roots = {str(row["artifact_id"]) for row in output_rows}
            for row in live_job_rows:
                spec = deserialize_job_spec(bytes(row["resolved_spec"]))
                roots.update(artifact_id.hex for artifact_id in spec.input_artifact_ids)
            return tuple(ArtifactId(value) for value in sorted(roots))
        except (sqlite3.Error, QueueCorruptionError, TypeError, ValueError) as error:
            # Translate the (sqlite3.Error, TypeError, ValueError) failure through the
            # sqlite retention root provider retained roots boundary.
            raise RetentionIntegrityError(
                "SQLite retained-root projection is corrupt or unavailable"
            ) from error
        finally:
            connection.close()


# Bind all once as an explicit module-level contract.
__all__ = ["SQLiteRetentionIndex", "SQLiteRetentionRootProvider"]
