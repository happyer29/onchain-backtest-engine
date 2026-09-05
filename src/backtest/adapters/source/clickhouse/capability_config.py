"""Strict declarative ClickHouse capability configuration.

The document describes schema mappings and fidelity only.  Connection details
and credentials are intentionally not part of this schema and are rejected as
unknown keys before a ClickHouse client is created.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

# Import typing at the visible module dependency boundary.
from typing import Any, cast

from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ProvenUtcDatePruning,
    UtcDateRange,
    # Include validated identifier so the query dependency remains explicit.
    validated_identifier,
)
from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import (
    CAPABILITY_PROOF_FIELDS,
    # Include capability descriptor so the models dependency remains explicit.
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    EvidenceStatus,
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
from backtest.domain.identifiers import CapabilityId, NetworkId, PositionSchemaId
from backtest.domain.time import BlockRange

CAPABILITY_CONFIG_FORMAT = "backtest.clickhouse-capabilities"
CAPABILITY_CONFIG_SCHEMA_VERSION = 2
_MAX_CONFIG_BYTES = 1024 * 1024
# Bind logical id re once as an explicit module-level contract.
_LOGICAL_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,255}\Z")
_VERSION_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z")

UtcPruningResolver = Callable[[BlockRange], UtcDateRange]
UtcPruningResolvers = Mapping[CapabilityId, UtcPruningResolver]


class CapabilityConfigError(ValueError):
    """A safe structural error that never includes TOML values."""


def load_clickhouse_capabilities(
    path: str | Path,
    *,
    utc_pruning_resolvers: UtcPruningResolvers | None = None,
) -> tuple[ClickHouseCapability, ...]:
    """Load a versioned capability catalog from a local TOML file."""

    config_path = Path(path)
    size = config_path.stat().st_size
    if size > _MAX_CONFIG_BYTES:
        raise CapabilityConfigError("capability configuration exceeds the 1 MiB limit")
    try:
        # Perform the protected load clickhouse capabilities operation before explicit
        # failure handling.
        with config_path.open("rb") as stream:
            document = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise CapabilityConfigError("capability configuration is not valid TOML") from None
    return _parse_document(document, utc_pruning_resolvers or {})


# Define parse clickhouse capabilities as one focused operation with an explicit boundary.
def parse_clickhouse_capabilities(
    text: str,
    *,
    utc_pruning_resolvers: UtcPruningResolvers | None = None,
) -> tuple[ClickHouseCapability, ...]:
    """Parse TOML text; primarily useful for tests and embedded templates."""

    if not isinstance(text, str):
        raise TypeError("capability configuration must be TOML text")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        # Fail the parse clickhouse capabilities path with CapabilityConfigError for
        # capability configuration is not valid utf-8; do not continue ambiguously.
        raise CapabilityConfigError("capability configuration is not valid UTF-8") from None
    if len(encoded) > _MAX_CONFIG_BYTES:
        raise CapabilityConfigError("capability configuration exceeds the 1 MiB limit")
    try:
        document = tomllib.loads(text)
    # Translate tomllib through the parse clickhouse capabilities boundary without hiding
    # other errors.
    except tomllib.TOMLDecodeError:
        raise CapabilityConfigError("capability configuration is not valid TOML") from None
    return _parse_document(document, utc_pruning_resolvers or {})


def _parse_document(
    document: Mapping[str, Any],
    # Keep the resolvers input explicit in the parse document contract.
    resolvers: UtcPruningResolvers,
) -> tuple[ClickHouseCapability, ...]:
    # Execute the parse document workflow in explicit, reviewable steps.
    path = "root"
    if not {"format", "schema_version"}.issubset(document):
        raise CapabilityConfigError("root schema is invalid")
    if _required_string(document, "format", path=path) != CAPABILITY_CONFIG_FORMAT:
        raise CapabilityConfigError("root.format is not a supported capability format")

    # Assemble schema version once so the parse document workflow shares one value.
    schema_version = _required_integer(document, "schema_version", path=path)
    if schema_version == 1:
        raise ReprepareRequiredError("backtest.clickhouse-capabilities/v1")
    if schema_version != CAPABILITY_CONFIG_SCHEMA_VERSION:
        raise CapabilityConfigError("root.schema_version is not supported")
    # Invoke _require_keys for format and schema version as a visible parse document step.
    _require_keys(
        document,
        required={
            "format",
            "schema_version",
            # Pass network id explicitly so _require_keys receives a reviewable format and
            # schema version input in parse document.
            "network_id",
            "position_schema_id",
            "capabilities",
        },
        optional=set(),
        # Pass path explicitly so _require_keys receives a reviewable format and schema
        # version input in parse document.
        path=path,
    )
    try:
        # Perform the protected parse document operation before explicit failure handling.
        network_id = NetworkId(_required_string(document, "network_id", path=path))
        position_schema_id = PositionSchemaId(
            _required_string(document, "position_schema_id", path=path)
        )
    except (TypeError, ValueError):
        # Fail the parse document path with CapabilityConfigError for root chain identity
        # is invalid; do not continue ambiguously.
        raise CapabilityConfigError("root chain identity is invalid") from None

    raw_capabilities = document["capabilities"]
    if not isinstance(raw_capabilities, list):
        raise CapabilityConfigError("root.capabilities must be an array of tables")
    if not raw_capabilities:
        # Fail the parse document path with CapabilityConfigError for capabilities must
        # not be empty when raw capabilities is true; do not continue ambiguously.
        raise CapabilityConfigError("root.capabilities must not be empty")

    capabilities: list[ClickHouseCapability] = []
    seen_ids: set[CapabilityId] = set()
    used_resolvers: set[CapabilityId] = set()
    for index, raw_capability in enumerate(raw_capabilities):
        # Process enumerate(raw_capabilities) inside the bounded parse document loop.
        capability_path = f"root.capabilities[{index}]"
        if not isinstance(raw_capability, dict):
            raise CapabilityConfigError(f"{capability_path} must be a table")
        capability, used_resolver = _parse_capability(
            raw_capability,
            # Pass path explicitly so _parse_capability receives a reviewable raw
            # capability and capability path input in parse document.
            path=capability_path,
            resolvers=resolvers,
            network_id=network_id,
            position_schema_id=position_schema_id,
        )
        # Assemble capability id once so the parse document workflow shares one value.
        capability_id = capability.descriptor.capability_id
        if capability_id in seen_ids:
            raise CapabilityConfigError("capability IDs must be unique")
        seen_ids.add(capability_id)
        if used_resolver:
            # Invoke add for capability id as a visible parse document step.
            used_resolvers.add(capability_id)
        capabilities.append(capability)

    unused_resolvers = set(resolvers).difference(used_resolvers)
    if unused_resolvers:
        # Handle the parse document unused_resolvers branch as a distinct logical block.
        raise CapabilityConfigError(
            "UTC pruning resolver was registered for an unknown or unproven capability"
        )
    return tuple(capabilities)


def _parse_capability(
    # Keep the raw input explicit in the parse capability contract.
    raw: Mapping[str, Any],
    *,
    path: str,
    resolvers: UtcPruningResolvers,
    network_id: NetworkId,
    # Keep the position schema id input explicit in the parse capability contract.
    position_schema_id: PositionSchemaId,
) -> tuple[ClickHouseCapability, bool]:
    # Execute the parse capability workflow in explicit, reviewable steps.
    _require_keys(
        raw,
        required={
            "capability_id",
            "protocol",
            # Pass protocol version explicitly so _require_keys receives a reviewable
            # capability id and protocol input in parse capability.
            "protocol_version",
            "capability_schema_version",
            "stream",
            "database",
            "table",
            # Pass logical block ordinal column explicitly so _require_keys receives a
            # reviewable capability id and protocol input in parse capability.
            "logical_block_ordinal_column",
            "columns",
            "mandatory_columns",
            "total_key",
            "keyset_key_is_proven",
            # Pass order by explicitly so _require_keys receives a reviewable capability
            # id and protocol input in parse capability.
            "order_by",
            "fidelity",
            "proofs",
        },
        optional={"utc_pruning"},
        # Pass path explicitly so _require_keys receives a reviewable capability id and
        # protocol input in parse capability.
        path=path,
    )

    capability_id = _capability_id(raw, path=path)
    column_map = _column_mapping(raw["columns"], path=f"{path}.columns")
    logical_block_ordinal_column = _identifier_string(
        # Pass raw explicitly so _identifier_string receives a reviewable logical block
        # ordinal column and raw input in parse capability.
        raw,
        "logical_block_ordinal_column",
        path=path,
    )
    mandatory_columns = _identifier_list(raw, "mandatory_columns", path=path)
    # Assemble total key once so the parse capability workflow shares one value.
    total_key = _identifier_list(raw, "total_key", path=path)
    order_by = _identifier_list(raw, "order_by", path=path)
    keyset_key_is_proven = _required_boolean(raw, "keyset_key_is_proven", path=path)
    fidelity = _parse_fidelity(raw["fidelity"], path=f"{path}.fidelity")
    try:
        # Assemble stream once so the parse capability workflow shares one value.
        stream = CapabilityStream(_required_string(raw, "stream", path=path))
    except ValueError:
        raise CapabilityConfigError(f"{path}.stream is not supported") from None

    utc_column: str | None = None
    utc_is_proven = False
    # Assemble utc pruning once so the parse capability workflow shares one value.
    utc_pruning: ProvenUtcDatePruning | None = None
    used_resolver = False
    if "utc_pruning" in raw:
        # Handle the parse capability 'utc_pruning' in raw branch as a distinct logical
        # block.
        utc_column, utc_is_proven = _parse_utc_pruning(
            raw["utc_pruning"],
            path=f"{path}.utc_pruning",
        )
        if utc_column not in column_map:
            # Fail the parse capability path with CapabilityConfigError for utc pruning
            # column is not mapped and path when utc column and column map is true; do not
            # continue ambiguously.
            raise CapabilityConfigError(f"{path}.utc_pruning column is not mapped")
        if utc_is_proven:
            # Handle the parse capability utc_is_proven branch as a distinct logical
            # block.
            resolver = resolvers.get(capability_id)
            if resolver is None:
                # Handle the parse capability resolver is None branch as a distinct
                # logical block.
                raise CapabilityConfigError(
                    f"{path}.utc_pruning is proven but no resolver was registered"
                )
            utc_pruning = ProvenUtcDatePruning(utc_column, resolver)
            used_resolver = True

    # Keep expected failures inside the parse capability error boundary.
    try:
        # Perform the protected parse capability operation before explicit failure
        # handling.
        descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            protocol=_version_token(raw, "protocol", path=path),
            protocol_version=_version_token(raw, "protocol_version", path=path),
            schema_version=_version_token(
                # Pass raw explicitly so _version_token receives a reviewable capability
                # schema version and raw input in parse capability.
                raw,
                "capability_schema_version",
                path=path,
            ),
            stream=stream,
            # Keep the column map tuple step visible while building descriptor.
            columns=tuple(column_map),
            mandatory_columns=mandatory_columns,
            fidelity=fidelity,
            proofs=_parse_proofs(raw["proofs"], path=f"{path}.proofs"),
            total_key=total_key,
            # Pass keyset key is proven explicitly so CapabilityDescriptor receives a
            # reviewable protocol and protocol version input in parse capability.
            keyset_key_is_proven=keyset_key_is_proven,
            utc_pruning_column=utc_column,
            utc_pruning_is_proven=utc_is_proven,
        )
        capability = ClickHouseCapability(
            # Pass descriptor explicitly so ClickHouseCapability receives a reviewable
            # database and table input in parse capability.
            descriptor=descriptor,
            network_id=network_id,
            position_schema_id=position_schema_id,
            database=_identifier_string(raw, "database", path=path),
            table=_identifier_string(raw, "table", path=path),
            # Pass logical to physical explicitly so ClickHouseCapability receives a
            # reviewable database and table input in parse capability.
            logical_to_physical=column_map,
            logical_block_ordinal_column=logical_block_ordinal_column,
            order_by=order_by,
            utc_pruning=utc_pruning,
        )
    # Translate type error through the parse capability boundary without hiding other
    # errors.
    except (TypeError, ValueError) as error:
        raise CapabilityConfigError(f"{path} is invalid: {error}") from None
    return capability, used_resolver


def _parse_proofs(raw: Any, *, path: str) -> CapabilityProofs:
    # Execute the parse proofs workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise CapabilityConfigError(f"{path} must be a table")
    _require_keys(
        raw,
        required=set(CAPABILITY_PROOF_FIELDS),
        # Pass optional explicitly to _require_keys for set and raw.
        optional=set(),
        path=path,
    )
    values: dict[str, EvidenceStatus] = {}
    for field_name in CAPABILITY_PROOF_FIELDS:
        # Process CAPABILITY_PROOF_FIELDS inside the bounded parse proofs loop.
        value = _required_string(raw, field_name, path=path)
        try:
            values[field_name] = EvidenceStatus(value)
        except ValueError:
            # Translate the ValueError failure through the parse proofs boundary.
            raise CapabilityConfigError(
                f"{path}.{field_name} must be UNKNOWN, PROVEN or REFUTED"
            ) from None
        if values[field_name] is not EvidenceStatus.UNKNOWN:
            # Handle the parse proofs unknown, values and field name condition as a
            # distinct block.
            raise CapabilityConfigError(
                f"{path}.{field_name} must be UNKNOWN in static configuration; "
                "bounded inspection produces proof outcomes"
            )
    return CapabilityProofs(**values)


# Define parse fidelity as one focused operation with an explicit boundary.
def _parse_fidelity(raw: Any, *, path: str) -> SourceFidelity:
    # Execute the parse fidelity workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise CapabilityConfigError(f"{path} must be a table")
    fields = {
        "identity": IdentityFidelity,
        "ordering": OrderingFidelity,
        # Keep the state component named inside the fields contract.
        "state": StateFidelity,
        "fees": FeesFidelity,
        "chain_finality": ChainFinality,
        "completeness": IngestionCompleteness,
        "consistency": SourceConsistency,
        # Complete the fields group only after its semantic components are visible.
    }
    _require_keys(raw, required=set(fields), optional=set(), path=path)
    values: dict[str, object] = {}
    for name, enum_type in fields.items():
        # Process fields.items() inside the bounded parse fidelity loop.
        value = _required_string(raw, name, path=path)
        try:
            values[name] = enum_type(value)
        except ValueError:
            # Translate the ValueError failure through the parse fidelity boundary.
            allowed = ", ".join(member.value for member in enum_type)
            raise CapabilityConfigError(f"{path}.{name} must be one of: {allowed}") from None
    return SourceFidelity(
        identity=cast(IdentityFidelity, values["identity"]),
        ordering=cast(OrderingFidelity, values["ordering"]),
        # Include state in the completed parse fidelity result.
        state=cast(StateFidelity, values["state"]),
        fees=cast(FeesFidelity, values["fees"]),
        chain_finality=cast(ChainFinality, values["chain_finality"]),
        completeness=cast(IngestionCompleteness, values["completeness"]),
        consistency=cast(SourceConsistency, values["consistency"]),
        # Complete SourceFidelity only after its identity and ordering inputs are visible in
        # parse fidelity.
    )


def _parse_utc_pruning(raw: Any, *, path: str) -> tuple[str, bool]:
    # Execute the parse utc pruning workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise CapabilityConfigError(f"{path} must be a table")
    _require_keys(
        raw,
        required={"logical_column", "is_proven"},
        # Pass optional explicitly to _require_keys for logical column and is proven.
        optional=set(),
        path=path,
    )
    return (
        _identifier_string(raw, "logical_column", path=path),
        # Include path in the completed parse utc pruning result.
        _required_boolean(raw, "is_proven", path=path),
    )


def _column_mapping(raw: Any, *, path: str) -> dict[str, str]:
    # Execute the column mapping workflow in explicit, reviewable steps.
    if not isinstance(raw, dict):
        raise CapabilityConfigError(f"{path} must be a table")
    if not raw:
        raise CapabilityConfigError(f"{path} must not be empty")
    result: dict[str, str] = {}
    # Traverse raw.items() explicitly so each column mapping iteration remains traceable.
    for logical, physical in raw.items():
        # Process raw.items() inside the bounded column mapping loop.
        try:
            validated_identifier(logical, field=f"{path} logical column")
        except (TypeError, ValueError) as error:
            raise CapabilityConfigError(str(error)) from None
        if not isinstance(physical, str):
            # Fail the column mapping path with CapabilityConfigError for physical column
            # must be a string and path when isinstance and physical is true; do not
            # continue ambiguously.
            raise CapabilityConfigError(f"{path} physical column must be a string")
        try:
            # Perform the protected column mapping operation before explicit failure
            # handling.
            result[logical] = validated_identifier(
                physical,
                field=f"{path} physical column",
            )
        except ValueError as error:
            # Fail the column mapping path with CapabilityConfigError for str and error;
            # do not continue ambiguously.
            raise CapabilityConfigError(str(error)) from None
    return result


def _capability_id(raw: Mapping[str, Any], *, path: str) -> CapabilityId:
    # Execute the capability id workflow in explicit, reviewable steps.
    value = _required_string(raw, "capability_id", path=path)
    if _LOGICAL_ID_RE.fullmatch(value) is None:
        raise CapabilityConfigError(f"{path}.capability_id is not a safe logical identifier")
    try:
        return CapabilityId(value)
    # Translate type error through the capability id boundary without hiding other errors.
    except (TypeError, ValueError) as error:
        raise CapabilityConfigError(f"{path}.capability_id is invalid: {error}") from None


def _identifier_string(raw: Mapping[str, Any], key: str, *, path: str) -> str:
    # Execute the identifier string workflow in explicit, reviewable steps.
    value = _required_string(raw, key, path=path)
    try:
        return validated_identifier(value, field=f"{path}.{key}")
    except ValueError as error:
        raise CapabilityConfigError(str(error)) from None


# Define version token as one focused operation with an explicit boundary.
def _version_token(raw: Mapping[str, Any], key: str, *, path: str) -> str:
    # Execute the version token workflow in explicit, reviewable steps.
    value = _required_string(raw, key, path=path)
    if _VERSION_TOKEN_RE.fullmatch(value) is None:
        raise CapabilityConfigError(f"{path}.{key} is not a safe version token")
    return value


def _identifier_list(
    # Keep the raw input explicit in the identifier list contract.
    raw: Mapping[str, Any],
    key: str,
    *,
    path: str,
) -> tuple[str, ...]:
    # Execute the identifier list workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, list):
        raise CapabilityConfigError(f"{path}.{key} must be an array")
    result: list[str] = []
    for item in value:
        # Process value inside the bounded identifier list loop.
        if not isinstance(item, str):
            raise CapabilityConfigError(f"{path}.{key} must contain only strings")
        try:
            result.append(validated_identifier(item, field=f"{path}.{key} item"))
        except ValueError as error:
            # Fail the identifier list path with CapabilityConfigError for str and error;
            # do not continue ambiguously.
            raise CapabilityConfigError(str(error)) from None
    if len(set(result)) != len(result):
        raise CapabilityConfigError(f"{path}.{key} must not contain duplicates")
    return tuple(result)


def _required_string(raw: Mapping[str, Any], key: str, *, path: str) -> str:
    # Execute the required string workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, str):
        raise CapabilityConfigError(f"{path}.{key} must be a string")
    if not value or value != value.strip():
        raise CapabilityConfigError(f"{path}.{key} must be non-empty and trimmed")
    # Return the completed required string result without a hidden fallback.
    return value


def _required_boolean(raw: Mapping[str, Any], key: str, *, path: str) -> bool:
    # Execute the required boolean workflow in explicit, reviewable steps.
    value = raw[key]
    if not isinstance(value, bool):
        raise CapabilityConfigError(f"{path}.{key} must be a boolean")
    return value


def _required_integer(raw: Mapping[str, Any], key: str, *, path: str) -> int:
    # Execute the required integer workflow in explicit, reviewable steps.
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapabilityConfigError(f"{path}.{key} must be an integer")
    return value


def _require_keys(
    # Keep the raw input explicit in the require keys contract.
    raw: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    path: str,
    # Close the require keys signature after its explicit inputs.
) -> None:
    # Execute the require keys workflow in explicit, reviewable steps.
    keys = set(raw)
    unknown = keys.difference(required, optional)
    if unknown:
        # Handle the require keys unknown branch as a distinct logical block.
        names = ", ".join(sorted(unknown))
        raise CapabilityConfigError(f"{path} contains unknown keys: {names}")
    missing = required.difference(keys)
    if missing:
        # Handle the require keys missing branch as a distinct logical block.
        names = ", ".join(sorted(missing))
        raise CapabilityConfigError(f"{path} is missing required keys: {names}")


__all__ = [
    "CAPABILITY_CONFIG_FORMAT",
    "CAPABILITY_CONFIG_SCHEMA_VERSION",
    # Keep the capability config error component named inside the all contract.
    "CapabilityConfigError",
    "UtcPruningResolver",
    "UtcPruningResolvers",
    "load_clickhouse_capabilities",
    "parse_clickhouse_capabilities",
    # Complete the all group only after its semantic components are visible.
]
