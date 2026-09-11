"""Optional analytical reads reject quotas/corruption and always release admission."""

from io import BytesIO
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import backtest.adapters.results.analytics as adapter
from backtest.application.run_results import FirstSwapSummaryMetadata
from backtest.application.strategy_results import StrategyResultsError
from backtest.domain.execution import Fill
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import AssetId, OrderId, PoolId
from backtest.engine.audit import CanonicalStreamHasher, fill_document


def _payload(records):
    """Real Parquet metadata exercises pre-decoding admission, including empty tables."""
    stream = BytesIO()
    table = pa.Table.from_arrays([pa.array(records, type=pa.binary())], names=["record_json"])
    pq.write_table(table, stream)
    return stream.getvalue()


class Handle:
    """Fixed immutable payload names model the existing artifact-handle port."""

    def __init__(self, payload):
        self.payloads = {
            "audit.parquet": _payload(payload),
            "fills.parquet": _payload([]),
            "roundtrips.parquet": _payload([]),
            "final_balances.parquet": _payload([]),
        }
        self.streams = []

    def open_binary(self, name):
        stream = BytesIO(self.payloads[name])
        self.streams.append(stream)
        return stream


def _fixture(payload=None):
    record = {"record_type": "INTENT_PROPOSED", "order_id": "a" * 64, "boundary_ordinal": 2}
    encoded = canonical_json_bytes(record) if payload is None else payload
    hasher = CanonicalStreamHasher("backtest.canonical-audit-stream.v1")
    hasher.append_canonical_bytes(encoded)
    # This fixture isolates admission/stream hashing; full manifest verification is injected.
    summary = object.__new__(FirstSwapSummaryMetadata)
    object.__setattr__(
        summary,
        "comparison",
        SimpleNamespace(
            audit_hash=hasher.digest,
            fill_hash=CanonicalStreamHasher("backtest.canonical-fill-stream.v1").digest,
            fill_count=0,
        ),
    )
    return Handle([encoded]), SimpleNamespace(bounded_summary=summary), record


def test_admitted_complete_read_checks_digest_and_releases_streams():
    handle, manifest, expected = _fixture()
    verified = []
    with adapter.bounded_entry_records(handle, manifest, lambda: verified.append(True)) as records:
        assert list(records) == [expected]
    assert verified == [True]
    assert all(stream.closed for stream in handle.streams)
    assert not adapter._SCAN_LOCK.locked()


@pytest.mark.parametrize("limit", ["MAX_ANALYTICS_BYTES", "MAX_ANALYTICS_ROWS"])
def test_oversized_read_rejects_before_semantic_verification(monkeypatch, limit):
    handle, manifest, _ = _fixture()
    monkeypatch.setattr(adapter, limit, 0)
    verified = []
    with (
        pytest.raises(StrategyResultsError, match="RESULT_ANALYTICS_LIMIT_EXCEEDED"),
        adapter.bounded_entry_records(handle, manifest, lambda: verified.append(True)) as rows,
    ):
        list(rows)
    assert not verified and not adapter._SCAN_LOCK.locked()
    assert all(stream.closed for stream in handle.streams)


def test_busy_read_does_not_open_any_payload():
    handle, manifest, _ = _fixture()
    with (
        adapter._SCAN_LOCK,
        pytest.raises(StrategyResultsError, match="RESULT_ANALYTICS_BUSY"),
        adapter.bounded_entry_records(handle, manifest, lambda: None),
    ):
        pytest.fail("busy scan was admitted")
    assert handle.streams == []


@pytest.mark.parametrize("payload", [b"[]", b"{bad", b'{"x": 1}', b'"bad"'])
def test_malformed_or_noncanonical_record_never_becomes_analytics(payload):
    handle, manifest, _ = _fixture(payload)
    with (
        pytest.raises(ValueError),
        adapter.bounded_entry_records(handle, manifest, lambda: None) as records,
    ):
        list(records)
    assert not adapter._SCAN_LOCK.locked()
    assert all(stream.closed for stream in handle.streams)


def test_consumer_failure_releases_live_scan():
    handle, manifest, _ = _fixture()
    with (
        pytest.raises(RuntimeError, match="consumer"),
        adapter.bounded_entry_records(handle, manifest, lambda: None) as records,
    ):
        next(records)
        raise RuntimeError("consumer")
    assert not adapter._SCAN_LOCK.locked()
    assert all(stream.closed for stream in handle.streams)


def test_deadline_rejects_complete_late_result(monkeypatch):
    handle, manifest, _ = _fixture()
    monkeypatch.setattr(adapter, "ANALYTICS_DEADLINE_SECONDS", -1)
    with (
        pytest.raises(StrategyResultsError, match="RESULT_ANALYTICS_LIMIT_EXCEEDED"),
        adapter.bounded_entry_records(handle, manifest, lambda: None) as records,
    ):
        list(records)
    assert not adapter._SCAN_LOCK.locked()


def test_consumer_work_remains_under_admission_and_deadline(monkeypatch):
    """Sorting and reduction after iteration must not outlive the query budget."""
    handle, manifest, _ = _fixture()
    clock = [0.0]
    monkeypatch.setattr(adapter, "monotonic", lambda: clock[0])
    with (
        pytest.raises(StrategyResultsError, match="RESULT_ANALYTICS_LIMIT_EXCEEDED"),
        adapter.bounded_entry_records(handle, manifest, lambda: None) as records,
    ):
        # Exhausted storage iteration does not release admission while the consumer still works.
        assert list(records)
        assert adapter._SCAN_LOCK.locked()
        clock[0] = adapter.ANALYTICS_DEADLINE_SECONDS + 1
    assert not adapter._SCAN_LOCK.locked()


def _with_fill(handle, manifest):
    """Use the writer's actual columnar format and original canonical stream digest."""
    fill = Fill(OrderId("a" * 64), PoolId("pool"), AssetId("SOL"), AssetId("TOKEN"), 100, 90, 1, 3)
    document = fill_document(fill)
    raw = {**document, "order_id": bytes.fromhex(document["order_id"])}
    for key in ("amount_in_atomic", "amount_out_atomic", "fee_amount_atomic"):
        raw[key] = raw[key].to_bytes(16, "big", signed=True)
    # Values are fixed-width physical bytes, not record_json or float amounts.
    stream = BytesIO()
    pq.write_table(pa.Table.from_pylist([raw]), stream)
    handle.payloads["fills.parquet"] = stream.getvalue()
    hasher = CanonicalStreamHasher("backtest.canonical-fill-stream.v1")
    hasher.append_canonical_bytes(canonical_json_bytes(document))
    # Preserve the independent audit digest while binding the exact one-row fill stream.
    comparison = manifest.bounded_summary.comparison
    comparison.fill_hash = hasher.digest
    comparison.fill_count = 1
    return document, raw


def test_columnar_fill_preserves_original_canonical_hash_and_order():
    """A correlated presentation tag is added only after hashing the original fill."""
    handle, manifest, _ = _fixture()
    document, _ = _with_fill(handle, manifest)
    with adapter.bounded_entry_records(handle, manifest, lambda: None) as records:
        result = list(records)
    assert result[-1] == {"record_type": "RESULT_FILL", "order_id": "a" * 64, "fill": document}


@pytest.mark.parametrize("field", ["fill_hash", "fill_count"])
def test_authenticated_fill_metadata_mismatch_rejects_complete_scan(field):
    """Neither a correct digest with wrong count nor a wrong digest is a valid result."""
    handle, manifest, _ = _fixture()
    _with_fill(handle, manifest)
    setattr(manifest.bounded_summary.comparison, field, "0" * 64 if field == "fill_hash" else 2)
    with (
        pytest.raises(ValueError, match="immutable summary"),
        adapter.bounded_entry_records(handle, manifest, lambda: None) as records,
    ):
        list(records)
    assert not adapter._SCAN_LOCK.locked()


@pytest.mark.parametrize("field", ["order_id", "amount_out_atomic", "boundary_ordinal"])
def test_malformed_physical_fill_cannot_enter_the_projection(field):
    """Reject malformed identity, integer encoding and bool-as-coordinate before domain decoding."""
    handle, manifest, _ = _fixture()
    _, raw = _with_fill(handle, manifest)
    raw[field] = True if field == "boundary_ordinal" else b"short"
    with pytest.raises(ValueError, match="invalid fill"):
        adapter._fill_payload(raw)
