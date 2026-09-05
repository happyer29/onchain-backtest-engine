"""Verified, rebuildable SQLite index for committed local artifacts."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress

# Run timestamps are normalized without floating-point epoch conversion.
from datetime import UTC, datetime

# Import pathlib at the visible module dependency boundary.
from pathlib import Path

from backtest.adapters.catalog.sqlite.schema import connect, initialize
from backtest.application.catalog_models import (
    ArtifactCatalogStatus,
    ArtifactCatalogVerificationError,
    ArtifactInventory,
    # Include build key collision error so the catalog models dependency remains explicit.
    BuildKeyCollisionError,
    CatalogRebuildReport,
    RunIndexEntry,
)
from backtest.application.errors import ApplicationError
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.artifacts import ArtifactRepository
from backtest.application.ports.catalog import RunListCursor
from backtest.application.run_results import (
    MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
    successful_run_manifest_from_bytes,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    # Run projection checks both experiment and physical-attempt identity.
    ExecutionAttemptId,
    LogicalRunId,
)

_COLLISION_REASON = "same build key resolved to different committed content IDs"
# One extra row is reserved for application-level continuation lookahead.
_MAX_RUN_QUERY_ROWS = 1_001
# Legacy CLI offsets cannot trigger effectively unbounded SQLite scans.
_MAX_RUN_QUERY_OFFSET = 10_000


class SQLiteArtifactCatalog:
    """An index that re-verifies filesystem authority before every successful lookup."""

    def __init__(
        self,
        path: Path,
        repository: ArtifactRepository,
        *,
        # Keep the busy timeout seconds input explicit in the init contract.
        busy_timeout_seconds: float = 5.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the sqlite artifact catalog init workflow in explicit, reviewable steps.
        if busy_timeout_seconds <= 0:
            raise ValueError("busy_timeout_seconds must be positive")
        self._path = path
        self._repository = repository
        self._busy_timeout_seconds = busy_timeout_seconds
        # Assemble self clock ns once so the sqlite artifact catalog init workflow shares
        # one value.
        self._clock_ns = clock_ns
        initialize(path, busy_timeout_seconds=busy_timeout_seconds)

    def find_committed(self, artifact_id: ArtifactId) -> CommittedArtifact | None:
        # Execute the sqlite artifact catalog find committed workflow in explicit,
        # reviewable steps.
        expected = self._indexed_verified_descriptor(artifact_id)
        if expected is None:
            # Read paths never repair/rebuild SQLite. The held controller
            # explicitly indexes direct/child outputs or performs startup
            # reconciliation; another CLI process must remain read-only.
            return None
        verified = self._verify_filesystem(expected)
        self._verify_lineage(verified)
        # A build-key collision may have been committed while filesystem hashes
        # were checked.  Re-read the short-lived index state before returning.
        current = self._indexed_verified_descriptor(artifact_id)
        if current is None:
            return None
        if current != verified:
            # Handle the sqlite artifact catalog find committed current != verified branch
            # as a distinct logical block.
            raise ArtifactCatalogVerificationError(
                "artifact index changed during filesystem verification"
            )
        return verified

    def find_by_build_key(self, build_key: ContentDigest) -> CommittedArtifact | None:
        # Execute the sqlite artifact catalog find by build key workflow in explicit,
        # reviewable steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite artifact catalog find by build key operation
            # before explicit failure handling.
            row = connection.execute(
                """
                SELECT artifact_id
                FROM build_key_mapping
                WHERE build_key = ? AND status = 'VERIFIED'
                """,
                (build_key.hex,),
            ).fetchone()
        finally:
            # Invoke close as a visible step within the sqlite artifact catalog find by
            # build key workflow.
            connection.close()
        if row is None:
            return None
        try:
            artifact_id = ArtifactId(str(row["artifact_id"]))
        # Translate type error through the sqlite artifact catalog find by build key
        # boundary without hiding other errors.
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the sqlite artifact
            # catalog find by build key boundary.
            raise ArtifactCatalogVerificationError(
                "build-key mapping contains an invalid artifact ID"
            ) from error
        artifact = self.find_committed(artifact_id)
        if artifact is None:
            # Return explicit absence from the sqlite artifact catalog find by build key
            # path.
            return None
        if artifact.build_key.hex != build_key.hex:
            # Handle the sqlite artifact catalog find by build key hex, build key and
            # artifact condition as a distinct block.
            raise ArtifactCatalogVerificationError(
                "build-key mapping disagrees with verified artifact descriptor"
            )
        return artifact

    def index_committed(self, artifact: CommittedArtifact) -> None:
        # Execute the sqlite artifact catalog index committed workflow in explicit,
        # reviewable steps.
        verified = self._verify_filesystem(artifact, verify_inputs=True)
        # Parse bounded Run metadata before opening the SQLite writer transaction.
        run_entry = self._run_index_entry(verified) if verified.kind is ArtifactKind.RUN else None
        collision: BuildKeyCollisionError | None = None
        connection = self._connect()
        try:
            # Perform the protected sqlite artifact catalog index committed operation
            # before explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            # Incremental writes may extend only a previously complete projection.
            self._require_run_index_complete(connection)
            now_ns = self._clock_ns()
            self._upsert_exact_artifact(connection, verified, now_ns=now_ns)
            mapping = connection.execute(
                """
                SELECT artifact_id, status
                FROM build_key_mapping
                WHERE build_key = ?
                """,
                # Open the declared payload explicitly for fetchone within sqlite artifact
                # catalog index committed.
                (verified.build_key.hex,),
            ).fetchone()
            if mapping is None:
                # Handle the sqlite artifact catalog index committed mapping is None
                # branch as a distinct logical block.
                connection.execute(
                    """
                    INSERT INTO build_key_mapping (
                        build_key, artifact_id, status,
                        first_seen_at_ns, updated_at_ns
                    ) VALUES (?, ?, 'VERIFIED', ?, ?)
                    """,
                    (
                        verified.build_key.hex,
                        verified.artifact_id.hex,
                        # Pass now ns explicitly so execute receives a reviewable hex and
                        # build key input in sqlite artifact catalog index committed.
                        now_ns,
                        now_ns,
                    ),
                )
            # Handle the sqlite artifact catalog index committed complement of mapping is
            # None explicitly.
            elif (
                str(mapping["status"]) == "VERIFIED"
                and str(mapping["artifact_id"]) == verified.artifact_id.hex
            ):
                pass
            # Route all remaining cases through the explicit alternative branch.
            else:
                # Handle the sqlite artifact catalog index committed complement of
                # verified, hex and artifact id explicitly.
                mapped_id = ArtifactId(str(mapping["artifact_id"]))
                conflict_ids = self._record_collision(
                    connection,
                    build_key=verified.build_key,
                    artifact_ids=(mapped_id, verified.artifact_id),
                    # Pass detected at ns explicitly so _record_collision receives a
                    # reviewable build key and artifact id input in sqlite artifact
                    # catalog index committed.
                    detected_at_ns=now_ns,
                )
                collision = BuildKeyCollisionError(verified.build_key, conflict_ids)
            # Index ordering metadata only while the exact artifact remains verified.
            if collision is None:
                self._upsert_run_entry(connection, verified, run_entry)
            # Row triggers keep the projection dirty until all structural checks pass.
            self._mark_run_index_complete(connection)
            connection.execute("COMMIT")
        except BaseException:
            # Translate the BaseException failure through the sqlite artifact catalog
            # index committed boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        # Guard this path with collision is not None before applying effects.
        if collision is not None:
            raise collision

    def lineage_inputs(self, artifact_id: ArtifactId) -> tuple[ArtifactId, ...]:
        # Execute the sqlite artifact catalog lineage inputs workflow in explicit,
        # reviewable steps.
        artifact = self.find_committed(artifact_id)
        if artifact is None:
            return ()
        return artifact.input_artifact_ids

    def list_committed(
        # Keep the remaining list committed inputs visible at the sqlite artifact catalog
        # list committed boundary.
        self,
        *,
        kind: ArtifactKind | None,
        limit: int,
        offset: int,
        # Keep the tuple input explicit in the list committed contract.
    ) -> tuple[CommittedArtifact, ...]:
        """Return a bounded page, re-verifying every filesystem descriptor."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("catalog page limit must be between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("catalog page offset must be non-negative")
        connection = self._connect()
        # Keep expected failures inside the sqlite artifact catalog list committed error
        # boundary.
        try:
            # Perform the protected sqlite artifact catalog list committed operation
            # before explicit failure handling.
            if kind is None:
                # Handle the sqlite artifact catalog list committed kind is None branch as
                # a distinct logical block.
                rows = connection.execute(
                    """
                    SELECT artifact_id
                    FROM artifact_index
                    WHERE status = 'VERIFIED'
                    ORDER BY indexed_at_ns DESC, artifact_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            else:
                # Handle the sqlite artifact catalog list committed complement of kind is
                # None explicitly.
                rows = connection.execute(
                    """
                    SELECT artifact_id
                    FROM artifact_index
                    WHERE status = 'VERIFIED' AND kind = ?
                    ORDER BY indexed_at_ns DESC, artifact_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (kind.value, limit, offset),
                ).fetchall()
        finally:
            # Invoke close as a visible step within the sqlite artifact catalog list
            # committed workflow.
            connection.close()
        result: list[CommittedArtifact] = []
        for row in rows:
            # Process rows inside the bounded sqlite artifact catalog list committed loop.
            try:
                artifact_id = ArtifactId(str(row["artifact_id"]))
            except (TypeError, ValueError) as error:
                # Translate the (TypeError, ValueError) failure through the sqlite
                # artifact catalog list committed boundary.
                raise ArtifactCatalogVerificationError(
                    "artifact page contains an invalid content ID"
                ) from error
            artifact = self.find_committed(artifact_id)
            if artifact is None:
                # Handle the sqlite artifact catalog list committed artifact is None
                # branch as a distinct logical block.
                raise ArtifactCatalogVerificationError(
                    "artifact changed classification while listing the verified page"
                )
            result.append(artifact)
        return tuple(result)

    def list_runs(
        self,
        *,
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]:
        """Return one globally newest-first Run page from the rebuildable projection."""

        return self._list_run_entries(
            logical_run_id=None,
            limit=limit,
            offset=offset,
            after=after,
        )

    def list_logical_runs(
        self,
        logical_run_id: LogicalRunId,
        *,
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]:
        """Return one newest-first page for an exact logical experiment identity."""

        return self._list_run_entries(
            logical_run_id=logical_run_id,
            limit=limit,
            offset=offset,
            after=after,
        )

    # Define sqlite artifact catalog rebuild index as one focused operation with an
    # explicit boundary.
    def rebuild_index(
        self,
        artifacts: Iterable[CommittedArtifact],
    ) -> CatalogRebuildReport:
        """Replace rebuildable artifact tables from fully verified descriptors."""

        by_id: dict[str, CommittedArtifact] = {}
        for candidate in artifacts:
            # Process artifacts inside the bounded sqlite artifact catalog rebuild index
            # loop.
            verified = self._verify_filesystem(candidate, verify_inputs=True)
            previous = by_id.setdefault(verified.artifact_id.hex, verified)
            if previous != verified:
                # Handle the sqlite artifact catalog rebuild index previous != verified
                # branch as a distinct logical block.
                raise ArtifactCatalogVerificationError(
                    "one artifact ID was supplied with different descriptors"
                )

        ordered = tuple(by_id[key] for key in sorted(by_id))
        # Parse every bounded manifest before any old rebuildable row is removed.
        run_entries: dict[str, RunIndexEntry | None] = {}
        for artifact in ordered:
            # Every Run gets either searchable metadata or an explicit exclusion row.
            if artifact.kind is ArtifactKind.RUN:
                run_entries[artifact.artifact_id.hex] = self._run_index_entry(artifact)
        by_build_key: dict[str, list[CommittedArtifact]] = defaultdict(list)
        # Traverse ordered explicitly so each sqlite artifact catalog rebuild index
        # iteration remains traceable.
        for artifact in ordered:
            by_build_key[artifact.build_key.hex].append(artifact)
        conflict_keys = {
            build_key
            for build_key, grouped_artifacts in by_build_key.items()
            # Keep the grouped artifacts len step visible while building conflict keys.
            if len(grouped_artifacts) > 1
        }
        quarantined_count = sum(len(by_build_key[build_key]) for build_key in conflict_keys)

        connection = self._connect()
        try:
            # Perform the protected sqlite artifact catalog rebuild index operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            # A crash rolls this marker back together with all replacement rows.
            connection.execute(
                "UPDATE run_index_state SET status = 'DIRTY', generation = generation + 1 "
                "WHERE singleton = 1"
            )
            connection.execute("DELETE FROM artifact_build_conflicts")
            connection.execute("DELETE FROM build_key_mapping")
            connection.execute("DELETE FROM lineage_edges")
            connection.execute("DELETE FROM run_index")
            connection.execute("DELETE FROM artifact_index")
            # Assemble now ns once so the sqlite artifact catalog rebuild index workflow
            # shares one value.
            now_ns = self._clock_ns()
            for artifact in ordered:
                # Process ordered inside the bounded sqlite artifact catalog rebuild index
                # loop.
                status = (
                    ArtifactCatalogStatus.QUARANTINED
                    if artifact.build_key.hex in conflict_keys
                    else ArtifactCatalogStatus.VERIFIED
                )
                # Invoke _insert_artifact for verified and connection as a visible sqlite
                # artifact catalog rebuild index step.
                self._insert_artifact(
                    connection,
                    artifact,
                    status=status,
                    reason=_COLLISION_REASON
                    # Pass status explicitly so _insert_artifact receives a reviewable
                    # verified and connection input in sqlite artifact catalog rebuild
                    # index.
                    if status is not ArtifactCatalogStatus.VERIFIED
                    else None,
                    now_ns=now_ns,
                )
                # Quarantined Runs receive no row; verified legacy Runs are explicit.
                if status is ArtifactCatalogStatus.VERIFIED and artifact.kind is ArtifactKind.RUN:
                    self._insert_run_projection(
                        connection,
                        artifact,
                        run_entries[artifact.artifact_id.hex],
                    )
            for build_key in sorted(by_build_key):
                # Process sorted(by_build_key) inside the bounded sqlite artifact catalog
                # rebuild index loop.
                group = sorted(
                    by_build_key[build_key],
                    key=lambda item: item.artifact_id.hex,
                )
                mapping_status = "CONFLICT" if build_key in conflict_keys else "VERIFIED"
                # Invoke execute for hex and artifact id as a visible sqlite artifact
                # catalog rebuild index step.
                connection.execute(
                    """
                    INSERT INTO build_key_mapping (
                        build_key, artifact_id, status,
                        first_seen_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        build_key,
                        group[0].artifact_id.hex,
                        # Pass mapping status explicitly so execute receives a reviewable
                        # hex and artifact id input in sqlite artifact catalog rebuild
                        # index.
                        mapping_status,
                        now_ns,
                        now_ns,
                    ),
                )
                # Guard this path with mapping_status == 'CONFLICT' before applying
                # effects.
                if mapping_status == "CONFLICT":
                    # Handle the sqlite artifact catalog rebuild index mapping_status ==
                    # 'CONFLICT' branch as a distinct logical block.
                    connection.executemany(
                        """
                        INSERT INTO artifact_build_conflicts (
                            build_key, artifact_id, detected_at_ns
                        ) VALUES (?, ?, ?)
                        """,
                        ((build_key, artifact.artifact_id.hex, now_ns) for artifact in group),
                    )
            # Publish searchable ordering only after every Run row and mapping agrees.
            self._mark_run_index_complete(connection)
            connection.execute("COMMIT")
        # Translate base exception through the sqlite artifact catalog rebuild index
        # boundary without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the sqlite artifact catalog
            # rebuild index boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        # Return the completed sqlite artifact catalog rebuild index result without a
        # hidden fallback.
        return CatalogRebuildReport(
            indexed_artifacts=len(ordered),
            quarantined_artifacts=quarantined_count,
            conflicting_build_keys=len(conflict_keys),
        )

    def begin_reconciliation_session(self, inventory: ArtifactInventory) -> bool:
        """Mark startup unclean and return whether payload re-hashing is avoidable."""

        connection = self._connect()
        try:
            # One writer transaction binds prior clean evidence to current catalog rows.
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT * FROM artifact_reconciliation_state WHERE singleton = 1"
            ).fetchone()
            reusable = (
                state is not None
                and str(state["status"]) == "CLEAN"
                and str(state["inventory_digest"]) == inventory.fingerprint.hex
                and int(state["artifact_count"]) == len(inventory.entries)
            )
            if reusable:
                reusable = self._inventory_matches_catalog(connection, inventory)
            # A crash after this commit forces the next controller to full-verify.
            changed = connection.execute(
                "UPDATE artifact_reconciliation_state SET status = 'UNCLEAN' WHERE singleton = 1"
            ).rowcount
            if changed != 1:
                raise ArtifactCatalogVerificationError(
                    "artifact reconciliation state is unavailable"
                )
            connection.execute("COMMIT")
            return reusable
        except BaseException:
            # Preserve the previous durable state when startup evidence cannot be read.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def finish_reconciliation_session(self, inventory: ArtifactInventory) -> bool:
        """Publish CLEAN only when cheap filesystem evidence matches every index row."""

        connection = self._connect()
        try:
            # Recheck under one writer snapshot before acknowledging a clean shutdown.
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT status FROM artifact_reconciliation_state WHERE singleton = 1"
            ).fetchone()
            consistent = state is not None and str(state["status"]) == "UNCLEAN"
            if consistent:
                consistent = self._inventory_matches_catalog(connection, inventory)
            if consistent:
                connection.execute(
                    """
                    UPDATE artifact_reconciliation_state
                    SET status = 'CLEAN', inventory_digest = ?, artifact_count = ?
                    WHERE singleton = 1
                    """,
                    (inventory.fingerprint.hex, len(inventory.entries)),
                )
            connection.execute("COMMIT")
            return consistent
        except BaseException:
            # A failed finish remains UNCLEAN and therefore cannot enable fast startup.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _inventory_matches_catalog(
        connection: sqlite3.Connection,
        inventory: ArtifactInventory,
    ) -> bool:
        """Prove cheap candidates equal the complete rebuildable catalog projection."""

        rows = connection.execute(
            """
            SELECT artifact_id, kind, manifest_digest, build_key, status,
                   status_reason, verified_at_ns
            FROM artifact_index
            ORDER BY artifact_id
            """
        ).fetchall()
        if len(rows) != len(inventory.entries):
            return False

        # Read lineage once so the check stays linear rather than querying per artifact.
        lineage_rows = connection.execute(
            """
            SELECT output_artifact_id, input_artifact_id, ordinal
            FROM lineage_edges
            ORDER BY output_artifact_id, ordinal
            """
        ).fetchall()
        lineage: dict[str, list[str]] = defaultdict(list)
        for row in lineage_rows:
            output_id = str(row["output_artifact_id"])
            expected_ordinal = len(lineage[output_id])
            if int(row["ordinal"]) != expected_ordinal:
                return False
            lineage[output_id].append(str(row["input_artifact_id"]))

        expected_by_id = {entry.descriptor.artifact_id.hex: entry for entry in inventory.entries}
        groups: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            artifact_id = str(row["artifact_id"])
            entry = expected_by_id.get(artifact_id)
            if entry is None:
                return False
            descriptor = entry.descriptor
            actual_identity = (
                artifact_id,
                str(row["kind"]),
                str(row["manifest_digest"]),
                str(row["build_key"]),
                tuple(lineage.pop(artifact_id, ())),
            )
            expected_identity = (
                descriptor.artifact_id.hex,
                descriptor.kind.value,
                descriptor.manifest_digest.hex,
                descriptor.build_key.hex,
                tuple(item.hex for item in descriptor.input_artifact_ids),
            )
            if actual_identity != expected_identity:
                return False
            # A file changed after its full verification cannot use metadata evidence.
            if int(row["verified_at_ns"]) < entry.latest_change_ns:
                return False
            groups[descriptor.build_key.hex].append(artifact_id)
        if lineage:
            return False

        # Recompute collision classification instead of trusting mutable SQLite labels.
        expected_mappings: list[tuple[str, str, str]] = []
        expected_conflicts: list[tuple[str, str]] = []
        row_by_id = {str(row["artifact_id"]): row for row in rows}
        for build_key in sorted(groups):
            artifact_ids = sorted(groups[build_key])
            conflict = len(artifact_ids) > 1
            expected_mappings.append(
                (build_key, artifact_ids[0], "CONFLICT" if conflict else "VERIFIED")
            )
            for artifact_id in artifact_ids:
                row = row_by_id[artifact_id]
                expected_status = "QUARANTINED" if conflict else "VERIFIED"
                expected_reason = _COLLISION_REASON if conflict else None
                if (str(row["status"]), row["status_reason"]) != (
                    expected_status,
                    expected_reason,
                ):
                    return False
                if conflict:
                    expected_conflicts.append((build_key, artifact_id))

        mappings = tuple(
            (str(row["build_key"]), str(row["artifact_id"]), str(row["status"]))
            for row in connection.execute(
                "SELECT build_key, artifact_id, status FROM build_key_mapping ORDER BY build_key"
            )
        )
        conflicts = tuple(
            (str(row["build_key"]), str(row["artifact_id"]))
            for row in connection.execute(
                "SELECT build_key, artifact_id FROM artifact_build_conflicts "
                "ORDER BY build_key, artifact_id"
            )
        )
        if mappings != tuple(expected_mappings) or conflicts != tuple(expected_conflicts):
            return False
        try:
            SQLiteArtifactCatalog._verify_run_index_completeness(connection)
        except ArtifactCatalogVerificationError:
            return False
        return True

    def _list_run_entries(
        self,
        *,
        logical_run_id: LogicalRunId | None,
        limit: int,
        offset: int,
        after: RunListCursor | None,
    ) -> tuple[RunIndexEntry, ...]:
        """Read one deterministic page after proving projection completeness."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("run index page limit must be an integer")
        if not 1 <= limit <= _MAX_RUN_QUERY_ROWS:
            raise ValueError("run index page limit must be between 1 and 1001")
        # A keyset and positional offset cannot describe one unambiguous page.
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("run index page offset must be an integer")
        if not 0 <= offset <= _MAX_RUN_QUERY_OFFSET:
            raise ValueError("run index page offset must be between 0 and 10000")
        if after is not None and (offset != 0 or after.logical_run_id != logical_run_id):
            raise ValueError("run cursor must match the scope and cannot use offset")

        try:
            connection = self._connect()
            try:
                # One SQLite snapshot binds COMPLETE, full structure and the page.
                connection.execute("BEGIN")
                try:
                    self._verify_run_index_completeness(connection)
                    rows = self._select_run_index_page(
                        connection,
                        logical_run_id=logical_run_id,
                        limit=limit,
                        offset=offset,
                        after=after,
                    )
                    connection.execute("COMMIT")
                except BaseException:
                    # Never leave the pooled read boundary transactionally ambiguous.
                    with suppress(sqlite3.Error):
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                    raise
            finally:
                connection.close()
        except sqlite3.Error as error:
            # SQLite details stay behind the typed catalog verification boundary.
            raise ArtifactCatalogVerificationError("run index query failed") from error

        try:
            # Strict DTO reconstruction catches malformed scalar SQLite values.
            return tuple(self._run_entry_from_row(row) for row in rows)
        except (TypeError, ValueError) as error:
            raise ArtifactCatalogVerificationError("run index contains invalid values") from error

    @staticmethod
    def _select_run_index_page(
        connection: sqlite3.Connection,
        *,
        logical_run_id: LogicalRunId | None,
        limit: int,
        offset: int,
        after: RunListCursor | None,
    ) -> Sequence[sqlite3.Row]:
        """Apply global order in SQLite before reading one bounded result page."""

        if logical_run_id is None and after is None:
            return connection.execute(
                """
                SELECT run_index.*
                FROM run_index
                JOIN artifact_index USING (artifact_id)
                JOIN build_key_mapping
                  ON build_key_mapping.build_key = artifact_index.build_key
                 AND build_key_mapping.artifact_id = artifact_index.artifact_id
                WHERE artifact_index.kind = 'RUN'
                  AND artifact_index.status = 'VERIFIED'
                  AND build_key_mapping.status = 'VERIFIED'
                  AND run_index.manifest_digest = artifact_index.manifest_digest
                  AND run_index.is_queryable = 1
                ORDER BY run_index.completed_at_ns DESC, run_index.artifact_id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        if logical_run_id is None:
            # Mixed-direction keyset matches completion DESC then artifact ID ASC.
            assert after is not None
            return connection.execute(
                """
                SELECT run_index.*
                FROM run_index
                JOIN artifact_index USING (artifact_id)
                JOIN build_key_mapping
                  ON build_key_mapping.build_key = artifact_index.build_key
                 AND build_key_mapping.artifact_id = artifact_index.artifact_id
                WHERE artifact_index.kind = 'RUN'
                  AND artifact_index.status = 'VERIFIED'
                  AND build_key_mapping.status = 'VERIFIED'
                  AND run_index.manifest_digest = artifact_index.manifest_digest
                  AND run_index.is_queryable = 1
                  AND (run_index.completed_at_ns < ?
                   OR (run_index.completed_at_ns = ? AND run_index.artifact_id > ?))
                ORDER BY run_index.completed_at_ns DESC, run_index.artifact_id ASC
                LIMIT ?
                """,
                (
                    after.completed_at_ns,
                    after.completed_at_ns,
                    after.artifact_id.hex,
                    limit,
                ),
            ).fetchall()

        # Logical filtering precedes LIMIT/OFFSET and preserves the same global order.
        if after is None:
            return connection.execute(
                """
                SELECT run_index.*
                FROM run_index
                JOIN artifact_index USING (artifact_id)
                JOIN build_key_mapping
                  ON build_key_mapping.build_key = artifact_index.build_key
                 AND build_key_mapping.artifact_id = artifact_index.artifact_id
                WHERE artifact_index.kind = 'RUN'
                  AND artifact_index.status = 'VERIFIED'
                  AND build_key_mapping.status = 'VERIFIED'
                  AND run_index.manifest_digest = artifact_index.manifest_digest
                  AND run_index.is_queryable = 1
                  AND run_index.logical_run_id = ?
                ORDER BY run_index.completed_at_ns DESC, run_index.artifact_id ASC
                LIMIT ? OFFSET ?
                """,
                (logical_run_id.hex, limit, offset),
            ).fetchall()

        # The exact logical ID is part of both cursor scope and indexed predicate.
        return connection.execute(
            """
            SELECT run_index.*
            FROM run_index
            JOIN artifact_index USING (artifact_id)
            JOIN build_key_mapping
              ON build_key_mapping.build_key = artifact_index.build_key
             AND build_key_mapping.artifact_id = artifact_index.artifact_id
            WHERE artifact_index.kind = 'RUN'
              AND artifact_index.status = 'VERIFIED'
              AND build_key_mapping.status = 'VERIFIED'
              AND run_index.manifest_digest = artifact_index.manifest_digest
              AND run_index.is_queryable = 1
              AND run_index.logical_run_id = ?
              AND (run_index.completed_at_ns < ?
               OR (run_index.completed_at_ns = ? AND run_index.artifact_id > ?))
            ORDER BY run_index.completed_at_ns DESC, run_index.artifact_id ASC
            LIMIT ?
            """,
            (
                logical_run_id.hex,
                after.completed_at_ns,
                after.completed_at_ns,
                after.artifact_id.hex,
                limit,
            ),
        ).fetchall()

    @staticmethod
    def _verify_run_index_completeness(connection: sqlite3.Connection) -> None:
        """Reject a dirty generation before trusting global filter/order fields."""

        SQLiteArtifactCatalog._require_run_index_complete(connection)
        SQLiteArtifactCatalog._verify_run_index_rows(connection)

    @staticmethod
    def _require_run_index_complete(connection: sqlite3.Connection) -> None:
        """Require the durable generation marker set by a verified catalog write."""

        state = connection.execute(
            "SELECT status FROM run_index_state WHERE singleton = 1"
        ).fetchone()
        if state is None or str(state["status"]) != "COMPLETE":
            raise ArtifactCatalogVerificationError("run index generation is incomplete")

    @staticmethod
    def _verify_run_index_rows(connection: sqlite3.Connection) -> None:
        """Reject missing, detached, or descriptor-stale Run projection rows."""

        missing = connection.execute(
            """
            SELECT 1
            FROM artifact_index
            LEFT JOIN build_key_mapping
              ON build_key_mapping.build_key = artifact_index.build_key
             AND build_key_mapping.artifact_id = artifact_index.artifact_id
            LEFT JOIN run_index
              ON run_index.artifact_id = artifact_index.artifact_id
             AND run_index.manifest_digest = artifact_index.manifest_digest
            WHERE artifact_index.kind = 'RUN'
              AND artifact_index.status = 'VERIFIED'
              AND (
                    build_key_mapping.artifact_id IS NULL
                 OR build_key_mapping.status != 'VERIFIED'
                 OR run_index.artifact_id IS NULL
              )
            LIMIT 1
            """
        ).fetchone()
        # A dangling or quarantined row means the projection was not atomically rebuilt.
        detached = connection.execute(
            """
            SELECT 1
            FROM run_index
            LEFT JOIN artifact_index USING (artifact_id)
            WHERE artifact_index.artifact_id IS NULL
               OR artifact_index.kind != 'RUN'
               OR artifact_index.status != 'VERIFIED'
               OR run_index.manifest_digest != artifact_index.manifest_digest
            LIMIT 1
            """
        ).fetchone()
        if missing is not None or detached is not None:
            raise ArtifactCatalogVerificationError(
                "run index disagrees with the verified artifact catalog"
            )

    @staticmethod
    def _mark_run_index_complete(connection: sqlite3.Connection) -> None:
        """Close one transactional generation only after structural verification."""

        SQLiteArtifactCatalog._verify_run_index_rows(connection)
        changed = connection.execute(
            "UPDATE run_index_state SET status = 'COMPLETE' WHERE singleton = 1"
        ).rowcount
        if changed != 1:
            raise ArtifactCatalogVerificationError("run index state is unavailable")

    @staticmethod
    def _run_entry_from_row(row: sqlite3.Row) -> RunIndexEntry:
        """Convert an untrusted SQLite row into the strict application DTO."""

        if int(row["is_queryable"]) != 1:
            raise ValueError("excluded Run row cannot be returned as searchable metadata")
        return RunIndexEntry(
            artifact_id=ArtifactId(str(row["artifact_id"])),
            manifest_digest=ContentDigest(str(row["manifest_digest"])),
            logical_run_id=LogicalRunId(str(row["logical_run_id"])),
            # Attempt identity is compared again with the selected verified manifest.
            execution_attempt_id=ExecutionAttemptId(str(row["execution_attempt_id"])),
            started_at_ns=int(row["started_at_ns"]),
            completed_at_ns=int(row["completed_at_ns"]),
        )

    def _run_index_entry(self, artifact: CommittedArtifact) -> RunIndexEntry | None:
        """Extract ordering fields from one already authenticated Run artifact."""

        handle = self._repository.open_committed(artifact.artifact_id)
        try:
            if not _same_descriptor(handle.descriptor, artifact):
                raise ArtifactCatalogVerificationError(
                    "Run descriptor changed before projection extraction"
                )
            with handle.open_binary("manifest.json") as stream:
                payload = stream.read(MAX_SUCCESSFUL_RUN_MANIFEST_BYTES + 1)
        finally:
            handle.close()

        try:
            manifest = successful_run_manifest_from_bytes(payload)
        except (ApplicationError, KeyError, TypeError, ValueError):
            # Generic legacy/debug Runs remain catalogued but cannot enter typed pages.
            return None
        if manifest.input_artifact_ids != artifact.input_artifact_ids:
            raise ArtifactCatalogVerificationError(
                "Run manifest input closure differs from its artifact descriptor"
            )
        return RunIndexEntry(
            artifact_id=artifact.artifact_id,
            manifest_digest=artifact.manifest_digest,
            logical_run_id=manifest.logical_run_id,
            # Keep attempt identity beside time fields for exact selected-page checks.
            execution_attempt_id=manifest.execution_attempt_id,
            started_at_ns=_datetime_epoch_ns(manifest.started_at),
            completed_at_ns=_datetime_epoch_ns(manifest.completed_at),
        )

    def _upsert_run_entry(
        self,
        connection: sqlite3.Connection,
        artifact: CommittedArtifact,
        entry: RunIndexEntry | None,
    ) -> None:
        """Insert a new exact projection or reject disagreement with an existing one."""

        row = connection.execute(
            "SELECT * FROM run_index WHERE artifact_id = ?",
            (artifact.artifact_id.hex,),
        ).fetchone()
        if artifact.kind is not ArtifactKind.RUN:
            if row is not None:
                raise ArtifactCatalogVerificationError("non-Run artifact has a Run projection row")
            return
        if row is None:
            self._insert_run_projection(connection, artifact, entry)
            return
        if entry is None:
            # An excluded Run has no sortable or filterable metadata in SQLite.
            excluded_values = tuple(
                row[field]
                for field in (
                    "logical_run_id",
                    "execution_attempt_id",
                    "started_at_ns",
                    "completed_at_ns",
                )
            )
            if (
                int(row["is_queryable"]) != 0
                or str(row["manifest_digest"]) != artifact.manifest_digest.hex
                or any(value is not None for value in excluded_values)
            ):
                raise ArtifactCatalogVerificationError(
                    "unqueryable Run projection disagrees with its verified manifest"
                )
            return
        try:
            indexed = self._run_entry_from_row(row)
        except (TypeError, ValueError) as error:
            raise ArtifactCatalogVerificationError("run index contains invalid values") from error
        if indexed != entry:
            raise ArtifactCatalogVerificationError(
                "run index entry disagrees with the verified manifest"
            )

    @staticmethod
    def _insert_run_projection(
        connection: sqlite3.Connection,
        artifact: CommittedArtifact,
        entry: RunIndexEntry | None,
    ) -> None:
        """Insert one searchable or explicitly excluded manifest-bound Run row."""

        if entry is not None and (
            entry.artifact_id != artifact.artifact_id
            or entry.manifest_digest != artifact.manifest_digest
        ):
            raise ArtifactCatalogVerificationError("Run projection identity is inconsistent")
        values: tuple[object, ...]
        if entry is None:
            values = (
                artifact.artifact_id.hex,
                artifact.manifest_digest.hex,
                0,
                None,
                None,
                None,
                None,
            )
        else:
            # Integer epochs make SQLite ordering independent of timestamp spelling.
            values = (
                entry.artifact_id.hex,
                entry.manifest_digest.hex,
                1,
                entry.logical_run_id.hex,
                entry.execution_attempt_id.hex,
                entry.started_at_ns,
                entry.completed_at_ns,
            )

        connection.execute(
            """
            INSERT INTO run_index (
                artifact_id, manifest_digest, is_queryable, logical_run_id,
                execution_attempt_id, started_at_ns, completed_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    # Define sqlite artifact catalog status as one focused operation with an explicit
    # boundary.
    def status(self, artifact_id: ArtifactId) -> ArtifactCatalogStatus | None:
        """Return index classification for diagnostics, never artifact authority."""

        connection = self._connect()
        try:
            # Perform the protected sqlite artifact catalog status operation before
            # explicit failure handling.
            row = connection.execute(
                "SELECT status FROM artifact_index WHERE artifact_id = ?",
                (artifact_id.hex,),
            ).fetchone()
        finally:
            # Invoke close as a visible step within the sqlite artifact catalog status
            # workflow.
            connection.close()
        if row is None:
            return None
        try:
            return ArtifactCatalogStatus(str(row["status"]))
        # Translate value error through the sqlite artifact catalog status boundary
        # without hiding other errors.
        except ValueError as error:
            # Translate the ValueError failure through the sqlite artifact catalog status
            # boundary.
            raise ArtifactCatalogVerificationError(
                "artifact index contains an invalid status"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        return connect(self._path, busy_timeout_seconds=self._busy_timeout_seconds)

    # Define sqlite artifact catalog verify filesystem as one focused operation with an
    # explicit boundary.
    def _verify_filesystem(
        self,
        expected: CommittedArtifact,
        *,
        verify_inputs: bool = False,
        # Keep the committed artifact input explicit in the verify filesystem contract.
    ) -> CommittedArtifact:
        # Execute the sqlite artifact catalog verify filesystem workflow in explicit,
        # reviewable steps.
        handle = self._repository.open_committed(expected.artifact_id)
        try:
            actual = handle.descriptor
        finally:
            handle.close()
        # Guard this path with not _same_descriptor(actual, expected) before applying
        # effects.
        if not _same_descriptor(actual, expected):
            # Handle the sqlite artifact catalog verify filesystem not
            # _same_descriptor(actual, expected) branch as a distinct logical block.
            raise ArtifactCatalogVerificationError(
                "filesystem artifact descriptor disagrees with catalog input"
            )
        if verify_inputs:
            # Handle the sqlite artifact catalog verify filesystem verify_inputs branch as
            # a distinct logical block.
            for input_id in actual.input_artifact_ids:
                # Process actual.input_artifact_ids inside the bounded sqlite artifact
                # catalog verify filesystem loop.
                input_handle = self._repository.open_committed(input_id)
                input_handle.close()
        return actual

    def _indexed_verified_descriptor(
        self,
        # Keep the artifact id input explicit in the indexed verified descriptor contract.
        artifact_id: ArtifactId,
    ) -> CommittedArtifact | None:
        # Execute the sqlite artifact catalog indexed verified descriptor workflow in
        # explicit, reviewable steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite artifact catalog indexed verified descriptor
            # operation before explicit failure handling.
            row = connection.execute(
                """
                SELECT
                    artifact_index.artifact_id,
                    artifact_index.kind,
                    artifact_index.manifest_digest,
                    artifact_index.build_key
                FROM artifact_index
                JOIN build_key_mapping
                  ON build_key_mapping.build_key = artifact_index.build_key
                 AND build_key_mapping.artifact_id = artifact_index.artifact_id
                WHERE artifact_index.artifact_id = ?
                  AND artifact_index.status = 'VERIFIED'
                  AND build_key_mapping.status = 'VERIFIED'
                """,
                (artifact_id.hex,),
            ).fetchone()
            if row is None:
                # Return explicit absence from the sqlite artifact catalog indexed
                # verified descriptor path.
                return None
            input_rows = connection.execute(
                """
                SELECT input_artifact_id
                FROM lineage_edges
                WHERE output_artifact_id = ?
                ORDER BY ordinal
                """,
                (artifact_id.hex,),
            ).fetchall()
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            connection.close()
        try:
            # Perform the protected sqlite artifact catalog indexed verified descriptor
            # operation before explicit failure handling.
            return CommittedArtifact(
                artifact_id=ArtifactId(str(row["artifact_id"])),
                kind=ArtifactKind(str(row["kind"])),
                manifest_digest=ContentDigest(str(row["manifest_digest"])),
                build_key=ContentDigest(str(row["build_key"])),
                # Include input artifact ids in the completed sqlite artifact catalog
                # indexed verified descriptor result.
                input_artifact_ids=tuple(
                    ArtifactId(str(input_row["input_artifact_id"])) for input_row in input_rows
                ),
            )
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the sqlite artifact
            # catalog indexed verified descriptor boundary.
            raise ArtifactCatalogVerificationError(
                "artifact index contains an invalid descriptor"
            ) from error

    def _verify_lineage(self, artifact: CommittedArtifact) -> None:
        # Execute the sqlite artifact catalog verify lineage workflow in explicit,
        # reviewable steps.
        for input_id in artifact.input_artifact_ids:
            # Process artifact.input_artifact_ids inside the bounded sqlite artifact
            # catalog verify lineage loop.
            input_handle = self._repository.open_committed(input_id)
            input_handle.close()

    def _upsert_exact_artifact(
        self,
        connection: sqlite3.Connection,
        # Keep the artifact input explicit in the upsert exact artifact contract.
        artifact: CommittedArtifact,
        *,
        now_ns: int,
    ) -> None:
        # Execute the sqlite artifact catalog upsert exact artifact workflow in explicit,
        # reviewable steps.
        row = connection.execute(
            """
            SELECT artifact_id, kind, manifest_digest, build_key, status
            FROM artifact_index
            WHERE artifact_id = ?
            """,
            (artifact.artifact_id.hex,),
        ).fetchone()
        if row is None:
            # Handle the sqlite artifact catalog upsert exact artifact row is None branch
            # as a distinct logical block.
            self._insert_artifact(
                connection,
                artifact,
                status=ArtifactCatalogStatus.VERIFIED,
                reason=None,
                # Pass now ns explicitly so _insert_artifact receives a reviewable
                # verified and connection input in sqlite artifact catalog upsert exact
                # artifact.
                now_ns=now_ns,
            )
            return
        indexed_identity = (
            str(row["artifact_id"]),
            # Register row and kind through str so the indexed identity table remains
            # scannable.
            str(row["kind"]),
            str(row["manifest_digest"]),
            str(row["build_key"]),
        )
        supplied_identity = (
            # Keep the artifact component named inside the supplied identity contract.
            artifact.artifact_id.hex,
            artifact.kind.value,
            artifact.manifest_digest.hex,
            artifact.build_key.hex,
        )
        # Guard this path with indexed_identity != supplied_identity before applying
        # effects.
        if indexed_identity != supplied_identity:
            # Handle the sqlite artifact catalog upsert exact artifact indexed_identity !=
            # supplied_identity branch as a distinct logical block.
            raise ArtifactCatalogVerificationError(
                "artifact ID is indexed with a different descriptor"
            )
        lineage = self._lineage_rows(connection, artifact.artifact_id)
        if lineage != artifact.input_artifact_ids:
            # Handle the sqlite artifact catalog upsert exact artifact lineage !=
            # artifact.input_artifact_ids branch as a distinct logical block.
            raise ArtifactCatalogVerificationError(
                "artifact index lineage disagrees with filesystem descriptor"
            )

    def _insert_artifact(
        self,
        # Keep the connection input explicit in the insert artifact contract.
        connection: sqlite3.Connection,
        artifact: CommittedArtifact,
        *,
        status: ArtifactCatalogStatus,
        reason: str | None,
        # Keep the now ns input explicit in the insert artifact contract.
        now_ns: int,
    ) -> None:
        # Execute the sqlite artifact catalog insert artifact workflow in explicit,
        # reviewable steps.
        connection.execute(
            """
            INSERT INTO artifact_index (
                artifact_id, kind, manifest_digest, build_key,
                status, status_reason, indexed_at_ns, verified_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id.hex,
                artifact.kind.value,
                # Pass artifact explicitly so execute receives a reviewable hex and value
                # input in sqlite artifact catalog insert artifact.
                artifact.manifest_digest.hex,
                artifact.build_key.hex,
                status.value,
                reason,
                now_ns,
                # Pass now ns explicitly so execute receives a reviewable hex and value
                # input in sqlite artifact catalog insert artifact.
                now_ns,
            ),
        )
        connection.executemany(
            """
            INSERT INTO lineage_edges (
                output_artifact_id, input_artifact_id, ordinal
            ) VALUES (?, ?, ?)
            """,
            # Open the hex and artifact id payload explicitly for executemany within
            # sqlite artifact catalog insert artifact.
            (
                (artifact.artifact_id.hex, input_id.hex, ordinal)
                for ordinal, input_id in enumerate(artifact.input_artifact_ids)
            ),
        )

    # Define sqlite artifact catalog record collision as one focused operation with an
    # explicit boundary.
    def _record_collision(
        self,
        connection: sqlite3.Connection,
        *,
        build_key: ContentDigest,
        # Keep the artifact ids input explicit in the record collision contract.
        artifact_ids: Sequence[ArtifactId],
        detected_at_ns: int,
    ) -> tuple[ArtifactId, ...]:
        # Execute the sqlite artifact catalog record collision workflow in explicit,
        # reviewable steps.
        unique_ids = tuple(sorted(set(artifact_ids), key=lambda item: item.hex))
        connection.executemany(
            """
            UPDATE artifact_index
            SET status = 'QUARANTINED', status_reason = ?
            WHERE artifact_id = ?
            """,
            ((_COLLISION_REASON, artifact_id.hex) for artifact_id in unique_ids),
        )
        # Quarantined artifacts must immediately disappear from searchable Run pages.
        connection.executemany(
            "DELETE FROM run_index WHERE artifact_id = ?",
            ((artifact_id.hex,) for artifact_id in unique_ids),
        )
        # Invoke execute for hex and detected at ns as a visible sqlite artifact catalog
        # record collision step.
        connection.execute(
            """
            UPDATE build_key_mapping
            SET status = 'CONFLICT', updated_at_ns = ?
            WHERE build_key = ?
            """,
            (detected_at_ns, build_key.hex),
        )
        connection.executemany(
            # Keep executemany, connection and hex visible while completing executemany
            # within sqlite artifact catalog record collision.
            """
            INSERT OR IGNORE INTO artifact_build_conflicts (
                build_key, artifact_id, detected_at_ns
            ) VALUES (?, ?, ?)
            """,
            ((build_key.hex, artifact_id.hex, detected_at_ns) for artifact_id in unique_ids),
        )
        rows = connection.execute(
            """
            SELECT artifact_id
            FROM artifact_build_conflicts
            WHERE build_key = ?
            ORDER BY artifact_id
            """,
            # Open the declared payload explicitly for fetchall within sqlite artifact
            # catalog record collision.
            (build_key.hex,),
        ).fetchall()
        return tuple(ArtifactId(str(row["artifact_id"])) for row in rows)

    @staticmethod
    def _lineage_rows(
        # Keep the connection input explicit in the lineage rows contract.
        connection: sqlite3.Connection,
        artifact_id: ArtifactId,
    ) -> tuple[ArtifactId, ...]:
        # Execute the sqlite artifact catalog lineage rows workflow in explicit,
        # reviewable steps.
        rows = connection.execute(
            """
            SELECT input_artifact_id
            FROM lineage_edges
            WHERE output_artifact_id = ?
            ORDER BY ordinal
            """,
            (artifact_id.hex,),
        ).fetchall()
        return tuple(ArtifactId(str(row["input_artifact_id"])) for row in rows)


# Bind all once as an explicit module-level contract.
__all__ = ["SQLiteArtifactCatalog"]


def _same_descriptor(left: CommittedArtifact, right: CommittedArtifact) -> bool:
    # Execute the same descriptor workflow in explicit, reviewable steps.
    return (
        left.artifact_id.hex == right.artifact_id.hex
        and left.kind is right.kind
        and left.manifest_digest.hex == right.manifest_digest.hex
        and left.build_key.hex == right.build_key.hex
        # Include tuple in the completed same descriptor result.
        and tuple(item.hex for item in left.input_artifact_ids)
        == tuple(item.hex for item in right.input_artifact_ids)
    )


def _datetime_epoch_ns(value: datetime) -> int:
    """Convert an aware manifest timestamp to an exact integer epoch without float."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Run index timestamp must be timezone-aware")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value.astimezone(UTC) - epoch
    # datetime precision is microseconds, so the integer conversion is exact.
    whole_seconds = delta.days * 86_400 + delta.seconds
    return whole_seconds * 1_000_000_000 + delta.microseconds * 1_000
