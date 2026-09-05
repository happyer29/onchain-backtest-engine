# Declare this module's dependencies and contracts before execution.
from dataclasses import replace

import pytest

from backtest.adapters.source.in_memory import InMemorySourceReader
from backtest.application.models import (
    CapabilityDescriptor,
    # Include capability stream so the models dependency remains explicit.
    CapabilityStream,
    DatasetShard,
    ExtractionRequest,
    QueryLimits,
    SourceMetadata,
    # Close the models import after its required symbols are visible.
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    IdentityFidelity,
    IngestionCompleteness,
    # Include ordering fidelity so the fidelity dependency remains explicit.
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange


def _descriptor() -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    return CapabilityDescriptor(
        capability_id=CapabilityId("events.v1"),
        protocol="fixture",
        protocol_version="1",
        schema_version="1",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # fixture input in descriptor.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=("block_ordinal", "value"),
        mandatory_columns=("block_ordinal",),
        fidelity=SourceFidelity(
            IdentityFidelity.UNKNOWN,
            # Pass ordering fidelity explicitly so SourceFidelity receives a reviewable
            # unknown and none input in descriptor.
            OrderingFidelity.UNKNOWN,
            StateFidelity.NONE,
            FeesFidelity.UNKNOWN,
            ChainFinality.UNKNOWN,
            IngestionCompleteness.UNKNOWN,
            # Pass source consistency explicitly so SourceFidelity receives a reviewable
            # unknown and none input in descriptor.
            SourceConsistency.UNKNOWN,
        ),
    )


def _metadata() -> SourceMetadata:
    # Execute the metadata workflow in explicit, reviewable steps.
    return SourceMetadata(
        source_id=SourceId("memory"),
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        server_version="fixture/1",
        # Pass tables explicitly so SourceMetadata receives a reviewable memory and
        # fixture/1 input in metadata.
        tables=(),
        capabilities=(_descriptor(),),
    )


def _request(*, columns: tuple[str, ...] = ("block_ordinal", "value")) -> ExtractionRequest:
    # Execute the request workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        1,
        3,
    )
    return ExtractionRequest(
        dataset_spec_id=ContentDigest("sha256:" + "a" * 64),
        shard=DatasetShard(
            ordinal=0,
            capability_id=CapabilityId("events.v1"),
            # Include block range in the completed request result.
            block_range=block_range,
            columns=columns,
        ),
        decision_range=block_range,
        query_limits=QueryLimits(1, 1024, 10),
    )


# Define test rejects rows without mandatory values as one focused operation with an
# explicit boundary.
def test_rejects_rows_without_mandatory_values() -> None:
    # Execute the test rejects rows without mandatory values workflow in explicit,
    # reviewable steps.
    with pytest.raises(ValueError, match="mandatory columns"):
        # Keep raises, value error and pytest active only for the bounded test rejects
        # rows without mandatory values operation.
        InMemorySourceReader(
            _metadata(),
            {CapabilityId("events.v1"): ({"value": "missing-block"},)},
        )


def test_rejects_unadvertised_projection() -> None:
    # Execute the test rejects unadvertised projection workflow in explicit, reviewable
    # steps.
    reader = InMemorySourceReader(
        _metadata(),
        {CapabilityId("events.v1"): ({"block_ordinal": 1, "value": "ok"},)},
    )
    request = _request()
    # Assemble bad shard once so the test rejects unadvertised projection workflow shares
    # one value.
    bad_shard = replace(request.shard, columns=("block_ordinal", "unknown"))

    with pytest.raises(ValueError, match="unadvertised"):
        tuple(reader.scan(replace(request, shard=bad_shard)))


def test_unknown_source_fails_closed() -> None:
    # Execute the test unknown source fails closed workflow in explicit, reviewable steps.
    reader = InMemorySourceReader(_metadata(), {CapabilityId("events.v1"): ()})

    with pytest.raises(ValueError, match="unknown source"):
        reader.inspect_metadata(SourceId("another-source"))
