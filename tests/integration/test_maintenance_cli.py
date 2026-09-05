# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

# Import types at the visible module dependency boundary.
from types import SimpleNamespace
from typing import cast

import pytest
from typer.testing import CliRunner

import backtest.bootstrap.cli as cli_module
from backtest.adapters.artifacts.localfs import LocalCommittedArtifactScanner
from backtest.adapters.artifacts.localfs import repository as repository_module
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.schema import connect

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.run_results import (
    RunBackend,
    RunPhysicalSettings,
    # Include successful run manifest so the run results dependency remains explicit.
    SuccessfulRunManifest,
)
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.application.use_cases.manage_retention import CreatePinRequest

# Import query artifacts at the visible module dependency boundary.
from backtest.application.use_cases.query_artifacts import ArtifactQueryError, QueryArtifacts
from backtest.application.use_cases.query_runs import QueryRuns, RunIndexQueryError
from backtest.bootstrap.catalog_reconciliation import LocalArtifactCatalogReconciler
from backtest.bootstrap.cli import RuntimeCliBackend, app, build_cli_backend
from backtest.bootstrap.config import (
    BackupSettings,
    # Include path settings so the config dependency remains explicit.
    PathSettings,
    RetentionSettings,
    Settings,
)
from backtest.bootstrap.container import RuntimeContainer

# Import maintenance at the visible module dependency boundary.
from backtest.bootstrap.maintenance import build_maintenance_services
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    AssetId,
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    Identifier,
    LogicalContentHash,
    RuntimeLockId,
    # Include snapshot id so the identifiers dependency remains explicit.
    SnapshotId,
)
from backtest.engine.reference import RunSummary
from backtest.interfaces.cli import create_cli


# Keep the factory contract and validation rules together.
class _Factory:
    def __init__(self, backend: RuntimeCliBackend) -> None:
        # Execute the factory init workflow in explicit, reviewable steps.
        self._backend = backend
        self.calls: list[bool] = []

    def __call__(
        self,
        config_path: Path,
        # Keep the capabilities file input explicit in the call contract.
        capabilities_file: Path | None,
        *,
        require_capabilities: bool = False,
        prefer_running_controller: bool = False,
    ) -> RuntimeCliBackend:
        # Execute the factory call workflow in explicit, reviewable steps.
        del config_path, capabilities_file, require_capabilities
        self.calls.append(prefer_running_controller)
        return self._backend


def _publish(
    repository: LocalArtifactRepository,
    # Close the publish signature after its explicit inputs.
    *,
    label: str,
    kind: ArtifactKind,
    inputs: tuple[ArtifactId, ...] = (),
    manifest: bytes | None = None,
    # Keep the committed artifact input explicit in the publish contract.
) -> CommittedArtifact:
    # Execute the publish workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind,
            domain_digest("test.maintenance-cli.build.v1", {"label": label}),
            inputs,
            # Complete ArtifactDraft only after its v1 and label inputs are visible in
            # publish.
        )
    )
    with writer.open_binary("payload.bin") as stream:
        stream.write(label.encode())
    if manifest is None:
        document: dict[str, object] = {"artifact_schema": f"test-{label}/v1"}
        if kind is ArtifactKind.RUN:
            document.update(
                {
                    "execution_attempt_id": domain_digest(
                        "test.maintenance-cli-attempt.v1", {"label": label}
                    ).hex,
                    "logical_run_id": domain_digest(
                        "test.maintenance-cli-logical-run.v1", {"label": label}
                    ).hex,
                }
            )
        selected_manifest = canonical_json_bytes(document)
    else:
        selected_manifest = manifest
    # Return the completed publish result without a hidden fallback.
    return writer.commit(selected_manifest, identity_manifest_bytes=selected_manifest)


def _backend(
    tmp_path: Path,
    clock: list[int],
    *,
    # Keep the backup configured input explicit in the backend contract.
    backup_configured: bool = True,
) -> tuple[RuntimeCliBackend, LocalArtifactRepository, SQLiteArtifactCatalog, Path, Path]:
    # Execute the backend workflow in explicit, reviewable steps.
    data_root = tmp_path / "live"
    backup_root = tmp_path / "backup-device"
    restore_parent = tmp_path / "restore-drills"
    restore_parent.mkdir()
    settings = Settings(
        # Keep the path settings and data root PathSettings step visible while building
        # settings.
        paths=PathSettings(data_root=data_root),
        retention=RetentionSettings(
            minimum_artifact_age_seconds=0,
            trash_grace_seconds=10,
            maximum_sweep_gb=1,
            # Complete RetentionSettings only after its declared inputs are visible in
            # backend.
        ),
        backup=(
            BackupSettings(
                target_root=backup_root,
                restore_verify_parent=restore_parent,
                # Pass allow same device for drill explicitly so BackupSettings receives a
                # reviewable backup root and restore parent input in backend.
                allow_same_device_for_drill=True,
            )
            if backup_configured
            else BackupSettings()
        ),
        # Complete Settings only after its path settings and retention settings inputs are
        # visible in backend.
    )
    artifacts = LocalArtifactRepository(data_root)
    catalog = SQLiteArtifactCatalog(data_root / "catalog" / "catalog.sqlite", artifacts)
    maintenance = build_maintenance_services(
        settings,
        # Pass artifacts explicitly so build_maintenance_services receives a reviewable
        # settings and artifacts input in backend.
        artifacts,
        clock_ns=lambda: clock[0],
    )
    queries = QueryArtifacts(catalog, artifacts)
    container = SimpleNamespace(
        # Pass artifacts explicitly so SimpleNamespace receives a reviewable simple
        # namespace and query runs input in backend.
        artifacts=artifacts,
        catalog=catalog,
        control=SimpleNamespace(
            query_artifacts=queries,
            # The real catalog supplies both artifact authority checks and Run ordering.
            query_runs=QueryRuns(queries, catalog),
            # Pass retry job explicitly so SimpleNamespace receives a reviewable query
            # runs and queries input in backend.
            retry_job=None,
        ),
        maintenance=maintenance,
        settings=settings,
    )
    # Return the completed backend result without a hidden fallback.
    return (
        RuntimeCliBackend(cast(RuntimeContainer, container)),
        artifacts,
        catalog,
        backup_root,
        # Include restore parent in the completed backend result.
        restore_parent,
    )


def _restart_with_clean_cache_probe(
    original_backend: RuntimeCliBackend,
    artifacts: LocalArtifactRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RuntimeCliBackend, LocalArtifactRepository, list[Path]]:
    """Open new adapters, reconcile a clean receipt, and count payload hashes."""

    restarted_artifacts = LocalArtifactRepository(artifacts.data_root)
    database = artifacts.data_root / "catalog" / "catalog.sqlite"
    restarted_catalog = SQLiteArtifactCatalog(database, restarted_artifacts)
    queries = QueryArtifacts(restarted_catalog, restarted_artifacts)
    restarted_container = SimpleNamespace(
        artifacts=restarted_artifacts,
        catalog=restarted_catalog,
        control=SimpleNamespace(
            query_artifacts=queries,
            query_runs=QueryRuns(queries, restarted_catalog),
        ),
        settings=original_backend.container.settings,
    )
    original_hash = repository_module._sha256_file
    hashed_paths: list[Path] = []

    def observe_hash(path: Path) -> tuple[str, int]:
        # Preserve real verification while measuring every expensive payload read.
        hashed_paths.append(path)
        return original_hash(path)

    monkeypatch.setattr(repository_module, "_sha256_file", observe_hash)
    LocalArtifactCatalogReconciler(
        restarted_artifacts,
        restarted_catalog,
    ).reconcile_once()
    return (
        RuntimeCliBackend(cast(RuntimeContainer, restarted_container)),
        restarted_artifacts,
        hashed_paths,
    )


def _publish_run(
    artifacts: LocalArtifactRepository,
    catalog: SQLiteArtifactCatalog,
    *,
    run_label: str = "run",
    attempt_character: str = "8",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> tuple[CommittedArtifact, CommittedArtifact]:
    # Execute the publish run workflow in explicit, reviewable steps.
    source = _publish(
        artifacts,
        label="source",
        kind=ArtifactKind.SOURCE_INSPECTION,
    )
    # Assemble spec once so the publish run workflow shares one value.
    spec = _run_spec()
    physical = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1)
    nonce = ContentDigest(attempt_character * 64)
    components = {item.role: item for item in spec.components}
    selected_start = datetime(2026, 1, 1, tzinfo=UTC) if started_at is None else started_at
    selected_completion = (
        datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC) if completed_at is None else completed_at
    )
    manifest = SuccessfulRunManifest(
        # Pass resolved spec explicitly into manifest_bytes within publish run.
        resolved_spec=spec,
        attempt_nonce=nonce,
        execution_attempt_id=spec.execution_attempt_id(nonce, physical.identity_digest),
        input_artifact_ids=(source.artifact_id,),
        summary=RunSummary(
            # Pass dataset logical content hash explicitly so RunSummary receives a
            # reviewable engine and latency input in publish run.
            dataset_logical_content_hash=spec.logical_content_hash,
            replay_semantics_id=spec.replay_semantics_id,
            engine_bundle_id=components["engine"].bundle_id,
            latency_bundle_id=components["latency"].bundle_id,
            historical_group_count=2,
            # Pass historical event count explicitly so RunSummary receives a reviewable
            # engine and latency input in publish run.
            historical_event_count=2,
            delivered_event_count=2,
            accepted_order_count=1,
            rejected_order_count=0,
            filled_order_count=1,
            # Pass failed order count explicitly so RunSummary receives a reviewable
            # engine and latency input in publish run.
            failed_order_count=0,
            ledger_transaction_count=2,
            fill_count=1,
            audit_hash=ContentDigest("d" * 64),
            ledger_hash=ContentDigest("e" * 64),
            # Keep the content digest and f ContentDigest step visible while building
            # manifest.
            fill_hash=ContentDigest("f" * 64),
            result_hash=ContentDigest("c" * 64),
            final_balances=(("portfolio", "available", "SOL", 900),),
        ),
        physical_settings=physical,
        # Keep the datetime and utc datetime step visible while building manifest.
        started_at=selected_start,
        completed_at=selected_completion,
    ).manifest_bytes()
    run = _publish(
        artifacts,
        # Pass label explicitly so _publish receives a reviewable run and artifact id
        # input in publish run.
        label=run_label,
        kind=ArtifactKind.RUN,
        inputs=(source.artifact_id,),
        manifest=manifest,
    )
    # Invoke index_committed for source as a visible publish run step.
    catalog.index_committed(source)
    catalog.index_committed(run)
    return source, run


def _run_spec() -> ResolvedRunSpec:
    # Execute the run spec workflow in explicit, reviewable steps.
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
            # Pass role explicitly so create receives a reviewable v1 and role input in
            # run spec.
            role=role,
            bundle_id=BundleId(domain_digest("test.maintenance-cli.bundle.v1", {"role": role}).hex),
            config=(
                ExactInferencePolicy.disabled().document()
                if role == "inference"
                # Route all remaining cases through the explicit alternative branch.
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
        )
        # Pass role explicitly so tuple receives a reviewable inference and v1 input in
        # run spec.
        for role in roles
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Include dataset revision id in the completed run spec result.
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        # Pass components explicitly so create receives a reviewable 1 and 2 input in run
        # spec.
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=1,
    )


# Define test verified artifact run and lineage cli use exact application queries as one
# focused operation with an explicit boundary.
def test_verified_artifact_run_and_lineage_cli_use_exact_application_queries(
    tmp_path: Path,
) -> None:
    # Execute the test verified artifact run and lineage cli use exact application queries
    # workflow in explicit, reviewable steps.
    clock = [0]
    backend, artifacts, catalog, _, _ = _backend(tmp_path, clock)
    source, run = _publish_run(artifacts, catalog)
    expected_run = backend.list_runs(limit=1, offset=0)[0]
    factory = _Factory(backend)
    # Assemble cli once so the test verified artifact run and lineage cli use exact
    # application queries workflow shares one value.
    cli = create_cli(factory)
    runner = CliRunner()

    verified = runner.invoke(cli, ["verify-artifact", run.artifact_id.hex])
    runs = runner.invoke(cli, ["list-runs", "--limit", "1"])
    lineage = runner.invoke(cli, ["show-lineage", run.artifact_id.hex])
    # Assemble missing once so the test verified artifact run and lineage cli use exact
    # application queries workflow shares one value.
    missing = runner.invoke(cli, ["verify-artifact", "f" * 64])

    assert factory.calls == [True, True, True, True]

    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)["descriptor"]["artifact_id"] == run.artifact_id.hex
    assert json.loads(verified.stdout)["verified"] is True
    # Verify runs.exit_code == 0 before this scenario is accepted.
    assert runs.exit_code == 0, runs.output
    assert json.loads(runs.stdout)["items"] == [
        {
            "audit_hash": "d" * 64,
            "canonicality": expected_run.canonicality.value,
            # Keep the canonical result hash expectation tied to items, loads and stdout
            # in this scenario.
            "canonical_result_hash": "c" * 64,
            "completed_at": "2026-01-01T00:00:01Z",
            "comparison": expected_run.comparison.document(),
            "execution_attempt_id": expected_run.execution_attempt_id.hex,
            "logical_run_id": expected_run.logical_run_id.hex,
            "physical_settings": expected_run.physical_settings.document(),
            # Keep the run artifact id expectation tied to items, loads and stdout in this
            # scenario.
            "run_artifact_id": run.artifact_id.hex,
            "started_at": "2026-01-01T00:00:00Z",
            "warnings": [],
        }
    ]
    assert lineage.exit_code == 0, lineage.output
    # Assemble lineage document once so the test verified artifact run and lineage cli use
    # exact application queries workflow shares one value.
    lineage_document = json.loads(lineage.stdout)
    assert lineage_document["root_artifact_id"] == run.artifact_id.hex
    assert {item["artifact_id"] for item in lineage_document["artifacts"]} == {
        source.artifact_id.hex,
        run.artifact_id.hex,
        # Verify the hex, item and artifact id relationship before this scenario is accepted.
    }
    assert missing.exit_code == 2
    assert json.loads(missing.stderr)["code"] == "ARTIFACT_VERIFICATION_FAILED"

    run_root = artifacts._find_artifact_root(run.artifact_id)[1]
    (run_root / "manifest.json").write_bytes(b'{"artifact_schema":"tampered/v1"}')
    # Assemble corrupt once so the test verified artifact run and lineage cli use exact
    # application queries workflow shares one value.
    corrupt = runner.invoke(cli, ["verify-artifact", run.artifact_id.hex])
    assert corrupt.exit_code == 2
    assert json.loads(corrupt.stderr) == {
        "code": "ARTIFACT_VERIFICATION_FAILED",
        "message": "The requested verified artifact metadata is unavailable.",
        # Verify the loads, stderr and code relationship before this scenario is accepted.
    }


def test_migrated_dirty_run_index_is_reconciled_before_direct_cli_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A v7 catalog with Runs becomes queryable without starting ``serve`` first."""

    original_backend, artifacts, _, _, _ = _backend(tmp_path, [0])
    _, run = _publish_run(artifacts, original_backend.container.catalog)
    database = artifacts.data_root / "catalog" / "catalog.sqlite"
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        # Reconstruct the last schema before the manifest-bound Run projection existed.
        connection.execute("DROP TABLE artifact_reconciliation_state")
        connection.execute("DROP TABLE run_index")
        connection.execute("DROP TABLE run_index_state")
        # Remove post-v7 list indexes before replaying later migrations.
        connection.execute("DROP INDEX jobs_list_submitted_idx")
        connection.execute("DROP INDEX jobs_state_list_submitted_idx")
        connection.execute("PRAGMA user_version = 7")
    finally:
        connection.close()

    migrated_catalog = SQLiteArtifactCatalog(database, artifacts)
    queries = QueryArtifacts(migrated_catalog, artifacts)
    migrated_container = SimpleNamespace(
        artifacts=artifacts,
        catalog=migrated_catalog,
        control=SimpleNamespace(
            query_artifacts=queries,
            query_runs=QueryRuns(queries, migrated_catalog),
        ),
        settings=original_backend.container.settings,
    )
    # The migration is deliberately DIRTY until controller-owned bootstrap rebuilds it.
    with pytest.raises(RunIndexQueryError):
        RuntimeCliBackend(cast(RuntimeContainer, migrated_container)).list_runs(
            limit=1,
            offset=0,
        )

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda _: original_backend.container.settings,
    )
    monkeypatch.setattr(
        cli_module,
        "build_runtime_container",
        lambda *_args, **_kwargs: cast(RuntimeContainer, migrated_container),
    )
    direct_backend = build_cli_backend(tmp_path / "local.toml", None)

    # No server lifecycle runs between migration and this direct local query.
    items = direct_backend.list_runs(limit=1, offset=0)
    assert tuple(item.run_artifact_id for item in items) == (run.artifact_id,)
    state = connect(database, busy_timeout_seconds=1.0)
    try:
        assert tuple(state.execute("SELECT status FROM run_index_state").fetchone()) == (
            "COMPLETE",
        )
    finally:
        state.close()


def test_clean_restart_first_run_list_performs_no_payload_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receipt-seeded evidence keeps the first bounded Run page off payload bytes."""

    original_backend, artifacts, catalog, _, _ = _backend(tmp_path, [0])
    _, run = _publish_run(artifacts, catalog)
    LocalArtifactCatalogReconciler(artifacts, catalog).reconcile_once()
    restarted_backend, _, hashed_paths = _restart_with_clean_cache_probe(
        original_backend,
        artifacts,
        monkeypatch,
    )
    runs = restarted_backend.list_runs(limit=1, offset=0)

    assert tuple(item.run_artifact_id for item in runs) == (run.artifact_id,)
    assert hashed_paths == []


def test_receipt_seeded_run_payload_mutation_rehashes_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed payload metadata invalidates a seed before bytes can be returned."""

    original_backend, artifacts, catalog, _, _ = _backend(tmp_path, [0])
    _, run = _publish_run(artifacts, catalog)
    LocalArtifactCatalogReconciler(artifacts, catalog).reconcile_once()
    restarted_backend, restarted_artifacts, hashed_paths = _restart_with_clean_cache_probe(
        original_backend,
        artifacts,
        monkeypatch,
    )

    # Same-size corruption proves the digest check, not merely a descriptor size check.
    run_root = restarted_artifacts._find_artifact_root(run.artifact_id)[1]
    (run_root / "payload.bin").write_bytes(b"bad")
    with pytest.raises(ArtifactQueryError, match="ARTIFACT_VERIFICATION_FAILED"):
        restarted_backend.list_runs(limit=1, offset=0)

    assert [path.name for path in hashed_paths] == ["payload.bin"]


def test_receipt_seeded_run_control_corruption_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seeded entry never bypasses control-envelope authentication on open."""

    original_backend, artifacts, catalog, _, _ = _backend(tmp_path, [0])
    _, run = _publish_run(artifacts, catalog)
    LocalArtifactCatalogReconciler(artifacts, catalog).reconcile_once()
    restarted_backend, restarted_artifacts, hashed_paths = _restart_with_clean_cache_probe(
        original_backend,
        artifacts,
        monkeypatch,
    )

    # Hold stat evidence constant to exercise control authentication on the seeded hit.
    run_root = restarted_artifacts._find_artifact_root(run.artifact_id)[1]
    cached_fingerprint = repository_module._artifact_file_fingerprint(run_root)
    original_fingerprint = repository_module._artifact_file_fingerprint
    # Other artifacts retain real stat checks if the tested path unexpectedly expands.
    monkeypatch.setattr(
        repository_module,
        "_artifact_file_fingerprint",
        lambda root: cached_fingerprint if root == run_root else original_fingerprint(root),
    )
    # Manifest corruption is rejected before any stale payload can reach the caller.
    (run_root / "manifest.json").write_bytes(b"[]")
    with pytest.raises(ArtifactQueryError, match="ARTIFACT_VERIFICATION_FAILED"):
        restarted_backend.list_runs(limit=1, offset=0)

    assert hashed_paths == []


def test_run_index_orders_globally_and_fails_closed_when_projection_drifts(
    tmp_path: Path,
) -> None:
    """Pagination order comes from exact completion time, not rebuild wall clock."""

    backend, artifacts, catalog, _, _ = _backend(tmp_path, [0])
    older_time = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    newer_time = datetime(2026, 1, 2, 0, 0, 1, tzinfo=UTC)
    _, older = _publish_run(
        artifacts,
        catalog,
        run_label="older-run",
        attempt_character="7",
        completed_at=older_time,
    )
    _, newer_one = _publish_run(
        artifacts,
        catalog,
        run_label="newer-run-one",
        attempt_character="8",
        completed_at=newer_time,
    )
    _, newer_two = _publish_run(
        artifacts,
        catalog,
        run_label="newer-run-two",
        attempt_character="9",
        completed_at=newer_time,
    )

    tied = tuple(sorted((newer_one.artifact_id, newer_two.artifact_id), key=lambda item: item.hex))
    first_page = backend.list_runs(limit=2, offset=0)
    second_page = backend.list_runs(limit=2, offset=2)
    ordered_ids = tuple(item.run_artifact_id for item in (*first_page, *second_page))
    assert ordered_ids == (*tied, older.artifact_id)

    query = backend.container.control.query_runs
    assert query is not None
    logical_id = first_page[0].logical_run_id
    logical_ids = tuple(
        item.run_artifact_id for item in query.get_logical(logical_id, limit=3, offset=0)
    )
    assert logical_ids == (*tied, older.artifact_id)

    database = artifacts.data_root / "catalog" / "catalog.sqlite"
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute(
            "DELETE FROM run_index WHERE artifact_id = ?",
            (tied[0].hex,),
        )
    finally:
        connection.close()
    with pytest.raises(RunIndexQueryError):
        backend.list_runs(limit=2, offset=0)
    failed_cli = CliRunner().invoke(
        create_cli(_Factory(backend)),
        ["list-runs", "--limit", "2"],
    )
    assert failed_cli.exit_code == 2
    assert json.loads(failed_cli.stderr)["code"] == "RUN_INDEX_UNAVAILABLE"

    # A full verified rebuild atomically restores the missing scalar projection.
    catalog.rebuild_index(LocalCommittedArtifactScanner(artifacts).scan())
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        row = connection.execute(
            "SELECT * FROM run_index WHERE artifact_id = ?",
            (tied[0].hex,),
        ).fetchone()
        assert row is not None
        connection.execute("DELETE FROM run_index WHERE artifact_id = ?", (tied[0].hex,))
        connection.execute(
            """
            INSERT INTO run_index VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["artifact_id"]),
                str(row["manifest_digest"]),
                1,
                str(row["logical_run_id"]),
                str(row["execution_attempt_id"]),
                0,
                0,
            ),
        )
    finally:
        connection.close()

    # The tampered newest Run now sorts beyond page one, but the dirty generation
    # must fail before LIMIT can hide it from selected-manifest verification.
    with pytest.raises(RunIndexQueryError):
        backend.list_runs(limit=1, offset=0)

    catalog.rebuild_index(LocalCommittedArtifactScanner(artifacts).scan())
    connection = connect(database, busy_timeout_seconds=1.0)
    try:
        connection.execute("DROP TABLE run_index")
    finally:
        connection.close()
    # Missing SQLite structures are translated to the same safe application error.
    with pytest.raises(RunIndexQueryError):
        backend.list_runs(limit=1, offset=0)


def test_failed_run_projection_rebuild_rolls_back_complete_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-transaction projection failure preserves the last searchable page."""

    backend, artifacts, catalog, _, _ = _backend(tmp_path, [0])
    _, run = _publish_run(artifacts, catalog)
    database = artifacts.data_root / "catalog" / "catalog.sqlite"

    def snapshot() -> tuple[tuple[object, ...], tuple[object, ...]]:
        connection = connect(database, busy_timeout_seconds=1.0)
        try:
            rows = tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM run_index ORDER BY artifact_id"
                ).fetchall()
            )
            state = tuple(connection.execute("SELECT * FROM run_index_state").fetchone())
            return rows, state
        finally:
            connection.close()

    before = snapshot()

    # Inject failure after rebuild has dirtied and cleared rows inside its transaction.
    def fail_projection(*_: object) -> None:
        raise OSError("injected projection failure")

    monkeypatch.setattr(
        SQLiteArtifactCatalog,
        "_insert_run_projection",
        staticmethod(fail_projection),
    )
    with pytest.raises(OSError, match="injected projection failure"):
        catalog.rebuild_index(LocalCommittedArtifactScanner(artifacts).scan())

    assert snapshot() == before
    assert backend.list_runs(limit=1, offset=0)[0].run_artifact_id == run.artifact_id


def test_pin_gc_execute_and_grace_guard_are_executable_from_cli(tmp_path: Path) -> None:
    # Execute the test pin gc execute and grace guard are executable from cli workflow in
    # explicit, reviewable steps.
    clock = [0]
    backend, artifacts, catalog, _, _ = _backend(tmp_path, clock)
    source, run = _publish_run(artifacts, catalog)
    clock[0] = time.time_ns() + 1_000_000_000
    cli = create_cli(_Factory(backend))
    # Assemble runner once so the test pin gc execute and grace guard are executable from
    # cli workflow shares one value.
    runner = CliRunner()

    pinned = runner.invoke(
        cli,
        ["pin", "baseline", "--root", run.artifact_id.hex, "--reason", "audit"],
    )
    # Assemble protected once so the test pin gc execute and grace guard are executable
    # from cli workflow shares one value.
    protected = runner.invoke(cli, ["gc", "--dry-run"])
    retired = runner.invoke(cli, ["unpin", "baseline"])
    dry_run = runner.invoke(cli, ["gc", "--dry-run"])

    assert pinned.exit_code == 0, pinned.output
    assert json.loads(pinned.stdout)["transitive_closure"] == sorted(
        # Open the hex and artifact id payload explicitly for sorted within test pin gc
        # execute and grace guard are executable from cli.
        (source.artifact_id.hex, run.artifact_id.hex)
    )
    assert protected.exit_code == 0, protected.output
    assert json.loads(protected.stdout)["plan"]["candidates"] == []
    assert retired.exit_code == 0, retired.output
    # Verify the retired, status and loads relationship before this scenario is accepted.
    assert json.loads(retired.stdout)["status"] == "RETIRED"
    assert dry_run.exit_code == 0, dry_run.output
    assert {item["artifact_id"] for item in json.loads(dry_run.stdout)["plan"]["candidates"]} == {
        source.artifact_id.hex,
        run.artifact_id.hex,
        # Verify the hex, item and artifact id relationship before this scenario is accepted.
    }
    artifacts.open_committed(run.artifact_id).close()

    executed = runner.invoke(cli, ["gc", "--execute"])
    assert executed.exit_code == 0, executed.output
    batch = json.loads(executed.stdout)["batch"]
    # Verify the hex, batch and artifact ids relationship before this scenario is
    # accepted.
    assert set(batch["artifact_ids"]) == {source.artifact_id.hex, run.artifact_id.hex}

    too_early = runner.invoke(cli, ["gc-purge", batch["batch_id"]])
    assert too_early.exit_code == 2
    assert json.loads(too_early.stderr)["code"] == "RETENTION_OPERATION_REJECTED"

    clock[0] = batch["purge_not_before_ns"]
    # Assemble purged once so the test pin gc execute and grace guard are executable from
    # cli workflow shares one value.
    purged = runner.invoke(cli, ["gc-purge", batch["batch_id"]])
    assert purged.exit_code == 0, purged.output
    receipt = json.loads(purged.stdout)
    assert set(receipt["artifact_ids"]) == {source.artifact_id.hex, run.artifact_id.hex}
    assert receipt["deleted_bytes"] > 0


# Define test backup and restore verify cli use only configured locations as one focused
# operation with an explicit boundary.
def test_backup_and_restore_verify_cli_use_only_configured_locations(tmp_path: Path) -> None:
    # Execute the test backup and restore verify cli use only configured locations
    # workflow in explicit, reviewable steps.
    clock = [0]
    backend, artifacts, catalog, backup_root, restore_parent = _backend(tmp_path, clock)
    _, run = _publish_run(artifacts, catalog)
    clock[0] = time.time_ns() + 1_000_000_000
    cli = create_cli(_Factory(backend))
    # Assemble runner once so the test backup and restore verify cli use only configured
    # locations workflow shares one value.
    runner = CliRunner()
    pinned = runner.invoke(
        cli,
        ["pin", "backup-root", "--root", run.artifact_id.hex, "--reason", "durability"],
    )
    # Verify pinned.exit_code == 0 before this scenario is accepted.
    assert pinned.exit_code == 0, pinned.output

    created = runner.invoke(cli, ["backup"])
    assert created.exit_code == 0, created.output
    generation = json.loads(created.stdout)
    cut = generation["backup_cut_id"]
    # Verify the is file, committed and cut relationship before this scenario is accepted.
    assert (backup_root / "generations" / cut / "COMMITTED").is_file()
    assert run.artifact_id.hex in generation["artifact_ids"]

    restored = runner.invoke(cli, ["restore-verify", cut])
    assert restored.exit_code == 0, restored.output
    report = json.loads(restored.stdout)
    # Verify report['backup_cut_id'] == cut before this scenario is accepted.
    assert report["backup_cut_id"] == cut
    assert report["reconciliation_complete"] is True
    assert report["restored_artifacts"] == 2
    destinations = tuple(restore_parent.iterdir())
    assert len(destinations) == 1
    # Verify the name, report and destination name relationship before this scenario is
    # accepted.
    assert report["destination_name"] == destinations[0].name
    assert (destinations[0] / "RESTORE_RECONCILED").is_file()

    missing = runner.invoke(cli, ["restore-verify", "f" * 64])
    assert missing.exit_code == 2
    assert json.loads(missing.stderr)["code"] == "BACKUP_OPERATION_REJECTED"


# Define test unconfigured backup fails with stable safe cli error as one focused
# operation with an explicit boundary.
def test_unconfigured_backup_fails_with_stable_safe_cli_error(tmp_path: Path) -> None:
    # Execute the test unconfigured backup fails with stable safe cli error workflow in
    # explicit, reviewable steps.
    clock = [time.time_ns()]
    backend, _, _, _, _ = _backend(tmp_path, clock, backup_configured=False)

    result = CliRunner().invoke(create_cli(_Factory(backend)), ["backup"])

    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        # Keep the code expectation tied to loads, stderr and code in this scenario.
        "code": "BACKUP_NOT_CONFIGURED",
        "message": "An external backup target is not configured for this host.",
    }


def test_production_restore_verify_ignores_a_corrupt_live_catalog(
    tmp_path: Path,
    # Close the test production restore verify ignores a corrupt live catalog signature after
    # its explicit inputs.
) -> None:
    # Execute the test production restore verify ignores a corrupt live catalog workflow
    # in explicit, reviewable steps.
    live = tmp_path / "live"
    backup_root = tmp_path / "backup-device"
    restore_parent = tmp_path / "restore-drills"
    restore_parent.mkdir()
    settings = Settings(
        # Keep the live PathSettings step visible while building settings.
        paths=PathSettings(live),
        backup=BackupSettings(
            target_root=backup_root,
            restore_verify_parent=restore_parent,
            allow_same_device_for_drill=True,
            # Complete BackupSettings only after its backup root and restore parent inputs are
            # visible in test production restore verify ignores a corrupt live catalog.
        ),
    )
    artifacts = LocalArtifactRepository(live)
    catalog = SQLiteArtifactCatalog(live / "catalog" / "catalog.sqlite", artifacts)
    retained = _publish(artifacts, label="recovery-root", kind=ArtifactKind.RUN)
    # Invoke index_committed for retained as a visible test production restore verify
    # ignores a corrupt live catalog step.
    catalog.index_committed(retained)
    maintenance = build_maintenance_services(settings, artifacts, clock_ns=lambda: 10)
    maintenance.retention.create_pin(
        CreatePinRequest(
            Identifier("production-recovery-root"),
            # Open the production-recovery-root and production recovery test payload
            # explicitly for CreatePinRequest within test production restore verify
            # ignores a corrupt live catalog.
            (retained.artifact_id,),
            "production recovery test",
        )
    )
    generation = maintenance.create_backup()
    # Assemble live catalog once so the test production restore verify ignores a corrupt
    # live catalog workflow shares one value.
    live_catalog = live / "catalog" / "catalog.sqlite"
    live_catalog.write_bytes(b"not a sqlite database")
    corrupt_bytes = live_catalog.read_bytes()
    config_path = tmp_path / "recovery.toml"
    config_path.write_text(
        # Pass n explicitly to write_text for value and [paths].
        "\n".join(
            (
                "[paths]",
                f"data_root = {json.dumps(str(live))}",
                "[backup]",
                # Pass target root json dumps str explicitly to write_text for value and
                # [paths].
                f"target_root = {json.dumps(str(backup_root))}",
                f"restore_verify_parent = {json.dumps(str(restore_parent))}",
                "allow_same_device_for_drill = true",
            )
        ),
        # Pass encoding explicitly so write_text receives a reviewable value and [paths]
        # input in test production restore verify ignores a corrupt live catalog.
        encoding="utf-8",
    )
    runner = CliRunner()

    restored = runner.invoke(
        app,
        # Open the restore-verify and --config payload explicitly for invoke within test
        # production restore verify ignores a corrupt live catalog.
        [
            "restore-verify",
            generation.backup_cut_id.hex,
            "--config",
            str(config_path),
            # Close the restore-verify and --config payload only after all test production
            # restore verify ignores a corrupt live catalog fields are present.
        ],
    )

    assert restored.exit_code == 0, restored.output
    report = json.loads(restored.stdout)
    assert report["backup_cut_id"] == generation.backup_cut_id.hex
    # Verify the report and reconciliation complete relationship before this scenario is
    # accepted.
    assert report["reconciliation_complete"] is True
    assert report["restored_artifacts"] == 1
    assert live_catalog.read_bytes() == corrupt_bytes
    destinations = tuple(restore_parent.iterdir())
    assert len(destinations) == 1
    # Verify the name, report and destination name relationship before this scenario is
    # accepted.
    assert destinations[0].name == report["destination_name"]
    assert (destinations[0] / "RESTORE_RECONCILED").is_file()

    missing = runner.invoke(
        app,
        ["restore-verify", "f" * 64, "--config", str(config_path)],
        # Complete invoke only after its restore-verify and --config inputs are visible in
        # test production restore verify ignores a corrupt live catalog.
    )
    assert missing.exit_code == 2
    assert json.loads(missing.stderr) == {
        "code": "BACKUP_OPERATION_REJECTED",
        "message": "The backup or restore verification operation failed closed.",
        # Verify the loads, stderr and code relationship before this scenario is accepted.
    }
    assert str(live) not in missing.output
    assert str(backup_root) not in missing.output
    assert live_catalog.read_bytes() == corrupt_bytes
