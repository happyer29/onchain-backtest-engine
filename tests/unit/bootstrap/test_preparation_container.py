# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import backtest.bootstrap.preparation_container as preparation_container_module
from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import clickhouse at the visible module dependency boundary.
from backtest.adapters.source.clickhouse import (
    ClickHouseCapability,
    clickhouse_capability_mapping_digest,
)
from backtest.adapters.source.clickhouse.query import query_template_digest

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import ReusableCanonicalDistribution
from backtest.application.models import (
    DATASET_SPEC_VERSION,
    CapabilityDescriptor,
    CapabilityExtractionRange,
    # Include capability stream so the models dependency remains explicit.
    CapabilityStream,
    DatasetPlan,
    DatasetShard,
    DatasetSpec,
    PlannedCapability,
    QueryLimits,
    # Include source column so the models dependency remains explicit.
    SourceColumn,
    SourceMetadata,
    SourceTable,
    dataset_spec_identity_digest,
)

# Import source at the visible module dependency boundary.
from backtest.application.ports.source import SourceMetadataReader
from backtest.application.source_fingerprint import source_schema_fingerprint
from backtest.application.use_cases.prepare_dataset import PrepareDataset
from backtest.bootstrap.config import PathSettings, Settings, SourceSettings
from backtest.bootstrap.preparation_container import (
    # Include preparation container so the preparation container dependency remains
    # explicit.
    PreparationContainer,
    SourceMetadataPreflightError,
    SourceSchemaDriftError,
    build_preparation_container,
)
from backtest.domain.chain import (
    # Include block32 transaction32 position schema id so the chain dependency remains
    # explicit.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    ChainFinality,
    # Include fees fidelity so the fidelity dependency remains explicit.
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    # Include source fidelity so the fidelity dependency remains explicit.
    SourceFidelity,
    StateFidelity,
)
from backtest.domain.identifiers import ArtifactId, CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange


# Keep the metadata source contract and validation rules together.
class _MetadataSource:
    def __init__(self, metadata: SourceMetadata | BaseException) -> None:
        # Execute the metadata source init workflow in explicit, reviewable steps.
        self.metadata = metadata
        self.inspect_calls = 0

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        # Execute the metadata source inspect metadata workflow in explicit, reviewable
        # steps.
        self.inspect_calls += 1
        if isinstance(self.metadata, BaseException):
            raise self.metadata
        assert source_id == self.metadata.source_id
        return self.metadata


# Define fidelity as one focused operation with an explicit boundary.
def _fidelity() -> SourceFidelity:
    # Execute the fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.EXACT,
        ordering=OrderingFidelity.TRANSACTION_EXACT,
        state=StateFidelity.NONE,
        fees=FeesFidelity.UNKNOWN,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable exact and
        # transaction exact input in fidelity.
        chain_finality=ChainFinality.FINALIZED,
        completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
        consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
    )


def _fixture() -> tuple[
    # Keep the dataset plan input explicit in the fixture contract.
    DatasetPlan,
    tuple[ClickHouseCapability, ...],
    SourceMetadata,
]:
    # Execute the fixture workflow in explicit, reviewable steps.
    descriptor = CapabilityDescriptor(
        capability_id=CapabilityId("fixture.swaps.v1"),
        protocol="fixture",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # fixture input in fixture.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("block_ordinal", "signature"),
        mandatory_columns=("block_ordinal", "signature"),
        fidelity=_fidelity(),
        total_key=("signature",),
        # Pass keyset key is proven explicitly so CapabilityDescriptor receives a
        # reviewable v1 and fixture input in fixture.
        keyset_key_is_proven=True,
    )
    capability = ClickHouseCapability(
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so ClickHouseCapability receives a reviewable
        # default and swaps input in fixture.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        table="swaps",
        logical_to_physical={"block_ordinal": "slot", "signature": "signature"},
        order_by=("block_ordinal", "signature"),
        # Complete ClickHouseCapability only after its default and swaps inputs are visible in
        # fixture.
    )
    capabilities = (capability,)
    mapping_digest = clickhouse_capability_mapping_digest(capabilities)
    template_digest = query_template_digest()
    metadata = SourceMetadata(
        # Keep the fixture-indexer SourceId step visible while building metadata.
        source_id=SourceId("fixture-indexer"),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        server_version="24.6.1",
        tables=(
            # Keep the source table and swaps SourceTable step visible while building
            # metadata.
            SourceTable(
                name="default.swaps",
                engine="MergeTree",
                partition_key="",
                sorting_key="(slot, signature)",
                # Pass columns explicitly so SourceTable receives a reviewable swaps and
                # merge tree input in fixture.
                columns=(
                    SourceColumn("signature", "String", False),
                    SourceColumn("slot", "UInt64", False),
                ),
            ),
            # Complete SourceMetadata only after its fixture-indexer and 1 inputs are visible
            # in fixture.
        ),
        capabilities=(descriptor,),
        capability_mapping_digest=mapping_digest,
        query_template_digest=template_digest,
    )
    # Assemble planned once so the fixture workflow shares one value.
    planned = PlannedCapability(
        capability_id=descriptor.capability_id,
        protocol=descriptor.protocol,
        protocol_version=descriptor.protocol_version,
        schema_version=descriptor.schema_version,
        # Pass stream explicitly so PlannedCapability receives a reviewable capability id
        # and protocol input in fixture.
        stream=descriptor.stream,
        columns=descriptor.columns,
        fidelity=descriptor.fidelity,
        proofs=descriptor.proofs,
        total_key=descriptor.total_key,
        # Pass keyset key is proven explicitly so PlannedCapability receives a reviewable
        # capability id and protocol input in fixture.
        keyset_key_is_proven=descriptor.keyset_key_is_proven,
        utc_pruning_column=None,
        utc_pruning_is_proven=False,
    )
    block_range = BlockRange(
        # Pass solana mainnet network id explicitly so BlockRange receives a reviewable
        # solana mainnet network id and block32 transaction32 position schema id input in
        # fixture.
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        10,
        20,
    )
    # Assemble shard once so the fixture workflow shares one value.
    shard = DatasetShard(0, descriptor.capability_id, block_range, descriptor.columns)
    identity: dict[str, Any] = {
        "spec_version": DATASET_SPEC_VERSION,
        "source_id": metadata.source_id,
        "source_inspection_artifact_id": ArtifactId("a" * 64),
        # Register metadata through source_schema_fingerprint so the identity table
        # remains scannable.
        "source_schema_fingerprint": source_schema_fingerprint(metadata),
        "capability_mapping_digest": mapping_digest,
        "query_template_digest": template_digest,
        "network_id": SOLANA_MAINNET_NETWORK_ID,
        "position_schema_id": BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Keep the decision range component named inside the identity contract.
        "decision_range": block_range,
        "settlement_tail": None,
        "warmup_blocks": 0,
        "evidence_contracts": (),
        "capabilities": (planned,),
        # Register capability id through CapabilityExtractionRange so the identity table
        # remains scannable.
        "capability_ranges": (CapabilityExtractionRange(descriptor.capability_id, block_range),),
        "cut_evidence": (),
        "shards": (shard,),
    }
    spec = DatasetSpec(
        # Keep the dataset spec identity digest and identity dataset_spec_identity_digest
        # step visible while building spec.
        spec_id=dataset_spec_identity_digest(**identity),
        **identity,
    )
    return DatasetPlan(spec, cast(Any, object()), cast(Any, object())), capabilities, metadata


def _container(
    # Keep the source input explicit in the container contract.
    source: _MetadataSource,
    capabilities: tuple[ClickHouseCapability, ...],
) -> PreparationContainer:
    # Execute the container workflow in explicit, reviewable steps.
    return PreparationContainer(
        settings=Settings(source=SourceSettings(source_id="fixture-indexer")),
        artifacts=cast(LocalArtifactRepository, object()),
        capabilities=capabilities,
        source_metadata=cast(SourceMetadataReader, source),
        # Include prepare dataset in the completed container result.
        prepare_dataset=cast(PrepareDataset, object()),
        projector_digest=ContentDigest("c" * 64),
        source_normalizer_digest=None,
    )


def test_remote_scan_requires_fresh_exact_schema_but_full_reuse_stays_offline() -> None:
    # Execute the test remote scan requires fresh exact schema but full reuse stays
    # offline workflow in explicit, reviewable steps.
    plan, capabilities, metadata = _fixture()
    source = _MetadataSource(metadata)
    container = _container(source, capabilities)

    container.validate_execution(
        plan,
        # Pass reusable canonical distribution explicitly to validate_execution for b and
        # reusable canonical distribution.
        (ReusableCanonicalDistribution(0, ArtifactId("b" * 64)),),
    )
    assert source.inspect_calls == 0

    container.validate_execution(plan, ())
    assert source.inspect_calls == 1


# Define test schema drift fails before extraction with a stable error as one focused
# operation with an explicit boundary.
def test_schema_drift_fails_before_extraction_with_a_stable_error() -> None:
    # Execute the test schema drift fails before extraction with a stable error workflow
    # in explicit, reviewable steps.
    plan, capabilities, metadata = _fixture()
    source = _MetadataSource(replace(metadata, server_version="24.7.0"))

    with pytest.raises(SourceSchemaDriftError, match="differs"):
        _container(source, capabilities).validate_execution(plan, ())

    assert source.inspect_calls == 1


# Define test metadata driver failure does not retain credentials or exception context as
# one focused operation with an explicit boundary.
def test_metadata_driver_failure_does_not_retain_credentials_or_exception_context() -> None:
    # Execute the test metadata driver failure does not retain credentials or exception
    # context workflow in explicit, reviewable steps.
    plan, capabilities, _ = _fixture()
    source = _MetadataSource(
        RuntimeError("http://readonly:plain-text-password@secret.example:8123")
    )

    with pytest.raises(SourceMetadataPreflightError) as caught:
        # Invoke validate_execution for plan as a visible test metadata driver failure
        # does not retain credentials or exception context step.
        _container(source, capabilities).validate_execution(plan, ())

    rendered = str(caught.value)
    assert "plain-text-password" not in rendered
    assert "secret.example" not in rendered
    assert caught.value.__cause__ is None
    # Verify caught.value.__context__ is None before this scenario is accepted.
    assert caught.value.__context__ is None


def test_plan_preflight_rejects_projector_and_source_normalizer_drift() -> None:
    _, capabilities, metadata = _fixture()
    projector_digest = ContentDigest("d" * 64)
    normalizer_digest = ContentDigest("e" * 64)
    container = replace(
        _container(_MetadataSource(metadata), capabilities),
        projector_digest=projector_digest,
        source_normalizer_digest=normalizer_digest,
    )
    binding = SimpleNamespace(
        projector_digest=projector_digest,
        normalizer_digest=normalizer_digest,
    )
    spec = SimpleNamespace(
        source_id=SourceId("fixture-indexer"),
        capability_mapping_digest=clickhouse_capability_mapping_digest(capabilities),
        query_template_digest=query_template_digest(),
        source_evidence_binding=binding,
    )

    container.validate_plan(cast(DatasetPlan, SimpleNamespace(spec=spec)))

    wrong_projector = replace(container, projector_digest=ContentDigest("f" * 64))
    with pytest.raises(ValueError, match="another canonical projector"):
        wrong_projector.validate_plan(cast(DatasetPlan, SimpleNamespace(spec=spec)))

    wrong_normalizer = replace(container, source_normalizer_digest=ContentDigest("1" * 64))
    with pytest.raises(ValueError, match="another source normalizer"):
        wrong_normalizer.validate_plan(cast(DatasetPlan, SimpleNamespace(spec=spec)))


def test_preparation_composition_binds_normalized_projector_and_live_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, raw_capabilities, metadata = _fixture()
    raw = raw_capabilities[0]
    normalized = replace(
        raw,
        descriptor=replace(
            raw.descriptor,
            protocol_version="normalized-v1",
            schema_version="normalized-v1",
            columns=("block_ordinal", "signature", "block_time"),
            mandatory_columns=("block_ordinal", "signature", "block_time"),
        ),
        logical_to_physical={
            "block_ordinal": "block_ordinal",
            "signature": "signature",
            "block_time": "block_time",
        },
    )
    mapping_digest = clickhouse_capability_mapping_digest(raw_capabilities)
    fixed_query_digest = ContentDigest("4" * 64)
    normalizer_digest = ContentDigest("5" * 64)
    projector_digest = ContentDigest("6" * 64)
    live = SimpleNamespace(
        raw_capabilities=raw_capabilities,
        metadata_capabilities=(normalized.descriptor,),
        projection_capabilities=(normalized,),
        capability_mapping_digest=mapping_digest,
        query_template_digest=fixed_query_digest,
        normalizer_digest=normalizer_digest,
    )
    settings = Settings(
        paths=PathSettings(data_root=tmp_path / "state"),
        source=SourceSettings(
            source_id=metadata.source_id.value,
            capabilities_file=tmp_path / "capabilities.toml",
            projections_file=tmp_path / "projections.toml",
        ),
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        preparation_container_module,
        "load_clickhouse_capabilities",
        lambda path: raw_capabilities,
    )
    monkeypatch.setattr(
        preparation_container_module,
        "select_clickhouse_query_profile",
        lambda capabilities: object(),
    )
    monkeypatch.setattr(
        preparation_container_module,
        "build_pumpfun_live_source_composition",
        lambda capabilities: live,
    )
    monkeypatch.setattr(preparation_container_module, "apply_thread_limits", lambda threads: None)

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
        return SimpleNamespace(config_digest=projector_digest)

    monkeypatch.setattr(
        preparation_container_module,
        "build_configured_projector",
        build_projector,
    )

    container = build_preparation_container(settings)

    assert container.capabilities == raw_capabilities
    assert container.projector_digest == projector_digest
    assert container.source_normalizer_digest == normalizer_digest
    assert observed["path"] == tmp_path / "projections.toml"
    assert observed["capabilities"] == (normalized,)
    assert observed["source_normalizer_digest"] == normalizer_digest

    request = cast(Any, container.source_metadata).build_evidence_request(
        source_id=metadata.source_id,
        block_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            10,
            20,
        ),
        decision_range=BlockRange(
            SOLANA_MAINNET_NETWORK_ID,
            BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            10,
            18,
        ),
        query_limits=QueryLimits(
            max_execution_seconds=30,
            max_memory_bytes=64 * 1024**2,
            max_result_rows=100_000,
        ),
    )
    assert request.capability_mapping_digest == mapping_digest
    assert request.query_template_digest == fixed_query_digest
    assert request.projector_digest == projector_digest
    assert request.normalizer_digest == normalizer_digest
