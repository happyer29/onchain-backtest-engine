# Declare this module's dependencies and contracts before execution.
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.application.use_cases.manage_retention import CreatePinRequest

# Import config at the visible module dependency boundary.
from backtest.bootstrap.config import (
    BackupSettings,
    PathSettings,
    RetentionSettings,
    Settings,
    # Close the config import after its required symbols are visible.
)
from backtest.bootstrap.maintenance import (
    MaintenanceConfigurationError,
    build_maintenance_services,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import Identifier


def _artifact(repository: LocalArtifactRepository):
    # Execute the artifact workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(ArtifactKind.RUN, domain_digest("test.build", {"version": 1}))
    )
    with writer.open_binary("result.bin") as stream:
        stream.write(b"durable result")
    # Return the completed artifact result without a hidden fallback.
    manifest = canonical_json_bytes(
        {
            "execution_attempt_id": "2" * 64,
            "logical_run_id": "1" * 64,
            "schema": "test-run/v1",
        }
    )
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def test_maintenance_keeps_backup_optional(tmp_path: Path) -> None:
    # Execute the test maintenance keeps backup optional workflow in explicit, reviewable
    # steps.
    artifacts = LocalArtifactRepository(tmp_path / "live")
    services = build_maintenance_services(
        Settings(paths=PathSettings(artifacts.data_root)),
        artifacts,
    )

    # Verify not services.backup_configured before this scenario is accepted.
    assert not services.backup_configured
    with pytest.raises(MaintenanceConfigurationError, match="not configured"):
        services.create_backup()


def test_external_generation_and_restore_drill_use_only_configured_locations(
    tmp_path: Path,
    # Close the test external generation and restore drill use only configured locations
    # signature after its explicit inputs.
) -> None:
    # Execute the test external generation and restore drill use only configured locations
    # workflow in explicit, reviewable steps.
    live = tmp_path / "live"
    backup = tmp_path / "external-backup"
    restore_parent = tmp_path / "restore-drills"
    restore_parent.mkdir()
    artifacts = LocalArtifactRepository(live)
    # Assemble root once so the test external generation and restore drill use only
    # configured locations workflow shares one value.
    root = _artifact(artifacts)
    settings = Settings(
        paths=PathSettings(live),
        retention=RetentionSettings(
            minimum_artifact_age_seconds=0,
            # Pass trash grace seconds explicitly into RetentionSettings within test
            # external generation and restore drill use only configured locations.
            trash_grace_seconds=0,
            maximum_sweep_gb=1,
        ),
        backup=BackupSettings(
            target_root=backup,
            # Pass restore verify parent explicitly so BackupSettings receives a
            # reviewable backup and restore parent input in test external generation and
            # restore drill use only configured locations.
            restore_verify_parent=restore_parent,
            allow_same_device_for_drill=True,
        ),
    )
    timestamps = iter((1, 2, 3, 4, 5))
    # Assemble services once so the test external generation and restore drill use only
    # configured locations workflow shares one value.
    services = build_maintenance_services(
        settings,
        artifacts,
        clock_ns=lambda: next(timestamps),
    )
    # Invoke create_pin for restore drill fixture and important-run as a visible test
    # external generation and restore drill use only configured locations step.
    services.retention.create_pin(
        CreatePinRequest(
            Identifier("important-run"),
            (root.artifact_id,),
            "restore drill fixture",
            # Complete CreatePinRequest only after its important-run and restore drill fixture
            # inputs are visible in test external generation and restore drill use only
            # configured locations.
        )
    )

    generation = services.create_backup()
    restored = services.verify_restore(generation.backup_cut_id)

    destination = restore_parent / restored.destination_name
    # Verify the reconciliation complete, report and restored relationship before this
    # scenario is accepted.
    assert restored.report.reconciliation_complete
    assert restored.report.restored_artifacts == 1
    assert destination.parent == restore_parent
    assert (destination / "RESTORE_RECONCILED").is_file()
