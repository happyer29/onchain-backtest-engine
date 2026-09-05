"""Fail-closed tests for bounded semantic verification reuse."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event, Lock
from types import SimpleNamespace
from typing import IO, cast

# Real Arrow envelopes ensure cached rows traverse the production decoder.
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import backtest.adapters.results.parquet as parquet_results
from backtest.application.ports.artifacts import ArtifactHandle, ArtifactRepository
from backtest.application.ports.run_results import RoundTripCursor

# Result metadata stays production-shaped even when repository I/O is isolated.
from backtest.application.run_results import (
    ROUNDTRIP_RESULT_SCHEMA_V4,
    PumpfunSnipingSummaryMetadata,
    RunResultTableRole,
    SuccessfulRunManifest,
)

# Chain identity is needed for strict decoded-row reconciliation.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.identifiers import ArtifactId, ContentDigest
from backtest.engine.audit import CanonicalStreamHasher


def _factory(*, entries: int = 64) -> parquet_results.LocalParquetRunResultReaderFactory:
    """Build a cache factory when repository I/O is outside the focused test."""

    artifacts = cast(ArtifactRepository, object())
    return parquet_results.LocalParquetRunResultReaderFactory(
        artifacts,
        semantic_cache_entries=entries,
    )


def _cache_reader(
    factory: parquet_results.LocalParquetRunResultReaderFactory,
    artifact_id: ArtifactId,
) -> parquet_results._LocalParquetRunResultReader:
    """Wire a bare reader to the production cache callbacks and single-flight lock."""

    reader = parquet_results._LocalParquetRunResultReader.__new__(
        parquet_results._LocalParquetRunResultReader
    )
    reader._balances_verified = False
    reader._roundtrips_verified = False
    # Factory-owned callbacks preserve the same LRU lifecycle as open_exact().
    reader._semantic_verified_probe = lambda: factory._is_semantically_verified(artifact_id)
    reader._roundtrip_page_index = None
    reader._roundtrip_page_index_probe = lambda: factory._roundtrip_page_index(artifact_id)
    reader._semantic_verified_callback = lambda page_index: factory._mark_semantically_verified(
        artifact_id, page_index
    )
    reader._semantic_verification_lock = factory._semantic_verification_lock_for(artifact_id)
    return reader


def test_semantic_cache_marks_only_after_both_complete_tables() -> None:
    factory = _factory()
    artifact_id = ArtifactId("1" * 64)
    reader = _cache_reader(factory, artifact_id)

    reader._balances_verified = True
    reader._mark_semantically_verified()
    assert not factory._is_semantically_verified(artifact_id)
    # A complete round-trip scan is the second half of the semantic token.
    reader._roundtrips_verified = True
    reader._mark_semantically_verified()
    assert factory._is_semantically_verified(artifact_id)


@pytest.mark.parametrize("failing_table", ["balances", "roundtrips"])
def test_corrupt_table_never_marks_semantic_cache(
    failing_table: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    artifact_id = ArtifactId("2" * 64)
    reader = _cache_reader(factory, artifact_id)

    def verify_balances() -> None:
        if failing_table == "balances":
            raise parquet_results.RunOutputIntegrityError("corrupt final balances")
        reader._balances_verified = True
        reader._mark_semantically_verified()

    def scan_roundtrips(*, after: object, limit: int) -> object:
        del after, limit
        raise parquet_results.RunOutputIntegrityError("corrupt round trips")

    monkeypatch.setattr(reader, "_verify_final_balances", verify_balances)
    monkeypatch.setattr(reader, "_scan_roundtrips", scan_roundtrips)
    with pytest.raises(parquet_results.RunOutputIntegrityError, match="corrupt"):
        reader.verify()
    # A partial local flag must never escape as reusable factory evidence.
    assert not factory._is_semantically_verified(artifact_id)


class _MemoryHandle:
    """Serve one immutable Parquet payload to the cached-page reader."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def open_binary(self, relative_name: str) -> IO[bytes]:
        assert relative_name == "roundtrips.parquet"
        return BytesIO(self._payload)


class _CachedPageManifest:
    """Expose only the manifest fields touched by cached page decoding."""

    bounded_summary = object.__new__(PumpfunSnipingSummaryMetadata)
    resolved_spec = SimpleNamespace(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    )

    def __init__(
        self,
        *,
        row_count: int = 1,
        canonical_digest: ContentDigest | None = None,
    ) -> None:
        digest = canonical_digest or ContentDigest("0" * 64)
        self._descriptor = SimpleNamespace(
            relative_name="roundtrips.parquet",
            schema_id=ROUNDTRIP_RESULT_SCHEMA_V4,
            row_count=row_count,
            # Digest is intentionally unused because the cached path reads one page only.
            canonical_digest=digest,
        )

    def result_table(self, role: RunResultTableRole) -> object:
        assert role is RunResultTableRole.ROUNDTRIPS
        return self._descriptor


def _invalid_roundtrip_parquet() -> bytes:
    """Encode a physical row whose canonical JSON violates the logical contract."""

    schema = pa.schema(
        [
            pa.field("target_boundary_ordinal", pa.uint64(), nullable=False),
            pa.field("roundtrip_id", pa.binary(32), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            # The payload is physical binary so strict logical decoding remains necessary.
            pa.field("record_json", pa.binary(), nullable=False),
        ],
        metadata={b"backtest.schema": ROUNDTRIP_RESULT_SCHEMA_V4.encode("ascii")},
    )
    table = pa.Table.from_pylist(
        [
            {
                "target_boundary_ordinal": 1,
                "roundtrip_id": b"\x00" * 32,
                "status": "CLOSED",
                "record_json": b"{}",
            }
        ],
        schema=schema,
    )
    # Buffer output keeps this corruption fixture hermetic and filesystem-free.
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def _indexed_roundtrip_parquet() -> bytes:
    """Encode six ordered rows into three independently readable row groups."""

    schema = pa.schema(
        [
            pa.field("target_boundary_ordinal", pa.uint64(), nullable=False),
            pa.field("roundtrip_id", pa.binary(32), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("record_json", pa.binary(), nullable=False),
        ],
        metadata={b"backtest.schema": ROUNDTRIP_RESULT_SCHEMA_V4.encode("ascii")},
    )
    rows = [
        {
            "target_boundary_ordinal": value,
            "roundtrip_id": value.to_bytes(32, "big"),
            "status": "CLOSED",
            "record_json": f'{{"row":{value}}}'.encode(),
        }
        for value in range(1, 7)
    ]
    sink = pa.BufferOutputStream()
    # Two rows per group make the expected late-page seek observable.
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), sink, row_group_size=2)
    return sink.getvalue().to_pybytes()


def test_cached_page_still_strictly_decodes_returned_rows() -> None:
    reader = parquet_results._LocalParquetRunResultReader.__new__(
        parquet_results._LocalParquetRunResultReader
    )
    reader._handle = cast(ArtifactHandle, _MemoryHandle(_invalid_roundtrip_parquet()))
    reader._manifest = cast(SuccessfulRunManifest, _CachedPageManifest())
    reader._balances_verified = True
    reader._roundtrips_verified = True
    # A cached semantic token skips the full hash scan, never row contract decoding.
    reader._semantic_verified_probe = None
    reader._roundtrip_page_index = None
    reader._roundtrip_page_index_probe = None
    reader._semantic_verified_callback = None
    reader._semantic_verification_lock = None
    # A cached token cannot legalize malformed JSON in a row returned to the caller.
    with pytest.raises(parquet_results.RunOutputIntegrityError, match="contract is invalid"):
        reader.roundtrips(after=None, limit=25)


def test_cached_late_page_starts_at_proven_row_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warm keyset continuation must not rescan earlier Parquet row groups."""

    payload = _indexed_roundtrip_parquet()
    reader = parquet_results._LocalParquetRunResultReader.__new__(
        parquet_results._LocalParquetRunResultReader
    )
    reader._handle = cast(ArtifactHandle, _MemoryHandle(payload))
    reader._manifest = cast(SuccessfulRunManifest, _CachedPageManifest(row_count=6))
    reader._balances_verified = True
    reader._roundtrips_verified = True
    # These checkpoints are normally created only by the complete semantic scan.
    reader._roundtrip_page_index = tuple(
        (group, (boundary, f"{boundary:064x}")) for group, boundary in ((0, 2), (1, 4), (2, 6))
    )
    reader._roundtrip_page_index_probe = None
    reader._semantic_verified_probe = None
    reader._semantic_verified_callback = None
    reader._semantic_verification_lock = None

    def decode(row: dict[str, object], *, schema_id: str) -> object:
        assert schema_id == ROUNDTRIP_RESULT_SCHEMA_V4
        boundary = cast(int, row["target_boundary_ordinal"])
        digest = ContentDigest(f"{boundary:064x}")
        record = SimpleNamespace(
            target_position=SimpleNamespace(boundary_ordinal=boundary),
            roundtrip_id=digest,
        )
        return cast(bytes, row["record_json"]), record, (boundary, digest.hex)

    monkeypatch.setattr(reader, "_decode_roundtrip_row", decode)
    real_parquet_file = pq.ParquetFile
    observed_groups: list[tuple[int, ...] | None] = []

    class RecordingParquetFile:
        """Delegate Arrow reads while exposing selected row-group ordinals."""

        def __init__(self, source: IO[bytes]) -> None:
            self._delegate = real_parquet_file(source)

        def __getattr__(self, name: str) -> object:
            return getattr(self._delegate, name)

        def iter_batches(self, **kwargs: object) -> object:
            groups = kwargs.get("row_groups")
            observed_groups.append(None if groups is None else tuple(cast(object, groups)))
            return self._delegate.iter_batches(**kwargs)

    monkeypatch.setattr(parquet_results.pq, "ParquetFile", RecordingParquetFile)
    cursor = RoundTripCursor(4, ContentDigest(f"{4:064x}"))
    page = reader.roundtrips(after=cursor, limit=1)

    assert observed_groups == [(2,)]
    assert [item.target_position.boundary_ordinal for item in page.items] == [5]
    assert page.next_cursor == RoundTripCursor(5, ContentDigest(f"{5:064x}"))


def test_complete_scan_publishes_sparse_row_group_seek_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a digest-checked full scan may publish cached row-group checkpoints."""

    encoded_rows = tuple(f'{{"row":{value}}}'.encode() for value in range(1, 7))
    hasher = CanonicalStreamHasher("backtest.sniping-roundtrip-stream.v4")
    for encoded in encoded_rows:
        hasher.append_canonical_bytes(encoded)

    reader = parquet_results._LocalParquetRunResultReader.__new__(
        parquet_results._LocalParquetRunResultReader
    )
    reader._handle = cast(ArtifactHandle, _MemoryHandle(_indexed_roundtrip_parquet()))
    reader._manifest = cast(
        SuccessfulRunManifest,
        _CachedPageManifest(row_count=6, canonical_digest=hasher.digest),
    )
    reader._balances_verified = True
    reader._roundtrips_verified = False
    reader._roundtrip_page_index = None
    reader._roundtrip_page_index_probe = None
    reader._semantic_verified_probe = None
    published: list[object] = []
    reader._semantic_verified_callback = published.append
    reader._semantic_verification_lock = None

    def decode(row: dict[str, object], *, schema_id: str) -> object:
        assert schema_id == ROUNDTRIP_RESULT_SCHEMA_V4
        boundary = cast(int, row["target_boundary_ordinal"])
        digest = ContentDigest(f"{boundary:064x}")
        record = SimpleNamespace(
            target_position=SimpleNamespace(boundary_ordinal=boundary),
            roundtrip_id=digest,
        )
        return cast(bytes, row["record_json"]), record, (boundary, digest.hex)

    monkeypatch.setattr(reader, "_decode_roundtrip_row", decode)
    reader._scan_roundtrips(after=None, limit=0)

    expected = tuple(
        (group, (boundary, f"{boundary:064x}")) for group, boundary in ((0, 2), (1, 4), (2, 6))
    )
    assert published == [expected]
    assert reader._roundtrip_page_index == expected


def test_lru_eviction_forces_full_semantic_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory(entries=1)
    evicted_id = ArtifactId("3" * 64)
    factory._mark_semantically_verified(evicted_id)
    factory._mark_semantically_verified(ArtifactId("4" * 64))
    reader = _cache_reader(factory, evicted_id)
    scans: list[str] = []

    def verify_balances() -> None:
        scans.append("balances")
        reader._balances_verified = True
        reader._mark_semantically_verified()

    def scan_roundtrips(*, after: object, limit: int) -> object:
        del after, limit
        scans.append("roundtrips")
        reader._roundtrips_verified = True
        reader._mark_semantically_verified()
        return object()

    monkeypatch.setattr(reader, "_verify_final_balances", verify_balances)
    monkeypatch.setattr(reader, "_scan_roundtrips", scan_roundtrips)
    reader.verify()
    # Reopening an evicted ID must pay both semantic scans again.
    assert scans == ["balances", "roundtrips"]
    assert factory._is_semantically_verified(evicted_id)


def test_concurrent_cold_requests_share_one_full_semantic_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    artifact_id = ArtifactId("5" * 64)
    readers = [_cache_reader(factory, artifact_id) for _ in range(2)]
    scan_started = Event()
    release_scan = Event()
    counter_lock = Lock()
    scan_count = 0

    def install_full_scan(reader: parquet_results._LocalParquetRunResultReader) -> None:
        def full_scan() -> None:
            nonlocal scan_count
            with counter_lock:
                scan_count += 1
            scan_started.set()
            assert release_scan.wait(timeout=2)
            # Publish the token only after both simulated table scans complete.
            reader._balances_verified = True
            reader._roundtrips_verified = True
            reader._mark_semantically_verified()

        monkeypatch.setattr(reader, "_verify_all", full_scan)

    for reader in readers:
        install_full_scan(reader)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(readers[0].verify)
        assert scan_started.wait(timeout=2)
        second = pool.submit(readers[1].verify)
        # The waiting request observes the published token after the first scan exits.
        release_scan.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert scan_count == 1
    assert factory._is_semantically_verified(artifact_id)


def test_distinct_lock_stripes_verify_cold_artifacts_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    artifact_ids = (ArtifactId("0" * 63 + "6"), ArtifactId("0" * 63 + "7"))
    readers = [_cache_reader(factory, artifact_id) for artifact_id in artifact_ids]
    started = (Event(), Event())
    release_scans = Event()

    # Protect this test from an accidental fixture collision in the stable stripe function.
    first_lock = factory._semantic_verification_lock_for(artifact_ids[0])
    second_lock = factory._semantic_verification_lock_for(artifact_ids[1])
    assert first_lock is not second_lock

    def install_full_scan(
        reader: parquet_results._LocalParquetRunResultReader,
        started_event: Event,
    ) -> None:
        def full_scan() -> None:
            started_event.set()
            assert release_scans.wait(timeout=2)
            # Each ID publishes only its own completed semantic evidence.
            reader._balances_verified = True
            reader._roundtrips_verified = True
            reader._mark_semantically_verified()

        monkeypatch.setattr(reader, "_verify_all", full_scan)

    for reader, started_event in zip(readers, started, strict=True):
        install_full_scan(reader, started_event)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(reader.verify) for reader in readers)
        assert all(event.wait(timeout=2) for event in started)
        # Neither cold scan may wait for the unrelated stripe to release.
        release_scans.set()
        for future in futures:
            future.result(timeout=2)

    assert all(factory._is_semantically_verified(item) for item in artifact_ids)
