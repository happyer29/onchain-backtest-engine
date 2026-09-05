# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import LocalArtifactRepository

# Import artifact catalog at the visible module dependency boundary.
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.adapters.catalog.sqlite.shard_ledger import SQLiteShardLedger
from backtest.application.canonical_data import SourceBoundary, ValidationStatus
from backtest.application.catalog_models import BuildKeyCollisionError

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.source_ledger import (
    CommittedShardRevision,
    ShardLedgerConflictError,
)

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    IngestionCompleteness,
    SourceConsistency,
)
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange


def _publish(
    repository: LocalArtifactRepository,
    *,
    payload: bytes,
    # Keep the build key input explicit in the publish contract.
    build_key: str,
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            build_key=ContentDigest(build_key),
        )
        # Complete stage only after its canonical distribution and artifact draft inputs are
        # visible in publish.
    )
    with writer.open_binary("part-00000.parquet") as stream:
        stream.write(payload)
    manifest = canonical_json_bytes(
        {"logical_content_hash": ContentDigest(build_key).hex, "version": 1}
    )
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def _boundary(
    # Keep the start input explicit in the boundary contract.
    start: int,
    end: int,
    *,
    revision_digit: str,
    validation_status: ValidationStatus = ValidationStatus.PASS,
    # Keep the source boundary input explicit in the boundary contract.
) -> SourceBoundary:
    # Execute the boundary workflow in explicit, reviewable steps.
    return SourceBoundary(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        capability_schema_version="v1",
        block_range=BlockRange(
            # Pass solana mainnet network id explicitly so BlockRange receives a
            # reviewable solana mainnet network id and block32 transaction32 position
            # schema id input in boundary.
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            start,
            end,
        ),
        # Pass snapshot cut to block explicitly so SourceBoundary receives a reviewable
        # source and v1 input in boundary.
        snapshot_cut_to_block=end,
        chain_finality=ChainFinality.UNKNOWN,
        ingestion_watermark_to_block=None,
        upstream_revision=None,
        internal_revision=ContentDigest(revision_digit * 64),
        # Pass source consistency explicitly so SourceBoundary receives a reviewable
        # source and v1 input in boundary.
        source_consistency=SourceConsistency.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        validation_status=validation_status,
        query_fingerprints=(ContentDigest(f"{int(revision_digit, 16):x}" * 64),),
    )


# Define record as one focused operation with an explicit boundary.
def _record(
    catalog: SQLiteArtifactCatalog,
    ledger: SQLiteShardLedger,
    repository: LocalArtifactRepository,
    *,
    # Keep the start input explicit in the record contract.
    start: int,
    end: int,
    digit: str,
    validation_status: ValidationStatus = ValidationStatus.PASS,
) -> CommittedArtifact:
    # Execute the record workflow in explicit, reviewable steps.
    artifact = _publish(
        repository,
        payload=f"{start}:{end}:{digit}".encode(),
        build_key=digit * 64,
    )
    # Invoke index_committed for artifact as a visible record step.
    catalog.index_committed(artifact)
    ledger.record_revision(
        CommittedShardRevision(
            artifact=artifact,
            boundary=_boundary(
                # Pass start explicitly so _boundary receives a reviewable start and end
                # input in record.
                start,
                end,
                revision_digit=digit,
                validation_status=validation_status,
            ),
            # Complete CommittedShardRevision only after its boundary and artifact inputs are
            # visible in record.
        )
    )
    return artifact


def test_frontier_stops_at_gap_and_failed_revision(tmp_path: Path) -> None:
    # Execute the test frontier stops at gap and failed revision workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    ledger = SQLiteShardLedger(database, catalog)
    _record(catalog, ledger, repository, start=0, end=10, digit="1")
    # Invoke _record for 2 and catalog as a visible test frontier stops at gap and failed
    # revision step.
    _record(catalog, ledger, repository, start=20, end=30, digit="2")
    _record(
        catalog,
        ledger,
        repository,
        # Pass start explicitly so _record receives a reviewable 3 and fail input in test
        # frontier stops at gap and failed revision.
        start=30,
        end=40,
        digit="3",
        validation_status=ValidationStatus.FAIL,
    )

    # Assemble frontier once so the test frontier stops at gap and failed revision
    # workflow shares one value.
    frontier = ledger.contiguous_frontier(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        capability_schema_version="v1",
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so contiguous_frontier receives a reviewable
        # source and v1 input in test frontier stops at gap and failed revision.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        coverage_from_block_ordinal=0,
    )
    assert frontier.frontier_block_ordinal == 10

    _record(catalog, ledger, repository, start=10, end=20, digit="4")
    # Assemble frontier once so the test frontier stops at gap and failed revision
    # workflow shares one value.
    frontier = ledger.contiguous_frontier(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        capability_schema_version="v1",
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so contiguous_frontier receives a reviewable
        # source and v1 input in test frontier stops at gap and failed revision.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        coverage_from_block_ordinal=0,
    )
    assert frontier.frontier_block_ordinal == 30


def test_ledger_preserves_unknown_fidelity_without_promotion(tmp_path: Path) -> None:
    # Execute the test ledger preserves unknown fidelity without promotion workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    ledger = SQLiteShardLedger(database, catalog)
    artifact = _record(catalog, ledger, repository, start=0, end=10, digit="1")

    # Recording the exact immutable revision is idempotent.
    ledger.record_revision(
        CommittedShardRevision(
            artifact=artifact,
            boundary=_boundary(0, 10, revision_digit="1"),
        )
        # Complete record_revision only after its 1 and committed shard revision inputs are
        # visible in test ledger preserves unknown fidelity without promotion.
    )

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test ledger preserves unknown fidelity without promotion
        # operation before explicit failure handling.
        row = connection.execute(
            """
            SELECT chain_finality, source_consistency, completeness,
                   ingestion_watermark_to_block
            FROM shard_ledger
            """
        ).fetchone()
    finally:
        connection.close()
    # Verify row is not None before this scenario is accepted.
    assert row is not None
    assert str(row["chain_finality"]) == "UNKNOWN"
    assert str(row["source_consistency"]) == "UNKNOWN"
    assert str(row["completeness"]) == "UNKNOWN"
    assert row["ingestion_watermark_to_block"] is None


# Define test frontier reverifies catalog and does not cross quarantine as one focused
# operation with an explicit boundary.
def test_frontier_reverifies_catalog_and_does_not_cross_quarantine(
    tmp_path: Path,
) -> None:
    # Execute the test frontier reverifies catalog and does not cross quarantine workflow
    # in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    ledger = SQLiteShardLedger(database, catalog)
    first = _record(catalog, ledger, repository, start=0, end=10, digit="1")
    # Assemble conflicting once so the test frontier reverifies catalog and does not cross
    # quarantine workflow shares one value.
    conflicting = _publish(
        repository,
        payload=b"nondeterministic output",
        build_key=first.build_key.hex,
    )

    # Acquire raises, build key collision error and pytest at an explicit test frontier
    # reverifies catalog and does not cross quarantine context boundary so cleanup remains
    # scoped.
    with pytest.raises(BuildKeyCollisionError):
        catalog.index_committed(conflicting)

    frontier = ledger.contiguous_frontier(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        # Pass capability schema version explicitly so contiguous_frontier receives a
        # reviewable source and v1 input in test frontier reverifies catalog and does not
        # cross quarantine.
        capability_schema_version="v1",
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        coverage_from_block_ordinal=0,
    )
    # Verify frontier.frontier_block_ordinal == 0 before this scenario is accepted.
    assert frontier.frontier_block_ordinal == 0


def test_same_revision_preserves_distinct_verified_physical_builds(tmp_path: Path) -> None:
    """A logical source revision may be repacked by more than one writer bundle."""

    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    ledger = SQLiteShardLedger(database, catalog)
    first = _record(catalog, ledger, repository, start=0, end=10, digit="1")
    replacement = _publish(repository, payload=b"replacement", build_key="2" * 64)
    catalog.index_committed(replacement)
    replacement_revision = CommittedShardRevision(
        artifact=replacement,
        boundary=_boundary(0, 10, revision_digit="1"),
    )

    ledger.record_revision(replacement_revision)
    ledger.record_revision(replacement_revision)

    revisions = ledger.committed_revisions(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        capability_schema_version="v1",
        block_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            0,
            10,
        ),
    )
    assert {item.artifact.artifact_id for item in revisions} == {
        first.artifact_id,
        replacement.artifact_id,
    }
    assert {item.artifact.build_key for item in revisions} == {
        first.build_key,
        replacement.build_key,
    }
    assert all(item.boundary.query_fingerprints == (ContentDigest("1" * 64),) for item in revisions)

    frontier = ledger.contiguous_frontier(
        source_id=SourceId("source"),
        capability_id=CapabilityId("swaps.v1"),
        capability_schema_version="v1",
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        coverage_from_block_ordinal=0,
    )
    assert frontier.frontier_block_ordinal == 10

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        assert connection.execute("SELECT COUNT(*) FROM shard_ledger").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM shard_query_fingerprints").fetchone()[0] == 2
        )
    finally:
        connection.close()


def test_same_revision_rejects_conflicting_logical_boundary(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    ledger = SQLiteShardLedger(database, catalog)
    _record(catalog, ledger, repository, start=0, end=10, digit="1")
    replacement = _publish(repository, payload=b"replacement", build_key="2" * 64)
    catalog.index_committed(replacement)
    conflicting_boundary = replace(
        _boundary(0, 10, revision_digit="1"),
        chain_finality=ChainFinality.FINALIZED,
    )

    with pytest.raises(ShardLedgerConflictError, match="logical shard revision"):
        ledger.record_revision(CommittedShardRevision(replacement, conflicting_boundary))

    fingerprint_variant = _publish(
        repository,
        payload=b"different-query-provenance",
        build_key="3" * 64,
    )
    catalog.index_committed(fingerprint_variant)
    conflicting_fingerprints = replace(
        _boundary(0, 10, revision_digit="1"),
        query_fingerprints=(ContentDigest("f" * 64),),
    )
    with pytest.raises(ShardLedgerConflictError, match="logical shard revision"):
        ledger.record_revision(
            CommittedShardRevision(fingerprint_variant, conflicting_fingerprints)
        )

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        assert connection.execute("SELECT COUNT(*) FROM shard_ledger").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM shard_query_fingerprints").fetchone()[0] == 1
        )
    finally:
        connection.close()


def test_concurrent_record_of_same_revision_is_idempotent(tmp_path: Path) -> None:
    # Execute the test concurrent record of same revision is idempotent workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    database = tmp_path / "catalog.sqlite"
    catalog = SQLiteArtifactCatalog(database, repository)
    artifact = _publish(repository, payload=b"revision", build_key="1" * 64)
    catalog.index_committed(artifact)
    # Assemble revision once so the test concurrent record of same revision is idempotent
    # workflow shares one value.
    revision = CommittedShardRevision(
        artifact=artifact,
        boundary=_boundary(0, 10, revision_digit="1"),
    )

    def record(_: int) -> None:
        # Invoke record_revision for revision as a visible record step.
        SQLiteShardLedger(database, catalog).record_revision(revision)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(record, (1, 2)))

    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Assemble count once so the test concurrent record of same revision is idempotent
        # workflow shares one value.
        count = connection.execute("SELECT COUNT(*) FROM shard_ledger").fetchone()
    finally:
        connection.close()
    assert count is not None
    assert int(count[0]) == 1
