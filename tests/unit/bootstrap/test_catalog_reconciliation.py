"""Restart reconciliation tests for filesystem-authoritative artifact indexes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import repository as repository_module
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    LocalArtifactRepository,
)
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.bootstrap.catalog_reconciliation import LocalArtifactCatalogReconciler
from backtest.domain.hashing import canonical_json_bytes, domain_digest


def _publish(repository: LocalArtifactRepository, label: str) -> CommittedArtifact:
    """Publish one small immutable payload with a distinct derivation key."""

    writer = repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.SOURCE_INSPECTION,
            build_key=domain_digest("test.reconciliation-build.v1", {"label": label}),
        )
    )
    # Payload bytes make full verification observable independently of control files.
    with writer.open_binary("data.bin") as stream:
        stream.write(label.encode("ascii"))
    manifest = canonical_json_bytes({"artifact_schema": "test.reconciliation/v1", "label": label})
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def _catalog(
    data_root: Path,
) -> tuple[LocalArtifactRepository, SQLiteArtifactCatalog, Path]:
    """Open a fresh process-local repository cache over one durable catalog."""

    repository = LocalArtifactRepository(data_root)
    database = data_root / "catalog" / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    return repository, catalog, database


def _reconciliation_state(database: Path) -> tuple[object, ...]:
    """Read the durable restart evidence without mutating it."""

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        row = connection.execute(
            "SELECT status, inventory_digest, artifact_count "
            "FROM artifact_reconciliation_state WHERE singleton = 1"
        ).fetchone()
        assert row is not None
        return tuple(row)
    finally:
        connection.close()


def _observe_payload_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Path]:
    """Count expensive physical hashes while preserving real verification."""

    original = repository_module._sha256_file
    hashed_paths: list[Path] = []

    def observe(path: Path) -> tuple[str, int]:
        # Keep the real digest check so test counts cannot weaken failure semantics.
        hashed_paths.append(path)
        return original(path)

    monkeypatch.setattr(repository_module, "_sha256_file", observe)
    return hashed_paths


def test_clean_unchanged_restart_reads_zero_payload_bytes_for_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean new process proves equality without re-hashing payload files."""

    data_root = tmp_path / "var"
    repository, catalog, database = _catalog(data_root)
    _publish(repository, "alpha")
    LocalArtifactCatalogReconciler(repository, catalog).reconcile_once()

    # Reopening both adapters discards the repository's process-local hash cache.
    restarted_repository, restarted_catalog, _ = _catalog(data_root)
    hashed_paths = _observe_payload_hashes(monkeypatch)
    LocalArtifactCatalogReconciler(
        restarted_repository,
        restarted_catalog,
    ).reconcile_once()

    assert hashed_paths == []
    status, inventory_digest, artifact_count = _reconciliation_state(database)
    assert status == "CLEAN"
    assert isinstance(inventory_digest, str) and len(inventory_digest) == 64
    assert artifact_count == 1


def test_interrupted_controller_session_forces_full_payload_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable UNCLEAN evidence disables the otherwise matching fast path."""

    data_root = tmp_path / "var"
    repository, catalog, database = _catalog(data_root)
    _publish(repository, "alpha")
    reconciler = LocalArtifactCatalogReconciler(repository, catalog)
    reconciler.reconcile_once()

    # Beginning without finishing models a killed controller after durable startup.
    inventory = LocalCommittedArtifactScanner(repository).inventory()
    assert catalog.begin_reconciliation_session(inventory) is True
    assert _reconciliation_state(database)[0] == "UNCLEAN"

    restarted_repository, restarted_catalog, _ = _catalog(data_root)
    hashed_paths = _observe_payload_hashes(monkeypatch)
    LocalArtifactCatalogReconciler(
        restarted_repository,
        restarted_catalog,
    ).reconcile_once()

    assert [path.name for path in hashed_paths] == ["data.bin"]
    assert _reconciliation_state(database)[0] == "CLEAN"


def test_offline_addition_forces_full_rebuild_and_enters_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed artifact added while stopped invalidates clean inventory evidence."""

    data_root = tmp_path / "var"
    repository, catalog, _ = _catalog(data_root)
    existing = _publish(repository, "alpha")
    LocalArtifactCatalogReconciler(repository, catalog).reconcile_once()
    added = _publish(repository, "bravo")

    # A different root fingerprint must select the fully verified rebuild path.
    restarted_repository, restarted_catalog, _ = _catalog(data_root)
    hashed_paths = _observe_payload_hashes(monkeypatch)
    LocalArtifactCatalogReconciler(
        restarted_repository,
        restarted_catalog,
    ).reconcile_once()

    assert sorted(path.parent.name for path in hashed_paths) == sorted(
        (existing.artifact_id.hex, added.artifact_id.hex)
    )
    assert len(hashed_paths) == 2
    assert restarted_catalog.find_committed(added.artifact_id) == added


def test_offline_same_size_mutation_fails_closed_and_remains_unclean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata detection triggers full hashing, which rejects changed payload bytes."""

    data_root = tmp_path / "var"
    repository, catalog, database = _catalog(data_root)
    committed = _publish(repository, "alpha")
    LocalArtifactCatalogReconciler(repository, catalog).reconcile_once()

    # Preserve size so the mutation test depends on timestamps and the final digest.
    root = repository._find_artifact_root(committed.artifact_id)[1]
    (root / "data.bin").write_bytes(b"omega")
    restarted_repository, restarted_catalog, _ = _catalog(data_root)
    hashed_paths = _observe_payload_hashes(monkeypatch)

    with pytest.raises(ArtifactIntegrityError, match="payload differs"):
        LocalArtifactCatalogReconciler(
            restarted_repository,
            restarted_catalog,
        ).reconcile_once()

    assert [path.name for path in hashed_paths] == ["data.bin"]
    assert _reconciliation_state(database)[0] == "UNCLEAN"


def test_offline_removal_forces_full_rebuild_and_removes_catalog_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed committed root cannot survive through stale SQLite metadata."""

    data_root = tmp_path / "var"
    repository, catalog, database = _catalog(data_root)
    committed = _publish(repository, "alpha")
    LocalArtifactCatalogReconciler(repository, catalog).reconcile_once()

    # Test-only removal models an offline operator or filesystem loss.
    root = repository._find_artifact_root(committed.artifact_id)[1]
    shutil.rmtree(root)
    restarted_repository, restarted_catalog, _ = _catalog(data_root)
    hashed_paths = _observe_payload_hashes(monkeypatch)
    LocalArtifactCatalogReconciler(
        restarted_repository,
        restarted_catalog,
    ).reconcile_once()

    assert hashed_paths == []
    assert restarted_catalog.find_committed(committed.artifact_id) is None
    assert _reconciliation_state(database)[0] == "CLEAN"
