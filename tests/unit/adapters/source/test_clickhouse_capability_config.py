# Declare this module's dependencies and contracts before execution.
from datetime import date
from pathlib import Path

import pytest

from backtest.adapters.source.clickhouse.capability_config import (
    CAPABILITY_CONFIG_FORMAT,
    # Include capability config schema version so the capability config dependency remains
    # explicit.
    CAPABILITY_CONFIG_SCHEMA_VERSION,
    CapabilityConfigError,
    load_clickhouse_capabilities,
    parse_clickhouse_capabilities,
)

# Import query at the visible module dependency boundary.
from backtest.adapters.source.clickhouse.query import UtcDateRange
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import CapabilityStream, EvidenceStatus
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    IdentityFidelity,
    OrderingFidelity,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
)
from backtest.domain.identifiers import CapabilityId
from backtest.domain.time import BlockRange

_ROOT = """\
format = "backtest.clickhouse-capabilities"
schema_version = 2
network_id = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
position_schema_id = "block32-transaction32-v1"
"""

# Bind capability once as an explicit module-level contract.
_CAPABILITY = """\
[[capabilities]]
capability_id = "fixture.swaps.v1"
stream = "PUMP_CURVE_TRADE"
protocol = "fixture"
protocol_version = "1"
capability_schema_version = "2"
database = "default"
table = "fixture_swaps"
logical_block_ordinal_column = "block_ordinal"
mandatory_columns = ["block_ordinal", "signature"]
total_key = ["signature", "tx_idx"]
keyset_key_is_proven = true
order_by = ["block_ordinal", "signature", "tx_idx"]

[capabilities.columns]
block_ordinal = "block_slot"
tx_idx = "tx_index"
signature = "tx_signature"
block_date_utc = "block_date_utc"

[capabilities.fidelity]
identity = "CANDIDATE"
ordering = "TRANSACTION_EXACT"
state = "AFTER_ONLY"
fees = "TOTAL_ONLY"
chain_finality = "UNKNOWN"
completeness = "UNKNOWN"
consistency = "BEST_EFFORT"

[capabilities.proofs]
block_time_monotone = "UNKNOWN"
block_time_second_resolution = "UNKNOWN"
bundled_instruction_order = "UNKNOWN"
creation_fields_immutable = "UNKNOWN"
curve_transitions_complete = "UNKNOWN"
failed_transactions_included = "UNKNOWN"
fee_component_rounding_exact = "UNKNOWN"
global_zero_based_transaction_index = "UNKNOWN"
lifecycle_complete = "UNKNOWN"
launch_transaction_success_exact = "UNKNOWN"
skipped_blocks_distinguished = "UNKNOWN"
successful_transactions_included = "UNKNOWN"
vote_transactions_included = "UNKNOWN"
"""

_VALID = _ROOT + _CAPABILITY


def test_parses_versioned_catalog_into_domain_and_adapter_types() -> None:
    # Execute the test parses versioned catalog into domain and adapter types workflow in
    # explicit, reviewable steps.
    capabilities = parse_clickhouse_capabilities(_VALID)

    assert len(capabilities) == 1
    capability = capabilities[0]
    descriptor = capability.descriptor
    assert descriptor.capability_id == CapabilityId("fixture.swaps.v1")
    # Verify the identity, candidate and fidelity relationship before this scenario is
    # accepted.
    assert descriptor.fidelity.identity is IdentityFidelity.CANDIDATE
    assert descriptor.fidelity.ordering is OrderingFidelity.TRANSACTION_EXACT
    assert descriptor.fidelity.consistency is SourceConsistency.BEST_EFFORT
    assert descriptor.stream is CapabilityStream.PUMP_CURVE_TRADE
    assert descriptor.proofs.failed_transactions_included is EvidenceStatus.UNKNOWN
    # Verify the network id, solana mainnet network id and capability relationship before
    # this scenario is accepted.
    assert capability.network_id == SOLANA_MAINNET_NETWORK_ID
    assert capability.position_schema_id == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
    assert capability.database == "default"
    assert capability.table == "fixture_swaps"
    assert capability.physical_column("block_ordinal") == "block_slot"
    # Verify the order by, capability and block ordinal relationship before this scenario
    # is accepted.
    assert capability.order_by == ("block_ordinal", "signature", "tx_idx")
    assert capability.utc_pruning is None


def test_static_configuration_cannot_declare_a_proven_source_claim() -> None:
    # Execute the test static configuration cannot declare a proven source claim workflow
    # in explicit, reviewable steps.
    forged = _VALID.replace(
        'global_zero_based_transaction_index = "UNKNOWN"',
        'global_zero_based_transaction_index = "PROVEN"',
    )

    with pytest.raises(CapabilityConfigError, match="bounded inspection"):
        # Invoke parse_clickhouse_capabilities for forged as a visible test static
        # configuration cannot declare a proven source claim step.
        parse_clickhouse_capabilities(forged)


def test_loads_repository_example_without_claiming_production_fidelity() -> None:
    # Execute the test loads repository example without claiming production fidelity
    # workflow in explicit, reviewable steps.
    repository_root = Path(__file__).parents[4]
    path = repository_root / "configs" / "indexer-capabilities.example.toml"

    capabilities = load_clickhouse_capabilities(path)

    assert CAPABILITY_CONFIG_FORMAT == "backtest.clickhouse-capabilities"
    assert CAPABILITY_CONFIG_SCHEMA_VERSION == 2
    # Verify the stream, capability stream and descriptor relationship before this
    # scenario is accepted.
    assert {item.descriptor.stream for item in capabilities} == set(CapabilityStream)
    assert all(item.network_id == SOLANA_MAINNET_NETWORK_ID for item in capabilities)
    assert all(
        item.position_schema_id == BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID for item in capabilities
    )
    # Verify the identity, unknown and item relationship before this scenario is accepted.
    assert all(
        item.descriptor.fidelity.identity is IdentityFidelity.UNKNOWN for item in capabilities
    )
    assert all(
        item.descriptor.fidelity.ordering is OrderingFidelity.UNKNOWN
        # Pass item explicitly so all receives a reviewable ordering and unknown input in
        # test loads repository example without claiming production fidelity.
        for item in capabilities
        # Complete all only after its ordering and unknown inputs are visible in test loads
        # repository example without claiming production fidelity.
    )
    assert all(
        item.descriptor.fidelity.consistency is SourceConsistency.UNKNOWN for item in capabilities
    )
    assert all(item.descriptor.keyset_key_is_proven is False for item in capabilities)
    # Verify the order by, item and capabilities relationship before this scenario is
    # accepted.
    assert all(item.order_by == () for item in capabilities)


@pytest.mark.parametrize(
    "text, expected",
    (
        (
            # Define test unknown keys are rejected at every structural level as one
            # focused operation with an explicit boundary.
            _VALID.replace(
                "schema_version = 2\n",
                "schema_version = 2\nunexpected_root = true\n",
                1,
            ),
            # Pass root contains unknown keys explicitly so parametrize receives a
            # reviewable text, expected and root contains unknown keys input in test
            # unknown keys are rejected at every structural level.
            "root contains unknown keys",
        ),
        (
            _VALID.replace('table = "fixture_swaps"', 'table = "fixture_swaps"\nport = 8123'),
            "contains unknown keys: port",
            # Complete parametrize only after its text, expected and root contains unknown
            # keys inputs are visible in test unknown keys are rejected at every structural
            # level.
        ),
        (
            _VALID.replace(
                'identity = "CANDIDATE"',
                'identity = "CANDIDATE"\nunexpected = "x"',
                # Complete replace only after its identity = "candidate" and identity =
                # "candidate" unexpected = "x" inputs are visible in test unknown keys are
                # rejected at every structural level.
            ),
            "fidelity contains unknown keys",
        ),
    ),
)
# Define test unknown keys are rejected at every structural level as one focused operation
# with an explicit boundary.
def test_unknown_keys_are_rejected_at_every_structural_level(
    text: str,
    expected: str,
) -> None:
    # Execute the test unknown keys are rejected at every structural level workflow in
    # explicit, reviewable steps.
    with pytest.raises(CapabilityConfigError, match=expected):
        parse_clickhouse_capabilities(text)


@pytest.mark.parametrize(
    "connection_key",
    ("host", "port", "username", "password", "dsn", "url", "token"),
    # Complete parametrize only after its connection key and host inputs are visible in test
    # connection and credential fields are outside the schema.
)
def test_connection_and_credential_fields_are_outside_the_schema(
    connection_key: str,
) -> None:
    # Execute the test connection and credential fields are outside the schema workflow in
    # explicit, reviewable steps.
    text = _VALID.replace(
        'table = "fixture_swaps"',
        f'table = "fixture_swaps"\n{connection_key} = "plain-secret-value"',
    )

    with pytest.raises(CapabilityConfigError) as caught:
        # Invoke parse_clickhouse_capabilities for text as a visible test connection and
        # credential fields are outside the schema step.
        parse_clickhouse_capabilities(text)

    assert connection_key in str(caught.value)
    assert "plain-secret-value" not in str(caught.value)


@pytest.mark.parametrize(
    "replacement",
    # Open the replacement and database = "default; drop table x" payload explicitly for
    # parametrize within test sql identifier syntax is rejected before client creation.
    (
        'database = "default; DROP TABLE x"',
        'database = "default.prod"',
        'database = "`default`"',
        'database = "default -- comment"',
        # Complete parametrize only after its replacement and database = "default; drop table
        # x" inputs are visible in test sql identifier syntax is rejected before client
        # creation.
    ),
)
def test_sql_identifier_syntax_is_rejected_before_client_creation(
    replacement: str,
) -> None:
    # Execute the test sql identifier syntax is rejected before client creation workflow
    # in explicit, reviewable steps.
    text = _VALID.replace('database = "default"', replacement)

    with pytest.raises(CapabilityConfigError, match="safe ClickHouse identifier"):
        parse_clickhouse_capabilities(text)


@pytest.mark.parametrize(
    ("field", "original"),
    # Open the field and original payload explicitly for parametrize within test logical
    # ids and versions reject urls or control syntax.
    (
        ("capability_id", "fixture.swaps.v1"),
        ("protocol", "fixture"),
        ("protocol_version", "1"),
        ("capability_schema_version", "2"),
        # Complete parametrize only after its field and original inputs are visible in test
        # logical ids and versions reject urls or control syntax.
    ),
)
def test_logical_ids_and_versions_reject_urls_or_control_syntax(
    field: str,
    original: str,
    # Close the test logical ids and versions reject urls or control syntax signature after
    # its explicit inputs.
) -> None:
    # Execute the test logical ids and versions reject urls or control syntax workflow in
    # explicit, reviewable steps.
    text = _VALID.replace(
        f'{field} = "{original}"',
        f'{field} = "https://user:plain-secret@example.invalid"',
    )

    with pytest.raises(CapabilityConfigError) as caught:
        # Invoke parse_clickhouse_capabilities for text as a visible test logical ids and
        # versions reject urls or control syntax step.
        parse_clickhouse_capabilities(text)

    assert field in str(caught.value)
    assert "plain-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "schema_line",
    # Open the schema line and schema version = 3 payload explicitly for parametrize
    # within test schema version is exact and typed.
    ("schema_version = 3", 'schema_version = "2"', "schema_version = true"),
)
def test_schema_version_is_exact_and_typed(schema_line: str) -> None:
    # Execute the test schema version is exact and typed workflow in explicit, reviewable
    # steps.
    text = _VALID.replace("schema_version = 2", schema_line, 1)

    with pytest.raises(CapabilityConfigError, match="schema_version"):
        parse_clickhouse_capabilities(text)


def test_legacy_schema_version_requires_reprepare() -> None:
    # Execute the test legacy schema version requires reprepare workflow in explicit,
    # reviewable steps.
    text = _VALID.replace("schema_version = 2", "schema_version = 1", 1)

    with pytest.raises(ReprepareRequiredError) as caught:
        parse_clickhouse_capabilities(text)
    assert caught.value.artifact_contract == "backtest.clickhouse-capabilities/v1"


def test_malformed_toml_error_does_not_echo_input_values() -> None:
    # Execute the test malformed toml error does not echo input values workflow in
    # explicit, reviewable steps.
    malformed = 'format = "https://user:plain-secret@example.invalid"\ninvalid = ['

    with pytest.raises(CapabilityConfigError) as caught:
        parse_clickhouse_capabilities(malformed)

    assert str(caught.value) == "capability configuration is not valid TOML"
    assert "plain-secret" not in str(caught.value)


# Define test invalid fidelity reports allowed values but not input as one focused
# operation with an explicit boundary.
def test_invalid_fidelity_reports_allowed_values_but_not_input() -> None:
    # Execute the test invalid fidelity reports allowed values but not input workflow in
    # explicit, reviewable steps.
    text = _VALID.replace(
        'identity = "CANDIDATE"',
        'identity = "plain-secret-value"',
    )

    with pytest.raises(CapabilityConfigError) as caught:
        # Invoke parse_clickhouse_capabilities for text as a visible test invalid fidelity
        # reports allowed values but not input step.
        parse_clickhouse_capabilities(text)

    assert "UNKNOWN, AMBIGUOUS, CANDIDATE, EXACT" in str(caught.value)
    assert "plain-secret-value" not in str(caught.value)


def test_duplicate_capability_ids_are_rejected() -> None:
    # Execute the test duplicate capability ids are rejected workflow in explicit,
    # reviewable steps.
    with pytest.raises(CapabilityConfigError, match="IDs must be unique"):
        parse_clickhouse_capabilities(_ROOT + _CAPABILITY + _CAPABILITY)


def test_proven_utc_pruning_requires_out_of_band_resolver() -> None:
    # Execute the test proven utc pruning requires out of band resolver workflow in
    # explicit, reviewable steps.
    text = (
        _VALID
        + """

[capabilities.utc_pruning]
logical_column = "block_date_utc"
is_proven = true
"""
    )

    with pytest.raises(CapabilityConfigError, match="no resolver was registered"):
        # Invoke parse_clickhouse_capabilities for text as a visible test proven utc
        # pruning requires out of band resolver step.
        parse_clickhouse_capabilities(text)


def test_proven_utc_pruning_binds_only_registered_resolver() -> None:
    # Execute the test proven utc pruning binds only registered resolver workflow in
    # explicit, reviewable steps.
    text = (
        _VALID
        + """

[capabilities.utc_pruning]
logical_column = "block_date_utc"
is_proven = true
"""
    )
    capability_id = CapabilityId("fixture.swaps.v1")

    # Assemble (capability,) once so the test proven utc pruning binds only registered
    # resolver workflow shares one value.
    (capability,) = parse_clickhouse_capabilities(
        text,
        utc_pruning_resolvers={
            capability_id: lambda _: UtcDateRange(
                date(2026, 8, 30),
                # Keep the date date step visible while building (capability,).
                date(2026, 9, 1),
            )
        },
    )

    assert capability.descriptor.utc_pruning_column == "block_date_utc"
    # Verify the utc pruning is proven, descriptor and capability relationship before this
    # scenario is accepted.
    assert capability.descriptor.utc_pruning_is_proven is True
    assert capability.utc_pruning is not None
    capability_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Keep block range, solana mainnet network id and block32 transaction32 position
        # schema id visible while completing BlockRange within test proven utc pruning
        # binds only registered resolver.
        100,
        200,
    )
    assert capability.utc_pruning.resolve(capability_range) == UtcDateRange(
        date(2026, 8, 30),
        # Keep the date expectation tied to resolve, capability range and utc date range
        # in this scenario.
        date(2026, 9, 1),
    )
    assert capability_range.from_block_ordinal == 100


def test_unregistered_or_unproven_resolver_is_rejected() -> None:
    # Execute the test unregistered or unproven resolver is rejected workflow in explicit,
    # reviewable steps.
    with pytest.raises(CapabilityConfigError, match="unknown or unproven"):
        # Keep raises, capability config error and pytest active only for the bounded test
        # unregistered or unproven resolver is rejected operation.
        parse_clickhouse_capabilities(
            _VALID,
            utc_pruning_resolvers={
                CapabilityId("fixture.swaps.v1"): lambda _: UtcDateRange(
                    date(2026, 8, 30),
                    # Pass date explicitly to parse_clickhouse_capabilities for v1 and
                    # capability id.
                    date(2026, 9, 1),
                )
            },
        )


def test_invalid_ordering_claim_is_rejected_by_adapter_invariants() -> None:
    # Execute the test invalid ordering claim is rejected by adapter invariants workflow
    # in explicit, reviewable steps.
    text = _VALID.replace("keyset_key_is_proven = true", "keyset_key_is_proven = false")

    with pytest.raises(CapabilityConfigError, match="ORDER BY requires a proven total key"):
        parse_clickhouse_capabilities(text)


@pytest.mark.parametrize(
    "network_id",
    (
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
        "solana:https://rpc.invalid/mainnet",
        # Reject both malformed Solana bytes and generic credential-shaped references.
        "solana:" + "z" * 44,
        "reference:user:invalid-password@rpc.invalid",
    ),
)
def test_malformed_network_identity_is_rejected_before_capability_creation(network_id: str) -> None:
    """Source configuration must not carry invalid or sensitive values into artifact identity."""
    text = _VALID.replace(SOLANA_MAINNET_NETWORK_ID.value, network_id)
    with pytest.raises(CapabilityConfigError, match="root chain identity is invalid") as captured:
        parse_clickhouse_capabilities(text)
    assert network_id not in str(captured.value)
