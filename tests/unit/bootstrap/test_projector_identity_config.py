# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backtest.adapters.source.clickhouse import (
    # Include click house capability so the clickhouse dependency remains explicit.
    ClickHouseCapability,
    load_clickhouse_capabilities,
)
from backtest.application.models import CapabilityDescriptor, CapabilityStream
from backtest.bootstrap.projector_config import (
    # Include projector config error so the projector config dependency remains explicit.
    ProjectorConfigError,
    load_projection_declarations,
    load_projection_specs,
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
from backtest.domain.identifiers import CapabilityId


def test_repository_pump_capability_and_projection_examples_form_a_structural_pair() -> None:
    # Execute the test repository pump capability and projection examples form a
    # structural pair workflow in explicit, reviewable steps.
    repository_root = Path(__file__).parents[3]
    capabilities = load_clickhouse_capabilities(
        repository_root / "configs" / "indexer-capabilities.example.toml"
    )

    configuration = load_projection_declarations(
        # Pass repository root explicitly so load_projection_declarations receives a
        # reviewable toml and configs input in test repository pump capability and
        # projection examples form a structural pair.
        repository_root / "configs" / "indexer-projections.example.toml",
        capabilities,
    )

    assert len(configuration.declarations) == 4
    assert {
        # Keep the item expectation tied to value, pump-launch-state-v1 and pump-
        # lifecycle-state-v1 in this scenario.
        item.protocol_payload_schema_id.value
        for item in configuration.declarations
        if item.protocol_payload_schema_id is not None
    } == {
        "pump-launch-state-v1",
        # Keep the pump-lifecycle-state-v1 expectation tied to value, pump-launch-state-v1
        # and pump-lifecycle-state-v1 in this scenario.
        "pump-lifecycle-state-v1",
        "pump-trade-state-v1",
    }


def test_projector_config_inherits_proven_total_key_and_identity_fidelity(
    tmp_path: Path,
    # Close the test projector config inherits proven total key and identity fidelity
    # signature after its explicit inputs.
) -> None:
    # Execute the test projector config inherits proven total key and identity fidelity
    # workflow in explicit, reviewable steps.
    capability = _capability(_descriptor())
    path = _projection_config(tmp_path)

    spec = load_projection_specs(path, (capability,))[0]

    assert spec.identity_fidelity is IdentityFidelity.EXACT
    assert spec.source_total_key == ("block_ordinal", "row_id")
    # Verify the source total key is proven and spec relationship before this scenario is
    # accepted.
    assert spec.source_total_key_is_proven is True
    assert spec.identity_document()["source_total_key_is_proven"] is True


def test_exact_identity_without_source_total_key_fails_at_composition(
    tmp_path: Path,
) -> None:
    # Execute the test exact identity without source total key fails at composition
    # workflow in explicit, reviewable steps.
    descriptor = replace(
        _descriptor(),
        total_key=(),
        keyset_key_is_proven=False,
    )
    # Assemble capability once so the test exact identity without source total key fails
    # at composition workflow shares one value.
    capability = _capability(descriptor)

    with pytest.raises(ProjectorConfigError, match="exact source identity requires"):
        load_projection_specs(_projection_config(tmp_path), (capability,))


def _descriptor() -> CapabilityDescriptor:
    # Execute the descriptor workflow in explicit, reviewable steps.
    columns = (
        "block_ordinal",
        "block_time",
        "transaction_count",
        "block_hash",
        # Keep the row id component named inside the columns contract.
        "row_id",
    )
    return CapabilityDescriptor(
        capability_id=CapabilityId("fixture.block-clock.v2"),
        protocol="solana",
        # Pass protocol version explicitly so CapabilityDescriptor receives a reviewable
        # v2 and solana input in descriptor.
        protocol_version="1",
        schema_version="2",
        stream=CapabilityStream.BLOCK_CLOCK,
        columns=columns,
        mandatory_columns=columns,
        # Include fidelity in the completed descriptor result.
        fidelity=SourceFidelity(
            identity=IdentityFidelity.EXACT,
            ordering=OrderingFidelity.INSTRUCTION_EXACT,
            state=StateFidelity.AFTER_ONLY,
            fees=FeesFidelity.TOTAL_ONLY,
            # Pass chain finality explicitly so SourceFidelity receives a reviewable exact
            # and instruction exact input in descriptor.
            chain_finality=ChainFinality.UNKNOWN,
            completeness=IngestionCompleteness.UNKNOWN,
            consistency=SourceConsistency.UNKNOWN,
        ),
        total_key=("block_ordinal", "row_id"),
        # Pass keyset key is proven explicitly so CapabilityDescriptor receives a
        # reviewable v2 and solana input in descriptor.
        keyset_key_is_proven=True,
    )


def _capability(descriptor: CapabilityDescriptor) -> ClickHouseCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    return ClickHouseCapability(
        descriptor=descriptor,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        database="default",
        # Pass table explicitly so ClickHouseCapability receives a reviewable default and
        # fixture blocks input in capability.
        table="fixture_blocks",
        logical_block_ordinal_column="block_ordinal",
        logical_to_physical={column: column for column in descriptor.columns},
        order_by=(("block_ordinal", "row_id") if descriptor.keyset_key_is_proven else ()),
    )


# Define projection config as one focused operation with an explicit boundary.
def _projection_config(tmp_path: Path) -> Path:
    # Execute the projection config workflow in explicit, reviewable steps.
    path = tmp_path / "projection.toml"
    path.write_text(
        """
format = "backtest.protocol-projections"
schema_version = 2
network_id = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
position_schema_id = "block32-transaction32-v1"

[[projections]]
capability_id = "fixture.block-clock.v2"
event_kind = "BLOCK"

[projections.columns]
block_ordinal = "block_ordinal"
block_time = "block_time"
transaction_count = "transaction_count"
block_hash = "block_hash"
""".strip(),
        encoding="utf-8",
    )
    # Return the completed projection config result without a hidden fallback.
    return path
