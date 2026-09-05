"""Verified immutable backup generations and atomic fresh-root restore."""

from __future__ import annotations

import os
import sqlite3
import stat
import uuid

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from backtest.adapters.artifacts.localfs.placement import (
    ArtifactPlacementError,
    validate_artifact_relative_shape,
)
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.retention import (
    LocalArtifactLease,
    LocalRetentionRepository,
    # Include verified artifact so the retention dependency remains explicit.
    _VerifiedArtifact,
)
from backtest.adapters.artifacts.localfs.safe_io import (
    FileRecord,
    SafeFilesystemError,
    # Include canonical json so the safe io dependency remains explicit.
    canonical_json,
    copy_tree_verified,
    ensure_real_directory,
    file_records,
    fsync_directory,
    # Include parse canonical object so the safe io dependency remains explicit.
    parse_canonical_object,
    read_regular,
    records_digest,
    records_from_json,
    remove_verified_tree,
    # Include require real directory so the safe io dependency remains explicit.
    require_real_directory,
    safe_relative_path,
    sha256_bytes,
    write_durable_exclusive,
)

# Import scanner at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.backup import (
    SQLiteCheckpoint,
    SQLiteCheckpointRepository,
    # Close the backup import after its required symbols are visible.
)
from backtest.adapters.catalog.sqlite.retention_index import SQLiteRetentionIndex
from backtest.adapters.catalog.sqlite.schema import LATEST_SCHEMA_VERSION, connect
from backtest.application.backups import (
    BackupGeneration,
    # Include backup integrity error so the backups dependency remains explicit.
    BackupIntegrityError,
    RestoreReport,
)
from backtest.application.models import ArtifactKind
from backtest.application.retention import PinRecord

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier
from backtest.runtime.file_locks import FileLock, LockMode

_BACKUP_DOMAIN: Final = b"local-backtest/backup-generation/v1\x00"
_TREE_DOMAIN: Final = b"local-backtest/tree-inventory/v1\x00"
_BACKUP_VERSION: Final = 1


# Keep the verified generation contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _VerifiedGeneration:
    generation: BackupGeneration
    root: Path
    payload_records: tuple[FileRecord, ...]
    # Declare catalog relative path explicitly in the verified generation contract.
    catalog_relative_path: str
    artifact_paths: tuple[tuple[ArtifactId, ArtifactKind, str, ContentDigest], ...]
    pins: tuple[tuple[str, ContentDigest], ...]
    successful_roots: tuple[ArtifactId, ...]
    manifest_digest: ContentDigest


# Apply dataclass semantics to the following captured backup cut contract.
@dataclass(frozen=True, slots=True)
class _CapturedBackupCut:
    """Small immutable cut captured before the potentially long device copy."""

    staging: Path
    payload: Path
    checkpoint: SQLiteCheckpoint
    inventory: dict[str, _VerifiedArtifact]
    closure: tuple[ArtifactId, ...]
    # Declare pin documents explicitly in the captured backup cut contract.
    pin_documents: list[dict[str, object]]
    lease: LocalArtifactLease | None


class LocalBackupRepository:
    """Creates a content-verified generation while holding one exact local cut."""

    def __init__(
        self,
        repository: LocalArtifactRepository,
        retention: LocalRetentionRepository,
        catalog_path: Path,
        # Keep the backup root input explicit in the init contract.
        backup_root: Path,
        *,
        allow_same_device_for_drill: bool = False,
        lock_timeout_seconds: float | None = None,
        busy_timeout_seconds: float = 5.0,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local backup repository init workflow in explicit, reviewable steps.
        candidate_backup_root = backup_root.absolute()
        if _paths_overlap(repository.data_root, candidate_backup_root):
            raise BackupIntegrityError("backup target must be outside the live data root")
        self._repository = repository
        self._retention = retention
        # Assemble self catalog path once so the local backup repository init workflow
        # shares one value.
        self._catalog_path = catalog_path
        self._backup_root = _prepare_backup_root(backup_root)
        self._lock_timeout_seconds = lock_timeout_seconds
        self._checkpoint_repository = SQLiteCheckpointRepository(
            catalog_path,
            # Pass busy timeout seconds explicitly so SQLiteCheckpointRepository receives
            # a reviewable catalog path and busy timeout seconds input in local backup
            # repository init.
            busy_timeout_seconds=busy_timeout_seconds,
        )
        if (
            not allow_same_device_for_drill
            and repository.data_root.stat().st_dev == self._backup_root.stat().st_dev
            # Evaluate the complete local backup repository init allow same device for drill,
            # st dev and stat condition before guarded effects.
        ):
            # Handle the local backup repository init allow same device for drill, st dev
            # and stat condition as a distinct block.
            raise BackupIntegrityError(
                "backup target must be a different physical device; "
                "the same-device override is only for isolated restore drills"
            )
        self._staging_root = self._backup_root / "staging"
        # Assemble self generations root once so the local backup repository init workflow
        # shares one value.
        self._generations_root = self._backup_root / "generations"
        ensure_real_directory(self._staging_root, parent=self._backup_root)
        ensure_real_directory(self._generations_root, parent=self._backup_root)
        fsync_directory(self._backup_root)

    def create_generation(self, *, created_at_ns: int) -> BackupGeneration:
        # Execute the local backup repository create generation workflow in explicit,
        # reviewable steps.
        if created_at_ns < 0:
            raise ValueError("backup clock must be non-negative")
        staging = self._staging_root / f"generation-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        payload = staging / "data"
        # Invoke mkdir as a visible step within the local backup repository create
        # generation workflow.
        payload.mkdir(mode=0o700)
        catalog_directory = payload / "catalog"
        catalog_directory.mkdir(mode=0o700)
        fsync_directory(self._staging_root)
        backup_cut_lock = FileLock(
            # Pass self explicitly so FileLock receives a reviewable lock and locks root
            # input in local backup repository create generation.
            self._repository.locks_root / "backup-cut.lock",
            mode=LockMode.EXCLUSIVE,
            timeout=self._lock_timeout_seconds,
        )
        retention_lock = FileLock(
            # Pass self explicitly so FileLock receives a reviewable lock and locks root
            # input in local backup repository create generation.
            self._repository.locks_root / "retention.lock",
            mode=LockMode.SHARED,
            timeout=self._lock_timeout_seconds,
        )
        publication_lock = FileLock(
            # Pass self explicitly so FileLock receives a reviewable lock and locks root
            # input in local backup repository create generation.
            self._repository.locks_root / "publication.lock",
            mode=LockMode.EXCLUSIVE,
            timeout=self._lock_timeout_seconds,
        )
        cut: _CapturedBackupCut | None = None
        # Keep expected failures inside the local backup repository create generation
        # error boundary.
        try:
            # Perform the protected local backup repository create generation operation
            # before explicit failure handling.
            with backup_cut_lock, retention_lock:
                # Keep backup cut lock active only for the bounded local backup repository
                # create generation operation.
                with publication_lock:
                    # Keep publication lock active only for the bounded local backup
                    # repository create generation operation.
                    checkpoint = self._checkpoint_repository.create_checkpoint(
                        catalog_directory / "catalog.sqlite"
                    )
                    pins = self._retention._active_pins_locked()
                    inventory = self._retention._verified_inventory_locked()
                    # Assemble pin roots once so the local backup repository create
                    # generation workflow shares one value.
                    pin_roots = tuple(root for pin in pins for root in pin.roots)
                    all_roots = _artifact_ids((*checkpoint.successful_roots, *pin_roots))
                    closure = self._retention._closure(all_roots, inventory)
                    # Pin records are small mutable-root authority.  Copy their
                    # exact bytes while the publication cut is still closed.
                    pin_documents = self._copy_pins(payload, pins)

                # Establish long-lived shared read leases before releasing the
                # outer retention lock.  They block GC for the selected closure
                # without blocking unrelated artifact publication.
                lease = (
                    None
                    if not all_roots
                    else self._retention.acquire_lease(
                        lease_id=Identifier(f"backup-{uuid.uuid4().hex}"),
                        # Pass roots explicitly so acquire_lease receives a reviewable
                        # backup- and materialize verified backup cut input in local
                        # backup repository create generation.
                        roots=all_roots,
                        reason="materialize verified backup cut",
                    )
                )
                if lease is not None and lease.info.transitive_closure != closure:
                    # Handle the local backup repository create generation lease,
                    # transitive closure and closure condition as a distinct block.
                    lease.close()
                    raise BackupIntegrityError(
                        "backup lease closure differs from the captured artifact cut"
                    )
                cut = _CapturedBackupCut(
                    # Pass staging explicitly so _CapturedBackupCut receives a reviewable
                    # staging and payload input in local backup repository create
                    # generation.
                    staging=staging,
                    payload=payload,
                    checkpoint=checkpoint,
                    inventory=inventory,
                    closure=closure,
                    # Pass pin documents explicitly so _CapturedBackupCut receives a
                    # reviewable staging and payload input in local backup repository
                    # create generation.
                    pin_documents=pin_documents,
                    lease=lease,
                )
            return self._materialize_cut(cut, created_at_ns=created_at_ns)
        finally:
            # Handle the cleanup path after the protected local backup repository create
            # generation operation.
            if cut is not None and cut.lease is not None:
                cut.lease.close()

    def _materialize_cut(
        self,
        cut: _CapturedBackupCut,
        # Close the materialize cut signature after its explicit inputs.
        *,
        created_at_ns: int,
    ) -> BackupGeneration:
        # Execute the local backup repository materialize cut workflow in explicit,
        # reviewable steps.
        checkpoint = cut.checkpoint
        try:
            # Perform the protected local backup repository materialize cut operation
            # before explicit failure handling.
            artifact_documents: list[dict[str, object]] = []
            for artifact_id in cut.closure:
                # Process cut.closure inside the bounded local backup repository
                # materialize cut loop.
                verified = cut.inventory[artifact_id.hex]
                relative = verified.root.relative_to(self._repository.data_root)
                try:
                    validate_artifact_relative_shape(
                        verified.descriptor.kind,
                        artifact_id,
                        relative.as_posix(),
                    )
                except ArtifactPlacementError as error:  # pragma: no cover - inventory verified
                    raise BackupIntegrityError(
                        "verified artifact has a non-canonical physical path"
                    ) from error
                destination = cut.payload / relative
                _ensure_relative_parent(cut.payload, relative.parts[:-1])
                # Invoke copy_tree_verified for root and files as a visible local backup
                # repository materialize cut step.
                copy_tree_verified(verified.root, destination, expected=verified.files)
                artifact_documents.append(
                    {
                        "artifact_id": artifact_id.hex,
                        "kind": verified.descriptor.kind.value,
                        # Pass relative path explicitly to append for artifact id and
                        # kind.
                        "relative_path": relative.as_posix(),
                        "tree_digest": verified.tree_digest.hex,
                    }
                )
            payload_records = file_records(cut.payload)
            # Assemble identity once so the local backup repository materialize cut
            # workflow shares one value.
            identity = {
                "artifacts": artifact_documents,
                "catalog": {
                    "relative_path": "catalog/catalog.sqlite",
                    "schema_version": checkpoint.schema_version,
                    # Keep the sha256 component named inside the identity contract.
                    "sha256": checkpoint.digest.hex,
                },
                "payload_files": [record.as_json() for record in payload_records],
                "pins": cut.pin_documents,
                "successful_roots": [item.hex for item in checkpoint.successful_roots],
                # Keep the version component named inside the identity contract.
                "version": _BACKUP_VERSION,
            }
            backup_cut_id = ContentDigest(
                sha256_bytes(canonical_json(identity), domain=_BACKUP_DOMAIN)
            )
            # Assemble manifest once so the local backup repository materialize cut
            # workflow shares one value.
            manifest = {
                **identity,
                "backup_cut_id": backup_cut_id.hex,
                "created_at_ns": created_at_ns,
            }
            # Assemble manifest payload once so the local backup repository materialize
            # cut workflow shares one value.
            manifest_payload = canonical_json(manifest)
            write_durable_exclusive(cut.staging / "backup.json", manifest_payload)
            fsync_directory(cut.staging)
            destination = self._generations_root / backup_cut_id.hex
            if _exists_no_follow(destination):
                # Handle the local backup repository materialize cut
                # _exists_no_follow(destination) branch as a distinct logical block.
                existing = _verify_generation(destination, expected_cut=backup_cut_id)
                _remove_private_tree(cut.staging)
                return existing.generation
            os.rename(cut.staging, destination)
            fsync_directory(self._staging_root)
            # Invoke fsync_directory for generations root as a visible local backup
            # repository materialize cut step.
            fsync_directory(self._generations_root)
            marker = canonical_json(
                {
                    "backup_cut_id": backup_cut_id.hex,
                    "manifest_sha256": sha256_bytes(manifest_payload),
                    # Keep version named so the backup cut id and manifest sha256 payload
                    # passed to canonical_json remains self-describing within local backup
                    # repository materialize cut.
                    "version": _BACKUP_VERSION,
                }
            )
            write_durable_exclusive(destination / "COMMITTED", marker)
            fsync_directory(destination)
            # Invoke fsync_directory for generations root as a visible local backup
            # repository materialize cut step.
            fsync_directory(self._generations_root)
            return BackupGeneration(
                backup_cut_id=backup_cut_id,
                catalog_digest=checkpoint.digest,
                artifact_ids=cut.closure,
                # Pass created at ns explicitly so BackupGeneration receives a reviewable
                # digest and closure input in local backup repository materialize cut.
                created_at_ns=created_at_ns,
                total_bytes=sum(record.size for record in payload_records),
            )
        except BaseException:
            # Marker-less staging/final directories are never valid generations.
            raise

    def _copy_pins(
        self,
        payload: Path,
        pins: tuple[PinRecord, ...],
        # Keep the list input explicit in the copy pins contract.
    ) -> list[dict[str, object]]:
        # Execute the local backup repository copy pins workflow in explicit, reviewable
        # steps.
        if not pins:
            return []
        pins_root = payload / "pins"
        pins_root.mkdir(mode=0o700)
        documents: list[dict[str, object]] = []
        # Traverse pins explicitly so each local backup repository copy pins iteration
        # remains traceable.
        for pin in pins:
            # Process pins inside the bounded local backup repository copy pins loop.
            source = self._repository.data_root / "pins" / f"{pin.pin_id.value}.json"
            pin_payload = read_regular(source, label="active pin")
            destination = pins_root / source.name
            write_durable_exclusive(destination, pin_payload)
            if read_regular(destination, label="copied pin") != pin_payload:
                # Fail the local backup repository copy pins path with
                # BackupIntegrityError for copied pin failed byte verification when pin
                # payload, read regular and destination is true; do not continue
                # ambiguously.
                raise BackupIntegrityError("copied pin failed byte verification")
            documents.append(
                {
                    "pin_id": pin.pin_id.value,
                    "record_digest": pin.record_digest.hex,
                    # Keep relative path named so the pin id and record digest payload
                    # passed to append remains self-describing within local backup
                    # repository copy pins.
                    "relative_path": f"pins/{source.name}",
                }
            )
        fsync_directory(pins_root)
        return documents


# Keep the local restore repository contract and validation rules together.
class LocalRestoreRepository:
    """Restores only a valid committed generation into one absent data root."""

    def __init__(
        self,
        backup_root: Path,
        destination_root: Path,
        *,
        # Keep the busy timeout seconds input explicit in the init contract.
        busy_timeout_seconds: float = 5.0,
    ) -> None:
        # Execute the local restore repository init workflow in explicit, reviewable
        # steps.
        self._backup_root = backup_root.absolute()
        _require_real_path_components(self._backup_root)
        require_real_directory(self._backup_root, label="backup root")
        self._generations_root = self._backup_root / "generations"
        require_real_directory(self._generations_root, label="backup generations root")
        # Assemble self destination root once so the local restore repository init
        # workflow shares one value.
        self._destination_root = destination_root.absolute()
        _require_real_path_components(self._destination_root.parent)
        self._busy_timeout_seconds = busy_timeout_seconds

    def restore_generation(self, backup_cut_id: ContentDigest) -> RestoreReport:
        # Execute the local restore repository restore generation workflow in explicit,
        # reviewable steps.
        if _exists_no_follow(self._destination_root):
            raise BackupIntegrityError("restore destination must not exist")
        require_real_directory(self._destination_root.parent, label="restore parent")
        generation = _verify_generation(
            self._generations_root / backup_cut_id.hex,
            # Pass expected cut explicitly so _verify_generation receives a reviewable
            # generations root and hex input in local restore repository restore
            # generation.
            expected_cut=backup_cut_id,
        )
        staging = self._destination_root.parent / (
            f".{self._destination_root.name}.restore-{uuid.uuid4().hex}"
        )
        # Invoke copy_tree_verified for data and root as a visible local restore
        # repository restore generation step.
        copy_tree_verified(
            generation.root / "data",
            staging,
            expected=generation.payload_records,
        )
        # Keep expected failures inside the local restore repository restore generation
        # error boundary.
        try:
            # Perform the protected local restore repository restore generation operation
            # before explicit failure handling.
            catalog_path = staging / generation.catalog_relative_path
            checkpoint = SQLiteCheckpointRepository(
                catalog_path,
                busy_timeout_seconds=self._busy_timeout_seconds,
            )
            # Assemble job roots once so the local restore repository restore generation
            # workflow shares one value.
            job_roots = checkpoint.verify_checkpoint(
                catalog_path,
                expected_digest=generation.generation.catalog_digest,
            )
            if job_roots != generation.successful_roots:
                # Fail the local restore repository restore generation path with
                # BackupIntegrityError for restored job roots disagree with backup
                # manifest when job roots, successful roots and generation is true; do not
                # continue ambiguously.
                raise BackupIntegrityError("restored job roots disagree with backup manifest")
            repository = LocalArtifactRepository(staging)
            scanner = LocalCommittedArtifactScanner(repository)
            artifacts = scanner.scan()
            actual_ids = tuple(
                # Keep the sorted and artifact id sorted step visible while building
                # actual ids.
                sorted(
                    (item.artifact_id for item in artifacts),
                    key=lambda item: item.hex,
                )
            )
            # Evaluate the complete local restore repository restore generation actual
            # ids, artifact ids and generation condition before guarded effects.
            if actual_ids != generation.generation.artifact_ids:
                raise BackupIntegrityError("restored artifact set disagrees with backup manifest")
            catalog = SQLiteArtifactCatalog(
                catalog_path,
                repository,
                # Pass busy timeout seconds explicitly so SQLiteArtifactCatalog receives a
                # reviewable busy timeout seconds and catalog path input in local restore
                # repository restore generation.
                busy_timeout_seconds=self._busy_timeout_seconds,
            )
            rebuild = catalog.rebuild_index(artifacts)
            retention = LocalRetentionRepository(repository)
            pins = retention.active_pins()
            # Assemble pin projection once so the local restore repository restore
            # generation workflow shares one value.
            pin_projection = tuple((pin.pin_id.value, pin.record_digest) for pin in pins)
            if pin_projection != generation.pins:
                raise BackupIntegrityError("restored pins disagree with backup manifest")
            SQLiteRetentionIndex(
                catalog_path,
                # Pass busy timeout seconds explicitly so rebuild receives a reviewable
                # pins input in local restore repository restore generation.
                busy_timeout_seconds=self._busy_timeout_seconds,
            ).rebuild(pins)
            _verify_successful_roots(job_roots, repository)
            _make_catalog_self_contained(
                catalog_path,
                # Pass busy timeout seconds explicitly so _make_catalog_self_contained
                # receives a reviewable busy timeout seconds and catalog path input in
                # local restore repository restore generation.
                busy_timeout_seconds=self._busy_timeout_seconds,
            )
            marker = canonical_json(
                {
                    "backup_cut_id": backup_cut_id.hex,
                    # Keep catalog indexed artifacts named so the backup cut id and
                    # catalog indexed artifacts payload passed to canonical_json remains
                    # self-describing within local restore repository restore generation.
                    "catalog_indexed_artifacts": rebuild.indexed_artifacts,
                    "manifest_sha256": generation.manifest_digest.hex,
                    "version": 1,
                }
            )
            # Invoke write_durable_exclusive for restore reconciled and staging as a
            # visible local restore repository restore generation step.
            write_durable_exclusive(staging / "RESTORE_RECONCILED", marker)
            fsync_directory(staging)
            os.rename(staging, self._destination_root)
            fsync_directory(self._destination_root.parent)
        except BaseException:
            # Private staging remains inspectable; the configured destination
            # never becomes visible before reconciliation succeeds.
            raise
        return RestoreReport(
            backup_cut_id=backup_cut_id,
            restored_artifacts=len(generation.generation.artifact_ids),
            catalog_rebuild=rebuild,
            # Pass restored job roots explicitly so RestoreReport receives a reviewable
            # artifact ids and generation input in local restore repository restore
            # generation.
            restored_job_roots=job_roots,
            reconciliation_complete=True,
        )


def _verify_generation(root: Path, *, expected_cut: ContentDigest) -> _VerifiedGeneration:
    # Execute the verify generation workflow in explicit, reviewable steps.
    try:
        # Perform the protected verify generation operation before explicit failure
        # handling.
        require_real_directory(root, label="backup generation")
        manifest_payload = read_regular(root / "backup.json", label="backup manifest")
        marker = parse_canonical_object(
            read_regular(root / "COMMITTED", label="backup marker"),
            label="backup marker",
            # Complete parse_canonical_object only after its committed and backup marker
            # inputs are visible in verify generation.
        )
        manifest = parse_canonical_object(manifest_payload, label="backup manifest")
    except SafeFilesystemError as error:
        raise BackupIntegrityError("backup generation is incomplete or corrupt") from error
    if marker != {
        # Keep backup cut id visible while evaluating the marker, backup cut id and
        # manifest sha256 guard.
        "backup_cut_id": expected_cut.hex,
        "manifest_sha256": sha256_bytes(manifest_payload),
        "version": _BACKUP_VERSION,
    }:
        raise BackupIntegrityError("backup marker does not authenticate its manifest")
    # Assemble expected keys once so the verify generation workflow shares one value.
    expected_keys = {
        "artifacts",
        "backup_cut_id",
        "catalog",
        "created_at_ns",
        # Keep the payload files component named inside the expected keys contract.
        "payload_files",
        "pins",
        "successful_roots",
        "version",
    }
    # Guard this path with set(manifest) != expected_keys before applying effects.
    if set(manifest) != expected_keys:
        raise BackupIntegrityError("backup manifest schema is unsupported")
    version = _integer(manifest, "version")
    if version != _BACKUP_VERSION:
        raise BackupIntegrityError("backup manifest schema is newer or unsupported")
    # Evaluate the complete verify generation hex, name and string condition before
    # guarded effects.
    if _string(manifest, "backup_cut_id") != expected_cut.hex or root.name != expected_cut.hex:
        raise BackupIntegrityError("backup cut identity mismatch")
    created_at_ns = _integer(manifest, "created_at_ns")
    catalog_value = manifest.get("catalog")
    if not isinstance(catalog_value, dict) or set(catalog_value) != {
        # Keep relative path visible while evaluating the isinstance, catalog value and
        # relative path guard.
        "relative_path",
        "schema_version",
        "sha256",
    }:
        raise BackupIntegrityError("backup catalog manifest is invalid")
    # Assemble catalog once so the verify generation workflow shares one value.
    catalog = cast(dict[str, object], catalog_value)
    catalog_path = _string(catalog, "relative_path")
    safe_relative_path(catalog_path)
    if catalog_path != "catalog/catalog.sqlite":
        raise BackupIntegrityError("backup catalog path is non-canonical")
    # Evaluate the complete verify generation latest schema version, integer and catalog
    # condition before guarded effects.
    if _integer(catalog, "schema_version") > LATEST_SCHEMA_VERSION:
        raise BackupIntegrityError("backup catalog schema is newer than this runtime")
    if _integer(catalog, "schema_version") != LATEST_SCHEMA_VERSION:
        raise BackupIntegrityError("backup catalog schema is unsupported")
    catalog_digest = ContentDigest(_string(catalog, "sha256"))
    # Assemble payload records once so the verify generation workflow shares one value.
    payload_records = records_from_json(manifest.get("payload_files"))
    actual_records = file_records(root / "data")
    if actual_records != payload_records:
        raise BackupIntegrityError("backup payload inventory verification failed")
    catalog_record = next((item for item in payload_records if item.path == catalog_path), None)
    # Evaluate the complete verify generation catalog record, sha256 and hex condition
    # before guarded effects.
    if catalog_record is None or catalog_record.sha256 != catalog_digest.hex:
        raise BackupIntegrityError("backup catalog digest disagrees with physical inventory")
    artifact_paths = _parse_artifacts(manifest.get("artifacts"))
    artifact_ids = tuple(item[0] for item in artifact_paths)
    pins = _parse_pins(manifest.get("pins"))
    # Traverse artifact_paths explicitly so each verify generation iteration remains
    # traceable.
    for _, _, relative_path, expected_tree_digest in artifact_paths:
        # Process artifact_paths inside the bounded verify generation loop.
        artifact_records = file_records(root / "data" / relative_path)
        if records_digest(artifact_records, domain=_TREE_DOMAIN) != expected_tree_digest.hex:
            raise BackupIntegrityError("backup artifact tree digest mismatch")
    _verify_payload_scope(payload_records, catalog_path, artifact_paths, pins)
    roots = _artifact_id_list(manifest.get("successful_roots"), label="successful roots")
    # Assemble identity once so the verify generation workflow shares one value.
    identity = dict(manifest)
    del identity["backup_cut_id"]
    del identity["created_at_ns"]
    recomputed = ContentDigest(sha256_bytes(canonical_json(identity), domain=_BACKUP_DOMAIN))
    if recomputed != expected_cut:
        # Fail the verify generation path with BackupIntegrityError for backup cut
        # checksum mismatch when recomputed and expected cut is true; do not continue
        # ambiguously.
        raise BackupIntegrityError("backup cut checksum mismatch")
    return _VerifiedGeneration(
        generation=BackupGeneration(
            backup_cut_id=expected_cut,
            catalog_digest=catalog_digest,
            # Pass artifact ids explicitly so BackupGeneration receives a reviewable size
            # and sum input in verify generation.
            artifact_ids=artifact_ids,
            created_at_ns=created_at_ns,
            total_bytes=sum(item.size for item in payload_records),
        ),
        root=root,
        # Pass payload records explicitly so _VerifiedGeneration receives a reviewable
        # size and backup generation input in verify generation.
        payload_records=payload_records,
        catalog_relative_path=catalog_path,
        artifact_paths=artifact_paths,
        pins=pins,
        successful_roots=roots,
        # Include manifest digest in the completed verify generation result.
        manifest_digest=ContentDigest(sha256_bytes(manifest_payload)),
    )


def _parse_artifacts(
    value: object,
) -> tuple[tuple[ArtifactId, ArtifactKind, str, ContentDigest], ...]:
    # Execute the parse artifacts workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise BackupIntegrityError("backup artifacts must be a list")
    parsed: list[tuple[ArtifactId, ArtifactKind, str, ContentDigest]] = []
    for raw in value:
        # Process value inside the bounded parse artifacts loop.
        if not isinstance(raw, dict) or set(raw) != {
            "artifact_id",
            "kind",
            "relative_path",
            "tree_digest",
            # Evaluate the complete parse artifacts isinstance, raw and artifact id condition
            # before guarded effects.
        }:
            raise BackupIntegrityError("backup artifact schema is invalid")
        item = cast(dict[str, object], raw)
        try:
            # Perform the protected parse artifacts operation before explicit failure
            # handling.
            artifact_id = ArtifactId(_string(item, "artifact_id"))
            kind = ArtifactKind(_string(item, "kind"))
            tree_digest = ContentDigest(_string(item, "tree_digest"))
            relative_path = _string(item, "relative_path")
            safe_relative_path(relative_path)
        # Translate safe filesystem error through the parse artifacts boundary without
        # hiding other errors.
        except (SafeFilesystemError, TypeError, ValueError) as error:
            raise BackupIntegrityError("backup artifact identity is invalid") from error
        try:
            validate_artifact_relative_shape(kind, artifact_id, relative_path)
        except ArtifactPlacementError as error:
            raise BackupIntegrityError("backup artifact path is non-canonical") from error
        # Invoke append for artifact id and kind as a visible parse artifacts step.
        parsed.append((artifact_id, kind, relative_path, tree_digest))
    ids = [item[0].hex for item in parsed]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise BackupIntegrityError("backup artifacts must be sorted and unique")
    return tuple(parsed)


# Define parse pins as one focused operation with an explicit boundary.
def _parse_pins(value: object) -> tuple[tuple[str, ContentDigest], ...]:
    # Execute the parse pins workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise BackupIntegrityError("backup pins must be a list")
    parsed: list[tuple[str, ContentDigest]] = []
    for raw in value:
        # Process value inside the bounded parse pins loop.
        if not isinstance(raw, dict) or set(raw) != {
            "pin_id",
            "record_digest",
            "relative_path",
        }:
            # Fail the parse pins path with BackupIntegrityError for backup pin schema is
            # invalid when isinstance, raw and pin id is true; do not continue
            # ambiguously.
            raise BackupIntegrityError("backup pin schema is invalid")
        item = cast(dict[str, object], raw)
        pin_id = _string(item, "pin_id")
        digest = ContentDigest(_string(item, "record_digest"))
        relative_path = _string(item, "relative_path")
        # Keep expected failures inside the parse pins error boundary.
        try:
            safe_relative_path(relative_path)
        except SafeFilesystemError as error:
            raise BackupIntegrityError("backup pin path is unsafe") from error
        if relative_path != f"pins/{pin_id}.json":
            # Fail the parse pins path with BackupIntegrityError for backup pin path is
            # non-canonical when relative path and pin id is true; do not continue
            # ambiguously.
            raise BackupIntegrityError("backup pin path is non-canonical")
        parsed.append((pin_id, digest))
    if [item[0] for item in parsed] != sorted(item[0] for item in parsed):
        raise BackupIntegrityError("backup pins must be sorted")
    return tuple(parsed)


# Define verify successful roots as one focused operation with an explicit boundary.
def _verify_successful_roots(
    roots: tuple[ArtifactId, ...],
    repository: LocalArtifactRepository,
) -> None:
    # Execute the verify successful roots workflow in explicit, reviewable steps.
    for root in roots:
        # Process roots inside the bounded verify successful roots loop.
        try:
            handle = repository.open_committed(root)
        except Exception as error:
            raise BackupIntegrityError("restored successful job root is unavailable") from error
        handle.close()


# Define verify payload scope as one focused operation with an explicit boundary.
def _verify_payload_scope(
    records: tuple[FileRecord, ...],
    catalog_path: str,
    artifacts: tuple[tuple[ArtifactId, ArtifactKind, str, ContentDigest], ...],
    pins: tuple[tuple[str, ContentDigest], ...],
    # Close the verify payload scope signature after its explicit inputs.
) -> None:
    # Execute the verify payload scope workflow in explicit, reviewable steps.
    exact = {catalog_path, *(f"pins/{pin_id}.json" for pin_id, _ in pins)}
    prefixes = tuple(f"{relative_path}/" for _, _, relative_path, _ in artifacts)
    for record in records:
        # Process records inside the bounded verify payload scope loop.
        if record.path not in exact and not record.path.startswith(prefixes):
            raise BackupIntegrityError("backup payload contains an undeclared path")


def _make_catalog_self_contained(path: Path, *, busy_timeout_seconds: float) -> None:
    # Execute the make catalog self contained workflow in explicit, reviewable steps.
    connection = connect(path, busy_timeout_seconds=busy_timeout_seconds)
    try:
        # Perform the protected make catalog self contained operation before explicit
        # failure handling.
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is None or int(result[0]) != 0:
            raise BackupIntegrityError("restored catalog WAL checkpoint failed")
        mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            # Fail the make catalog self contained path with BackupIntegrityError for
            # restored catalog is not self-contained when mode, delete and lower is true;
            # do not continue ambiguously.
            raise BackupIntegrityError("restored catalog is not self-contained")
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or str(integrity[0]).lower() != "ok":
            raise BackupIntegrityError("restored catalog failed final integrity check")
    except sqlite3.Error as error:
        # Fail the make catalog self contained path with BackupIntegrityError for restored
        # catalog finalization failed; do not continue ambiguously.
        raise BackupIntegrityError("restored catalog finalization failed") from error
    finally:
        connection.close()
    fsync_directory(path.parent)


def _prepare_backup_root(path: Path) -> Path:
    # Execute the prepare backup root workflow in explicit, reviewable steps.
    absolute = path.absolute()
    _require_real_path_components(absolute.parent)
    if _exists_no_follow(absolute):
        # Handle the prepare backup root _exists_no_follow(absolute) branch as a distinct
        # logical block.
        require_real_directory(absolute, label="backup root")
        return absolute
    require_real_directory(absolute.parent, label="backup parent")
    absolute.mkdir(mode=0o700)
    fsync_directory(absolute.parent)
    # Return the completed prepare backup root result without a hidden fallback.
    return absolute


def _ensure_relative_parent(root: Path, parts: tuple[str, ...]) -> Path:
    """Create a verified backup parent without following a path-component symlink."""

    require_real_directory(root, label="backup payload root")
    current = root
    for part in parts:
        child = current / part
        missing = not _exists_no_follow(child)
        ensure_real_directory(child, parent=current)
        if missing:
            fsync_directory(current)
        current = child
    return current


def _require_real_path_components(path: Path) -> None:
    # Execute the require real path components workflow in explicit, reviewable steps.
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        # Process absolute.parts[1:] inside the bounded require real path components loop.
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as error:
            raise BackupIntegrityError("configured path has a missing ancestor") from error
        # Evaluate the complete require real path components s islnk, st mode and stat
        # condition before guarded effects.
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise BackupIntegrityError("configured path crosses a symlink or non-directory")


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _exists_no_follow(path: Path) -> bool:
    # Execute the exists no follow workflow in explicit, reviewable steps.
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


# Define remove private tree as one focused operation with an explicit boundary.
def _remove_private_tree(path: Path) -> None:
    # Execute the remove private tree workflow in explicit, reviewable steps.
    remove_verified_tree(path, file_records(path))
    fsync_directory(path.parent)


def _artifact_ids(values: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
    return tuple(ArtifactId(value) for value in sorted({item.hex for item in values}))


def _artifact_id_list(value: object, *, label: str) -> tuple[ArtifactId, ...]:
    # Execute the artifact id list workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BackupIntegrityError(f"{label} must be a list")
    try:
        parsed = tuple(ArtifactId(cast(str, item)) for item in value)
    except (TypeError, ValueError) as error:
        # Fail the artifact id list path with BackupIntegrityError for contains an invalid
        # artifact id and label; do not continue ambiguously.
        raise BackupIntegrityError(f"{label} contains an invalid artifact ID") from error
    if [item.hex for item in parsed] != sorted(item.hex for item in parsed) or len(parsed) != len(
        set(parsed)
    ):
        raise BackupIntegrityError(f"{label} must be sorted and unique")
    # Return the completed artifact id list result without a hidden fallback.
    return parsed


def _string(document: dict[str, object], key: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = document.get(key)
    if not isinstance(value, str):
        raise BackupIntegrityError(f"{key} must be a string")
    return value


def _integer(document: dict[str, object], key: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BackupIntegrityError(f"{key} must be a non-negative integer")
    return value


__all__ = ["LocalBackupRepository", "LocalRestoreRepository"]
