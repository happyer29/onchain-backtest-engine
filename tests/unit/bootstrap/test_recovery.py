# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact

# Import manage retention at the visible module dependency boundary.
from backtest.application.use_cases.manage_retention import CreatePinRequest
from backtest.bootstrap.config import BackupSettings, PathSettings, Settings
from backtest.bootstrap.maintenance import (
    MaintenanceConfigurationError,
    build_maintenance_services,
    # Close the maintenance import after its required symbols are visible.
)
from backtest.bootstrap.recovery import RecoveryServices
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import Identifier


def _publish(repository: LocalArtifactRepository) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            ArtifactKind.RUN,
            domain_digest("test.recovery-only-build", {"version": 1}),
        )
        # Complete stage only after its recovery-only-build and version inputs are visible in
        # publish.
    )
    with writer.open_binary("result.bin") as stream:
        stream.write(b"durable result")
    manifest = canonical_json_bytes(
        {
            "execution_attempt_id": "2" * 64,
            "logical_run_id": "1" * 64,
            "schema": "test-run/v1",
        }
    )
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def test_recovery_composition_restores_without_opening_corrupt_live_sqlite(
    # Keep the tmp path input explicit in the test recovery composition restores without
    # opening corrupt live sqlite contract.
    tmp_path: Path,
) -> None:
    # Execute the test recovery composition restores without opening corrupt live sqlite
    # workflow in explicit, reviewable steps.
    live = tmp_path / "live"
    backup_root = tmp_path / "backup"
    restore_parent = tmp_path / "restore"
    restore_parent.mkdir()
    settings = Settings(
        # Keep the live PathSettings step visible while building settings.
        paths=PathSettings(live),
        backup=BackupSettings(
            target_root=backup_root,
            restore_verify_parent=restore_parent,
            allow_same_device_for_drill=True,
            # Complete BackupSettings only after its backup root and restore parent inputs are
            # visible in test recovery composition restores without opening corrupt live
            # sqlite.
        ),
    )
    artifacts = LocalArtifactRepository(live)
    run = _publish(artifacts)
    maintenance = build_maintenance_services(
        # Pass settings explicitly so build_maintenance_services receives a reviewable
        # settings and artifacts input in test recovery composition restores without
        # opening corrupt live sqlite.
        settings,
        artifacts,
        clock_ns=lambda: 10,
    )
    maintenance.retention.create_pin(
        # Pass create pin request explicitly to create_pin for recovery test and recovery-
        # root.
        CreatePinRequest(Identifier("recovery-root"), (run.artifact_id,), "recovery test")
    )
    generation = maintenance.create_backup()

    live_catalog = live / "catalog" / "catalog.sqlite"
    live_catalog.write_bytes(b"not a sqlite database")
    # Assemble before once so the test recovery composition restores without opening
    # corrupt live sqlite workflow shares one value.
    before = live_catalog.read_bytes()

    restored = RecoveryServices(settings, clock_ns=lambda: 20).verify_restore(
        generation.backup_cut_id
    )

    assert restored.report.reconciliation_complete
    # Verify the restored artifacts, report and restored relationship before this scenario
    # is accepted.
    assert restored.report.restored_artifacts == 1
    assert live_catalog.read_bytes() == before
    destination = restore_parent / restored.destination_name
    assert (destination / "RESTORE_RECONCILED").is_file()
    assert (destination / "catalog" / "catalog.sqlite").is_file()
    assert (destination / "runs" / ("1" * 64) / ("2" * 64) / "COMMITTED").is_file()


# Define test recovery composition fails safely when backup is not configured as one
# focused operation with an explicit boundary.
def test_recovery_composition_fails_safely_when_backup_is_not_configured(
    tmp_path: Path,
) -> None:
    # Execute the test recovery composition fails safely when backup is not configured
    # workflow in explicit, reviewable steps.
    service = RecoveryServices(Settings(paths=PathSettings(tmp_path / "live")))

    with pytest.raises(MaintenanceConfigurationError, match="not configured"):
        service.verify_restore(domain_digest("test.missing-cut", {"version": 1}))
