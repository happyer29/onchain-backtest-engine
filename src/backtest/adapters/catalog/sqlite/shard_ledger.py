"""SQLite shard ledger with filesystem-verified, gap-safe frontiers."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

# Import schema at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.schema import connect, initialize
from backtest.application.canonical_data import SourceBoundary, ValidationStatus
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.catalog import ArtifactCatalog
from backtest.application.source_ledger import (
    # Include committed shard revision so the source ledger dependency remains explicit.
    CommittedShardRevision,
    ShardArtifactNotVerifiedError,
    ShardLedgerConflictError,
    SourceFrontier,
)

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import (
    ChainFinality,
    IngestionCompleteness,
    SourceConsistency,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    CapabilityId,
    ContentDigest,
    NetworkId,
    # Include position schema id so the identifiers dependency remains explicit.
    PositionSchemaId,
    SourceId,
)
from backtest.domain.time import BlockRange


# Keep the sqlite shard ledger contract and validation rules together.
class SQLiteShardLedger:
    def __init__(
        self,
        path: Path,
        artifact_catalog: ArtifactCatalog,
        # Close the init signature after its explicit inputs.
        *,
        busy_timeout_seconds: float = 5.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        # Execute the sqlite shard ledger init workflow in explicit, reviewable steps.
        if busy_timeout_seconds <= 0:
            raise ValueError("busy_timeout_seconds must be positive")
        self._path = path
        self._artifact_catalog = artifact_catalog
        self._busy_timeout_seconds = busy_timeout_seconds
        # Assemble self clock ns once so the sqlite shard ledger init workflow shares one
        # value.
        self._clock_ns = clock_ns
        initialize(path, busy_timeout_seconds=busy_timeout_seconds)

    def record_revision(self, revision: CommittedShardRevision) -> None:
        # Execute the sqlite shard ledger record revision workflow in explicit, reviewable
        # steps.
        verified = self._artifact_catalog.find_committed(revision.artifact.artifact_id)
        if verified is None or not _same_artifact(verified, revision.artifact):
            # Handle the sqlite shard ledger record revision verified, same artifact and
            # artifact condition as a distinct block.
            raise ShardArtifactNotVerifiedError(
                "shard artifact is absent, quarantined, or differs from filesystem authority"
            )

        boundary = revision.boundary
        identity = self._identity(boundary)
        # Assemble values once so the sqlite shard ledger record revision workflow shares
        # one value.
        values = self._values(revision, committed_at_ns=self._clock_ns())
        connection = self._connect()
        try:
            # Perform the protected sqlite shard ledger record revision operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            existing_rows = connection.execute(
                """
                SELECT * FROM shard_ledger
                WHERE source_id = ?
                  AND capability_id = ?
                  AND capability_schema_version = ?
                  AND network_id = ?
                  AND position_schema_id = ?
                  AND from_block_ordinal = ?
                  AND to_block_ordinal = ?
                  AND internal_revision = ?
                """,
                identity,
            ).fetchall()
            if any(
                not self._row_matches_logical_boundary(connection, row, boundary)
                for row in existing_rows
            ):
                raise ShardLedgerConflictError(
                    "logical shard revision is already recorded with conflicting metadata"
                )
            existing_artifact = next(
                (
                    row
                    for row in existing_rows
                    if str(row["artifact_id"]) == revision.artifact.artifact_id.hex
                ),
                None,
            )
            if existing_artifact is None:
                try:
                    # Perform the protected sqlite shard ledger record revision operation
                    # before explicit failure handling.
                    connection.execute(
                        """
                        INSERT INTO shard_ledger (
                            source_id, capability_id, capability_schema_version,
                            network_id, position_schema_id,
                            from_block_ordinal, to_block_ordinal,
                            internal_revision, artifact_id,
                            snapshot_cut_to_block, chain_finality,
                            ingestion_watermark_to_block, upstream_revision,
                            source_consistency, completeness, validation_status,
                            committed_at_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                    connection.executemany(
                        # Keep executemany, connection and hex visible while completing
                        # executemany within sqlite shard ledger record revision.
                        """
                        INSERT INTO shard_query_fingerprints (
                            source_id, capability_id, capability_schema_version,
                            network_id, position_schema_id,
                            from_block_ordinal, to_block_ordinal, internal_revision,
                            artifact_id, query_fingerprint, ordinal
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            (
                                *identity,
                                revision.artifact.artifact_id.hex,
                                fingerprint.hex,
                                ordinal,
                            )
                            for ordinal, fingerprint in enumerate(boundary.query_fingerprints)
                        ),
                        # Complete executemany only after its hex and query fingerprints
                        # inputs are visible in sqlite shard ledger record revision.
                    )
                except sqlite3.IntegrityError as error:
                    # Translate the sqlite3.IntegrityError failure through the sqlite
                    # shard ledger record revision boundary.
                    raise ShardLedgerConflictError(
                        "artifact or shard revision is already bound differently"
                    ) from error
            connection.execute(
                """
                DELETE FROM source_frontiers
                WHERE source_id = ?
                  AND capability_id = ?
                  AND capability_schema_version = ?
                """,
                # Open the value and capability schema version payload explicitly for
                # execute within sqlite shard ledger record revision.
                (
                    boundary.source_id.value,
                    boundary.capability_id.value,
                    boundary.capability_schema_version,
                ),
                # Complete execute only after its value and capability schema version inputs
                # are visible in sqlite shard ledger record revision.
            )
            connection.execute("COMMIT")
        except BaseException:
            # Translate the BaseException failure through the sqlite shard ledger record
            # revision boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # Define sqlite shard ledger contiguous frontier as one focused operation with an
    # explicit boundary.
    def contiguous_frontier(
        self,
        *,
        source_id: SourceId,
        capability_id: CapabilityId,
        # Keep the capability schema version input explicit in the contiguous frontier
        # contract.
        capability_schema_version: str,
        network_id: NetworkId,
        position_schema_id: PositionSchemaId,
        coverage_from_block_ordinal: int,
    ) -> SourceFrontier:
        # Execute the sqlite shard ledger contiguous frontier workflow in explicit,
        # reviewable steps.
        if not capability_schema_version:
            raise ValueError("capability schema version must be non-empty")
        if not isinstance(network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(position_schema_id, PositionSchemaId):
            # Fail the sqlite shard ledger contiguous frontier path with TypeError for
            # position schema id must be a position schema id when isinstance and position
            # schema id is true; do not continue ambiguously.
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if isinstance(coverage_from_block_ordinal, bool) or not isinstance(
            coverage_from_block_ordinal,
            int,
        ):
            # Fail the sqlite shard ledger contiguous frontier path with TypeError for
            # coverage from block ordinal must be an integer when isinstance and coverage
            # from block ordinal is true; do not continue ambiguously.
            raise TypeError("coverage_from_block_ordinal must be an integer")
        if coverage_from_block_ordinal < 0:
            raise ValueError("coverage_from_block_ordinal must be non-negative")

        connection = self._connect()
        try:
            # Perform the protected sqlite shard ledger contiguous frontier operation
            # before explicit failure handling.
            rows = connection.execute(
                """
                SELECT from_block_ordinal, to_block_ordinal, artifact_id, committed_at_ns
                FROM shard_ledger
                WHERE source_id = ?
                  AND capability_id = ?
                  AND capability_schema_version = ?
                  AND network_id = ?
                  AND position_schema_id = ?
                  AND validation_status = ?
                  AND to_block_ordinal > ?
                ORDER BY from_block_ordinal, to_block_ordinal, committed_at_ns, artifact_id
                """,
                (
                    source_id.value,
                    capability_id.value,
                    # Pass capability schema version explicitly into fetchall within
                    # sqlite shard ledger contiguous frontier.
                    capability_schema_version,
                    network_id.value,
                    position_schema_id.value,
                    ValidationStatus.PASS.value,
                    coverage_from_block_ordinal,
                    # Complete fetchall only after its declared inputs are visible in sqlite
                    # shard ledger contiguous frontier.
                ),
            ).fetchall()
        finally:
            connection.close()

        verified_ranges: list[tuple[int, int]] = []
        # Traverse rows explicitly so each sqlite shard ledger contiguous frontier
        # iteration remains traceable.
        for row in rows:
            # Process rows inside the bounded sqlite shard ledger contiguous frontier
            # loop.
            artifact_id = ArtifactId(str(row["artifact_id"]))
            artifact = self._artifact_catalog.find_committed(artifact_id)
            if artifact is None or artifact.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
                continue
            verified_ranges.append((int(row["from_block_ordinal"]), int(row["to_block_ordinal"])))

        # Assemble frontier block ordinal once so the sqlite shard ledger contiguous
        # frontier workflow shares one value.
        frontier_block_ordinal = coverage_from_block_ordinal
        while True:
            # Keep the True loop body bounded within sqlite shard ledger contiguous
            # frontier.
            next_frontier = max(
                (
                    to_block
                    for from_block, to_block in verified_ranges
                    if from_block <= frontier_block_ordinal < to_block
                    # Complete max only after its to block and verified ranges inputs are
                    # visible in sqlite shard ledger contiguous frontier.
                ),
                default=frontier_block_ordinal,
            )
            if next_frontier == frontier_block_ordinal:
                break
            # Assemble frontier block ordinal once so the sqlite shard ledger contiguous
            # frontier workflow shares one value.
            frontier_block_ordinal = next_frontier

        frontier = SourceFrontier(
            source_id=source_id,
            capability_id=capability_id,
            capability_schema_version=capability_schema_version,
            # Pass network id explicitly so SourceFrontier receives a reviewable source id
            # and capability id input in sqlite shard ledger contiguous frontier.
            network_id=network_id,
            position_schema_id=position_schema_id,
            coverage_from_block_ordinal=coverage_from_block_ordinal,
            frontier_block_ordinal=frontier_block_ordinal,
        )
        # Invoke _cache_frontier for frontier as a visible sqlite shard ledger contiguous
        # frontier step.
        self._cache_frontier(frontier)
        return frontier

    def committed_revisions(
        self,
        *,
        # Keep the source id input explicit in the committed revisions contract.
        source_id: SourceId,
        capability_id: CapabilityId,
        capability_schema_version: str,
        block_range: BlockRange,
    ) -> tuple[CommittedShardRevision, ...]:
        """Return filesystem-verified exact revisions for one half-open shard."""

        if not capability_schema_version:
            raise ValueError("capability schema version must be non-empty")
        connection = self._connect()
        try:
            # Perform the protected sqlite shard ledger committed revisions operation
            # before explicit failure handling.
            rows = connection.execute(
                """
                SELECT * FROM shard_ledger
                WHERE source_id = ?
                  AND capability_id = ?
                  AND capability_schema_version = ?
                  AND network_id = ?
                  AND position_schema_id = ?
                  AND from_block_ordinal = ?
                  AND to_block_ordinal = ?
                  AND validation_status = ?
                ORDER BY committed_at_ns, artifact_id
                """,
                (
                    source_id.value,
                    capability_id.value,
                    # Pass capability schema version explicitly into fetchall within
                    # sqlite shard ledger committed revisions.
                    capability_schema_version,
                    block_range.network_id.value,
                    block_range.position_schema_id.value,
                    block_range.from_block_ordinal,
                    block_range.to_block_ordinal,
                    # Pass validation status explicitly into fetchall within sqlite shard
                    # ledger committed revisions.
                    ValidationStatus.PASS.value,
                ),
            ).fetchall()
            result: list[CommittedShardRevision] = []
            for row in rows:
                # Process rows inside the bounded sqlite shard ledger committed revisions
                # loop.
                artifact_id = ArtifactId(str(row["artifact_id"]))
                artifact = self._artifact_catalog.find_committed(artifact_id)
                if artifact is None or artifact.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
                    continue
                fingerprints = connection.execute(
                    # Keep fetchall, execute and connection visible while completing
                    # fetchall within sqlite shard ledger committed revisions.
                    """
                    SELECT query_fingerprint
                    FROM shard_query_fingerprints
                    WHERE source_id = ?
                      AND capability_id = ?
                      AND capability_schema_version = ?
                      AND network_id = ?
                      AND position_schema_id = ?
                      AND from_block_ordinal = ?
                      AND to_block_ordinal = ?
                      AND internal_revision = ?
                      AND artifact_id = ?
                    ORDER BY ordinal
                    """,
                    (
                        source_id.value,
                        capability_id.value,
                        capability_schema_version,
                        # Pass block range explicitly into fetchall within sqlite shard
                        # ledger committed revisions.
                        block_range.network_id.value,
                        block_range.position_schema_id.value,
                        block_range.from_block_ordinal,
                        block_range.to_block_ordinal,
                        str(row["internal_revision"]),
                        str(row["artifact_id"]),
                        # Complete fetchall only after its declared inputs are visible in
                        # sqlite shard ledger committed revisions.
                    ),
                ).fetchall()
                boundary = SourceBoundary(
                    source_id=source_id,
                    capability_id=capability_id,
                    # Pass capability schema version explicitly so SourceBoundary receives
                    # a reviewable snapshot cut to block and chain finality input in
                    # sqlite shard ledger committed revisions.
                    capability_schema_version=capability_schema_version,
                    block_range=block_range,
                    snapshot_cut_to_block=int(row["snapshot_cut_to_block"]),
                    chain_finality=ChainFinality(str(row["chain_finality"])),
                    ingestion_watermark_to_block=(
                        # Keep source boundary, source id and capability id visible while
                        # completing SourceBoundary within sqlite shard ledger committed
                        # revisions.
                        None
                        if row["ingestion_watermark_to_block"] is None
                        else int(row["ingestion_watermark_to_block"])
                    ),
                    upstream_revision=(
                        # Keep the row and upstream revision str step visible while
                        # building boundary.
                        None if row["upstream_revision"] is None else str(row["upstream_revision"])
                    ),
                    internal_revision=ContentDigest(str(row["internal_revision"])),
                    source_consistency=SourceConsistency(str(row["source_consistency"])),
                    completeness=IngestionCompleteness(str(row["completeness"])),
                    # Keep the validation status and row ValidationStatus step visible
                    # while building boundary.
                    validation_status=ValidationStatus(str(row["validation_status"])),
                    query_fingerprints=tuple(
                        ContentDigest(str(item["query_fingerprint"])) for item in fingerprints
                    ),
                )
                # Invoke append for committed shard revision and artifact as a visible
                # sqlite shard ledger committed revisions step.
                result.append(CommittedShardRevision(artifact, boundary))
        except (TypeError, ValueError) as error:
            raise ShardLedgerConflictError("shard ledger contains an invalid revision") from error
        finally:
            connection.close()
        # Return the completed sqlite shard ledger committed revisions result without a
        # hidden fallback.
        return tuple(result)

    def _cache_frontier(self, frontier: SourceFrontier) -> None:
        # Execute the sqlite shard ledger cache frontier workflow in explicit, reviewable
        # steps.
        connection = self._connect()
        try:
            # Perform the protected sqlite shard ledger cache frontier operation before
            # explicit failure handling.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO source_frontiers (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    coverage_from_block_ordinal, frontier_block_ordinal, computed_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    source_id, capability_id,
                    capability_schema_version, network_id, position_schema_id,
                    coverage_from_block_ordinal
                ) DO UPDATE SET
                    frontier_block_ordinal = excluded.frontier_block_ordinal,
                    computed_at_ns = excluded.computed_at_ns
                """,
                (
                    frontier.source_id.value,
                    # Pass frontier explicitly so execute receives a reviewable value and
                    # capability schema version input in sqlite shard ledger cache
                    # frontier.
                    frontier.capability_id.value,
                    frontier.capability_schema_version,
                    frontier.network_id.value,
                    frontier.position_schema_id.value,
                    frontier.coverage_from_block_ordinal,
                    # Pass frontier explicitly so execute receives a reviewable value and
                    # capability schema version input in sqlite shard ledger cache
                    # frontier.
                    frontier.frontier_block_ordinal,
                    self._clock_ns(),
                ),
            )
            connection.execute("COMMIT")
        # Translate base exception through the sqlite shard ledger cache frontier boundary
        # without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the sqlite shard ledger cache
            # frontier boundary.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # Define sqlite shard ledger connect as one focused operation with an explicit
    # boundary.
    def _connect(self) -> sqlite3.Connection:
        return connect(self._path, busy_timeout_seconds=self._busy_timeout_seconds)

    @staticmethod
    def _identity(boundary: SourceBoundary) -> tuple[object, ...]:
        # Execute the sqlite shard ledger identity workflow in explicit, reviewable steps.
        return (
            boundary.source_id.value,
            boundary.capability_id.value,
            boundary.capability_schema_version,
            boundary.block_range.network_id.value,
            # Include boundary in the completed sqlite shard ledger identity result.
            boundary.block_range.position_schema_id.value,
            boundary.block_range.from_block_ordinal,
            boundary.block_range.to_block_ordinal,
            boundary.internal_revision.hex,
        )

    # Apply classmethod semantics to the following sqlite shard ledger values contract.
    @classmethod
    def _values(
        cls,
        revision: CommittedShardRevision,
        *,
        # Keep the committed at ns input explicit in the values contract.
        committed_at_ns: int,
    ) -> tuple[object, ...]:
        # Execute the sqlite shard ledger values workflow in explicit, reviewable steps.
        boundary = revision.boundary
        return (
            *cls._identity(boundary),
            revision.artifact.artifact_id.hex,
            boundary.snapshot_cut_to_block,
            # Include boundary in the completed sqlite shard ledger values result.
            boundary.chain_finality.value,
            boundary.ingestion_watermark_to_block,
            boundary.upstream_revision,
            boundary.source_consistency.value,
            boundary.completeness.value,
            # Include boundary in the completed sqlite shard ledger values result.
            boundary.validation_status.value,
            committed_at_ns,
        )

    @classmethod
    def _row_matches_logical_boundary(
        # Keep the remaining row matches inputs visible at the sqlite shard ledger row
        # matches boundary.
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        boundary: SourceBoundary,
    ) -> bool:
        # Execute the sqlite shard ledger row matches workflow in explicit, reviewable
        # steps.
        expected = (
            *cls._identity(boundary),
            boundary.snapshot_cut_to_block,
            boundary.chain_finality.value,
            boundary.ingestion_watermark_to_block,
            boundary.upstream_revision,
            boundary.source_consistency.value,
            boundary.completeness.value,
            boundary.validation_status.value,
        )
        actual = (
            str(row["source_id"]),
            str(row["capability_id"]),
            # Register row and capability schema version through str so the actual without
            # time table remains scannable.
            str(row["capability_schema_version"]),
            str(row["network_id"]),
            str(row["position_schema_id"]),
            int(row["from_block_ordinal"]),
            int(row["to_block_ordinal"]),
            # Register row and internal revision through str so the actual without time
            # table remains scannable.
            str(row["internal_revision"]),
            int(row["snapshot_cut_to_block"]),
            str(row["chain_finality"]),
            None
            # Keep the row component named inside the actual without time contract.
            if row["ingestion_watermark_to_block"] is None
            else int(row["ingestion_watermark_to_block"]),
            None if row["upstream_revision"] is None else str(row["upstream_revision"]),
            str(row["source_consistency"]),
            str(row["completeness"]),
            # Register row and validation status through str so the actual without time
            # table remains scannable.
            str(row["validation_status"]),
        )
        if actual != expected:
            return False
        fingerprint_rows = connection.execute(
            # Keep fetchall, execute and connection visible while completing fetchall
            # within sqlite shard ledger row matches.
            """
            SELECT query_fingerprint
            FROM shard_query_fingerprints
            WHERE source_id = ?
              AND capability_id = ?
              AND capability_schema_version = ?
              AND network_id = ?
              AND position_schema_id = ?
              AND from_block_ordinal = ?
              AND to_block_ordinal = ?
              AND internal_revision = ?
              AND artifact_id = ?
            ORDER BY ordinal
            """,
            (*cls._identity(boundary), str(row["artifact_id"])),
        ).fetchall()
        return tuple(str(item["query_fingerprint"]) for item in fingerprint_rows) == tuple(
            fingerprint.hex
            # Pass fingerprint explicitly so tuple receives a reviewable hex and query
            # fingerprints input in sqlite shard ledger row matches.
            for fingerprint in boundary.query_fingerprints
            # Complete tuple only after its hex and query fingerprints inputs are visible in
            # sqlite shard ledger row matches.
        )


__all__ = ["SQLiteShardLedger"]


def _same_artifact(left: CommittedArtifact, right: CommittedArtifact) -> bool:
    # Execute the same artifact workflow in explicit, reviewable steps.
    return (
        left.artifact_id.hex == right.artifact_id.hex
        and left.kind is right.kind
        and left.manifest_digest.hex == right.manifest_digest.hex
        and left.build_key.hex == right.build_key.hex
        # Include tuple in the completed same artifact result.
        and tuple(item.hex for item in left.input_artifact_ids)
        == tuple(item.hex for item in right.input_artifact_ids)
    )
