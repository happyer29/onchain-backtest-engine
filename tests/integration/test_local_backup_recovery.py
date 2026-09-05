# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Import threading at the visible module dependency boundary.
from threading import Event
from typing import cast

import pytest

import backtest.adapters.backup.local as backup_module
import backtest.adapters.catalog.sqlite.backup as sqlite_backup_module

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.retention import LocalRetentionRepository
from backtest.adapters.backup.local import LocalBackupRepository, LocalRestoreRepository
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.backup import SQLiteCheckpointRepository

# Import schema at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.schema import (
    LATEST_SCHEMA_VERSION,
    connect,
    initialize,
)

# Import backups at the visible module dependency boundary.
from backtest.application.backups import BackupIntegrityError
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.retention import PinRecord
from backtest.application.use_cases.manage_backups import CreateBackup, RestoreBackup
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier


# Define publish as one focused operation with an explicit boundary.
def _publish(
    repository: LocalArtifactRepository,
    *,
    payload: bytes,
    key: str,
    # Keep the kind input explicit in the publish contract.
    kind: ArtifactKind = ArtifactKind.SOURCE_INSPECTION,
    inputs: tuple[ArtifactId, ...] = (),
    identity: dict[str, object] | None = None,
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=ContentDigest(key),
            input_artifact_ids=inputs,
            # Complete ArtifactDraft only after its content digest and kind inputs are visible
            # in publish.
        )
    )
    with writer.open_binary("data.bin") as stream:
        stream.write(payload)
    placement_identity = {} if identity is None else identity
    return writer.commit(
        canonical_json_bytes({**placement_identity, "schema_version": 1}),
        identity_manifest_bytes=canonical_json_bytes(placement_identity),
    )


# Define successful job as one focused operation with an explicit boundary.
def _successful_job(database: Path, root: ArtifactId) -> None:
    # Execute the successful job workflow in explicit, reviewable steps.
    initialize(database, busy_timeout_seconds=1.0)
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected successful job operation before explicit failure handling.
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, command_type, idempotency_key, request_digest,
                resolved_spec, state, state_version, cancel_requested,
                current_attempt_id, submitted_at_ns, updated_at_ns
            ) VALUES (
                'job-1', 'RUN_BACKTEST', 'backup-test', 'digest',
                X'00', 'SUCCEEDED', 2, 0, NULL, 1, 2
            )
            """
        )
        connection.execute(
            # Keep execute, connection and hex visible while completing execute within
            # successful job.
            """
            INSERT INTO job_attempts (
                attempt_id, job_id, attempt_number, supervisor_instance_id,
                state, state_version, result_artifact_id, created_at_ns, updated_at_ns
            ) VALUES (
                'attempt-1', 'job-1', 1, 'supervisor-1',
                'SUCCEEDED', 2, ?, 1, 2
            )
            """,
            (root.hex,),
        )
        connection.execute(
            "UPDATE jobs SET current_attempt_id = 'attempt-1' WHERE job_id = 'job-1'"
            # Complete execute only after its declared inputs are visible in successful job.
        )
        connection.execute("COMMIT")
    except BaseException:
        # Translate the BaseException failure through the successful job boundary.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


# Define source as one focused operation with an explicit boundary.
def _source(
    tmp_path: Path,
) -> tuple[
    LocalArtifactRepository,
    LocalRetentionRepository,
    # Keep the path input explicit in the source contract.
    Path,
    CommittedArtifact,
    CommittedArtifact,
]:
    # Execute the source workflow in explicit, reviewable steps.
    data_root = tmp_path / "live"
    repository = LocalArtifactRepository(data_root)
    parent = _publish(
        repository,
        payload=b"parent",
        key="1" * 64,
        kind=ArtifactKind.CANONICAL_DISTRIBUTION,
        identity={"logical_content_hash": "a" * 64},
    )
    result = _publish(
        repository,
        # Pass payload explicitly so _publish receives a reviewable 2 and snapshot input
        # in source.
        payload=b"result",
        key="2" * 64,
        kind=ArtifactKind.SNAPSHOT,
        inputs=(parent.artifact_id,),
    )
    # Assemble catalog path once so the source workflow shares one value.
    catalog_path = data_root / "catalog" / "catalog.sqlite"
    _successful_job(catalog_path, result.artifact_id)
    catalog = SQLiteArtifactCatalog(catalog_path, repository)
    catalog.index_committed(parent)
    catalog.index_committed(result)
    # Assemble retention once so the source workflow shares one value.
    retention = LocalRetentionRepository(repository)
    retention.create_pin(
        pin_id=Identifier("baseline"),
        roots=(result.artifact_id,),
        reason="restore drill",
        # Pass created at ns explicitly so create_pin receives a reviewable baseline and
        # restore drill input in source.
        created_at_ns=5,
    )
    return repository, retention, catalog_path, parent, result


@pytest.mark.integration
def test_backup_generation_and_fresh_root_restore_reconcile_db_artifacts_and_pins(
    # Keep the tmp path input explicit in the test backup generation and fresh root
    # restore reconcile db artifacts and pins contract.
    tmp_path: Path,
) -> None:
    # Execute the test backup generation and fresh root restore reconcile db artifacts and
    # pins workflow in explicit, reviewable steps.
    repository, retention, catalog_path, parent, result = _source(tmp_path)
    backup_root = tmp_path / "backup-device"
    backup = LocalBackupRepository(
        repository,
        retention,
        # Pass catalog path explicitly so LocalBackupRepository receives a reviewable
        # repository and retention input in test backup generation and fresh root restore
        # reconcile db artifacts and pins.
        catalog_path,
        backup_root,
        allow_same_device_for_drill=True,
        lock_timeout_seconds=0,
    )

    # Assemble generation once so the test backup generation and fresh root restore
    # reconcile db artifacts and pins workflow shares one value.
    generation = CreateBackup(backup, clock_ns=lambda: 100).execute()

    generation_root = backup_root / "generations" / generation.backup_cut_id.hex
    assert (generation_root / "backup.json").is_file()
    assert (generation_root / "COMMITTED").is_file()
    assert (
        generation_root / "data" / "canonical" / ("a" * 64) / parent.artifact_id.hex / "COMMITTED"
    ).is_file()
    assert generation.artifact_ids == tuple(
        # Keep the key expectation tied to artifact ids, generation and sorted in this
        # scenario.
        sorted((parent.artifact_id, result.artifact_id), key=lambda item: item.hex)
    )
    restored_root = tmp_path / "restored"
    report = RestoreBackup(LocalRestoreRepository(backup_root, restored_root)).execute(
        generation.backup_cut_id
        # Complete execute only after its backup cut id and generation inputs are visible in
        # test backup generation and fresh root restore reconcile db artifacts and pins.
    )

    assert report.reconciliation_complete
    assert report.restored_artifacts == 2
    assert report.restored_job_roots == (result.artifact_id,)
    assert (restored_root / "RESTORE_RECONCILED").is_file()
    # Assemble restored repository once so the test backup generation and fresh root
    # restore reconcile db artifacts and pins workflow shares one value.
    restored_repository = LocalArtifactRepository(restored_root)
    assert (
        restored_root / "canonical" / ("a" * 64) / parent.artifact_id.hex / "COMMITTED"
    ).is_file()
    with restored_repository.open_committed(parent.artifact_id) as parent_handle:  # type: ignore[attr-defined]
        assert parent_handle.descriptor == parent
    handle = restored_repository.open_committed(result.artifact_id)
    try:
        assert handle.descriptor == result
    finally:
        # Invoke close as a visible step within the test backup generation and fresh root
        # restore reconcile db artifacts and pins workflow.
        handle.close()
    restored_retention = LocalRetentionRepository(restored_repository)
    assert restored_retention.active_pins()[0].roots == (result.artifact_id,)
    restored_catalog = SQLiteArtifactCatalog(
        restored_root / "catalog" / "catalog.sqlite",
        # Pass restored repository explicitly so SQLiteArtifactCatalog receives a
        # reviewable sqlite and catalog input in test backup generation and fresh root
        # restore reconcile db artifacts and pins.
        restored_repository,
    )
    assert restored_catalog.find_committed(result.artifact_id) == result
    connection = connect(
        restored_root / "catalog" / "catalog.sqlite",
        # Pass busy timeout seconds explicitly so connect receives a reviewable sqlite and
        # catalog input in test backup generation and fresh root restore reconcile db
        # artifacts and pins.
        busy_timeout_seconds=1.0,
    )
    try:
        # Perform the protected test backup generation and fresh root restore reconcile db
        # artifacts and pins operation before explicit failure handling.
        job = connection.execute(
            "SELECT state, current_attempt_id FROM jobs WHERE job_id = 'job-1'"
        ).fetchone()
    finally:
        connection.close()
    # Verify job is not None before this scenario is accepted.
    assert job is not None
    assert (str(job["state"]), str(job["current_attempt_id"])) == (
        "SUCCEEDED",
        "attempt-1",
    )


# Apply integration semantics to the following test backup cut coexists with an active
# artifact lease contract.
@pytest.mark.integration
def test_backup_cut_coexists_with_an_active_artifact_lease(tmp_path: Path) -> None:
    # Execute the test backup cut coexists with an active artifact lease workflow in
    # explicit, reviewable steps.
    repository, retention, catalog_path, _, result = _source(tmp_path)
    backup = LocalBackupRepository(
        repository,
        retention,
        catalog_path,
        # Pass tmp path explicitly so LocalBackupRepository receives a reviewable backup-
        # device and repository input in test backup cut coexists with an active artifact
        # lease.
        tmp_path / "backup-device",
        allow_same_device_for_drill=True,
        lock_timeout_seconds=0,
    )
    lease = retention.acquire_lease(
        # Keep the active-run Identifier step visible while building lease.
        lease_id=Identifier("active-run"),
        roots=(result.artifact_id,),
        reason="running backtest",
    )
    try:
        # Assemble generation once so the test backup cut coexists with an active artifact
        # lease workflow shares one value.
        generation = backup.create_generation(created_at_ns=100)
    finally:
        lease.close()
    assert result.artifact_id in generation.artifact_ids


@pytest.mark.integration
# Define test backup copy does not block new publication and excludes it from cut as one
# focused operation with an explicit boundary.
def test_backup_copy_does_not_block_new_publication_and_excludes_it_from_cut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test backup copy does not block new publication and excludes it from cut
    # workflow in explicit, reviewable steps.
    repository, retention, catalog_path, _, _ = _source(tmp_path)
    backup = LocalBackupRepository(
        repository,
        retention,
        catalog_path,
        # Pass tmp path explicitly so LocalBackupRepository receives a reviewable backup-
        # device and repository input in test backup copy does not block new publication
        # and excludes it from cut.
        tmp_path / "backup-device",
        allow_same_device_for_drill=True,
        lock_timeout_seconds=0,
    )
    copy_tree = backup_module.copy_tree_verified
    # Assemble published once so the test backup copy does not block new publication and
    # excludes it from cut workflow shares one value.
    published: list[CommittedArtifact] = []

    def copy_after_publication(
        source: Path,
        destination: Path,
        *,
        # Keep the expected input explicit in the copy after publication contract.
        expected: tuple[backup_module.FileRecord, ...],
    ) -> None:
        # Execute the copy after publication workflow in explicit, reviewable steps.
        if not published:
            # Handle the copy after publication not published branch as a distinct logical
            # block.
            published.append(
                _publish(
                    repository,
                    payload=b"published after the exact cut",
                    key="3" * 64,
                    # Complete _publish only after its 3 and repository inputs are visible in
                    # copy after publication.
                )
            )
        copy_tree(source, destination, expected=expected)

    monkeypatch.setattr(backup_module, "copy_tree_verified", copy_after_publication)

    generation = backup.create_generation(created_at_ns=100)

    # Verify len(published) == 1 before this scenario is accepted.
    assert len(published) == 1
    assert published[0].artifact_id not in generation.artifact_ids
    handle = repository.open_committed(published[0].artifact_id)
    handle.close()


@pytest.mark.integration
# Define test pin published after backup root inventory is excluded from the exact cut as
# one focused operation with an explicit boundary.
def test_pin_published_after_backup_root_inventory_is_excluded_from_the_exact_cut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test pin published after backup root inventory is excluded from the
    # exact cut workflow in explicit, reviewable steps.
    repository, retention, catalog_path, _, _ = _source(tmp_path)
    late_root = _publish(repository, payload=b"late pin root", key="3" * 64)
    backup = LocalBackupRepository(
        repository,
        retention,
        # Pass catalog path explicitly so LocalBackupRepository receives a reviewable
        # backup-device and repository input in test pin published after backup root
        # inventory is excluded from the exact cut.
        catalog_path,
        tmp_path / "backup-device",
        allow_same_device_for_drill=True,
        lock_timeout_seconds=None,
    )
    # Assemble inventory captured once so the test pin published after backup root
    # inventory is excluded from the exact cut workflow shares one value.
    inventory_captured = Event()
    release_cut = Event()
    pin_started = Event()
    original_copy_pins = LocalBackupRepository._copy_pins

    def pause_cut(
        # Keep the remaining pause cut inputs visible at the pause cut boundary.
        self: LocalBackupRepository,
        payload: Path,
        pins: tuple[PinRecord, ...],
    ) -> list[dict[str, object]]:
        # Execute the pause cut workflow in explicit, reviewable steps.
        inventory_captured.set()
        if not release_cut.wait(timeout=5):
            raise TimeoutError("backup cut race fixture timed out")
        return original_copy_pins(self, payload, pins)

    def publish_late_pin() -> PinRecord:
        # Execute the publish late pin workflow in explicit, reviewable steps.
        pin_started.set()
        return retention.create_pin(
            pin_id=Identifier("late-backup-pin"),
            roots=(late_root.artifact_id,),
            reason="published after inventory",
            # Pass created at ns explicitly so create_pin receives a reviewable late-
            # backup-pin and published after inventory input in publish late pin.
            created_at_ns=101,
        )

    monkeypatch.setattr(LocalBackupRepository, "_copy_pins", pause_cut)
    with ThreadPoolExecutor(max_workers=2) as pool:
        # Keep thread pool executor active only for the bounded test pin published after
        # backup root inventory is excluded from the exact cut operation.
        generation_future = pool.submit(backup.create_generation, created_at_ns=100)
        assert inventory_captured.wait(timeout=5)
        pin_future = pool.submit(publish_late_pin)
        assert pin_started.wait(timeout=5)
        assert not pin_future.done()
        # Invoke set as a visible step within the test pin published after backup root
        # inventory is excluded from the exact cut workflow.
        release_cut.set()
        generation = generation_future.result(timeout=10)
        late_pin = pin_future.result(timeout=10)

    assert late_pin.roots == (late_root.artifact_id,)
    assert late_root.artifact_id not in generation.artifact_ids
    # Assemble generation root once so the test pin published after backup root inventory
    # is excluded from the exact cut workflow shares one value.
    generation_root = tmp_path / "backup-device" / "generations" / generation.backup_cut_id.hex
    manifest = backup_module.parse_canonical_object(
        (generation_root / "backup.json").read_bytes(),
        label="backup manifest",
    )
    # Assemble pins once so the test pin published after backup root inventory is excluded
    # from the exact cut workflow shares one value.
    pins = cast(list[dict[str, object]], manifest["pins"])
    assert {item["pin_id"] for item in pins} == {"baseline"}
    assert {pin.pin_id.value for pin in retention.active_pins()} == {
        "baseline",
        "late-backup-pin",
        # Verify the value, baseline and late-backup-pin relationship before this scenario is
        # accepted.
    }


@pytest.mark.integration
def test_corrupt_backup_payload_fails_closed_and_destination_stays_absent(
    tmp_path: Path,
) -> None:
    # Execute the test corrupt backup payload fails closed and destination stays absent
    # workflow in explicit, reviewable steps.
    repository, retention, catalog_path, _, result = _source(tmp_path)
    backup_root = tmp_path / "backup-device"
    generation = LocalBackupRepository(
        repository,
        retention,
        # Pass catalog path explicitly into create_generation within test corrupt backup
        # payload fails closed and destination stays absent.
        catalog_path,
        backup_root,
        allow_same_device_for_drill=True,
    ).create_generation(created_at_ns=100)
    payload = (
        # Keep the backup root component named inside the payload contract.
        backup_root
        / "generations"
        / generation.backup_cut_id.hex
        / "data"
        / "snapshots"
        # Keep the result component named inside the payload contract.
        / result.artifact_id.hex
        / "data.bin"
    )
    payload.write_bytes(b"corrupt")
    destination = tmp_path / "must-not-exist"

    # Acquire raises, backup integrity error and pytest at an explicit test corrupt backup
    # payload fails closed and destination stays absent context boundary so cleanup
    # remains scoped.
    with pytest.raises(BackupIntegrityError, match="inventory"):
        # Keep raises, backup integrity error and pytest active only for the bounded test
        # corrupt backup payload fails closed and destination stays absent operation.
        LocalRestoreRepository(backup_root, destination).restore_generation(
            generation.backup_cut_id
        )
    assert not destination.exists()


@pytest.mark.integration
# Define test backup generation is invalid if crash happens before final marker as one
# focused operation with an explicit boundary.
def test_backup_generation_is_invalid_if_crash_happens_before_final_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test backup generation is invalid if crash happens before final marker
    # workflow in explicit, reviewable steps.
    repository, retention, catalog_path, _, _ = _source(tmp_path)
    backup_root = tmp_path / "backup-device"
    backup = LocalBackupRepository(
        repository,
        retention,
        # Pass catalog path explicitly so LocalBackupRepository receives a reviewable
        # repository and retention input in test backup generation is invalid if crash
        # happens before final marker.
        catalog_path,
        backup_root,
        allow_same_device_for_drill=True,
    )
    durable_write = backup_module.write_durable_exclusive

    # Define fail final marker as one focused operation with an explicit boundary.
    def fail_final_marker(path: Path, payload: bytes) -> None:
        # Execute the fail final marker workflow in explicit, reviewable steps.
        if path.name == "COMMITTED" and path.parent.parent.name == "generations":
            raise OSError("injected crash before commit point")
        durable_write(path, payload)

    monkeypatch.setattr(backup_module, "write_durable_exclusive", fail_final_marker)

    with pytest.raises(OSError, match="injected crash"):
        # Invoke create_generation as a visible step within the test backup generation is
        # invalid if crash happens before final marker workflow.
        backup.create_generation(created_at_ns=100)

    incomplete = tuple((backup_root / "generations").iterdir())
    assert len(incomplete) == 1
    assert not (incomplete[0] / "COMMITTED").exists()
    cut = ContentDigest(incomplete[0].name)
    # Assemble destination once so the test backup generation is invalid if crash happens
    # before final marker workflow shares one value.
    destination = tmp_path / "not-published"
    with pytest.raises(BackupIntegrityError, match="incomplete"):
        LocalRestoreRepository(backup_root, destination).restore_generation(cut)
    assert not destination.exists()


def test_same_device_backup_is_rejected_without_explicit_drill_override(tmp_path: Path) -> None:
    # Execute the test same device backup is rejected without explicit drill override
    # workflow in explicit, reviewable steps.
    repository, retention, catalog_path, _, _ = _source(tmp_path)

    with pytest.raises(BackupIntegrityError, match="different physical device"):
        # Keep raises, backup integrity error and pytest active only for the bounded test
        # same device backup is rejected without explicit drill override operation.
        LocalBackupRepository(
            repository,
            retention,
            catalog_path,
            tmp_path / "same-device",
            # Complete LocalBackupRepository only after its same-device and repository inputs
            # are visible in test same device backup is rejected without explicit drill
            # override.
        )


def test_sqlite_checkpoint_rejects_newer_schema(tmp_path: Path) -> None:
    # Execute the test sqlite checkpoint rejects newer schema workflow in explicit,
    # reviewable steps.
    source = tmp_path / "source.sqlite"
    initialize(source, busy_timeout_seconds=1.0)
    checkpoint_path = tmp_path / "checkpoint.sqlite"
    SQLiteCheckpointRepository(source).create_checkpoint(checkpoint_path)
    connection = sqlite3.connect(checkpoint_path)
    # Invoke execute for pragma user version = and latest schema version as a visible test
    # sqlite checkpoint rejects newer schema step.
    connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises((BackupIntegrityError, RuntimeError), match="newer"):
        # Keep raises, pytest and backup integrity error active only for the bounded test
        # sqlite checkpoint rejects newer schema operation.
        SQLiteCheckpointRepository(source).verify_checkpoint(
            checkpoint_path,
            expected_digest=ContentDigest(hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()),
        )


def test_sqlite_checkpoint_closes_source_if_destination_open_fails(
    # Keep the tmp path input explicit in the test sqlite checkpoint closes source if
    # destination open fails contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test sqlite checkpoint closes source if destination open fails workflow
    # in explicit, reviewable steps.
    source_path = tmp_path / "source.sqlite"
    initialize(source_path, busy_timeout_seconds=1.0)

    # Keep the source connection contract and validation rules together.
    class _SourceConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    # Keep the failing sqlite module contract and validation rules together.
    class _FailingSqliteModule:
        @staticmethod
        def connect(*args: object, **kwargs: object) -> None:
            # Execute the failing sqlite module connect workflow in explicit, reviewable
            # steps.
            del args, kwargs
            raise sqlite3.OperationalError("injected destination-open failure")

    source = _SourceConnection()
    monkeypatch.setattr(sqlite_backup_module, "connect", lambda *args, **kwargs: source)
    monkeypatch.setattr(sqlite_backup_module, "sqlite3", _FailingSqliteModule())

    # Acquire raises, operational error and pytest at an explicit test sqlite checkpoint
    # closes source if destination open fails context boundary so cleanup remains scoped.
    with pytest.raises(sqlite3.OperationalError, match="destination-open failure"):
        SQLiteCheckpointRepository(source_path).create_checkpoint(tmp_path / "target.sqlite")

    assert source.closed


def test_restore_requires_absent_destination(tmp_path: Path) -> None:
    # Execute the test restore requires absent destination workflow in explicit,
    # reviewable steps.
    backup_root = tmp_path / "backup"
    (backup_root / "generations").mkdir(parents=True)
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(BackupIntegrityError, match="must not exist"):
        # Invoke restore_generation for 1 and content digest as a visible test restore
        # requires absent destination step.
        LocalRestoreRepository(backup_root, destination).restore_generation(ContentDigest("1" * 64))
