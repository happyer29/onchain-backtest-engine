# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Import localfs at the visible module dependency boundary.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.source.in_memory import InMemorySourceReader
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import (
    # Include artifact draft so the models dependency remains explicit.
    ArtifactDraft,
    ArtifactKind,
    CapabilityDescriptor,
    CapabilityStream,
    SourceColumn,
    # Include source metadata so the models dependency remains explicit.
    SourceMetadata,
    SourceTable,
)
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection

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
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId


# Define test source inspection is committed without connection details as one focused
# operation with an explicit boundary.
def test_source_inspection_is_committed_without_connection_details(tmp_path: Path) -> None:
    # Execute the test source inspection is committed without connection details workflow
    # in explicit, reviewable steps.
    source_id = SourceId("indexer-a")
    capability_id = CapabilityId("swaps.v1")
    fidelity = SourceFidelity(
        identity=IdentityFidelity.CANDIDATE,
        ordering=OrderingFidelity.TRANSACTION_PARTIAL,
        # Pass state explicitly so SourceFidelity receives a reviewable candidate and
        # transaction partial input in test source inspection is committed without
        # connection details.
        state=StateFidelity.AFTER_ONLY,
        fees=FeesFidelity.TOTAL_ONLY,
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.BEST_EFFORT,
        # Complete SourceFidelity only after its candidate and transaction partial inputs are
        # visible in test source inspection is committed without connection details.
    )
    metadata = SourceMetadata(
        source_id=source_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Pass server version explicitly so SourceMetadata receives a reviewable 6 and
        # swaps input in test source inspection is committed without connection details.
        server_version="24.6",
        tables=(
            SourceTable(
                name="default.swaps",
                engine="MergeTree",
                # Pass partition key explicitly so SourceTable receives a reviewable swaps
                # and merge tree input in test source inspection is committed without
                # connection details.
                partition_key="day",
                sorting_key="(slot, tx_idx)",
                columns=(SourceColumn("slot", "UInt64", False),),
            ),
        ),
        # Pass capabilities explicitly so SourceMetadata receives a reviewable 6 and swaps
        # input in test source inspection is committed without connection details.
        capabilities=(
            CapabilityDescriptor(
                capability_id=capability_id,
                protocol="test",
                protocol_version="1",
                # Pass schema version explicitly so CapabilityDescriptor receives a
                # reviewable test and 1 input in test source inspection is committed
                # without connection details.
                schema_version="1",
                stream=CapabilityStream.PUMP_CURVE_TRADE,
                columns=("block_ordinal",),
                mandatory_columns=("block_ordinal",),
                fidelity=fidelity,
                # Complete CapabilityDescriptor only after its test and 1 inputs are visible
                # in test source inspection is committed without connection details.
            ),
        ),
    )
    reader = InMemorySourceReader(metadata, {capability_id: ()})

    def clock() -> datetime:
        # Return the completed clock result without a hidden fallback.
        return datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    artifacts = LocalArtifactRepository(tmp_path / "var")
    use_case = StoreSourceInspection(InspectSource(reader, now=clock), artifacts)

    result = use_case.execute(InspectSourceRequest(source_id))

    handle = artifacts.open_committed(result.artifact.artifact_id)
    # Keep expected failures inside the test source inspection is committed without
    # connection details error boundary.
    try:
        # Perform the protected test source inspection is committed without connection
        # details operation before explicit failure handling.
        with handle.open_binary("inspection.json") as stream:
            payload = json.load(stream)
    finally:
        handle.close()
    assert payload["schema_fingerprint"] == result.inspection.schema_fingerprint.value
    # Verify payload['version'] == 5 before this scenario is accepted.
    assert payload["version"] == 5
    assert payload["evidence_receipts"] == []
    assert payload["network_id"] == SOLANA_MAINNET_NETWORK_ID.value
    assert payload["position_schema_id"] == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID.value
    assert payload["capability_mapping_digest"]
    # Assemble serialized once so the test source inspection is committed without
    # connection details workflow shares one value.
    serialized = json.dumps(payload).lower()
    assert "password" not in serialized
    assert "host" not in serialized

    loaded = ArtifactSourceInspectionLoader(artifacts).load(result.artifact.artifact_id)
    assert loaded == result.inspection


# Define test loader rejects legacy unpinned inspection schema as one focused operation
# with an explicit boundary.
def test_loader_rejects_legacy_unpinned_inspection_schema(tmp_path: Path) -> None:
    # Execute the test loader rejects legacy unpinned inspection schema workflow in
    # explicit, reviewable steps.
    artifacts = LocalArtifactRepository(tmp_path / "var")
    writer = artifacts.stage(
        ArtifactDraft(
            kind=ArtifactKind.SOURCE_INSPECTION,
            build_key=ContentDigest("1" * 64),
            # Complete ArtifactDraft only after its 1 and source inspection inputs are visible
            # in test loader rejects legacy unpinned inspection schema.
        )
    )
    with writer.open_binary("inspection.json") as stream:
        stream.write(b"{}")
    legacy = writer.commit(
        # Pass artifact schema explicitly into commit within test loader rejects legacy
        # unpinned inspection schema.
        b'{"artifact_schema":"source-inspection/v1","inspection_file":"inspection.json"}'
    )

    with pytest.raises(ReprepareRequiredError):
        ArtifactSourceInspectionLoader(artifacts).load(legacy.artifact_id)
