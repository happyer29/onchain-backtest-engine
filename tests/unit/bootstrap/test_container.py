# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

# Import typing at the visible module dependency boundary.
from typing import Any, cast

import pytest

import backtest.bootstrap.container as container_module
import backtest.bootstrap.execution_container as execution_container_module
import backtest.bootstrap.source as source_module

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.catalog.sqlite import SQLiteJobQueue
from backtest.adapters.performance import BenchmarkAdmissionError
from backtest.adapters.source.clickhouse import ClickHouseCapability
from backtest.adapters.source.clickhouse.query import clickhouse_capability_mapping_digest
from backtest.adapters.source.in_memory import InMemorySourceReader
from backtest.application.errors import ErrorCode, SourceEvidenceValidationError
from backtest.application.job_commands import ResolvedCompileReplayJob

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    BoundedSourceEvidenceRequest,
    BudgetLimits,
    CapabilityDescriptor,
    CapabilityStream,
    DataRequirement,
    # Include job type so the models dependency remains explicit.
    JobType,
    ListJobsRequest,
    PlanDatasetRequest,
    QueryLimits,
    RequirementOrigin,
    # Include source metadata so the models dependency remains explicit.
    SourceMetadata,
)
from backtest.application.use_cases.cancel_job import CancelJobRequest
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest
from backtest.application.use_cases.query_jobs import GetJobRequest

# Import store source inspection at the visible module dependency boundary.
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.bootstrap.config import (
    PathSettings,
    ReplaySettings,
    # Include resource settings so the config dependency remains explicit.
    ResourceSettings,
    Settings,
    SourceSettings,
)
from backtest.bootstrap.container import ConfiguredClickHouseSource, build_runtime_container
from backtest.bootstrap.pumpfun_live_source import (
    PumpfunLiveSourceComposition,
    PumpfunLiveSourceError,
    PumpfunLiveSourceErrorCode,
)

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.identifiers import (
    BundleId,
    CapabilityId,
    ContentDigest,
    SnapshotId,
    SourceId,
)

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange
from backtest.runtime.host_resources import HostMemoryMeasurement
from backtest.runtime.thread_limits import (
    ChildProcessEnvironmentError,
    apply_child_process_determinism,
)


# Keep the result contract and validation rules together.
@dataclass
class _Result:
    result_rows: Sequence[Sequence[Any]]
    closed: bool = False

    def close(self) -> None:
        # Assemble self closed once so the result close workflow shares one value.
        self.closed = True


# Keep the unused stream contract and validation rules together.
class _UnusedStream(AbstractContextManager[Iterator[Sequence[Sequence[Any]]]]):
    def __enter__(self) -> Iterator[Sequence[Sequence[Any]]]:
        raise AssertionError("metadata inspection must not open a row stream")

    def __exit__(self, *args: object) -> None:
        return None


# Keep the metadata client contract and validation rules together.
class _MetadataClient:
    def __init__(self, *, fail_close: bool = False) -> None:
        # Execute the metadata client init workflow in explicit, reviewable steps.
        self.fail_close = fail_close
        self.closed = False
        self.results: list[_Result] = []

    def query(
        self,
        # Keep the query input explicit in the query contract.
        query: str,
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        # Keep the transport settings input explicit in the query contract.
        transport_settings: Mapping[str, str] | None = None,
    ) -> _Result:
        # Execute the metadata client query workflow in explicit, reviewable steps.
        del parameters, settings, query_tz, transport_settings
        if "version()" in query:
            rows: Sequence[Sequence[Any]] = (("24.8",),)
        # Handle the metadata client query complement of 'version()' in query explicitly.
        elif "system.tables" in query:
            rows = (("MergeTree", "", "slot"),)
        # Handle the metadata client query complement of 'system.tables' in query
        # explicitly.
        elif "system.columns" in query:
            rows = (("slot", "UInt64"),)
        else:
            raise AssertionError(f"unexpected metadata query: {query}")
        result = _Result(rows)
        # Invoke append for result as a visible metadata client query step.
        self.results.append(result)
        return result

    def query_row_block_stream(
        self,
        query: str,
        # Keep the parameters input explicit in the query row block stream contract.
        parameters: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        *,
        query_tz: str | None = None,
        transport_settings: Mapping[str, str] | None = None,
        # Keep the unused stream input explicit in the query row block stream contract.
    ) -> _UnusedStream:
        # Execute the metadata client query row block stream workflow in explicit,
        # reviewable steps.
        del query, parameters, settings, query_tz, transport_settings
        return _UnusedStream()

    def close(self) -> None:
        # Execute the metadata client close workflow in explicit, reviewable steps.
        self.closed = True
        if self.fail_close:
            raise RuntimeError("close diagnostics must be suppressed")


def _capability() -> ClickHouseCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    descriptor = CapabilityDescriptor(
        capability_id=CapabilityId("fixture.slots.v1"),
        protocol="fixture",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # fixture input in capability.
        stream=CapabilityStream.BLOCK_CLOCK,
        columns=("block_ordinal",),
        mandatory_columns=("block_ordinal",),
        fidelity=SourceFidelity(
            identity=IdentityFidelity.UNKNOWN,
            # Pass ordering explicitly so SourceFidelity receives a reviewable unknown and
            # none input in capability.
            ordering=OrderingFidelity.UNKNOWN,
            state=StateFidelity.NONE,
            fees=FeesFidelity.UNKNOWN,
            chain_finality=ChainFinality.UNKNOWN,
            completeness=IngestionCompleteness.UNKNOWN,
            # Pass consistency explicitly so SourceFidelity receives a reviewable unknown
            # and none input in capability.
            consistency=SourceConsistency.UNKNOWN,
        ),
    )
    return ClickHouseCapability(
        descriptor=descriptor,
        # Pass network id explicitly so ClickHouseCapability receives a reviewable default
        # and slots input in capability.
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table="slots",
        logical_to_physical={"block_ordinal": "slot"},
        # Complete ClickHouseCapability only after its default and slots inputs are visible in
        # capability.
    )


def _settings(
    data_root: Path,
    *,
    capabilities_file: Path | None = None,
    # Keep the settings input explicit in the settings contract.
) -> Settings:
    # Execute the settings workflow in explicit, reviewable steps.
    return Settings(
        paths=PathSettings(data_root=data_root),
        resources=ResourceSettings(
            tmp_quota_gb=1,
            disk_low_watermark_gb=1,
            # Pass disk emergency watermark gb explicitly into ResourceSettings within
            # settings.
            disk_emergency_watermark_gb=1,
            native_threads_per_process=3,
        ),
        replay=ReplaySettings(threads=3),
        source=SourceSettings(
            # Pass source id explicitly so SourceSettings receives a reviewable fixture-
            # indexer and internal input in settings.
            source_id="fixture-indexer",
            host="indexer.internal",
            port=8_443,
            database="analytics",
            username="readonly",
            # Pass secret ref explicitly so SourceSettings receives a reviewable fixture-
            # indexer and internal input in settings.
            secret_ref="TEST_INDEXER_PASSWORD",
            capabilities_file=capabilities_file,
            secure=True,
        ),
    )


# Define test execution container rejects mismatched isolated child environment as one
# focused operation with an explicit boundary.
def test_execution_container_rejects_mismatched_isolated_child_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test execution container rejects mismatched isolated child environment
    # workflow in explicit, reviewable steps.
    declared: dict[str, str] = {}
    apply_child_process_determinism(3, declared)
    for name, value in declared.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PYTHONHASHSEED", "wrong")

    # Acquire raises, child process environment error and pytest at an explicit test
    # execution container rejects mismatched isolated child environment context boundary
    # so cleanup remains scoped.
    with pytest.raises(ChildProcessEnvironmentError, match="runtime contract"):
        # Keep raises, child process environment error and pytest active only for the
        # bounded test execution container rejects mismatched isolated child environment
        # operation.
        execution_container_module.build_execution_container(
            _settings(tmp_path / "state"),
            verify_isolated_child_environment=True,
        )


def test_execution_container_bounds_replay_compiler_parquet_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_source(*args: object, **kwargs: object) -> object:
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        execution_container_module,
        "CanonicalParquetReplaySource",
        capture_source,
    )
    container = execution_container_module.build_execution_container(_settings(tmp_path / "state"))
    compiler = cast(Any, container.compile_replay)._compiler
    source_factory = cast(Any, compiler)._source_factory

    source_factory(SnapshotId("a" * 64))

    assert captured["reader_batch_rows"] == 8_192
    assert captured["reader_readahead"] == 1


def test_runtime_container_composes_measured_benchmark_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = replace(
        _settings(tmp_path / "unused").resources,
        max_builder_memory_mb=144,
        builder_peak_private_memory_mb=768,
        run_peak_private_memory_mb=768,
    )
    settings = replace(_settings(tmp_path / "state"), resources=resources)
    measurements: list[HostMemoryMeasurement] = []
    measurement = HostMemoryMeasurement(
        total_physical_bytes=16 * 1024**3,
        available_physical_bytes=8 * 1024**3,
        controller_private_rss_bytes=256 * 1024**2,
    )

    def measure() -> HostMemoryMeasurement:
        measurements.append(measurement)
        return measurement

    monkeypatch.setattr(container_module, "measure_host_memory", measure)
    monkeypatch.setattr(container_module, "physical_core_count", lambda: 8)

    runtime = build_runtime_container(settings, profile="unit")
    runner = cast(Any, cast(Any, runtime.run_exact_benchmark)._runner)

    assert measurements == []
    assert runner._capacity.private_memory_mb == resources.max_aggregate_child_memory_mb
    capacity = runner._capacity_provider()
    assert measurements == [measurement]
    assert capacity.private_memory_mb == 4_352
    assert capacity.physical_cores == 8
    assert capacity.max_processes_by_io == resources.max_parallel_runs
    assert capacity.private_memory_mb > resources.max_builder_memory_mb


def test_measured_benchmark_capacity_rejects_zero_safe_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _settings(tmp_path / "state").resources
    monkeypatch.setattr(
        container_module,
        "measure_host_memory",
        lambda: HostMemoryMeasurement(
            total_physical_bytes=16 * 1024**3,
            available_physical_bytes=1_024 * 1024**2,
            controller_private_rss_bytes=256 * 1024**2,
        ),
    )

    with pytest.raises(BenchmarkAdmissionError, match="no safe private budget"):
        container_module._measure_benchmark_host_capacity(
            resources,
            physical_cores=8,
            max_processes_by_io=1,
        )


def test_runtime_container_is_lazy_and_wires_local_paths_and_use_cases(
    # Keep the tmp path input explicit in the test runtime container is lazy and wires
    # local paths and use cases contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test runtime container is lazy and wires local paths and use cases
    # workflow in explicit, reviewable steps.
    data_root = tmp_path / "state"
    capability_path = tmp_path / "capabilities.toml"
    settings = _settings(data_root, capabilities_file=capability_path)
    capability = _capability()
    loaded_paths: list[Path] = []
    # Assemble thread limits once so the test runtime container is lazy and wires local
    # paths and use cases workflow shares one value.
    thread_limits: list[int] = []

    def load_capabilities(path: Path) -> tuple[ClickHouseCapability, ...]:
        # Execute the load capabilities workflow in explicit, reviewable steps.
        loaded_paths.append(path)
        return (capability,)

    def reject_network(**_: object) -> None:
        raise AssertionError("composition and planning must not connect to ClickHouse")

    monkeypatch.setattr(container_module, "load_clickhouse_capabilities", load_capabilities)
    # Invoke setattr for apply thread limits and append as a visible test runtime
    # container is lazy and wires local paths and use cases step.
    monkeypatch.setattr(
        execution_container_module,
        "apply_thread_limits",
        thread_limits.append,
    )
    # Invoke setattr for get client and clickhouse connect as a visible test runtime
    # container is lazy and wires local paths and use cases step.
    monkeypatch.setattr(source_module.clickhouse_connect, "get_client", reject_network)

    runtime = build_runtime_container(settings, profile="unit")

    assert loaded_paths == [capability_path]
    assert thread_limits == [3]
    assert runtime.settings is settings
    # Verify the isinstance, artifacts and local artifact repository relationship before
    # this scenario is accepted.
    assert isinstance(runtime.artifacts, LocalArtifactRepository)
    assert runtime.artifacts.data_root == data_root.resolve()
    assert isinstance(runtime.jobs, SQLiteJobQueue)
    assert runtime.jobs.database_path == data_root.resolve() / "catalog" / "catalog.sqlite"
    assert runtime.control.profile == "unit"
    # Verify the query run results, control and runtime relationship before this scenario
    # is accepted.
    assert runtime.control.query_run_results is not None
    assert runtime.source.list_capabilities(SourceId("fixture-indexer")) == (capability.descriptor,)

    inspection_source = InMemorySourceReader(
        SourceMetadata(
            source_id=SourceId("fixture-indexer"),
            # Pass network id explicitly so SourceMetadata receives a reviewable fixture-
            # indexer and fixture-v1 input in test runtime container is lazy and wires
            # local paths and use cases.
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            server_version="fixture-v1",
            tables=(),
            capabilities=(capability.descriptor,),
            # Complete SourceMetadata only after its fixture-indexer and fixture-v1 inputs are
            # visible in test runtime container is lazy and wires local paths and use cases.
        ),
        {capability.descriptor.capability_id: ()},
    )
    stored_inspection = StoreSourceInspection(
        InspectSource(inspection_source),
        # Pass runtime explicitly so execute receives a reviewable fixture-indexer and
        # inspect source request input in test runtime container is lazy and wires local
        # paths and use cases.
        runtime.artifacts,
    ).execute(InspectSourceRequest(SourceId("fixture-indexer")))
    plan = runtime.control.plan_dataset.execute(
        PlanDatasetRequest(
            source_id=SourceId("fixture-indexer"),
            # Pass source inspection artifact id explicitly so PlanDatasetRequest receives
            # a reviewable fixture-indexer and strategy input in test runtime container is
            # lazy and wires local paths and use cases.
            source_inspection_artifact_id=stored_inspection.artifact.artifact_id,
            network_id=SOLANA_MAINNET_NETWORK_ID,
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            decision_range=BlockRange(
                SOLANA_MAINNET_NETWORK_ID,
                # Pass block32 transaction32 position schema id explicitly so BlockRange
                # receives a reviewable solana mainnet network id and block32
                # transaction32 position schema id input in test runtime container is lazy
                # and wires local paths and use cases.
                BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                10,
                20,
            ),
            warmup_blocks=2,
            # Pass settlement tail blocks explicitly so PlanDatasetRequest receives a
            # reviewable fixture-indexer and strategy input in test runtime container is
            # lazy and wires local paths and use cases.
            settlement_tail_blocks=0,
            max_shard_blocks=6,
            requested_days=None,
            requirements=(
                DataRequirement(
                    # Pass origin explicitly so DataRequirement receives a reviewable
                    # strategy and block ordinal input in test runtime container is lazy
                    # and wires local paths and use cases.
                    origin=RequirementOrigin.STRATEGY,
                    origin_id="strategy",
                    capability_id=capability.descriptor.capability_id,
                    columns=("block_ordinal",),
                ),
                # Complete PlanDatasetRequest only after its fixture-indexer and strategy
                # inputs are visible in test runtime container is lazy and wires local paths
                # and use cases.
            ),
            budget_limits=BudgetLimits(
                max_remote_bytes=1,
                max_local_bytes=1,
                max_days=1,
                # Pass temporary reserve bytes explicitly into BudgetLimits within test
                # runtime container is lazy and wires local paths and use cases.
                temporary_reserve_bytes=0,
                disk_low_watermark_bytes=0,
            ),
            query_limits=QueryLimits(max_execution_seconds=1, max_memory_bytes=1),
        )
        # Complete execute only after its fixture-indexer and strategy inputs are visible in
        # test runtime container is lazy and wires local paths and use cases.
    )
    assert tuple(shard.block_range for shard in plan.spec.shards) == (
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            # Keep block range, solana mainnet network id and block32 transaction32
            # position schema id visible while completing BlockRange within test runtime
            # container is lazy and wires local paths and use cases.
            8,
            14,
        ),
        BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            # Pass block32 transaction32 position schema id explicitly so BlockRange
            # receives a reviewable solana mainnet network id and block32 transaction32
            # position schema id input in test runtime container is lazy and wires local
            # paths and use cases.
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            14,
            20,
        ),
    )

    # Assemble submitted once so the test runtime container is lazy and wires local paths
    # and use cases workflow shares one value.
    submitted = runtime.control.submit_job.execute(
        SubmitJobRequest(
            spec_version=1,
            job_type=JobType.COMPILE_REPLAY,
            payload_json=ResolvedCompileReplayJob(SnapshotId("a" * 64)).canonical_bytes(),
            # Pass idempotency key explicitly so SubmitJobRequest receives a reviewable a
            # and container-wiring input in test runtime container is lazy and wires local
            # paths and use cases.
            idempotency_key="container-wiring",
        )
    )
    assert runtime.control.get_job.execute(GetJobRequest(submitted.job_id)) == submitted
    assert runtime.control.list_jobs.execute(ListJobsRequest()) == (submitted,)
    # Assemble cancelled once so the test runtime container is lazy and wires local paths
    # and use cases workflow shares one value.
    cancelled = runtime.control.cancel_job.execute(CancelJobRequest(submitted.job_id))
    assert cancelled.state.value == "CANCELLED"
    assert runtime.jobs.database_path.is_file()


def test_runtime_container_builds_projector_from_normalized_live_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _capability()
    normalized = replace(
        raw,
        descriptor=replace(
            raw.descriptor,
            protocol_version="normalized-v1",
            schema_version="normalized-v1",
            columns=("block_ordinal", "block_time"),
            mandatory_columns=("block_ordinal", "block_time"),
        ),
        logical_to_physical={"block_ordinal": "block_ordinal", "block_time": "block_time"},
    )
    normalizer_digest = ContentDigest("a" * 64)
    projector_digest = ContentDigest("b" * 64)
    projector_bundle_id = BundleId("c" * 64)
    live = SimpleNamespace(
        raw_capabilities=(raw,),
        projection_capabilities=(normalized,),
        normalizer_digest=normalizer_digest,
    )
    settings = _settings(tmp_path / "state", capabilities_file=tmp_path / "capabilities.toml")
    settings = replace(
        settings,
        source=replace(settings.source, projections_file=tmp_path / "projections.toml"),
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        container_module,
        "load_clickhouse_capabilities",
        lambda path: (raw,),
    )
    monkeypatch.setattr(
        container_module,
        "select_clickhouse_query_profile",
        lambda capabilities: object(),
    )
    monkeypatch.setattr(
        container_module,
        "build_pumpfun_live_source_composition",
        lambda capabilities: live,
    )

    def build_projector(
        path: Path,
        capabilities: tuple[ClickHouseCapability, ...],
        *,
        build_tools: object,
        source_normalizer_digest: ContentDigest | None,
    ) -> SimpleNamespace:
        observed.update(
            path=path,
            capabilities=capabilities,
            build_tools=build_tools,
            source_normalizer_digest=source_normalizer_digest,
        )
        return SimpleNamespace(
            bundle_id=projector_bundle_id,
            config_digest=projector_digest,
        )

    class _CompositionReached(RuntimeError):
        pass

    def stop_after_projector(
        settings: Settings,
        *,
        build_tools: object,
        expected_projector_bundle_id: BundleId | None,
    ) -> None:
        del settings, build_tools
        observed["expected_projector_bundle_id"] = expected_projector_bundle_id
        raise _CompositionReached

    monkeypatch.setattr(container_module, "build_configured_projector", build_projector)
    monkeypatch.setattr(container_module, "build_execution_container", stop_after_projector)

    with pytest.raises(_CompositionReached):
        build_runtime_container(settings, profile="unit")

    assert observed["path"] == tmp_path / "projections.toml"
    assert observed["capabilities"] == (normalized,)
    assert observed["source_normalizer_digest"] == normalizer_digest
    assert observed["expected_projector_bundle_id"] == projector_bundle_id


def test_configured_source_builds_evidence_request_from_live_contract_without_network(
    tmp_path: Path,
) -> None:
    raw = _capability()
    normalized_descriptor = replace(
        raw.descriptor,
        protocol_version="normalized-v1",
        schema_version="normalized-v1",
        columns=("block_ordinal", "block_time"),
        mandatory_columns=("block_ordinal", "block_time"),
    )
    mapping_digest = clickhouse_capability_mapping_digest((raw,))
    fixed_query_digest = ContentDigest("d" * 64)
    normalizer_digest = ContentDigest("e" * 64)
    projector_digest = ContentDigest("f" * 64)
    live = SimpleNamespace(
        raw_capabilities=(raw,),
        metadata_capabilities=(normalized_descriptor,),
        capability_mapping_digest=mapping_digest,
        query_template_digest=fixed_query_digest,
        normalizer_digest=normalizer_digest,
    )
    source = ConfiguredClickHouseSource(
        _settings(tmp_path / "state"),
        (raw,),
        pumpfun_live=live,
        projector_digest=projector_digest,
    )
    evidence_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        20,
    )
    decision_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        18,
    )

    request = source.build_evidence_request(
        source_id=SourceId("fixture-indexer"),
        block_range=evidence_range,
        decision_range=decision_range,
        query_limits=QueryLimits(
            max_execution_seconds=30,
            max_memory_bytes=64 * 1024**2,
            max_result_rows=100_000,
        ),
    )

    assert source.list_capabilities(SourceId("fixture-indexer")) == (normalized_descriptor,)
    assert request.capability_mapping_digest == mapping_digest
    assert request.query_template_digest == fixed_query_digest
    assert request.normalizer_digest == normalizer_digest
    assert request.projector_digest == projector_digest
    assert request.block_range == evidence_range
    assert request.decision_range == decision_range


@pytest.mark.parametrize("fail_close", (False, True))
def test_configured_source_connects_only_for_inspection_and_always_closes(
    # Keep the tmp path input explicit in the test configured source connects only for
    # inspection and always closes contract.
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_close: bool,
) -> None:
    # Execute the test configured source connects only for inspection and always closes
    # workflow in explicit, reviewable steps.
    secret = "not-returned-to-domain"
    settings = _settings(tmp_path / "state")
    client = _MetadataClient(fail_close=fail_close)
    connection_arguments: list[dict[str, object]] = []

    def connect(**kwargs: object) -> _MetadataClient:
        # Execute the connect workflow in explicit, reviewable steps.
        connection_arguments.append(kwargs)
        return client

    monkeypatch.setenv("TEST_INDEXER_PASSWORD", secret)
    monkeypatch.setattr(source_module.clickhouse_connect, "get_client", connect)
    source = ConfiguredClickHouseSource(settings, (_capability(),))

    # Verify connection_arguments == [] before this scenario is accepted.
    assert connection_arguments == []
    assert source.list_capabilities(SourceId("fixture-indexer"))
    assert connection_arguments == []

    metadata = source.inspect_metadata(SourceId("fixture-indexer"))

    assert metadata.source_id == SourceId("fixture-indexer")
    # Verify metadata.server_version == '24.8' before this scenario is accepted.
    assert metadata.server_version == "24.8"
    assert connection_arguments == [
        {
            "host": "indexer.internal",
            "port": 8_443,
            # Keep the username expectation tied to connection arguments, host and port in
            # this scenario.
            "username": "readonly",
            "password": secret,
            "database": "analytics",
            "secure": True,
            "verify": True,
            # Verify the connection arguments, host and port relationship before this scenario
            # is accepted.
        }
    ]
    assert client.closed is True
    assert client.results and all(result.closed for result in client.results)
    assert secret not in repr(metadata)


# Define test configured source fails closed without leaking connection details as one
# focused operation with an explicit boundary.
def test_configured_source_fails_closed_without_leaking_connection_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test configured source fails closed without leaking connection details
    # workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")
    calls = 0

    def fail_connection(**_: object) -> None:
        # Execute the fail connection workflow in explicit, reviewable steps.
        nonlocal calls
        calls += 1
        raise RuntimeError("https://readonly:plain-secret@indexer.internal")

    monkeypatch.setenv("TEST_INDEXER_PASSWORD", "plain-secret")
    monkeypatch.setattr(source_module.clickhouse_connect, "get_client", fail_connection)
    # Assemble source once so the test configured source fails closed without leaking
    # connection details workflow shares one value.
    source = ConfiguredClickHouseSource(settings, (_capability(),))

    with pytest.raises(RuntimeError) as caught:
        source.inspect_metadata(SourceId("fixture-indexer"))

    assert str(caught.value) == "ClickHouse metadata connection failed"
    assert caught.value.__cause__ is None
    # Verify caught.value.__context__ is None before this scenario is accepted.
    assert caught.value.__context__ is None
    assert "plain-secret" not in repr(caught.value)
    assert calls == 1


@pytest.mark.parametrize(
    ("source_code", "public_code"),
    (
        (
            PumpfunLiveSourceErrorCode.INCOMPLETE_BLOCK_RANGE,
            ErrorCode.INCOMPLETE_BLOCK_RANGE,
        ),
        (
            PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH,
            ErrorCode.CURVE_TRANSITION_MISMATCH,
        ),
    ),
)
def test_configured_source_maps_typed_live_evidence_rejections_without_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_code: PumpfunLiveSourceErrorCode,
    public_code: ErrorCode,
) -> None:
    raw = _capability()
    mapping_digest = clickhouse_capability_mapping_digest((raw,))
    query_digest = ContentDigest("d" * 64)
    normalizer_digest = ContentDigest("e" * 64)
    projector_digest = ContentDigest("f" * 64)

    class _FailingLive:
        def __init__(self) -> None:
            self.raw_capabilities = (raw,)
            self.metadata_capabilities = (raw.descriptor,)
            self.capability_mapping_digest = mapping_digest
            self.query_template_digest = query_digest
            self.normalizer_digest = normalizer_digest

        def inspect_bounded_evidence(
            self,
            reader: object,
            request: BoundedSourceEvidenceRequest,
            *,
            projector_digest: ContentDigest,
        ) -> tuple[()]:
            del reader, request, projector_digest
            try:
                raise RuntimeError("password=live-driver-secret")
            except RuntimeError as error:
                raise PumpfunLiveSourceError(source_code) from error

    client = _MetadataClient()
    monkeypatch.setenv("TEST_INDEXER_PASSWORD", "live-driver-secret")
    monkeypatch.setattr(source_module.clickhouse_connect, "get_client", lambda **_: client)
    source = ConfiguredClickHouseSource(
        _settings(tmp_path / "state"),
        (raw,),
        pumpfun_live=cast(PumpfunLiveSourceComposition, _FailingLive()),
        projector_digest=projector_digest,
    )
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        20,
    )
    request = source.build_evidence_request(
        source_id=SourceId("fixture-indexer"),
        block_range=block_range,
        decision_range=block_range,
        query_limits=QueryLimits(30, 64 * 1024**2, 100_000),
    )

    with pytest.raises(SourceEvidenceValidationError) as caught:
        source.inspect_bounded_evidence(request)

    assert caught.value.code is public_code
    assert "live-driver-secret" not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert client.closed is True


def test_configured_source_rejects_wrong_source_and_missing_mapping_before_network(
    tmp_path: Path,
    # Keep the monkeypatch input explicit in the test configured source rejects wrong
    # source and missing mapping before network contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test configured source rejects wrong source and missing mapping before
    # network workflow in explicit, reviewable steps.
    settings = _settings(tmp_path / "state")

    def reject_network(**_: object) -> None:
        raise AssertionError("invalid local requests must not connect")

    monkeypatch.setattr(source_module.clickhouse_connect, "get_client", reject_network)
    source = ConfiguredClickHouseSource(settings, ())

    # Acquire raises, value error and pytest at an explicit test configured source rejects
    # wrong source and missing mapping before network context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValueError, match="unknown source"):
        source.list_capabilities(SourceId("other-indexer"))
    with pytest.raises(RuntimeError, match="mapping is not configured"):
        source.inspect_metadata(SourceId("fixture-indexer"))
