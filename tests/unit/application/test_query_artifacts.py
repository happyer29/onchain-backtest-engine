# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from typing import Any, cast

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.use_cases.query_artifacts import (
    MAX_ARTIFACT_MANIFEST_BYTES,
    ArtifactDetails,
    ArtifactQueryError,
    # Include query artifacts so the query artifacts dependency remains explicit.
    QueryArtifacts,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ArtifactId, ContentDigest


def _publish(
    # Keep the repository input explicit in the publish contract.
    repository: LocalArtifactRepository,
    *,
    label: str,
    kind: ArtifactKind,
    inputs: tuple[ArtifactId, ...] = (),
    # Keep the committed artifact input explicit in the publish contract.
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind,
            domain_digest("test.query-artifact.build", {"label": label}),
            inputs,
            # Complete ArtifactDraft only after its build and label inputs are visible in
            # publish.
        )
    )
    document: dict[str, object] = {"artifact_schema": f"test-{label}/v1"}
    if kind is ArtifactKind.RUN:
        document.update(
            {
                "execution_attempt_id": domain_digest(
                    "test.query-artifact-attempt", {"label": label}
                ).hex,
                "logical_run_id": domain_digest(
                    "test.query-artifact-logical-run", {"label": label}
                ).hex,
            }
        )
    manifest = canonical_json_bytes(document)
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def test_catalog_page_and_transitive_lineage_reverify_filesystem(tmp_path: object) -> None:
    # Execute the test catalog page and transitive lineage reverify filesystem workflow in
    # explicit, reviewable steps.
    from pathlib import Path

    root = Path(str(tmp_path))
    repository = LocalArtifactRepository(root)
    catalog = SQLiteArtifactCatalog(root / "catalog" / "catalog.sqlite", repository)
    source = _publish(repository, label="source", kind=ArtifactKind.SOURCE_INSPECTION)
    # Assemble snapshot once so the test catalog page and transitive lineage reverify
    # filesystem workflow shares one value.
    snapshot = _publish(
        repository,
        label="snapshot",
        kind=ArtifactKind.SNAPSHOT,
        inputs=(source.artifact_id,),
        # Complete _publish only after its snapshot and artifact id inputs are visible in test
        # catalog page and transitive lineage reverify filesystem.
    )
    run = _publish(
        repository,
        label="run",
        kind=ArtifactKind.RUN,
        # Pass inputs explicitly so _publish receives a reviewable run and artifact id
        # input in test catalog page and transitive lineage reverify filesystem.
        inputs=(snapshot.artifact_id,),
    )
    for artifact in (source, snapshot, run):
        catalog.index_committed(artifact)

    queries = QueryArtifacts(catalog, repository)
    # Verify the list, run and queries relationship before this scenario is accepted.
    assert queries.list(kind=ArtifactKind.RUN) == (run,)
    assert queries.details(run.artifact_id).descriptor == run
    lineage = queries.lineage(run.artifact_id)
    assert {item.artifact_id for item in lineage.artifacts} == {
        source.artifact_id,
        # Keep the snapshot expectation tied to artifact id, item and artifacts in this
        # scenario.
        snapshot.artifact_id,
        run.artifact_id,
    }
    assert len(lineage.edges) == 2


def test_queries_fail_closed_for_unknown_or_unindexed_artifact(tmp_path: object) -> None:
    # Execute the test queries fail closed for unknown or unindexed artifact workflow in
    # explicit, reviewable steps.
    from pathlib import Path

    root = Path(str(tmp_path))
    repository = LocalArtifactRepository(root)
    catalog = SQLiteArtifactCatalog(root / "catalog" / "catalog.sqlite", repository)
    orphan = _publish(repository, label="orphan", kind=ArtifactKind.RUN)
    # Assemble queries once so the test queries fail closed for unknown or unindexed
    # artifact workflow shares one value.
    queries = QueryArtifacts(catalog, repository)

    with pytest.raises(ArtifactQueryError, match="NOT_FOUND"):
        queries.details(orphan.artifact_id)
    assert catalog.list_committed(kind=None, limit=10, offset=0) == ()


def test_catalog_page_rejects_unbounded_parameters(tmp_path: object) -> None:
    # Execute the test catalog page rejects unbounded parameters workflow in explicit,
    # reviewable steps.
    from pathlib import Path

    root = Path(str(tmp_path))
    repository = LocalArtifactRepository(root)
    catalog = SQLiteArtifactCatalog(root / "catalog" / "catalog.sqlite", repository)
    with pytest.raises(ValueError, match="between"):
        # Invoke list_committed as a visible step within the test catalog page rejects
        # unbounded parameters workflow.
        catalog.list_committed(kind=None, limit=1001, offset=0)


def test_corrupt_indexed_bytes_are_translated_to_a_stable_query_failure(
    tmp_path: object,
) -> None:
    # Execute the test corrupt indexed bytes are translated to a stable query failure
    # workflow in explicit, reviewable steps.
    from pathlib import Path

    root = Path(str(tmp_path))
    repository = LocalArtifactRepository(root)
    catalog = SQLiteArtifactCatalog(root / "catalog" / "catalog.sqlite", repository)
    artifact = _publish(repository, label="corrupt", kind=ArtifactKind.SOURCE_INSPECTION)
    # Invoke index_committed for artifact as a visible test corrupt indexed bytes are
    # translated to a stable query failure step.
    catalog.index_committed(artifact)
    artifact_root = repository._find_artifact_root(artifact.artifact_id)[1]
    (artifact_root / "manifest.json").write_bytes(b'{"artifact_schema":"tampered/v1"}')

    with pytest.raises(ArtifactQueryError, match="VERIFICATION_FAILED"):
        QueryArtifacts(catalog, repository).details(artifact.artifact_id)


# Define test lineage fails closed above the shared transport bound as one focused
# operation with an explicit boundary.
def test_lineage_fails_closed_above_the_shared_transport_bound() -> None:
    # Execute the test lineage fails closed above the shared transport bound workflow in
    # explicit, reviewable steps.
    descriptors: dict[str, CommittedArtifact] = {}
    previous: ArtifactId | None = None
    for ordinal in range(1, 1_002):
        # Process range(1, 1002) inside the bounded test lineage fails closed above the
        # shared transport bound loop.
        artifact_id = ArtifactId(f"{ordinal:064x}")
        descriptor = CommittedArtifact(
            artifact_id=artifact_id,
            kind=ArtifactKind.RUN,
            manifest_digest=ContentDigest("a" * 64),
            # Keep the content digest and b ContentDigest step visible while building
            # descriptor.
            build_key=ContentDigest("b" * 64),
            input_artifact_ids=() if previous is None else (previous,),
        )
        descriptors[artifact_id.hex] = descriptor
        previous = artifact_id

    # Keep the catalog contract and validation rules together.
    class Catalog:
        def find_committed(self, artifact_id: ArtifactId) -> CommittedArtifact | None:
            return descriptors.get(artifact_id.hex)

    assert previous is not None
    queries = QueryArtifacts(cast(Any, Catalog()), cast(Any, object()))

    # Acquire raises, artifact query error and pytest at an explicit test lineage fails
    # closed above the shared transport bound context boundary so cleanup remains scoped.
    with pytest.raises(ArtifactQueryError, match="LINEAGE_LIMIT_EXCEEDED"):
        queries.lineage(previous)


def test_artifact_details_enforce_the_shared_manifest_transport_bound() -> None:
    # Execute the test artifact details enforce the shared manifest transport bound
    # workflow in explicit, reviewable steps.
    descriptor = CommittedArtifact(
        artifact_id=ArtifactId("1" * 64),
        kind=ArtifactKind.RUN,
        manifest_digest=ContentDigest("a" * 64),
        build_key=ContentDigest("b" * 64),
        # Complete CommittedArtifact only after its 1 and a inputs are visible in test
        # artifact details enforce the shared manifest transport bound.
    )

    with pytest.raises(ValueError, match="exceeds"):
        ArtifactDetails(descriptor, b"x" * (MAX_ARTIFACT_MANIFEST_BYTES + 1))
