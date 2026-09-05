"""Opt-in smoke test for an explicitly configured read-only ClickHouse."""

from __future__ import annotations

import os

import clickhouse_connect
import pytest

from backtest.adapters.source.clickhouse import (
    # Include click house capability so the clickhouse dependency remains explicit.
    ClickHouseCapability,
    ClickHouseSourceReader,
)
from backtest.application.models import CapabilityDescriptor, CapabilityStream
from backtest.application.source_fingerprint import source_schema_fingerprint

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
from backtest.domain.identifiers import CapabilityId, NetworkId, PositionSchemaId, SourceId

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("BACKTEST_RUN_LIVE_CLICKHOUSE") != "1",
        # Pass reason explicitly so skipif receives a reviewable 1 and backtest run live
        # clickhouse input in module.
        reason="set BACKTEST_RUN_LIVE_CLICKHOUSE=1 for the external read-only smoke test",
    ),
]


def _required_environment(name: str) -> str:
    # Execute the required environment workflow in explicit, reviewable steps.
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for the live ClickHouse test")
    return value


def test_live_metadata_inspection_is_explicitly_opt_in() -> None:
    # Execute the test live metadata inspection is explicitly opt in workflow in explicit,
    # reviewable steps.
    host = _required_environment("BACKTEST_CLICKHOUSE_HOST")
    username = _required_environment("BACKTEST_CLICKHOUSE_USER")
    password = _required_environment("BACKTEST_CLICKHOUSE_PASSWORD")
    database = _required_environment("BACKTEST_CLICKHOUSE_DATABASE")
    table = _required_environment("BACKTEST_CLICKHOUSE_TABLE")
    # Assemble slot column once so the test live metadata inspection is explicitly opt in
    # workflow shares one value.
    slot_column = _required_environment("BACKTEST_CLICKHOUSE_SLOT_COLUMN")
    physical_columns = tuple(
        column.strip()
        for column in _required_environment("BACKTEST_CLICKHOUSE_COLUMNS").split(",")
        if column.strip()
        # Complete tuple only after its , and backtest clickhouse columns inputs are visible
        # in test live metadata inspection is explicitly opt in.
    )
    if slot_column not in physical_columns:
        pytest.skip("BACKTEST_CLICKHOUSE_COLUMNS must include the slot column")
    logical_columns = tuple(
        "block_ordinal" if column == slot_column else column
        # Pass column explicitly so tuple receives a reviewable block ordinal and column
        # input in test live metadata inspection is explicitly opt in.
        for column in physical_columns
        # Complete tuple only after its block ordinal and column inputs are visible in test
        # live metadata inspection is explicitly opt in.
    )
    if len(set(logical_columns)) != len(logical_columns):
        pytest.skip("the slot mapping collides with an existing block_ordinal column")
    network_id = NetworkId(_required_environment("BACKTEST_NETWORK_ID"))
    position_schema_id = PositionSchemaId(_required_environment("BACKTEST_POSITION_SCHEMA_ID"))

    # Assemble descriptor once so the test live metadata inspection is explicitly opt in
    # workflow shares one value.
    descriptor = CapabilityDescriptor(
        capability_id=CapabilityId("live.inspection.v1"),
        protocol="live-inspection",
        protocol_version="unknown",
        schema_version="discovered",
        # Pass stream explicitly so CapabilityDescriptor receives a reviewable v1 and
        # live-inspection input in test live metadata inspection is explicitly opt in.
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        columns=logical_columns,
        mandatory_columns=("block_ordinal",),
        fidelity=SourceFidelity(
            IdentityFidelity.UNKNOWN,
            # Pass ordering fidelity explicitly so SourceFidelity receives a reviewable
            # unknown and none input in test live metadata inspection is explicitly opt
            # in.
            OrderingFidelity.UNKNOWN,
            StateFidelity.NONE,
            FeesFidelity.UNKNOWN,
            ChainFinality.UNKNOWN,
            IngestionCompleteness.UNKNOWN,
            # Pass source consistency explicitly so SourceFidelity receives a reviewable
            # unknown and none input in test live metadata inspection is explicitly opt
            # in.
            SourceConsistency.UNKNOWN,
        ),
    )
    client = clickhouse_connect.get_client(
        host=host,
        # Keep the get and backtest clickhouse port int step visible while building
        # client.
        port=int(os.environ.get("BACKTEST_CLICKHOUSE_PORT", "8123")),
        username=username,
        password=password,
        database=database,
        connect_timeout=5,
        # Pass send receive timeout explicitly so get_client receives a reviewable
        # backtest clickhouse port and 8123 input in test live metadata inspection is
        # explicitly opt in.
        send_receive_timeout=30,
    )
    try:
        # Perform the protected test live metadata inspection is explicitly opt in
        # operation before explicit failure handling.
        reader = ClickHouseSourceReader(
            client=client,
            source_id=SourceId("live-indexer"),
            capabilities=(
                ClickHouseCapability(
                    # Pass descriptor explicitly so ClickHouseCapability receives a
                    # reviewable block ordinal and dict input in test live metadata
                    # inspection is explicitly opt in.
                    descriptor=descriptor,
                    network_id=network_id,
                    position_schema_id=position_schema_id,
                    database=database,
                    table=table,
                    # Keep the logical columns and physical columns dict step visible
                    # while building reader.
                    logical_to_physical=dict(zip(logical_columns, physical_columns, strict=True)),
                    logical_block_ordinal_column="block_ordinal",
                ),
            ),
        )
        # Assemble metadata once so the test live metadata inspection is explicitly opt in
        # workflow shares one value.
        metadata = reader.inspect_metadata(SourceId("live-indexer"))
        assert metadata.tables
        assert metadata.server_version
        assert source_schema_fingerprint(metadata).hex
    finally:
        # Invoke close as a visible step within the test live metadata inspection is
        # explicitly opt in workflow.
        client.close()
