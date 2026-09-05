"""Atomic local pins, read leases, and two-phase mark/sweep garbage collection."""

from __future__ import annotations

import os
import uuid
from contextlib import suppress

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, cast

from backtest.adapters.artifacts.localfs.layout import DataRootLayout

# Import repository at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.repository import (
    LocalArtifactRepository,
    _committed_from_descriptor,
)

# Import safe io at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs.safe_io import (
    FileRecord,
    SafeFilesystemError,
    canonical_json,
    ensure_real_directory,
    # Include file records so the safe io dependency remains explicit.
    file_records,
    fsync_directory,
    parse_canonical_object,
    publish_no_replace,
    read_regular,
    # Include records digest so the safe io dependency remains explicit.
    records_digest,
    records_from_json,
    remove_verified_tree,
    require_real_directory,
    sha256_bytes,
    # Include write durable exclusive so the safe io dependency remains explicit.
    write_durable_exclusive,
)
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.artifacts import ArtifactHandle
from backtest.application.retention import (
    # Include artifact lease info so the retention dependency remains explicit.
    ArtifactLeaseInfo,
    GarbageCollectionBatch,
    GarbageCollectionCandidate,
    GarbageCollectionPlan,
    GarbageCollectionPlanStaleError,
    # Include garbage collection policy so the retention dependency remains explicit.
    GarbageCollectionPolicy,
    GarbageCollectionReceipt,
    PinRecord,
    RetentionConflictError,
    RetentionIntegrityError,
    # Close the retention import after its required symbols are visible.
)
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier
from backtest.runtime.file_locks import FileLock, LockMode

_PIN_VERSION: Final = 1
_PIN_DOMAIN: Final = b"local-backtest/pin/v1\x00"
# Bind gc plan domain once as an explicit module-level contract.
_GC_PLAN_DOMAIN: Final = b"local-backtest/gc-plan/v1\x00"
_GC_BATCH_DOMAIN: Final = b"local-backtest/gc-batch/v1\x00"
_GC_RECEIPT_DOMAIN: Final = b"local-backtest/gc-deletion-receipt/v1\x00"
_TREE_DOMAIN: Final = b"local-backtest/tree-inventory/v1\x00"


# Keep the verified artifact contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _VerifiedArtifact:
    descriptor: CommittedArtifact
    root: Path
    committed_at_ns: int
    # Declare files explicitly in the verified artifact contract.
    files: tuple[FileRecord, ...]
    tree_digest: ContentDigest

    @property
    def size_bytes(self) -> int:
        return sum(item.size for item in self.files)


# Keep the local retention repository contract and validation rules together.
class LocalRetentionRepository:
    """Filesystem records are authority; all operations obey retention/publication order."""

    def __init__(
        self,
        repository: LocalArtifactRepository,
        *,
        exclusive_lock_timeout_seconds: float | None = 0.0,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local retention repository init workflow in explicit, reviewable
        # steps.
        if exclusive_lock_timeout_seconds is not None and exclusive_lock_timeout_seconds < 0:
            raise ValueError("exclusive lock timeout must be non-negative or None")
        self._repository = repository
        self._layout = DataRootLayout(repository.data_root)
        self._exclusive_lock_timeout_seconds = exclusive_lock_timeout_seconds
        # Invoke ensure_foundation as a visible step within the local retention repository
        # init workflow.
        self._layout.ensure_foundation()
        self._retired_pins = self._layout.pins_directory / "retired"
        self._gc_root = self._layout.trash_directory / "gc-batches"
        self._receipts_root = self._layout.trash_directory / "deletion-receipts"
        self._ensure_metadata_directories()

    # Define local retention repository create pin as one focused operation with an
    # explicit boundary.
    def create_pin(
        self,
        *,
        pin_id: Identifier,
        roots: tuple[ArtifactId, ...],
        # Keep the reason input explicit in the create pin contract.
        reason: str,
        created_at_ns: int,
    ) -> PinRecord:
        # Execute the local retention repository create pin workflow in explicit,
        # reviewable steps.
        normalized_roots = _artifact_ids(roots, label="pin roots", require_nonempty=True)
        lease_id = Identifier(f"pin-{pin_id.value}")
        lease = self.acquire_lease(
            lease_id=lease_id,
            roots=normalized_roots,
            # Pass reason explicitly so acquire_lease receives a reviewable publish pin
            # and value input in local retention repository create pin.
            reason=f"publish pin {pin_id.value}",
        )
        try:
            # Perform the protected local retention repository create pin operation before
            # explicit failure handling.
            pin = _make_pin(
                pin_id=pin_id,
                roots=normalized_roots,
                closure=lease.info.transitive_closure,
                reason=reason,
                # Pass created at ns explicitly so _make_pin receives a reviewable
                # transitive closure and info input in local retention repository create
                # pin.
                created_at_ns=created_at_ns,
            )
            payload = _pin_payload(pin)
            destination = self._layout.pin(pin_id)
            with FileLock(self._layout.publication_lock, mode=LockMode.EXCLUSIVE):
                # Keep file lock, publication lock and layout active only for the bounded
                # local retention repository create pin operation.
                if self._retired_pin_by_id(pin_id) is not None:
                    # Handle the local retention repository create pin retired pin by id
                    # and pin id condition as a distinct block.
                    raise RetentionConflictError(
                        f"retired pin identity {pin_id.value!r} cannot be reused"
                    )
                published = publish_no_replace(
                    destination,
                    # Pass payload explicitly so publish_no_replace receives a reviewable
                    # value and tmp- input in local retention repository create pin.
                    payload,
                    temporary_name=f".{destination.name}.tmp-{uuid.uuid4().hex}",
                )
                if not published:
                    # Handle the local retention repository create pin not published
                    # branch as a distinct logical block.
                    existing = self._read_pin(destination)
                    if existing != pin:
                        # Handle the local retention repository create pin existing != pin
                        # branch as a distinct logical block.
                        raise RetentionConflictError(
                            f"pin {pin_id.value!r} already names different immutable content"
                        )
            return pin
        finally:
            # Invoke close as a visible step within the local retention repository create
            # pin workflow.
            lease.close()

    def retire_pin(self, pin_id: Identifier, *, retired_at_ns: int) -> PinRecord:
        # Execute the local retention repository retire pin workflow in explicit,
        # reviewable steps.
        if retired_at_ns < 0:
            raise ValueError("retirement time must be non-negative")
        active = self._layout.pin(pin_id)
        retention = FileLock(self._layout.retention_lock, mode=LockMode.SHARED)
        publication = FileLock(self._layout.publication_lock, mode=LockMode.EXCLUSIVE)
        # Acquire retention at an explicit local retention repository retire pin context
        # boundary so cleanup remains scoped.
        with retention, publication:
            # Keep retention active only for the bounded local retention repository retire
            # pin operation.
            if not _exists_no_follow(active):
                # Handle the local retention repository retire pin not
                # _exists_no_follow(active) branch as a distinct logical block.
                retired = self._retired_pin_by_id(pin_id)
                if retired is not None:
                    return retired
            pin = self._read_pin(active)
            if self._retired_pin_by_id(pin_id) is not None:
                # Fail the local retention repository retire pin path with
                # RetentionIntegrityError for pin is both active and retired when retired
                # pin by id and pin id is true; do not continue ambiguously.
                raise RetentionIntegrityError("pin is both active and retired")
            destination = self._retired_pins / (
                f"{active.stem}-{retired_at_ns:020d}-{pin.record_digest.hex}.json"
            )
            try:
                # Invoke lstat as a visible step within the local retention repository
                # retire pin workflow.
                destination.lstat()
            except FileNotFoundError:
                pass
            else:
                raise RetentionConflictError("pin retirement identity already exists")
            # Invoke rename for active and destination as a visible local retention
            # repository retire pin step.
            os.rename(active, destination)
            fsync_directory(self._layout.pins_directory)
            fsync_directory(self._retired_pins)
            return pin

    def active_pins(self) -> tuple[PinRecord, ...]:
        # Execute the local retention repository active pins workflow in explicit,
        # reviewable steps.
        with FileLock(self._layout.retention_lock, mode=LockMode.SHARED):
            return self._active_pins_locked()

    def acquire_lease(
        self,
        *,
        # Keep the lease id input explicit in the acquire lease contract.
        lease_id: Identifier,
        roots: tuple[ArtifactId, ...],
        reason: str,
    ) -> LocalArtifactLease:
        # Execute the local retention repository acquire lease workflow in explicit,
        # reviewable steps.
        normalized_roots = _artifact_ids(roots, label="lease roots", require_nonempty=True)
        if not reason or reason != reason.strip() or len(reason) > 500:
            raise ValueError("lease reason must be 1..500 characters without outer whitespace")
        handles: dict[str, ArtifactHandle] = {}
        pending = list(reversed(normalized_roots))
        # Keep expected failures inside the local retention repository acquire lease error
        # boundary.
        try:
            # Perform the protected local retention repository acquire lease operation
            # before explicit failure handling.
            while pending:
                # Keep the pending loop body bounded within local retention repository
                # acquire lease.
                artifact_id = pending.pop()
                if artifact_id.hex in handles:
                    continue
                handle = self._repository.open_committed(artifact_id)
                handles[artifact_id.hex] = handle
                # Invoke extend for input artifact ids and descriptor as a visible local
                # retention repository acquire lease step.
                pending.extend(
                    sorted(
                        handle.descriptor.input_artifact_ids,
                        key=lambda item: item.hex,
                        reverse=True,
                        # Complete sorted only after its input artifact ids and descriptor
                        # inputs are visible in local retention repository acquire lease.
                    )
                )
        except BaseException:
            # Translate the BaseException failure through the local retention repository
            # acquire lease boundary.
            for handle in handles.values():
                handle.close()
            raise
        closure = tuple(ArtifactId(value) for value in sorted(handles))
        return LocalArtifactLease(
            # Include info in the completed local retention repository acquire lease
            # result.
            info=ArtifactLeaseInfo(
                lease_id=lease_id,
                roots=normalized_roots,
                transitive_closure=closure,
                reason=reason,
                # Complete ArtifactLeaseInfo only after its lease id and normalized roots
                # inputs are visible in local retention repository acquire lease.
            ),
            handles=tuple(handles[value] for value in sorted(handles)),
        )

    def plan_garbage_collection(
        self,
        # Close the plan garbage collection signature after its explicit inputs.
        *,
        retained_roots: tuple[ArtifactId, ...],
        policy: GarbageCollectionPolicy,
        now_ns: int,
    ) -> GarbageCollectionPlan:
        # Execute the local retention repository plan garbage collection workflow in
        # explicit, reviewable steps.
        normalized = _artifact_ids(retained_roots, label="retained roots")
        with FileLock(self._layout.retention_lock, mode=LockMode.SHARED):
            # Keep file lock, retention lock and layout active only for the bounded local
            # retention repository plan garbage collection operation.
            return self._plan_locked(
                retained_roots=normalized,
                policy=policy,
                now_ns=now_ns,
            )

    # Define local retention repository execute garbage collection as one focused
    # operation with an explicit boundary.
    def execute_garbage_collection(
        self,
        plan: GarbageCollectionPlan,
        *,
        now_ns: int,
        # Keep the garbage collection batch input explicit in the execute garbage collection
        # contract.
    ) -> GarbageCollectionBatch:
        # Execute the local retention repository execute garbage collection workflow in
        # explicit, reviewable steps.
        if now_ns < plan.planned_at_ns:
            raise ValueError("GC execution time predates its plan")
        lock = FileLock(
            self._layout.retention_lock,
            mode=LockMode.EXCLUSIVE,
            # Pass timeout explicitly so FileLock receives a reviewable retention lock and
            # layout input in local retention repository execute garbage collection.
            timeout=self._exclusive_lock_timeout_seconds,
        )
        with lock:
            # Keep lock active only for the bounded local retention repository execute
            # garbage collection operation.
            refreshed = self._plan_locked(
                retained_roots=plan.retained_roots,
                policy=plan.policy,
                now_ns=plan.planned_at_ns,
            )
            # Evaluate the complete local retention repository execute garbage collection
            # plan id, candidates and pinned roots condition before guarded effects.
            if (
                refreshed.plan_id != plan.plan_id
                or refreshed.candidates != plan.candidates
                or refreshed.pinned_roots != plan.pinned_roots
            ):
                # Handle the local retention repository execute garbage collection plan
                # id, candidates and pinned roots condition as a distinct block.
                raise GarbageCollectionPlanStaleError(
                    "GC authority changed after dry run; create and approve a new plan"
                )
            inventory = self._verified_inventory_locked()
            batch_id = ContentDigest(
                # Keep the sha256 bytes and canonical json sha256_bytes step visible while
                # building batch id.
                sha256_bytes(
                    canonical_json(
                        {
                            "moved_at_ns": now_ns,
                            "plan_id": plan.plan_id.hex,
                            # Keep version named so the moved at ns and plan id payload
                            # passed to canonical_json remains self-describing within
                            # local retention repository execute garbage collection.
                            "version": 1,
                        }
                    ),
                    domain=_GC_BATCH_DOMAIN,
                )
                # Complete ContentDigest only after its moved at ns and plan id inputs are
                # visible in local retention repository execute garbage collection.
            )
            batch_root = self._gc_root / batch_id.hex
            try:
                batch_root.lstat()
            except FileNotFoundError:
                # Translate the FileNotFoundError failure through the local retention
                # repository execute garbage collection boundary.
                batch_root.mkdir(mode=0o700)
                fsync_directory(self._gc_root)
            else:
                raise RetentionConflictError("GC batch identity already exists")
            artifacts_root = batch_root / "artifacts"
            # Invoke mkdir as a visible step within the local retention repository execute
            # garbage collection workflow.
            artifacts_root.mkdir(mode=0o700)
            manifest_items: list[dict[str, object]] = []
            try:
                # Perform the protected local retention repository execute garbage
                # collection operation before explicit failure handling.
                for candidate in plan.candidates:
                    # Process plan.candidates inside the bounded local retention
                    # repository execute garbage collection loop.
                    verified = inventory.get(candidate.artifact_id.hex)
                    if verified is None or not _same_candidate(candidate, verified):
                        # Handle the local retention repository execute garbage collection
                        # verified, same candidate and candidate condition as a distinct
                        # block.
                        raise GarbageCollectionPlanStaleError(
                            "GC candidate changed during final revalidation"
                        )
                    kind_root = artifacts_root / candidate.kind.value
                    if not kind_root.exists():
                        # Handle the local retention repository execute garbage collection
                        # not kind_root.exists() branch as a distinct logical block.
                        kind_root.mkdir(mode=0o700)
                        fsync_directory(artifacts_root)
                    require_real_directory(kind_root, label="GC trash kind directory")
                    destination = kind_root / candidate.artifact_id.hex
                    os.rename(verified.root, destination)
                    # Invoke fsync_directory for parent and root as a visible local
                    # retention repository execute garbage collection step.
                    fsync_directory(verified.root.parent)
                    fsync_directory(kind_root)
                    manifest_items.append(
                        {
                            "artifact_id": candidate.artifact_id.hex,
                            # Pass files explicitly to append for artifact id and files.
                            "files": [record.as_json() for record in verified.files],
                            "kind": candidate.kind.value,
                            "size_bytes": candidate.size_bytes,
                            "tree_digest": candidate.tree_digest.hex,
                        }
                        # Complete append only after its artifact id and files inputs are
                        # visible in local retention repository execute garbage collection.
                    )
                manifest_identity = {
                    "artifacts": manifest_items,
                    "batch_id": batch_id.hex,
                    "moved_at_ns": now_ns,
                    # Keep the plan id component named inside the manifest identity
                    # contract.
                    "plan_id": plan.plan_id.hex,
                    "purge_not_before_ns": now_ns + plan.policy.trash_grace_period_ns,
                    "version": 1,
                }
                manifest_payload = canonical_json(manifest_identity)
                # Invoke write_durable_exclusive for json and batch root as a visible
                # local retention repository execute garbage collection step.
                write_durable_exclusive(batch_root / "batch.json", manifest_payload)
                marker_payload = canonical_json(
                    {
                        "batch_id": batch_id.hex,
                        "manifest_sha256": sha256_bytes(manifest_payload),
                        # Keep version named so the batch id and manifest sha256 payload
                        # passed to canonical_json remains self-describing within local
                        # retention repository execute garbage collection.
                        "version": 1,
                    }
                )
                write_durable_exclusive(batch_root / "COMMITTED", marker_payload)
                fsync_directory(batch_root)
                # Invoke fsync_directory for gc root as a visible local retention
                # repository execute garbage collection step.
                fsync_directory(self._gc_root)
            except BaseException:
                # A marker-less batch is explicit recoverable trash state.  It
                # is never eligible for purge and is not a deletion receipt.
                raise
            return GarbageCollectionBatch(
                batch_id=batch_id,
                plan_id=plan.plan_id,
                moved_at_ns=now_ns,
                # Pass purge not before ns explicitly so GarbageCollectionBatch receives a
                # reviewable plan id and trash grace period ns input in local retention
                # repository execute garbage collection.
                purge_not_before_ns=now_ns + plan.policy.trash_grace_period_ns,
                artifact_ids=tuple(candidate.artifact_id for candidate in plan.candidates),
            )

    def purge_trash(
        self,
        # Keep the batch id input explicit in the purge trash contract.
        batch_id: Identifier,
        *,
        now_ns: int,
    ) -> GarbageCollectionReceipt:
        # Execute the local retention repository purge trash workflow in explicit,
        # reviewable steps.
        parsed_batch_id = ContentDigest(batch_id.value)
        receipt_path = self._receipts_root / f"{parsed_batch_id.hex}.json"
        if receipt_path.exists():
            return self._read_receipt(receipt_path)
        lock = FileLock(
            # Pass self explicitly so FileLock receives a reviewable retention lock and
            # layout input in local retention repository purge trash.
            self._layout.retention_lock,
            mode=LockMode.EXCLUSIVE,
            timeout=self._exclusive_lock_timeout_seconds,
        )
        with lock:
            # Keep lock active only for the bounded local retention repository purge trash
            # operation.
            manifest, manifest_items = self._read_batch(parsed_batch_id)
            purge_not_before_ns = _integer(manifest, "purge_not_before_ns")
            if now_ns < purge_not_before_ns:
                raise RetentionConflictError("GC trash grace period has not elapsed")
            batch_root = self._gc_root / parsed_batch_id.hex
            # Assemble deleted bytes once so the local retention repository purge trash
            # workflow shares one value.
            deleted_bytes = 0
            deleted: list[ArtifactId] = []
            receipt_items: list[dict[str, object]] = []
            for item, records in manifest_items:
                # Process manifest_items inside the bounded local retention repository
                # purge trash loop.
                artifact_id = ArtifactId(_string(item, "artifact_id"))
                kind = ArtifactKind(_string(item, "kind"))
                artifact_root = batch_root / "artifacts" / kind.value / artifact_id.hex
                expected_digest = ContentDigest(_string(item, "tree_digest"))
                if records_digest(records, domain=_TREE_DOMAIN) != expected_digest.hex:
                    # Fail the local retention repository purge trash path with
                    # RetentionIntegrityError for gc trash inventory digest is corrupt
                    # when hex, records digest and records is true; do not continue
                    # ambiguously.
                    raise RetentionIntegrityError("GC trash inventory digest is corrupt")
                deleted_bytes += remove_verified_tree(artifact_root, records)
                deleted.append(artifact_id)
                receipt_items.append(
                    {
                        # Keep artifact id named so the artifact id and kind payload
                        # passed to append remains self-describing within local retention
                        # repository purge trash.
                        "artifact_id": artifact_id.hex,
                        "kind": kind.value,
                        "tree_digest": expected_digest.hex,
                    }
                )
            # Assemble identity once so the local retention repository purge trash
            # workflow shares one value.
            identity = {
                "artifacts": receipt_items,
                "batch_id": parsed_batch_id.hex,
                "deleted_at_ns": now_ns,
                "deleted_bytes": deleted_bytes,
                # Keep the version component named inside the identity contract.
                "version": 1,
            }
            digest = ContentDigest(
                sha256_bytes(canonical_json(identity), domain=_GC_RECEIPT_DOMAIN)
            )
            # Assemble receipt payload once so the local retention repository purge trash
            # workflow shares one value.
            receipt_payload = canonical_json({**identity, "receipt_digest": digest.hex})
            published = publish_no_replace(
                receipt_path,
                receipt_payload,
                temporary_name=f".{receipt_path.name}.tmp-{uuid.uuid4().hex}",
                # Complete publish_no_replace only after its value and tmp- inputs are visible
                # in local retention repository purge trash.
            )
            if not published:
                # Handle the local retention repository purge trash not published branch
                # as a distinct logical block.
                existing = self._read_receipt(receipt_path)
                if existing.receipt_digest != digest:
                    raise RetentionConflictError("deletion receipt identity collision")
            self._remove_empty_batch(batch_root)
            return GarbageCollectionReceipt(
                # Pass receipt digest explicitly so GarbageCollectionReceipt receives a
                # reviewable hex and tuple input in local retention repository purge
                # trash.
                receipt_digest=digest,
                batch_id=parsed_batch_id,
                deleted_at_ns=now_ns,
                artifact_ids=tuple(sorted(deleted, key=lambda item: item.hex)),
                deleted_bytes=deleted_bytes,
                # Complete GarbageCollectionReceipt only after its hex and tuple inputs are
                # visible in local retention repository purge trash.
            )

    def _plan_locked(
        self,
        *,
        retained_roots: tuple[ArtifactId, ...],
        # Keep the policy input explicit in the plan locked contract.
        policy: GarbageCollectionPolicy,
        now_ns: int,
    ) -> GarbageCollectionPlan:
        # Execute the local retention repository plan locked workflow in explicit,
        # reviewable steps.
        if now_ns < 0:
            raise ValueError("GC clock must be non-negative")
        inventory = self._verified_inventory_locked()
        pins = self._active_pins_locked()
        pinned_roots = _artifact_ids(
            # Keep the root and pin tuple step visible while building pinned roots.
            tuple(root for pin in pins for root in pin.roots),
            label="pinned roots",
        )
        for pin in pins:
            # Process pins inside the bounded local retention repository plan locked loop.
            actual = self._closure(pin.roots, inventory)
            if actual != pin.transitive_closure:
                # Handle the local retention repository plan locked actual !=
                # pin.transitive_closure branch as a distinct logical block.
                raise RetentionIntegrityError(
                    f"pin {pin.pin_id.value!r} closure disagrees with artifact manifests"
                )
        protected_roots = list(retained_roots) + list(pinned_roots)
        for verified in inventory.values():
            # Process inventory.values() inside the bounded local retention repository
            # plan locked loop.
            age_ns = now_ns - verified.committed_at_ns
            if age_ns < policy.minimum_artifact_age_ns:
                protected_roots.append(verified.descriptor.artifact_id)
        protected = {
            item.hex
            # Keep the closure and inventory _closure step visible while building
            # protected.
            for item in self._closure(
                _artifact_ids(tuple(protected_roots), label="protected roots"),
                inventory,
            )
        }
        # Assemble candidates once so the local retention repository plan locked workflow
        # shares one value.
        candidates: list[GarbageCollectionCandidate] = []
        consumed = 0
        for artifact_id in sorted(inventory):
            # Process sorted(inventory) inside the bounded local retention repository plan
            # locked loop.
            verified = inventory[artifact_id]
            if artifact_id in protected:
                continue
            if now_ns - verified.committed_at_ns < policy.minimum_artifact_age_ns:
                continue
            # Evaluate the complete local retention repository plan locked maximum sweep
            # bytes, consumed and size bytes condition before guarded effects.
            if consumed + verified.size_bytes > policy.maximum_sweep_bytes:
                continue
            candidate = GarbageCollectionCandidate(
                artifact_id=verified.descriptor.artifact_id,
                kind=verified.descriptor.kind,
                # Pass size bytes explicitly so GarbageCollectionCandidate receives a
                # reviewable artifact id and descriptor input in local retention
                # repository plan locked.
                size_bytes=verified.size_bytes,
                committed_at_ns=verified.committed_at_ns,
                tree_digest=verified.tree_digest,
            )
            candidates.append(candidate)
            # Assemble consumed once so the local retention repository plan locked
            # workflow shares one value.
            consumed += candidate.size_bytes
        identity = {
            "candidates": [_candidate_json(item) for item in candidates],
            "maximum_sweep_bytes": policy.maximum_sweep_bytes,
            "minimum_artifact_age_ns": policy.minimum_artifact_age_ns,
            # Keep the pinned roots component named inside the identity contract.
            "pinned_roots": [item.hex for item in pinned_roots],
            "planned_at_ns": now_ns,
            "retained_roots": [item.hex for item in retained_roots],
            "trash_grace_period_ns": policy.trash_grace_period_ns,
            "version": 1,
            # Complete the identity group only after its semantic components are visible.
        }
        plan_id = ContentDigest(sha256_bytes(canonical_json(identity), domain=_GC_PLAN_DOMAIN))
        return GarbageCollectionPlan(
            plan_id=plan_id,
            planned_at_ns=now_ns,
            # Pass policy explicitly so GarbageCollectionPlan receives a reviewable tuple
            # and plan id input in local retention repository plan locked.
            policy=policy,
            retained_roots=retained_roots,
            pinned_roots=pinned_roots,
            candidates=tuple(candidates),
        )

    # Define local retention repository verified inventory locked as one focused operation
    # with an explicit boundary.
    def _verified_inventory_locked(self) -> dict[str, _VerifiedArtifact]:
        # Execute the local retention repository verified inventory locked workflow in
        # explicit, reviewable steps.
        inventory: dict[str, _VerifiedArtifact] = {}
        for kind in ArtifactKind:
            for candidate in self._repository._candidate_roots(kind):
                marker = candidate / "COMMITTED"
                try:
                    marker.lstat()
                # Translate file not found error through the local retention repository
                # verified inventory locked boundary without hiding other errors.
                except FileNotFoundError:
                    # Staging/orphan recovery state is never swept by this GC.
                    continue
                try:
                    # Perform the protected local retention repository verified inventory
                    # locked operation before explicit failure handling.
                    descriptor_json = self._repository._verify_committed(
                        candidate,
                        expected_kind=kind,
                    )
                    # Assemble descriptor once so the local retention repository verified
                    # inventory locked workflow shares one value.
                    descriptor = _committed_from_descriptor(descriptor_json)
                    records = file_records(candidate)
                except Exception as error:
                    raise RetentionIntegrityError(
                        "committed artifact candidate failed verification"
                    ) from error
                artifact_id = descriptor.artifact_id
                if artifact_id.hex in inventory:
                    raise RetentionIntegrityError(
                        "artifact ID occurs in multiple physical locations"
                    )
                # Assemble inventory[artifact id hex] once so the local retention
                # repository verified inventory locked workflow shares one value.
                inventory[artifact_id.hex] = _VerifiedArtifact(
                    descriptor=descriptor,
                    root=candidate,
                    committed_at_ns=marker.lstat().st_mtime_ns,
                    files=records,
                    # Keep the content digest and records digest ContentDigest step
                    # visible while building inventory[artifact id.hex].
                    tree_digest=ContentDigest(records_digest(records, domain=_TREE_DOMAIN)),
                )
        return inventory

    @staticmethod
    def _closure(
        # Keep the roots input explicit in the closure contract.
        roots: tuple[ArtifactId, ...],
        inventory: dict[str, _VerifiedArtifact],
    ) -> tuple[ArtifactId, ...]:
        # Execute the local retention repository closure workflow in explicit, reviewable
        # steps.
        visited: dict[str, ArtifactId] = {}
        pending = list(reversed(roots))
        while pending:
            # Keep the pending loop body bounded within local retention repository
            # closure.
            artifact_id = pending.pop()
            if artifact_id.hex in visited:
                continue
            try:
                verified = inventory[artifact_id.hex]
            # Translate key error through the local retention repository closure boundary
            # without hiding other errors.
            except KeyError:
                # Translate the KeyError failure through the local retention repository
                # closure boundary.
                raise RetentionIntegrityError(
                    f"retention root or lineage input {artifact_id.hex} is missing"
                ) from None
            visited[artifact_id.hex] = artifact_id
            pending.extend(
                # Pass sorted explicitly to extend for input artifact ids and descriptor.
                sorted(
                    verified.descriptor.input_artifact_ids,
                    key=lambda item: item.hex,
                    reverse=True,
                )
                # Complete extend only after its input artifact ids and descriptor inputs are
                # visible in local retention repository closure.
            )
        return tuple(visited[value] for value in sorted(visited))

    def _active_pins_locked(self) -> tuple[PinRecord, ...]:
        # Execute the local retention repository active pins locked workflow in explicit,
        # reviewable steps.
        require_real_directory(self._layout.pins_directory, label="pins directory")
        pins: list[PinRecord] = []
        for path in sorted(self._layout.pins_directory.glob("*.json"), key=lambda item: item.name):
            pins.append(self._read_pin(path))
        ids = [pin.pin_id.value for pin in pins]
        # Guard this path with len(ids) != len(set(ids)) before applying effects.
        if len(ids) != len(set(ids)):
            raise RetentionIntegrityError("duplicate active pin identities")
        return tuple(sorted(pins, key=lambda item: item.pin_id.value))

    def _retired_pin_by_id(self, pin_id: Identifier) -> PinRecord | None:
        # Execute the local retention repository retired pin by id workflow in explicit,
        # reviewable steps.
        matches = [
            pin
            for path in sorted(self._retired_pins.glob("*.json"), key=lambda item: item.name)
            if (pin := self._read_pin(path)).pin_id == pin_id
        ]
        # Guard this path with len(matches) > 1 before applying effects.
        if len(matches) > 1:
            raise RetentionIntegrityError("retired pin identity occurs more than once")
        return matches[0] if matches else None

    def _read_pin(self, path: Path) -> PinRecord:
        # Execute the local retention repository read pin workflow in explicit, reviewable
        # steps.
        try:
            # Perform the protected local retention repository read pin operation before
            # explicit failure handling.
            document = parse_canonical_object(read_regular(path, label="pin"), label="pin")
            if (
                set(document)
                != {
                    "created_at_ns",
                    # Keep pin id visible while evaluating the pin version, document and
                    # created at ns guard.
                    "pin_id",
                    "reason",
                    "record_digest",
                    "roots",
                    "transitive_closure",
                    # Keep version visible while evaluating the pin version, document and
                    # created at ns guard.
                    "version",
                }
                or _integer(document, "version") != _PIN_VERSION
            ):
                raise RetentionIntegrityError("pin schema is unsupported")
            # Assemble pin id once so the local retention repository read pin workflow
            # shares one value.
            pin_id = Identifier(_string(document, "pin_id"))
            if path.parent == self._layout.pins_directory and path.name != f"{pin_id.value}.json":
                raise RetentionIntegrityError("pin identity does not match its filename")
            roots = _artifact_id_list(document.get("roots"), label="pin roots")
            closure = _artifact_id_list(
                # Keep the transitive closure get step visible while building closure.
                document.get("transitive_closure"),
                label="pin closure",
            )
            expected = _make_pin(
                pin_id=pin_id,
                # Pass roots explicitly so _make_pin receives a reviewable reason and
                # created at ns input in local retention repository read pin.
                roots=roots,
                closure=closure,
                reason=_string(document, "reason"),
                created_at_ns=_integer(document, "created_at_ns"),
            )
            # Evaluate the complete local retention repository read pin hex, string and
            # document condition before guarded effects.
            if _string(document, "record_digest") != expected.record_digest.hex:
                raise RetentionIntegrityError("pin checksum mismatch")
            return expected
        except RetentionIntegrityError:
            raise
        # Translate safe filesystem error through the local retention repository read pin
        # boundary without hiding other errors.
        except (SafeFilesystemError, TypeError, ValueError) as error:
            raise RetentionIntegrityError("pin record is corrupt") from error

    def _read_batch(
        self,
        batch_id: ContentDigest,
        # Keep the tuple input explicit in the read batch contract.
    ) -> tuple[dict[str, object], tuple[tuple[dict[str, object], tuple[FileRecord, ...]], ...]]:
        # Execute the local retention repository read batch workflow in explicit,
        # reviewable steps.
        root = self._gc_root / batch_id.hex
        try:
            # Perform the protected local retention repository read batch operation before
            # explicit failure handling.
            manifest_payload = read_regular(root / "batch.json", label="GC batch manifest")
            marker = parse_canonical_object(
                read_regular(root / "COMMITTED", label="GC batch marker"),
                label="GC batch marker",
            )
            # Assemble manifest once so the local retention repository read batch workflow
            # shares one value.
            manifest = parse_canonical_object(manifest_payload, label="GC batch manifest")
        except SafeFilesystemError as error:
            raise RetentionIntegrityError("GC batch is incomplete or corrupt") from error
        if marker != {
            "batch_id": batch_id.hex,
            # Keep manifest sha256 visible while evaluating the marker, batch id and
            # manifest sha256 guard.
            "manifest_sha256": sha256_bytes(manifest_payload),
            "version": 1,
        }:
            raise RetentionIntegrityError("GC batch marker does not authenticate its manifest")
        if (
            # Keep set visible while evaluating the manifest, artifacts and batch id
            # guard.
            set(manifest)
            != {
                "artifacts",
                "batch_id",
                "moved_at_ns",
                # Keep plan id visible while evaluating the manifest, artifacts and batch
                # id guard.
                "plan_id",
                "purge_not_before_ns",
                "version",
            }
            or _integer(manifest, "version") != 1
            # Evaluate the complete local retention repository read batch manifest, artifacts
            # and batch id condition before guarded effects.
        ):
            raise RetentionIntegrityError("GC batch schema is unsupported")
        if _string(manifest, "batch_id") != batch_id.hex:
            raise RetentionIntegrityError("GC batch identity mismatch")
        try:
            # Invoke ContentDigest for plan id and string as a visible local retention
            # repository read batch step.
            ContentDigest(_string(manifest, "plan_id"))
        except (TypeError, ValueError) as error:
            raise RetentionIntegrityError("GC batch plan identity is invalid") from error
        moved_at_ns = _integer(manifest, "moved_at_ns")
        if _integer(manifest, "purge_not_before_ns") < moved_at_ns:
            # Fail the local retention repository read batch path with
            # RetentionIntegrityError for gc batch grace interval is invalid when moved at
            # ns, integer and manifest is true; do not continue ambiguously.
            raise RetentionIntegrityError("GC batch grace interval is invalid")
        raw_items = manifest.get("artifacts")
        if not isinstance(raw_items, list):
            raise RetentionIntegrityError("GC batch artifacts must be a list")
        parsed: list[tuple[dict[str, object], tuple[FileRecord, ...]]] = []
        # Assemble ids once so the local retention repository read batch workflow shares
        # one value.
        ids: list[str] = []
        for raw in raw_items:
            # Process raw_items inside the bounded local retention repository read batch
            # loop.
            if not isinstance(raw, dict) or set(raw) != {
                "artifact_id",
                "files",
                "kind",
                "size_bytes",
                # Keep tree digest visible while evaluating the isinstance, raw and
                # artifact id guard.
                "tree_digest",
            }:
                raise RetentionIntegrityError("GC batch artifact schema is invalid")
            item = cast(dict[str, object], raw)
            try:
                # Perform the protected local retention repository read batch operation
                # before explicit failure handling.
                artifact_id = ArtifactId(_string(item, "artifact_id"))
                ArtifactKind(_string(item, "kind"))
                ContentDigest(_string(item, "tree_digest"))
                records = records_from_json(item.get("files"))
            except (SafeFilesystemError, TypeError, ValueError) as error:
                # Fail the local retention repository read batch path with
                # RetentionIntegrityError for gc batch artifact is invalid; do not
                # continue ambiguously.
                raise RetentionIntegrityError("GC batch artifact is invalid") from error
            if _integer(item, "size_bytes") != sum(record.size for record in records):
                raise RetentionIntegrityError("GC batch artifact size mismatch")
            ids.append(artifact_id.hex)
            parsed.append((item, records))
        # Evaluate the complete local retention repository read batch ids and sorted
        # condition before guarded effects.
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise RetentionIntegrityError("GC batch artifacts must be sorted and unique")
        return manifest, tuple(parsed)

    def _read_receipt(self, path: Path) -> GarbageCollectionReceipt:
        # Execute the local retention repository read receipt workflow in explicit,
        # reviewable steps.
        try:
            # Perform the protected local retention repository read receipt operation
            # before explicit failure handling.
            document = parse_canonical_object(
                read_regular(path, label="deletion receipt"),
                label="deletion receipt",
            )
            if (
                # Keep set visible while evaluating the document, artifacts and batch id
                # guard.
                set(document)
                != {
                    "artifacts",
                    "batch_id",
                    "deleted_at_ns",
                    # Keep deleted bytes visible while evaluating the document, artifacts
                    # and batch id guard.
                    "deleted_bytes",
                    "receipt_digest",
                    "version",
                }
                or _integer(document, "version") != 1
                # Evaluate the complete local retention repository read receipt document,
                # artifacts and batch id condition before guarded effects.
            ):
                raise RetentionIntegrityError("deletion receipt schema is unsupported")
            digest = ContentDigest(_string(document, "receipt_digest"))
            identity = dict(document)
            del identity["receipt_digest"]
            # Evaluate the complete local retention repository read receipt hex, sha256
            # bytes and digest condition before guarded effects.
            if sha256_bytes(canonical_json(identity), domain=_GC_RECEIPT_DOMAIN) != digest.hex:
                raise RetentionIntegrityError("deletion receipt checksum mismatch")
            raw_items = document.get("artifacts")
            if not isinstance(raw_items, list):
                raise RetentionIntegrityError("deletion receipt artifacts must be a list")
            # Assemble artifact ids once so the local retention repository read receipt
            # workflow shares one value.
            artifact_ids: list[ArtifactId] = []
            for raw in raw_items:
                # Process raw_items inside the bounded local retention repository read
                # receipt loop.
                if not isinstance(raw, dict) or set(raw) != {
                    "artifact_id",
                    "kind",
                    "tree_digest",
                }:
                    # Fail the local retention repository read receipt path with
                    # RetentionIntegrityError for deletion receipt artifact schema is
                    # invalid when isinstance, raw and artifact id is true; do not
                    # continue ambiguously.
                    raise RetentionIntegrityError("deletion receipt artifact schema is invalid")
                item = cast(dict[str, object], raw)
                artifact_ids.append(ArtifactId(_string(item, "artifact_id")))
                ArtifactKind(_string(item, "kind"))
                ContentDigest(_string(item, "tree_digest"))
            # Evaluate the complete local retention repository read receipt hex, sorted
            # and artifact ids condition before guarded effects.
            if [item.hex for item in artifact_ids] != sorted(
                item.hex for item in artifact_ids
            ) or len(artifact_ids) != len(set(artifact_ids)):
                # Handle the local retention repository read receipt hex, sorted and
                # artifact ids condition as a distinct block.
                raise RetentionIntegrityError(
                    "deletion receipt artifacts must be sorted and unique"
                )
            batch_id = ContentDigest(_string(document, "batch_id"))
            if path.name != f"{batch_id.hex}.json":
                # Fail the local retention repository read receipt path with
                # RetentionIntegrityError for deletion receipt filename mismatch when
                # name, path and hex is true; do not continue ambiguously.
                raise RetentionIntegrityError("deletion receipt filename mismatch")
            return GarbageCollectionReceipt(
                receipt_digest=digest,
                batch_id=batch_id,
                deleted_at_ns=_integer(document, "deleted_at_ns"),
                # Include artifact ids in the completed local retention repository read
                # receipt result.
                artifact_ids=tuple(artifact_ids),
                deleted_bytes=_integer(document, "deleted_bytes"),
            )
        except RetentionIntegrityError:
            raise
        # Translate safe filesystem error through the local retention repository read
        # receipt boundary without hiding other errors.
        except (SafeFilesystemError, TypeError, ValueError) as error:
            raise RetentionIntegrityError("deletion receipt is corrupt") from error

    def _remove_empty_batch(self, batch_root: Path) -> None:
        # Execute the local retention repository remove empty batch workflow in explicit,
        # reviewable steps.
        artifacts_root = batch_root / "artifacts"
        if artifacts_root.exists():
            # Handle the local retention repository remove empty batch
            # artifacts_root.exists() branch as a distinct logical block.
            for child in sorted(artifacts_root.iterdir(), key=lambda item: item.name):
                # Process sorted, iterdir and artifacts root inside the bounded local
                # retention repository remove empty batch loop.
                require_real_directory(child, label="GC batch kind directory")
                child.rmdir()
            artifacts_root.rmdir()
        os.unlink(batch_root / "batch.json")
        os.unlink(batch_root / "COMMITTED")
        # Invoke rmdir as a visible step within the local retention repository remove
        # empty batch workflow.
        batch_root.rmdir()
        fsync_directory(self._gc_root)

    def _ensure_metadata_directories(self) -> None:
        # Execute the local retention repository ensure metadata directories workflow in
        # explicit, reviewable steps.
        ensure_real_directory(self._retired_pins, parent=self._layout.pins_directory)
        ensure_real_directory(self._gc_root, parent=self._layout.trash_directory)
        ensure_real_directory(self._receipts_root, parent=self._layout.trash_directory)
        fsync_directory(self._layout.pins_directory)
        fsync_directory(self._layout.trash_directory)


# Keep the local artifact lease contract and validation rules together.
class LocalArtifactLease:
    def __init__(self, *, info: ArtifactLeaseInfo, handles: tuple[ArtifactHandle, ...]) -> None:
        # Execute the local artifact lease init workflow in explicit, reviewable steps.
        self._info = info
        self._handles = handles
        self._closed = False

    @property
    def info(self) -> ArtifactLeaseInfo:
        # Return the completed local artifact lease info result without a hidden fallback.
        return self._info

    def close(self) -> None:
        # Execute the local artifact lease close workflow in explicit, reviewable steps.
        if self._closed:
            return
        self._closed = True
        for handle in reversed(self._handles):
            handle.close()

    # Define local artifact lease enter as one focused operation with an explicit
    # boundary.
    def __enter__(self) -> LocalArtifactLease:
        # Execute the local artifact lease enter workflow in explicit, reviewable steps.
        if self._closed:
            raise RuntimeError("artifact lease is closed")
        return self

    def __exit__(
        self,
        # Keep the exc type input explicit in the exit contract.
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # Define local artifact lease del as one focused operation with an explicit boundary.
    def __del__(self) -> None:
        # Execute the local artifact lease del workflow in explicit, reviewable steps.
        if not getattr(self, "_closed", True):
            # Handle the local artifact lease del not getattr(self, '_closed', True)
            # branch as a distinct logical block.
            with suppress(BaseException):
                self.close()


def _make_pin(
    *,
    pin_id: Identifier,
    # Keep the roots input explicit in the make pin contract.
    roots: tuple[ArtifactId, ...],
    closure: tuple[ArtifactId, ...],
    reason: str,
    created_at_ns: int,
) -> PinRecord:
    # Execute the make pin workflow in explicit, reviewable steps.
    identity = {
        "created_at_ns": created_at_ns,
        "pin_id": pin_id.value,
        "reason": reason,
        "roots": [item.hex for item in roots],
        # Keep the transitive closure component named inside the identity contract.
        "transitive_closure": [item.hex for item in closure],
        "version": _PIN_VERSION,
    }
    digest = ContentDigest(sha256_bytes(canonical_json(identity), domain=_PIN_DOMAIN))
    return PinRecord(
        # Pass pin id explicitly so PinRecord receives a reviewable pin id and roots input
        # in make pin.
        pin_id=pin_id,
        roots=roots,
        transitive_closure=closure,
        reason=reason,
        created_at_ns=created_at_ns,
        # Pass record digest explicitly so PinRecord receives a reviewable pin id and
        # roots input in make pin.
        record_digest=digest,
    )


def _pin_payload(pin: PinRecord) -> bytes:
    # Execute the pin payload workflow in explicit, reviewable steps.
    return canonical_json(
        {
            "created_at_ns": pin.created_at_ns,
            "pin_id": pin.pin_id.value,
            "reason": pin.reason,
            # Keep record digest named so the reason and created at ns payload passed to
            # canonical_json remains self-describing within pin payload.
            "record_digest": pin.record_digest.hex,
            "roots": [item.hex for item in pin.roots],
            "transitive_closure": [item.hex for item in pin.transitive_closure],
            "version": _PIN_VERSION,
        }
        # Complete canonical_json only after its reason and created at ns inputs are visible
        # in pin payload.
    )


def _artifact_ids(
    values: tuple[ArtifactId, ...],
    *,
    label: str,
    # Keep the require nonempty input explicit in the artifact ids contract.
    require_nonempty: bool = False,
) -> tuple[ArtifactId, ...]:
    # Execute the artifact ids workflow in explicit, reviewable steps.
    normalized = tuple(ArtifactId(value) for value in sorted({item.hex for item in values}))
    if require_nonempty and not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _artifact_id_list(value: object, *, label: str) -> tuple[ArtifactId, ...]:
    # Execute the artifact id list workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RetentionIntegrityError(f"{label} must be a list of artifact IDs")
    parsed = tuple(ArtifactId(cast(str, item)) for item in value)
    if tuple(item.hex for item in parsed) != tuple(sorted(item.hex for item in parsed)) or len(
        parsed
        # Keep len visible while evaluating the parsed, hex and sorted guard.
    ) != len(set(parsed)):
        raise RetentionIntegrityError(f"{label} must be sorted and unique")
    return parsed


def _candidate_json(candidate: GarbageCollectionCandidate) -> dict[str, object]:
    # Execute the candidate json workflow in explicit, reviewable steps.
    return {
        "artifact_id": candidate.artifact_id.hex,
        "committed_at_ns": candidate.committed_at_ns,
        "kind": candidate.kind.value,
        "size_bytes": candidate.size_bytes,
        # Include tree digest in the completed candidate json result.
        "tree_digest": candidate.tree_digest.hex,
    }


def _same_candidate(candidate: GarbageCollectionCandidate, verified: _VerifiedArtifact) -> bool:
    # Execute the same candidate workflow in explicit, reviewable steps.
    return (
        candidate.artifact_id == verified.descriptor.artifact_id
        and candidate.kind is verified.descriptor.kind
        and candidate.size_bytes == verified.size_bytes
        and candidate.committed_at_ns == verified.committed_at_ns
        # Include tree digest in the completed same candidate result.
        and candidate.tree_digest == verified.tree_digest
    )


def _string(document: dict[str, object], key: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = document.get(key)
    if not isinstance(value, str):
        raise RetentionIntegrityError(f"{key} must be a string")
    return value


def _integer(document: dict[str, object], key: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetentionIntegrityError(f"{key} must be a non-negative integer")
    return value


def _exists_no_follow(path: Path) -> bool:
    # Execute the exists no follow workflow in explicit, reviewable steps.
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


# Bind all once as an explicit module-level contract.
__all__ = ["LocalArtifactLease", "LocalRetentionRepository"]
