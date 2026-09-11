"""Single-admission bounded scans over authenticated immutable result payloads."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Iterator
from contextlib import closing, contextmanager

# Scan lifetime uses a monotonic budget and process-wide admission, never event-loop semantics.
from threading import Lock
from time import monotonic
from typing import cast

import pyarrow.parquet as pq

# Strict family codecs preserve the existing immutable record meanings.
from backtest.application.copy_result_codec import copy_position_from_document
from backtest.application.ports.artifacts import ArtifactHandle
from backtest.application.run_results import (
    CopySummaryMetadata,
    FirstSwapSummaryMetadata,
    RunResultTableRole,
    SuccessfulRunManifest,
)

# Limits belong to the query contract, not a mutable deployment preference.
from backtest.application.strategy_results import (
    ANALYTICS_DEADLINE_SECONDS,
    MAX_ANALYTICS_BYTES,
    MAX_ANALYTICS_ROWS,
    StrategyResultsError,
)

# Canonical fill reconstruction reuses domain validation and the original stream hash format.
from backtest.domain.execution import Fill
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AssetId, OrderId, PoolId
from backtest.domain.roundtrips import RoundTripRecord, roundtrip_record_from_document
from backtest.engine.audit import CanonicalStreamHasher, fill_document
from backtest.engine.copytrading_results import CopyPositionRecord

# One process-wide admission gate bounds concurrent optional analytical work.
_SCAN_LOCK = Lock()
# Fill tables predate record_json and keep fixed-width signed atomic values in separate columns.
_FILL_COLUMNS = (
    "order_id",
    "pool_id",
    "sold_asset_id",
    "bought_asset_id",
    # Signed atomic amounts use the writer's fixed-width encoding, separate from identifiers.
    "amount_in_atomic",
    "amount_out_atomic",
    "fee_amount_atomic",
    "boundary_ordinal",
)


@contextmanager
def bounded_entry_records(
    handle: ArtifactHandle, manifest: SuccessfulRunManifest, verify: Callable[[], None]
) -> Iterator[Iterator[RoundTripRecord | CopyPositionRecord | dict[str, object]]]:
    """No partial result is returned by the use case if this iterator fails."""
    if not _SCAN_LOCK.acquire(blocking=False):
        raise StrategyResultsError("RESULT_ANALYTICS_BUSY")
    deadline = monotonic() + ANALYTICS_DEADLINE_SECONDS
    try:
        # Authentication is owned by the enclosing repository handle and lease.
        with closing(_read_records(handle, manifest, verify, deadline)) as records:
            yield records
            _check_deadline(deadline)
    # Admission covers the consumer reduction as well as storage decoding, including exceptions.
    finally:
        _SCAN_LOCK.release()


def _read_records(
    handle: ArtifactHandle,
    manifest: SuccessfulRunManifest,
    verify: Callable[[], None],
    deadline: float,
) -> Generator[RoundTripRecord | CopyPositionRecord | dict[str, object]]:
    """Measure fixed payloads before verification or optional row decoding."""
    generic = isinstance(manifest.bounded_summary, FirstSwapSummaryMetadata)
    selected = ("audit.parquet", "fills.parquet") if generic else ("roundtrips.parquet",)
    # Cold semantic verification also reads balances; include those bytes and rows.
    names = tuple(dict.fromkeys((*selected, "roundtrips.parquet", "final_balances.parquet")))
    total_bytes = total_rows = 0
    for name in names:
        with handle.open_binary(name) as stream:
            total_bytes += stream.seek(0, 2)
            stream.seek(0)
            # Metadata permits rejecting oversized history before decoding any records.
            total_rows += pq.ParquetFile(stream).metadata.num_rows
        if total_bytes > MAX_ANALYTICS_BYTES or total_rows > MAX_ANALYTICS_ROWS:
            raise StrategyResultsError("RESULT_ANALYTICS_LIMIT_EXCEEDED")
    verify()
    decoded_bytes = 0
    for name in selected:
        # Audit and fills are independently hashed against their original summary digests.
        domain = (
            "backtest.canonical-fill-stream.v1"
            if name == "fills.parquet"
            else "backtest.canonical-audit-stream.v1"
        )
        # Independently authenticate audit and fills; presentation tags never enter their hashes.
        hasher = CanonicalStreamHasher(domain)
        with handle.open_binary(name) as stream:
            parquet = pq.ParquetFile(stream)
            expected_rows = parquet.metadata.num_rows
            # Batches bound temporary decoded records; the total quota spans every selected file.
            read_rows = 0
            columns = list(_FILL_COLUMNS) if name == "fills.parquet" else ["record_json"]
            for batch in parquet.iter_batches(batch_size=256, columns=columns):
                _check_deadline(deadline)
                for raw in batch.to_pylist():
                    payload = _fill_payload(raw) if name == "fills.parquet" else raw["record_json"]
                    # Canonical bytes remain the authenticated transport of the original record.
                    if not isinstance(payload, bytes) or len(payload) > 256 * 1024:
                        raise ValueError("invalid bounded result record")
                    document = json.loads(payload)
                    if not isinstance(document, dict):
                        raise ValueError("result record is not an object")
                    # Canonical encoding checks prevent ambiguous duplicate keys and numeric forms.
                    if canonical_json_bytes(document) != payload:
                        raise ValueError("result record is not canonical JSON")
                    decoded_bytes += len(payload)
                    if decoded_bytes > MAX_ANALYTICS_BYTES:
                        raise StrategyResultsError("RESULT_ANALYTICS_LIMIT_EXCEEDED")
                    # Original hashes are computed before adding presentation-only correlation tags.
                    read_rows += 1
                    if generic:
                        hasher.append_canonical_bytes(payload)
                        if name == "fills.parquet":
                            # The wrapper adds ORDER correlation only to the post-run view.
                            yield {
                                "record_type": "RESULT_FILL",
                                "order_id": document["order_id"],
                                "fill": document,
                            }
                        else:
                            # Non-order observations cannot be guessed into strategy signals.
                            yield cast(dict[str, object], document)
                    elif isinstance(manifest.bounded_summary, CopySummaryMetadata):
                        yield copy_position_from_document(document)
                    else:
                        schema = manifest.result_table(RunResultTableRole.ROUNDTRIPS).schema_id
                        # The strict codec preserves legacy/current round-trip semantics.
                        yield roundtrip_record_from_document(document, schema_id=schema)
            _check_deadline(deadline)
            if read_rows != expected_rows:
                raise ValueError("result row count changed during read")
            if generic:
                # A complete late or digest-mismatched scan cannot become a partial successful page.
                comparison = manifest.bounded_summary.comparison
                expected_hash = (
                    comparison.fill_hash if name == "fills.parquet" else comparison.audit_hash
                )
                # Original count and digest must both agree after the entire selected stream.
                if hasher.digest != expected_hash:
                    raise ValueError("result stream differs from the immutable summary")
                if name == "fills.parquet" and read_rows != comparison.fill_count:
                    raise ValueError("fill count differs from the immutable summary")


def _check_deadline(deadline: float) -> None:
    """A late complete scan is rejected too; truncated analytics is never success."""
    if monotonic() > deadline:
        raise StrategyResultsError("RESULT_ANALYTICS_LIMIT_EXCEEDED")


def _fill_payload(raw: dict[str, object]) -> bytes:
    """Decode the published physical format into its original canonical Fill document."""
    if set(raw) != set(_FILL_COLUMNS):
        raise ValueError("invalid fill columns")
    order = raw["order_id"]
    if not isinstance(order, bytes) or len(order) != 32:
        raise ValueError("invalid fill order identity")
    # The three atomic legs share the writer's signed-int128-big-endian-v1 encoding.
    amounts = []
    for key in ("amount_in_atomic", "amount_out_atomic", "fee_amount_atomic"):
        value = raw[key]
        if not isinstance(value, bytes) or len(value) != 16:
            raise ValueError("invalid fill integer encoding")
        amounts.append(int.from_bytes(value, "big", signed=True))
    # Scalar identities are validated before constructing the existing pure domain value.
    identifiers = [raw[key] for key in ("pool_id", "sold_asset_id", "bought_asset_id")]
    if not all(isinstance(value, str) for value in identifiers):
        raise ValueError("invalid fill asset identity")
    boundary = raw["boundary_ordinal"]
    if isinstance(boundary, bool) or not isinstance(boundary, int):
        raise ValueError("invalid fill coordinate")
    # Reusing Fill validation preserves positive amounts, distinct assets and fee bounds.
    fill = Fill(
        OrderId(order.hex()),
        PoolId(str(identifiers[0])),
        AssetId(str(identifiers[1])),
        AssetId(str(identifiers[2])),
        # Input, output and fee legs retain their original atomic units and domain constraints.
        amounts[0],
        amounts[1],
        amounts[2],
        boundary,
    )
    return canonical_json_bytes(fill_document(fill))
