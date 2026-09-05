# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import (
    DataRootLayout,
    # Include unsafe data root identifier error so the localfs dependency remains
    # explicit.
    UnsafeDataRootIdentifierError,
)
from backtest.domain.identifiers import (
    ArtifactId,
    AttemptId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ExecutionAttemptId,
    Identifier,
    LogicalContentHash,
    LogicalRunId,
    # Include source id so the identifiers dependency remains explicit.
    SourceId,
)
from backtest.domain.time import SlotRange


def test_layout_builds_normative_local_paths(tmp_path: Path) -> None:
    # Execute the test layout builds normative local paths workflow in explicit,
    # reviewable steps.
    root = tmp_path / "var"
    layout = DataRootLayout(root)
    digest = "a" * 64
    distribution = "b" * 64

    assert layout.catalog_database == root / "catalog" / "catalog.sqlite"
    # Verify the publication lock, layout and lock relationship before this scenario is
    # accepted.
    assert layout.publication_lock == root / "locks" / "publication.lock"
    assert layout.run_lock(ExecutionAttemptId(distribution)) == (
        root / "locks" / f"run-{distribution}.lock"
    )
    assert layout.staging_attempt(AttemptId("attempt-1")) == (root / "staging" / "attempt-1")
    # Verify the job receipt, json and layout relationship before this scenario is
    # accepted.
    assert layout.job_receipt(AttemptId("attempt-1")) == (root / "job_receipts" / "attempt-1.json")
    assert layout.raw_shard(
        SourceId("indexer"),
        CapabilityId("swaps.v1"),
        SlotRange(5, 12),
        # Complete raw_shard only after its indexer and v1 inputs are visible in test layout
        # builds normative local paths.
    ) == root / "cache" / "raw" / "indexer" / "swaps.v1" / (
        "00000000000000000005-00000000000000000012"
    )
    assert (
        layout.canonical_distribution(LogicalContentHash(digest), ArtifactId(distribution))
        # Keep the root expectation tied to canonical distribution, distribution and
        # layout in this scenario.
        == root / "canonical" / digest / distribution
    )
    assert (
        layout.run_attempt(LogicalRunId(digest), ExecutionAttemptId(distribution))
        == root / "runs" / digest / distribution
        # Verify the run attempt, distribution and layout relationship before this scenario is
        # accepted.
    )


@pytest.mark.parametrize(
    "unsafe",
    ["../escape", "/absolute", "a/b", "a\\b", ".", "..", "я" * 121],
)
# Define test layout rejects identifiers that are not single segments as one focused
# operation with an explicit boundary.
def test_layout_rejects_identifiers_that_are_not_single_segments(
    tmp_path: Path,
    unsafe: str,
) -> None:
    # Execute the test layout rejects identifiers that are not single segments workflow in
    # explicit, reviewable steps.
    layout = DataRootLayout(tmp_path / "var")

    with pytest.raises(UnsafeDataRootIdentifierError):
        layout.pin(Identifier(unsafe))


def test_ensure_foundation_creates_only_stable_directories(tmp_path: Path) -> None:
    # Execute the test ensure foundation creates only stable directories workflow in
    # explicit, reviewable steps.
    layout = DataRootLayout(tmp_path / "var")

    layout.ensure_foundation()

    assert layout.catalog_directory.is_dir()
    assert layout.job_receipts_directory.is_dir()
    assert layout.raw_cache_directory.is_dir()
    # Verify the is dir, delivery schedules directory and layout relationship before this
    # scenario is accepted.
    assert layout.delivery_schedules_directory.is_dir()
    assert layout.trash_directory.is_dir()
    assert not layout.catalog_database.exists()
