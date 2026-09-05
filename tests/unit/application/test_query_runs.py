# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

# Import pytest at the visible module dependency boundary.
import pytest

from backtest.application.catalog_models import RunIndexEntry
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.ports.catalog import RunListCursor
from backtest.application.run_results import (
    MAX_COMPARISON_FINAL_BALANCES,
    # Include max comparison label length so the run results dependency remains explicit.
    MAX_COMPARISON_LABEL_LENGTH,
    MAX_RUN_WARNING_LENGTH,
    MAX_RUN_WARNINGS,
    MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
    RunBackend,
    # Include run physical settings so the run results dependency remains explicit.
    RunPhysicalSettings,
    SuccessfulRunManifest,
)
from backtest.application.run_specs import (
    AssetBalance,
    # Include replay contract so the run specs dependency remains explicit.
    ReplayContract,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    # Close the run specs import after its required symbols are visible.
)
from backtest.application.use_cases.query_artifacts import (
    MAX_ARTIFACT_MANIFEST_BYTES,
    ArtifactDetails,
    ArtifactQueryError,
    # Include query artifacts so the query artifacts dependency remains explicit.
    QueryArtifacts,
)
from backtest.application.use_cases.query_runs import QueryRuns, RunIndexQueryError
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    # Include asset id so the identifiers dependency remains explicit.
    AssetId,
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    LogicalRunId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
)
from backtest.engine.reference import RunSummary


def _digest(character: str) -> ContentDigest:
    # Return the completed digest result without a hidden fallback.
    return ContentDigest(character * 64)


def _artifact(character: str, *, kind: ArtifactKind = ArtifactKind.RUN) -> CommittedArtifact:
    # Execute the artifact workflow in explicit, reviewable steps.
    return CommittedArtifact(
        artifact_id=ArtifactId(character * 64),
        kind=kind,
        manifest_digest=_digest("f"),
        build_key=_digest("e"),
        # Complete CommittedArtifact only after its f and e inputs are visible in artifact.
    )


def _spec(seed: int = 1) -> ResolvedRunSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    roles = (
        "clock",
        "engine",
        "execution",
        "inference",
        # Keep the latency component named inside the roles contract.
        "latency",
        "protocol:reference",
        "risk",
        "scheduler",
        "strategy",
        # Keep the universe component named inside the roles contract.
        "universe",
        "valuation:price_source",
    )
    components = tuple(
        ResolvedComponent.create(
            # Pass role explicitly so create receives a reviewable bundle and role input
            # in spec.
            role=role,
            bundle_id=BundleId(domain_digest("test.query-runs.bundle", {"role": role}).hex),
            config=(
                ExactInferencePolicy.disabled().document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
        )
        # Pass role explicitly so tuple receives a reviewable inference and bundle input
        # in spec.
        for role in roles
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include dataset revision id in the completed spec result.
        dataset_revision_id=DatasetRevisionId(f"{seed:x}" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=_digest("4"),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable x and 2 input in
        # spec.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=seed,
    )


# Define physical as one focused operation with an explicit boundary.
def _physical() -> RunPhysicalSettings:
    return RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 2, 8_192, 1)


def _run_manifest(
    spec: ResolvedRunSpec,
    *,
    # Keep the attempt character input explicit in the run manifest contract.
    attempt_character: str,
    result_character: str = "c",
    audit_character: str = "d",
    final_balances: tuple[tuple[str, str, str, int], ...] = (
        ("portfolio:available:SOL", "available", "SOL", 987),
        # Close the run manifest signature after its explicit inputs.
    ),
) -> SuccessfulRunManifest:
    # Execute the run manifest workflow in explicit, reviewable steps.
    components = {item.role: item for item in spec.components}
    nonce = _digest(attempt_character)
    physical = _physical()
    summary = RunSummary(
        dataset_logical_content_hash=spec.logical_content_hash,
        # Pass replay semantics id explicitly so RunSummary receives a reviewable engine
        # and latency input in run manifest.
        replay_semantics_id=spec.replay_semantics_id,
        engine_bundle_id=components["engine"].bundle_id,
        latency_bundle_id=components["latency"].bundle_id,
        historical_group_count=10,
        historical_event_count=12,
        # Pass delivered event count explicitly so RunSummary receives a reviewable engine
        # and latency input in run manifest.
        delivered_event_count=11,
        accepted_order_count=3,
        rejected_order_count=1,
        filled_order_count=2,
        failed_order_count=0,
        # Pass ledger transaction count explicitly so RunSummary receives a reviewable
        # engine and latency input in run manifest.
        ledger_transaction_count=2,
        fill_count=2,
        audit_hash=_digest(audit_character),
        ledger_hash=_digest("a"),
        fill_hash=_digest("b"),
        # Keep the result character _digest step visible while building summary.
        result_hash=_digest(result_character),
        final_balances=final_balances,
    )
    return SuccessfulRunManifest(
        resolved_spec=spec,
        # Bind the physical attempt to its exact nonce and settings.
        attempt_nonce=nonce,
        execution_attempt_id=spec.execution_attempt_id(nonce, physical.identity_digest),
        input_artifact_ids=(),
        summary=summary,
        physical_settings=physical,
        # Operational timestamps are excluded from semantic Run identity.
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        warnings=("fixture warning",),
    )


def _epoch_ns(value: datetime) -> int:
    """Mirror the exact integer epoch representation exposed by the index port."""

    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    whole_seconds = delta.days * 86_400 + delta.seconds
    return whole_seconds * 1_000_000_000 + delta.microseconds * 1_000


def _run_entry(
    artifact: CommittedArtifact,
    manifest: SuccessfulRunManifest,
) -> RunIndexEntry:
    """Build an index record tied to the exact descriptor and manifest fixture."""

    return RunIndexEntry(
        artifact_id=artifact.artifact_id,
        manifest_digest=artifact.manifest_digest,
        logical_run_id=manifest.logical_run_id,
        # The selected page must recheck physical attempt and both timestamps.
        execution_attempt_id=manifest.execution_attempt_id,
        started_at_ns=_epoch_ns(manifest.started_at),
        completed_at_ns=_epoch_ns(manifest.completed_at),
    )


# Keep the artifact queries contract and validation rules together.
@dataclass(slots=True)
class _ArtifactQueries:
    descriptors: tuple[CommittedArtifact, ...]
    manifests: dict[str, bytes]

    def list(
        # Keep the remaining list inputs visible at the artifact queries list boundary.
        self,
        *,
        kind: ArtifactKind | None = None,
        limit: int = 100,
        offset: int = 0,
        # Keep the tuple input explicit in the list contract.
    ) -> tuple[CommittedArtifact, ...]:
        # Execute the artifact queries list workflow in explicit, reviewable steps.
        selected = tuple(item for item in self.descriptors if kind is None or item.kind is kind)
        return selected[offset : offset + limit]

    def details(self, artifact_id: ArtifactId) -> ArtifactDetails:
        # Execute the artifact queries details workflow in explicit, reviewable steps.
        descriptor = next(item for item in self.descriptors if item.artifact_id == artifact_id)
        return ArtifactDetails(descriptor, self.manifests[artifact_id.hex])


@dataclass(slots=True)
class _RunIndex:
    """Small port double that records bounded global and logical page calls."""

    entries: tuple[RunIndexEntry, ...]
    calls: list[tuple[str, int, int]]

    def list_runs(
        self,
        *,
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]:
        self.calls.append(("all", limit, offset))
        entries = self.entries
        if after is not None:
            # The double reproduces the production mixed-direction keyset.
            entries = tuple(item for item in entries if _entry_is_after(item, after))
        return entries[offset : offset + limit]

    def list_logical_runs(
        self,
        logical_run_id: LogicalRunId,
        *,
        limit: int,
        offset: int,
        after: RunListCursor | None = None,
    ) -> tuple[RunIndexEntry, ...]:
        # Filtering precedes pagination, matching the real indexed SQL query.
        selected = tuple(item for item in self.entries if item.logical_run_id == logical_run_id)
        if after is not None:
            selected = tuple(item for item in selected if _entry_is_after(item, after))
        self.calls.append(("logical", limit, offset))
        return selected[offset : offset + limit]


def _entry_is_after(item: RunIndexEntry, cursor: RunListCursor) -> bool:
    """Return whether one entry follows the exclusive canonical cursor."""

    return item.completed_at_ns < cursor.completed_at_ns or (
        item.completed_at_ns == cursor.completed_at_ns
        and item.artifact_id.hex > cursor.artifact_id.hex
    )


def _empty_run_index() -> _RunIndex:
    """Provide an explicit index dependency for artifact-ID-only query tests."""

    return _RunIndex((), [])


def test_query_runs_projects_verified_manifest_fields() -> None:
    # Execute the test query runs projects verified manifest fields workflow in explicit,
    # reviewable steps.
    run = _artifact("a")
    manifest = _run_manifest(_spec(), attempt_character="2")
    run_index = _RunIndex((_run_entry(run, manifest),), [])
    queries = QueryRuns(
        cast(
            QueryArtifacts,
            # Keep the artifact queries and run _ArtifactQueries step visible while
            # building queries.
            _ArtifactQueries(
                (run,),
                {run.artifact_id.hex: manifest.manifest_bytes()},
            ),
        ),
        run_index,
        # Complete QueryRuns only after its hex and artifact id inputs are visible in test
        # query runs projects verified manifest fields.
    )

    assert queries.list(limit=10) == (queries.get(run.artifact_id),)
    view = queries.get(run.artifact_id)
    assert view.run_artifact_id == run.artifact_id
    assert view.logical_run_id == manifest.logical_run_id
    # Verify the execution attempt id, view and manifest relationship before this scenario
    # is accepted.
    assert view.execution_attempt_id == manifest.execution_attempt_id
    assert view.canonical_result_hash == _digest("c")
    assert view.audit_hash == _digest("d")
    assert view.comparison.ledger_hash == _digest("a")
    assert view.comparison.fill_count == 2
    # Verify the final balances count, comparison and view relationship before this
    # scenario is accepted.
    assert view.comparison.final_balances_count == 1
    assert view.comparison.final_balances_digest == domain_digest(
        "backtest.final-balances.v1",
        [["portfolio:available:SOL", "available", "SOL", 987]],
    )
    # Verify view.physical_settings == _physical() before this scenario is accepted.
    assert view.physical_settings == _physical()
    assert view.canonicality is ReplayContract.CANONICAL_EXACT
    assert view.started_at == manifest.started_at
    assert view.completed_at == manifest.completed_at
    assert view.warnings == ("fixture warning",)
    assert run_index.calls == [("all", 10, 0)]


def test_query_runs_orders_each_bounded_page_by_completion_time() -> None:
    older_artifact = _artifact("a")
    newer_artifact = _artifact("b")
    older = _run_manifest(_spec(), attempt_character="1")
    newer = replace(
        _run_manifest(_spec(), attempt_character="2"),
        started_at=datetime(2026, 1, 2, tzinfo=UTC),
        completed_at=datetime(2026, 1, 2, 0, 0, 1, tzinfo=UTC),
    )
    # The index, not an in-memory post-page sort, selects global order.
    run_index = _RunIndex(
        (_run_entry(newer_artifact, newer), _run_entry(older_artifact, older)),
        [],
    )
    queries = QueryRuns(
        cast(
            QueryArtifacts,
            _ArtifactQueries(
                (older_artifact, newer_artifact),
                {
                    older_artifact.artifact_id.hex: older.manifest_bytes(),
                    newer_artifact.artifact_id.hex: newer.manifest_bytes(),
                },
            ),
        ),
        run_index,
    )

    result = queries.list(limit=2)

    assert tuple(item.run_artifact_id for item in result) == (
        newer_artifact.artifact_id,
        older_artifact.artifact_id,
    )


def test_query_run_page_continuation_survives_newer_insert() -> None:
    """The application resumes from the last authenticated visible Run."""

    artifacts = tuple(_artifact(character) for character in ("a", "b", "c", "d"))
    base = _run_manifest(_spec(), attempt_character="1")
    manifests = tuple(
        replace(
            base,
            attempt_nonce=_digest(character),
            execution_attempt_id=base.resolved_spec.execution_attempt_id(
                _digest(character),
                base.physical_settings.identity_digest,
            ),
            started_at=datetime(2026, 1, day, tzinfo=UTC),
            completed_at=datetime(2026, 1, day, 0, 0, 1, tzinfo=UTC),
        )
        for character, day in zip(("2", "3", "4", "5"), (1, 2, 3, 4), strict=True)
    )
    entries = tuple(
        _run_entry(item, manifest) for item, manifest in zip(artifacts, manifests, strict=True)
    )
    # Start without the newest future insert, preserving canonical descending order.
    run_index = _RunIndex((entries[2], entries[1], entries[0]), [])
    queries = QueryRuns(
        cast(
            QueryArtifacts,
            _ArtifactQueries(
                artifacts,
                {
                    item.artifact_id.hex: manifest.manifest_bytes()
                    for item, manifest in zip(artifacts, manifests, strict=True)
                },
            ),
        ),
        run_index,
    )

    first = queries.page(limit=2)
    assert tuple(item.run_artifact_id for item in first.items) == (
        artifacts[2].artifact_id,
        artifacts[1].artifact_id,
    )
    assert first.next_cursor == RunListCursor(
        entries[1].completed_at_ns,
        artifacts[1].artifact_id,
    )

    # A new completion belongs ahead of page one, not inside the continuation window.
    run_index.entries = (entries[3], entries[2], entries[1], entries[0])
    second = queries.page(limit=2, after=first.next_cursor)

    assert tuple(item.run_artifact_id for item in second.items) == (artifacts[0].artifact_id,)
    assert second.next_cursor is None


def test_query_runs_rejects_stale_selected_page_metadata() -> None:
    """A SQLite timestamp cannot override the exact verified manifest timestamp."""

    run = _artifact("a")
    manifest = _run_manifest(_spec(), attempt_character="2")
    stale = replace(
        _run_entry(run, manifest),
        completed_at_ns=_epoch_ns(manifest.completed_at) + 1_000,
    )
    queries = QueryRuns(
        cast(
            QueryArtifacts,
            _ArtifactQueries((run,), {run.artifact_id.hex: manifest.manifest_bytes()}),
        ),
        _RunIndex((stale,), []),
    )

    with pytest.raises(RunIndexQueryError):
        queries.list(limit=1, offset=0)


def test_query_logical_uses_index_filter_before_bounded_pagination() -> None:
    # Execute the test query logical pages and sorts attempts workflow in explicit,
    # reviewable steps.
    matching = tuple(_artifact(f"{index:x}") for index in range(1, 10))
    other = _artifact("a")
    descriptors = (*matching, other)
    matching_spec = _spec()
    manifest_models = {
        item.artifact_id.hex: _run_manifest(
            matching_spec,
            attempt_character=f"{10 - index:x}",
        )
        for index, item in enumerate(matching, start=1)
    }
    manifest_models[other.artifact_id.hex] = _run_manifest(_spec(2), attempt_character="f")
    manifests = {key: value.manifest_bytes() for key, value in manifest_models.items()}
    # All fixtures share completion time, so artifact ID is the deterministic tie-breaker.
    entries = tuple(_run_entry(item, manifest_models[item.artifact_id.hex]) for item in descriptors)
    run_index = _RunIndex(entries, [])
    queries = QueryRuns(
        cast(QueryArtifacts, _ArtifactQueries(descriptors, manifests)),
        run_index,
    )

    # Assemble result once so the test query logical pages and sorts attempts workflow
    # shares one value.
    result = queries.get_logical(matching_spec.logical_run_id, limit=4, offset=2)

    assert tuple(item.run_artifact_id for item in result) == tuple(
        item.artifact_id for item in matching[2:6]
    )
    assert run_index.calls == [("logical", 4, 2)]


# Define test query logical reads the next page after an exactly full page as one focused
# operation with an explicit boundary.
def test_query_logical_does_not_scan_unrelated_artifact_pages() -> None:
    """One logical page maps to one indexed call and one bounded verification set."""

    run = _artifact("a")
    manifest = _run_manifest(_spec(), attempt_character="c")
    artifacts = _ArtifactQueries(
        (run,),
        {run.artifact_id.hex: manifest.manifest_bytes()},
    )
    run_index = _RunIndex((_run_entry(run, manifest),), [])
    queries = QueryRuns(cast(QueryArtifacts, artifacts), run_index)

    result = queries.get_logical(manifest.logical_run_id, limit=1, offset=0)

    assert tuple(item.run_artifact_id for item in result) == (run.artifact_id,)
    assert run_index.calls == [("logical", 1, 0)]


@pytest.mark.parametrize(
    "manifest",
    (
        b"not-json",
        # Define test query runs rejects malformed manifest as one focused operation with
        # an explicit boundary.
        canonical_json_bytes({"logical_run_id": "a" * 64}),
        canonical_json_bytes(
            {
                "execution_attempt_id": "b" * 64,
                "logical_run_id": "a" * 64,
                # Keep summary named so the execution attempt id and logical run id
                # payload passed to canonical_json_bytes remains self-describing within
                # test query runs rejects malformed manifest.
                "summary": [],
            }
        ),
        canonical_json_bytes(
            {
                # Keep execution attempt id named so the execution attempt id and logical
                # run id payload passed to canonical_json_bytes remains self-describing
                # within test query runs rejects malformed manifest.
                "execution_attempt_id": "not-a-digest",
                "logical_run_id": "a" * 64,
                "summary": {"audit_hash": "c" * 64, "result_hash": "d" * 64},
            }
        ),
        # Complete parametrize only after its manifest and logical run id inputs are visible
        # in test query runs rejects malformed manifest.
    ),
)
def test_query_runs_rejects_malformed_manifest(manifest: bytes) -> None:
    # Execute the test query runs rejects malformed manifest workflow in explicit,
    # reviewable steps.
    run = _artifact("a")
    queries = QueryRuns(
        cast(QueryArtifacts, _ArtifactQueries((run,), {run.artifact_id.hex: manifest})),
        _empty_run_index(),
    )

    with pytest.raises(ArtifactQueryError, match="RUN_MANIFEST_INVALID"):
        # Invoke get for artifact id and run as a visible test query runs rejects
        # malformed manifest step.
        queries.get(run.artifact_id)


def test_query_runs_rejects_tampered_summary_and_descriptor_closure() -> None:
    # Execute the test query runs rejects tampered summary and descriptor closure workflow
    # in explicit, reviewable steps.
    manifest = _run_manifest(_spec(), attempt_character="c")
    document = json.loads(manifest.manifest_bytes())
    document["summary"]["fill_count"] = -1
    run = _artifact("a")
    malformed = QueryRuns(
        # Keep the query artifacts cast step visible while building malformed.
        cast(
            QueryArtifacts,
            _ArtifactQueries((run,), {run.artifact_id.hex: canonical_json_bytes(document)}),
        ),
        _empty_run_index(),
    )
    # Acquire raises, artifact query error and pytest at an explicit test query runs
    # rejects tampered summary and descriptor closure context boundary so cleanup remains
    # scoped.
    with pytest.raises(ArtifactQueryError, match="RUN_MANIFEST_INVALID"):
        malformed.get(run.artifact_id)

    substituted_descriptor = replace(run, input_artifact_ids=(ArtifactId("b" * 64),))
    substituted = QueryRuns(
        cast(
            # Pass query artifacts explicitly so cast receives a reviewable hex and
            # artifact id input in test query runs rejects tampered summary and descriptor
            # closure.
            QueryArtifacts,
            _ArtifactQueries(
                (substituted_descriptor,),
                {substituted_descriptor.artifact_id.hex: manifest.manifest_bytes()},
            ),
            # Complete cast only after its hex and artifact id inputs are visible in test
            # query runs rejects tampered summary and descriptor closure.
        ),
        _empty_run_index(),
    )
    with pytest.raises(ArtifactQueryError, match="RUN_MANIFEST_INVALID"):
        substituted.get(substituted_descriptor.artifact_id)


def test_run_manifest_externalizes_large_balances_and_bounds_metadata() -> None:
    # Execute the test run manifest externalizes large balances and bounds metadata
    # workflow in explicit, reviewable steps.
    balances = tuple(
        (f"account:{index:05d}", "available", "SOL", index)
        for index in range(MAX_COMPARISON_FINAL_BALANCES + 1)
    )
    manifest = _run_manifest(
        # Keep the spec _spec step visible while building manifest.
        _spec(),
        attempt_character="c",
        final_balances=balances,
    )

    assert manifest.comparison.final_balances_count == 16_385
    # Verify the max successful run manifest bytes, manifest bytes and manifest
    # relationship before this scenario is accepted.
    assert len(manifest.manifest_bytes()) < MAX_SUCCESSFUL_RUN_MANIFEST_BYTES


def test_run_comparison_labels_and_warnings_are_explicitly_bounded() -> None:
    # Execute the test run comparison labels and warnings are explicitly bounded workflow
    # in explicit, reviewable steps.
    manifest = _run_manifest(_spec(), attempt_character="c")
    with pytest.raises(ValueError, match="balance account is invalid"):
        # Keep raises, value error and pytest active only for the bounded test run
        # comparison labels and warnings are explicitly bounded operation.
        _run_manifest(
            _spec(),
            attempt_character="c",
            final_balances=(("x" * (MAX_COMPARISON_LABEL_LENGTH + 1), "a", "SOL", 1),),
        )
    # Acquire raises, value error and pytest at an explicit test run comparison labels and
    # warnings are explicitly bounded context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="bounded count"):
        # Keep raises, value error and pytest active only for the bounded test run
        # comparison labels and warnings are explicitly bounded operation.
        replace(
            manifest,
            warnings=tuple(f"warning-{index:03d}" for index in range(MAX_RUN_WARNINGS + 1)),
        )
    with pytest.raises(ValueError, match="printable"):
        # Invoke replace for x and manifest as a visible test run comparison labels and
        # warnings are explicitly bounded step.
        replace(manifest, warnings=("x" * (MAX_RUN_WARNING_LENGTH + 1),))


def test_successful_run_manifest_limit_matches_the_metadata_query_limit() -> None:
    assert MAX_SUCCESSFUL_RUN_MANIFEST_BYTES == MAX_ARTIFACT_MANIFEST_BYTES


def test_query_runs_rejects_non_run_descriptor() -> None:
    # Execute the test query runs rejects non run descriptor workflow in explicit,
    # reviewable steps.
    artifact = _artifact("a", kind=ArtifactKind.SNAPSHOT)
    queries = QueryRuns(
        cast(
            QueryArtifacts,
            _ArtifactQueries(
                # Open the c and hex payload explicitly for _ArtifactQueries within test
                # query runs rejects non run descriptor.
                (artifact,),
                {
                    artifact.artifact_id.hex: _run_manifest(
                        _spec(), attempt_character="c"
                    ).manifest_bytes()
                    # Close the c and hex payload only after all test query runs rejects non
                    # run descriptor fields are present.
                },
            ),
        ),
        _empty_run_index(),
    )

    with pytest.raises(ArtifactQueryError, match="ARTIFACT_IS_NOT_A_RUN"):
        # Invoke get for artifact id and artifact as a visible test query runs rejects non
        # run descriptor step.
        queries.get(artifact.artifact_id)
