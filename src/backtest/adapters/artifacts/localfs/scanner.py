"""Recovery discovery for the normative local artifact repository layout."""

from __future__ import annotations

import hashlib
from pathlib import Path

from backtest.adapters.artifacts.localfs.placement import artifact_leaf_names_artifact_id
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    LocalArtifactRepository,
    _artifact_file_fingerprint,
    _ArtifactFingerprint,
    _cached_verification_weight,
    _canonical_json,
    _committed_from_descriptor,
    _parse_json_object,
    _read_regular_file,
    _verify_cached_control_files,
    # Close the repository import after its required symbols are visible.
)
from backtest.application.catalog_models import ArtifactInventory, ArtifactInventoryEntry
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.domain.identifiers import ArtifactId, ContentDigest

_INVENTORY_DOMAIN = b"local-backtest/artifact-inventory/v1\x00"
_VerificationSeed = tuple[Path, _ArtifactFingerprint, bytes]


class LocalCommittedArtifactScanner:
    """Discover candidates by name and accept them only through ``open_committed``.

    Directory enumeration is used solely to find candidate content IDs.  It is
    never treated as a manifest or as proof of commit.
    """

    def __init__(self, repository: LocalArtifactRepository) -> None:
        self._repository = repository

    def scan(self) -> tuple[CommittedArtifact, ...]:
        # Execute the local committed artifact scanner scan workflow in explicit,
        # reviewable steps.
        discovered: dict[str, CommittedArtifact] = {}
        for kind in ArtifactKind:
            for candidate in self._repository._candidate_roots(kind):
                # A final directory without a marker is recovery/orphan state,
                # not a committed artifact and not catalog input.
                try:
                    (candidate / "COMMITTED").lstat()
                except FileNotFoundError:
                    continue
                artifact_id = (
                    ArtifactId(candidate.name)
                    if artifact_leaf_names_artifact_id(kind)
                    else self._repository._candidate_descriptor_id(candidate)
                )
                if artifact_id is None:
                    raise ArtifactIntegrityError(
                        "committed artifact candidate has no canonical descriptor ID"
                    )
                handle = self._repository.open_committed(artifact_id)
                try:
                    # Assemble descriptor once so the local committed artifact scanner
                    # scan workflow shares one value.
                    descriptor = handle.descriptor
                finally:
                    handle.close()
                previous = discovered.setdefault(artifact_id.hex, descriptor)
                if previous != descriptor:
                    # Handle the local committed artifact scanner scan previous !=
                    # descriptor branch as a distinct logical block.
                    raise RuntimeError(
                        "one artifact ID resolved to different committed descriptors"
                    )
        return tuple(discovered[key] for key in sorted(discovered))

    def inventory(self) -> ArtifactInventory:
        """Read bounded control bytes and stat metadata, never payload contents."""

        inventory, _ = self._inventory_with_seeds(frozenset())
        return inventory

    def _inventory_with_seeds(
        self, selected_ids: frozenset[str]
    ) -> tuple[ArtifactInventory, dict[str, _VerificationSeed]]:
        """Retain only selected metadata within the repository's existing cache budget."""

        hasher = hashlib.sha256(_INVENTORY_DOMAIN)
        entries: list[ArtifactInventoryEntry] = []
        seeds: dict[str, _VerificationSeed] = {}
        seed_bytes = 0
        # Candidate names discover roots; control files authenticate each descriptor.
        for kind in ArtifactKind:
            for candidate in self._repository._candidate_roots(kind):
                try:
                    (candidate / "COMMITTED").lstat()
                except FileNotFoundError:
                    # Markerless recovery orphans cannot supply reusable evidence.
                    continue
                entry, fingerprint_payload, seed = self._inventory_candidate(kind, candidate)
                entries.append(entry)
                artifact_id = entry.descriptor.artifact_id.hex
                # Both existing bounds apply before retaining any fingerprint tree.
                if artifact_id in selected_ids:
                    weight = _cached_verification_weight(seed[1], seed[2])
                    within_entries = len(seeds) < self._repository._verification_cache_entries
                    # File-count metadata is charged even when descriptor bytes are tiny.
                    within_bytes = (
                        seed_bytes + weight <= self._repository._verification_cache_max_bytes
                    )
                    # An oversized seed is a cache miss, never a verification exemption.
                    if within_entries and within_bytes:
                        seeds[artifact_id] = seed
                        seed_bytes += weight
                # Length framing prevents ambiguity between canonical inventory records.
                hasher.update(len(fingerprint_payload).to_bytes(8, "big"))
                hasher.update(fingerprint_payload)

        # Global ordering is unchanged by the optional bounded seed selection.
        ordered = tuple(sorted(entries, key=lambda item: item.descriptor.artifact_id.hex))
        inventory = ArtifactInventory(ContentDigest(hasher.hexdigest()), ordered)
        return inventory, seeds

    def _seed_verification_cache(
        self,
        inventory: ArtifactInventory,
        artifact_ids: tuple[ArtifactId, ...],
    ) -> None:
        """Re-authenticate the receipt cut before moving bounded evidence into the LRU."""

        identifiers = tuple(item.hex for item in artifact_ids)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("verification seed artifact IDs must be unique")
        # A second metadata-only pass avoids retaining all payload fingerprints.
        current, seeds = self._inventory_with_seeds(frozenset(identifiers))
        if current != inventory:
            raise ArtifactIntegrityError("artifact inventory changed before verification seeding")
        available = {entry.descriptor.artifact_id.hex for entry in current.entries}
        # Missing selected artifacts cannot be confused with budget-driven cache misses.
        if any(identifier not in available for identifier in identifiers):
            raise ArtifactIntegrityError("verification seed artifact is absent")
        for identifier in identifiers:
            seed = seeds.pop(identifier, None)
            # Metadata beyond either hard cache limit receives ordinary full verification.
            if seed is None:
                continue
            self._repository._seed_verification_cache(*seed)

    def _inventory_candidate(
        self,
        kind: ArtifactKind,
        candidate: Path,
    ) -> tuple[ArtifactInventoryEntry, bytes, _VerificationSeed]:
        """Build stable cheap evidence for one canonical-shape candidate root."""

        # Capture the whole tree before reading control files to close mutation races.
        before = _artifact_file_fingerprint(candidate)
        descriptor_bytes = _read_regular_file(
            candidate / "artifact.json",
            label="artifact descriptor",
        )
        # Parse only the bounded descriptor, without opening any large payload member.
        descriptor = _parse_json_object(descriptor_bytes, label="artifact descriptor")
        # Canonical control bytes are an operand of the durable inventory digest.
        if descriptor_bytes != _canonical_json(descriptor):
            raise ArtifactIntegrityError("artifact descriptor is not canonical JSON")

        # Small authority files are re-authenticated even on the restart fast path.
        _verify_cached_control_files(candidate, descriptor, descriptor_bytes)
        artifact = _committed_from_descriptor(descriptor)
        # Placement remains authenticated independently from the rebuildable index.
        if artifact.kind is not kind:
            raise ArtifactIntegrityError("inventory descriptor kind disagrees with placement")
        if artifact_leaf_names_artifact_id(kind) and candidate.name != artifact.artifact_id.hex:
            raise ArtifactIntegrityError("inventory descriptor ID disagrees with placement")

        # Authenticate the same tree on both sides of the small control-file reads.
        after = _artifact_file_fingerprint(candidate)
        if after != before:
            raise ArtifactIntegrityError("artifact changed while collecting inventory")
        latest_change_ns = max(max(item[-2], item[-1]) for item in after)
        # The receipt binds both exact metadata and the verified catalog descriptor.
        entry = ArtifactInventoryEntry(artifact, latest_change_ns)
        payload = _canonical_json(
            {
                "descriptor": descriptor,
                "fingerprint": [list(item) for item in after],
                # The physical path is operational evidence, not artifact identity.
                "root": candidate.relative_to(self._repository.data_root).as_posix(),
            }
        )
        return entry, payload, (candidate, after, descriptor_bytes)


__all__ = ["LocalCommittedArtifactScanner"]
