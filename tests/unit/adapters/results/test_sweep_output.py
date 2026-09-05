# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.results.sweep import LocalSweepOutputStore
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.run_results import (
    # Include max run warning length so the run results dependency remains explicit.
    MAX_RUN_WARNING_LENGTH,
    MAX_RUN_WARNINGS,
    RunBackend,
    RunComparisonMetric,
    RunComparisonProjection,
    # Include run physical settings so the run results dependency remains explicit.
    RunPhysicalSettings,
)
from backtest.application.run_specs import ReplayContract
from backtest.application.sweeps import (
    MAX_SWEEP_RESULT_MANIFEST_BYTES,
    # Include resolved sweep spec so the sweeps dependency remains explicit.
    ResolvedSweepSpec,
    SweepEntryResult,
    sweep_result_digest,
)
from backtest.application.use_cases.query_artifacts import MAX_ARTIFACT_MANIFEST_BYTES

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    ContentDigest,
    ExecutionAttemptId,
    # Include logical run id so the identifiers dependency remains explicit.
    LogicalRunId,
)


# Keep the sweep identity contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _SweepIdentity:
    sweep_spec_id: ContentDigest
    comparison_metrics: tuple[RunComparisonMetric, ...]


def _publish_run(repository: LocalArtifactRepository, label: str) -> CommittedArtifact:
    # Execute the publish run workflow in explicit, reviewable steps.
    build_key = domain_digest("test.sweep-output.run-build", {"label": label})
    payload = canonical_json_bytes(
        {
            "execution_attempt_id": domain_digest(
                "test.sweep-output.execution-attempt",
                {"label": label},
            ).hex,
            "label": label,
            "logical_run_id": domain_digest(
                "test.sweep-output.logical-run",
                {"label": label},
            ).hex,
            "schema": "test.run/v1",
        }
    )
    writer = repository.stage(ArtifactDraft(ArtifactKind.RUN, build_key))
    return writer.commit(payload, identity_manifest_bytes=payload)


def _entry(character: str, run: CommittedArtifact) -> SweepEntryResult:
    # Execute the entry workflow in explicit, reviewable steps.
    result_hash = ContentDigest(chr(ord(character) + 6) * 64)
    return SweepEntryResult(
        entry_id=ContentDigest(character * 64),
        logical_run_id=LogicalRunId(chr(ord(character) + 2) * 64),
        execution_attempt_id=ExecutionAttemptId(chr(ord(character) + 4) * 64),
        # Pass canonical result hash explicitly so SweepEntryResult receives a reviewable
        # a and b input in entry.
        canonical_result_hash=result_hash,
        run_artifact=run,
        comparison=RunComparisonProjection(
            canonical_result_hash=result_hash,
            audit_hash=ContentDigest("a" * 64),
            # Include ledger hash in the completed entry result.
            ledger_hash=ContentDigest("b" * 64),
            fill_hash=ContentDigest("c" * 64),
            historical_group_count=2,
            historical_event_count=3,
            delivered_event_count=3,
            # Pass accepted order count explicitly so RunComparisonProjection receives a
            # reviewable a and b input in entry.
            accepted_order_count=1,
            rejected_order_count=0,
            filled_order_count=1,
            failed_order_count=0,
            ledger_transaction_count=1,
            # Pass fill count explicitly so RunComparisonProjection receives a reviewable
            # a and b input in entry.
            fill_count=1,
            final_balances_count=1,
            final_balances_digest=ContentDigest("d" * 64),
        ),
        physical_settings=RunPhysicalSettings(
            # Pass run backend explicitly so RunPhysicalSettings receives a reviewable
            # reference python and run backend input in entry.
            RunBackend.REFERENCE_PYTHON,
            65_536,
            1,
            8_192,
            1,
            # Complete RunPhysicalSettings only after its reference python and run backend
            # inputs are visible in entry.
        ),
        canonicality=ReplayContract.CANONICAL_EXACT,
        warnings=("fixture warning",),
    )


def test_sweep_output_publishes_canonical_comparison_and_retains_runs(
    # Keep the tmp path input explicit in the test sweep output publishes canonical
    # comparison and retains runs contract.
    tmp_path: Path,
) -> None:
    # Execute the test sweep output publishes canonical comparison and retains runs
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path)
    first_run = _publish_run(repository, "first")
    second_run = _publish_run(repository, "second")
    entries = (_entry("1", first_run), _entry("2", second_run))
    identity = _SweepIdentity(
        # Keep the spec domain_digest step visible while building identity.
        domain_digest("test.sweep-output.spec", {"version": 1}),
        (
            RunComparisonMetric.CANONICAL_RESULT_HASH,
            RunComparisonMetric.FILL_COUNT,
        ),
        # Complete _SweepIdentity only after its spec and version inputs are visible in test
        # sweep output publishes canonical comparison and retains runs.
    )
    spec = cast(ResolvedSweepSpec, identity)

    artifact = LocalSweepOutputStore(repository).publish(spec, entries)

    assert artifact.kind is ArtifactKind.SWEEP
    assert artifact.build_key == identity.sweep_spec_id
    # Verify the input artifact ids, artifact and sorted relationship before this scenario
    # is accepted.
    assert artifact.input_artifact_ids == tuple(
        sorted((first_run.artifact_id, second_run.artifact_id), key=lambda item: item.hex)
    )
    handle = repository.open_committed(artifact.artifact_id)
    try:
        # Perform the protected test sweep output publishes canonical comparison and
        # retains runs operation before explicit failure handling.
        with handle.open_binary("comparison.json") as stream:
            comparison = json.load(stream)
        with handle.open_binary("manifest.json") as stream:
            manifest = json.load(stream)
    finally:
        # Invoke close as a visible step within the test sweep output publishes canonical
        # comparison and retains runs workflow.
        handle.close()
    assert comparison == manifest
    assert (
        comparison["result_digest"]
        == sweep_result_digest(
            # Pass identity explicitly so sweep_result_digest receives a reviewable sweep
            # spec id and comparison metrics input in test sweep output publishes
            # canonical comparison and retains runs.
            identity.sweep_spec_id,
            identity.comparison_metrics,
            entries,
        ).hex
    )
    # Verify the comparison, comparison metrics and canonical result hash relationship
    # before this scenario is accepted.
    assert comparison["comparison_metrics"] == ["canonical_result_hash", "fill_count"]
    assert [item["entry_id"] for item in comparison["entries"]] == ["1" * 64, "2" * 64]
    assert comparison["entries"][0]["comparison"] == {
        "canonical_result_hash": entries[0].canonical_result_hash.hex,
        "fill_count": 1,
        # Verify the comparison, canonical result hash and fill count relationship before this
        # scenario is accepted.
    }
    assert comparison["entries"][0]["canonicality"] == "CANONICAL_EXACT"
    assert comparison["entries"][0]["warnings"] == ["fixture warning"]
    assert comparison["schema"] == "backtest.sweep-result/v2"


def test_sweep_output_rejects_invalid_entry_collections_before_publication(
    # Keep the tmp path input explicit in the test sweep output rejects invalid entry
    # collections before publication contract.
    tmp_path: Path,
) -> None:
    # Execute the test sweep output rejects invalid entry collections before publication
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path)
    store = LocalSweepOutputStore(repository)
    run = _publish_run(repository, "shared")
    first = _entry("1", run)
    second = _entry("2", run)
    # Assemble spec once so the test sweep output rejects invalid entry collections before
    # publication workflow shares one value.
    spec = cast(
        ResolvedSweepSpec,
        _SweepIdentity(domain_digest("test.sweep-output.spec", {"version": 1}), ()),
    )

    with pytest.raises(ValueError, match="at least one"):
        # Invoke publish for spec as a visible test sweep output rejects invalid entry
        # collections before publication step.
        store.publish(spec, ())
    with pytest.raises(ValueError, match="canonically ordered"):
        store.publish(spec, (second, first))
    with pytest.raises(ValueError, match="distinct run artifacts"):
        store.publish(spec, (first, second))


# Define test sweep output rejects an oversized bounded metadata document as one focused
# operation with an explicit boundary.
def test_sweep_output_rejects_an_oversized_bounded_metadata_document(
    tmp_path: Path,
) -> None:
    # Execute the test sweep output rejects an oversized bounded metadata document
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path)
    base = _entry("1", _publish_run(repository, "base"))
    warnings = tuple(
        f"warning-{index:02d}-" + "x" * (MAX_RUN_WARNING_LENGTH - 11)
        for index in range(MAX_RUN_WARNINGS)
        # Complete tuple only after its warning- and - inputs are visible in test sweep output
        # rejects an oversized bounded metadata document.
    )
    entries = tuple(
        sorted(
            (
                replace(
                    # Pass base explicitly so replace receives a reviewable entry and
                    # ordinal input in test sweep output rejects an oversized bounded
                    # metadata document.
                    base,
                    entry_id=domain_digest("test.sweep-output.entry", {"ordinal": ordinal}),
                    logical_run_id=LogicalRunId(
                        domain_digest(
                            "test.sweep-output.logical-run",
                            # Open the logical-run and ordinal payload explicitly for
                            # domain_digest within test sweep output rejects an oversized
                            # bounded metadata document.
                            {"ordinal": ordinal},
                        ).hex
                    ),
                    execution_attempt_id=ExecutionAttemptId(
                        domain_digest(
                            # Pass attempt explicitly so domain_digest receives a
                            # reviewable attempt and ordinal input in test sweep output
                            # rejects an oversized bounded metadata document.
                            "test.sweep-output.attempt",
                            {"ordinal": ordinal},
                        ).hex
                    ),
                    canonical_result_hash=(
                        # Keep the result domain_digest step visible while building
                        # entries.
                        result_hash := domain_digest(
                            "test.sweep-output.result",
                            {"ordinal": ordinal},
                        )
                    ),
                    # Keep the run artifact replace step visible while building entries.
                    run_artifact=replace(
                        base.run_artifact,
                        artifact_id=ArtifactId(
                            domain_digest(
                                "test.sweep-output.run",
                                # Open the run and ordinal payload explicitly for
                                # domain_digest within test sweep output rejects an
                                # oversized bounded metadata document.
                                {"ordinal": ordinal},
                            ).hex
                        ),
                    ),
                    comparison=replace(
                        # Pass base explicitly so replace receives a reviewable comparison
                        # and base input in test sweep output rejects an oversized bounded
                        # metadata document.
                        base.comparison,
                        canonical_result_hash=result_hash,
                    ),
                    warnings=warnings,
                )
                # Build each bounded entry from its ordinal before canonical sorting.
                for ordinal in range(600)
            ),
            key=lambda item: item.entry_id.hex,
        )
    )
    # Assemble spec once so the test sweep output rejects an oversized bounded metadata
    # document workflow shares one value.
    spec = cast(
        ResolvedSweepSpec,
        _SweepIdentity(domain_digest("test.sweep-output.spec", {"version": 2}), ()),
    )

    with pytest.raises(ValueError, match="bounded metadata limit"):
        # Invoke publish for spec and entries as a visible test sweep output rejects an
        # oversized bounded metadata document step.
        LocalSweepOutputStore(repository).publish(spec, entries)

    assert MAX_SWEEP_RESULT_MANIFEST_BYTES == MAX_ARTIFACT_MANIFEST_BYTES
