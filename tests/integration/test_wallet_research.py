"""Independent expected counts, immutable publication and adversarial research bounds."""

from dataclasses import replace
from pathlib import Path

import pytest

# Exercise the real repository and DuckDB recipe through application-owned contracts.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.columnar.numpy.compiler import (
    LocalNumpyReplayPackCompiler,
    ReplayPackCompileError,
)

# The unchanged replay compiler is the authority that rejects observational artifact kinds.
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.adapters.research.store import LocalResearchStore
from backtest.application.research import ResearchError, ResearchTable, WalletAnalysisSpec
from backtest.domain.identifiers import RuntimeLockId, SnapshotId

# Expected values come from a small source fixture with independently known roles and counts.
from tests.support.research import DIGEST, dataset, key, observations


def test_activity_pairs_and_evidence_keep_roles_multiplicity_and_exact_amounts(
    tmp_path: Path,
) -> None:
    """One mint votes once for a pair, while every observed source row counts in activity."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST)
    result = store.analyze(spec)
    # Two mints qualify at the inclusive 60-second boundary; the rebuy adds no evidence.
    summary = store.summary(result.artifact_id)
    assert summary["counts"] == {
        "source_rows": 7,
        "selected_rows": 7,
        "wallets": 3,
        # Pair and evidence totals count pair relationships, not global unique mints.
        "pairs": 1,
        "evidence": 2,
    }
    pairs = store.page(result.artifact_id, ResearchTable.PAIRS, after=-1, limit=20)
    assert len(pairs) == 1
    # One mint is ordered by transaction position; the second is a same-transaction tie.
    assert (pairs[0]["shared_mints"], pairs[0]["a_first"], pairs[0]["same_transaction"]) == (
        "2",
        "1",
        "1",
    )
    # The shared payer must not replace either signing wallet in the graph.
    assert (pairs[0]["signer_a"], pairs[0]["signer_b"]) == (key(1), key(2))
    activity = store.page(result.artifact_id, ResearchTable.ACTIVITY, after=-1, limit=20)
    assert activity[0]["buy_rows"] == "4"
    assert activity[0]["source_quote_buy_atomic"] == str(4 * (10**18 + 1))
    # Evidence pages dereference both verified observation rows and preserve source roles.
    evidence = store.page(result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=1, pair=0)
    assert evidence[0]["left_fee_payer"] == key(9)
    assert evidence[0]["left_signing_wallet"] == key(1)
    assert evidence[0]["right_signing_wallet"] == key(2)
    assert evidence[0]["delta_seconds"] == "60"
    # A scoped continuation reaches the other mint without repeating the first evidence.
    tail = store.page(result.artifact_id, ResearchTable.EVIDENCE, after=0, limit=20, pair=0)
    assert len(tail) == 1 and tail[0]["mint"] == key(6)


def test_input_order_batches_threads_and_selection_have_explicit_identity(tmp_path: Path) -> None:
    """Physical source arrival and execution settings cannot change successful bytes."""

    repository = LocalArtifactRepository(tmp_path)
    store = LocalResearchStore(repository)
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    reordered = tuple(reversed(observations()))
    # A fresh acquisition with the same observations must reproduce the same content ID.
    second = store.publish_snapshot(dataset(), DIGEST, iter((reordered[:2], reordered[2:])))
    assert snapshot.artifact_id == second.artifact_id
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST)
    result = store.analyze(spec)
    assert LocalResearchStore(repository, threads=2).analyze(spec).artifact_id == result.artifact_id
    # Wallet selection and window changes are semantic, and never use a sampled fallback.
    selected = store.analyze(replace(spec, wallets=(key(1),)))
    assert store.summary(selected.artifact_id)["counts"] == {
        "source_rows": 7,
        "selected_rows": 4,
        "wallets": 1,
        # A single selected signer cannot form any pair, even after repeated buys.
        "pairs": 0,
        "evidence": 0,
    }
    shorter = store.analyze(replace(spec, window_seconds=59))
    # Removing the inclusive-boundary mint makes the minimum-two-mints threshold fail.
    assert store.summary(shorter.artifact_id)["counts"]["pairs"] == 0


def test_limits_abort_without_publishing_partial_results(tmp_path: Path) -> None:
    """Check candidate fanout before joining and local row limits before snapshot commit."""

    repository = LocalArtifactRepository(tmp_path)
    store = LocalResearchStore(repository)
    with pytest.raises(ResearchError, match="SOURCE_ROW_LIMIT"):
        LocalResearchStore(repository, maximum_source_rows=2).publish_snapshot(
            # A complete seven-row batch is rejected, never cut down to the two-row budget.
            dataset(),
            DIGEST,
            iter((observations(),)),
        )
    # A failed source scan leaves no committed snapshot or retained root.
    assert not tuple((tmp_path / "research-snapshots").glob("**/COMMITTED"))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    # Prejoin fanout rejection leaves the already committed input intact.
    with pytest.raises(ResearchError, match="PAIR_CANDIDATE_LIMIT"):
        LocalResearchStore(repository, maximum_pair_candidates=1).analyze(
            WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST),
        )
    # A rejected candidate budget must not produce even a partial committed result.
    assert not tuple((tmp_path / "research-results").glob("**/COMMITTED"))


def test_source_failure_and_disk_budget_do_not_publish_partial_snapshot(tmp_path: Path) -> None:
    """A partially yielded source stream and exhausted output quota both fail atomically."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))

    def failing_source():
        """Simulate a source connection failing after it already yielded useful rows."""
        yield observations()
        raise OSError("synthetic read failure")

    with pytest.raises(OSError, match="synthetic read failure"):
        store.publish_snapshot(dataset(), DIGEST, failing_source())
    # A complete input still cannot publish when its authoritative output exceeds quota.
    with pytest.raises(ResearchError, match="BYTE_LIMIT"):
        LocalResearchStore(store.artifacts, output_bytes=1024).publish_snapshot(
            dataset(),
            # The tiny disk budget is deliberately below a complete Parquet artifact.
            DIGEST,
            iter((observations(),)),
        )
    # Neither publication nor staging may retain a partial output after quota rejection.
    assert not tuple((tmp_path / "research-snapshots").glob("**/COMMITTED"))
    assert not tuple((tmp_path / "staging").iterdir())


def test_empty_completed_scan_is_distinct_from_source_failure(tmp_path: Path) -> None:
    """A genuinely empty bounded scan yields verified empty activity, never invented rows."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter(()))
    result = store.analyze(WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST))
    assert set(store.summary(result.artifact_id)["counts"].values()) == {0}
    assert store.page(result.artifact_id, ResearchTable.PAIRS, after=-1, limit=25) == ()
    # Missing pair identity is an error even when no evidence rows exist.
    with pytest.raises(ResearchError, match="PAIR_REQUIRED"):
        store.page(result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=25)


def test_corrupt_input_is_rejected_before_analysis_publication(tmp_path: Path) -> None:
    """A cached prior read cannot authenticate changed bytes under an immutable ID."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    store.summary(snapshot.artifact_id)
    path = tmp_path / "research-snapshots" / snapshot.artifact_id.hex / "observations.parquet"
    original = path.read_bytes()
    # Deliberately damage this isolated test artifact, preserving its old manifest and ID.
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(RuntimeError):
        store.analyze(WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST))
    assert not tuple((tmp_path / "research-results").glob("**/COMMITTED"))


def test_page_scope_rejects_pair_leakage_and_other_artifact_kind(tmp_path: Path) -> None:
    """View roles and pair scope remain binding even when IDs are valid artifacts."""
    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    result = store.analyze(WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST))
    with pytest.raises(ResearchError, match="TABLE_UNAVAILABLE"):
        store.page(snapshot.artifact_id, ResearchTable.PAIRS, after=-1, limit=25)
    # Pair ordinals cannot silently select an unrelated table or empty nonexistent pair.
    with pytest.raises(ResearchError, match="INVALID_PAIR_SCOPE"):
        store.page(result.artifact_id, ResearchTable.ACTIVITY, after=-1, limit=25, pair=0)
    with pytest.raises(ResearchError, match="PAIR_UNAVAILABLE"):
        store.page(result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=25, pair=1)
    # A cursor outside the selected evidence range cannot skip into another pair.
    with pytest.raises(ResearchError, match="INVALID_PAIR_SCOPE"):
        store.page(result.artifact_id, ResearchTable.EVIDENCE, after=50, limit=25, pair=0)


def test_research_artifacts_cannot_enter_replay_compilation(tmp_path: Path) -> None:
    """Neither research kind can impersonate a canonical execution snapshot."""

    repository = LocalArtifactRepository(tmp_path)
    store = LocalResearchStore(repository)
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    result = store.analyze(WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST))

    def no_source(snapshot_id: SnapshotId):
        """Artifact-kind rejection must happen before historical state is even opened."""
        pytest.fail("research artifact reached the historical source factory")

    compiler = LocalNumpyReplayPackCompiler(
        repository, no_source, runtime_lock_id=RuntimeLockId(DIGEST.hex)
    )
    # Valid committed bytes alone cannot grant a different artifact's execution semantics.
    for artifact in (snapshot, result):
        with pytest.raises(ReplayPackCompileError, match="committed snapshot"):
            compiler.compile(SnapshotId(artifact.artifact_id.hex), COMPILER_VERSION)
