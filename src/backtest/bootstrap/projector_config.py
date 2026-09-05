"""Strict network-aware local configuration for semantic projections."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Import typing at the visible module dependency boundary.
from typing import Any

from backtest.adapters.source.clickhouse import ClickHouseCapability
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import CapabilityStream
from backtest.domain.identifiers import (
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    NetworkId,
    PositionSchemaId,
    ProtocolPayloadSchemaId,
)

# Import market events at the visible module dependency boundary.
from backtest.domain.market_events import EventKindName
from backtest.plugins.protocols.reference import ProjectionKind, ProjectionSpec

_PUMP_LAUNCH_SCHEMA = "pump-launch-state-v1"
_PUMP_TRADE_SCHEMA = "pump-trade-state-v1"
_PUMP_LIFECYCLE_SCHEMA = "pump-lifecycle-state-v1"

# Bind projection config format once as an explicit module-level contract.
PROJECTION_CONFIG_FORMAT = "backtest.protocol-projections"
PROJECTION_CONFIG_SCHEMA_VERSION = 2
_MAX_CONFIG_BYTES = 1024 * 1024


class ProjectorConfigError(ValueError):
    """Safe structural error that never renders configured values."""


@dataclass(frozen=True, slots=True)
class ProjectionDeclaration:
    capability_id: CapabilityId
    event_kind: EventKindName
    protocol_payload_schema_id: ProtocolPayloadSchemaId | None
    # Declare columns explicitly in the projection declaration contract.
    columns: tuple[tuple[str, str], ...]

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self.columns)


# Keep the projection configuration contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProjectionConfiguration:
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    declarations: tuple[ProjectionDeclaration, ...]


# Bind expected event kind once as an explicit module-level contract.
_EXPECTED_EVENT_KIND = {
    CapabilityStream.BLOCK_CLOCK: EventKindName.BLOCK,
    CapabilityStream.TOKEN_LAUNCH: EventKindName.TOKEN_LAUNCH,
    CapabilityStream.PUMP_CURVE_TRADE: EventKindName.VENUE_TRADE,
    CapabilityStream.PUMP_CURVE_LIFECYCLE: EventKindName.VENUE_LIFECYCLE,
    # Complete the expected event kind group only after its semantic components are visible.
}

_REFERENCE_KIND = {
    EventKindName.BLOCK: ProjectionKind.BLOCK,
    EventKindName.TOKEN_LAUNCH: ProjectionKind.TOKEN_CREATION,
    EventKindName.VENUE_TRADE: ProjectionKind.SWAP,
    # Complete the reference kind group only after its semantic components are visible.
}

_REQUIRED_SEMANTIC_COLUMNS = {
    EventKindName.BLOCK: {
        "block_ordinal",
        "block_time",
        # Keep the transaction count component named inside the required semantic columns
        # contract.
        "transaction_count",
        "block_hash",
    },
    EventKindName.TOKEN_LAUNCH: {
        "block_ordinal",
        # Keep the transaction index component named inside the required semantic columns
        # contract.
        "transaction_index",
        "event_index",
        "signature",
        "asset",
        "developer",
        # Keep the creation user component named inside the required semantic columns
        # contract.
        "creation_user",
        "venue",
        "quote_asset",
        "protocol_payload",
    },
    # Keep the event kind name component named inside the required semantic columns
    # contract.
    EventKindName.VENUE_TRADE: {
        "block_ordinal",
        "transaction_index",
        "event_index",
        "signature",
        # Keep the venue component named inside the required semantic columns contract.
        "venue",
        "asset",
        "quote_asset",
        "side",
        "base_amount_atomic",
        # Keep the quote amount atomic component named inside the required semantic
        # columns contract.
        "quote_amount_atomic",
        "protocol_payload",
    },
    EventKindName.VENUE_LIFECYCLE: {
        "block_ordinal",
        # Keep the transaction index component named inside the required semantic columns
        # contract.
        "transaction_index",
        "event_index",
        "signature",
        "venue",
        "lifecycle_kind",
        # Keep the protocol payload component named inside the required semantic columns
        # contract.
        "protocol_payload",
    },
}

_PUMP_STATE_COLUMNS = {
    "virtual_token_reserves_atomic",
    # Keep the virtual sol reserves lamports component named inside the pump state columns
    # contract.
    "virtual_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "real_sol_reserves_lamports",
    "token_total_supply_atomic",
    "lifecycle",
    # Keep the mode component named inside the pump state columns contract.
    "mode",
}

_PUMP_REQUIRED_SEMANTIC_COLUMNS = {
    EventKindName.TOKEN_LAUNCH: (
        _REQUIRED_SEMANTIC_COLUMNS[EventKindName.TOKEN_LAUNCH]
        # Pass difference explicitly so difference receives a reviewable protocol payload
        # input in module.
        .difference({"protocol_payload"})
        .union(_PUMP_STATE_COLUMNS, {"transaction_succeeded"})
    ),
    EventKindName.VENUE_TRADE: (
        _REQUIRED_SEMANTIC_COLUMNS[EventKindName.VENUE_TRADE]
        # Pass difference explicitly so difference receives a reviewable protocol payload
        # input in module.
        .difference({"protocol_payload"})
        .union(_PUMP_STATE_COLUMNS, {"protocol_fee_atomic", "creator_fee_atomic"})
    ),
    EventKindName.VENUE_LIFECYCLE: (
        _REQUIRED_SEMANTIC_COLUMNS[EventKindName.VENUE_LIFECYCLE]
        # Pass difference explicitly so difference receives a reviewable protocol payload
        # input in module.
        .difference({"protocol_payload"})
        .union(_PUMP_STATE_COLUMNS)
    ),
}

_PUMP_PAYLOAD_SCHEMA_BY_KIND = {
    # Keep the event kind name component named inside the pump payload schema by kind
    # contract.
    EventKindName.TOKEN_LAUNCH: _PUMP_LAUNCH_SCHEMA,
    EventKindName.VENUE_TRADE: _PUMP_TRADE_SCHEMA,
    EventKindName.VENUE_LIFECYCLE: _PUMP_LIFECYCLE_SCHEMA,
}


def load_projection_declarations(
    # Keep the path input explicit in the load projection declarations contract.
    path: Path,
    capabilities: Sequence[ClickHouseCapability],
) -> ProjectionConfiguration:
    """Load and structurally validate generic v2 projection declarations."""

    document = _load_document(path)
    if not {"format", "schema_version"}.issubset(document):
        raise ProjectorConfigError("root schema is invalid")
    if _required_string(document, "format", path="root") != PROJECTION_CONFIG_FORMAT:
        raise ProjectorConfigError("root.format is not a supported projection format")
    # Assemble schema version once so the load projection declarations workflow shares one
    # value.
    schema_version = _required_integer(document, "schema_version", path="root")
    if schema_version == 1:
        raise ReprepareRequiredError("backtest.protocol-projections/v1")
    if schema_version != PROJECTION_CONFIG_SCHEMA_VERSION:
        raise ProjectorConfigError("root.schema_version is not supported")
    # Invoke _require_exact_keys for format and schema version as a visible load
    # projection declarations step.
    _require_exact_keys(
        document,
        {
            "format",
            "schema_version",
            # Pass network id explicitly so _require_exact_keys receives a reviewable
            # format and schema version input in load projection declarations.
            "network_id",
            "position_schema_id",
            "projections",
        },
        path="root",
        # Complete _require_exact_keys only after its format and schema version inputs are
        # visible in load projection declarations.
    )
    try:
        # Perform the protected load projection declarations operation before explicit
        # failure handling.
        network_id = NetworkId(_required_string(document, "network_id", path="root"))
        position_schema_id = PositionSchemaId(
            _required_string(document, "position_schema_id", path="root")
        )
    except (TypeError, ValueError):
        # Fail the load projection declarations path with ProjectorConfigError for root
        # chain identity is invalid; do not continue ambiguously.
        raise ProjectorConfigError("root chain identity is invalid") from None

    by_id = {item.descriptor.capability_id: item for item in capabilities}
    if not by_id or len(by_id) != len(capabilities):
        raise ProjectorConfigError("capabilities must be non-empty and unique")
    if any(
        # Pass item explicitly so any receives a reviewable network id and position schema
        # id input in load projection declarations.
        item.network_id != network_id or item.position_schema_id != position_schema_id
        for item in capabilities
    ):
        raise ProjectorConfigError("projection and capability chain identities differ")

    raw_projections = document["projections"]
    # Evaluate the complete load projection declarations raw projections and isinstance
    # condition before guarded effects.
    if not isinstance(raw_projections, list) or not raw_projections:
        raise ProjectorConfigError("root.projections must be a non-empty array of tables")
    declarations = tuple(
        _parse_declaration(raw, index=index, capabilities=by_id)
        for index, raw in enumerate(raw_projections)
        # Complete tuple only after its parse declaration and enumerate inputs are visible in
        # load projection declarations.
    )
    if len({item.capability_id for item in declarations}) != len(declarations):
        raise ProjectorConfigError("projection capability IDs must be unique")
    return ProjectionConfiguration(network_id, position_schema_id, declarations)


def load_projection_specs(
    # Keep the path input explicit in the load projection specs contract.
    path: Path,
    capabilities: Sequence[ClickHouseCapability],
) -> tuple[ProjectionSpec, ...]:
    """Resolve declarations supported by the installed reference projector.

    Pump lifecycle declarations are accepted structurally by
    :func:`load_projection_declarations`, but this resolver fails closed until
    a concrete Pump projector is installed by bootstrap.
    """

    configuration = load_projection_declarations(path, capabilities)
    by_id = {item.descriptor.capability_id: item.descriptor for item in capabilities}
    specs: list[ProjectionSpec] = []
    for declaration in configuration.declarations:
        # Process configuration.declarations inside the bounded load projection specs
        # loop.
        descriptor = by_id[declaration.capability_id]
        try:
            kind = _REFERENCE_KIND[declaration.event_kind]
        except KeyError:
            # Translate the KeyError failure through the load projection specs boundary.
            raise ProjectorConfigError(
                "projection requires a concrete protocol projector that is not installed"
            ) from None
        try:
            # Perform the protected load projection specs operation before explicit
            # failure handling.
            specs.append(
                ProjectionSpec(
                    capability_id=declaration.capability_id,
                    kind=kind,
                    protocol=descriptor.protocol,
                    # Pass protocol version explicitly so ProjectionSpec receives a
                    # reviewable capability id and protocol input in load projection
                    # specs.
                    protocol_version=descriptor.protocol_version,
                    identity_fidelity=descriptor.fidelity.identity,
                    ordering_fidelity=descriptor.fidelity.ordering,
                    source_total_key=descriptor.total_key,
                    source_total_key_is_proven=descriptor.keyset_key_is_proven,
                    # Pass columns explicitly to append for capability id and protocol.
                    columns=_reference_columns(declaration),
                )
            )
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the load projection
            # specs boundary.
            raise ProjectorConfigError(
                f"projection is not supported by the installed reference projector: {error}"
            ) from None
    return tuple(specs)


def _reference_columns(
    # Keep the declaration input explicit in the reference columns contract.
    declaration: ProjectionDeclaration,
) -> tuple[tuple[str, str], ...]:
    """Translate the generic v2 block vocabulary for the retained oracle."""

    aliases = (
        {
            "block_ordinal": "slot",
            "transaction_count": "tx_count",
        }
        # Keep the declaration component named inside the aliases contract.
        if declaration.event_kind is EventKindName.BLOCK
        else {}
    )
    return tuple(
        sorted(
            # Include aliases in the completed reference columns result.
            (aliases.get(semantic, semantic), logical)
            for semantic, logical in declaration.columns
        )
    )


def _load_document(path: Path) -> dict[str, Any]:
    # Execute the load document workflow in explicit, reviewable steps.
    if path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ProjectorConfigError("projection configuration exceeds the 1 MiB limit")
    try:
        # Perform the protected load document operation before explicit failure handling.
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise ProjectorConfigError("projection configuration is not valid TOML") from None
    return document


# Define parse declaration as one focused operation with an explicit boundary.
def _parse_declaration(
    raw: object,
    *,
    index: int,
    capabilities: Mapping[CapabilityId, ClickHouseCapability],
    # Keep the projection declaration input explicit in the parse declaration contract.
) -> ProjectionDeclaration:
    # Execute the parse declaration workflow in explicit, reviewable steps.
    path = f"root.projections[{index}]"
    if not isinstance(raw, dict):
        raise ProjectorConfigError(f"{path} must be a table")
    keys = set(raw)
    required = {"capability_id", "event_kind", "columns"}
    # Evaluate the complete parse declaration issubset, keys and required condition before
    # guarded effects.
    if not required.issubset(keys) or not keys.issubset({*required, "protocol_payload_schema_id"}):
        raise ProjectorConfigError(f"{path} schema is invalid")
    try:
        # Perform the protected parse declaration operation before explicit failure
        # handling.
        capability_id = CapabilityId(_required_string(raw, "capability_id", path=path))
        capability = capabilities[capability_id]
        event_kind = EventKindName(_required_string(raw, "event_kind", path=path))
    except (KeyError, TypeError, ValueError):
        raise ProjectorConfigError(f"{path} references an invalid capability or kind") from None
    # Evaluate the complete parse declaration event kind, expected event kind and stream
    # condition before guarded effects.
    if event_kind is not _EXPECTED_EVENT_KIND[capability.descriptor.stream]:
        raise ProjectorConfigError(f"{path} event kind does not match the capability stream")

    payload_schema_raw = raw.get("protocol_payload_schema_id")
    if payload_schema_raw is None:
        payload_schema_id = None
    # Handle the parse declaration complement of payload_schema_raw is None explicitly.
    elif isinstance(payload_schema_raw, str):
        # Handle the parse declaration isinstance(payload_schema_raw, str) branch as a
        # distinct logical block.
        try:
            payload_schema_id = ProtocolPayloadSchemaId(payload_schema_raw)
        except (TypeError, ValueError):
            raise ProjectorConfigError(f"{path}.protocol_payload_schema_id is invalid") from None
    else:
        # Fail the parse declaration path with ProjectorConfigError for protocol payload
        # schema id must be a string or null and path when payload schema raw str type is
        # true; do not continue ambiguously.
        raise ProjectorConfigError(f"{path}.protocol_payload_schema_id must be a string or null")
    if event_kind is EventKindName.BLOCK and payload_schema_id is not None:
        raise ProjectorConfigError(f"{path} block projection cannot have a payload schema")
    if event_kind is not EventKindName.BLOCK and payload_schema_id is None:
        raise ProjectorConfigError(f"{path} protocol event requires a payload schema")

    # Assemble columns raw once so the parse declaration workflow shares one value.
    columns_raw = raw["columns"]
    if not isinstance(columns_raw, dict) or not columns_raw:
        raise ProjectorConfigError(f"{path}.columns must be a non-empty table")
    columns: list[tuple[str, str]] = []
    for semantic, logical in columns_raw.items():
        # Process columns_raw.items() inside the bounded parse declaration loop.
        if (
            not isinstance(semantic, str)
            or not semantic
            or semantic != semantic.strip()
            or not isinstance(logical, str)
            # Keep logical visible while evaluating the semantic, logical and columns
            # guard.
            or logical not in capability.descriptor.columns
        ):
            raise ProjectorConfigError(f"{path}.columns contains an invalid mapping")
        columns.append((semantic, logical))
    ordered = tuple(sorted(columns))
    # Evaluate the complete parse declaration ordered, left and right condition before
    # guarded effects.
    if len({left for left, _ in ordered}) != len(ordered) or len(
        {right for _, right in ordered}
    ) != len(ordered):
        raise ProjectorConfigError(f"{path}.columns mappings must be one-to-one")
    expected_pump_schema = _PUMP_PAYLOAD_SCHEMA_BY_KIND.get(event_kind)
    # Evaluate the complete parse declaration payload schema id, value and pump launch
    # schema condition before guarded effects.
    if payload_schema_id is not None and payload_schema_id.value in {
        _PUMP_LAUNCH_SCHEMA,
        _PUMP_TRADE_SCHEMA,
        _PUMP_LIFECYCLE_SCHEMA,
    }:
        # Handle the parse declaration payload schema id, value and pump launch schema
        # condition as a distinct block.
        if payload_schema_id.value != expected_pump_schema:
            raise ProjectorConfigError(f"{path} Pump payload schema does not match event kind")
        required_semantic_columns = _PUMP_REQUIRED_SEMANTIC_COLUMNS[event_kind]
    else:
        required_semantic_columns = _REQUIRED_SEMANTIC_COLUMNS[event_kind]
    # Assemble missing once so the parse declaration workflow shares one value.
    missing = required_semantic_columns.difference(semantic for semantic, _ in ordered)
    if missing:
        raise ProjectorConfigError(f"{path}.columns misses required semantic fields")
    return ProjectionDeclaration(capability_id, event_kind, payload_schema_id, ordered)


def _required_string(raw: Mapping[str, Any], key: str, *, path: str) -> str:
    # Execute the required string workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProjectorConfigError(f"{path}.{key} must be a non-empty trimmed string")
    return value


def _required_integer(raw: Mapping[str, Any], key: str, *, path: str) -> int:
    # Execute the required integer workflow in explicit, reviewable steps.
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectorConfigError(f"{path}.{key} must be an integer")
    return value


def _require_exact_keys(raw: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    # Execute the require exact keys workflow in explicit, reviewable steps.
    if set(raw) != expected:
        raise ProjectorConfigError(f"{path} schema is invalid")


__all__ = [
    "PROJECTION_CONFIG_FORMAT",
    "PROJECTION_CONFIG_SCHEMA_VERSION",
    # Keep the projection configuration component named inside the all contract.
    "ProjectionConfiguration",
    "ProjectionDeclaration",
    "ProjectorConfigError",
    "load_projection_declarations",
    "load_projection_specs",
    # Complete the all group only after its semantic components are visible.
]
