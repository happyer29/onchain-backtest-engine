# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from socket import socket
from threading import Event, Thread

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.bootstrap import benchmark_control as benchmark_control_module
from backtest.bootstrap.benchmark_control import create_isolated_benchmark_workspace

# Import config at the visible module dependency boundary.
from backtest.bootstrap.config import (
    PathSettings,
    Settings,
    SourceSettings,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.runtime.controller_lock import ControllerLock


def _run_seed_manifest(label: str) -> bytes:
    return canonical_json_bytes(
        {
            "execution_attempt_id": domain_digest(
                "test.benchmark-control-attempt.v1", {"label": label}
            ).hex,
            "logical_run_id": domain_digest(
                "test.benchmark-control-logical-run.v1", {"label": label}
            ).hex,
            "schema": "test.run-seed.v1",
        }
    )


def test_isolated_workspace_has_exact_artifacts_and_secret_free_config(tmp_path: Path) -> None:
    # Execute the test isolated workspace has exact artifacts and secret free config
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "live"
    artifacts = LocalArtifactRepository(data_root)
    writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.RUN,
            # Keep the v1 domain_digest step visible while building writer.
            domain_digest("test.benchmark-control-seed.v1", {}),
        )
    )
    with writer.open_binary("result.bin") as stream:
        stream.write(b"exact result")
    # Assemble seed once so the test isolated workspace has exact artifacts and secret
    # free config workflow shares one value.
    manifest = _run_seed_manifest("workspace")
    seed = writer.commit(manifest, identity_manifest_bytes=manifest)
    defaults = Settings()
    settings = replace(
        defaults,
        paths=PathSettings(data_root=data_root),
        # Keep the resources replace step visible while building settings.
        resources=replace(
            defaults.resources,
            max_parallel_runs=2,
            disk_low_watermark_gb=1,
            disk_emergency_watermark_gb=1,
            # Complete replace only after its resources and defaults inputs are visible in
            # test isolated workspace has exact artifacts and secret free config.
        ),
        planning=replace(defaults.planning, max_local_gb=1),
        source=SourceSettings(
            host="indexer.invalid",
            secure=True,
            # Pass secret ref explicitly so SourceSettings receives a reviewable invalid
            # and private indexer password input in test isolated workspace has exact
            # artifacts and secret free config.
            secret_ref="PRIVATE_INDEXER_PASSWORD",
        ),
    )

    workspace = create_isolated_benchmark_workspace(
        settings,
        # Pass root artifact id explicitly so create_isolated_benchmark_workspace receives
        # a reviewable artifact id and settings input in test isolated workspace has exact
        # artifacts and secret free config.
        root_artifact_id=seed.artifact_id,
        control_port=18_080,
    )
    workspace_root = workspace.workspace_root
    try:
        # Perform the protected test isolated workspace has exact artifacts and secret
        # free config operation before explicit failure handling.
        payload = workspace.config_path.read_text(encoding="utf-8")
        assert "[source]" not in payload
        assert "secret" not in payload.casefold()
        assert "indexer.invalid" not in payload
        assert workspace.settings.source == SourceSettings()
        # Verify the max parallel runs, resources and settings relationship before this
        # scenario is accepted.
        assert workspace.settings.resources.max_parallel_runs == 1
        copied = LocalArtifactRepository(workspace.settings.paths.data_root)
        handle = copied.open_committed(seed.artifact_id)
        try:
            assert handle.descriptor == seed
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            handle.close()
    finally:
        workspace.close()

    assert not workspace_root.exists()


# Define test http failure cleanup releases authority socket and workspace as one focused
# operation with an explicit boundary.
def test_http_failure_cleanup_releases_authority_socket_and_workspace(tmp_path: Path) -> None:
    # Execute the test http failure cleanup releases authority socket and workspace
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "live"
    artifacts = LocalArtifactRepository(data_root)
    writer = artifacts.stage(
        ArtifactDraft(
            ArtifactKind.RUN,
            # Keep the v1 domain_digest step visible while building writer.
            domain_digest("test.benchmark-control-cleanup-seed.v1", {}),
        )
    )
    manifest = _run_seed_manifest("cleanup")
    seed = writer.commit(manifest, identity_manifest_bytes=manifest)
    defaults = Settings()
    # Assemble settings once so the test http failure cleanup releases authority socket
    # and workspace workflow shares one value.
    settings = replace(
        defaults,
        paths=PathSettings(data_root=data_root),
        resources=replace(
            defaults.resources,
            # Pass disk low watermark gb explicitly so replace receives a reviewable
            # resources and defaults input in test http failure cleanup releases authority
            # socket and workspace.
            disk_low_watermark_gb=1,
            disk_emergency_watermark_gb=1,
        ),
        planning=replace(defaults.planning, max_local_gb=1),
    )
    # Assemble workspace once so the test http failure cleanup releases authority socket
    # and workspace workflow shares one value.
    workspace = create_isolated_benchmark_workspace(
        settings,
        root_artifact_id=seed.artifact_id,
        control_port=18_081,
    )
    # Assemble workspace root once so the test http failure cleanup releases authority
    # socket and workspace workflow shares one value.
    workspace_root = workspace.workspace_root
    authority = ControllerLock(
        workspace.settings.paths.data_root / "locks" / "controller.lock"
    ).acquire()
    bound_socket = socket()
    # Assemble thread once so the test http failure cleanup releases authority socket and
    # workspace workflow shares one value.
    thread = Thread(target=lambda: None)
    thread.start()
    thread.join()
    failure = RuntimeError("server failed")

    with pytest.raises(RuntimeError, match="server failed") as caught:
        # Keep raises, runtime error and pytest active only for the bounded test http
        # failure cleanup releases authority socket and workspace operation.
        benchmark_control_module._finalize_http_authority(
            thread,
            Event(),
            [failure],
            bound_socket,
            # Pass authority explicitly so _finalize_http_authority receives a reviewable
            # event and thread input in test http failure cleanup releases authority
            # socket and workspace.
            authority,
            workspace,
        )

    assert caught.value.__cause__ is failure
    assert not authority.locked
    # Verify bound_socket.fileno() == -1 before this scenario is accepted.
    assert bound_socket.fileno() == -1
    assert not workspace_root.exists()
