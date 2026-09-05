# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import (
    ArtifactClosureMaterializationError,
    # Include local artifact repository so the localfs dependency remains explicit.
    LocalArtifactRepository,
    materialize_verified_artifact_closure,
)
from backtest.adapters.artifacts.localfs.repository import ArtifactIntegrityError
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest


def _commit(
    repository: LocalArtifactRepository,
    *,
    kind: ArtifactKind,
    # Keep the label input explicit in the commit contract.
    label: str,
    inputs: tuple[CommittedArtifact, ...] = (),
    identity: dict[str, object] | None = None,
) -> CommittedArtifact:
    # Execute the commit workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=domain_digest("test.materialized-build.v1", {"label": label}),
            input_artifact_ids=tuple(item.artifact_id for item in inputs),
            # Complete ArtifactDraft only after its v1 and label inputs are visible in commit.
        )
    )
    with writer.open_binary("payload.bin") as stream:
        stream.write(label.encode("ascii"))
    placement_identity = {} if identity is None else identity
    return writer.commit(
        canonical_json_bytes({**placement_identity, "schema": "test.materialized-artifact.v1"}),
        identity_manifest_bytes=canonical_json_bytes(placement_identity),
    )


# Define test materializes exact transitive closure as single link files as one focused
# operation with an explicit boundary.
def test_materializes_exact_transitive_closure_as_single_link_files(tmp_path: Path) -> None:
    # Execute the test materializes exact transitive closure as single link files workflow
    # in explicit, reviewable steps.
    source = LocalArtifactRepository(tmp_path / "source")
    leaf = _commit(
        source,
        kind=ArtifactKind.CANONICAL_DISTRIBUTION,
        label="leaf",
        identity={"logical_content_hash": "a" * 64},
    )
    root = _commit(
        source,
        kind=ArtifactKind.REPLAY_PACK,
        label="root",
        inputs=(leaf,),
        identity={"snapshot_id": "b" * 64},
    )

    materialized = materialize_verified_artifact_closure(
        source,
        # Pass roots explicitly so materialize_verified_artifact_closure receives a
        # reviewable isolated and artifact id input in test materializes exact transitive
        # closure as single link files.
        roots=(root.artifact_id,),
        destination_root=tmp_path / "isolated",
        maximum_copy_bytes=1 << 20,
        minimum_free_after_bytes=0,
    )

    # Verify the roots, materialized and artifact id relationship before this scenario is
    # accepted.
    assert materialized.roots == (root.artifact_id,)
    assert materialized.transitive_closure == tuple(
        sorted((leaf.artifact_id, root.artifact_id), key=lambda item: item.hex)
    )
    assert materialized.logical_bytes > len(b"leafroot")
    # Verify the hex, closure digest and materialized relationship before this scenario is
    # accepted.
    assert len(materialized.closure_digest.hex) == 64
    copied = LocalArtifactRepository(materialized.data_root)
    assert (
        materialized.data_root / "canonical" / ("a" * 64) / leaf.artifact_id.hex / "COMMITTED"
    ).is_file()
    assert (
        materialized.data_root / "replay" / ("b" * 64) / root.artifact_id.hex / "COMMITTED"
    ).is_file()
    for expected in (leaf, root):
        # Process (leaf, root) inside the bounded test materializes exact transitive
        # closure as single link files loop.
        handle = copied.open_committed(expected.artifact_id)
        try:
            # Perform the protected test materializes exact transitive closure as single
            # link files operation before explicit failure handling.
            assert handle.descriptor == expected
            with handle.open_binary("payload.bin") as stream:
                assert stream.read() in {b"leaf", b"root"}
        finally:
            handle.close()
    # Traverse materialized.data_root.rglob('*') explicitly so each test materializes
    # exact transitive closure as single link files iteration remains traceable.
    for path in materialized.data_root.rglob("*"):
        # Process materialized.data_root.rglob('*') inside the bounded test materializes
        # exact transitive closure as single link files loop.
        if path.is_file():
            assert path.stat().st_nlink == 1


def test_materialization_fails_before_copy_when_closure_exceeds_quota(tmp_path: Path) -> None:
    # Execute the test materialization fails before copy when closure exceeds quota
    # workflow in explicit, reviewable steps.
    source = LocalArtifactRepository(tmp_path / "source")
    root = _commit(source, kind=ArtifactKind.SNAPSHOT, label="larger-than-one-byte")
    destination = tmp_path / "isolated"

    with pytest.raises(ArtifactClosureMaterializationError, match="hard quota"):
        # Keep raises, artifact closure materialization error and pytest active only for
        # the bounded test materialization fails before copy when closure exceeds quota
        # operation.
        materialize_verified_artifact_closure(
            source,
            roots=(root.artifact_id,),
            destination_root=destination,
            maximum_copy_bytes=1,
            # Pass minimum free after bytes explicitly so
            # materialize_verified_artifact_closure receives a reviewable artifact id and
            # source input in test materialization fails before copy when closure exceeds
            # quota.
            minimum_free_after_bytes=0,
        )

    assert not destination.exists()


def test_materialization_rejects_tampered_source_and_existing_destination(
    tmp_path: Path,
    # Close the test materialization rejects tampered source and existing destination
    # signature after its explicit inputs.
) -> None:
    # Execute the test materialization rejects tampered source and existing destination
    # workflow in explicit, reviewable steps.
    source = LocalArtifactRepository(tmp_path / "source")
    root = _commit(source, kind=ArtifactKind.SNAPSHOT, label="root")
    destination = tmp_path / "isolated"
    destination.mkdir()

    with pytest.raises(ArtifactClosureMaterializationError, match="already exists"):
        # Keep raises, artifact closure materialization error and pytest active only for
        # the bounded test materialization rejects tampered source and existing
        # destination operation.
        materialize_verified_artifact_closure(
            source,
            roots=(root.artifact_id,),
            destination_root=destination,
            maximum_copy_bytes=1 << 20,
            # Pass minimum free after bytes explicitly so
            # materialize_verified_artifact_closure receives a reviewable artifact id and
            # source input in test materialization rejects tampered source and existing
            # destination.
            minimum_free_after_bytes=0,
        )

    destination.rmdir()
    payload = next((tmp_path / "source" / "snapshots" / root.artifact_id.hex).glob("payload.bin"))
    payload.write_bytes(b"tampered")
    # Acquire raises, artifact integrity error and pytest at an explicit test
    # materialization rejects tampered source and existing destination context boundary so
    # cleanup remains scoped.
    with pytest.raises(ArtifactIntegrityError):
        # Keep raises, artifact integrity error and pytest active only for the bounded
        # test materialization rejects tampered source and existing destination operation.
        materialize_verified_artifact_closure(
            source,
            roots=(root.artifact_id,),
            destination_root=destination,
            maximum_copy_bytes=1 << 20,
            # Pass minimum free after bytes explicitly so
            # materialize_verified_artifact_closure receives a reviewable artifact id and
            # source input in test materialization rejects tampered source and existing
            # destination.
            minimum_free_after_bytes=0,
        )
    assert not destination.exists()
