# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backtest.adapters.catalog.sqlite.job_queue import SQLiteJobQueue

# Import schema at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.schema import (
    LATEST_SCHEMA_VERSION,
    SQLiteSchemaError,
    connect,
    initialize,
    # Include schema version so the schema dependency remains explicit.
    schema_version,
)

_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "sqlite"
_EXPECTED_TABLES_BY_VERSION = {
    1: {"job_attempts", "jobs"},
    # Complete the expected tables by version group only after its semantic components are
    # visible.
    2: {
        "artifact_build_conflicts",
        "artifact_index",
        "build_key_mapping",
        "completion_receipt_outputs",
        # Keep the completion receipts component named inside the expected tables by
        # version contract.
        "completion_receipts",
        "job_attempts",
        "job_events",
        "jobs",
        "lineage_edges",
        # Keep the pin roots component named inside the expected tables by version
        # contract.
        "pin_roots",
        "pins",
        "shard_ledger",
        "shard_query_fingerprints",
        "source_frontiers",
        # Complete the expected tables by version group only after its semantic components are
        # visible.
    },
    3: {
        "artifact_build_conflicts",
        "artifact_index",
        "attempt_failures",
        # Keep the attempt runtime component named inside the expected tables by version
        # contract.
        "attempt_runtime",
        "build_key_mapping",
        "completion_receipt_outputs",
        "completion_receipts",
        "job_attempts",
        # Keep the job events component named inside the expected tables by version
        # contract.
        "job_events",
        "job_retry_schedule",
        "jobs",
        "lineage_edges",
        "pin_roots",
        # Keep the pins component named inside the expected tables by version contract.
        "pins",
        "shard_ledger",
        "shard_query_fingerprints",
        "source_frontiers",
    },
    # Complete the expected tables by version group only after its semantic components are
    # visible.
    4: {
        "artifact_build_conflicts",
        "artifact_index",
        "attempt_failures",
        "attempt_runtime",
        # Keep the build key mapping component named inside the expected tables by version
        # contract.
        "build_key_mapping",
        "completion_receipt_outputs",
        "completion_receipts",
        "job_attempts",
        "job_events",
        # Keep the job retry schedule component named inside the expected tables by
        # version contract.
        "job_retry_schedule",
        "jobs",
        "lineage_edges",
        "pin_roots",
        "pins",
        # Keep the shard ledger component named inside the expected tables by version
        # contract.
        "shard_ledger",
        "shard_query_fingerprints",
        "source_frontiers",
    },
}

# Keep the row step explicit within the module workflow.
type _Row = tuple[object, ...]
type _TableSnapshot = dict[str, tuple[tuple[str, ...], tuple[_Row, ...]]]


def _load_frozen_fixture(database: Path, version: int) -> None:
    # Execute the load frozen fixture workflow in explicit, reviewable steps.
    script = (_FIXTURE_ROOT / f"catalog_v{version}.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.executescript(script)
    finally:
        # Invoke close as a visible step within the load frozen fixture workflow.
        connection.close()


def _user_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    # Execute the user tables workflow in explicit, reviewable steps.
    return tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        # Complete tuple only after its execute and str inputs are visible in user tables.
    )


def _snapshot_tables(
    connection: sqlite3.Connection,
    table_names: tuple[str, ...] | None = None,
) -> _TableSnapshot:
    # Execute the snapshot tables workflow in explicit, reviewable steps.
    selected = _user_tables(connection) if table_names is None else table_names
    snapshot: _TableSnapshot = {}
    for table_name in selected:
        # Process selected inside the bounded snapshot tables loop.
        columns = tuple(
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        )
        projection = ", ".join(f'"{column}"' for column in columns)
        rows = tuple(
            # Keep the sorted and repr sorted step visible while building rows.
            sorted(
                (
                    tuple(row)
                    for row in connection.execute(f'SELECT {projection} FROM "{table_name}"')
                ),
                # Pass key explicitly so sorted receives a reviewable select and from "
                # input in snapshot tables.
                key=repr,
            )
        )
        snapshot[table_name] = (columns, rows)
    return snapshot


# Define test connect closes partially configured connection as one focused operation with
# an explicit boundary.
def test_connect_closes_partially_configured_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test connect closes partially configured connection workflow in
    # explicit, reviewable steps.
    class _BrokenConnection:
        row_factory: object | None = None
        closed = False

        def execute(self, statement: str) -> None:
            # Execute the broken connection execute workflow in explicit, reviewable
            # steps.
            del statement
            raise sqlite3.DatabaseError("injected pragma failure")

        def close(self) -> None:
            self.closed = True

    broken = _BrokenConnection()
    # Invoke setattr for connect and sqlite3 as a visible test connect closes partially
    # configured connection step.
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: broken)

    with pytest.raises(sqlite3.DatabaseError, match="injected pragma failure"):
        connect(tmp_path / "catalog.sqlite", busy_timeout_seconds=1.0)

    assert broken.closed


@pytest.mark.parametrize("version", (1, 2, 3, 4))
# Define test frozen historical schema migrates to latest without losing authoritative rows as
# one focused operation with an explicit boundary.
def test_frozen_historical_schema_migrates_to_latest_without_losing_authoritative_rows(
    tmp_path: Path,
    version: int,
) -> None:
    # Execute the test frozen historical schema migrates to latest without losing
    # authoritative rows workflow in explicit, reviewable steps.
    database = tmp_path / f"catalog-v{version}.sqlite"
    _load_frozen_fixture(database, version)
    before_connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test frozen historical schema migrates to v6 without
        # losing authoritative rows operation before explicit failure handling.
        assert set(_user_tables(before_connection)) == _EXPECTED_TABLES_BY_VERSION[version]
        assert before_connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 4
        assert before_connection.execute("SELECT COUNT(*) FROM job_attempts").fetchone()[0] == 3
        assert before_connection.execute("PRAGMA foreign_key_check").fetchall() == []
        before = _snapshot_tables(before_connection)
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        before_connection.close()

    initialize(database, busy_timeout_seconds=1.0)
    initialize(database, busy_timeout_seconds=1.0)

    migrated = connect(database, busy_timeout_seconds=1.0)
    # Keep expected failures inside the test frozen historical schema migrates to v6
    # without losing authoritative rows error boundary.
    try:
        # Perform the protected test frozen historical schema migrates to v6 without
        # losing authoritative rows operation before explicit failure handling.
        rebuilt_source_indexes = {
            "shard_ledger",
            "shard_query_fingerprints",
            "source_frontiers",
        }
        # Traverse before.items() explicitly so each test frozen historical schema
        # migrates to v6 without losing authoritative rows iteration remains traceable.
        for table_name, (columns, rows) in before.items():
            # Process before.items() inside the bounded test frozen historical schema
            # migrates to v6 without losing authoritative rows loop.
            if table_name in rebuilt_source_indexes:
                # Handle the test frozen historical schema migrates to v6 without losing
                # authoritative rows table_name in rebuilt_source_indexes branch as a
                # distinct logical block.
                assert migrated.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0] == 0
                continue
            migrated_columns = _snapshot_tables(migrated, (table_name,))[table_name][0]
            assert migrated_columns[: len(columns)] == columns
            projection = ", ".join(f'"{column}"' for column in columns)
            # Assemble projected rows once so the test frozen historical schema migrates
            # to v6 without losing authoritative rows workflow shares one value.
            projected_rows = tuple(
                sorted(
                    (
                        tuple(row)
                        for row in migrated.execute(f'SELECT {projection} FROM "{table_name}"')
                        # Complete sorted only after its select and from " inputs are visible
                        # in test frozen historical schema migrates to v6 without losing
                        # authoritative rows.
                    ),
                    key=repr,
                )
            )
            assert projected_rows == rows
        # Verify the latest schema version, fetchone and execute relationship before this
        # scenario is accepted.
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            # Keep raises, integrity error and pytest active only for the bounded test
            # frozen historical schema migrates to latest without losing authoritative rows
            # operation.
            migrated.execute(
                "UPDATE jobs SET resolved_spec = X'00' WHERE job_id = ?",
                (f"job-v{version}-queued",),
            )
    finally:
        # Invoke close as a visible step within the test frozen historical schema migrates
        # to v6 without losing authoritative rows workflow.
        migrated.close()

    queue = SQLiteJobQueue(database, busy_timeout_seconds=1.0)
    assert {record.job_id.value for record in queue.list_jobs()} == {
        f"job-v{version}-queued",
        f"job-v{version}-retry",
        # Keep the job-v version running expectation tied to value, job id and record in
        # this scenario.
        f"job-v{version}-running",
        f"job-v{version}-succeeded",
    }


def test_v6_to_latest_preserves_shard_rows_and_query_fingerprints(tmp_path: Path) -> None:
    """Later migrations retain the rebuildable physical-variant source index."""

    assert LATEST_SCHEMA_VERSION == 10
    database = tmp_path / "catalog-v6.sqlite"
    initialize(database, busy_timeout_seconds=1.0)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        # Remove later projection/session tables before reconstructing exact v6.
        connection.execute("DROP INDEX jobs_list_submitted_idx")
        connection.execute("DROP INDEX jobs_state_list_submitted_idx")
        connection.execute("DROP TABLE artifact_reconciliation_state")
        connection.execute("DROP TABLE run_index")
        connection.execute("DROP TABLE run_index_state")
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP TABLE shard_query_fingerprints;
            DROP TABLE shard_ledger;

            CREATE TABLE shard_ledger (
                source_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                capability_schema_version TEXT NOT NULL,
                network_id TEXT NOT NULL,
                position_schema_id TEXT NOT NULL,
                from_block_ordinal INTEGER NOT NULL CHECK (from_block_ordinal >= 0),
                to_block_ordinal INTEGER NOT NULL CHECK (
                    to_block_ordinal > from_block_ordinal
                ),
                internal_revision TEXT NOT NULL CHECK (length(internal_revision) = 64),
                artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
                snapshot_cut_to_block INTEGER NOT NULL CHECK (
                    snapshot_cut_to_block = to_block_ordinal
                ),
                chain_finality TEXT NOT NULL,
                ingestion_watermark_to_block INTEGER,
                upstream_revision TEXT,
                source_consistency TEXT NOT NULL,
                completeness TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                committed_at_ns INTEGER NOT NULL CHECK (committed_at_ns >= 0),
                PRIMARY KEY (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision
                ),
                UNIQUE (artifact_id),
                CHECK (
                    ingestion_watermark_to_block IS NULL
                    OR ingestion_watermark_to_block >= 0
                )
            );

            CREATE TABLE shard_query_fingerprints (
                source_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                capability_schema_version TEXT NOT NULL,
                network_id TEXT NOT NULL,
                position_schema_id TEXT NOT NULL,
                from_block_ordinal INTEGER NOT NULL,
                to_block_ordinal INTEGER NOT NULL,
                internal_revision TEXT NOT NULL,
                query_fingerprint TEXT NOT NULL CHECK (length(query_fingerprint) = 64),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                PRIMARY KEY (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision,
                    query_fingerprint
                ),
                UNIQUE (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision, ordinal
                ),
                FOREIGN KEY (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision
                ) REFERENCES shard_ledger (
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision
                ) ON DELETE CASCADE
            );

            CREATE INDEX shard_ledger_frontier_idx
                ON shard_ledger(
                    source_id, capability_id, capability_schema_version,
                    network_id, position_schema_id,
                    from_block_ordinal, to_block_ordinal, internal_revision
                );

            INSERT INTO shard_ledger VALUES (
                'source-v6', 'swaps.v1', 'v1', 'solana:genesis-v6',
                'block32-transaction32-v1', 10, 20,
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                20, 'FINALIZED', 20, 'upstream-v6', 'SNAPSHOT',
                'PROVEN_COMPLETE', 'PASS', 123
            );
            INSERT INTO shard_query_fingerprints VALUES (
                'source-v6', 'swaps.v1', 'v1', 'solana:genesis-v6',
                'block32-transaction32-v1', 10, 20,
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                0
            );
            PRAGMA user_version = 6;
            COMMIT;
            """
        )
    finally:
        connection.close()

    initialize(database, busy_timeout_seconds=1.0)
    initialize(database, busy_timeout_seconds=1.0)

    migrated = connect(database, busy_timeout_seconds=1.0)
    try:
        row = migrated.execute("SELECT * FROM shard_ledger").fetchone()
        fingerprint = migrated.execute("SELECT * FROM shard_query_fingerprints").fetchone()
        assert row is not None
        assert fingerprint is not None
        assert str(row["artifact_id"]) == "a" * 64
        assert str(row["internal_revision"]) == "c" * 64
        assert str(fingerprint["artifact_id"]) == "a" * 64
        assert str(fingerprint["query_fingerprint"]) == "b" * 64
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 10
        assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
        primary_key_columns = tuple(
            str(item["name"])
            for item in sorted(
                (
                    item
                    for item in migrated.execute("PRAGMA table_info(shard_ledger)")
                    if int(item["pk"]) > 0
                ),
                key=lambda item: int(item["pk"]),
            )
        )
        assert primary_key_columns[-2:] == ("internal_revision", "artifact_id")
    finally:
        migrated.close()


def test_v7_to_v8_adds_empty_manifest_bound_run_projection(tmp_path: Path) -> None:
    """Migration never guesses ordering metadata from an unparsed legacy index row."""

    database = tmp_path / "catalog-v7.sqlite"
    initialize(database, busy_timeout_seconds=1.0)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Reconstruct the state that genuinely existed before migration v8.
        connection.execute("DROP INDEX jobs_list_submitted_idx")
        connection.execute("DROP INDEX jobs_state_list_submitted_idx")
        connection.execute("DROP TABLE artifact_reconciliation_state")
        connection.execute("DROP TABLE run_index")
        connection.execute("DROP TABLE run_index_state")
        connection.execute("PRAGMA user_version = 7")
    finally:
        connection.close()

    initialize(database, busy_timeout_seconds=1.0)

    migrated = connect(database, busy_timeout_seconds=1.0)
    try:
        columns = tuple(
            str(row["name"]) for row in migrated.execute("PRAGMA table_info(run_index)")
        )
        assert columns == (
            "artifact_id",
            "manifest_digest",
            "is_queryable",
            "logical_run_id",
            # Physical-attempt identity completes stale-projection detection.
            "execution_attempt_id",
            "started_at_ns",
            "completed_at_ns",
        )
        assert migrated.execute("SELECT COUNT(*) FROM run_index").fetchone()[0] == 0
        state = migrated.execute("SELECT status, generation FROM run_index_state").fetchone()
        assert tuple(state) == ("COMPLETE", 0)
        reconciliation = migrated.execute(
            "SELECT status, inventory_digest, artifact_count FROM artifact_reconciliation_state"
        ).fetchone()
        assert tuple(reconciliation) == ("UNCLEAN", None, None)
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        migrated.close()


def test_v7_to_v8_marks_existing_verified_runs_dirty_until_rebuild(tmp_path: Path) -> None:
    """Migration does not claim complete ordering for unparsed historical Runs."""

    database = tmp_path / "catalog-v7-with-run.sqlite"
    initialize(database, busy_timeout_seconds=1.0)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("DROP INDEX jobs_list_submitted_idx")
        connection.execute("DROP INDEX jobs_state_list_submitted_idx")
        connection.execute("DROP TABLE artifact_reconciliation_state")
        connection.execute("DROP TABLE run_index")
        connection.execute("DROP TABLE run_index_state")
        connection.execute(
            """
            INSERT INTO artifact_index (
                artifact_id, kind, manifest_digest, build_key, status,
                status_reason, indexed_at_ns, verified_at_ns
            ) VALUES (?, 'RUN', ?, ?, 'VERIFIED', NULL, 1, 1)
            """,
            ("a" * 64, "b" * 64, "c" * 64),
        )
        # Preserve the v7 catalog relationship that makes the Run discoverable.
        connection.execute(
            """
            INSERT INTO build_key_mapping (
                build_key, artifact_id, status, first_seen_at_ns, updated_at_ns
            ) VALUES (?, ?, 'VERIFIED', 1, 1)
            """,
            ("c" * 64, "a" * 64),
        )
        connection.execute("PRAGMA user_version = 7")
    finally:
        connection.close()

    initialize(database, busy_timeout_seconds=1.0)

    migrated = connect(database, busy_timeout_seconds=1.0)
    try:
        state = migrated.execute(
            "SELECT status, generation FROM run_index_state WHERE singleton = 1"
        ).fetchone()
        assert state is not None
        assert tuple(state) == ("DIRTY", 0)
        assert migrated.execute("SELECT COUNT(*) FROM run_index").fetchone()[0] == 0
        reconciliation = migrated.execute(
            "SELECT status, inventory_digest, artifact_count FROM artifact_reconciliation_state"
        ).fetchone()
        assert tuple(reconciliation) == ("UNCLEAN", None, None)
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        migrated.close()


def test_v9_to_v10_adds_job_list_indexes_and_invalidates_clean_receipt(
    tmp_path: Path,
) -> None:
    """The keyset migration is queryable and cannot reuse older restart evidence."""

    database = tmp_path / "catalog-v9.sqlite"
    initialize(database, busy_timeout_seconds=1.0)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Reconstruct a clean v9 catalog before the two browser-list indexes existed.
        connection.execute("DROP INDEX jobs_list_submitted_idx")
        connection.execute("DROP INDEX jobs_state_list_submitted_idx")
        connection.execute(
            """
            UPDATE artifact_reconciliation_state
            SET status = 'CLEAN', inventory_digest = ?, artifact_count = 0
            WHERE singleton = 1
            """,
            ("a" * 64,),
        )
        connection.execute("PRAGMA user_version = 9")
    finally:
        connection.close()

    initialize(database, busy_timeout_seconds=1.0)

    migrated = connect(database, busy_timeout_seconds=1.0)
    try:
        # Both complete list orders must be explicit schema objects after migration.
        indexes = {
            str(row[0])
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'jobs'"
            )
        }
        assert {"jobs_list_submitted_idx", "jobs_state_list_submitted_idx"} <= indexes
        receipt = migrated.execute(
            "SELECT status, inventory_digest, artifact_count "
            "FROM artifact_reconciliation_state WHERE singleton = 1"
        ).fetchone()
        assert tuple(receipt) == ("UNCLEAN", None, None)
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        migrated.close()


def test_mid_v3_migration_failure_rolls_back_schema_and_rows_atomically(
    tmp_path: Path,
    # Close the test mid v3 migration failure rolls back schema and rows atomically signature
    # after its explicit inputs.
) -> None:
    # Execute the test mid v3 migration failure rolls back schema and rows atomically
    # workflow in explicit, reviewable steps.
    database = tmp_path / "catalog-v3.sqlite"
    _load_frozen_fixture(database, 3)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test mid v3 migration failure rolls back schema and rows
        # atomically operation before explicit failure handling.
        original_tables = _user_tables(connection)
        before = _snapshot_tables(connection, original_tables)
        connection.execute("CREATE TABLE attempt_failures_v4 (blocker INTEGER NOT NULL)")
    finally:
        connection.close()

    # Acquire raises, operational error and pytest at an explicit test mid v3 migration
    # failure rolls back schema and rows atomically context boundary so cleanup remains
    # scoped.
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        initialize(database, busy_timeout_seconds=1.0)

    failed = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test mid v3 migration failure rolls back schema and rows
        # atomically operation before explicit failure handling.
        assert failed.execute("PRAGMA user_version").fetchone()[0] == 3
        runtime_columns = tuple(
            str(row[1]) for row in failed.execute("PRAGMA table_info(attempt_runtime)")
        )
        assert "temporary_disk_bytes" not in runtime_columns
        # Verify the output disk bytes and runtime columns relationship before this
        # scenario is accepted.
        assert "output_disk_bytes" not in runtime_columns
        assert _snapshot_tables(failed, original_tables) == before
        assert failed.execute("PRAGMA foreign_key_check").fetchall() == []
        assert "attempt_failures_v5" not in _user_tables(failed)
        failed.execute("DROP TABLE attempt_failures_v4")
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        failed.close()

    initialize(database, busy_timeout_seconds=1.0)
    assert schema_version(database) == LATEST_SCHEMA_VERSION


def test_corrupt_database_bytes_fail_closed_without_rewrite(tmp_path: Path) -> None:
    # Execute the test corrupt database bytes fail closed without rewrite workflow in
    # explicit, reviewable steps.
    database = tmp_path / "corrupt.sqlite"
    original = b"not-a-sqlite-database\x00with-private-details"
    database.write_bytes(original)

    with pytest.raises(SQLiteSchemaError, match="integrity verification failed"):
        initialize(database, busy_timeout_seconds=0.05)

    # Verify database.read_bytes() == original before this scenario is accepted.
    assert database.read_bytes() == original
    assert not database.with_name(f"{database.name}-wal").exists()


def test_incomplete_v5_schema_fails_before_journal_mode_is_changed(tmp_path: Path) -> None:
    # Execute the test incomplete v5 schema fails before journal mode is changed workflow
    # in explicit, reviewable steps.
    database = tmp_path / "incomplete-v5.sqlite"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        # Perform the protected test incomplete v5 schema fails before journal mode is
        # changed operation before explicit failure handling.
        connection.execute("CREATE TABLE incomplete_marker (value INTEGER)")
        connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()

    # Acquire raises, sqlite schema error and pytest at an explicit test incomplete v5
    # schema fails before journal mode is changed context boundary so cleanup remains
    # scoped.
    with pytest.raises(SQLiteSchemaError, match="schema verification failed"):
        initialize(database, busy_timeout_seconds=1.0)

    reopened = sqlite3.connect(database)
    try:
        # Perform the protected test incomplete v5 schema fails before journal mode is
        # changed operation before explicit failure handling.
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert reopened.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert (
            reopened.execute(
                "SELECT name FROM sqlite_master WHERE name = 'incomplete_marker'"
                # Complete fetchone only after its declared inputs are visible in test
                # incomplete v5 schema fails before journal mode is changed.
            ).fetchone()
            is not None
        )
    finally:
        reopened.close()


# Define test newer schema fails before journal mode is changed as one focused operation
# with an explicit boundary.
def test_newer_schema_fails_before_journal_mode_is_changed(tmp_path: Path) -> None:
    # Execute the test newer schema fails before journal mode is changed workflow in
    # explicit, reviewable steps.
    database = tmp_path / "newer.sqlite"
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        # Perform the protected test newer schema fails before journal mode is changed
        # operation before explicit failure handling.
        connection.execute("CREATE TABLE future_state (value INTEGER NOT NULL)")
        connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()

    # Acquire raises, sqlite schema error and pytest at an explicit test newer schema
    # fails before journal mode is changed context boundary so cleanup remains scoped.
    with pytest.raises(SQLiteSchemaError, match="newer"):
        initialize(database, busy_timeout_seconds=1.0)

    reopened = sqlite3.connect(database)
    try:
        # Perform the protected test newer schema fails before journal mode is changed
        # operation before explicit failure handling.
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == (LATEST_SCHEMA_VERSION + 1)
        assert reopened.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert reopened.execute("SELECT COUNT(*) FROM future_state").fetchone()[0] == 0
    finally:
        reopened.close()
