"""Bounded restart evidence never replaces current filesystem authentication."""

from pathlib import Path

import pytest

# Exercise actual publication and verification, counting only expensive payload hashes.
from backtest.adapters.artifacts.localfs import repository as repository_module
from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    LocalArtifactRepository,
)

# The scanner exposes metadata inventory separately from ordinary authenticated opens.
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner

# These values describe immutable fixtures; no production catalog is consulted.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ArtifactId


def _publish(repository: LocalArtifactRepository, label: str) -> CommittedArtifact:
    """Use the regular durable publication path for one small distinct payload."""

    draft = ArtifactDraft(
        kind=ArtifactKind.SOURCE_INSPECTION,
        build_key=domain_digest("test.inventory-seed.v1", {"label": label}),
    )
    # Distinct bytes ensure each fixture has an independent committed identity.
    writer = repository.stage(draft)
    with writer.open_binary("payload.bin") as stream:
        stream.write(label.encode("ascii"))
    return writer.commit(b"{}")


def _observe_hashes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Preserve real hashes so the measurement cannot hide corruption."""

    original = repository_module._sha256_file
    paths: list[Path] = []

    # Control-file authentication deliberately remains outside this payload counter.
    def observe(path: Path) -> tuple[str, int]:
        paths.append(path)
        return original(path)

    monkeypatch.setattr(repository_module, "_sha256_file", observe)
    return paths


@pytest.mark.parametrize(
    ("entry_limit", "byte_limit", "retained"), [(2, 8192, 2), (8, 4096, 1), (8, 1, 0)]
)
def test_inventory_retains_only_requested_seeds_within_existing_cache_budgets(
    tmp_path: Path, entry_limit: int, byte_limit: int, retained: int
) -> None:
    """Inventory size cannot enlarge the metadata retained for cache warming."""

    publisher = LocalArtifactRepository(tmp_path)
    artifacts = tuple(_publish(publisher, str(index)) for index in range(12))
    # Fresh adapters have no process-local proof inherited from publication.
    reader = LocalArtifactRepository(
        tmp_path, verification_cache_entries=entry_limit, verification_cache_bytes=byte_limit
    )
    scanner = LocalCommittedArtifactScanner(reader)
    # A normal inventory retains no payload-fingerprint trees after returning.
    inventory, empty = scanner._inventory_with_seeds(frozenset())
    selected = frozenset(item.artifact_id.hex for item in artifacts[:6])
    repeated, seeds = scanner._inventory_with_seeds(selected)
    assert repeated == inventory and empty == {}
    # Both the requested subset and independent entry/byte budgets are enforced.
    assert len(seeds) == retained and set(seeds) <= selected
    weight = sum(
        repository_module._cached_verification_weight(seed[1], seed[2]) for seed in seeds.values()
    )
    assert weight <= byte_limit
    # Moving temporary evidence into the LRU preserves the same independent bounds.
    scanner._seed_verification_cache(inventory, tuple(item.artifact_id for item in artifacts[:6]))
    assert len(reader._verification_cache) <= entry_limit
    # Cache insertion uses the same charge as bounded temporary evidence collection.
    assert reader._verification_cache_current_bytes <= byte_limit


def test_inventory_drift_before_seeding_rejects_without_retaining_evidence(tmp_path: Path) -> None:
    """A CLEAN receipt's old inventory cannot authenticate subsequently changed bytes."""

    publisher = LocalArtifactRepository(tmp_path)
    committed = _publish(publisher, "alpha")
    reader = LocalArtifactRepository(tmp_path)
    scanner = LocalCommittedArtifactScanner(reader)
    # Capture genuine metadata before a same-size offline mutation.
    inventory = scanner.inventory()
    root = reader._find_artifact_root(committed.artifact_id)[1]
    (root / "payload.bin").write_bytes(b"omega")
    with pytest.raises(ArtifactIntegrityError, match="inventory changed"):
        scanner._seed_verification_cache(inventory, (committed.artifact_id,))
    # Failed seeding neither caches evidence nor disables the ordinary digest failure.
    assert reader._verification_cache == {}
    with pytest.raises(ArtifactIntegrityError, match="payload differs"):
        reader.open_committed(committed.artifact_id)


@pytest.mark.parametrize("member", ["payload.bin", "manifest.json"])
def test_seeded_open_rejects_post_inventory_mutation(tmp_path: Path, member: str) -> None:
    """Seeding does not exempt the first open from fingerprint and control checks."""

    publisher = LocalArtifactRepository(tmp_path)
    committed = _publish(publisher, "alpha")
    reader = LocalArtifactRepository(tmp_path)
    scanner = LocalCommittedArtifactScanner(reader)
    # Seed only the exact genuine inventory, then change bytes before the first read.
    scanner._seed_verification_cache(scanner.inventory(), (committed.artifact_id,))
    root = reader._find_artifact_root(committed.artifact_id)[1]
    (root / member).write_bytes(b"omega" if member == "payload.bin" else b"[]")
    with pytest.raises(ArtifactIntegrityError):
        reader.open_committed(committed.artifact_id)
    # A detected mutation removes the seed before attempting full verification.
    assert reader._verification_cache == {}


def test_seed_replacement_preserves_byte_charge_and_avoids_payload_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeated receipt seed has one memory charge and normal authenticated reads."""

    publisher = LocalArtifactRepository(tmp_path)
    committed = _publish(publisher, "alpha")
    reader = LocalArtifactRepository(tmp_path)
    scanner = LocalCommittedArtifactScanner(reader)
    # Payload counters begin only after regular publication has verified the fixture.
    paths = _observe_hashes(monkeypatch)
    inventory = scanner.inventory()
    scanner._seed_verification_cache(inventory, (committed.artifact_id,))
    initial_charge = reader._verification_cache_current_bytes
    scanner._seed_verification_cache(inventory, (committed.artifact_id,))
    # Repeated seeds replace evidence; they cannot accumulate phantom memory charges.
    reader.open_committed(committed.artifact_id).close()
    assert reader._verification_cache_current_bytes == initial_charge > 0
    assert paths == []


def test_seed_budget_miss_performs_full_payload_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Insufficient metadata budget changes speed only, preserving authentication."""

    publisher = LocalArtifactRepository(tmp_path)
    committed = _publish(publisher, "alpha")
    reader = LocalArtifactRepository(tmp_path, verification_cache_bytes=1)
    scanner = LocalCommittedArtifactScanner(reader)
    # An intentionally tiny supported budget cannot retain even one descriptor.
    paths = _observe_hashes(monkeypatch)
    scanner._seed_verification_cache(scanner.inventory(), (committed.artifact_id,))
    reader.open_committed(committed.artifact_id).close()
    assert [path.name for path in paths] == ["payload.bin"]
    assert reader._verification_cache_current_bytes == 0


def test_seed_selection_rejects_missing_and_duplicate_ids(tmp_path: Path) -> None:
    """Malformed selection cannot borrow evidence from a different artifact."""

    repository = LocalArtifactRepository(tmp_path)
    committed = _publish(repository, "alpha")
    scanner = LocalCommittedArtifactScanner(repository)
    inventory = scanner.inventory()
    # Duplicates and absent exact IDs are distinct from ordinary budget misses.
    with pytest.raises(ValueError, match="unique"):
        scanner._seed_verification_cache(inventory, (committed.artifact_id,) * 2)
    with pytest.raises(ArtifactIntegrityError, match="absent"):
        scanner._seed_verification_cache(inventory, (ArtifactId("f" * 64),))
