"""Fixed bounded Pump participation acquisition with preserved source multiplicity."""

from collections.abc import Iterator
from secrets import token_hex
from typing import Any, Final

# The SDK protocol exposes only the read operations needed by this fixed profile.
from backtest.adapters.source.clickhouse.reader import ClickHouseClientProtocol
from backtest.application.research import (
    MAX_SOURCE_ROWS,
    SOL_QUOTE,
    # Validation and semantic caps are application-owned, not driver policy.
    SOURCE_PROFILE,
    ResearchDatasetSpec,
    ResearchError,
    WalletObservation,
)

# Query provenance contains only the fixed mapping and safe typed operands.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest

SOURCE_COLUMNS: Final = (
    # This allowlist must remain synchronized with the explicit fixed query projection.
    "slot",
    "tx_idx",
    "ix_idx",
    "signature",
    "block_time",
    # These source amount legs are observations, not wallet-net cash accounting.
    "base_coin",
    "quote_coin",
    "direction",
    "base_coin_amount",
    "quote_coin_amount",
    # Participant roles and success are read directly instead of inferred from launches.
    "signing_wallet",
    "fee_payer",
    "failed",
)

# No launch join or DISTINCT: every successful SOL-paired source row is retained.
RESEARCH_SQL: Final = """SELECT
slot AS block_ordinal, tx_idx AS transaction_index, ix_idx AS source_instruction_index,
toStringCutToZero(signature) AS signature, toUnixTimestamp(block_time) AS block_time_s,
toStringCutToZero(base_coin) AS mint, toStringCutToZero(quote_coin) AS quote_asset,
upperUTF8(direction) AS side, base_coin_amount AS base_amount_atomic,
quote_coin_amount AS quote_amount_atomic, toStringCutToZero(signing_wallet) AS signing_wallet,
toStringCutToZero(fee_payer) AS fee_payer
FROM pumpfun_v2_swaps
PREWHERE slot >= {start:UInt64} AND slot < {stop:UInt64}
WHERE failed = 0 AND quote_coin = {quote:String}"""

# Source-schema categories are fixed and included in the profile identity.
_INTEGER_TYPES: Final = frozenset(
    f"{prefix}{width}" for prefix in ("UInt", "Int") for width in (8, 16, 32, 64)
)
_NUMERIC_COLUMNS: Final = frozenset(
    # All source integers still undergo per-row nonnegative/range validation.
    {"slot", "tx_idx", "ix_idx", "base_coin_amount", "quote_coin_amount", "failed"}
)


def profile_digest() -> ContentDigest:
    """Pin the fixed query and schema rules without endpoint/database credentials."""

    return domain_digest(
        SOURCE_PROFILE,
        {
            "sql": RESEARCH_SQL,
            "columns": SOURCE_COLUMNS,
            # A changed interpretation of the same physical columns requires a new identity.
            "schema_policy": "required-nonnull-numeric-string-second-time/v2",
            "multiplicity": "retain-all-observations/v1",
        },
    )


class ClickHouseResearchSource:
    """An injected read-only SDK client; bootstrap alone owns its credentials."""

    def __init__(
        self, client: ClickHouseClientProtocol, *, database: str, memory_bytes: int = 512 * 1024**2
    ) -> None:
        """Retain the injected read-only client and an explicit remote memory budget."""
        self._client = client
        self._database = database
        self._memory_bytes = memory_bytes

    def inspect(self, spec: ResearchDatasetSpec) -> ContentDigest:
        """Check all required physical columns before issuing a source-row query."""

        if spec.profile_digest != profile_digest():
            raise ResearchError("RESEARCH_SOURCE_PROFILE_MISMATCH")
        query = "SELECT name, type FROM system.columns WHERE database={database:String} "
        query += "AND table='pumpfun_v2_swaps' ORDER BY position"
        # Metadata reads are bounded too; unexpected width/size cannot be ignored.
        result = self._client.query(
            query,
            parameters={"database": self._database},
            query_tz="UTC",
            settings={
                # Metadata access obeys the same read-only session and explicit RAM cap.
                "readonly": 1,
                "max_memory_usage": self._memory_bytes,
                "max_result_rows": 256,
                "max_result_bytes": 1_048_576,
                "result_overflow_mode": "throw",
                # A metadata timeout cannot authorize a subsequent source-row scan.
                "max_execution_time": 30,
            },
            transport_settings={"query_id": "bt_research_schema_" + token_hex(12)},
        )
        # Driver result handles are closed even when source metadata is malformed.
        try:
            rows = result.result_rows
            if len(rows) > 256 or any(len(row) != 2 for row in rows):
                raise ResearchError("RESEARCH_SOURCE_SCHEMA_MISMATCH")
            columns = {str(row[0]): str(row[1]) for row in rows}
        # Releasing metadata buffers is mandatory on both successful and rejected schemas.
        finally:
            result.close()
        # A duplicate metadata name is not an alternative version of the column.
        if len(columns) != len(rows) or not set(SOURCE_COLUMNS) <= set(columns):
            raise ResearchError("RESEARCH_SOURCE_SCHEMA_MISMATCH")
        for name in SOURCE_COLUMNS:
            if not _accepted_type(name, columns[name]):
                raise ResearchError("RESEARCH_SOURCE_SCHEMA_MISMATCH")
        # Hash observed required types only; database/endpoint values are not identity operands.
        return domain_digest(
            "wallet-research-source-schema/v1", {name: columns[name] for name in SOURCE_COLUMNS}
        )

    def batches(self, spec: ResearchDatasetSpec) -> Iterator[tuple[WalletObservation, ...]]:
        """Read complete bounded source rows; every overflow is a failure, never LIMIT."""

        if spec.profile_digest != profile_digest():
            raise ResearchError("RESEARCH_SOURCE_PROFILE_MISMATCH")
        parameters = {
            # The typed half-open range is authoritative; time is not a pruning shortcut.
            "start": spec.block_range.from_block_ordinal,
            "stop": spec.block_range.to_block_ordinal,
            "quote": SOL_QUOTE,
        }
        # Limit server scan work as well as returned bytes; no unbounded sort is requested.
        settings = {
            "readonly": 1,
            "max_execution_time": 120,
            "max_memory_usage": self._memory_bytes,
            "max_rows_to_read": 20_000_000,
            # Both scan-work and result limits throw; neither is a request for truncation.
            "max_bytes_to_read": 2 * 1024**3,
            "read_overflow_mode": "throw",
            "max_result_rows": MAX_SOURCE_ROWS,
            # Throw-on-excess prevents a successful-looking truncated observational cut.
            "max_result_bytes": 1024**3,
            "result_overflow_mode": "throw",
            "max_block_size": 8_192,
            "max_threads": 1,
        }
        # Every query has a fresh opaque transport ID with no source configuration embedded.
        stream = self._client.query_row_block_stream(
            RESEARCH_SQL,
            parameters=parameters,
            settings=settings,
            # UTC affects decoding only; reported block positions define extraction bounds.
            query_tz="UTC",
            transport_settings={"query_id": "bt_research_rows_" + token_hex(12)},
        )
        # Source order and stream block size are not research semantic operands.
        count = 0
        with stream as batches:
            for batch in batches:
                count += len(batch)
                if count > MAX_SOURCE_ROWS or len(batch) > 65_536:
                    # Enforce caps locally even if a driver or remote setting is ineffective.
                    raise ResearchError("RESEARCH_SOURCE_ROW_LIMIT")
                # Strict row construction validates required roles and unsigned coordinates.
                observations = tuple(_observation(row) for row in batch)
                if any(
                    not spec.block_range.contains_block(row.block_ordinal) for row in observations
                ):
                    raise ResearchError("RESEARCH_SOURCE_RANGE_MISMATCH")
                # Yield a complete validated batch, retaining multiplicity and source roles.
                yield observations


# Physical type acceptance never increases completeness, finality or availability claims.
def _accepted_type(name: str, value: str) -> bool:
    """Allow only explicit non-null fixed-profile physical types."""

    if name in _NUMERIC_COLUMNS:
        return value in _INTEGER_TYPES or (name == "failed" and value == "Bool")
    if name == "block_time":
        return value == "DateTime" or (value.startswith("DateTime('") and value.endswith("')"))
    # Dictionary-encoded non-null strings keep their values; nullable/numeric wrappers reject.
    if value == "LowCardinality(String)":
        return True
    # FixedString is normalized only by removing its physical trailing NUL padding.
    return value == "String" or value in {f"FixedString({size})" for size in (44, 64, 88, 128)}


def _observation(row: Any) -> WalletObservation:
    """Keep the SDK's untyped row conversion at the source adapter seam."""

    if len(row) != 12:
        raise ResearchError("RESEARCH_SOURCE_ROW_WIDTH")
    return WalletObservation(*row)
