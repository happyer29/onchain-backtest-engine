# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import (
    LocalArtifactRepository,
    LocalCommittedArtifactScanner,
)
from backtest.adapters.artifacts.localfs.repository import (
    # Include artifact integrity error so the repository dependency remains explicit.
    ArtifactIntegrityError,
    ArtifactNotCommittedError,
)
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.schema import (
    # Include latest schema version so the schema dependency remains explicit.
    LATEST_SCHEMA_VERSION,
    connect,
    initialize,
    schema_version,
)

# Import catalog models at the visible module dependency boundary.
from backtest.application.catalog_models import (
    ArtifactCatalogStatus,
    ArtifactCatalogVerificationError,
    BuildKeyCollisionError,
)

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.ports.catalog import RunListCursor
from backtest.domain.identifiers import ArtifactId, ContentDigest, LogicalRunId


def _publish(
    repository: LocalArtifactRepository,
    *,
    # Keep the payload input explicit in the publish contract.
    payload: bytes,
    build_key: str,
    kind: ArtifactKind = ArtifactKind.SOURCE_INSPECTION,
    inputs: tuple[ArtifactId, ...] = (),
    manifest_bytes: bytes = b'{"version":1}',
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=ContentDigest(build_key),
            input_artifact_ids=inputs,
            # Complete ArtifactDraft only after its content digest and kind inputs are visible
            # in publish.
        )
    )
    with writer.open_binary("data.bin") as stream:
        stream.write(payload)
    return writer.commit(manifest_bytes)


def _seed_queryable_run_row(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    manifest_digest: str,
    build_key: str,
    attempt_id: str,
    completed_at_ns: int,
) -> None:
    """Seed one internally consistent projection row for transaction-race tests."""

    connection.execute(
        """
        INSERT INTO artifact_index (
            artifact_id, kind, manifest_digest, build_key, status,
            status_reason, indexed_at_ns, verified_at_ns
        ) VALUES (?, 'RUN', ?, ?, 'VERIFIED', NULL, 1, 1)
        """,
        (artifact_id, manifest_digest, build_key),
    )
    # The verified mapping is part of the completeness proof read by list_runs.
    connection.execute(
        """
        INSERT INTO build_key_mapping (
            build_key, artifact_id, status, first_seen_at_ns, updated_at_ns
        ) VALUES (?, ?, 'VERIFIED', 1, 1)
        """,
        (build_key, artifact_id),
    )
    connection.execute(
        """
        INSERT INTO run_index (
            artifact_id, manifest_digest, is_queryable, logical_run_id,
            execution_attempt_id, started_at_ns, completed_at_ns
        ) VALUES (?, ?, 1, ?, ?, 10, ?)
        """,
        (artifact_id, manifest_digest, "1" * 64, attempt_id, completed_at_ns),
    )


# Define test schema migrations are versioned and include recovery tables as one focused
# operation with an explicit boundary.
def test_schema_migrations_are_versioned_and_include_recovery_tables(
    tmp_path: Path,
) -> None:
    # Execute the test schema migrations are versioned and include recovery tables
    # workflow in explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"

    initialize(database, busy_timeout_seconds=1.0)

    assert schema_version(database) == LATEST_SCHEMA_VERSION
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test schema migrations are versioned and include recovery
        # tables operation before explicit failure handling.
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        # Invoke close as a visible step within the test schema migrations are versioned
        # and include recovery tables workflow.
        connection.close()
    assert {
        "artifact_index",
        "build_key_mapping",
        "lineage_edges",
        # Keep the pins expectation tied to tables, artifact index and build key mapping
        # in this scenario.
        "pins",
        "shard_ledger",
        "source_frontiers",
        "completion_receipts",
        "job_events",
        "run_index_state",
        "run_index",
        # Controller restart evidence is rebuildable operational metadata only.
        "artifact_reconciliation_state",
        # Keep the tables expectation tied to tables, artifact index and build key mapping in
        # this scenario.
    } <= tables


def test_newer_schema_version_fails_closed(tmp_path: Path) -> None:
    # Execute the test newer schema version fails closed workflow in explicit, reviewable
    # steps.
    database = tmp_path / "catalog.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(RuntimeError, match="newer"):
        # Invoke initialize for database as a visible test newer schema version fails
        # closed step.
        initialize(database, busy_timeout_seconds=1.0)


def test_catalog_lookup_reverifies_bytes_and_lineage(tmp_path: Path) -> None:
    # Execute the test catalog lookup reverifies bytes and lineage workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    parent = _publish(repository, payload=b"parent", build_key="1" * 64)
    child = _publish(
        repository,
        # Pass payload explicitly so _publish receives a reviewable 2 and snapshot input
        # in test catalog lookup reverifies bytes and lineage.
        payload=b"child",
        build_key="2" * 64,
        kind=ArtifactKind.SNAPSHOT,
        inputs=(parent.artifact_id,),
    )

    # Invoke index_committed for parent as a visible test catalog lookup reverifies bytes
    # and lineage step.
    catalog.index_committed(parent)
    catalog.index_committed(child)

    assert catalog.find_committed(child.artifact_id) == child
    assert catalog.find_by_build_key(child.build_key) == child
    assert catalog.lineage_inputs(child.artifact_id) == (parent.artifact_id,)

    # Assemble payload path once so the test catalog lookup reverifies bytes and lineage
    # workflow shares one value.
    payload_path = repository.data_root / "source-inspections" / parent.artifact_id.hex / "data.bin"
    payload_path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        catalog.find_committed(child.artifact_id)


def test_catalog_read_stays_read_only_until_controller_indexes_child_output(
    # Keep the tmp path input explicit in the test catalog read stays read only until
    # controller indexes child output contract.
    tmp_path: Path,
) -> None:
    # Execute the test catalog read stays read only until controller indexes child output
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    artifact = _publish(repository, payload=b"child-output", build_key="9" * 64)

    assert catalog.status(artifact.artifact_id) is None
    assert catalog.find_committed(artifact.artifact_id) is None

    # Invoke index_committed for artifact as a visible test catalog read stays read only
    # until controller indexes child output step.
    catalog.index_committed(artifact)

    assert catalog.find_committed(artifact.artifact_id) == artifact
    assert catalog.status(artifact.artifact_id) is ArtifactCatalogStatus.VERIFIED


def test_catalog_refuses_uncommitted_or_forged_descriptor(tmp_path: Path) -> None:
    # Execute the test catalog refuses uncommitted or forged descriptor workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    forged = CommittedArtifact(
        artifact_id=ArtifactId("a" * 64),
        kind=ArtifactKind.SNAPSHOT,
        # Keep the content digest and b ContentDigest step visible while building forged.
        manifest_digest=ContentDigest("b" * 64),
        build_key=ContentDigest("c" * 64),
    )

    with pytest.raises(ArtifactNotCommittedError):
        catalog.index_committed(forged)

    # Assemble committed once so the test catalog refuses uncommitted or forged descriptor
    # workflow shares one value.
    committed = _publish(repository, payload=b"real", build_key="1" * 64)
    mismatched = CommittedArtifact(
        artifact_id=committed.artifact_id,
        kind=committed.kind,
        manifest_digest=committed.manifest_digest,
        # Keep the content digest ContentDigest step visible while building mismatched.
        build_key=ContentDigest("2" * 64),
    )
    with pytest.raises(ArtifactCatalogVerificationError):
        catalog.index_committed(mismatched)


def test_digest_display_prefixes_do_not_change_catalog_identity(tmp_path: Path) -> None:
    # Execute the test digest display prefixes do not change catalog identity workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    committed = _publish(repository, payload=b"real", build_key="1" * 64)
    prefixed = CommittedArtifact(
        artifact_id=ArtifactId(f"sha256:{committed.artifact_id.hex}"),
        # Pass kind explicitly so CommittedArtifact receives a reviewable sha256: and hex
        # input in test digest display prefixes do not change catalog identity.
        kind=committed.kind,
        manifest_digest=ContentDigest(f"sha256:{committed.manifest_digest.hex}"),
        build_key=ContentDigest(f"sha256:{committed.build_key.hex}"),
        input_artifact_ids=committed.input_artifact_ids,
    )

    # Invoke index_committed for prefixed as a visible test digest display prefixes do not
    # change catalog identity step.
    catalog.index_committed(prefixed)

    assert catalog.find_committed(committed.artifact_id) == committed


def test_build_key_collision_quarantines_both_catalog_entries(tmp_path: Path) -> None:
    # Execute the test build key collision quarantines both catalog entries workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    first = _publish(repository, payload=b"first", build_key="1" * 64)
    second = _publish(repository, payload=b"second", build_key="1" * 64)

    catalog.index_committed(first)
    # Acquire raises, build key collision error and pytest at an explicit test build key
    # collision quarantines both catalog entries context boundary so cleanup remains
    # scoped.
    with pytest.raises(BuildKeyCollisionError) as raised:
        catalog.index_committed(second)

    assert raised.value.artifact_ids == tuple(
        sorted((first.artifact_id, second.artifact_id), key=lambda item: item.hex)
    )
    # Verify the quarantined, status and artifact id relationship before this scenario is
    # accepted.
    assert catalog.status(first.artifact_id) is ArtifactCatalogStatus.QUARANTINED
    assert catalog.status(second.artifact_id) is ArtifactCatalogStatus.QUARANTINED
    assert catalog.find_committed(first.artifact_id) is None
    assert catalog.find_committed(second.artifact_id) is None
    assert catalog.find_by_build_key(first.build_key) is None


# Define test concurrent build key collision has no verified winner as one focused
# operation with an explicit boundary.
def test_concurrent_build_key_collision_has_no_verified_winner(tmp_path: Path) -> None:
    # Execute the test concurrent build key collision has no verified winner workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    first = _publish(repository, payload=b"first", build_key="1" * 64)
    second = _publish(repository, payload=b"second", build_key="1" * 64)

    def index(artifact: CommittedArtifact) -> str:
        # Execute the index workflow in explicit, reviewable steps.
        catalog = SQLiteArtifactCatalog(database, repository)
        try:
            catalog.index_committed(artifact)
        except BuildKeyCollisionError:
            return "collision"
        # Return the completed index result without a hidden fallback.
        return "indexed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(index, (first, second)))

    catalog = SQLiteArtifactCatalog(database, repository)
    assert sorted(outcomes) == ["collision", "indexed"]
    # Verify the quarantined, status and artifact id relationship before this scenario is
    # accepted.
    assert catalog.status(first.artifact_id) is ArtifactCatalogStatus.QUARANTINED
    assert catalog.status(second.artifact_id) is ArtifactCatalogStatus.QUARANTINED
    assert catalog.find_by_build_key(first.build_key) is None


def test_rebuild_discovers_verified_files_and_preserves_queue_tables(tmp_path: Path) -> None:
    # Execute the test rebuild discovers verified files and preserves queue tables
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    first = _publish(repository, payload=b"first", build_key="1" * 64)
    second = _publish(repository, payload=b"second", build_key="2" * 64)
    # Invoke index_committed for first as a visible test rebuild discovers verified files
    # and preserves queue tables step.
    catalog.index_committed(first)

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test rebuild discovers verified files and preserves queue
        # tables operation before explicit failure handling.
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, command_type, idempotency_key, request_digest,
                resolved_spec, state, state_version, cancel_requested,
                current_attempt_id, submitted_at_ns, updated_at_ns
            ) VALUES (
                'job-preserved', 'RUN_BACKTEST', 'preserved', 'digest',
                X'00', 'QUEUED', 0, 0, NULL, 1, 1
            )
            """
        )
        connection.execute("DELETE FROM build_key_mapping")
        # Invoke execute for delete from lineage edges as a visible test rebuild discovers
        # verified files and preserves queue tables step.
        connection.execute("DELETE FROM lineage_edges")
        connection.execute("DELETE FROM artifact_index")
        connection.execute("COMMIT")
    finally:
        connection.close()

    # Assemble report once so the test rebuild discovers verified files and preserves
    # queue tables workflow shares one value.
    report = catalog.rebuild_index(LocalCommittedArtifactScanner(repository).scan())

    assert report.indexed_artifacts == 2
    assert report.quarantined_artifacts == 0
    assert catalog.find_committed(first.artifact_id) == first
    assert catalog.find_committed(second.artifact_id) == second
    # Assemble connection once so the test rebuild discovers verified files and preserves
    # queue tables workflow shares one value.
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test rebuild discovers verified files and preserves queue
        # tables operation before explicit failure handling.
        preserved = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE job_id = 'job-preserved'"
        ).fetchone()
    finally:
        connection.close()
    # Verify preserved is not None before this scenario is accepted.
    assert preserved is not None
    assert int(preserved[0]) == 1


def test_rebuild_rediscovers_build_key_collision(tmp_path: Path) -> None:
    # Execute the test rebuild rediscovers build key collision workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    first = _publish(repository, payload=b"first", build_key="1" * 64)
    second = _publish(repository, payload=b"second", build_key="1" * 64)

    report = catalog.rebuild_index(LocalCommittedArtifactScanner(repository).scan())

    # Verify report.indexed_artifacts == 2 before this scenario is accepted.
    assert report.indexed_artifacts == 2
    assert report.quarantined_artifacts == 2
    assert report.conflicting_build_keys == 1
    assert catalog.find_committed(first.artifact_id) is None
    assert catalog.find_committed(second.artifact_id) is None


# Define test failed rebuild does not erase previous verified index as one focused
# operation with an explicit boundary.
def test_failed_rebuild_does_not_erase_previous_verified_index(tmp_path: Path) -> None:
    # Execute the test failed rebuild does not erase previous verified index workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    retained = _publish(repository, payload=b"retained", build_key="1" * 64)
    corrupt = _publish(repository, payload=b"corrupt", build_key="2" * 64)
    catalog.index_committed(retained)
    # Assemble corrupt payload once so the test failed rebuild does not erase previous
    # verified index workflow shares one value.
    corrupt_payload = (
        repository.data_root / "source-inspections" / corrupt.artifact_id.hex / "data.bin"
    )
    corrupt_payload.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        # Invoke rebuild_index for retained and corrupt as a visible test failed rebuild
        # does not erase previous verified index step.
        catalog.rebuild_index((retained, corrupt))

    assert catalog.find_committed(retained.artifact_id) == retained


def test_lookup_fails_closed_when_mapping_index_is_incomplete(tmp_path: Path) -> None:
    # Execute the test lookup fails closed when mapping index is incomplete workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    artifact = _publish(repository, payload=b"artifact", build_key="1" * 64)
    catalog.index_committed(artifact)
    # Assemble connection once so the test lookup fails closed when mapping index is
    # incomplete workflow shares one value.
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test lookup fails closed when mapping index is incomplete
        # operation before explicit failure handling.
        connection.execute(
            "DELETE FROM build_key_mapping WHERE build_key = ?",
            (artifact.build_key.hex,),
        )
    finally:
        # Invoke close as a visible step within the test lookup fails closed when mapping
        # index is incomplete workflow.
        connection.close()

    assert catalog.find_committed(artifact.artifact_id) is None


def test_run_page_uses_one_snapshot_while_another_connection_dirties_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent mutation cannot splice validation and pagination snapshots."""

    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    newest_id = "a" * 64
    older_id = "b" * 64
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _seed_queryable_run_row(
            connection,
            artifact_id=newest_id,
            manifest_digest="c" * 64,
            build_key="e" * 64,
            attempt_id="2" * 64,
            completed_at_ns=300,
        )
        # A second valid row proves that an interleaved reorder changes the page.
        _seed_queryable_run_row(
            connection,
            artifact_id=older_id,
            manifest_digest="d" * 64,
            build_key="f" * 64,
            attempt_id="3" * 64,
            completed_at_ns=200,
        )
        connection.execute("UPDATE run_index_state SET status = 'COMPLETE' WHERE singleton = 1")
        connection.execute("COMMIT")
    finally:
        connection.close()

    original_verify = SQLiteArtifactCatalog._verify_run_index_rows
    mutation_applied = False

    def mutate_after_complete_check(reader: sqlite3.Connection) -> None:
        nonlocal mutation_applied
        if mutation_applied:
            original_verify(reader)
            return
        mutation_applied = True
        writer = connect(database, busy_timeout_seconds=1.0)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("DELETE FROM run_index WHERE artifact_id = ?", (newest_id,))
            writer.execute(
                """
                INSERT INTO run_index (
                    artifact_id, manifest_digest, is_queryable, logical_run_id,
                    execution_attempt_id, started_at_ns, completed_at_ns
                ) VALUES (?, ?, 1, ?, ?, 10, 100)
                """,
                (newest_id, "c" * 64, "1" * 64, "2" * 64),
            )
            writer.execute("COMMIT")
        finally:
            writer.close()
        # The reader must continue against the pre-mutation COMPLETE snapshot.
        original_verify(reader)

    monkeypatch.setattr(
        SQLiteArtifactCatalog,
        "_verify_run_index_rows",
        staticmethod(mutate_after_complete_check),
    )

    page = catalog.list_runs(limit=1, offset=0)

    assert tuple(entry.artifact_id.hex for entry in page) == (newest_id,)
    with pytest.raises(ArtifactCatalogVerificationError, match="incomplete"):
        catalog.list_runs(limit=1, offset=0)


def test_run_keyset_page_does_not_shift_after_newer_index_insert(tmp_path: Path) -> None:
    """A Run continuation remains stable while a newer artifact is committed."""

    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = (
            ("a", "1", "4", "7", 300),
            ("b", "2", "5", "8", 200),
            ("c", "3", "6", "9", 100),
        )
        for artifact, manifest, build_key, attempt, completion in rows:
            # Seed exact distinct keys in the same global completion order as production.
            _seed_queryable_run_row(
                connection,
                artifact_id=artifact * 64,
                manifest_digest=manifest * 64,
                build_key=build_key * 64,
                attempt_id=attempt * 64,
                completed_at_ns=completion,
            )
        connection.execute("UPDATE run_index_state SET status = 'COMPLETE' WHERE singleton = 1")
        connection.execute("COMMIT")
    finally:
        connection.close()

    first = catalog.list_runs(limit=2, offset=0)
    cursor = RunListCursor(first[-1].completed_at_ns, first[-1].artifact_id)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        # This row belongs ahead of the prior page and must not shift its continuation.
        _seed_queryable_run_row(
            connection,
            artifact_id="d" * 64,
            manifest_digest="e" * 64,
            build_key="f" * 64,
            attempt_id="0" * 64,
            completed_at_ns=400,
        )
        connection.execute("UPDATE run_index_state SET status = 'COMPLETE' WHERE singleton = 1")
        connection.execute("COMMIT")
    finally:
        connection.close()

    second = catalog.list_runs(limit=2, offset=0, after=cursor)

    assert tuple(item.artifact_id.hex for item in first) == ("a" * 64, "b" * 64)
    assert tuple(item.artifact_id.hex for item in second) == ("c" * 64,)
    # Legacy offset demonstrates the insertion shift that the keyset avoids.
    shifted = catalog.list_runs(limit=2, offset=2)
    assert tuple(item.artifact_id.hex for item in shifted) == ("b" * 64, "c" * 64)


def test_run_list_rejects_pathological_or_wrong_scope_cursor(tmp_path: Path) -> None:
    """SQLite rejects oversized scans and cursor/filter ambiguity before query."""

    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(tmp_path / "catalog.sqlite", repository)
    cursor = RunListCursor(1, ArtifactId("a" * 64))

    with pytest.raises(ValueError, match="between 0 and 10000"):
        catalog.list_runs(limit=1, offset=10_001)
    with pytest.raises(ValueError, match="cannot use offset"):
        catalog.list_runs(limit=1, offset=1, after=cursor)
    with pytest.raises(ValueError, match="match the scope"):
        catalog.list_logical_runs(
            LogicalRunId("b" * 64),
            limit=1,
            offset=0,
            after=cursor,
        )


def test_rebuild_records_legacy_run_as_explicitly_unqueryable(tmp_path: Path) -> None:
    """A verified non-v3 Run is retained but cannot affect typed result pages."""

    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    legacy_manifest = (
        b'{"artifact_schema":"legacy-run/v1",'
        b'"execution_attempt_id":"' + b"2" * 64 + b'",'
        b'"logical_run_id":"' + b"1" * 64 + b'"}'
    )
    legacy = _publish(
        repository,
        payload=b"legacy-run",
        build_key="7" * 64,
        kind=ArtifactKind.RUN,
        manifest_bytes=legacy_manifest,
    )

    report = catalog.rebuild_index((legacy,))

    assert report.indexed_artifacts == 1
    assert catalog.list_runs(limit=10, offset=0) == ()
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        row = connection.execute(
            "SELECT * FROM run_index WHERE artifact_id = ?",
            (legacy.artifact_id.hex,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert int(row["is_queryable"]) == 0
    assert row["logical_run_id"] is None
    assert row["execution_attempt_id"] is None
    assert row["started_at_ns"] is None
    assert row["completed_at_ns"] is None
