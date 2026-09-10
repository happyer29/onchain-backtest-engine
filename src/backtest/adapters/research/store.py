"""Atomic local research publication with bounded DuckDB work and Parquet reads."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

# Temporary workspaces are same-filesystem disposable state, never committed authority.
from tempfile import TemporaryDirectory

# Native analytical libraries are confined to adapters and bounded batches.
from threading import Timer
from typing import Any, cast

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

# The existing repository owns publication locks, hashes, fsync and read leases.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.research import queries
from backtest.adapters.research.layout import (
    BATCH_ROWS,
    OBSERVATION_COLUMNS,
    # Fixed layout helpers give every committed table one schema and canonical row digest.
    OBSERVATION_ORDER,
    TableDigest,
    bounded_rows,
    observation_batch,
    raw_schema,
    # No caller supplies a physical file name or arbitrary native schema.
    table_schema,
)

# Research kinds remain structurally separate from canonical replay snapshots.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.ports.artifacts import ArtifactHandle, ArtifactWriter

# Strict command parsers are reused for persisted manifests and dependency checks.
from backtest.application.research import (
    MAX_PAIR_CANDIDATES,
    MAX_SIGNERS_PER_MINT,
    MAX_SOURCE_ROWS,
    RESULT_SCHEMA,
    # Snapshot/result schemas are versioned independently of canonical replay data.
    SNAPSHOT_SCHEMA,
    ResearchDatasetSpec,
    ResearchError,
    ResearchTable,
    WalletAnalysisSpec,
    # The same strict parsers validate both queued commands and stored manifest operands.
    WalletObservation,
    analysis_spec,
    dataset_spec,
    integer,
)

# Semantic hashing excludes operational paths, query IDs and source credentials.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ArtifactId, ContentDigest

# These source-quality claims are fixed and are never upgraded by local validation.
QUALITY = {
    "completeness": "UNKNOWN",
    "finality": "UNKNOWN",
    "consistency": "UNKNOWN",
    "causal_availability": "UNKNOWN",
    # A content hash cannot turn multiplicity-preserving observations into exact event IDs.
    "identity": "SOURCE_OBSERVATIONS_WITH_MULTIPLICITY",
    # Validation proves the observations, not market-wide coverage or wallet ownership.
    "ordering": "SOURCE_REPORTED_POSITIONS",
    "ownership": "NOT_INFERRED",
}
# Closed metadata fields keep manifests bounded and reject silent schema extensions.
_COUNTS = {"source_rows", "selected_rows", "wallets", "pairs", "evidence"}
_SNAPSHOT_KEYS = {"schema", "dataset", "source_schema_digest", "quality", "counts", "tables"}
_RESULT_KEYS = {"schema", "dataset", "analysis", "quality", "counts", "tables"}


class LocalResearchStore:
    """One bounded writer/query implementation over authoritative local artifacts."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        memory_mb: int = 512,
        # Temporary spill and authoritative output have independent hard byte limits.
        temporary_bytes: int = 1024**3,
        output_bytes: int = 1024**3,
        threads: int = 1,
        maximum_source_rows: int = MAX_SOURCE_ROWS,
        # Candidate fanout is bounded before the pair self-join, not after truncation.
        maximum_pair_candidates: int = MAX_PAIR_CANDIDATES,
    ) -> None:
        """Physical bounds may reject work, but never alter a successful result."""

        self.artifacts = artifacts
        self.memory_mb = integer(memory_mb, minimum=32, maximum=8_192)
        self.temporary_bytes = integer(temporary_bytes, minimum=1_024)
        self.output_bytes = integer(output_bytes, minimum=1_024)
        # Each native engine receives an explicit budget inside the admitted child.
        self.threads = integer(threads, minimum=1, maximum=8)
        self.maximum_source_rows = integer(maximum_source_rows, minimum=1, maximum=MAX_SOURCE_ROWS)
        self.maximum_pair_candidates = integer(
            maximum_pair_candidates, minimum=1, maximum=MAX_PAIR_CANDIDATES
        )

    # Every native connection and its interrupt timer share one explicit lifetime.
    @contextmanager
    def _workspace(self) -> Iterator[tuple[Path, Any]]:
        """Bound sort/join spill on the same filesystem and always close native state."""

        with TemporaryDirectory(prefix="research-", dir=self.artifacts.staging_root) as temporary:
            root = Path(temporary)
            connection = duckdb.connect()
            timer = Timer(120, connection.interrupt)
            # A native timeout cannot publish partial tables; the surrounding writer aborts.
            try:
                connection.execute(f"SET memory_limit='{self.memory_mb}MB'")
                connection.execute(f"SET threads={self.threads}")
                connection.execute("SET temp_directory=?", [str(root / "spill")])
                connection.execute(f"SET max_temp_directory_size='{self.temporary_bytes // 3}B'")
                # Only bundled built-in functions over trusted local paths are used.
                connection.execute("SET autoinstall_known_extensions=false")
                connection.execute("SET autoload_known_extensions=false")
                timer.start()
                yield root, connection
            # Resource failures are finite errors and can never return partial successful rows.
            except duckdb.OutOfMemoryException:
                raise ResearchError("RESEARCH_MEMORY_LIMIT") from None
            except duckdb.InterruptException:
                # Native interrupts abort the surrounding writer; no partial table is a result.
                raise ResearchError("RESEARCH_QUERY_TIMEOUT") from None
            finally:
                timer.cancel()
                # An in-flight interrupt must finish before the native connection closes.
                if timer.ident is not None:
                    timer.join()
                connection.close()

    # Only fully consumed and validated source streams are eligible for publication.
    def publish_snapshot(
        self,
        spec: ResearchDatasetSpec,
        schema_digest: ContentDigest,
        batches: Iterator[tuple[WalletObservation, ...]],
        # Batch arrival order affects neither canonical ordering nor logical content identity.
    ) -> CommittedArtifact:
        """Sort complete observations, then publish through the existing commit protocol."""

        with self._workspace() as (root, connection):
            raw = root / "raw.parquet"
            self._spool(raw, spec, batches)
            connection.read_parquet(str(raw)).create_view("source_rows")
            # Canonical row groups and order are independent of remote batch boundaries.
            sql = f"SELECT row_number() OVER (ORDER BY {OBSERVATION_ORDER})-1 row_id, "
            sql += f"* FROM source_rows ORDER BY {OBSERVATION_ORDER}"
            sorted_path = root / "observations.parquet"
            # Write a complete deterministic spool before obtaining publication authority.
            with sorted_path.open("xb") as stream:
                table = self._write_query(
                    connection,
                    sql,
                    ResearchTable.OBSERVATIONS,
                    # Raw input, sorted spool and native spill each consume at most one third.
                    stream,
                    maximum_bytes=self.temporary_bytes // 3,
                )
            # A fresh mutable-source scan is keyed by its actual observed content.
            wallets_query = "SELECT count(DISTINCT signing_wallet) FROM source_rows"
            wallets = int(connection.execute(wallets_query).fetchone()[0])
            counts = _counts(table["rows"], table["rows"], wallets)
            # Source observations and quality claims are explicit, bounded manifest operands.
            manifest: dict[str, object] = {
                "schema": SNAPSHOT_SCHEMA,
                "dataset": spec.document(),
                "source_schema_digest": schema_digest.hex,
                "quality": QUALITY,
                # Logical table digests bind counts to actual rows without embedding those rows.
                "counts": counts,
                "tables": {"observations": table},
            }
            build_key = domain_digest(SNAPSHOT_SCHEMA, manifest)
            return self._publish_spooled(build_key, manifest, sorted_path)

    # Source spool IO is separate from the authoritative repository publication protocol.
    def _spool(
        self,
        path: Path,
        spec: ResearchDatasetSpec,
        # Iterators may fail mid-stream; the temporary workspace then disappears without a root.
        batches: Iterator[tuple[WalletObservation, ...]],
    ) -> None:
        """Bound the local source spool independently of SDK/server enforcement."""

        count = 0
        with (
            path.open("xb") as stream,
            pq.ParquetWriter(stream, raw_schema(), compression="zstd") as writer,
        ):
            # Check driver batch width as well as cumulative row cardinality.
            for rows in batches:
                count += len(rows)
                if count > self.maximum_source_rows or len(rows) > 65_536:
                    raise ResearchError("RESEARCH_SOURCE_ROW_LIMIT")
                # Trusted and live ports both obey the same application range contract.
                if any(not spec.block_range.contains_block(row.block_ordinal) for row in rows):
                    raise ResearchError("RESEARCH_SOURCE_RANGE_MISMATCH")
                if rows:
                    writer.write_batch(observation_batch(rows))
                _require_bytes(stream.tell(), self.temporary_bytes // 3)
        # The Parquet footer also consumes space and must fit the same temporary quota.
        _require_bytes(path.stat().st_size, self.temporary_bytes // 3)

    def _publish_spooled(
        self, build_key: ContentDigest, manifest: dict[str, object], path: Path
    ) -> CommittedArtifact:
        """Only a complete validated spool may enter authoritative publication."""

        writer = self.artifacts.stage(ArtifactDraft(ArtifactKind.RESEARCH_SNAPSHOT, build_key))
        try:
            # Copy in bounded blocks; the shared repository retains lock/fsync/commit authority.
            with writer.open_binary("observations.parquet") as output, path.open("rb") as source:
                while block := source.read(1024**2):
                    output.write(block)
                    _require_bytes(output.tell(), self.output_bytes)
            # The repository owns all fsync, hash, collision, rename and marker semantics.
            return writer.commit(canonical_json_bytes(manifest))
        except BaseException:
            writer.abort()
            raise

    def analyze(self, spec: WalletAnalysisSpec) -> CommittedArtifact:
        """Acquire writer authority before the retained input to preserve lock order."""

        draft = ArtifactDraft(ArtifactKind.RESEARCH_RESULT, spec.build_key, (spec.snapshot_id,))
        writer = self.artifacts.stage(draft)
        try:
            # Writer-before-reader lock acquisition matches the global publication order.
            with ExitStack() as stack:
                handle = self.artifacts.open_committed(spec.snapshot_id)
                stack.callback(handle.close)
                manifest = self._manifest(handle, expected=ArtifactKind.RESEARCH_SNAPSHOT)
                # The input lease outlives native readers and final reference publication.
                stream = stack.enter_context(handle.open_binary("observations.parquet"))
                input_file = pq.ParquetFile(stream)
                self._validate_input(input_file, manifest)
                # Validation finishes before DuckDB can interpret the observation stream.
                _, connection = stack.enter_context(self._workspace())
                result = self._calculate(connection, input_file, spec, manifest, writer)
                return writer.commit(canonical_json_bytes(result))
        # Any exception leaves only an aborted staging attempt, never a successful marker.
        except BaseException:
            writer.abort()
            raise

    def _validate_input(self, file: pq.ParquetFile, manifest: dict[str, Any]) -> None:
        """Revalidate observed rows and their logical digest before native aggregation."""

        self._validate_table(file, ResearchTable.OBSERVATIONS, manifest)
        spec = dataset_spec(manifest["dataset"])
        digest = TableDigest(ResearchTable.OBSERVATIONS)
        previous: tuple[int | str, ...] | None = None
        # This is a bounded offline validation scan, never an engine hot-loop path.
        for batch in file.iter_batches(batch_size=BATCH_ROWS):
            digest.update(batch)
            for raw in batch.to_pylist():
                row = WalletObservation(**{name: raw[name] for name in OBSERVATION_COLUMNS})
                values = row.values()
                # A corrupt order/range cannot masquerade as the first observed purchase.
                if not spec.block_range.contains_block(row.block_ordinal) or (
                    previous is not None and values < previous
                ):
                    # The first-buy recipe must not operate on reordered or out-of-range inputs.
                    raise ResearchError("RESEARCH_SOURCE_RANGE_OR_ORDER_MISMATCH")
                previous = values
        expected = manifest["tables"]["observations"]
        # Verify the complete logical row stream, independently of physical Parquet hashes.
        if digest.count != expected["rows"] or digest.hex != expected["digest"]:
            raise ResearchError("RESEARCH_TABLE_DIGEST_MISMATCH")

    # This fixed native recipe is an offline application worker, never replay hot-loop code.
    def _calculate(
        self,
        connection: Any,
        file: pq.ParquetFile,
        spec: WalletAnalysisSpec,
        # Input metadata and output authority remain distinct from the native query connection.
        snapshot: dict[str, Any],
        writer: ArtifactWriter,
    ) -> dict[str, object]:
        """Run the fixed recipe and publish complete activity/pair/evidence tables."""

        reader = pa.RecordBatchReader.from_batches(file.schema_arrow, file.iter_batches(BATCH_ROWS))
        connection.register("input_rows", reader)
        connection.execute("CREATE TEMP TABLE observations AS SELECT * FROM input_rows")
        connection.unregister("input_rows")
        # Signer selection is a bound value list, not interpolated SQL or an arbitrary join.
        if spec.wallets:
            connection.execute(
                "CREATE TEMP TABLE selected AS SELECT * FROM observations "
                "WHERE signing_wallet IN (SELECT unnest(?))",
                # Wallets are bound values; they cannot change the fixed query structure.
                [list(spec.wallets)],
            )
        # An omitted selection includes all rows; it is not a hidden top-wallet sample.
        else:
            connection.execute("CREATE TEMP VIEW selected AS SELECT * FROM observations")
        # Dense popular-token joins are rejected before any quadratic materialization.
        connection.execute(queries.FIRST_BUYS)
        maximum_signers, candidates = connection.execute(queries.CANDIDATE_BUDGET).fetchone()
        if maximum_signers > MAX_SIGNERS_PER_MINT or candidates > self.maximum_pair_candidates:
            raise ResearchError("RESEARCH_PAIR_CANDIDATE_LIMIT")
        # Only an admitted complete candidate set may reach the potentially quadratic join.
        connection.execute(queries.CANDIDATES, [spec.window_seconds])
        connection.execute(queries.PAIRS, [spec.minimum_shared_mints])
        # All global counters are calculated from the complete selected observations.
        selected_rows = int(connection.execute("SELECT count(*) FROM selected").fetchone()[0])
        table_queries = {
            # Every persisted result table is produced by one reviewed fixed statement.
            ResearchTable.ACTIVITY: queries.ACTIVITY,
            ResearchTable.PAIRS: "SELECT * FROM pairs ORDER BY row_id",
            ResearchTable.EVIDENCE: queries.EVIDENCE,
        }
        # One output budget is shared across all three result tables.
        tables: dict[str, object] = {}
        written = 0
        # Fixed-size Parquet row groups keep later HTTP reads bounded and SQL-free.
        for role, query in table_queries.items():
            with writer.open_binary(role.value + ".parquet") as stream:
                tables[role.value] = self._write_query(
                    # The remaining shared output budget shrinks after each completed table.
                    connection,
                    query,
                    role,
                    stream,
                    # All result tables consume one shared quota, not a quota per table.
                    maximum_bytes=self.output_bytes - written,
                )
                written += stream.tell()
        # Typed descriptors summarize complete tables and drive manifest/evidence reconciliation.
        activity, pairs, evidence = (
            cast(dict[str, Any], tables[role]) for role in ("activity", "pairs", "evidence")
        )
        # Reconcile evidence cardinality against full pair counts before root publication.
        expected = int(
            connection.execute("SELECT coalesce(sum(shared_mints),0) FROM pairs").fetchone()[0]
        )
        if expected != evidence["rows"]:
            raise ResearchError("RESEARCH_EVIDENCE_MISMATCH")
        # Global counters are independent of which page or graph view a client later opens.
        counts = _counts(
            snapshot["counts"]["source_rows"],
            selected_rows,
            activity["rows"],
            pairs["rows"],
            # Evidence cardinality is a count of pair-mint observations, not unique market mints.
            evidence["rows"],
        )
        return {
            "schema": RESULT_SCHEMA,
            # The selected input identity and canonical recipe explain every derived row.
            "dataset": snapshot["dataset"],
            "analysis": spec.document(),
            # A successful calculation does not upgrade its input's source fidelity.
            "quality": QUALITY,
            "counts": counts,
            "tables": tables,
        }

    # Canonical batch boundaries stabilize Parquet bytes independently of source arrival order.
    def _write_query(
        self, connection: Any, query: str, role: ResearchTable, stream: Any, *, maximum_bytes: int
    ) -> dict[str, object]:
        """Write canonical batches with checked schema and logical row digests."""

        schema = table_schema(role)
        digest = TableDigest(role)
        reader = connection.execute(query).to_arrow_reader(BATCH_ROWS)
        with pq.ParquetWriter(stream, schema, compression="zstd", version="2.6") as writer:
            # Safe Arrow casts reject overflow rather than narrowing native aggregates.
            for batch in reader:
                canonical = batch.cast(schema, safe=True)
                digest.update(canonical)
                writer.write_batch(canonical, row_group_size=BATCH_ROWS)
                _require_bytes(stream.tell(), maximum_bytes)
        # Include the final Parquet footer in the output quota before committing a descriptor.
        _require_bytes(stream.tell(), maximum_bytes)
        return {"rows": digest.count, "digest": digest.hex}

    def summary(self, artifact_id: ArtifactId) -> dict[str, object]:
        """Authenticate bounded manifests and file descriptors without analytical SQL."""

        handle = self.artifacts.open_committed(artifact_id)
        try:
            manifest = self._manifest(handle)
            # Even metadata reads check that every declared columnar table is present and shaped.
            for name in manifest["tables"]:
                with handle.open_binary(name + ".parquet") as stream:
                    self._validate_table(pq.ParquetFile(stream), ResearchTable(name), manifest)
            # Only bounded semantic metadata leaves the adapter; paths remain private.
            return {
                "artifact_id": artifact_id.hex,
                "kind": handle.descriptor.kind.value,
                # Only already validated bounded metadata is returned; no file paths or raw rows.
                **manifest,
            }
        finally:
            handle.close()

    # Rows are read through verified handles, never by constructing a path from caller text.
    def page(
        self,
        artifact_id: ArtifactId,
        table: ResearchTable,
        # Transport pagination is a location within this immutable table, not an SQL query.
        *,
        after: int,
        limit: int,
        # Evidence must be scoped to one pair; other tables reject this parameter.
        pair: int | None = None,
    ) -> tuple[dict[str, str], ...]:
        """Read one immutable keyset page and optionally its exact source evidence."""

        with ExitStack() as stack:
            handle = self.artifacts.open_committed(artifact_id)
            stack.callback(handle.close)
            manifest = self._manifest(handle)
            if table.value not in manifest["tables"]:
                # A snapshot cannot expose pair tables, and a result cannot masquerade as raw input.
                raise ResearchError("RESEARCH_TABLE_UNAVAILABLE")
            # Evidence uses a verified contiguous pair range, not a whole-table scan.
            start, count = after + 1, limit
            pair_row = None
            if table is ResearchTable.EVIDENCE:
                # Pair range lookup must finish before the evidence reader opens its first group.
                start, count, pair_row = self._evidence_range(handle, manifest, pair, start, count)
            elif pair is not None:
                raise ResearchError("RESEARCH_INVALID_PAIR_SCOPE")
            # File roles are fixed constants and are opened only after manifest verification.
            stream = stack.enter_context(handle.open_binary(table.value + ".parquet"))
            file = pq.ParquetFile(stream)
            self._validate_table(file, table, manifest)
            rows = tuple(bounded_rows(file, table, start, count))
            # Drilldown shows the observations that support each shared-mint edge.
            if table is ResearchTable.EVIDENCE:
                assert pair_row is not None
                return self._evidence_observations(manifest, rows, pair_row)
            return rows

    # Evidence pages use a bounded pair lookup rather than scanning unrelated pair ranges.
    def _evidence_range(
        self,
        handle: ArtifactHandle,
        manifest: dict[str, Any],
        pair: int | None,
        # The validated pair descriptor supplies the actual start/end offsets.
        start: int,
        count: int,
    ) -> tuple[int, int, dict[str, str]]:
        """Every evidence page is bound to one exact pair row in this result."""

        if pair is None:
            raise ResearchError("RESEARCH_PAIR_REQUIRED")
        with handle.open_binary("pairs.parquet") as stream:
            # Opening by manifest-relative role retains the result lease through this lookup.
            file = pq.ParquetFile(stream)
            self._validate_table(file, ResearchTable.PAIRS, manifest)
            pairs = tuple(bounded_rows(file, ResearchTable.PAIRS, pair, 1))
        # Out-of-range pair references cannot become an empty successful drilldown.
        if not pairs:
            raise ResearchError("RESEARCH_PAIR_UNAVAILABLE")
        first = int(pairs[0]["evidence_start"])
        end = first + int(pairs[0]["evidence_count"])
        # A pair's entire declared evidence range must fit the complete result table.
        if end > manifest["counts"]["evidence"]:
            raise ResearchError("RESEARCH_EVIDENCE_MISMATCH")
        # The initial sentinel starts at the pair range; later cursors stay inside it.
        start = first if start == 0 else start
        if not first <= start <= end:
            raise ResearchError("RESEARCH_INVALID_PAIR_SCOPE")
        return start, min(count, end - start), pairs[0]

    # Drilldown verifies both retained source observations before presenting a relationship.
    def _evidence_observations(
        self, manifest: dict[str, Any], rows: tuple[dict[str, str], ...], pair: dict[str, str]
    ) -> tuple[dict[str, str], ...]:
        """Reopen the exact retained snapshot and resolve only selected row ordinals."""

        spec = analysis_spec(manifest["analysis"])
        handle = self.artifacts.open_committed(spec.snapshot_id)
        try:
            source = self._manifest(handle, expected=ArtifactKind.RESEARCH_SNAPSHOT)
            # Evidence is meaningful only under the same exact source specification.
            if source["dataset"] != manifest["dataset"]:
                raise ResearchError("RESEARCH_INPUT_MISMATCH")
            # Interpret row pointers only after authenticating the exact input dataset.
            with handle.open_binary("observations.parquet") as stream:
                # Source schema/count bounds apply before any row group is decompressed.
                file = pq.ParquetFile(stream)
                self._validate_table(file, ResearchTable.OBSERVATIONS, source)
                # Each loaded observation is validated against its evidence mint/role.
                for row in rows:
                    if row["pair_row_id"] != pair["row_id"]:
                        raise ResearchError("RESEARCH_EVIDENCE_MISMATCH")
                    for side, field in (
                        ("left", "left_observation"),
                        # Both sides are checked independently even for same-transaction trades.
                        ("right", "right_observation"),
                    ):
                        observed = tuple(
                            bounded_rows(file, ResearchTable.OBSERVATIONS, int(row[field]), 1)
                        )
                        # Every supporting row must describe a BUY of exactly this evidence mint.
                        if (
                            not observed
                            or observed[0]["mint"] != row["mint"]
                            or observed[0]["side"] != "BUY"
                            # Shared-mint evidence never points to a sale or an unrelated asset.
                        ):
                            raise ResearchError("RESEARCH_EVIDENCE_MISMATCH")
                        # Preserve all original source fields with explicit left/right prefixes.
                        row.update({side + "_" + key: value for key, value in observed[0].items()})
                    # Reconcile the displayed pair and time relation with both source rows.
                    actual_delta = int(row["right_block_time_s"]) - int(row["left_block_time_s"])
                    if (
                        row["left_signing_wallet"] != pair["signer_a"]
                        or row["right_signing_wallet"] != pair["signer_b"]
                        or actual_delta != int(row["delta_seconds"])
                        # Inclusive window equality is part of the committed recipe contract.
                        or abs(actual_delta) > spec.window_seconds
                    ):
                        raise ResearchError("RESEARCH_EVIDENCE_MISMATCH")
            return rows
        finally:
            # The source lease covers all evidence reads, including exceptional exits.
            handle.close()

    # The manifest is a closed versioned contract, not an arbitrary JSON metadata bag.
    def _manifest(
        self, handle: ArtifactHandle, *, expected: ArtifactKind | None = None
    ) -> dict[str, Any]:
        """Strict kind/schema/dependency validation precedes all research file access."""

        kind = handle.descriptor.kind
        if kind not in {ArtifactKind.RESEARCH_SNAPSHOT, ArtifactKind.RESEARCH_RESULT} or (
            expected is not None and kind is not expected
        ):
            raise ResearchError("RESEARCH_WRONG_ARTIFACT_KIND")
        # Verify a bounded canonical manifest before interpreting any table descriptor.
        with handle.open_binary("manifest.json") as stream:
            raw = stream.read(1024**2 + 1)
        _require_bytes(len(raw), 1024**2)
        manifest = json.loads(raw)
        # Canonical bytes and closed fields prevent opaque schemas entering query views.
        snapshot = kind is ArtifactKind.RESEARCH_SNAPSHOT
        keys = _SNAPSHOT_KEYS if snapshot else _RESULT_KEYS
        # Canonical bytes reject duplicate keys, alternate encodings and unexpected fields.
        if (
            not isinstance(manifest, dict)
            or set(manifest) != keys
            or canonical_json_bytes(manifest) != raw
        ):
            # An authenticated file hash does not excuse a noncanonical semantic envelope.
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        schema = SNAPSHOT_SCHEMA if snapshot else RESULT_SCHEMA
        # Quality claims are fixed by this observational profile and cannot be caller-upgraded.
        if manifest["schema"] != schema or manifest["quality"] != QUALITY:
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        # A stored research dataset remains a typed observational request.
        if dataset_spec(manifest["dataset"]).document() != manifest["dataset"]:
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        counts = manifest["counts"]
        tables = manifest["tables"]
        # Both count and table maps are closed; unknown keys are not silently ignored.
        if not isinstance(counts, dict) or set(counts) != _COUNTS or not isinstance(tables, dict):
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        # Count bounds make even maliciously large manifests unable to allocate row arrays.
        for value in counts.values():
            integer(value, maximum=MAX_SOURCE_ROWS)
        if (
            counts["wallets"] > counts["selected_rows"]
            # Counters cannot claim observations or participants absent from the source rows.
            or counts["selected_rows"] > counts["source_rows"]
        ):
            # A selected universe cannot contain more wallets or rows than the source scan.
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        expected_tables = {"observations"} if snapshot else {"activity", "pairs", "evidence"}
        if set(tables) != expected_tables:
            raise ResearchError("RESEARCH_INVALID_MANIFEST")
        # Descriptor counts and exact table digests are mandatory bounded metadata.
        count_fields = {
            "observations": "source_rows",
            "activity": "wallets",
            "pairs": "pairs",
            # Evidence counts include every retained pair-mint relation after threshold filtering.
            "evidence": "evidence",
        }
        for role, descriptor in tables.items():
            # Per-table counts and logical hashes must agree with the bounded summary.
            if not isinstance(descriptor, dict) or set(descriptor) != {"rows", "digest"}:
                raise ResearchError("RESEARCH_INVALID_MANIFEST")
            if descriptor["rows"] != counts[count_fields[role]]:
                raise ResearchError("RESEARCH_INVALID_MANIFEST")
            integer(descriptor["rows"], maximum=MAX_SOURCE_ROWS)
            # The content digest remains distinct from the row ordinal used for local navigation.
            ContentDigest(descriptor["digest"])
        # Snapshot roots have no implicit live or execution dependencies.
        if snapshot:
            ContentDigest(manifest["source_schema_digest"])
            if (
                handle.descriptor.build_key != domain_digest(SNAPSHOT_SCHEMA, manifest)
                or counts["selected_rows"] != counts["source_rows"]
                # Snapshot creation has no signer-selection phase or hidden row filter.
            ):
                # A fresh acquisition build key binds the observed logical data and schema.
                raise ResearchError("RESEARCH_INPUT_MISMATCH")
            if handle.descriptor.input_artifact_ids or counts["pairs"] or counts["evidence"]:
                raise ResearchError("RESEARCH_INPUT_MISMATCH")
        else:
            # Derived results retain exactly one source snapshot and the complete recipe identity.
            spec = analysis_spec(manifest["analysis"])
            if spec.document() != manifest["analysis"]:
                raise ResearchError("RESEARCH_INVALID_MANIFEST")
            if handle.descriptor.input_artifact_ids != (spec.snapshot_id,):
                raise ResearchError("RESEARCH_INPUT_MISMATCH")
            # A descriptor cannot relabel one recipe's output as another build.
            if handle.descriptor.build_key != spec.build_key:
                raise ResearchError("RESEARCH_INPUT_MISMATCH")
        return cast(dict[str, Any], manifest)

    # Footer validation runs before row-group reads on every public query path.
    def _validate_table(
        self, file: pq.ParquetFile, role: ResearchTable, manifest: dict[str, Any]
    ) -> None:
        """Check trusted footer descriptors before reading even one result row."""

        if file.schema_arrow != table_schema(role):
            raise ResearchError("RESEARCH_INVALID_TABLE")
        if file.metadata.num_rows != manifest["tables"][role.value]["rows"]:
            raise ResearchError("RESEARCH_TABLE_COUNT_MISMATCH")
        # Reject oversized row groups before decompression or source-string allocation.
        for index in range(file.metadata.num_row_groups):
            group = file.metadata.row_group(index)
            if group.num_rows > BATCH_ROWS or group.total_byte_size > BATCH_ROWS * 2048:
                raise ResearchError("RESEARCH_ROW_GROUP_LIMIT")


# Bounded scalar metadata avoids embedding an unbounded row list in an artifact manifest.
def _counts(
    source: Any, selected: Any, wallets: Any, pairs: Any = 0, evidence: Any = 0
) -> dict[str, int]:
    """Use exact bounded counters, including genuine zero-observation results."""

    return {
        "source_rows": integer(source),
        "selected_rows": integer(selected),
        "wallets": integer(wallets),
        # Pair and evidence counts summarize the complete filtered relation.
        "pairs": integer(pairs),
        "evidence": integer(evidence),
    }


def _require_bytes(actual: int, maximum: int) -> None:
    """A quota failure aborts publication rather than emitting a partial artifact."""

    if actual > maximum:
        raise ResearchError("RESEARCH_BYTE_LIMIT")
