# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Import threading at the visible module dependency boundary.
from threading import Event

import pytest

from backtest.adapters.artifacts.localfs.repository import (
    ArtifactNotCommittedError,
    LocalArtifactRepository,
    # Close the repository import after its required symbols are visible.
)
from backtest.adapters.artifacts.localfs.retention import LocalRetentionRepository
from backtest.adapters.catalog.sqlite.retention_index import (
    SQLiteRetentionIndex,
    SQLiteRetentionRootProvider,
    # Close the retention index import after its required symbols are visible.
)
from backtest.adapters.catalog.sqlite.schema import connect
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.retention import (
    GarbageCollectionPlanStaleError,
    # Include garbage collection policy so the retention dependency remains explicit.
    GarbageCollectionPolicy,
    RetentionConflictError,
    RetentionIntegrityError,
)
from backtest.application.use_cases.manage_retention import (
    # Include acquire lease request so the manage retention dependency remains explicit.
    AcquireLeaseRequest,
    CreatePinRequest,
    ManageRetention,
    PlanGarbageCollectionRequest,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ArtifactId, ContentDigest, Identifier
from backtest.runtime.file_locks import LockUnavailableError


def _publish(
    repository: LocalArtifactRepository,
    *,
    # Keep the payload input explicit in the publish contract.
    payload: bytes,
    key: str,
    kind: ArtifactKind = ArtifactKind.SOURCE_INSPECTION,
    inputs: tuple[ArtifactId, ...] = (),
    identity: dict[str, object] | None = None,
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=kind,
            build_key=ContentDigest(key),
            input_artifact_ids=inputs,
            # Complete ArtifactDraft only after its content digest and kind inputs are visible
            # in publish.
        )
    )
    with writer.open_binary("data.bin") as stream:
        stream.write(payload)
    placement_identity = {} if identity is None else identity
    manifest = json.dumps(
        {**placement_identity, "schema_version": 1},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    identity_manifest = json.dumps(
        placement_identity,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return writer.commit(manifest, identity_manifest_bytes=identity_manifest)


# Define age as one focused operation with an explicit boundary.
def _age(
    repository: LocalArtifactRepository,
    artifact: CommittedArtifact,
    *,
    mtime_ns: int,
    # Close the age signature after its explicit inputs.
) -> None:
    # Execute the age workflow in explicit, reviewable steps.
    root = repository._find_artifact_root(artifact.artifact_id)[1]
    os.utime(root / "COMMITTED", ns=(mtime_ns, mtime_ns))


def _policy(*, grace: int = 10) -> GarbageCollectionPolicy:
    # Execute the policy workflow in explicit, reviewable steps.
    return GarbageCollectionPolicy(
        minimum_artifact_age_ns=100,
        trash_grace_period_ns=grace,
        maximum_sweep_bytes=10_000_000,
    )


# Define test atomic pin records verified transitive closure and indexes after publish as
# one focused operation with an explicit boundary.
def test_atomic_pin_records_verified_transitive_closure_and_indexes_after_publish(
    tmp_path: Path,
) -> None:
    # Execute the test atomic pin records verified transitive closure and indexes after
    # publish workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    repository = LocalArtifactRepository(data_root)
    parent = _publish(repository, payload=b"parent", key="1" * 64)
    child = _publish(
        repository,
        # Pass payload explicitly so _publish receives a reviewable 2 and snapshot input
        # in test atomic pin records verified transitive closure and indexes after
        # publish.
        payload=b"child",
        key="2" * 64,
        kind=ArtifactKind.SNAPSHOT,
        inputs=(parent.artifact_id,),
    )
    # Assemble retention once so the test atomic pin records verified transitive closure
    # and indexes after publish workflow shares one value.
    retention = LocalRetentionRepository(repository)
    database = data_root / "catalog" / "catalog.sqlite"
    now = [12]
    manager = ManageRetention(
        retention,
        # Keep the database SQLiteRetentionIndex step visible while building manager.
        SQLiteRetentionIndex(database, clock_ns=lambda: 13),
        SQLiteRetentionRootProvider(database),
        policy=_policy(),
        clock_ns=lambda: now[0],
    )

    # Assemble pin once so the test atomic pin records verified transitive closure and
    # indexes after publish workflow shares one value.
    pin = manager.create_pin(
        CreatePinRequest(
            pin_id=Identifier("research-baseline"),
            roots=(child.artifact_id,),
            reason="approved reproducible baseline",
            # Complete CreatePinRequest only after its research-baseline and approved
            # reproducible baseline inputs are visible in test atomic pin records verified
            # transitive closure and indexes after publish.
        )
    )

    assert pin.roots == (child.artifact_id,)
    assert pin.transitive_closure == tuple(
        sorted((parent.artifact_id, child.artifact_id), key=lambda item: item.hex)
        # Complete tuple only after its artifact id and hex inputs are visible in test atomic
        # pin records verified transitive closure and indexes after publish.
    )
    assert retention.active_pins() == (pin,)
    payload = (data_root / "pins" / "research-baseline.json").read_bytes()
    assert (
        payload
        # Keep the json expectation tied to payload, encode and dumps in this scenario.
        == json.dumps(
            json.loads(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            # Pass separators explicitly into encode within test atomic pin records
            # verified transitive closure and indexes after publish.
            separators=(",", ":"),
        ).encode()
    )
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Perform the protected test atomic pin records verified transitive closure and
        # indexes after publish operation before explicit failure handling.
        row = connection.execute(
            "SELECT status, record_digest FROM pins WHERE pin_id = 'research-baseline'"
        ).fetchone()
    finally:
        connection.close()
    # Verify row is not None before this scenario is accepted.
    assert row is not None
    assert (str(row["status"]), str(row["record_digest"])) == (
        "ACTIVE",
        pin.record_digest.hex,
    )
    # Invoke rebuild_pin_index as a visible step within the test atomic pin records
    # verified transitive closure and indexes after publish workflow.
    manager.rebuild_pin_index()
    lease = manager.acquire_lease(
        AcquireLeaseRequest(
            lease_id=Identifier("read-drill"),
            roots=(child.artifact_id,),
            # Pass reason explicitly so AcquireLeaseRequest receives a reviewable read-
            # drill and verify use-case boundary input in test atomic pin records verified
            # transitive closure and indexes after publish.
            reason="verify use-case boundary",
        )
    )
    lease.close()
    plan = manager.plan_garbage_collection(PlanGarbageCollectionRequest())
    # Assemble batch once so the test atomic pin records verified transitive closure and
    # indexes after publish workflow shares one value.
    batch = manager.execute_garbage_collection(plan)
    now[0] = batch.purge_not_before_ns
    assert manager.purge_trash(batch.batch_id).artifact_ids == ()


def test_pin_is_idempotent_but_conflicting_identity_is_rejected(tmp_path: Path) -> None:
    # Execute the test pin is idempotent but conflicting identity is rejected workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"one", key="1" * 64)
    other = _publish(repository, payload=b"two", key="2" * 64)
    retention = LocalRetentionRepository(repository)

    first = retention.create_pin(
        # Keep the keep Identifier step visible while building first.
        pin_id=Identifier("keep"),
        roots=(artifact.artifact_id,),
        reason="audit",
        created_at_ns=1,
    )

    # Verify the first, create pin and retention relationship before this scenario is
    # accepted.
    assert (
        retention.create_pin(
            pin_id=Identifier("keep"),
            roots=(artifact.artifact_id,),
            reason="audit",
            # Pass created at ns explicitly so create_pin receives a reviewable keep and
            # audit input in test pin is idempotent but conflicting identity is rejected.
            created_at_ns=1,
        )
        == first
    )
    with pytest.raises(RetentionConflictError, match="different"):
        # Keep raises, retention conflict error and pytest active only for the bounded
        # test pin is idempotent but conflicting identity is rejected operation.
        retention.create_pin(
            pin_id=Identifier("keep"),
            roots=(other.artifact_id,),
            reason="audit",
            created_at_ns=1,
            # Complete create_pin only after its keep and audit inputs are visible in test pin
            # is idempotent but conflicting identity is rejected.
        )


def test_pin_is_not_acknowledged_before_parent_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test pin is not acknowledged before parent directory fsync workflow in
    # explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import safe_io

    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"one", key="1" * 64)
    retention = LocalRetentionRepository(repository)
    directory_fsync = safe_io.fsync_directory
    # Assemble failed once so the test pin is not acknowledged before parent directory
    # fsync workflow shares one value.
    failed = False

    def fail_first_pin_fsync(path: Path) -> None:
        # Execute the fail first pin fsync workflow in explicit, reviewable steps.
        nonlocal failed
        if path.name == "pins" and not failed and (path / "keep.json").exists():
            # Handle the fail first pin fsync name, pins and failed condition as a
            # distinct block.
            failed = True
            raise OSError("injected pin directory fsync failure")
        directory_fsync(path)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test pin is not
        # acknowledged before parent directory fsync operation.
        context.setattr(safe_io, "fsync_directory", fail_first_pin_fsync)
        with pytest.raises(OSError, match="pin directory fsync"):
            # Keep raises, oserror and pytest active only for the bounded test pin is not
            # acknowledged before parent directory fsync operation.
            retention.create_pin(
                pin_id=Identifier("keep"),
                roots=(artifact.artifact_id,),
                reason="audit",
                created_at_ns=1,
                # Complete create_pin only after its keep and audit inputs are visible in test
                # pin is not acknowledged before parent directory fsync.
            )

    # The interrupted call returned no acknowledgement.  If the atomic link
    # did reach the filesystem, recovery can verify it and retry idempotently.
    recovered = retention.active_pins()
    assert len(recovered) == 1
    assert (
        retention.create_pin(
            pin_id=Identifier("keep"),
            # Pass roots explicitly so create_pin receives a reviewable keep and audit
            # input in test pin is not acknowledged before parent directory fsync.
            roots=(artifact.artifact_id,),
            reason="audit",
            created_at_ns=1,
        )
        == recovered[0]
        # Verify the create pin, recovered and retention relationship before this scenario is
        # accepted.
    )


def test_pin_remains_authoritative_if_rebuildable_index_update_fails(tmp_path: Path) -> None:
    # Execute the test pin remains authoritative if rebuildable index update fails
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"one", key="1" * 64)
    retention = LocalRetentionRepository(repository)

    # Keep the rejecting index contract and validation rules together.
    class RejectingIndex:
        def index_active(self, pin: object) -> None:
            # Execute the rejecting index index active workflow in explicit, reviewable
            # steps.
            del pin
            raise RuntimeError("injected index outage")

        def index_retired(self, pin: object) -> None:
            del pin

        def rebuild(self, active_pins: object) -> None:
            # Discard active_pins after its boundary-only use.
            del active_pins

    manager = ManageRetention(
        retention,
        RejectingIndex(),  # type: ignore[arg-type]
        SQLiteRetentionRootProvider(repository.data_root / "catalog" / "catalog.sqlite"),
        policy=_policy(),
        clock_ns=lambda: 1,
    )

    with pytest.raises(RuntimeError, match="index outage"):
        # Invoke create_pin for audit and keep as a visible test pin remains authoritative
        # if rebuildable index update fails step.
        manager.create_pin(CreatePinRequest(Identifier("keep"), (artifact.artifact_id,), "audit"))

    assert retention.active_pins()[0].pin_id == Identifier("keep")


def test_retiring_pin_moves_it_to_retained_namespace_and_updates_projection(
    tmp_path: Path,
) -> None:
    # Execute the test retiring pin moves it to retained namespace and updates projection
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "var"
    repository = LocalArtifactRepository(data_root)
    artifact = _publish(repository, payload=b"one", key="1" * 64)
    retention = LocalRetentionRepository(repository)
    index = SQLiteRetentionIndex(data_root / "catalog" / "catalog.sqlite")
    # Assemble manager once so the test retiring pin moves it to retained namespace and
    # updates projection workflow shares one value.
    manager = ManageRetention(
        retention,
        index,
        SQLiteRetentionRootProvider(data_root / "catalog" / "catalog.sqlite"),
        policy=_policy(),
        # Pass clock ns explicitly so ManageRetention receives a reviewable sqlite and
        # catalog input in test retiring pin moves it to retained namespace and updates
        # projection.
        clock_ns=lambda: 20,
    )
    pin = manager.create_pin(CreatePinRequest(Identifier("keep"), (artifact.artifact_id,), "audit"))

    assert manager.retire_pin(Identifier("keep")) == pin
    assert manager.retire_pin(Identifier("keep")) == pin

    # Verify retention.active_pins() == () before this scenario is accepted.
    assert retention.active_pins() == ()
    assert not (data_root / "pins" / "keep.json").exists()
    retired = tuple((data_root / "pins" / "retired").glob("keep-*.json"))
    assert len(retired) == 1
    connection = connect(data_root / "catalog" / "catalog.sqlite", busy_timeout_seconds=1.0)
    # Keep expected failures inside the test retiring pin moves it to retained namespace
    # and updates projection error boundary.
    try:
        status = connection.execute("SELECT status FROM pins WHERE pin_id = 'keep'").fetchone()
    finally:
        connection.close()
    assert status is not None and str(status["status"]) == "RETIRED"
    # Acquire raises, retention conflict error and pytest at an explicit test retiring pin
    # moves it to retained namespace and updates projection context boundary so cleanup
    # remains scoped.
    with pytest.raises(RetentionConflictError, match="cannot be reused"):
        # Keep raises, retention conflict error and pytest active only for the bounded
        # test retiring pin moves it to retained namespace and updates projection
        # operation.
        retention.create_pin(
            pin_id=Identifier("keep"),
            roots=(artifact.artifact_id,),
            reason="attempted resurrection",
            created_at_ns=21,
            # Complete create_pin only after its keep and attempted resurrection inputs are
            # visible in test retiring pin moves it to retained namespace and updates
            # projection.
        )


def test_mark_phase_protects_pins_retained_roots_and_young_descendant_lineage(
    tmp_path: Path,
) -> None:
    # Execute the test mark phase protects pins retained roots and young descendant
    # lineage workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    parent = _publish(repository, payload=b"parent", key="1" * 64)
    child = _publish(
        repository,
        payload=b"child",
        # Pass key explicitly so _publish receives a reviewable 2 and snapshot input in
        # test mark phase protects pins retained roots and young descendant lineage.
        key="2" * 64,
        kind=ArtifactKind.SNAPSHOT,
        inputs=(parent.artifact_id,),
    )
    _age(repository, parent, mtime_ns=0)
    # Invoke _age for repository and child as a visible test mark phase protects pins
    # retained roots and young descendant lineage step.
    _age(repository, child, mtime_ns=200)
    retention = LocalRetentionRepository(repository)

    young_plan = retention.plan_garbage_collection(
        retained_roots=(),
        policy=_policy(),
        # Pass now ns explicitly so plan_garbage_collection receives a reviewable policy
        # input in test mark phase protects pins retained roots and young descendant
        # lineage.
        now_ns=250,
    )
    assert young_plan.candidates == ()

    retained_plan = retention.plan_garbage_collection(
        retained_roots=(child.artifact_id,),
        # Keep the policy _policy step visible while building retained plan.
        policy=_policy(),
        now_ns=400,
    )
    assert retained_plan.candidates == ()

    retention.create_pin(
        # Pass pin id explicitly to create_pin for keep-child and replay.
        pin_id=Identifier("keep-child"),
        roots=(child.artifact_id,),
        reason="replay",
        created_at_ns=300,
    )
    # Assemble pinned plan once so the test mark phase protects pins retained roots and
    # young descendant lineage workflow shares one value.
    pinned_plan = retention.plan_garbage_collection(
        retained_roots=(),
        policy=_policy(),
        now_ns=400,
    )
    # Verify pinned_plan.candidates == () before this scenario is accepted.
    assert pinned_plan.candidates == ()


def test_active_lease_blocks_exclusive_sweep(tmp_path: Path) -> None:
    # Execute the test active lease blocks exclusive sweep workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository, exclusive_lock_timeout_seconds=0)
    plan = retention.plan_garbage_collection(
        # Pass retained roots explicitly so plan_garbage_collection receives a reviewable
        # policy input in test active lease blocks exclusive sweep.
        retained_roots=(),
        policy=_policy(),
        now_ns=200,
    )
    lease = retention.acquire_lease(
        # Keep the running-job Identifier step visible while building lease.
        lease_id=Identifier("running-job"),
        roots=(artifact.artifact_id,),
        reason="active backtest input",
    )
    try:
        # Perform the protected test active lease blocks exclusive sweep operation before
        # explicit failure handling.
        with pytest.raises(LockUnavailableError):
            retention.execute_garbage_collection(plan, now_ns=201)
    finally:
        lease.close()


def test_concurrent_run_publication_blocks_gc_then_invalidates_its_old_plan(
    # Keep the tmp path input explicit in the test concurrent run publication blocks gc
    # then invalidates its old plan contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test concurrent run publication blocks gc then invalidates its old plan
    # workflow in explicit, reviewable steps.
    from backtest.adapters.artifacts.localfs import repository as repository_module

    repository = LocalArtifactRepository(tmp_path / "var")
    parent = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, parent, mtime_ns=0)
    retention = LocalRetentionRepository(repository, exclusive_lock_timeout_seconds=0)
    # Assemble plan once so the test concurrent run publication blocks gc then invalidates
    # its old plan workflow shares one value.
    plan = retention.plan_garbage_collection(
        retained_roots=(),
        policy=_policy(),
        now_ns=200,
    )
    # Assemble writer once so the test concurrent run publication blocks gc then
    # invalidates its old plan workflow shares one value.
    writer = repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.RUN,
            build_key=ContentDigest("2" * 64),
            input_artifact_ids=(parent.artifact_id,),
            # Complete ArtifactDraft only after its 2 and run inputs are visible in test
            # concurrent run publication blocks gc then invalidates its old plan.
        )
    )
    with writer.open_binary("result.bin") as stream:
        stream.write(b"new successful run")
    marker_reached = Event()
    # Assemble release marker once so the test concurrent run publication blocks gc then
    # invalidates its old plan workflow shares one value.
    release_marker = Event()
    durable_write = repository_module._write_durable_exclusive

    def pause_at_marker(path: Path, payload: bytes) -> None:
        # Execute the pause at marker workflow in explicit, reviewable steps.
        if path.name.startswith(".COMMITTED.tmp-"):
            # Handle the pause at marker startswith, name and path condition as a distinct
            # block.
            marker_reached.set()
            if not release_marker.wait(timeout=5):
                raise TimeoutError("publication race fixture timed out")
        durable_write(path, payload)

    with monkeypatch.context() as context:
        # Keep context and monkeypatch active only for the bounded test concurrent run
        # publication blocks gc then invalidates its old plan operation.
        context.setattr(repository_module, "_write_durable_exclusive", pause_at_marker)
        with ThreadPoolExecutor(max_workers=1) as pool:
            # Keep thread pool executor active only for the bounded test concurrent run
            # publication blocks gc then invalidates its old plan operation.
            future = pool.submit(
                writer.commit,
                json.dumps(
                    {
                        "execution_attempt_id": "4" * 64,
                        "logical_run_id": "3" * 64,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode(),
            )
            assert marker_reached.wait(timeout=5)
            with pytest.raises(LockUnavailableError):
                retention.execute_garbage_collection(plan, now_ns=201)
            release_marker.set()
            # Assemble run once so the test concurrent run publication blocks gc then
            # invalidates its old plan workflow shares one value.
            run = future.result(timeout=5)

    with pytest.raises(GarbageCollectionPlanStaleError):
        retention.execute_garbage_collection(plan, now_ns=202)
    with repository.open_committed(parent.artifact_id) as parent_handle:  # type: ignore[attr-defined]
        assert parent_handle.descriptor == parent
    with repository.open_committed(run.artifact_id) as run_handle:  # type: ignore[attr-defined]
        assert run_handle.descriptor == run


def test_use_case_rejects_plan_from_a_different_host_policy(tmp_path: Path) -> None:
    # Execute the test use case rejects plan from a different host policy workflow in
    # explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    retention = LocalRetentionRepository(repository)
    configured = _policy()
    manager = ManageRetention(
        retention,
        # Keep the sqlite retention index and sqlite SQLiteRetentionIndex step visible
        # while building manager.
        SQLiteRetentionIndex(repository.data_root / "catalog" / "catalog.sqlite"),
        SQLiteRetentionRootProvider(repository.data_root / "catalog" / "catalog.sqlite"),
        policy=configured,
        clock_ns=lambda: 200,
    )
    # Assemble weaker once so the test use case rejects plan from a different host policy
    # workflow shares one value.
    weaker = GarbageCollectionPolicy(
        minimum_artifact_age_ns=0,
        trash_grace_period_ns=0,
        maximum_sweep_bytes=configured.maximum_sweep_bytes,
    )
    # Assemble forged once so the test use case rejects plan from a different host policy
    # workflow shares one value.
    forged = retention.plan_garbage_collection(
        retained_roots=(),
        policy=weaker,
        now_ns=200,
    )

    # Acquire raises, value error and pytest at an explicit test use case rejects plan
    # from a different host policy context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="host retention policy"):
        manager.execute_garbage_collection(forged)


def test_request_cannot_omit_host_owned_retained_roots(tmp_path: Path) -> None:
    # Execute the test request cannot omit host owned retained roots workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"successful run", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)

    # Keep the fixed roots contract and validation rules together.
    class FixedRoots:
        def retained_roots(self) -> tuple[ArtifactId, ...]:
            return (artifact.artifact_id,)

    manager = ManageRetention(
        retention,
        # Keep the sqlite retention index and sqlite SQLiteRetentionIndex step visible
        # while building manager.
        SQLiteRetentionIndex(repository.data_root / "catalog" / "catalog.sqlite"),
        FixedRoots(),
        policy=_policy(),
        clock_ns=lambda: 200,
    )

    # Assemble plan once so the test request cannot omit host owned retained roots
    # workflow shares one value.
    plan = manager.plan_garbage_collection(PlanGarbageCollectionRequest())

    assert plan.retained_roots == (artifact.artifact_id,)
    assert plan.candidates == ()


def test_new_host_root_after_dry_run_makes_plan_stale(tmp_path: Path) -> None:
    # Execute the test new host root after dry run makes plan stale workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"successful later", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)

    # Keep the mutable roots contract and validation rules together.
    class MutableRoots:
        roots: tuple[ArtifactId, ...] = ()

        def retained_roots(self) -> tuple[ArtifactId, ...]:
            return self.roots

    roots = MutableRoots()
    # Assemble manager once so the test new host root after dry run makes plan stale
    # workflow shares one value.
    manager = ManageRetention(
        retention,
        SQLiteRetentionIndex(repository.data_root / "catalog" / "catalog.sqlite"),
        roots,
        policy=_policy(),
        # Pass clock ns explicitly so ManageRetention receives a reviewable sqlite and
        # catalog input in test new host root after dry run makes plan stale.
        clock_ns=lambda: 200,
    )
    plan = manager.plan_garbage_collection(PlanGarbageCollectionRequest())
    roots.roots = (artifact.artifact_id,)

    with pytest.raises(GarbageCollectionPlanStaleError, match="host-retained"):
        # Invoke execute_garbage_collection for plan as a visible test new host root after
        # dry run makes plan stale step.
        manager.execute_garbage_collection(plan)


def test_pin_created_after_dry_run_makes_plan_stale(tmp_path: Path) -> None:
    # Execute the test pin created after dry run makes plan stale workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)
    plan = retention.plan_garbage_collection(
        # Pass retained roots explicitly so plan_garbage_collection receives a reviewable
        # policy input in test pin created after dry run makes plan stale.
        retained_roots=(),
        policy=_policy(),
        now_ns=200,
    )
    retention.create_pin(
        # Pass pin id explicitly to create_pin for late-pin and approved after dry run.
        pin_id=Identifier("late-pin"),
        roots=(artifact.artifact_id,),
        reason="approved after dry run",
        created_at_ns=201,
    )

    # Acquire raises, garbage collection plan stale error and pytest at an explicit test
    # pin created after dry run makes plan stale context boundary so cleanup remains
    # scoped.
    with pytest.raises(GarbageCollectionPlanStaleError):
        retention.execute_garbage_collection(plan, now_ns=202)
    handle = repository.open_committed(artifact.artifact_id)
    try:
        assert handle.descriptor == artifact
    # Complete the required cleanup regardless of the protected outcome.
    finally:
        handle.close()


def test_young_dependent_published_after_dry_run_protects_candidate_lineage(
    tmp_path: Path,
) -> None:
    # Execute the test young dependent published after dry run protects candidate lineage
    # workflow in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    parent = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, parent, mtime_ns=0)
    retention = LocalRetentionRepository(repository)
    plan = retention.plan_garbage_collection(
        # Pass retained roots explicitly so plan_garbage_collection receives a reviewable
        # policy input in test young dependent published after dry run protects candidate
        # lineage.
        retained_roots=(),
        policy=_policy(),
        now_ns=200,
    )
    _publish(
        # Pass repository explicitly so _publish receives a reviewable 2 and snapshot
        # input in test young dependent published after dry run protects candidate
        # lineage.
        repository,
        payload=b"new child",
        key="2" * 64,
        kind=ArtifactKind.SNAPSHOT,
        inputs=(parent.artifact_id,),
        # Complete _publish only after its 2 and snapshot inputs are visible in test young
        # dependent published after dry run protects candidate lineage.
    )

    with pytest.raises(GarbageCollectionPlanStaleError):
        retention.execute_garbage_collection(plan, now_ns=201)
    handle = repository.open_committed(parent.artifact_id)
    handle.close()


# Define test sweep only moves to trash then verified purge honors grace as one focused
# operation with an explicit boundary.
def test_sweep_only_moves_to_trash_then_verified_purge_honors_grace(
    tmp_path: Path,
) -> None:
    # Execute the test sweep only moves to trash then verified purge honors grace workflow
    # in explicit, reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)
    plan = retention.plan_garbage_collection(
        # Pass retained roots explicitly so plan_garbage_collection receives a reviewable
        # policy input in test sweep only moves to trash then verified purge honors grace.
        retained_roots=(),
        policy=_policy(grace=10),
        now_ns=200,
    )
    assert tuple(item.artifact_id for item in plan.candidates) == (artifact.artifact_id,)

    # Assemble batch once so the test sweep only moves to trash then verified purge honors
    # grace workflow shares one value.
    batch = retention.execute_garbage_collection(plan, now_ns=201)

    with pytest.raises(ArtifactNotCommittedError):
        repository.open_committed(artifact.artifact_id)
    batch_root = repository.data_root / "trash" / "gc-batches" / batch.batch_id.hex
    assert (batch_root / "COMMITTED").is_file()
    # Acquire raises, retention conflict error and pytest at an explicit test sweep only
    # moves to trash then verified purge honors grace context boundary so cleanup remains
    # scoped.
    with pytest.raises(RetentionConflictError, match="grace"):
        retention.purge_trash(batch.batch_id, now_ns=210)
    receipt = retention.purge_trash(batch.batch_id, now_ns=211)
    assert receipt.artifact_ids == (artifact.artifact_id,)
    assert receipt.deleted_bytes > 0
    # Verify not batch_root.exists() before this scenario is accepted.
    assert not batch_root.exists()
    assert retention.purge_trash(batch.batch_id, now_ns=999) == receipt


def test_gc_discovers_and_sweeps_nested_canonical_artifact(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "var")
    logical_content_hash = "a" * 64
    artifact = _publish(
        repository,
        payload=b"nested canonical",
        key="1" * 64,
        kind=ArtifactKind.CANONICAL_DISTRIBUTION,
        identity={"logical_content_hash": logical_content_hash},
    )
    root = repository.data_root / "canonical" / logical_content_hash / artifact.artifact_id.hex
    assert (root / "COMMITTED").is_file()
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)
    plan = retention.plan_garbage_collection(
        retained_roots=(),
        policy=_policy(grace=0),
        now_ns=200,
    )
    assert tuple(item.artifact_id for item in plan.candidates) == (artifact.artifact_id,)

    batch = retention.execute_garbage_collection(plan, now_ns=201)

    assert not root.exists()
    trashed = (
        repository.data_root
        / "trash"
        / "gc-batches"
        / batch.batch_id.hex
        / "artifacts"
        / ArtifactKind.CANONICAL_DISTRIBUTION.value
        / artifact.artifact_id.hex
    )
    assert (trashed / "COMMITTED").is_file()
    receipt = retention.purge_trash(batch.batch_id, now_ns=201)
    assert receipt.artifact_ids == (artifact.artifact_id,)


def test_corrupt_or_symlinked_pin_fails_gc_closed(tmp_path: Path) -> None:
    # Execute the test corrupt or symlinked pin fails gc closed workflow in explicit,
    # reviewable steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _publish(repository, payload=b"old", key="1" * 64)
    _age(repository, artifact, mtime_ns=0)
    retention = LocalRetentionRepository(repository)
    outside = tmp_path / "outside.json"
    # Invoke write_text for {} as a visible test corrupt or symlinked pin fails gc closed
    # step.
    outside.write_text("{}")
    (repository.data_root / "pins" / "evil.json").symlink_to(outside)

    with pytest.raises(RetentionIntegrityError):
        # Keep raises, retention integrity error and pytest active only for the bounded
        # test corrupt or symlinked pin fails gc closed operation.
        retention.plan_garbage_collection(
            retained_roots=(),
            policy=_policy(),
            now_ns=200,
        )


# Define test pin with newer schema fails closed as one focused operation with an explicit
# boundary.
def test_pin_with_newer_schema_fails_closed(tmp_path: Path) -> None:
    # Execute the test pin with newer schema fails closed workflow in explicit, reviewable
    # steps.
    repository = LocalArtifactRepository(tmp_path / "var")
    retention = LocalRetentionRepository(repository)
    path = repository.data_root / "pins" / "future.json"
    path.write_text(
        json.dumps(
            # Open the future and created at ns payload explicitly for dumps within test
            # pin with newer schema fails closed.
            {
                "created_at_ns": 0,
                "pin_id": "future",
                "reason": "future",
                "record_digest": "0" * 64,
                # Keep roots named so the future and created at ns payload passed to dumps
                # remains self-describing within test pin with newer schema fails closed.
                "roots": ["1" * 64],
                "transitive_closure": ["1" * 64],
                "version": 2,
            },
            separators=(",", ":"),
            # Pass sort keys explicitly so dumps receives a reviewable future and created
            # at ns input in test pin with newer schema fails closed.
            sort_keys=True,
        )
    )

    with pytest.raises(RetentionIntegrityError, match="unsupported"):
        retention.active_pins()
