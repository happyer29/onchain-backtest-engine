"""Fail-closed ClickHouse query construction.

Only identifiers from trusted adapter configuration are rendered into SQL.
All runtime values use ClickHouse server-side parameters.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# Import datetime at the visible module dependency boundary.
from datetime import date
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from backtest.application.models import (
    # Include capability proof fields so the models dependency remains explicit.
    CAPABILITY_PROOF_FIELDS,
    CapabilityDescriptor,
    ExtractionRequest,
    QueryLimits,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ContentDigest, NetworkId, PositionSchemaId
from backtest.domain.time import BlockRange

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")


def validated_identifier(value: str, *, field: str = "identifier") -> str:
    """Accept the conservative identifier subset supported by this adapter."""

    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{field} is not a safe ClickHouse identifier")
    return value


# Define quoted identifier as one focused operation with an explicit boundary.
def quoted_identifier(value: str) -> str:
    return f"`{validated_identifier(value)}`"


@dataclass(frozen=True, slots=True)
class UtcDateRange:
    """A non-empty, half-open UTC calendar-date pruning range."""

    from_date: date
    to_date: date

    def __post_init__(self) -> None:
        # Execute the utc date range post init workflow in explicit, reviewable steps.
        if type(self.from_date) is not date:
            raise TypeError("from_date must be a date")
        if type(self.to_date) is not date:
            raise TypeError("to_date must be a date")
        if self.to_date <= self.from_date:
            # Fail the utc date range post init path with ValueError for utc date range
            # must be non-empty when to date and from date is true; do not continue
            # ambiguously.
            raise ValueError("UTC date range must be non-empty")


@dataclass(frozen=True, slots=True)
class ProvenUtcDatePruning:
    """Explicit proof boundary for an optional partition-pruning predicate.

    The resolver must return a date range that is a safe superset of the slots.
    Its implementation belongs to source discovery/planning; this adapter never
    guesses dates from Solana slots or from the ClickHouse server timezone.
    """

    logical_column: str
    resolve: Callable[[BlockRange], UtcDateRange]

    def __post_init__(self) -> None:
        # Execute the proven utc date pruning post init workflow in explicit, reviewable
        # steps.
        validated_identifier(self.logical_column, field="UTC pruning logical column")
        if not callable(self.resolve):
            raise TypeError("UTC pruning resolver must be callable")


@dataclass(frozen=True, slots=True)
class ClickHouseCapability:
    """Trusted mapping from one logical capability to one physical table."""

    descriptor: CapabilityDescriptor
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    database: str
    table: str
    # Declare logical to physical explicitly in the click house capability contract.
    logical_to_physical: Mapping[str, str]
    logical_block_ordinal_column: str = "block_ordinal"
    order_by: tuple[str, ...] = ()
    utc_pruning: ProvenUtcDatePruning | None = None

    def __post_init__(self) -> None:
        # Execute the click house capability post init workflow in explicit, reviewable
        # steps.
        validated_identifier(self.database, field="database")
        validated_identifier(self.table, field="table")
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            # Fail the click house capability post init path with TypeError for position
            # schema id must be a position schema id when isinstance and position schema
            # id is true; do not continue ambiguously.
            raise TypeError("position_schema_id must be a PositionSchemaId")
        validated_identifier(
            self.logical_block_ordinal_column,
            field="logical block ordinal column",
        )

        # Assemble column map once so the click house capability post init workflow shares
        # one value.
        column_map = dict(self.logical_to_physical)
        if set(column_map) != set(self.descriptor.columns):
            raise ValueError("column mapping must exactly cover advertised logical columns")
        for logical, physical in column_map.items():
            # Process column_map.items() inside the bounded click house capability post
            # init loop.
            validated_identifier(logical, field="logical column")
            validated_identifier(physical, field="physical column")
        if len(set(column_map.values())) != len(column_map):
            raise ValueError("physical column mapping must be one-to-one")
        if self.logical_block_ordinal_column not in column_map:
            # Fail the click house capability post init path with ValueError for logical
            # block ordinal column is not mapped when logical block ordinal column and
            # column map is true; do not continue ambiguously.
            raise ValueError("logical block ordinal column is not mapped")
        if self.logical_block_ordinal_column not in self.descriptor.mandatory_columns:
            raise ValueError("block ordinal must be a mandatory capability column")

        order_by = tuple(self.order_by)
        if order_by:
            # Handle the click house capability post init order_by branch as a distinct
            # logical block.
            if not self.descriptor.keyset_key_is_proven:
                raise ValueError("ORDER BY requires a proven total key")
            expected = _deduplicated(
                (self.logical_block_ordinal_column, *self.descriptor.total_key)
            )
            # Guard this path with order_by != expected before applying effects.
            if order_by != expected:
                raise ValueError("ORDER BY must equal block ordinal plus the proven total key")
        for column in order_by:
            # Process order_by inside the bounded click house capability post init loop.
            if column not in column_map:
                raise ValueError(f"ORDER BY column {column!r} is not mapped")

        if self.utc_pruning is not None:
            # Handle the click house capability post init self.utc_pruning is not None
            # branch as a distinct logical block.
            descriptor = self.descriptor
            if not descriptor.utc_pruning_is_proven:
                raise ValueError("UTC pruning is configured but capability proof is absent")
            if descriptor.utc_pruning_column != self.utc_pruning.logical_column:
                raise ValueError("UTC pruning column differs from capability descriptor")
            # Evaluate the complete click house capability post init logical column,
            # column map and utc pruning condition before guarded effects.
            if self.utc_pruning.logical_column not in column_map:
                raise ValueError("UTC pruning column is not mapped")

        object.__setattr__(self, "logical_to_physical", MappingProxyType(column_map))
        object.__setattr__(self, "order_by", order_by)

    @property
    # Define click house capability qualified table as one focused operation with an
    # explicit boundary.
    def qualified_table(self) -> str:
        return f"{quoted_identifier(self.database)}.{quoted_identifier(self.table)}"

    def physical_column(self, logical_column: str) -> str:
        # Execute the click house capability physical column workflow in explicit,
        # reviewable steps.
        try:
            return self.logical_to_physical[logical_column]
        except KeyError:
            raise ValueError(f"unmapped logical column {logical_column!r}") from None


@dataclass(frozen=True, slots=True)
# Keep the click house query policy contract and validation rules together.
class ClickHouseQueryPolicy:
    """Adapter-wide hard ceilings; request limits can only lower them."""

    max_block_span: int = 2_000_000
    max_execution_seconds: int = 300
    max_memory_bytes: int = 4 * 1024**3
    max_result_rows: int = 10_000_000
    max_rows_to_read: int = 100_000_000
    # Declare max bytes to read explicitly in the click house query policy contract.
    max_bytes_to_read: int = 16 * 1024**3
    max_threads: int = 4
    max_block_size: int = 8_192
    metadata_max_result_rows: int = 4096
    evidence_max_block_span: int = 8_192
    evidence_max_result_rows: int = 100_000
    # Declare evidence max result bytes explicitly in the click house query policy
    # contract.
    evidence_max_result_bytes: int = 64 * 1024**2
    evidence_max_rows_to_read: int = 2_000_000
    evidence_max_bytes_to_read: int = 1024**3

    def __post_init__(self) -> None:
        # Execute the click house query policy post init workflow in explicit, reviewable
        # steps.
        for field in (
            "max_block_span",
            "max_execution_seconds",
            "max_memory_bytes",
            "max_result_rows",
            # Traverse max block span, max execution seconds and max memory bytes
            # explicitly so each click house query policy post init iteration remains
            # traceable.
            "max_rows_to_read",
            "max_bytes_to_read",
            "max_threads",
            "max_block_size",
            "metadata_max_result_rows",
            "evidence_max_block_span",
            # Traverse max block span, max execution seconds and max memory bytes
            # explicitly so each click house query policy post init iteration remains
            # traceable.
            "evidence_max_result_rows",
            "evidence_max_result_bytes",
            "evidence_max_rows_to_read",
            "evidence_max_bytes_to_read",
        ):
            # Process max block span, max execution seconds and max memory bytes inside
            # the bounded click house query policy post init loop.
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field} must be an integer")
            if value <= 0:
                raise ValueError(f"{field} must be positive")

    # Define click house query policy scan settings as one focused operation with an
    # explicit boundary.
    def scan_settings(self, limits: QueryLimits) -> dict[str, int | str]:
        # Execute the click house query policy scan settings workflow in explicit,
        # reviewable steps.
        requested_rows = limits.max_result_rows or self.max_result_rows
        return {
            "readonly": 1,
            "max_execution_time": min(
                limits.max_execution_seconds,
                # Pass self explicitly so min receives a reviewable max execution seconds
                # and limits input in click house query policy scan settings.
                self.max_execution_seconds,
            ),
            "max_memory_usage": min(limits.max_memory_bytes, self.max_memory_bytes),
            "max_result_rows": min(requested_rows, self.max_result_rows),
            "result_overflow_mode": "throw",
            # Include max rows to read in the completed click house query policy scan
            # settings result.
            "max_rows_to_read": self.max_rows_to_read,
            "read_overflow_mode": "throw",
            "max_bytes_to_read": self.max_bytes_to_read,
            "max_threads": self.max_threads,
            "max_block_size": self.max_block_size,
        }

    # Define click house query policy metadata settings as one focused operation with an
    # explicit boundary.
    def metadata_settings(self) -> dict[str, int | str]:
        # Execute the click house query policy metadata settings workflow in explicit,
        # reviewable steps.
        return {
            "readonly": 1,
            "max_execution_time": min(30, self.max_execution_seconds),
            "max_memory_usage": min(256 * 1024**2, self.max_memory_bytes),
            "max_result_rows": self.metadata_max_result_rows,
            # Include result overflow mode in the completed click house query policy
            # metadata settings result.
            "result_overflow_mode": "throw",
            "max_rows_to_read": self.metadata_max_result_rows,
            "read_overflow_mode": "throw",
            "max_threads": 1,
            "max_block_size": self.max_block_size,
        }

    # Define click house query policy evidence settings as one focused operation with an
    # explicit boundary.
    def evidence_settings(self, limits: QueryLimits) -> dict[str, int | str]:
        """Return ceilings for small, bounded validation reads."""

        if limits.max_result_rows is None:
            raise ValueError("bounded evidence requires an explicit result-row limit")
        return {
            "readonly": 1,
            "max_execution_time": min(
                # Pass limits explicitly so min receives a reviewable max execution
                # seconds and limits input in click house query policy evidence settings.
                limits.max_execution_seconds,
                self.max_execution_seconds,
                60,
            ),
            "max_memory_usage": min(
                # Pass limits explicitly so min receives a reviewable max memory bytes and
                # limits input in click house query policy evidence settings.
                limits.max_memory_bytes,
                self.max_memory_bytes,
                512 * 1024**2,
            ),
            "max_result_rows": min(
                # Pass limits explicitly so min receives a reviewable max result rows and
                # evidence max result rows input in click house query policy evidence
                # settings.
                limits.max_result_rows,
                self.evidence_max_result_rows,
            ),
            "result_overflow_mode": "throw",
            "max_result_bytes": self.evidence_max_result_bytes,
            # Include max rows to read in the completed click house query policy evidence
            # settings result.
            "max_rows_to_read": min(
                self.max_rows_to_read,
                self.evidence_max_rows_to_read,
            ),
            "read_overflow_mode": "throw",
            # Include max bytes to read in the completed click house query policy evidence
            # settings result.
            "max_bytes_to_read": min(
                self.max_bytes_to_read,
                self.evidence_max_bytes_to_read,
            ),
            "max_threads": 1,
            "max_block_size": self.max_block_size,
            # Return the completed click house query policy evidence settings result without a
            # hidden fallback.
        }


# Keep the bounded query contract and validation rules together.
@dataclass(frozen=True, slots=True)
class BoundedQuery:
    sql: str
    parameters: Mapping[str, Any]
    columns: tuple[str, ...]
    # Declare block ordinal column index explicitly in the bounded query contract.
    block_ordinal_column_index: int
    fingerprint: ContentDigest


def build_scan_query(
    capability: ClickHouseCapability,
    request: ExtractionRequest,
    # Keep the policy input explicit in the build scan query contract.
    policy: ClickHouseQueryPolicy,
) -> BoundedQuery:
    """Compile one explicit, parameterized and bounded extraction query."""

    if request.shard.capability_id != capability.descriptor.capability_id:
        raise ValueError("request capability does not match ClickHouse mapping")
    if request.shard.block_range.span > policy.max_block_span:
        raise ValueError("requested block shard exceeds ClickHouse hard span limit")
    if (
        # Keep request visible while evaluating the network id, position schema id and
        # block range guard.
        request.shard.block_range.network_id != capability.network_id
        or request.shard.block_range.position_schema_id != capability.position_schema_id
    ):
        raise ValueError("request and ClickHouse capability use different chain identities")

    columns = request.shard.columns
    # Guard this path with not columns before applying effects.
    if not columns:
        raise ValueError("source projection must not be empty")
    unknown = set(columns).difference(capability.descriptor.columns)
    if unknown:
        raise ValueError(f"projection contains unadvertised columns: {sorted(unknown)}")
    # Assemble missing once so the build scan query workflow shares one value.
    missing = set(capability.descriptor.mandatory_columns).difference(columns)
    if missing:
        raise ValueError(f"projection misses mandatory columns: {sorted(missing)}")

    projection = ", ".join(
        f"{quoted_identifier(capability.physical_column(column))} AS {quoted_identifier(column)}"
        # Pass column explicitly so join receives a reviewable as and physical column
        # input in build scan query.
        for column in columns
    )
    physical_block = quoted_identifier(
        capability.physical_column(capability.logical_block_ordinal_column)
    )
    # Assemble predicates once so the build scan query workflow shares one value.
    predicates = [
        f"{physical_block} >= {{from_block_ordinal:UInt64}}",
        f"{physical_block} < {{to_block_ordinal:UInt64}}",
    ]
    parameters: dict[str, Any] = {
        # Keep the from block ordinal component named inside the parameters contract.
        "from_block_ordinal": request.shard.block_range.from_block_ordinal,
        "to_block_ordinal": request.shard.block_range.to_block_ordinal,
    }

    if capability.utc_pruning is not None:
        # Handle the build scan query capability.utc_pruning is not None branch as a
        # distinct logical block.
        utc_range = capability.utc_pruning.resolve(request.shard.block_range)
        if not isinstance(utc_range, UtcDateRange):
            raise TypeError("UTC pruning resolver must return UtcDateRange")
        physical_date = quoted_identifier(
            capability.physical_column(capability.utc_pruning.logical_column)
            # Complete quoted_identifier only after its physical column and logical column
            # inputs are visible in build scan query.
        )
        predicates.extend(
            (
                f"{physical_date} >= {{from_date_utc:Date}}",
                f"{physical_date} < {{to_date_utc:Date}}",
                # Complete extend only after its >= {from date utc:date} and < {to date
                # utc:date} inputs are visible in build scan query.
            )
        )
        parameters["from_date_utc"] = utc_range.from_date
        parameters["to_date_utc"] = utc_range.to_date

    sql_lines = [
        # Keep the select projection component named inside the sql lines contract.
        f"SELECT {projection}",
        f"FROM {capability.qualified_table}",
        f"PREWHERE {' AND '.join(predicates)}",
    ]
    if capability.order_by:
        # Handle the build scan query capability.order_by branch as a distinct logical
        # block.
        ordering = ", ".join(
            quoted_identifier(capability.physical_column(column)) for column in capability.order_by
        )
        sql_lines.append(f"ORDER BY {ordering}")

    sql = "\n".join(sql_lines)
    # Invoke _assert_safe_shape for sql as a visible build scan query step.
    _assert_safe_shape(sql)
    fingerprint = _query_fingerprint(sql, parameters)
    return BoundedQuery(
        sql=sql,
        parameters=MappingProxyType(parameters),
        # Pass columns explicitly so BoundedQuery receives a reviewable index and logical
        # block ordinal column input in build scan query.
        columns=columns,
        block_ordinal_column_index=columns.index(capability.logical_block_ordinal_column),
        fingerprint=fingerprint,
    )


def build_evidence_query(
    # Keep the capability input explicit in the build evidence query contract.
    capability: ClickHouseCapability,
    block_range: BlockRange,
    columns: tuple[str, ...],
    policy: ClickHouseQueryPolicy,
) -> BoundedQuery:
    """Compile a validation-only query with an explicit bounded projection."""

    if block_range.span > policy.evidence_max_block_span:
        raise ValueError("requested evidence range exceeds ClickHouse hard span limit")
    if (
        block_range.network_id != capability.network_id
        or block_range.position_schema_id != capability.position_schema_id
        # Evaluate the complete build evidence query network id, position schema id and block
        # range condition before guarded effects.
    ):
        raise ValueError("evidence range and ClickHouse capability use different chain identities")
    selected = tuple(sorted(set(columns)))
    if not selected:
        raise ValueError("evidence projection must not be empty")
    # Assemble unknown once so the build evidence query workflow shares one value.
    unknown = set(selected).difference(capability.descriptor.columns)
    if unknown:
        raise ValueError("evidence projection contains unavailable logical columns")
    if capability.logical_block_ordinal_column not in selected:
        raise ValueError("evidence projection must contain the block ordinal")

    # Assemble projection once so the build evidence query workflow shares one value.
    projection = ", ".join(
        f"{quoted_identifier(capability.physical_column(column))} AS {quoted_identifier(column)}"
        for column in selected
    )
    physical_block = quoted_identifier(
        # Keep the logical block ordinal column physical_column step visible while
        # building physical block.
        capability.physical_column(capability.logical_block_ordinal_column)
    )
    predicates = [
        f"{physical_block} >= {{from_block_ordinal:UInt64}}",
        f"{physical_block} < {{to_block_ordinal:UInt64}}",
        # Complete the predicates group only after its semantic components are visible.
    ]
    parameters: dict[str, Any] = {
        "from_block_ordinal": block_range.from_block_ordinal,
        "to_block_ordinal": block_range.to_block_ordinal,
    }
    # Guard this path with capability.utc_pruning is not None before applying effects.
    if capability.utc_pruning is not None:
        # Handle the build evidence query capability.utc_pruning is not None branch as a
        # distinct logical block.
        utc_range = capability.utc_pruning.resolve(block_range)
        if not isinstance(utc_range, UtcDateRange):
            raise TypeError("UTC pruning resolver must return UtcDateRange")
        physical_date = quoted_identifier(
            capability.physical_column(capability.utc_pruning.logical_column)
            # Complete quoted_identifier only after its physical column and logical column
            # inputs are visible in build evidence query.
        )
        predicates.extend(
            (
                f"{physical_date} >= {{from_date_utc:Date}}",
                f"{physical_date} < {{to_date_utc:Date}}",
                # Complete extend only after its >= {from date utc:date} and < {to date
                # utc:date} inputs are visible in build evidence query.
            )
        )
        parameters["from_date_utc"] = utc_range.from_date
        parameters["to_date_utc"] = utc_range.to_date
    sql = "\n".join(
        # Open the select and from payload explicitly for join within build evidence
        # query.
        (
            f"SELECT {projection}",
            f"FROM {capability.qualified_table}",
            f"PREWHERE {' AND '.join(predicates)}",
        )
        # Complete join only after its select and from inputs are visible in build evidence
        # query.
    )
    _assert_safe_shape(sql)
    return BoundedQuery(
        sql=sql,
        parameters=MappingProxyType(parameters),
        # Pass columns explicitly so BoundedQuery receives a reviewable index and logical
        # block ordinal column input in build evidence query.
        columns=selected,
        block_ordinal_column_index=selected.index(capability.logical_block_ordinal_column),
        fingerprint=_query_fingerprint(sql, parameters),
    )


def query_template_digest() -> ContentDigest:
    # Execute the query template digest workflow in explicit, reviewable steps.
    material = "\n--template--\n".join(
        (
            _SERVER_VERSION_SQL,
            _TABLE_METADATA_SQL,
            _COLUMN_METADATA_SQL,
            # Pass bounded-scan v2 explicit-projection half-open-block explicitly so join
            # receives a reviewable server version sql and table metadata sql input in
            # query template digest.
            "bounded-scan:v2:explicit-projection:half-open-block:optional-proven-utc",
            "bounded-evidence:v1:explicit-projection:half-open-block:no-order-assumption",
        )
    )
    return ContentDigest(f"sha256:{sha256(material.encode()).hexdigest()}")


# Define clickhouse capability mapping digest as one focused operation with an explicit
# boundary.
def clickhouse_capability_mapping_digest(
    capabilities: Sequence[ClickHouseCapability],
) -> ContentDigest:
    """Hash the exact secret-free logical-to-physical mapping bundle."""

    if not capabilities:
        raise ValueError("capability mapping must not be empty")
    ordered = tuple(sorted(capabilities, key=lambda item: item.descriptor.capability_id.value))
    identifiers = tuple(item.descriptor.capability_id for item in ordered)
    if len(set(identifiers)) != len(identifiers):
        # Fail the clickhouse capability mapping digest path with ValueError for
        # capability mapping has duplicate logical ids when identifiers is true; do not
        # continue ambiguously.
        raise ValueError("capability mapping has duplicate logical IDs")
    document = {
        "capabilities": [
            {
                "capability": {
                    # Keep the capability id component named inside the document contract.
                    "capability_id": item.descriptor.capability_id.value,
                    "columns": list(item.descriptor.columns),
                    "fidelity": {
                        "chain_finality": item.descriptor.fidelity.chain_finality.value,
                        "completeness": item.descriptor.fidelity.completeness.value,
                        # Keep the consistency component named inside the document
                        # contract.
                        "consistency": item.descriptor.fidelity.consistency.value,
                        "fees": item.descriptor.fidelity.fees.value,
                        "identity": item.descriptor.fidelity.identity.value,
                        "ordering": item.descriptor.fidelity.ordering.value,
                        "state": item.descriptor.fidelity.state.value,
                        # Complete the document group only after its semantic components are
                        # visible.
                    },
                    "keyset_key_is_proven": item.descriptor.keyset_key_is_proven,
                    "mandatory_columns": list(item.descriptor.mandatory_columns),
                    "protocol": item.descriptor.protocol,
                    "protocol_version": item.descriptor.protocol_version,
                    # Keep the proofs component named inside the document contract.
                    "proofs": {
                        field_name: getattr(item.descriptor.proofs, field_name).value
                        for field_name in CAPABILITY_PROOF_FIELDS
                    },
                    "schema_version": item.descriptor.schema_version,
                    # Keep the stream component named inside the document contract.
                    "stream": item.descriptor.stream.value,
                    "total_key": list(item.descriptor.total_key),
                    "utc_pruning_column": item.descriptor.utc_pruning_column,
                    "utc_pruning_is_proven": item.descriptor.utc_pruning_is_proven,
                },
                # Keep the database component named inside the document contract.
                "database": item.database,
                "logical_block_ordinal_column": item.logical_block_ordinal_column,
                "logical_to_physical": dict(sorted(item.logical_to_physical.items())),
                "network_id": item.network_id.value,
                "order_by": list(item.order_by),
                # Keep the position schema id component named inside the document
                # contract.
                "position_schema_id": item.position_schema_id.value,
                "table": item.table,
                "utc_pruning_enabled": item.utc_pruning is not None,
            }
            for item in ordered
            # Complete the document group only after its semantic components are visible.
        ],
        "schema": "backtest.clickhouse-capability-mapping/v2",
    }
    encoded = json.dumps(
        document,
        # Pass allow nan explicitly so encode receives a reviewable utf-8 input in
        # clickhouse capability mapping digest.
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    # Assemble domain once so the clickhouse capability mapping digest workflow shares one
    # value.
    domain = b"backtest.clickhouse-capability-mapping.identity.v2\x00"
    return ContentDigest(sha256(domain + encoded).hexdigest())


_SERVER_VERSION_SQL = "SELECT version() AS server_version LIMIT 1"
_TABLE_METADATA_SQL = """SELECT engine, partition_key, sorting_key
FROM system.tables
WHERE database = {database:String} AND name = {table:String}
LIMIT 2"""
_COLUMN_METADATA_SQL = """SELECT name, type
FROM system.columns
WHERE database = {database:String} AND table = {table:String}
ORDER BY position
LIMIT 4096"""


# Define metadata query templates as one focused operation with an explicit boundary.
def metadata_query_templates() -> tuple[str, str, str]:
    # Execute the metadata query templates workflow in explicit, reviewable steps.
    for sql in (_SERVER_VERSION_SQL, _TABLE_METADATA_SQL, _COLUMN_METADATA_SQL):
        _assert_safe_shape(sql)
    return _SERVER_VERSION_SQL, _TABLE_METADATA_SQL, _COLUMN_METADATA_SQL


def _query_fingerprint(sql: str, parameters: Mapping[str, Any]) -> ContentDigest:
    # Execute the query fingerprint workflow in explicit, reviewable steps.
    normalized_parameters = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in parameters.items()
    }
    material = json.dumps(
        # Open the declared payload explicitly for encode within query fingerprint.
        {"sql": sql, "parameters": normalized_parameters},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ContentDigest(f"sha256:{sha256(material).hexdigest()}")


# Define assert safe shape as one focused operation with an explicit boundary.
def _assert_safe_shape(sql: str) -> None:
    # Execute the assert safe shape workflow in explicit, reviewable steps.
    normalized = " ".join(sql.upper().split())
    if "SELECT *" in normalized:
        raise AssertionError("ClickHouse adapter must never emit SELECT *")
    if re.search(r"\bOFFSET\b", normalized) is not None:
        raise AssertionError("ClickHouse adapter must never emit OFFSET")
    # Guard this path with not normalized.startswith('SELECT ') before applying effects.
    if not normalized.startswith("SELECT "):
        raise AssertionError("ClickHouse source adapter may only emit SELECT")


def _deduplicated(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    # Keep the bounded query component named inside the all contract.
    "BoundedQuery",
    "ClickHouseCapability",
    "ClickHouseQueryPolicy",
    "ProvenUtcDatePruning",
    "UtcDateRange",
    # Keep the build scan query component named inside the all contract.
    "build_scan_query",
    "clickhouse_capability_mapping_digest",
    "metadata_query_templates",
    "query_template_digest",
    "quoted_identifier",
    # Keep the validated identifier component named inside the all contract.
    "validated_identifier",
]
