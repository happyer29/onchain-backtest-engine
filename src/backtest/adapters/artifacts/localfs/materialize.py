"""Verified single-link copies of an exact artifact closure.

The benchmark control-plane harness uses this adapter to give an isolated
controller its own filesystem authority. It intentionally never hard-links
artifact members: repository readers require every committed member to have a
link count of exactly one.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.retention import LocalRetentionRepository
from backtest.adapters.artifacts.localfs.safe_io import (
    # Include file record so the safe io dependency remains explicit.
    FileRecord,
    copy_tree_verified,
    ensure_real_directory,
    file_records,
    fsync_directory,
    # Include records digest so the safe io dependency remains explicit.
    records_digest,
    require_real_directory,
)
from backtest.application.models import CommittedArtifact
from backtest.domain.hashing import domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier

_TREE_DIGEST_DOMAIN = b"local-backtest/isolated-artifact-tree/v1\x00"


class ArtifactClosureMaterializationError(RuntimeError):
    """An exact closure cannot be copied within its hard disk bounds."""


@dataclass(frozen=True, slots=True)
class MaterializedArtifactClosure:
    """Evidence for one independently verified private artifact authority."""

    data_root: Path
    roots: tuple[ArtifactId, ...]
    transitive_closure: tuple[ArtifactId, ...]
    logical_bytes: int
    closure_digest: ContentDigest


# Keep the inventory item contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _InventoryItem:
    descriptor: CommittedArtifact
    source_root: Path
    relative_root: PurePosixPath
    files: tuple[FileRecord, ...]
    # Declare tree digest explicitly in the inventory item contract.
    tree_digest: ContentDigest

    @property
    def logical_bytes(self) -> int:
        return sum(item.size for item in self.files)


def materialize_verified_artifact_closure(
    # Keep the source input explicit in the materialize verified artifact closure
    # contract.
    source: LocalArtifactRepository,
    *,
    roots: tuple[ArtifactId, ...],
    destination_root: Path,
    maximum_copy_bytes: int,
    # Keep the minimum free after bytes input explicit in the materialize verified
    # artifact closure contract.
    minimum_free_after_bytes: int,
) -> MaterializedArtifactClosure:
    """Copy one leased closure and re-open every artifact from the copy.

    Setup is deliberately a separate operation from benchmark timing. The
    caller owns cleanup of ``destination_root`` and must keep it private.
    """

    _validate_limits(maximum_copy_bytes, minimum_free_after_bytes)
    normalized_roots = _ordered_artifact_ids(roots, label="materialization roots")
    destination = destination_root.resolve()
    if destination.exists():
        raise ArtifactClosureMaterializationError("isolated data root already exists")
    # Invoke require_real_directory for isolated data-root parent and parent as a visible
    # materialize verified artifact closure step.
    require_real_directory(destination.parent, label="isolated data-root parent")

    lease_key = domain_digest(
        "backtest.benchmark-artifact-materialization-lease.v1",
        {"roots": [item.hex for item in normalized_roots]},
    )
    # Assemble retention once so the materialize verified artifact closure workflow shares
    # one value.
    retention = LocalRetentionRepository(source)
    with retention.acquire_lease(
        lease_id=Identifier(f"benchmark-materialize-{lease_key.hex}"),
        roots=normalized_roots,
        reason="materialize exact benchmark control-plane authority",
        # Complete acquire_lease only after its benchmark-materialize- and materialize exact
        # benchmark control-plane authority inputs are visible in materialize verified
        # artifact closure.
    ) as lease:
        # Keep acquire lease, retention and normalized roots active only for the bounded
        # materialize verified artifact closure operation.
        closure = lease.info.transitive_closure
        inventory = _inventory(source, closure)
        logical_bytes = sum(item.logical_bytes for item in inventory.values())
        if logical_bytes > maximum_copy_bytes:
            # Handle the materialize verified artifact closure logical_bytes >
            # maximum_copy_bytes branch as a distinct logical block.
            raise ArtifactClosureMaterializationError(
                "artifact closure exceeds the isolated-copy hard quota"
            )
        free_bytes = shutil.disk_usage(destination.parent).free
        if free_bytes - logical_bytes < minimum_free_after_bytes:
            # Handle the materialize verified artifact closure minimum free after bytes,
            # free bytes and logical bytes condition as a distinct block.
            raise ArtifactClosureMaterializationError(
                "artifact closure copy would cross the disk free-space reserve"
            )

        copied = LocalArtifactRepository(destination)
        _copy_inventory(inventory, copied)
        # Invoke _verify_destination for copied and normalized roots as a visible
        # materialize verified artifact closure step.
        _verify_destination(
            copied,
            roots=normalized_roots,
            expected_closure=closure,
            expected=inventory,
            # Complete _verify_destination only after its copied and normalized roots inputs
            # are visible in materialize verified artifact closure.
        )
        closure_digest = _closure_digest(normalized_roots, closure, inventory)

    return MaterializedArtifactClosure(
        data_root=destination,
        roots=normalized_roots,
        # Pass transitive closure explicitly so MaterializedArtifactClosure receives a
        # reviewable destination and normalized roots input in materialize verified
        # artifact closure.
        transitive_closure=closure,
        logical_bytes=logical_bytes,
        closure_digest=closure_digest,
    )


def _validate_limits(maximum_copy_bytes: int, minimum_free_after_bytes: int) -> None:
    # Execute the validate limits workflow in explicit, reviewable steps.
    if (
        isinstance(maximum_copy_bytes, bool)
        or not isinstance(maximum_copy_bytes, int)
        or maximum_copy_bytes <= 0
    ):
        # Fail the validate limits path with ValueError for maximum copy bytes must be a
        # positive integer when isinstance and maximum copy bytes is true; do not continue
        # ambiguously.
        raise ValueError("maximum_copy_bytes must be a positive integer")
    if (
        isinstance(minimum_free_after_bytes, bool)
        or not isinstance(minimum_free_after_bytes, int)
        or minimum_free_after_bytes < 0
        # Evaluate the complete validate limits isinstance and minimum free after bytes
        # condition before guarded effects.
    ):
        raise ValueError("minimum_free_after_bytes must be a non-negative integer")


def _ordered_artifact_ids(
    values: tuple[ArtifactId, ...],
    *,
    # Keep the label input explicit in the ordered artifact ids contract.
    label: str,
) -> tuple[ArtifactId, ...]:
    # Execute the ordered artifact ids workflow in explicit, reviewable steps.
    if not values:
        raise ValueError(f"{label} must not be empty")
    ordered = tuple(sorted(values, key=lambda item: item.hex))
    if values != ordered or len(values) != len(set(values)):
        raise ValueError(f"{label} must be sorted and unique")
    # Return the completed ordered artifact ids result without a hidden fallback.
    return values


def _inventory(
    source: LocalArtifactRepository,
    closure: tuple[ArtifactId, ...],
) -> dict[ArtifactId, _InventoryItem]:
    # Execute the inventory workflow in explicit, reviewable steps.
    inventory: dict[ArtifactId, _InventoryItem] = {}
    for artifact_id in closure:
        # Process closure inside the bounded inventory loop.
        handle = source.open_committed(artifact_id)
        try:
            descriptor = handle.descriptor
        finally:
            handle.close()
        _, source_root = source._find_artifact_root(descriptor.artifact_id)
        relative_root = PurePosixPath(source_root.relative_to(source.data_root).as_posix())
        records = file_records(source_root)
        inventory[artifact_id] = _InventoryItem(
            # Pass descriptor explicitly so _InventoryItem receives a reviewable content
            # digest and records digest input in inventory.
            descriptor=descriptor,
            source_root=source_root,
            relative_root=relative_root,
            files=records,
            tree_digest=ContentDigest(records_digest(records, domain=_TREE_DIGEST_DOMAIN)),
        )
    # Return the completed inventory result without a hidden fallback.
    return inventory


def _copy_inventory(
    inventory: dict[ArtifactId, _InventoryItem],
    destination: LocalArtifactRepository,
) -> None:
    # Execute the copy inventory workflow in explicit, reviewable steps.
    synchronized_directories: set[Path] = {destination.data_root}
    for item in inventory.values():
        parent = destination.data_root
        for part in item.relative_root.parts[:-1]:
            child = parent / part
            ensure_real_directory(child, parent=parent)
            synchronized_directories.add(parent)
            synchronized_directories.add(child)
            parent = child
        copy_tree_verified(
            item.source_root,
            parent / item.relative_root.name,
            # Pass expected explicitly so copy_tree_verified receives a reviewable source
            # root and hex input in copy inventory.
            expected=item.files,
        )
    for directory in sorted(
        synchronized_directories,
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        fsync_directory(directory)


# Define verify destination as one focused operation with an explicit boundary.
def _verify_destination(
    destination: LocalArtifactRepository,
    *,
    roots: tuple[ArtifactId, ...],
    expected_closure: tuple[ArtifactId, ...],
    # Keep the expected input explicit in the verify destination contract.
    expected: dict[ArtifactId, _InventoryItem],
) -> None:
    # Execute the verify destination workflow in explicit, reviewable steps.
    observed: set[ArtifactId] = set()
    pending = list(reversed(roots))
    while pending:
        # Keep the pending loop body bounded within verify destination.
        artifact_id = pending.pop()
        if artifact_id in observed:
            continue
        item = expected.get(artifact_id)
        if item is None:
            # Handle the verify destination item is None branch as a distinct logical
            # block.
            raise ArtifactClosureMaterializationError(
                "copied artifact references an item outside the leased closure"
            )
        handle = destination.open_committed(artifact_id)
        try:
            # Assemble descriptor once so the verify destination workflow shares one
            # value.
            descriptor = handle.descriptor
        finally:
            handle.close()
        if descriptor != item.descriptor:
            # Handle the verify destination descriptor != item.descriptor branch as a
            # distinct logical block.
            raise ArtifactClosureMaterializationError(
                "copied artifact descriptor differs from the verified source"
            )
        observed.add(artifact_id)
        pending.extend(reversed(descriptor.input_artifact_ids))
    # Assemble ordered once so the verify destination workflow shares one value.
    ordered = tuple(sorted(observed, key=lambda item: item.hex))
    if ordered != expected_closure:
        # Handle the verify destination ordered != expected_closure branch as a distinct
        # logical block.
        raise ArtifactClosureMaterializationError(
            "copied artifact graph differs from the leased transitive closure"
        )


def _closure_digest(
    roots: tuple[ArtifactId, ...],
    # Keep the closure input explicit in the closure digest contract.
    closure: tuple[ArtifactId, ...],
    inventory: dict[ArtifactId, _InventoryItem],
) -> ContentDigest:
    # Execute the closure digest workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.isolated-artifact-closure.v1",
        {
            "artifacts": [
                {
                    # Keep artifact id named so the v1 and artifacts payload passed to
                    # domain_digest remains self-describing within closure digest.
                    "artifact_id": artifact_id.hex,
                    "descriptor": inventory[artifact_id].descriptor.manifest_digest.hex,
                    "tree": inventory[artifact_id].tree_digest.hex,
                }
                for artifact_id in closure
                # Close the v1 and artifacts payload only after all closure digest fields are
                # present.
            ],
            "roots": [item.hex for item in roots],
        },
    )


__all__ = [
    # Keep the artifact closure materialization error component named inside the all
    # contract.
    "ArtifactClosureMaterializationError",
    "MaterializedArtifactClosure",
    "materialize_verified_artifact_closure",
]
