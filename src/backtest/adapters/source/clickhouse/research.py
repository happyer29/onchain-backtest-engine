"""Fixed bounded Pump participation acquisition with preserved source multiplicity."""

from collections.abc import Iterator
from dataclasses import replace
from secrets import token_hex
from typing import Any, Final

# The SDK protocol exposes only the read operations needed by this fixed profile.
from backtest.adapters.source.clickhouse.reader import ClickHouseClientProtocol
from backtest.application.research import (
    MAX_MODE_MINTS,
    MAX_SOURCE_ROWS,
    SOL_QUOTE,
    # Validation and semantic caps are application-owned, not driver policy.
    SOURCE_PROFILE,
    ResearchDatasetSpec,
    ResearchError,
    ResearchTokenMode,
    TokenMode,
    # Raw observations and metadata share primitive validation, not row filtering.
    WalletObservation,
    integer,
    solana_base58,
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
    {
        "slot",
        "tx_idx",
        "ix_idx",
        # Amount and mode columns are checked as exact integers at the source boundary.
        "base_coin_amount",
        "quote_coin_amount",
        "failed",
        "creation_ix_index",
        # An immutable creation flag has stricter per-row 0/1 validation below.
        "mayhem_mode",
    }
)


# One separate metadata read classifies the exact observed mints without multiplying swap rows.
MODE_COLUMNS: Final = ("mint", "slot", "tx_idx", "creation_ix_index", "signature", "mayhem_mode")
# No version-selection clause may discard contradictory creation records.
MODE_SQL: Final = """SELECT toStringCutToZero(mint),slot,tx_idx,creation_ix_index,
toStringCutToZero(signature),mayhem_mode
FROM pumpfun_token_creation
PREWHERE slot >= {creation_start:UInt64} AND slot < {creation_stop:UInt64}
WHERE toStringCutToZero(mint) IN {mints:Array(String)}"""


def profile_digest() -> ContentDigest:
    """Pin the fixed query and schema rules without endpoint/database credentials."""

    return domain_digest(
        SOURCE_PROFILE,
        {
            "sql": RESEARCH_SQL,
            "columns": SOURCE_COLUMNS,
            # A changed interpretation of the same physical columns requires a new identity.
            "schema_policy": "required-nonnull-numeric-string-second-time/v3",
            "multiplicity": "retain-all-observations/v1",
            # Creation classification has its own fixed projection, scope and conflict policy.
            "mode_sql": MODE_SQL,
            "mode_columns": MODE_COLUMNS,
            "mode_policy": "exact-observed-mints-consistent-creation-skip-empty-signature/v2",
            # The creation cut includes launches preceding the bounded observation period.
            "creation_range": "[0,swap-to-block-ordinal)",
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

        if spec.schema_version != 2 or spec.profile_digest != profile_digest():
            raise ResearchError("RESEARCH_SOURCE_PROFILE_MISMATCH")
        swaps = self._schema("pumpfun_v2_swaps", SOURCE_COLUMNS)
        modes = self._schema("pumpfun_token_creation", MODE_COLUMNS)
        # Both physical schemas bind the same freshly prepared acquisition.
        return domain_digest(
            "wallet-research-source-schema/v2", {"swaps": swaps, "token_modes": modes}
        )

    def _schema(self, table: str, required: tuple[str, ...]) -> dict[str, str]:
        """Inspect only internal fixed table names, with bounded metadata and closed handles."""

        query = "SELECT name, type FROM system.columns WHERE database={database:String} "
        query += "AND table={table:String} ORDER BY position"
        # Metadata reads are bounded too; unexpected width/size cannot be ignored.
        result = self._client.query(
            query,
            parameters={"database": self._database, "table": table},
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
        if len(columns) != len(rows) or not set(required) <= set(columns):
            raise ResearchError("RESEARCH_SOURCE_SCHEMA_MISMATCH")
        for name in required:
            if not _accepted_type(name, columns[name]):
                raise ResearchError("RESEARCH_SOURCE_SCHEMA_MISMATCH")
        # Hash observed required types only; database/endpoint values are not identity operands.
        return {name: columns[name] for name in required}

    def batches(self, spec: ResearchDatasetSpec) -> Iterator[tuple[WalletObservation, ...]]:
        """Read complete bounded source rows; every overflow is a failure, never LIMIT."""

        if spec.schema_version != 2 or spec.profile_digest != profile_digest():
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
            # Scanned bytes and returned rows have independent fail-closed ceilings.
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

    def modes(
        self, spec: ResearchDatasetSpec, mints: tuple[str, ...]
    ) -> tuple[ResearchTokenMode, ...]:
        """Read bounded creation evidence for exactly the retained snapshot mint set."""

        if spec.schema_version != 2 or spec.profile_digest != profile_digest():
            raise ResearchError("RESEARCH_SOURCE_PROFILE_MISMATCH")
        # Operand size and canonical uniqueness are proved before remote contact.
        if (
            not isinstance(mints, tuple)
            or len(mints) > MAX_MODE_MINTS
            # A canonical unique operand makes missing-record classification deterministic.
            or tuple(sorted(set(mints))) != mints
        ):
            raise ResearchError("RESEARCH_MODE_MINT_LIMIT")
        # Full address validation precedes the single bounded parameterized lookup.
        for mint in mints:
            solana_base58(mint)
        if not mints:
            return ()
        # The mint operand is complete and exact; no broad token history is mirrored.
        parameters = {
            "creation_start": 0,
            "creation_stop": spec.block_range.to_block_ordinal,
            "mints": list(mints),
        }
        # The historical creation range is pruned by exact observed mints, never a full mirror.
        settings = {
            "readonly": 1,
            "max_execution_time": 120,
            "max_memory_usage": self._memory_bytes,
            "max_rows_to_read": 20_000_000,
            # Scanned bytes and returned rows have independent fail-closed ceilings.
            "max_bytes_to_read": 2 * 1024**3,
            "read_overflow_mode": "throw",
            "max_result_rows": MAX_SOURCE_ROWS,
            "max_result_bytes": 1024**3,
            "result_overflow_mode": "throw",
            # Driver batches and native parallelism stay inside one admitted worker budget.
            "max_block_size": 8192,
            "max_threads": 1,
        }
        # One value per mint bounds memory while retaining repeated-record counts.
        selected = set(mints)
        known: dict[str, ResearchTokenMode] = {}
        count = 0
        # Operational query IDs carry no endpoint, key material or semantic identity.
        stream = self._client.query_row_block_stream(
            MODE_SQL,
            parameters=parameters,
            settings=settings,
            # Driver transport metadata remains outside artifact provenance.
            query_tz="UTC",
            transport_settings={"query_id": "bt_research_modes_" + token_hex(12)},
        )
        # A failed stream cannot return a partially classified mint set to publication.
        with stream as batches:
            for batch in batches:
                count += len(batch)
                if len(batch) > 65_536 or count > MAX_SOURCE_ROWS:
                    raise ResearchError("RESEARCH_SOURCE_ROW_LIMIT")
                # Local validation catches malformed results even if remote predicates fail.
                for raw in batch:
                    observed = _mode_observation(raw, selected, spec.block_range.to_block_ordinal)
                    previous = known.get(observed.mint)
                    # Never choose latest/first/majority when source creation evidence disagrees.
                    if previous and (
                        previous.mode != observed.mode or previous.creation != observed.creation
                    ):
                        raise ResearchError("RESEARCH_MODE_CONFLICT")
                    # Exact repeats preserve evidence multiplicity without multiplying trades.
                    known[observed.mint] = replace(
                        observed, source_rows=1 if previous is None else previous.source_rows + 1
                    )
        # Missing rows retain UNKNOWN without an invented creation reference.
        return tuple(
            known[mint] if mint in known else ResearchTokenMode(mint, TokenMode.UNKNOWN, None, 0)
            for mint in mints
        )


# Physical type acceptance never increases completeness, finality or availability claims.
def _accepted_type(name: str, value: str) -> bool:
    """Allow only explicit non-null fixed-profile physical types."""

    if name in _NUMERIC_COLUMNS:
        return value in _INTEGER_TYPES or (name in {"failed", "mayhem_mode"} and value == "Bool")
    if name == "block_time":
        return value == "DateTime" or (value.startswith("DateTime('") and value.endswith("')"))
    # Dictionary-encoded non-null strings keep their values; nullable/numeric wrappers reject.
    if value == "LowCardinality(String)":
        return True
    # The live creation table pads full base58 mints to 48 bytes; only that field admits it.
    if name == "mint" and value == "FixedString(48)":
        return True
    # FixedString is normalized only by removing its physical trailing NUL padding.
    return value == "String" or value in {f"FixedString({size})" for size in (44, 64, 88, 128)}


def _observation(row: Any) -> WalletObservation:
    """Keep the SDK's untyped row conversion at the source adapter seam."""

    if len(row) != 12:
        raise ResearchError("RESEARCH_SOURCE_ROW_WIDTH")
    return WalletObservation(*row)


def _mode_observation(raw: Any, mints: set[str], stop: int) -> ResearchTokenMode:
    """Bind a physical creation row to the exact requested mint and authoritative upper cut."""

    if len(raw) != 6:
        raise ResearchError("RESEARCH_SOURCE_ROW_WIDTH")
    mint = solana_base58(raw[0])
    block = integer(raw[1], maximum=2**32 - 1)
    # A source-side predicate is rechecked locally; rows outside the lookup cannot classify a token.
    if mint not in mints or block >= stop:
        raise ResearchError("RESEARCH_SOURCE_RANGE_MISMATCH")
    # Bool and integer 0/1 are explicit physical encodings; truthy strings are invalid.
    mode = raw[5]
    if isinstance(mode, bool):
        mode = int(mode)
    if type(mode) is not int or mode not in {0, 1}:
        raise ResearchError("RESEARCH_INVALID_MODE")
    # Only literal source 0/1 is classified; null and truthy strings are never interpreted as false.
    signature = "" if raw[4] == "" else solana_base58(raw[4], size=64)
    creation = (block, integer(raw[2]), integer(raw[3]), signature)
    issue = "MISSING_CREATION_SIGNATURE" if signature == "" else ""
    # The reported flag remains evidence; the explicit issue prevents eligibility in either mode.
    return ResearchTokenMode(
        mint, TokenMode.MAYHEM if mode else TokenMode.NON_MAYHEM, creation, 1, issue
    )
