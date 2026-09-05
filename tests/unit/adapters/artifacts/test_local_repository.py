# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import errno
import json
import os
import shutil
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from threading import Event

import pytest

from backtest.adapters.artifacts.localfs.repository import (
    ArtifactIntegrityError,
    ArtifactNotCommittedError,
    # Include artifact repository error so the repository dependency remains explicit.
    ArtifactRepositoryError,
    ArtifactWriterStateError,
    InvalidArtifactPathError,
    LocalArtifactRepository,
    StagingQuotaExceededError,
    # Close the repository import after its required symbols are visible.
)
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ArtifactId, ContentDigest, ReplayPackId, SnapshotId
from backtest.runtime.file_locks import FileLock, LockMode, LockUnavailableError


def _draft() -> ArtifactDraft:
    # Execute the draft workflow in explicit, reviewable steps.
    return ArtifactDraft(
        kind=ArtifactKind.SOURCE_INSPECTION,
        build_key=ContentDigest("1" * 64),
    )


def _publish_layout_artifact(
    repository: LocalArtifactRepository,
    *,
    kind: ArtifactKind,
    identity: dict[str, object],
    label: str,
) -> CommittedArtifact:
    """Publish a small artifact whose identity carries only placement operands."""

    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=domain_digest(
                "test.local-artifact-layout-build.v1",
                {"kind": kind.value, "label": label},
            ),
        )
    )
    with writer.open_binary("data.bin") as stream:
        stream.write(label.encode("ascii"))
    manifest = canonical_json_bytes({**identity, "schema": "test.artifact-layout/v1"})
    return writer.commit(
        manifest,
        identity_manifest_bytes=canonical_json_bytes(identity),
    )


def test_round_trip_committed_artifact(tmp_path: Path) -> None:
    # Execute the test round trip committed artifact workflow in explicit, reviewable
    # steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("metadata/schema.json") as stream:
        stream.write(b'{"tables":[]}')

    committed = writer.commit(b'{"schema_version":1}')

    # Assemble handle once so the test round trip committed artifact workflow shares one
    # value.
    handle = repository.open_committed(committed.artifact_id)
    try:
        # Perform the protected test round trip committed artifact operation before
        # explicit failure handling.
        assert handle.descriptor == committed
        with handle.open_binary("metadata/schema.json") as stream:
            assert stream.read() == b'{"tables":[]}'
        with handle.open_binary("manifest.json") as stream:
            assert json.load(stream) == {"schema_version": 1}
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        handle.close()


def test_same_content_reuses_same_artifact_identity(tmp_path: Path) -> None:
    # Execute the test same content reuses same artifact identity workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")

    def publish() -> object:
        # Execute the publish workflow in explicit, reviewable steps.
        writer = repository.stage(_draft())
        with writer.open_binary("data.bin") as stream:
            stream.write(b"same bytes")
        return writer.commit(b'{"version":1}')

    assert publish() == publish()


# Apply parametrize semantics to the following test writer rejects unsafe or reserved
# paths contract.
@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        # Pass json explicitly so parametrize receives a reviewable name and /escape input
        # in test writer rejects unsafe or reserved paths.
        "manifest.json",
        "manifest.json/child",
        ".COMMITTED.tmp-attacker",
        ".",
        "line\nbreak",
        # Pass a b explicitly so parametrize receives a reviewable name and /escape input
        # in test writer rejects unsafe or reserved paths.
        "a\\b",
    ],
)
def test_writer_rejects_unsafe_or_reserved_paths(tmp_path: Path, name: str) -> None:
    # Execute the test writer rejects unsafe or reserved paths workflow in explicit,
    # reviewable steps.
    writer = LocalArtifactRepository(tmp_path / "var").stage(_draft())
    try:
        # Perform the protected test writer rejects unsafe or reserved paths operation
        # before explicit failure handling.
        with pytest.raises(InvalidArtifactPathError):
            writer.open_binary(name)
    finally:
        writer.abort()


def test_commit_requires_closed_payload_streams(tmp_path: Path) -> None:
    # Execute the test commit requires closed payload streams workflow in explicit,
    # reviewable steps.
    writer = LocalArtifactRepository(tmp_path / "var").stage(_draft())
    stream = writer.open_binary("data.bin")
    try:
        # Perform the protected test commit requires closed payload streams operation
        # before explicit failure handling.
        with pytest.raises(ArtifactWriterStateError):
            writer.commit(b"{}")
    finally:
        # Handle the cleanup path after the protected test commit requires closed payload
        # streams operation.
        stream.close()
        writer.abort()


def test_staging_quota_rejects_payload_before_crossing_hard_limit(tmp_path: Path) -> None:
    # Execute the test staging quota rejects payload before crossing hard limit workflow
    # in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var", staging_quota_bytes=4)
    writer = repository.stage(_draft())
    stream = writer.open_binary("data.bin")
    try:
        # Perform the protected test staging quota rejects payload before crossing hard
        # limit operation before explicit failure handling.
        with pytest.raises(StagingQuotaExceededError, match="quota"):
            stream.write(b"12345")
        assert next(repository.staging_root.glob("artifact-*/data.bin")).stat().st_size == 0
    finally:
        # Handle the cleanup path after the protected test staging quota rejects payload
        # before crossing hard limit operation.
        stream.close()
        writer.abort()


def test_staging_quota_includes_manifest_and_descriptor_bytes(tmp_path: Path) -> None:
    # Execute the test staging quota includes manifest and descriptor bytes workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var", staging_quota_bytes=1)
    writer = repository.stage(_draft())

    with pytest.raises(StagingQuotaExceededError, match="quota"):
        writer.commit(b"{}")

    assert not tuple((tmp_path / "var" / "source-inspections").glob("*/COMMITTED"))
    # Invoke abort as a visible step within the test staging quota includes manifest and
    # descriptor bytes workflow.
    writer.abort()


def test_open_detects_payload_tampering(tmp_path: Path) -> None:
    # Execute the test open detects payload tampering workflow in explicit, reviewable
    # steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"original")
    committed = writer.commit(b"{}")

    # Assemble payload path once so the test open detects payload tampering workflow
    # shares one value.
    payload_path = tmp_path / "var" / "source-inspections" / committed.artifact_id.hex / "data.bin"
    payload_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        repository.open_committed(committed.artifact_id)


def test_repeated_open_reuses_hashes_only_until_file_fingerprint_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest.adapters.artifacts.localfs import repository as repository_module

    data_root = tmp_path / "var"
    publisher = LocalArtifactRepository(data_root)
    writer = publisher.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"original")
    committed = writer.commit(b"{}")

    reader = LocalArtifactRepository(data_root)
    original_sha256_file = repository_module._sha256_file
    hashed_paths: list[Path] = []

    def observe_hash(path: Path) -> tuple[str, int]:
        hashed_paths.append(path)
        return original_sha256_file(path)

    monkeypatch.setattr(repository_module, "_sha256_file", observe_hash)
    reader.open_committed(committed.artifact_id).close()
    cold_hash_count = len(hashed_paths)
    assert cold_hash_count > 0

    reader.open_committed(committed.artifact_id).close()
    assert len(hashed_paths) == cold_hash_count

    payload_path = data_root / "source-inspections" / committed.artifact_id.hex / "data.bin"
    payload_path.write_bytes(b"modified")
    with pytest.raises(ArtifactIntegrityError):
        reader.open_committed(committed.artifact_id)
    assert len(hashed_paths) > cold_hash_count


def test_verification_cache_size_is_strictly_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="verification_cache_entries"):
        LocalArtifactRepository(tmp_path / "var", verification_cache_entries=0)
    with pytest.raises(ValueError, match="verification_cache_bytes"):
        LocalArtifactRepository(tmp_path / "var", verification_cache_bytes=0)


def test_oversized_verification_evidence_is_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest.adapters.artifacts.localfs import repository as repository_module

    data_root = tmp_path / "var"
    publisher = LocalArtifactRepository(data_root)
    writer = publisher.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"payload")
    committed = writer.commit(b"{}")
    reader = LocalArtifactRepository(data_root, verification_cache_bytes=1)
    original_sha256_file = repository_module._sha256_file
    hashed_paths: list[Path] = []

    # Count full payload authentication; a one-byte budget cannot retain its evidence.
    def observe_hash(path: Path) -> tuple[str, int]:
        hashed_paths.append(path)
        return original_sha256_file(path)

    monkeypatch.setattr(repository_module, "_sha256_file", observe_hash)
    reader.open_committed(committed.artifact_id).close()
    first_hash_count = len(hashed_paths)
    reader.open_committed(committed.artifact_id).close()

    assert first_hash_count > 0
    assert len(hashed_paths) == 2 * first_hash_count
    assert reader._verification_cache_current_bytes == 0


def test_cache_hit_reauthenticates_small_authority_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest.adapters.artifacts.localfs import repository as repository_module

    data_root = tmp_path / "var"
    repository = LocalArtifactRepository(data_root)
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    repository.open_committed(committed.artifact_id).close()
    cached_fingerprint = repository_module._artifact_file_fingerprint(
        data_root / "source-inspections" / committed.artifact_id.hex
    )

    # Simulate unchanged stat evidence so the cheap control-file authentication is tested.
    monkeypatch.setattr(
        repository_module,
        "_artifact_file_fingerprint",
        lambda _: cached_fingerprint,
    )
    manifest = data_root / "source-inspections" / committed.artifact_id.hex / "manifest.json"
    manifest.write_bytes(b"[]")

    with pytest.raises(ArtifactIntegrityError, match="manifest digest"):
        repository.open_committed(committed.artifact_id)


def test_cache_hit_rejects_payload_mutation_during_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second fingerprint closes the race after cached control-file checks."""

    from backtest.adapters.artifacts.localfs import repository as repository_module

    data_root = tmp_path / "var"
    repository = LocalArtifactRepository(data_root)
    writer = repository.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"original")
    committed = writer.commit(b"{}")
    repository.open_committed(committed.artifact_id).close()

    payload = data_root / "source-inspections" / committed.artifact_id.hex / "data.bin"
    authenticate = repository_module._verify_cached_control_files

    # Mutate only after the cache-hit fingerprint has been accepted.
    def mutate_after_authentication(
        root: Path,
        descriptor: Mapping[str, object],
        descriptor_bytes: bytes,
    ) -> None:
        authenticate(root, descriptor, descriptor_bytes)
        payload.write_bytes(b"modified")

    monkeypatch.setattr(
        repository_module,
        "_verify_cached_control_files",
        mutate_after_authentication,
    )
    with pytest.raises(ArtifactIntegrityError, match="changed during verification"):
        repository.open_committed(committed.artifact_id)


def test_concurrent_cold_opens_share_one_full_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "var"
    publisher = LocalArtifactRepository(data_root)
    writer = publisher.stage(_draft())
    committed = writer.commit(b"{}")
    reader = LocalArtifactRepository(data_root)
    original_verify = reader._verify_committed_uncached
    first_started = Event()
    release_first = Event()
    calls: list[Path] = []

    # Hold the first cold scan long enough for the second request to join single-flight.
    def observe_verify(
        root: Path,
        *,
        expected_id: ArtifactId | None = None,
        expected_kind: ArtifactKind | None = None,
    ) -> dict[str, object]:
        calls.append(root)
        first_started.set()
        assert release_first.wait(timeout=5)
        return original_verify(
            root,
            expected_id=expected_id,
            expected_kind=expected_kind,
        )

    monkeypatch.setattr(reader, "_verify_committed_uncached", observe_verify)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(reader.open_committed, committed.artifact_id)
        assert first_started.wait(timeout=5)
        second = pool.submit(reader.open_committed, committed.artifact_id)
        release_first.set()
        first.result(timeout=5).close()
        second.result(timeout=5).close()

    assert calls == [data_root / "source-inspections" / committed.artifact_id.hex]


@pytest.mark.parametrize(
    ("kind", "identity", "identifier_type"),
    (
        (ArtifactKind.SNAPSHOT, {}, SnapshotId),
        (ArtifactKind.REPLAY_PACK, {"snapshot_id": "b" * 64}, ReplayPackId),
    ),
)
def test_verification_cache_accepts_typed_artifact_ids_on_repeated_open(
    tmp_path: Path,
    kind: ArtifactKind,
    identity: dict[str, object],
    identifier_type: type[ArtifactId],
) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    committed = _publish_layout_artifact(
        repository,
        kind=kind,
        identity=identity,
        label=kind.value,
    )
    typed_id = identifier_type(committed.artifact_id.hex)

    repository.open_committed(typed_id).close()
    repository.open_committed(typed_id).close()


def test_manifest_must_be_json_object(tmp_path: Path) -> None:
    # Execute the test manifest must be json object workflow in explicit, reviewable
    # steps.
    writer = LocalArtifactRepository(tmp_path / "var").stage(_draft())
    with pytest.raises(ArtifactIntegrityError):
        writer.commit(b"[]")
    writer.abort()


def test_manifest_rejects_non_finite_json_numbers(tmp_path: Path) -> None:
    # Execute the test manifest rejects non finite json numbers workflow in explicit,
    # reviewable steps.
    writer = LocalArtifactRepository(tmp_path / "var").stage(_draft())
    with pytest.raises(ArtifactIntegrityError, match="invalid root manifest JSON"):
        writer.commit(b'{"value":NaN}')
    writer.abort()


def test_digest_display_prefix_does_not_change_artifact_identity(tmp_path: Path) -> None:
    # Execute the test digest display prefix does not change artifact identity workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    plain = _draft()
    prefixed = ArtifactDraft(
        kind=plain.kind,
        build_key=ContentDigest(f"sha256:{plain.build_key.hex}"),
        # Complete ArtifactDraft only after its sha256: and kind inputs are visible in test
        # digest display prefix does not change artifact identity.
    )

    def publish(draft: ArtifactDraft):  # type: ignore[no-untyped-def]
        writer = repository.stage(draft)
        with writer.open_binary("data.bin") as stream:
            stream.write(b"same")
        return writer.commit(b"{}")

    assert publish(plain) == publish(prefixed)


# Define test missing input artifact prevents publication as one focused operation with an
# explicit boundary.
def test_missing_input_artifact_prevents_publication(tmp_path: Path) -> None:
    # Execute the test missing input artifact prevents publication workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.SNAPSHOT,
            build_key=ContentDigest("2" * 64),
            # Keep the artifact id and a ArtifactId step visible while building writer.
            input_artifact_ids=(ArtifactId("a" * 64),),
        )
    )
    with writer.open_binary("data.bin") as stream:
        stream.write(b"payload")

    # Acquire raises, artifact not committed error and pytest at an explicit test missing
    # input artifact prevents publication context boundary so cleanup remains scoped.
    with pytest.raises(ArtifactNotCommittedError):
        writer.commit(b"{}")
    assert not tuple((tmp_path / "var" / "snapshots").glob("*/COMMITTED"))
    writer.abort()


def test_valid_input_artifact_is_verified_before_dependent_commit(tmp_path: Path) -> None:
    # Execute the test valid input artifact is verified before dependent commit workflow
    # in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    input_writer = repository.stage(_draft())
    input_artifact = input_writer.commit(b"{}")
    output_writer = repository.stage(
        ArtifactDraft(
            # Pass kind explicitly so ArtifactDraft receives a reviewable 2 and snapshot
            # input in test valid input artifact is verified before dependent commit.
            kind=ArtifactKind.SNAPSHOT,
            build_key=ContentDigest("2" * 64),
            input_artifact_ids=(input_artifact.artifact_id,),
        )
    )

    # Assemble output once so the test valid input artifact is verified before dependent
    # commit workflow shares one value.
    output = output_writer.commit(b"{}")

    with repository.open_committed(output.artifact_id) as handle:  # type: ignore[attr-defined]
        assert handle.descriptor == output


def test_input_order_does_not_change_artifact_identity(tmp_path: Path) -> None:
    # Execute the test input order does not change artifact identity workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    first_writer = repository.stage(_draft())
    first = first_writer.commit(b'{"input":1}')
    second_writer = repository.stage(_draft())
    second = second_writer.commit(b'{"input":2}')

    def publish(inputs: tuple[ArtifactId, ...]):  # type: ignore[no-untyped-def]
        writer = repository.stage(
            ArtifactDraft(
                kind=ArtifactKind.SNAPSHOT,
                build_key=ContentDigest("2" * 64),
                input_artifact_ids=inputs,
                # Complete ArtifactDraft only after its 2 and snapshot inputs are visible in
                # publish.
            )
        )
        return writer.commit(b"{}")

    assert publish((first.artifact_id, second.artifact_id)) == publish(
        (second.artifact_id, first.artifact_id)
        # Complete publish only after its artifact id and second inputs are visible in test
        # input order does not change artifact identity.
    )


def test_duplicate_input_artifacts_are_rejected(tmp_path: Path) -> None:
    # Execute the test duplicate input artifacts are rejected workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    input_writer = repository.stage(_draft())
    input_artifact = input_writer.commit(b"{}")
    writer = repository.stage(
        ArtifactDraft(
            # Pass kind explicitly so ArtifactDraft receives a reviewable 2 and snapshot
            # input in test duplicate input artifacts are rejected.
            kind=ArtifactKind.SNAPSHOT,
            build_key=ContentDigest("2" * 64),
            input_artifact_ids=(input_artifact.artifact_id, input_artifact.artifact_id),
        )
    )

    # Acquire raises, artifact integrity error and pytest at an explicit test duplicate
    # input artifacts are rejected context boundary so cleanup remains scoped.
    with pytest.raises(ArtifactIntegrityError, match="duplicates"):
        writer.commit(b"{}")
    writer.abort()


def test_symbolic_link_payload_is_rejected(tmp_path: Path) -> None:
    # Execute the test symbolic link payload is rejected workflow in explicit, reviewable
    # steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    staging_root = next(repository.staging_root.glob("artifact-*"))
    # Invoke symlink_to for outside as a visible test symbolic link payload is rejected
    # step.
    (staging_root / "link").symlink_to(outside)

    with pytest.raises(ArtifactIntegrityError, match="symbolic links"):
        writer.commit(b"{}")
    writer.abort()


def test_hard_linked_payload_is_rejected(tmp_path: Path) -> None:
    # Execute the test hard linked payload is rejected workflow in explicit, reviewable
    # steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    outside = tmp_path / "outside"
    outside.write_bytes(b"mutable elsewhere")
    staging_root = next(repository.staging_root.glob("artifact-*"))
    # Invoke link for hard-link and outside as a visible test hard linked payload is
    # rejected step.
    os.link(outside, staging_root / "hard-link")

    with pytest.raises(ArtifactIntegrityError, match="hard-linked"):
        writer.commit(b"{}")
    writer.abort()


def test_symbolic_link_artifact_root_is_never_followed(tmp_path: Path) -> None:
    # Execute the test symbolic link artifact root is never followed workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    root = repository.data_root / "source-inspections" / committed.artifact_id.hex
    moved = root.with_name(f"{root.name}.moved")
    # Invoke rename for moved as a visible test symbolic link artifact root is never
    # followed step.
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError, match="real directory"):
        repository.open_committed(committed.artifact_id)


def test_descriptor_kind_must_match_physical_directory(tmp_path: Path) -> None:
    # Execute the test descriptor kind must match physical directory workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    original = repository.data_root / "source-inspections" / committed.artifact_id.hex
    snapshots = repository.data_root / "snapshots"
    # Invoke mkdir as a visible step within the test descriptor kind must match physical
    # directory workflow.
    snapshots.mkdir()
    moved = snapshots / committed.artifact_id.hex
    original.rename(moved)

    with pytest.raises(ArtifactIntegrityError, match="kind"):
        repository.open_committed(committed.artifact_id)


# Define test duplicate artifact roots fail closed as one focused operation with an
# explicit boundary.
def test_duplicate_artifact_roots_fail_closed(tmp_path: Path) -> None:
    # Execute the test duplicate artifact roots fail closed workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    original = repository.data_root / "source-inspections" / committed.artifact_id.hex
    duplicate = repository.data_root / "snapshots" / committed.artifact_id.hex
    # Invoke mkdir as a visible step within the test duplicate artifact roots fail closed
    # workflow.
    duplicate.parent.mkdir()
    shutil.copytree(original, duplicate)

    with pytest.raises(ArtifactIntegrityError, match="more than one"):
        repository.open_committed(committed.artifact_id)


def test_temporary_marker_is_not_an_unauthenticated_payload_namespace(tmp_path: Path) -> None:
    # Execute the test temporary marker is not an unauthenticated payload namespace
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    root = repository.data_root / "source-inspections" / committed.artifact_id.hex
    (root / ".COMMITTED.tmp-injected").write_bytes(b"not authenticated")

    # Acquire raises, artifact integrity error and pytest at an explicit test temporary
    # marker is not an unauthenticated payload namespace context boundary so cleanup
    # remains scoped.
    with pytest.raises(ArtifactIntegrityError, match="payload"):
        repository.open_committed(committed.artifact_id)


def test_open_handle_releases_publication_lock_but_keeps_retention_lease(
    tmp_path: Path,
) -> None:
    # Execute the test open handle releases publication lock but keeps retention lease
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")

    handle = repository.open_committed(committed.artifact_id)
    try:
        # Perform the protected test open handle releases publication lock but keeps
        # retention lease operation before explicit failure handling.
        with FileLock(
            repository.locks_root / "publication.lock",
            mode=LockMode.EXCLUSIVE,
            timeout=0,
        ):
            # Keep this explicitly supported no-op branch visible.
            pass
        with pytest.raises(LockUnavailableError):
            # Keep raises, lock unavailable error and pytest active only for the bounded
            # test open handle releases publication lock but keeps retention lease
            # operation.
            FileLock(
                repository.locks_root / "retention.lock",
                mode=LockMode.EXCLUSIVE,
                timeout=0,
            ).acquire()
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        handle.close()

    with FileLock(
        repository.locks_root / "retention.lock",
        mode=LockMode.EXCLUSIVE,
        # Pass timeout explicitly so FileLock receives a reviewable lock and locks root
        # input in test open handle releases publication lock but keeps retention lease.
        timeout=0,
    ):
        pass


def test_crash_before_marker_never_exposes_partial_artifact(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test crash before marker never exposes
    # partial artifact contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test crash before marker never exposes partial artifact workflow in
    # explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"payload")
    # Assemble durable write once so the test crash before marker never exposes partial
    # artifact workflow shares one value.
    durable_write = repository_module._write_durable_exclusive

    def fail_marker(path: Path, payload: bytes) -> None:
        # Execute the fail marker workflow in explicit, reviewable steps.
        if path.name.startswith(".COMMITTED.tmp-"):
            raise OSError("injected crash before marker")
        durable_write(path, payload)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test crash before
        # marker never exposes partial artifact operation.
        context.setattr(repository_module, "_write_durable_exclusive", fail_marker)
        with pytest.raises(OSError, match="injected crash"):
            writer.commit(b"{}")

    partial_root = next((repository.data_root / "source-inspections").iterdir())
    partial_id = ArtifactId(partial_root.name)
    # Verify the exists, partial root and committed relationship before this scenario is
    # accepted.
    assert not (partial_root / "COMMITTED").exists()
    with pytest.raises(ArtifactNotCommittedError):
        repository.open_committed(partial_id)

    retry = repository.stage(_draft())
    with retry.open_binary("data.bin") as stream:
        # Invoke write as a visible step within the test crash before marker never exposes
        # partial artifact workflow.
        stream.write(b"payload")
    committed = retry.commit(b"{}")
    with repository.open_committed(committed.artifact_id) as handle:  # type: ignore[attr-defined]
        assert handle.descriptor == committed
    assert any(repository.trash_root.iterdir())


def test_enospc_while_writing_staging_metadata_never_publishes_an_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test enospc while writing staging metadata never publishes an artifact
    # signature after its explicit inputs.
) -> None:
    # Execute the test enospc while writing staging metadata never publishes an artifact
    # workflow in explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"payload")
    # Assemble durable write once so the test enospc while writing staging metadata never
    # publishes an artifact workflow shares one value.
    durable_write = repository_module._write_durable_exclusive

    def fail_manifest(path: Path, payload: bytes) -> None:
        # Execute the fail manifest workflow in explicit, reviewable steps.
        if path.name == "manifest.json":
            raise OSError(errno.ENOSPC, "injected disk full")
        durable_write(path, payload)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test enospc while
        # writing staging metadata never publishes an artifact operation.
        context.setattr(repository_module, "_write_durable_exclusive", fail_manifest)
        with pytest.raises(OSError) as caught:
            writer.commit(b"{}")

    assert caught.value.errno == errno.ENOSPC
    assert not tuple((repository.data_root / "source-inspections").glob("*/COMMITTED"))
    # Invoke abort as a visible step within the test enospc while writing staging metadata
    # never publishes an artifact workflow.
    writer.abort()
    assert not tuple(repository.staging_root.glob("artifact-*"))


def test_enospc_at_commit_marker_leaves_only_an_invisible_recoverable_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test enospc at commit marker leaves only an invisible recoverable partial
    # signature after its explicit inputs.
) -> None:
    # Execute the test enospc at commit marker leaves only an invisible recoverable
    # partial workflow in explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("data.bin") as stream:
        stream.write(b"payload")
    # Assemble durable write once so the test enospc at commit marker leaves only an
    # invisible recoverable partial workflow shares one value.
    durable_write = repository_module._write_durable_exclusive

    def fail_marker(path: Path, payload: bytes) -> None:
        # Execute the fail marker workflow in explicit, reviewable steps.
        if path.name.startswith(".COMMITTED.tmp-"):
            raise OSError(errno.ENOSPC, "injected disk full")
        durable_write(path, payload)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test enospc at commit
        # marker leaves only an invisible recoverable partial operation.
        context.setattr(repository_module, "_write_durable_exclusive", fail_marker)
        with pytest.raises(OSError) as caught:
            writer.commit(b"{}")

    assert caught.value.errno == errno.ENOSPC
    partial_root = next((repository.data_root / "source-inspections").iterdir())
    # Verify the exists, partial root and committed relationship before this scenario is
    # accepted.
    assert not (partial_root / "COMMITTED").exists()
    with pytest.raises(ArtifactNotCommittedError):
        repository.open_committed(ArtifactId(partial_root.name))

    retry = repository.stage(_draft())
    with retry.open_binary("data.bin") as stream:
        # Invoke write as a visible step within the test enospc at commit marker leaves
        # only an invisible recoverable partial workflow.
        stream.write(b"payload")
    committed = retry.commit(b"{}")
    with repository.open_committed(committed.artifact_id) as handle:  # type: ignore[attr-defined]
        assert handle.descriptor == committed
    assert any(repository.trash_root.iterdir())


def test_marker_surviving_pre_fsync_crash_is_verified_and_adopted_on_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    # Close the test marker surviving pre fsync crash is verified and adopted on open
    # signature after its explicit inputs.
) -> None:
    # Execute the test marker surviving pre fsync crash is verified and adopted on open
    # workflow in explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    directory_fsync = repository_module._fsync_directory
    failed = False

    # Define fail after marker as one focused operation with an explicit boundary.
    def fail_after_marker(path: Path) -> None:
        # Execute the fail after marker workflow in explicit, reviewable steps.
        nonlocal failed
        if not failed and path.name != "source-inspections" and (path / "COMMITTED").exists():
            # Handle the fail after marker failed, name and source-inspections condition
            # as a distinct block.
            failed = True
            raise OSError("injected crash after marker rename")
        directory_fsync(path)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test marker surviving
        # pre fsync crash is verified and adopted on open operation.
        context.setattr(repository_module, "_fsync_directory", fail_after_marker)
        with pytest.raises(OSError, match="after marker"):
            writer.commit(b"{}")

    partial_root = next((repository.data_root / "source-inspections").iterdir())
    artifact_id = ArtifactId(partial_root.name)
    # Verify (partial_root / 'COMMITTED').is_file() before this scenario is accepted.
    assert (partial_root / "COMMITTED").is_file()
    with repository.open_committed(artifact_id) as handle:  # type: ignore[attr-defined]
        assert handle.descriptor.artifact_id == artifact_id


def test_corrupt_collision_is_quarantined_not_overwritten(tmp_path: Path) -> None:
    # Execute the test corrupt collision is quarantined not overwritten workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")

    def publish():  # type: ignore[no-untyped-def]
        writer = repository.stage(_draft())
        with writer.open_binary("data.bin") as stream:
            stream.write(b"correct")
        return writer.commit(b"{}")

    first = publish()
    # Assemble root once so the test corrupt collision is quarantined not overwritten
    # workflow shares one value.
    root = repository.data_root / "source-inspections" / first.artifact_id.hex
    (root / "data.bin").write_bytes(b"corrupt")

    second = publish()

    assert second == first
    with (
        repository.open_committed(second.artifact_id) as handle,  # type: ignore[attr-defined]
        handle.open_binary("data.bin") as stream,
    ):
        assert stream.read() == b"correct"
    quarantined = tuple(repository.trash_root.iterdir())
    assert len(quarantined) == 1
    # Verify the read bytes, bin and quarantined relationship before this scenario is
    # accepted.
    assert (quarantined[0] / "data.bin").read_bytes() == b"corrupt"


def test_abort_releases_writer_lock_even_if_cleanup_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test abort releases writer lock even if cleanup fsync fails workflow in
    # explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    directory_fsync = repository_module._fsync_directory

    def fail_staging_fsync(path: Path) -> None:
        # Execute the fail staging fsync workflow in explicit, reviewable steps.
        if path == repository.staging_root:
            raise OSError("injected cleanup failure")
        directory_fsync(path)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test abort releases
        # writer lock even if cleanup fsync fails operation.
        context.setattr(repository_module, "_fsync_directory", fail_staging_fsync)
        with pytest.raises(OSError, match="cleanup"):
            writer.abort()

    with FileLock(
        repository.locks_root / "writer.lock",
        # Pass mode explicitly so FileLock receives a reviewable lock and locks root input
        # in test abort releases writer lock even if cleanup fsync fails.
        mode=LockMode.EXCLUSIVE,
        timeout=0,
    ):
        pass


def test_handle_rejects_symlinked_parent_after_verification(tmp_path: Path) -> None:
    # Execute the test handle rejects symlinked parent after verification workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    with writer.open_binary("nested/data.bin") as stream:
        stream.write(b"inside")
    committed = writer.commit(b"{}")
    # Assemble handle once so the test handle rejects symlinked parent after verification
    # workflow shares one value.
    handle = repository.open_committed(committed.artifact_id)
    root = repository.data_root / "source-inspections" / committed.artifact_id.hex
    original = root / "nested"
    moved = root / "moved"
    original.rename(moved)
    # Invoke symlink_to for tmp path as a visible test handle rejects symlinked parent
    # after verification step.
    original.symlink_to(tmp_path, target_is_directory=True)
    try:
        # Perform the protected test handle rejects symlinked parent after verification
        # operation before explicit failure handling.
        with pytest.raises(InvalidArtifactPathError, match="symlink"):
            handle.open_binary("nested/data.bin")
    finally:
        handle.close()


def test_writer_lifecycle_is_terminal_after_abort(tmp_path: Path) -> None:
    # Execute the test writer lifecycle is terminal after abort workflow in explicit,
    # reviewable steps.
    writer = LocalArtifactRepository(tmp_path / "var").stage(_draft())
    writer.abort()
    writer.abort()

    with pytest.raises(ArtifactWriterStateError, match="aborted"):
        writer.open_binary("data.bin")
    # Acquire raises, artifact writer state error and pytest at an explicit test writer
    # lifecycle is terminal after abort context boundary so cleanup remains scoped.
    with pytest.raises(ArtifactWriterStateError, match="aborted"):
        writer.commit(b"{}")


def test_closed_handle_rejects_reads(tmp_path: Path) -> None:
    # Execute the test closed handle rejects reads workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(_draft())
    committed = writer.commit(b"{}")
    handle = repository.open_committed(committed.artifact_id)
    handle.close()

    # Acquire raises, artifact repository error and pytest at an explicit test closed
    # handle rejects reads context boundary so cleanup remains scoped.
    with pytest.raises(ArtifactRepositoryError, match="closed"):
        handle.open_binary("manifest.json")


def test_manifest_identity_selects_exact_normative_physical_paths(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    cases = (
        (
            ArtifactKind.CANONICAL_DISTRIBUTION,
            {"logical_content_hash": "a" * 64},
            ("canonical", "a" * 64),
        ),
        (ArtifactKind.SNAPSHOT, {}, ("snapshots",)),
        (ArtifactKind.REPLAY_PACK, {"snapshot_id": "b" * 64}, ("replay", "b" * 64)),
        (ArtifactKind.DELIVERY_SCHEDULE, {}, ("delivery_schedules",)),
        (
            ArtifactKind.RUN,
            {"logical_run_id": "c" * 64, "execution_attempt_id": "d" * 64},
            ("runs", "c" * 64, "d" * 64),
        ),
        (ArtifactKind.FEATURE_SET, {}, ("features",)),
        (ArtifactKind.LABEL_SET, {}, ("labels",)),
        (ArtifactKind.UNIVERSE, {}, ("universes",)),
        (ArtifactKind.MODEL_BUNDLE, {}, ("models",)),
        (ArtifactKind.MODEL_SCHEDULE, {}, ("model-schedules",)),
        (ArtifactKind.PREDICTION_SET, {}, ("predictions",)),
        (ArtifactKind.STRATEGY_BUNDLE, {}, ("strategies",)),
        (ArtifactKind.SWEEP, {}, ("sweeps",)),
        (ArtifactKind.BENCHMARK, {}, ("benchmarks",)),
        (ArtifactKind.SOURCE_INSPECTION, {}, ("source-inspections",)),
    )

    for index, (kind, identity, parent_parts) in enumerate(cases):
        committed = _publish_layout_artifact(
            repository,
            kind=kind,
            identity=identity,
            label=f"case-{index}",
        )
        expected = repository.data_root.joinpath(*parent_parts)
        if kind is not ArtifactKind.RUN:
            expected /= committed.artifact_id.hex
        assert (expected / "COMMITTED").is_file()
        with repository.open_committed(committed.artifact_id) as handle:  # type: ignore[attr-defined]
            assert handle.descriptor == committed

    assert not (repository.data_root / "delivery-schedules").exists()


@pytest.mark.parametrize(
    ("kind", "identity"),
    (
        (ArtifactKind.CANONICAL_DISTRIBUTION, {}),
        (
            ArtifactKind.CANONICAL_DISTRIBUTION,
            {"logical_content_hash": f"sha256:{'a' * 64}"},
        ),
        (ArtifactKind.CANONICAL_DISTRIBUTION, {"logical_content_hash": "../escape"}),
        (ArtifactKind.REPLAY_PACK, {"snapshot_id": "A" * 64}),
        (ArtifactKind.RUN, {"logical_run_id": "c" * 64}),
        (
            ArtifactKind.RUN,
            {"logical_run_id": "c" * 64, "execution_attempt_id": "../../escape"},
        ),
    ),
)
def test_commit_rejects_missing_noncanonical_or_traversing_placement_identity(
    tmp_path: Path,
    kind: ArtifactKind,
    identity: dict[str, object],
) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=domain_digest(
                "test.invalid-local-artifact-placement.v1",
                {"identity": identity, "kind": kind.value},
            ),
        )
    )
    manifest = canonical_json_bytes({**identity, "schema": "test.invalid-placement/v1"})

    with pytest.raises(ArtifactIntegrityError, match="cannot be placed"):
        writer.commit(manifest, identity_manifest_bytes=canonical_json_bytes(identity))
    writer.abort()


def test_nested_grouping_symlink_is_rejected_before_publication(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    canonical = repository.data_root / "canonical"
    canonical.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (canonical / ("a" * 64)).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactRepositoryError, match="real directory"):
        _publish_layout_artifact(
            repository,
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            identity={"logical_content_hash": "a" * 64},
            label="symlink",
        )
    assert not tuple(outside.iterdir())


def test_case_folding_alias_cannot_replace_canonical_group_spelling(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    canonical = repository.data_root / "canonical"
    canonical.mkdir()
    alias = canonical / ("A" * 64)
    alias.mkdir()
    if not (canonical / ("a" * 64)).exists():
        pytest.skip("filesystem is case-sensitive")

    with pytest.raises(ArtifactRepositoryError, match="non-canonical on-disk spelling"):
        _publish_layout_artifact(
            repository,
            kind=ArtifactKind.CANONICAL_DISTRIBUTION,
            identity={"logical_content_hash": "a" * 64},
            label="case-alias",
        )
    assert not tuple(alias.glob("*/COMMITTED"))


def test_identity_mismatched_nested_location_is_not_authoritative(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    committed = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.CANONICAL_DISTRIBUTION,
        identity={"logical_content_hash": "a" * 64},
        label="moved",
    )
    original = repository.data_root / "canonical" / ("a" * 64) / committed.artifact_id.hex
    wrong_parent = repository.data_root / "canonical" / ("b" * 64)
    wrong_parent.mkdir()
    original.rename(wrong_parent / committed.artifact_id.hex)

    with pytest.raises(ArtifactIntegrityError, match="does not match identity"):
        repository.open_committed(committed.artifact_id)


def test_run_path_collision_quarantines_both_committed_and_incoming_trees(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    identity = {"logical_run_id": "c" * 64, "execution_attempt_id": "d" * 64}
    first = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.RUN,
        identity=identity,
        label="first",
    )

    with pytest.raises(ArtifactIntegrityError, match="different committed content"):
        _publish_layout_artifact(
            repository,
            kind=ArtifactKind.RUN,
            identity=identity,
            label="second",
        )

    final_root = repository.data_root / "runs" / ("c" * 64) / ("d" * 64)
    assert not final_root.exists()
    assert len(tuple(repository.trash_root.iterdir())) == 2
    with pytest.raises(ArtifactNotCommittedError):
        repository.open_committed(first.artifact_id)


def test_run_collision_waits_for_active_read_lease_before_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    identity = {"logical_run_id": "c" * 64, "execution_attempt_id": "d" * 64}
    first = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.RUN,
        identity=identity,
        label="first",
    )
    handle = repository.open_committed(first.artifact_id)
    exclusive_requested = Event()
    resolve_collision = (
        repository_module._LocalArtifactWriter._resolve_existing_path_under_exclusive_retention
    )

    def observe_exclusive_request(self: object, *args: object, **kwargs: object) -> object:
        exclusive_requested.set()
        return resolve_collision(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        repository_module._LocalArtifactWriter,
        "_resolve_existing_path_under_exclusive_retention",
        observe_exclusive_request,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _publish_layout_artifact,
            repository,
            kind=ArtifactKind.RUN,
            identity=identity,
            label="second",
        )
        assert exclusive_requested.wait(timeout=5)
        assert not future.done()
        with handle.open_binary("data.bin") as stream:
            assert stream.read() == b"first"
        handle.close()
        with pytest.raises(ArtifactIntegrityError, match="different committed content"):
            future.result(timeout=5)

    assert len(tuple(repository.trash_root.iterdir())) == 2


def test_duplicate_run_artifact_id_locations_fail_closed(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    committed = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.RUN,
        identity={"logical_run_id": "c" * 64, "execution_attempt_id": "d" * 64},
        label="run",
    )
    original = repository.data_root / "runs" / ("c" * 64) / ("d" * 64)
    duplicate = repository.data_root / "runs" / ("e" * 64) / ("f" * 64)
    duplicate.parent.mkdir()
    shutil.copytree(original, duplicate)

    with pytest.raises(ArtifactIntegrityError, match="more than one physical location"):
        repository.open_committed(committed.artifact_id)


def test_scanner_requires_verified_metadata_not_directory_shape(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    incomplete = repository.data_root / "replay" / ("a" * 64) / ("b" * 64)
    incomplete.mkdir(parents=True)
    assert LocalCommittedArtifactScanner(repository).scan() == ()

    (incomplete / "COMMITTED").write_bytes(b"{}")
    with pytest.raises(ArtifactNotCommittedError, match="incomplete"):
        LocalCommittedArtifactScanner(repository).scan()


def test_markerless_recovery_orphans_do_not_shadow_a_committed_artifact(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    committed = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.RUN,
        identity={"logical_run_id": "c" * 64, "execution_attempt_id": "d" * 64},
        label="run",
    )
    original = repository.data_root / "runs" / ("c" * 64) / ("d" * 64)
    orphan = repository.data_root / "runs" / ("e" * 64) / ("f" * 64)
    orphan.parent.mkdir()
    shutil.copytree(original, orphan)
    (orphan / "COMMITTED").unlink()
    malformed = repository.data_root / "runs" / ("1" * 64) / ("2" * 64)
    malformed.mkdir(parents=True)
    (malformed / "artifact.json").write_bytes(b"not-json")

    with repository.open_committed(committed.artifact_id) as handle:  # type: ignore[attr-defined]
        assert handle.descriptor == committed


def test_open_handle_rejects_nested_identity_group_symlink_substitution(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    committed = _publish_layout_artifact(
        repository,
        kind=ArtifactKind.CANONICAL_DISTRIBUTION,
        identity={"logical_content_hash": "a" * 64},
        label="canonical",
    )
    handle = repository.open_committed(committed.artifact_id)
    group = repository.data_root / "canonical" / ("a" * 64)
    moved = repository.data_root / "canonical" / "moved-group"
    group.rename(moved)
    group.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(InvalidArtifactPathError, match="symlink"):
            handle.open_binary("data.bin")
        with pytest.raises(InvalidArtifactPathError, match="symlink"):
            handle.local_path("data.bin")  # type: ignore[attr-defined]
    finally:
        handle.close()
