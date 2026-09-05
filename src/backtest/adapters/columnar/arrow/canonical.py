"""Bounded canonical Parquet v3 materialization with external sorting and QA."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile

# Import abc at the visible module dependency boundary.
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Protocol, cast

# Import duckdb at the visible module dependency boundary.
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.build_tool_roles import CANONICAL_WRITER_ROLE

# Import canonical data at the visible module dependency boundary.
from backtest.application.canonical_data import (
    CanonicalDistributionRef,
    EffectiveSourceBoundary,
    PreparedSnapshot,
    ProjectedEventBatch,
    # Include source boundary so the canonical data dependency remains explicit.
    SourceBoundary,
    ValidationStatus,
    canonical_distribution_source_contract,
    covering_cut_evidence,
    immutable_reuse_evidence,
    # Close the canonical data import after its required symbols are visible.
)
from backtest.application.code_bundles import PinnedCodeBundleIdentity, PinnedCodeBundleSet
from backtest.application.dataset_plans import dataset_spec_document
from backtest.application.errors import (
    ReprepareRequiredError,
    # Include snapshot validation error so the errors dependency remains explicit.
    SnapshotValidationError,
    SnapshotValidationErrorCode,
)
from backtest.application.models import (
    ArtifactDraft,
    # Include artifact kind so the models dependency remains explicit.
    ArtifactKind,
    DatasetPlan,
    DatasetShard,
    PlannedCapability,
)

# Import canonical at the visible module dependency boundary.
from backtest.application.ports.canonical import CanonicalSnapshotValidator
from backtest.domain.chain import ChainIdentityMismatchError, ChainPosition
from backtest.domain.event_hashing import canonical_event_digest
from backtest.domain.fidelity import SourceFidelity
from backtest.domain.hashing import canonical_json_bytes, domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    SnapshotId,
)
from backtest.domain.market_events import (
    BlockEvent,
    # Include canonical event so the market events dependency remains explicit.
    CanonicalEvent,
    EventKind,
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueTradeEvent,
    # Close the market events import after its required symbols are visible.
)
from backtest.domain.time import BlockRange
from backtest.engine.transaction_clock import TransactionClockError

_CANONICAL_SCHEMA_VERSION = 3
_DISTRIBUTION_ARTIFACT_SCHEMA = "canonical-distribution/v5"
# Bind snapshot artifact schema once as an explicit module-level contract.
_SNAPSHOT_ARTIFACT_SCHEMA = "canonical-snapshot/v4"
_UNIT_WRITER_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.canonical-writer-unit-default.v6",
        {
            # Keep authority named so the v6 and authority payload passed to domain_digest
            # remains self-describing within module.
            "authority": "isolated-unit-default-only",
            "compression": "zstd",
            "integer_encoding": "signed-int128-big-endian",
            "position": "block32-transaction32-v1",
            "protocol_payload": "exact-binary",
            "row_group_rows": 8_192,
            # Keep source fidelity manifest named so the v6 and authority payload passed
            # to domain_digest remains self-describing within module.
            "source_fidelity_manifest": "effective-source-boundary-v2",
        },
    ).hex
)


def _unit_writer_tools() -> PinnedCodeBundleSet:
    # Execute the unit writer tools workflow in explicit, reviewable steps.
    return PinnedCodeBundleSet(
        (PinnedCodeBundleIdentity.for_unit_tests(CANONICAL_WRITER_ROLE, _UNIT_WRITER_BUNDLE_ID),)
    )


# Keep the local handle contract and validation rules together.
class _LocalHandle(Protocol):
    @property
    def descriptor(self) -> Any: ...

    def local_path(self, relative_name: str) -> Path: ...

    def open_binary(self, relative_name: str) -> IO[bytes]: ...

    # Define local handle close as one focused operation with an explicit boundary.
    def close(self) -> None: ...


class CanonicalDataError(RuntimeError):
    """Canonical rows or manifests failed a deterministic local check."""


class LocalArrowCanonicalStore:
    """One-writer local store for immutable, externally sorted v3 partitions."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        memory_limit_mb: int = 2_048,
        # Keep the threads input explicit in the init contract.
        threads: int = 1,
        row_group_size: int = 8_192,
        projection_batch_rows: int = 8_192,
        validation_batch_rows: int = 512,
        tmp_quota_bytes: int | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local arrow canonical store init workflow in explicit, reviewable
        # steps.
        if (
            min(
                memory_limit_mb,
                threads,
                row_group_size,
                projection_batch_rows,
                validation_batch_rows,
            )
            <= 0
        ):
            raise ValueError("canonical store limits must be positive")
        if tmp_quota_bytes is not None and (
            isinstance(tmp_quota_bytes, bool) or tmp_quota_bytes <= 0
        ):
            # Fail the local arrow canonical store init path with ValueError for canonical
            # store temporary quota must be positive when tmp quota bytes and isinstance
            # is true; do not continue ambiguously.
            raise ValueError("canonical store temporary quota must be positive")
        self._artifacts = artifacts
        self._memory_limit_mb = memory_limit_mb
        self._threads = threads
        self._row_group_size = row_group_size
        # Assemble self projection batch rows once so the local arrow canonical store init
        # workflow shares one value.
        self._projection_batch_rows = projection_batch_rows
        self._validation_batch_rows = validation_batch_rows
        self._tmp_quota_bytes = tmp_quota_bytes
        self._build_tools = build_tools or _unit_writer_tools()
        self._tmp_root = artifacts.data_root / "tmp" / "canonical"
        self._tmp_root.mkdir(parents=True, exist_ok=True)

    # Define local arrow canonical store open reusable distribution as one focused
    # operation with an explicit boundary.
    def open_reusable_distribution(
        self,
        *,
        artifact_id: ArtifactId,
        plan: DatasetPlan,
        # Keep the shard input explicit in the open reusable distribution contract.
        shard: DatasetShard,
        capability: PlannedCapability,
        event_kind: EventKind,
        projector_bundle_id: BundleId,
    ) -> CanonicalDistributionRef:
        """Rehydrate one exact immutable v3 shard after full local verification."""

        evidence = immutable_reuse_evidence(plan, shard)
        if evidence is None:
            raise CanonicalDataError("source evidence does not prove an immutable reusable shard")
        writer_bundle_id = self._writer_bundle_id()
        expected_build_key = canonical_distribution_build_key(
            # Pass plan explicitly so canonical_distribution_build_key receives a
            # reviewable plan and shard input in local arrow canonical store open reusable
            # distribution.
            plan=plan,
            shard=shard,
            capability=capability,
            event_kind=event_kind,
            projector_bundle_id=projector_bundle_id,
            # Pass writer bundle id explicitly so canonical_distribution_build_key
            # receives a reviewable plan and shard input in local arrow canonical store
            # open reusable distribution.
            writer_bundle_id=writer_bundle_id,
        )
        handle = cast(_LocalHandle, self._artifacts.open_committed(artifact_id))
        try:
            # Perform the protected local arrow canonical store open reusable distribution
            # operation before explicit failure handling.
            descriptor = handle.descriptor
            if (
                descriptor.kind is not ArtifactKind.CANONICAL_DISTRIBUTION
                or descriptor.build_key != expected_build_key
                or descriptor.input_artifact_ids != (plan.spec.source_inspection_artifact_id,)
                # Evaluate the complete local arrow canonical store open reusable distribution
                # kind, canonical distribution and build key condition before guarded effects.
            ):
                # Handle the local arrow canonical store open reusable distribution kind,
                # canonical distribution and build key condition as a distinct block.
                raise CanonicalDataError(
                    "reusable distribution descriptor differs from the resolved shard"
                )
            manifest = _canonical_manifest(handle, "reusable distribution manifest")
            artifact_schema = manifest.get("artifact_schema")
            # Evaluate the complete local arrow canonical store open reusable distribution
            # artifact schema condition before guarded effects.
            if artifact_schema in {
                "canonical-distribution/v1",
                "canonical-distribution/v2",
                "canonical-distribution/v3",
                "canonical-distribution/v4",
                # Evaluate the complete local arrow canonical store open reusable distribution
                # artifact schema condition before guarded effects.
            }:
                raise ReprepareRequiredError(artifact_schema)
            schema = _schema(event_kind)
            if (
                set(manifest) != _distribution_manifest_keys()
                # Keep artifact schema visible while evaluating the artifact schema,
                # distribution artifact schema and canonical schema version guard.
                or artifact_schema != _DISTRIBUTION_ARTIFACT_SCHEMA
                or manifest.get("canonical_schema_version") != _CANONICAL_SCHEMA_VERSION
                or manifest.get("canonical_schema_id") != _schema_id(event_kind, schema).hex
                or manifest.get("network_id") != plan.spec.network_id.value
                or manifest.get("position_schema_id") != plan.spec.position_schema_id.value
                # Keep manifest visible while evaluating the artifact schema, distribution
                # artifact schema and canonical schema version guard.
                or manifest.get("capability_id") != capability.capability_id.value
                or manifest.get("event_kind") != event_kind.name
                or manifest.get("event_file") != "events.parquet"
                or manifest.get("projector_bundle_id") != projector_bundle_id.hex
                or manifest.get("writer_bundle_id") != writer_bundle_id.hex
                # Keep manifest visible while evaluating the artifact schema, distribution
                # artifact schema and canonical schema version guard.
                or manifest.get("source_contract")
                != canonical_distribution_source_contract(plan, shard, capability)
            ):
                # Handle the local arrow canonical store open reusable distribution
                # artifact schema, distribution artifact schema and canonical schema
                # version condition as a distinct block.
                raise CanonicalDataError(
                    "reusable distribution manifest differs from the resolved shard"
                )
            try:
                # Perform the protected local arrow canonical store open reusable
                # distribution operation before explicit failure handling.
                effective = EffectiveSourceBoundary.from_document(manifest["source_boundary"])
                logical_hash = LogicalContentHash(cast(str, manifest["logical_content_hash"]))
                row_count = _manifest_integer(manifest["row_count"], "row_count")
                minimum = _manifest_optional_integer(
                    manifest["minimum_boundary_ordinal"],
                    # Pass minimum boundary ordinal explicitly so
                    # _manifest_optional_integer receives a reviewable minimum boundary
                    # ordinal and manifest input in local arrow canonical store open
                    # reusable distribution.
                    "minimum_boundary_ordinal",
                    # Complete _manifest_optional_integer only after its minimum boundary
                    # ordinal and manifest inputs are visible in local arrow canonical store
                    # open reusable distribution.
                )
                maximum = _manifest_optional_integer(
                    manifest["maximum_boundary_ordinal"], "maximum_boundary_ordinal"
                )
                created_at = datetime.fromisoformat(cast(str, manifest["created_at"]))
            # Translate type error through the local arrow canonical store open reusable
            # distribution boundary without hiding other errors.
            except (TypeError, ValueError) as error:
                # Translate the (TypeError, ValueError) failure through the local arrow
                # canonical store open reusable distribution boundary.
                raise CanonicalDataError(
                    "reusable distribution manifest fields are invalid"
                ) from error
            boundary = effective.source_boundary
            if (
                # Keep effective visible while evaluating the event kind, source fidelity
                # and fidelity guard.
                effective.event_kind is not event_kind
                or effective.source_fidelity != capability.fidelity
                or boundary.source_id != plan.spec.source_id
                or boundary.capability_id != capability.capability_id
                or boundary.capability_schema_version != capability.schema_version
                # Keep boundary visible while evaluating the event kind, source fidelity
                # and fidelity guard.
                or boundary.block_range != shard.block_range
                or boundary.chain_finality is not evidence.chain_finality
                or boundary.completeness is not evidence.completeness
                or boundary.source_consistency is not evidence.consistency
                or boundary.ingestion_watermark_to_block != evidence.ingestion_watermark_to_block
                # Keep boundary visible while evaluating the event kind, source fidelity
                # and fidelity guard.
                or boundary.upstream_revision != evidence.upstream_revision
                or boundary.validation_status is not ValidationStatus.PASS
                or created_at.tzinfo is None
                or created_at.utcoffset() is None
            ):
                # Handle the local arrow canonical store open reusable distribution event
                # kind, source fidelity and fidelity condition as a distinct block.
                raise CanonicalDataError(
                    "reusable distribution source boundary differs from the exact cut"
                )
            qa = _validate_and_hash(
                handle.local_path("events.parquet"),
                event_kind,
                shard,
                batch_rows=self._validation_batch_rows,
            )
            if (
                # Keep qa visible while evaluating the hex, row count and minimum boundary
                # ordinal guard.
                qa.logical_content_hash.hex != logical_hash.hex
                or qa.row_count != row_count
                or qa.minimum_boundary_ordinal != minimum
                or qa.maximum_boundary_ordinal != maximum
            ):
                # Fail the local arrow canonical store open reusable distribution path
                # with CanonicalDataError for reusable distribution payload differs from
                # its manifest when hex, row count and minimum boundary ordinal is true;
                # do not continue ambiguously.
                raise CanonicalDataError("reusable distribution payload differs from its manifest")
            return CanonicalDistributionRef(
                artifact=descriptor,
                logical_content_hash=logical_hash,
                capability_id=capability.capability_id,
                # Pass event kind explicitly so CanonicalDistributionRef receives a
                # reviewable capability id and source fidelity input in local arrow
                # canonical store open reusable distribution.
                event_kind=event_kind,
                shard=shard,
                row_count=row_count,
                minimum_boundary_ordinal=minimum,
                maximum_boundary_ordinal=maximum,
                # Pass source boundary explicitly so CanonicalDistributionRef receives a
                # reviewable capability id and source fidelity input in local arrow
                # canonical store open reusable distribution.
                source_boundary=boundary,
                source_fidelity=effective.source_fidelity,
            )
        finally:
            handle.close()

    # Define local arrow canonical store publish distribution as one focused operation
    # with an explicit boundary.
    def publish_distribution(
        self,
        *,
        plan: DatasetPlan,
        shard: DatasetShard,
        # Keep the capability input explicit in the publish distribution contract.
        capability: PlannedCapability,
        event_kind: EventKind,
        projector_bundle_id: BundleId,
        batches: Iterable[ProjectedEventBatch],
        extracted_at: datetime,
        # Keep the canonical distribution ref input explicit in the publish distribution
        # contract.
    ) -> CanonicalDistributionRef:
        # Execute the local arrow canonical store publish distribution workflow in
        # explicit, reviewable steps.
        if shard.capability_id != capability.capability_id:
            raise ValueError("shard and capability do not match")
        if (
            shard.block_range.network_id != plan.spec.network_id
            or shard.block_range.position_schema_id != plan.spec.position_schema_id
            # Evaluate the complete local arrow canonical store publish distribution network
            # id, position schema id and block range condition before guarded effects.
        ):
            raise ValueError("shard and dataset plan use different chain identities")
        if extracted_at.tzinfo is None or extracted_at.utcoffset() is None:
            raise ValueError("extracted_at must be timezone-aware")
        schema = _schema(event_kind)
        # Assemble writer bundle id once so the local arrow canonical store publish
        # distribution workflow shares one value.
        writer_bundle_id = self._writer_bundle_id()
        schema_id = _schema_id(event_kind, schema)
        build_key = canonical_distribution_build_key(
            plan=plan,
            shard=shard,
            # Pass capability explicitly so canonical_distribution_build_key receives a
            # reviewable plan and shard input in local arrow canonical store publish
            # distribution.
            capability=capability,
            event_kind=event_kind,
            projector_bundle_id=projector_bundle_id,
            writer_bundle_id=writer_bundle_id,
        )
        # Assemble temporary root once so the local arrow canonical store publish
        # distribution workflow shares one value.
        temporary_root = Path(tempfile.mkdtemp(prefix="distribution-", dir=self._tmp_root))
        raw_path = temporary_root / "raw.parquet"
        sorted_path = temporary_root / "events.parquet"
        writer = None
        query_fingerprints: set[ContentDigest] = set()
        # Keep expected failures inside the local arrow canonical store publish
        # distribution error boundary.
        try:
            # Perform the protected local arrow canonical store publish distribution
            # operation before explicit failure handling.
            parquet_writer = pq.ParquetWriter(
                raw_path, schema, compression="zstd", use_dictionary=True, write_statistics=True
            )
            try:
                # Perform the protected local arrow canonical store publish distribution
                # operation before explicit failure handling.
                pending: list[dict[str, object]] = []
                for batch in batches:
                    # Process batches inside the bounded local arrow canonical store
                    # publish distribution loop.
                    if batch.query_fingerprint is not None:
                        query_fingerprints.add(batch.query_fingerprint)
                    for event in batch.events:
                        # Process batch.events inside the bounded local arrow canonical
                        # store publish distribution loop.
                        _validate_event_for_shard(event, event_kind, shard)
                        pending.append(_event_row(event))
                        if len(pending) >= self._projection_batch_rows:
                            # Handle the local arrow canonical store publish distribution
                            # projection batch rows and pending condition as a distinct
                            # block.
                            parquet_writer.write_table(pa.Table.from_pylist(pending, schema=schema))
                            pending.clear()
                if pending:
                    parquet_writer.write_table(pa.Table.from_pylist(pending, schema=schema))
            finally:
                # Invoke close as a visible step within the local arrow canonical store
                # publish distribution workflow.
                parquet_writer.close()

            self._external_sort(raw_path, sorted_path, schema)
            self._reject_identity_collisions(sorted_path)
            qa = _validate_and_hash(
                sorted_path,
                event_kind,
                shard,
                batch_rows=self._validation_batch_rows,
            )
            logical_hash = LogicalContentHash(qa.logical_content_hash.hex)
            # Assemble internal revision once so the local arrow canonical store publish
            # distribution workflow shares one value.
            internal_revision = domain_digest(
                "backtest.internal-dataset-revision.v2",
                {
                    "block_range": _block_range_document(shard.block_range),
                    "capability_id": capability.capability_id.value,
                    # Keep capability schema version named so the v2 and block range
                    # payload passed to domain_digest remains self-describing within local
                    # arrow canonical store publish distribution.
                    "capability_schema_version": capability.schema_version,
                    "logical_content_hash": logical_hash.hex,
                    "projector_bundle_id": projector_bundle_id.hex,
                    "query_fingerprints": sorted(item.hex for item in query_fingerprints),
                    "source_id": plan.spec.source_id.value,
                    # Close the v2 and block range payload only after all local arrow
                    # canonical store publish distribution fields are present.
                },
            )
            cut_evidence = covering_cut_evidence(plan, shard)
            boundary = SourceBoundary(
                source_id=plan.spec.source_id,
                # Pass capability id explicitly so SourceBoundary receives a reviewable
                # source id and spec input in local arrow canonical store publish
                # distribution.
                capability_id=capability.capability_id,
                capability_schema_version=capability.schema_version,
                block_range=shard.block_range,
                snapshot_cut_to_block=shard.block_range.to_block_ordinal,
                chain_finality=capability.fidelity.chain_finality,
                # Pass ingestion watermark to block explicitly so SourceBoundary receives
                # a reviewable source id and spec input in local arrow canonical store
                # publish distribution.
                ingestion_watermark_to_block=(
                    None if cut_evidence is None else cut_evidence.ingestion_watermark_to_block
                ),
                upstream_revision=(
                    None if cut_evidence is None else cut_evidence.upstream_revision
                    # Complete SourceBoundary only after its source id and spec inputs are
                    # visible in local arrow canonical store publish distribution.
                ),
                internal_revision=internal_revision,
                source_consistency=capability.fidelity.consistency,
                completeness=capability.fidelity.completeness,
                validation_status=ValidationStatus.PASS,
                # Keep the sorted and query fingerprints tuple step visible while building
                # boundary.
                query_fingerprints=tuple(sorted(query_fingerprints, key=lambda item: item.hex)),
            )
            effective_fidelity = SourceFidelity(
                identity=capability.fidelity.identity,
                ordering=capability.fidelity.ordering,
                # Pass state explicitly so SourceFidelity receives a reviewable identity
                # and fidelity input in local arrow canonical store publish distribution.
                state=capability.fidelity.state,
                fees=capability.fidelity.fees,
                chain_finality=boundary.chain_finality,
                completeness=boundary.completeness,
                consistency=boundary.source_consistency,
                # Complete SourceFidelity only after its identity and fidelity inputs are
                # visible in local arrow canonical store publish distribution.
            )
            effective_boundary = EffectiveSourceBoundary(
                source_boundary=boundary,
                event_kind=event_kind,
                source_fidelity=effective_fidelity,
                # Complete EffectiveSourceBoundary only after its boundary and event kind
                # inputs are visible in local arrow canonical store publish distribution.
            )
            identity_manifest = {
                "artifact_schema": _DISTRIBUTION_ARTIFACT_SCHEMA,
                "canonical_schema_id": schema_id.hex,
                "canonical_schema_version": _CANONICAL_SCHEMA_VERSION,
                # Keep the capability id component named inside the identity manifest
                # contract.
                "capability_id": capability.capability_id.value,
                "event_file": "events.parquet",
                "event_kind": event_kind.name,
                "logical_content_hash": logical_hash.hex,
                "maximum_boundary_ordinal": qa.maximum_boundary_ordinal,
                # Keep the minimum boundary ordinal component named inside the identity
                # manifest contract.
                "minimum_boundary_ordinal": qa.minimum_boundary_ordinal,
                "network_id": plan.spec.network_id.value,
                "position_schema_id": plan.spec.position_schema_id.value,
                "projector_bundle_id": projector_bundle_id.hex,
                "row_count": qa.row_count,
                # Register identity document and effective boundary through
                # identity_document so the identity manifest table remains scannable.
                "source_boundary": effective_boundary.identity_document(),
                "source_contract": canonical_distribution_source_contract(plan, shard, capability),
                "writer_bundle_id": writer_bundle_id.hex,
            }
            full_manifest = {**identity_manifest, "created_at": extracted_at.isoformat()}
            # Assemble writer once so the local arrow canonical store publish distribution
            # workflow shares one value.
            writer = self._artifacts.stage(
                ArtifactDraft(
                    kind=ArtifactKind.CANONICAL_DISTRIBUTION,
                    build_key=build_key,
                    input_artifact_ids=(plan.spec.source_inspection_artifact_id,),
                    # Complete ArtifactDraft only after its canonical distribution and source
                    # inspection artifact id inputs are visible in local arrow canonical store
                    # publish distribution.
                )
            )
            with writer.open_binary("events.parquet") as destination:
                _copy_file(sorted_path, destination)
            committed = writer.commit(
                # Keep the full manifest canonical_json_bytes step visible while building
                # committed.
                canonical_json_bytes(full_manifest),
                identity_manifest_bytes=canonical_json_bytes(identity_manifest),
            )
            return CanonicalDistributionRef(
                artifact=committed,
                # Pass logical content hash explicitly so CanonicalDistributionRef
                # receives a reviewable capability id and row count input in local arrow
                # canonical store publish distribution.
                logical_content_hash=logical_hash,
                capability_id=capability.capability_id,
                event_kind=event_kind,
                shard=shard,
                row_count=qa.row_count,
                # Pass minimum boundary ordinal explicitly so CanonicalDistributionRef
                # receives a reviewable capability id and row count input in local arrow
                # canonical store publish distribution.
                minimum_boundary_ordinal=qa.minimum_boundary_ordinal,
                maximum_boundary_ordinal=qa.maximum_boundary_ordinal,
                source_boundary=boundary,
                source_fidelity=effective_fidelity,
            )
        # Translate base exception through the local arrow canonical store publish
        # distribution boundary without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the local arrow canonical store
            # publish distribution boundary.
            if writer is not None:
                writer.abort()
            raise
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)

    # Define local arrow canonical store publish snapshot as one focused operation with an
    # explicit boundary.
    def publish_snapshot(
        self,
        *,
        plan: DatasetPlan,
        projector_bundle_id: BundleId,
        # Keep the distributions input explicit in the publish snapshot contract.
        distributions: tuple[CanonicalDistributionRef, ...],
        extracted_at: datetime,
        validator: CanonicalSnapshotValidator | None = None,
    ) -> PreparedSnapshot:
        # Execute the local arrow canonical store publish snapshot workflow in explicit,
        # reviewable steps.
        if not distributions:
            raise ValueError("snapshot requires at least one canonical distribution")
        self._writer_bundle_id()
        expected_shards = tuple(plan.spec.shards)
        by_ordinal = {item.shard.ordinal: item for item in distributions}
        # Evaluate the complete local arrow canonical store publish snapshot by ordinal,
        # distributions and sorted condition before guarded effects.
        if len(by_ordinal) != len(distributions) or tuple(sorted(by_ordinal)) != tuple(
            range(len(expected_shards))
        ):
            raise ValueError("snapshot distributions must cover unique contiguous shard ordinals")
        if (
            # Keep tuple visible while evaluating the expected shards, shard and index
            # guard.
            tuple(by_ordinal[index].shard for index in range(len(expected_shards)))
            != expected_shards
        ):
            raise ValueError("snapshot distributions do not exactly match the dataset plan")
        ordered = tuple(by_ordinal[index] for index in range(len(expected_shards)))
        # Evaluate the complete local arrow canonical store publish snapshot item, ordered
        # and network id condition before guarded effects.
        if any(
            item.shard.block_range.network_id != plan.spec.network_id
            or item.shard.block_range.position_schema_id != plan.spec.position_schema_id
            for item in ordered
        ):
            # Fail the local arrow canonical store publish snapshot path with ValueError
            # for snapshot distributions mix chain identities when item, ordered and
            # network id is true; do not continue ambiguously.
            raise ValueError("snapshot distributions mix chain identities")

        if plan.spec.settlement_requirement is not None:
            # Handle the local arrow canonical store publish snapshot settlement
            # requirement, spec and plan condition as a distinct block.
            if validator is None:
                raise SnapshotValidationError(SnapshotValidationErrorCode.VALIDATOR_REQUIRED)
            from backtest.adapters.columnar.arrow.parquet_replay import (
                CanonicalDistributionCandidateSource,
            )

            # Keep expected failures inside the local arrow canonical store publish
            # snapshot error boundary.
            try:
                # Perform the protected local arrow canonical store publish snapshot
                # operation before explicit failure handling.
                candidate = CanonicalDistributionCandidateSource(
                    self._artifacts,
                    plan.spec,
                    ordered,
                    projector_bundle_id=projector_bundle_id,
                    # Keep the writer bundle id _writer_bundle_id step visible while
                    # building candidate.
                    writer_bundle_id=self._writer_bundle_id(),
                    reader_batch_rows=self._validation_batch_rows,
                    reader_readahead=1,
                )
                validator.validate_snapshot_candidate(plan.spec, candidate)
            # Translate snapshot validation error through the local arrow canonical store
            # publish snapshot boundary without hiding other errors.
            except SnapshotValidationError:
                raise
            except TransactionClockError as error:
                raise SnapshotValidationError(SnapshotValidationErrorCode.CLOCK_INVALID) from error
            except ChainIdentityMismatchError as error:
                # Translate the ChainIdentityMismatchError failure through the local arrow
                # canonical store publish snapshot boundary.
                raise SnapshotValidationError(
                    SnapshotValidationErrorCode.EVENT_POSITION_INVALID
                ) from error
            except CanonicalDataError as error:
                # Translate the CanonicalDataError failure through the local arrow
                # canonical store publish snapshot boundary.
                raise SnapshotValidationError(
                    SnapshotValidationErrorCode.EVENT_STREAM_INVALID
                ) from error

        logical_hash = self._snapshot_logical_hash(ordered)
        boundaries = [item.effective_source_boundary.identity_document() for item in ordered]
        # Assemble dataset revision id once so the local arrow canonical store publish
        # snapshot workflow shares one value.
        dataset_revision_id = DatasetRevisionId(
            domain_digest(
                "backtest.dataset-revision.v4",
                {
                    "boundaries": boundaries,
                    # Keep canonical schema version named so the v4 and boundaries payload
                    # passed to domain_digest remains self-describing within local arrow
                    # canonical store publish snapshot.
                    "canonical_schema_version": _CANONICAL_SCHEMA_VERSION,
                    "logical_content_hash": logical_hash.hex,
                    "network_id": plan.spec.network_id.value,
                    "position_schema_id": plan.spec.position_schema_id.value,
                    "projector_bundle_id": projector_bundle_id.hex,
                    # Keep spec id named so the v4 and boundaries payload passed to
                    # domain_digest remains self-describing within local arrow canonical
                    # store publish snapshot.
                    "spec_id": plan.spec.spec_id.hex,
                },
            ).hex
        )
        identity_manifest = {
            # Keep the artifact schema component named inside the identity manifest
            # contract.
            "artifact_schema": _SNAPSHOT_ARTIFACT_SCHEMA,
            "canonical_schema_version": _CANONICAL_SCHEMA_VERSION,
            "capability_ranges": [
                {
                    "block_range": _block_range_document(item.block_range),
                    # Keep the capability id component named inside the identity manifest
                    # contract.
                    "capability_id": item.capability_id.value,
                }
                for item in plan.spec.capability_ranges
            ],
            "dataset_revision_id": dataset_revision_id.hex,
            # Register spec through dataset_spec_document so the identity manifest table
            # remains scannable.
            "dataset_spec": dataset_spec_document(plan.spec),
            "distributions": [
                {
                    "artifact_id": item.artifact.artifact_id.hex,
                    "capability_id": item.capability_id.value,
                    # Keep the event kind component named inside the identity manifest
                    # contract.
                    "event_kind": item.event_kind.name,
                    "logical_content_hash": item.logical_content_hash.hex,
                    "manifest_digest": item.artifact.manifest_digest.hex,
                    "row_count": item.row_count,
                    "shard": _shard_document(item.shard),
                    # Complete the identity manifest group only after its semantic components
                    # are visible.
                }
                for item in ordered
            ],
            "logical_content_hash": logical_hash.hex,
            "network_id": plan.spec.network_id.value,
            # Keep the position schema id component named inside the identity manifest
            # contract.
            "position_schema_id": plan.spec.position_schema_id.value,
            "projector_bundle_id": projector_bundle_id.hex,
            "requested_decision_range": _block_range_document(plan.spec.decision_range),
            "settlement_tail": (
                None
                # Keep the plan component named inside the identity manifest contract.
                if plan.spec.settlement_tail is None
                else _block_range_document(plan.spec.settlement_tail)
            ),
            "source_boundaries": boundaries,
            "source_id": plan.spec.source_id.value,
            # Keep the spec id component named inside the identity manifest contract.
            "spec_id": plan.spec.spec_id.hex,
            "validation_status": ValidationStatus.PASS.value,
        }
        full_manifest = {**identity_manifest, "created_at": extracted_at.isoformat()}
        build_key = domain_digest(
            # Pass version tag explicitly so domain_digest receives a reviewable v4 and
            # distribution ids input in local arrow canonical store publish snapshot.
            "backtest.canonical-snapshot-build.v4",
            {
                "distribution_ids": [item.artifact.artifact_id.hex for item in ordered],
                "projector_bundle_id": projector_bundle_id.hex,
                "spec_id": plan.spec.spec_id.hex,
                # Close the v4 and distribution ids payload only after all local arrow
                # canonical store publish snapshot fields are present.
            },
        )
        writer = self._artifacts.stage(
            ArtifactDraft(
                kind=ArtifactKind.SNAPSHOT,
                # Pass build key explicitly so ArtifactDraft receives a reviewable
                # snapshot and artifact id input in local arrow canonical store publish
                # snapshot.
                build_key=build_key,
                input_artifact_ids=tuple(item.artifact.artifact_id for item in ordered),
            )
        )
        try:
            # Perform the protected local arrow canonical store publish snapshot operation
            # before explicit failure handling.
            committed = writer.commit(
                canonical_json_bytes(full_manifest),
                identity_manifest_bytes=canonical_json_bytes(identity_manifest),
            )
        except BaseException:
            # Translate the BaseException failure through the local arrow canonical store
            # publish snapshot boundary.
            writer.abort()
            raise
        return PreparedSnapshot(
            artifact=committed,
            snapshot_id=SnapshotId(committed.artifact_id.hex),
            # Pass dataset revision id explicitly so PreparedSnapshot receives a
            # reviewable hex and artifact id input in local arrow canonical store publish
            # snapshot.
            dataset_revision_id=dataset_revision_id,
            logical_content_hash=logical_hash,
            spec=plan.spec,
            projector_bundle_id=projector_bundle_id,
            distributions=ordered,
            # Pass extracted at explicitly so PreparedSnapshot receives a reviewable hex
            # and artifact id input in local arrow canonical store publish snapshot.
            extracted_at=extracted_at,
        )

    def _external_sort(self, raw_path: Path, sorted_path: Path, schema: pa.Schema) -> None:
        # Execute the local arrow canonical store external sort workflow in explicit,
        # reviewable steps.
        connection = duckdb.connect()
        parquet_writer: pq.ParquetWriter | None = None
        try:
            # Perform the protected local arrow canonical store external sort operation
            # before explicit failure handling.
            connection.execute(f"SET memory_limit='{self._memory_limit_mb}MB'")
            connection.execute(f"SET threads={self._threads}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute("SET temp_directory=?", [str(self._tmp_root)])
            self._apply_tmp_quota(connection)
            # Assemble relation once so the local arrow canonical store external sort
            # workflow shares one value.
            relation = connection.read_parquet(str(raw_path)).order(
                "boundary_ordinal, transaction_group_id, event_index NULLS FIRST, stable_causal_id"
            )
            parquet_writer = pq.ParquetWriter(
                sorted_path,
                # Pass schema explicitly so ParquetWriter receives a reviewable zstd and
                # sorted path input in local arrow canonical store external sort.
                schema,
                compression="zstd",
                use_dictionary=True,
                write_statistics=True,
                # Complete ParquetWriter only after its zstd and sorted path inputs are
                # visible in local arrow canonical store external sort.
            )
            for batch in relation.to_arrow_reader(batch_size=self._row_group_size):
                # Process to arrow reader, relation and row group size inside the bounded
                # local arrow canonical store external sort loop.
                table = pa.Table.from_batches([batch]).cast(schema, safe=True)
                parquet_writer.write_table(table, row_group_size=self._row_group_size)
        finally:
            # Handle the cleanup path after the protected local arrow canonical store
            # external sort operation.
            if parquet_writer is not None:
                parquet_writer.close()
            connection.close()

    def _snapshot_logical_hash(
        self,
        # Keep the distributions input explicit in the snapshot logical hash contract.
        distributions: tuple[CanonicalDistributionRef, ...],
        # Keep the logical content hash input explicit in the snapshot logical hash contract.
    ) -> LogicalContentHash:
        # Execute the local arrow canonical store snapshot logical hash workflow in
        # explicit, reviewable steps.
        handles: list[_LocalHandle] = []
        connection = duckdb.connect()
        try:
            # Perform the protected local arrow canonical store snapshot logical hash
            # operation before explicit failure handling.
            paths: list[str] = []
            for item in distributions:
                # Process distributions inside the bounded local arrow canonical store
                # snapshot logical hash loop.
                handle = cast(
                    _LocalHandle, self._artifacts.open_committed(item.artifact.artifact_id)
                )
                handles.append(handle)
                paths.append(str(handle.local_path("events.parquet")))
            # Invoke execute for set memory limit=' and mb' as a visible local arrow
            # canonical store snapshot logical hash step.
            connection.execute(f"SET memory_limit='{self._memory_limit_mb}MB'")
            connection.execute(f"SET threads={self._threads}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute("SET temp_directory=?", [str(self._tmp_root)])
            self._apply_tmp_quota(connection)
            # Assemble relation once so the local arrow canonical store snapshot logical
            # hash workflow shares one value.
            relation = (
                connection.read_parquet(paths, union_by_name=True)
                .project(
                    "boundary_ordinal, transaction_group_id, event_index, "
                    "stable_causal_id, logical_row_digest"
                    # Complete project only after its declared inputs are visible in local
                    # arrow canonical store snapshot logical hash.
                )
                .order(
                    "boundary_ordinal, transaction_group_id, "
                    "event_index NULLS FIRST, stable_causal_id"
                )
                # Complete the relation group only after its semantic components are visible.
            )
            digest = hashlib.sha256(b"backtest.canonical-logical-stream.v3\x00")
            for batch in relation.to_arrow_reader(batch_size=self._validation_batch_rows):
                # Process to arrow reader and relation inside the bounded local arrow
                # canonical store snapshot logical hash loop.
                column = batch.column(batch.schema.get_field_index("logical_row_digest"))
                for value in column:
                    # Process column inside the bounded local arrow canonical store
                    # snapshot logical hash loop.
                    raw = value.as_py()
                    if not isinstance(raw, bytes) or len(raw) != 32:
                        raise CanonicalDataError("logical row digest has an invalid width")
                    digest.update(raw)
            return LogicalContentHash(digest.hexdigest())
        # Complete the required cleanup regardless of the protected outcome.
        finally:
            # Handle the cleanup path after the protected local arrow canonical store
            # snapshot logical hash operation.
            connection.close()
            for handle in handles:
                handle.close()

    def _reject_identity_collisions(self, path: Path) -> None:
        # Execute the local arrow canonical store reject identity collisions workflow in
        # explicit, reviewable steps.
        connection = duckdb.connect()
        try:
            # Perform the protected local arrow canonical store reject identity collisions
            # operation before explicit failure handling.
            connection.execute(f"SET memory_limit='{self._memory_limit_mb}MB'")
            connection.execute(f"SET threads={self._threads}")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute("SET temp_directory=?", [str(self._tmp_root)])
            self._apply_tmp_quota(connection)
            # Traverse source record id and canonical event id explicitly so each local
            # arrow canonical store reject identity collisions iteration remains
            # traceable.
            for column, message in (
                (
                    "source_record_id",
                    "stable source occurrence identity is duplicated; multiplicity is ambiguous",
                ),
                # Traverse source record id and canonical event id explicitly so each
                # local arrow canonical store reject identity collisions iteration remains
                # traceable.
                ("canonical_event_id", "canonical event identity is duplicated"),
            ):
                # Process source record id and canonical event id inside the bounded local
                # arrow canonical store reject identity collisions loop.
                duplicate = connection.execute(
                    f"SELECT 1 FROM read_parquet(?) GROUP BY {column} HAVING count(*) > 1 LIMIT 1",
                    [str(path)],
                ).fetchone()
                if duplicate is not None:
                    # Fail the local arrow canonical store reject identity collisions path
                    # with CanonicalDataError for message when duplicate is true; do not
                    # continue ambiguously.
                    raise CanonicalDataError(message)
        finally:
            connection.close()

    def _apply_tmp_quota(self, connection: Any) -> None:
        # Execute the local arrow canonical store apply tmp quota workflow in explicit,
        # reviewable steps.
        if self._tmp_quota_bytes is not None:
            connection.execute(f"SET max_temp_directory_size='{self._tmp_quota_bytes}B'")

    def _writer_bundle_id(self) -> BundleId:
        return self._build_tools.require_current(CANONICAL_WRITER_ROLE)


def canonical_distribution_build_key(
    # Close the canonical distribution build key signature after its explicit inputs.
    *,
    plan: DatasetPlan,
    shard: DatasetShard,
    capability: PlannedCapability,
    event_kind: EventKind,
    # Keep the projector bundle id input explicit in the canonical distribution build key
    # contract.
    projector_bundle_id: BundleId,
    writer_bundle_id: BundleId | None = None,
) -> ContentDigest:
    """Intent identity for one shard, independent of the enclosing dataset plan."""

    schema = _schema(event_kind)
    return domain_digest(
        "backtest.canonical-distribution-build.v5",
        {
            "canonical_schema_id": _schema_id(event_kind, schema).hex,
            # Keep event kind named so the name and v5 payload passed to domain_digest
            # remains self-describing within canonical distribution build key.
            "event_kind": event_kind.name,
            "network_id": plan.spec.network_id.value,
            "position_schema_id": plan.spec.position_schema_id.value,
            "projector_bundle_id": projector_bundle_id.hex,
            "source_contract": canonical_distribution_source_contract(plan, shard, capability),
            # Keep writer bundle id named so the name and v5 payload passed to
            # domain_digest remains self-describing within canonical distribution build
            # key.
            "writer_bundle_id": (
                _UNIT_WRITER_BUNDLE_ID if writer_bundle_id is None else writer_bundle_id
            ).hex,
        },
    )


# Define canonical writer bundle id as one focused operation with an explicit boundary.
def canonical_writer_bundle_id() -> BundleId:
    """Return the fixed isolated-unit default; production injects an exact pin."""

    return BundleId(_UNIT_WRITER_BUNDLE_ID.hex)


def _schema(event_kind: EventKind) -> pa.Schema:
    # Execute the schema workflow in explicit, reviewable steps.
    common = [
        pa.field("boundary_ordinal", pa.uint64(), nullable=False),
        pa.field("block_ordinal", pa.uint32(), nullable=False),
        pa.field("transaction_index", pa.int64(), nullable=False),
        pa.field("event_index", pa.uint32(), nullable=True),
        # Register transaction group id through field so the common table remains
        # scannable.
        pa.field("transaction_group_id", pa.binary(32), nullable=False),
        pa.field("source_record_id", pa.binary(32), nullable=False),
        pa.field("canonical_event_id", pa.binary(32), nullable=False),
        pa.field("stable_causal_id", pa.binary(32), nullable=False),
        pa.field("logical_row_digest", pa.binary(32), nullable=False),
        # Register capability id through field so the common table remains scannable.
        pa.field("capability_id", pa.string(), nullable=False),
        pa.field("protocol", pa.string(), nullable=False),
        pa.field("protocol_version", pa.string(), nullable=False),
        pa.field("ordering_fidelity", pa.string(), nullable=False),
        pa.field("event_kind", pa.uint8(), nullable=False),
        # Complete the common group only after its semantic components are visible.
    ]
    protocol_payload = [
        pa.field("protocol_payload_schema", pa.string(), nullable=False),
        pa.field("protocol_payload", pa.binary(), nullable=False),
    ]
    # Assemble fee component once so the schema workflow shares one value.
    fee_component = pa.struct(
        [
            pa.field("component_id", pa.string(), nullable=False),
            pa.field("asset_id", pa.string(), nullable=False),
            pa.field("amount_atomic", pa.binary(16), nullable=False),
            # Close the component id and asset id payload only after all schema fields are
            # present.
        ]
    )
    payload = {
        EventKind.BLOCK: [
            pa.field("block_time_ns", pa.int64(), nullable=False),
            # Keep the transaction count field step visible while building payload.
            pa.field("transaction_count", pa.uint32(), nullable=False),
            pa.field("block_hash", pa.string(), nullable=True),
        ],
        EventKind.TOKEN_LAUNCH: [
            pa.field("asset_id", pa.string(), nullable=False),
            # Keep the developer id field step visible while building payload.
            pa.field("developer_id", pa.string(), nullable=False),
            pa.field("creation_user_id", pa.string(), nullable=False),
            pa.field("venue_id", pa.string(), nullable=False),
            pa.field("quote_asset_id", pa.string(), nullable=False),
            pa.field("decimals", pa.int16(), nullable=True),
            # Pass protocol payload explicitly so get receives a reviewable event kind
            # input in schema.
            *protocol_payload,
        ],
        EventKind.VENUE_TRADE: [
            pa.field("venue_id", pa.string(), nullable=False),
            pa.field("sold_asset_id", pa.string(), nullable=False),
            # Keep the bought asset id field step visible while building payload.
            pa.field("bought_asset_id", pa.string(), nullable=False),
            pa.field("sold_amount_atomic", pa.binary(16), nullable=False),
            pa.field("bought_amount_atomic", pa.binary(16), nullable=False),
            # Parquet canonicalizes the LIST child name to ``element``.  Name
            # it explicitly so the schema is byte-stable across write/read
            # verification instead of comparing ``item`` with ``element``.
            pa.field(
                "fee_components",
                pa.list_(pa.field("element", fee_component)),
                nullable=False,
            ),
            # Pass protocol payload explicitly so get receives a reviewable event kind
            # input in schema.
            *protocol_payload,
        ],
        EventKind.VENUE_LIFECYCLE: [
            pa.field("venue_id", pa.string(), nullable=False),
            pa.field("lifecycle_kind", pa.string(), nullable=False),
            # Pass protocol payload explicitly so get receives a reviewable event kind
            # input in schema.
            *protocol_payload,
        ],
    }.get(event_kind)
    if payload is None:
        raise ValueError(f"canonical schema is not implemented for {event_kind.name}")
    # Return the completed schema result without a hidden fallback.
    return pa.schema([*common, *payload])


def _schema_id(event_kind: EventKind, schema: pa.Schema) -> ContentDigest:
    # Execute the schema id workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.canonical-parquet-schema.v3",
        {
            "event_kind": event_kind.name,
            "fields": [
                # Include name in the completed schema id result.
                {"name": field.name, "nullable": field.nullable, "type": str(field.type)}
                for field in schema
            ],
            "schema_version": _CANONICAL_SCHEMA_VERSION,
        },
        # Complete domain_digest only after its name and v3 inputs are visible in schema id.
    )


def _event_row(event: CanonicalEvent) -> dict[str, object]:
    # Execute the event row workflow in explicit, reviewable steps.
    envelope = event.envelope
    row: dict[str, object] = {
        "boundary_ordinal": envelope.boundary_ordinal,
        "block_ordinal": envelope.position.block_ordinal,
        "canonical_event_id": bytes.fromhex(envelope.canonical_event_id.hex),
        # Keep the capability id component named inside the row contract.
        "capability_id": envelope.capability_id.value,
        "event_index": envelope.position.event_index,
        "event_kind": int(event.kind),
        "logical_row_digest": bytes.fromhex(canonical_event_digest(event).hex),
        "ordering_fidelity": envelope.ordering_fidelity.value,
        # Keep the protocol component named inside the row contract.
        "protocol": envelope.protocol,
        "protocol_version": envelope.protocol_version,
        "source_record_id": bytes.fromhex(envelope.source_record_id.hex),
        "stable_causal_id": bytes.fromhex(envelope.stable_causal_id.hex),
        "transaction_group_id": bytes.fromhex(envelope.transaction_group_id.hex),
        # Keep the transaction index component named inside the row contract.
        "transaction_index": envelope.position.transaction_index,
    }
    if isinstance(event, BlockEvent):
        # Handle the event row isinstance(event, BlockEvent) branch as a distinct logical
        # block.
        if event.block_time_ns is None or event.tx_count is None:
            # Handle the event row block time ns, tx count and event condition as a
            # distinct block.
            raise CanonicalDataError(
                "canonical v3 block clock requires exact block time and transaction count"
            )
        row.update(
            block_hash=event.block_hash,
            # Pass block time ns explicitly so update receives a reviewable block hash and
            # block time ns input in event row.
            block_time_ns=event.block_time_ns,
            transaction_count=event.tx_count,
        )
    # Handle the event row complement of isinstance(event, BlockEvent) explicitly.
    elif isinstance(event, TokenLaunchEvent):
        # Handle the event row isinstance(event, TokenLaunchEvent) branch as a distinct
        # logical block.
        row.update(
            asset_id=event.asset_id.value,
            creation_user_id=event.creation_user_id.value,
            decimals=event.decimals,
            developer_id=event.developer_id.value,
            # Pass protocol payload explicitly so update receives a reviewable value and
            # asset id input in event row.
            protocol_payload=event.protocol_payload,
            protocol_payload_schema=event.protocol_payload_schema.value,
            quote_asset_id=event.quote_asset_id.value,
            venue_id=event.venue_id.value,
        )
    # Handle the event row complement of isinstance(event, TokenLaunchEvent) explicitly.
    elif isinstance(event, VenueTradeEvent):
        # Handle the event row isinstance(event, VenueTradeEvent) branch as a distinct
        # logical block.
        row.update(
            bought_amount_atomic=_int128_bytes(event.bought_amount_atomic),
            bought_asset_id=event.bought_asset_id.value,
            fee_components=[
                {
                    # Pass amount atomic explicitly to update for amount atomic and asset
                    # id.
                    "amount_atomic": _int128_bytes(component.amount_atomic),
                    "asset_id": component.asset_id.value,
                    "component_id": component.component_id.value,
                }
                for component in event.fee_components
                # Close the amount atomic and asset id payload only after all event row fields
                # are present.
            ],
            protocol_payload=event.protocol_payload,
            protocol_payload_schema=event.protocol_payload_schema.value,
            sold_amount_atomic=_int128_bytes(event.sold_amount_atomic),
            sold_asset_id=event.sold_asset_id.value,
            # Pass venue id explicitly so update receives a reviewable amount atomic and
            # asset id input in event row.
            venue_id=event.venue_id.value,
        )
    # Handle the event row complement of isinstance(event, VenueTradeEvent) explicitly.
    elif isinstance(event, VenueLifecycleEvent):
        # Handle the event row isinstance(event, VenueLifecycleEvent) branch as a distinct
        # logical block.
        row.update(
            lifecycle_kind=event.lifecycle_kind.value,
            protocol_payload=event.protocol_payload,
            protocol_payload_schema=event.protocol_payload_schema.value,
            venue_id=event.venue_id.value,
            # Complete update only after its value and lifecycle kind inputs are visible in
            # event row.
        )
    else:  # pragma: no cover
        raise TypeError(f"unsupported canonical event: {type(event).__name__}")
    return row


# Keep the distribution qa contract and validation rules together.
@dataclass(frozen=True, slots=True)
class _DistributionQa:
    row_count: int
    logical_content_hash: ContentDigest
    minimum_boundary_ordinal: int | None
    # Declare maximum boundary ordinal explicitly in the distribution qa contract.
    maximum_boundary_ordinal: int | None


def _validate_and_hash(
    path: Path,
    event_kind: EventKind,
    shard: DatasetShard,
    *,
    batch_rows: int,
) -> _DistributionQa:
    # Execute the validate and hash workflow in explicit, reviewable steps.
    parquet = pq.ParquetFile(path)
    if not parquet.schema_arrow.equals(_schema(event_kind), check_metadata=True):
        raise CanonicalDataError("canonical Parquet schema differs from its versioned contract")
    digest = hashlib.sha256(b"backtest.canonical-distribution-stream.v3\x00")
    previous_key: tuple[int, bytes, int, bytes] | None = None
    # Assemble row count once so the validate and hash workflow shares one value.
    row_count = 0
    minimum: int | None = None
    maximum: int | None = None
    for batch in parquet.iter_batches(batch_size=batch_rows):
        # Process parquet.iter_batches inside a bounded validation and hash loop.  The
        # physical batch size cannot affect ordering checks or the canonical digest.
        names = batch.schema.names
        columns = {name: batch.column(names.index(name)) for name in names}
        for index in range(batch.num_rows):
            # Process range(batch.num_rows) inside the bounded validate and hash loop.
            boundary = cast(int, columns["boundary_ordinal"][index].as_py())
            block_ordinal = cast(int, columns["block_ordinal"][index].as_py())
            transaction_index = cast(int, columns["transaction_index"][index].as_py())
            event_index_value = columns["event_index"][index].as_py()
            position = ChainPosition(
                # Pass network id explicitly so ChainPosition receives a reviewable
                # network id and block range input in validate and hash.
                network_id=shard.block_range.network_id,
                position_schema_id=shard.block_range.position_schema_id,
                block_ordinal=block_ordinal,
                transaction_index=transaction_index,
                event_index=(None if event_index_value is None else cast(int, event_index_value)),
                # Complete ChainPosition only after its network id and block range inputs are
                # visible in validate and hash.
            )
            capability_id = cast(str, columns["capability_id"][index].as_py())
            stored_event_kind = cast(int, columns["event_kind"][index].as_py())
            if (
                boundary != position.boundary_ordinal
                # Keep shard visible while evaluating the boundary, boundary ordinal and
                # capability id guard.
                or not shard.block_range.contains_block(block_ordinal)
                or capability_id != shard.capability_id.value
                or stored_event_kind != int(event_kind)
            ):
                # Handle the validate and hash boundary, boundary ordinal and capability
                # id condition as a distinct block.
                raise CanonicalDataError(
                    "canonical payload rows differ from their exact shard contract"
                )
            group = cast(bytes, columns["transaction_group_id"][index].as_py())
            stable = cast(bytes, columns["stable_causal_id"][index].as_py())
            # Assemble key once so the validate and hash workflow shares one value.
            key = (
                boundary,
                group,
                -1 if event_index_value is None else cast(int, event_index_value),
                stable,
                # Complete the key group only after its semantic components are visible.
            )
            if previous_key is not None and key < previous_key:
                raise CanonicalDataError("canonical rows are not in monotone order")
            previous_key = key
            logical = cast(bytes, columns["logical_row_digest"][index].as_py())
            # Guard this path with len(logical) != 32 before applying effects.
            if len(logical) != 32:
                raise CanonicalDataError("logical row digest has an invalid width")
            digest.update(logical)
            minimum = boundary if minimum is None else min(minimum, boundary)
            maximum = boundary if maximum is None else max(maximum, boundary)
            # Assemble row count once so the validate and hash workflow shares one value.
            row_count += 1
    if row_count != parquet.metadata.num_rows:
        raise CanonicalDataError("canonical Parquet row count is inconsistent")
    return _DistributionQa(row_count, ContentDigest(digest.hexdigest()), minimum, maximum)


def _validate_event_for_shard(
    # Keep the event input explicit in the validate event for shard contract.
    event: CanonicalEvent,
    expected_kind: EventKind,
    shard: DatasetShard,
) -> None:
    # Execute the validate event for shard workflow in explicit, reviewable steps.
    position = event.envelope.position
    if event.kind is not expected_kind:
        raise CanonicalDataError("projector returned an unexpected event kind")
    if event.envelope.capability_id != shard.capability_id:
        raise CanonicalDataError("projector returned an event for another capability")
    # Evaluate the complete validate event for shard network id, position schema id and
    # position condition before guarded effects.
    if (
        position.network_id != shard.block_range.network_id
        or position.position_schema_id != shard.block_range.position_schema_id
        or not shard.block_range.contains_block(position.block_ordinal)
    ):
        # Fail the validate event for shard path with CanonicalDataError for projector
        # returned an event outside its shard or network when network id, position schema
        # id and position is true; do not continue ambiguously.
        raise CanonicalDataError("projector returned an event outside its shard or network")


def _int128_bytes(value: int) -> bytes:
    # Execute the int128 bytes workflow in explicit, reviewable steps.
    if not -(1 << 127) <= value < 1 << 127:
        raise OverflowError("canonical integer does not fit signed Int128")
    return value.to_bytes(16, "big", signed=True)


def _manifest_integer(value: object, field: str) -> int:
    # Execute the manifest integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _manifest_optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _manifest_integer(value, field)


# Define block range document as one focused operation with an explicit boundary.
def _block_range_document(value: BlockRange) -> dict[str, object]:
    # Execute the block range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed block range document result without a hidden fallback.
    }


def _shard_document(shard: DatasetShard) -> dict[str, object]:
    # Execute the shard document workflow in explicit, reviewable steps.
    return {
        "block_range": _block_range_document(shard.block_range),
        "capability_id": shard.capability_id.value,
        "columns": list(shard.columns),
        "ordinal": shard.ordinal,
        # Return the completed shard document result without a hidden fallback.
    }


def _distribution_manifest_keys() -> set[str]:
    # Execute the distribution manifest keys workflow in explicit, reviewable steps.
    return {
        "artifact_schema",
        "canonical_schema_id",
        "canonical_schema_version",
        "capability_id",
        # Include created at in the completed distribution manifest keys result.
        "created_at",
        "event_file",
        "event_kind",
        "logical_content_hash",
        "maximum_boundary_ordinal",
        # Include minimum boundary ordinal in the completed distribution manifest keys
        # result.
        "minimum_boundary_ordinal",
        "network_id",
        "position_schema_id",
        "projector_bundle_id",
        "row_count",
        # Include source boundary in the completed distribution manifest keys result.
        "source_boundary",
        "source_contract",
        "writer_bundle_id",
    }


def _canonical_manifest(handle: _LocalHandle, label: str) -> dict[str, object]:
    # Execute the canonical manifest workflow in explicit, reviewable steps.
    with handle.open_binary("manifest.json") as stream:
        payload = stream.read()
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        # Fail the canonical manifest path with CanonicalDataError for is invalid json and
        # label; do not continue ambiguously.
        raise CanonicalDataError(f"{label} is invalid JSON") from error
    if (
        not isinstance(value, dict)
        or not all(isinstance(key, str) for key in value)
        or canonical_json_bytes(value) != payload
        # Evaluate the complete canonical manifest payload, isinstance and value condition
        # before guarded effects.
    ):
        raise CanonicalDataError(f"{label} is not canonical")
    return cast(dict[str, object], value)


def _copy_file(path: Path, destination: IO[bytes]) -> None:
    # Execute the copy file workflow in explicit, reviewable steps.
    with path.open("rb") as source:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


__all__ = [
    "CanonicalDataError",
    "LocalArrowCanonicalStore",
    # Keep the canonical distribution build key component named inside the all contract.
    "canonical_distribution_build_key",
    "canonical_writer_bundle_id",
]
