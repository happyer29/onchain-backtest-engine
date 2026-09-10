"""Fixed columnar research schemas and deterministic streaming table digests."""

from collections.abc import Iterator
from decimal import Decimal
from hashlib import sha256
from typing import Any, Final

# Arrow is the storage boundary; Decimal is used only to decode exact scale-zero sums.
import pyarrow as pa
import pyarrow.parquet as pq

# Infrastructure types stop at this adapter; the application sees integers and text.
from backtest.application.research import ResearchError, ResearchTable, WalletObservation
from backtest.domain.hashing import canonical_json_bytes

BATCH_ROWS: Final = 8_192
OBSERVATION_COLUMNS: Final = (
    # Chain coordinates and transaction identity precede all observation attributes.
    "block_ordinal",
    "transaction_index",
    "source_instruction_index",
    "signature",
    "block_time_s",
    # Field order is versioned and participates in the canonical observation digest.
    "mint",
    "quote_asset",
    "side",
    "base_amount_atomic",
    "quote_amount_atomic",
    # These roles remain distinct even when the source reports the same address.
    "signing_wallet",
    "fee_payer",
)

# Lexical strings follow reported numeric coordinates, with no deduplication key.
OBSERVATION_ORDER: Final = ", ".join(OBSERVATION_COLUMNS)
_OBSERVATION_INTS: Final = frozenset(
    {
        "block_ordinal",
        "transaction_index",
        # Source positions and amount legs are integers, not floating analytic measures.
        "source_instruction_index",
        "block_time_s",
        "base_amount_atomic",
        "quote_amount_atomic",
        # The remaining observation fields retain their exact text representation.
    }
)


def raw_schema() -> pa.Schema:
    """UInt64 preserves validated source values without a lossy floating conversion."""

    fields = [
        pa.field(name, pa.uint64() if name in _OBSERVATION_INTS else pa.string(), nullable=False)
        for name in OBSERVATION_COLUMNS
    ]
    # Field order is the fixed logical observation order used by both hashing and queries.
    return pa.schema(fields)


def table_schema(role: ResearchTable) -> pa.Schema:
    """Closed schemas make files and browser exports impossible to select by path."""

    row_id = pa.field("row_id", pa.uint64(), nullable=False)
    if role is ResearchTable.OBSERVATIONS:
        return pa.schema([row_id, *raw_schema()])
    if role is ResearchTable.TOKEN_MODES:
        # Absent creation uses an empty reference, never synthetic chain coordinates.
        fields = [
            pa.field(name, pa.string(), nullable=False) for name in ("mint", "mode", "creation_ref")
        ]
        # The issue marks partial creation evidence without changing observed mode values.
        count = pa.field("source_rows", pa.uint64(), nullable=False)
        issue = pa.field("issue", pa.string(), nullable=False)
        return pa.schema([row_id, *fields, count, issue])
    if role is ResearchTable.DATA_ISSUES:
        # One row per affected mint keeps warning pages bounded and inspectable.
        fields = [pa.field(name, pa.string(), nullable=False) for name in ("mint", "issue")]
        count = pa.field("observation_rows", pa.uint64(), nullable=False)
        return pa.schema([row_id, *fields, count])
    if role is ResearchTable.ACTIVITY:
        # Activity groups source rows by signer and retains the observed block span.
        names: tuple[str, ...] = (
            "signing_wallet",
            "buy_rows",
            "sell_rows",
            "mint_count",
            # These bounds describe observation coverage, not the wallet's lifetime.
            "first_block",
            "last_block",
        )
        # Aggregate amount legs can exceed UInt64; decimal scale zero remains exact.
        fields = [
            pa.field(name, pa.string() if name == "signing_wallet" else pa.uint64(), nullable=False)
            for name in names
        ]
        # Buy/sell totals describe source quote legs, not net wallet cash or fee accounting.
        amounts = ("source_quote_buy_atomic", "source_quote_sell_atomic")
        # Scale zero preserves exact sums even when repeated rows exceed UInt64.
        money = [pa.field(name, pa.decimal128(38, 0), nullable=False) for name in amounts]
        return pa.schema([row_id, *fields, *money])
    if role is ResearchTable.PAIRS:
        names = (
            # Pair identity is lexical; direction counts compare transaction coordinates.
            "signer_a",
            "signer_b",
            "shared_mints",
            "a_first",
            "b_first",
            # Same-transaction events are ties, and evidence occupies a contiguous range.
            "same_transaction",
            "evidence_start",
            "evidence_count",
        )
        # Evidence ranges refer only to the exact sorted table in the same result.
        fields = [
            pa.field(
                name, pa.string() if name.startswith("signer_") else pa.uint64(), nullable=False
            )
            # Every pair field is required; nulls cannot silently hide missing counts or roles.
            for name in names
        ]
        # Pair rows start with a stable ordinal before their signer/count fields.
        return pa.schema([row_id, *fields])
    # Evidence has one immutable row reference for each side of the observed relation.
    return pa.schema(
        [
            row_id,
            pa.field("pair_row_id", pa.uint64(), nullable=False),
            pa.field("mint", pa.string(), nullable=False),
            # Evidence row references are local ordinals, never claimed as chain event IDs.
            pa.field("left_observation", pa.uint64(), nullable=False),
            pa.field("right_observation", pa.uint64(), nullable=False),
            pa.field("delta_seconds", pa.int64(), nullable=False),
        ]
    )


# Source ports expose value objects; only this adapter builds native column arrays.
def observation_batch(rows: tuple[WalletObservation, ...]) -> pa.RecordBatch:
    """Convert only one bounded source batch; no full-period Python row collection."""

    values = [row.values() for row in rows]
    # Materialize columns only for this bounded batch before handing them to Arrow.
    columns = [
        pa.array([row[index] for row in values], type=field.type)
        for index, field in enumerate(raw_schema())
    ]
    return pa.RecordBatch.from_arrays(columns, schema=raw_schema())


# This conversion is shared by row hashing and decimal-string transport formatting.
def normalized_scalar(value: Any) -> int | str:
    """Canonical and transport values have no floats or context-dependent decimals."""

    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ResearchError("RESEARCH_INVALID_TABLE")
        return int(value)
    # Nullable, boolean and floating values are outside every research table schema.
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ResearchError("RESEARCH_INVALID_TABLE")
    return value


class TableDigest:
    """Hash a fixed logical row stream independently of Parquet physical batches."""

    def __init__(self, role: ResearchTable) -> None:
        self._digest = sha256(("wallet-research-table/v1:" + role.value + "\x00").encode())
        self.count = 0

    def update(self, batch: pa.RecordBatch) -> None:
        """Check row ordinals while hashing every complete fixed-order row."""

        columns = [column.to_pylist() for column in batch.columns]
        for values in zip(*columns, strict=True):
            row = tuple(normalized_scalar(value) for value in values)
            if row[0] != self.count:
                raise ResearchError("RESEARCH_TABLE_ORDER_MISMATCH")
            # Length prefixes make concatenated canonical row encodings unambiguous.
            encoded = canonical_json_bytes(row)
            self._digest.update(len(encoded).to_bytes(8, "big"))
            self._digest.update(encoded)
            self.count += 1

    # Exposing the digest never finalizes or resets the running hash state.
    @property
    def hex(self) -> str:
        """Return a snapshot of the stream digest without mutating it."""

        return self._digest.hexdigest()


def bounded_rows(
    file: pq.ParquetFile, role: ResearchTable, start: int, count: int
) -> Iterator[dict[str, str]]:
    """Use immutable row-group counts to read only groups covering a bounded page."""

    if file.schema_arrow != table_schema(role) or start < 0 or count < 0:
        raise ResearchError("RESEARCH_INVALID_TABLE")
    consumed = 0
    stop = min(file.metadata.num_rows, start + count)
    # Footer navigation skips whole row groups without scanning earlier observations.
    for group in range(file.num_row_groups):
        group_rows = file.metadata.row_group(group).num_rows
        if group_rows > BATCH_ROWS:
            raise ResearchError("RESEARCH_INVALID_TABLE")
        group_end = consumed + group_rows
        # Decode one fixed-size group at a time, retaining only the requested rows.
        if consumed < stop and group_end > start:
            table = file.read_row_group(group)
            first = max(0, start - consumed)
            last = min(group_rows, stop - consumed)
            # Ordinals stay global even though only one physical row group is decoded.
            for index, row in enumerate(
                table.slice(first, last - first).to_pylist(), consumed + first
            ):
                # A footer does not replace validation of selected logical ordinals.
                if row["row_id"] != index:
                    raise ResearchError("RESEARCH_TABLE_ORDER_MISMATCH")
                yield {name: str(normalized_scalar(value)) for name, value in row.items()}
        # Stop immediately after the requested page; later row groups remain unopened.
        consumed = group_end
        if consumed >= stop:
            break
