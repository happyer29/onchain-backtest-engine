# Declare this module's dependencies and contracts before execution.
from pathlib import Path

import pytest

from backtest.adapters.source.clickhouse.capability_config import (
    CAPABILITY_CONFIG_SCHEMA_VERSION,
    CapabilityConfigError,
    # Include load clickhouse capabilities so the capability config dependency remains
    # explicit.
    load_clickhouse_capabilities,
    parse_clickhouse_capabilities,
)
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import CapabilityStream, EvidenceStatus

# Import projector config at the visible module dependency boundary.
from backtest.bootstrap.projector_config import (
    PROJECTION_CONFIG_SCHEMA_VERSION,
    ProjectorConfigError,
    load_projection_declarations,
    load_projection_specs,
    # Close the projector config import after its required symbols are visible.
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import EventKindName


def _repository_root() -> Path:
    return Path(__file__).parents[4]


def test_secret_free_pumpfun_examples_are_strict_and_structurally_loadable() -> None:
    # Execute the test secret free pumpfun examples are strict and structurally loadable
    # workflow in explicit, reviewable steps.
    root = _repository_root()
    capabilities = load_clickhouse_capabilities(
        root / "configs" / "indexer-capabilities.example.toml"
    )
    configuration = load_projection_declarations(
        # Pass root explicitly so load_projection_declarations receives a reviewable toml
        # and configs input in test secret free pumpfun examples are strict and
        # structurally loadable.
        root / "configs" / "indexer-projections.example.toml",
        capabilities,
    )

    assert CAPABILITY_CONFIG_SCHEMA_VERSION == 2
    assert PROJECTION_CONFIG_SCHEMA_VERSION == 2
    # Verify the network id, solana mainnet network id and configuration relationship
    # before this scenario is accepted.
    assert configuration.network_id == SOLANA_MAINNET_NETWORK_ID
    assert configuration.position_schema_id == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
    assert {item.descriptor.stream for item in capabilities} == set(CapabilityStream)
    assert {item.event_kind for item in configuration.declarations} == {
        EventKindName.BLOCK,
        # Keep the event kind name expectation tied to event kind, block and token launch
        # in this scenario.
        EventKindName.TOKEN_LAUNCH,
        EventKindName.VENUE_TRADE,
        EventKindName.VENUE_LIFECYCLE,
    }
    assert all(
        # Pass item explicitly so all receives a reviewable block time monotone and
        # unknown input in test secret free pumpfun examples are strict and structurally
        # loadable.
        item.descriptor.proofs.block_time_monotone is EvidenceStatus.UNKNOWN
        for item in capabilities
    )


def test_example_cannot_resolve_to_the_legacy_reference_projector() -> None:
    # Execute the test example cannot resolve to the legacy reference projector workflow
    # in explicit, reviewable steps.
    root = _repository_root()
    capabilities = load_clickhouse_capabilities(
        root / "configs" / "indexer-capabilities.example.toml"
    )

    with pytest.raises(ProjectorConfigError, match=r"not installed|not supported"):
        # Keep raises, projector config error and pytest active only for the bounded test
        # example cannot resolve to the legacy reference projector operation.
        load_projection_specs(
            root / "configs" / "indexer-projections.example.toml",
            capabilities,
        )


def test_legacy_capability_and_projection_shapes_require_reprepare(tmp_path: Path) -> None:
    # Execute the test legacy capability and projection shapes require reprepare workflow
    # in explicit, reviewable steps.
    with pytest.raises(ReprepareRequiredError) as capability_error:
        # Keep raises, reprepare required error and pytest active only for the bounded
        # test legacy capability and projection shapes require reprepare operation.
        parse_clickhouse_capabilities(
            'format = "backtest.clickhouse-capabilities"\nschema_version = 1\n'
        )
    assert capability_error.value.artifact_contract == "backtest.clickhouse-capabilities/v1"

    projection = tmp_path / "legacy.toml"
    # Invoke write_text for protocol-projections" schema version = 1 and utf-8 as a
    # visible test legacy capability and projection shapes require reprepare step.
    projection.write_text(
        'format = "backtest.protocol-projections"\nschema_version = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ReprepareRequiredError) as projection_error:
        # Invoke load_projection_declarations for projection as a visible test legacy
        # capability and projection shapes require reprepare step.
        load_projection_declarations(projection, ())
    assert projection_error.value.artifact_contract == "backtest.protocol-projections/v1"


def test_unknown_root_secret_is_rejected_without_echoing_value() -> None:
    # Execute the test unknown root secret is rejected without echoing value workflow in
    # explicit, reviewable steps.
    example = (_repository_root() / "configs" / "indexer-capabilities.example.toml").read_text(
        encoding="utf-8"
    )
    document = example.replace(
        'position_schema_id = "block32-transaction32-v1"',
        # Pass position schema id explicitly so replace receives a reviewable position
        # schema id = "block32-transaction32-v1" input in test unknown root secret is
        # rejected without echoing value.
        'position_schema_id = "block32-transaction32-v1"\npassword = "plain-secret"',
        1,
    )

    with pytest.raises(CapabilityConfigError) as caught:
        parse_clickhouse_capabilities(document)

    # Verify 'password' in str(caught.value) before this scenario is accepted.
    assert "password" in str(caught.value)
    assert "plain-secret" not in str(caught.value)
