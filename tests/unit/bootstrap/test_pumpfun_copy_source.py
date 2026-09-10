"""Independent source coverage rejects silent JOIN losses before publication."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

# Shared fixture rows exercise the real reserve, sentinel and terminal-lifecycle validators.
from test_pumpfun_live_source import (
    _TIME_S,
    _block_row,
    _capabilities,
    _evidence_request,
    # Fixtures provide deterministic source keys and bounded typed ranges.
    _key,
    _range,
    _Reader,
    _valid_rows,
)

# This integration slice uses the production publication and verified-reader adapters.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.artifacts.source_inspection import ArtifactSourceInspectionLoader
from backtest.adapters.columnar.arrow.canonical import LocalArrowCanonicalStore
from backtest.adapters.columnar.arrow.parquet_replay import CanonicalParquetReplaySource
from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import PumpfunIndexerV1Query

# The fake reader implements the same streaming source contract as live inspection.
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceBatch

# Tests use pinned installed code so source projection identity is reviewable.
from backtest.application.copy_source import COPYBUY_SOURCE_CONTRACT, CopySourceSelection

# Planning proves the source family; publication separately proves the maximum settlement path.
from backtest.application.dataset_plans import (
    dataset_plan_bytes,
    dataset_plan_from_bytes,
    dataset_spec_document,
    dataset_spec_from_document,
    # Plan and DatasetSpec codecs must preserve the copy schema boundary exactly.
)
from backtest.application.errors import SnapshotValidationError, SnapshotValidationErrorCode
from backtest.application.models import (
    BoundedSourceEvidenceRequest,
    BudgetLimits,
    # Settlement and planning budgets are explicit inputs to source preparation.
    CapabilityStream,
    CopyBuySettlementRequirement,
    DataRequirement,
    DatasetPlanningPolicy,
    PlanDatasetRequest,
    # Hard query limits constrain each bounded proof rather than only final output size.
    QueryLimits,
    RequirementOrigin,
    SourceInspection,
    SourceMetadata,
)

# Inspection fingerprinting and receipt serialization share the production implementation.
from backtest.application.source_fingerprint import source_schema_fingerprint
from backtest.application.source_inspection_document import (
    decode_source_inspection,
    source_inspection_manifest,
    source_inspection_payload,
    # Stored inspection artifacts must round-trip before a planner can consume them.
)
from backtest.application.use_cases.inspect_source import (
    InspectSource,
    InspectSourceRequest,
    _with_generated_evidence,
    # Inspection, planning and preparation remain separate application use cases.
)
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.prepare_dataset import PrepareDataset, PrepareDatasetRequest
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection
from backtest.bootstrap.build_tools import BuildToolBundleRegistry

# The copy source keeps old Sniping fixture semantics while adding independent enumeration.
from backtest.bootstrap.pumpfun_copy_source import (
    PumpfunCopySourceComposition,
    build_pumpfun_copy_source_composition,
)
from backtest.bootstrap.pumpfun_live_source import PumpfunLiveSourceError

# Network coordinates and original signer keys retain their domain types.
from backtest.domain.identifiers import AccountId, CapabilityId
from backtest.domain.time import BlockRange


class CopyReader(_Reader):
    """Emulate fixed query results and permit independent candidate/history fault injection."""

    def __init__(self) -> None:
        super().__init__(_valid_rows())
        self.candidate_rows = self.rows[CapabilityStream.PUMP_CURVE_TRADE]
        # The query selects only candidate mints; the unrelated Mayhem creation is absent.
        self.rows[CapabilityStream.TOKEN_LAUNCH] = self.rows[CapabilityStream.TOKEN_LAUNCH][:1]

    def stream_pumpfun_copybuy_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
        *,
        selection: CopySourceSelection,
        # The fake reader receives typed per-query bounds and exact capability identity.
        capability_id: CapabilityId,
        block_range: BlockRange,
        query: PumpfunIndexerV1Query,
        candidates: bool = False,
    ) -> tuple[SourceBatch, ...]:
        """Candidate results intentionally come from a separate collection from market rows."""
        if not candidates:
            return self.stream_pumpfun_indexer_v1_evidence(
                request, capability_id=capability_id, block_range=block_range, query=query
            )
        # Candidate rows are selected independently of creation history in this fixture too.
        wallets = {wallet.value for wallet in selection.signing_wallets}
        rows = tuple(
            tuple(row[column] for column in query.columns)
            for row in self.candidate_rows
            if block_range.contains_block(cast(int, row["block_ordinal"]))
            # Signer membership and decision containment are both required for candidate
            # enumeration.
            and row["signing_wallet"] in wallets
        )
        return (SourceBatch(capability_id, block_range, query.columns, rows, query.fingerprint),)

    def scan_pumpfun_copybuy(self, request, query, selection):
        """Preparation uses the same complete fixture rows after source inspection."""
        assert request.decision_range == selection.decision_range
        return self.scan_pumpfun_indexer_v1(request, query)


def composition(*, decision_start=12) -> PumpfunCopySourceComposition:
    """The leader buys at block twelve, using exact creation history from block ten."""
    selection = CopySourceSelection(
        (AccountId(_key(51)),),
        _range(decision_start, decision_start + 1),
        _range(10, decision_start + 1),
    )
    # The lookback deliberately includes a creation older than the copied trade.
    return build_pumpfun_copy_source_composition(
        _capabilities(), selection, build_tools=BuildToolBundleRegistry().pin()
    )


def request_for(source: PumpfunCopySourceComposition) -> BoundedSourceEvidenceRequest:
    """Use copy policy and exact projector/selection operands instead of old fixture defaults."""
    return replace(
        _evidence_request(source, source.selection.history_range, source.selection.decision_range),
        projector_digest=source.projector.config_digest,
        copy_selection=source.selection,
        launch_universe_policy_id=source.normalizer.launch_universe_policy_id,
        # Copy selection and universe policy are explicit evidence operands.
    )


def inspect(source: PumpfunCopySourceComposition, reader: CopyReader):
    """Call only the bounded read-only proof boundary; no artifact or success marker is forged."""
    return source.inspect_bounded_evidence(
        cast(ClickHouseSourceReader, reader),
        request_for(source),
        projector_digest=source.projector.config_digest,
    )


def test_copy_evidence_includes_older_creation_and_preserves_inspection_roundtrip() -> None:
    source = composition()
    first, second = inspect(source, CopyReader()), inspect(source, CopyReader())
    assert first == second
    coverage = first[0].copy_coverage
    # Repeated inspection must produce byte-stable eligible occurrence coverage.
    assert coverage is not None and (
        coverage.candidate_occurrences,
        coverage.eligible_occurrences,
    ) == (1, 1)
    # All four streams bind one proof and the independently enumerated older mint.
    assert all(
        receipt.schema == "bounded-source-evidence/v3" and receipt.copy_coverage == coverage
        for receipt in first
    )
    request = request_for(source)
    # Promoted metadata is constructed only from successfully verified generated receipts.
    metadata = SourceMetadata(
        request.source_id,
        request.block_range.network_id,
        request.block_range.position_schema_id,
        "unit-fixture",
        # The fixture advertises no alternate source or inferred extra capabilities.
        (),
        source.metadata_capabilities,
        source.capability_mapping_digest,
        source.query_template_digest,
    )
    # Generated proof promotion keeps the source schema fingerprint reproducible.
    promoted = _with_generated_evidence(metadata, first)
    inspection = SourceInspection(
        promoted, source_schema_fingerprint(promoted), datetime(2026, 9, 1, tzinfo=UTC)
    )
    # Version six must decode exactly; old inspection bytes cannot acquire copy meaning.
    payload, manifest = (
        source_inspection_payload(inspection),
        source_inspection_manifest(inspection),
    )
    assert b'"version":6' in payload and b"source-inspection/v6" in manifest
    # A copy inspection must not decode under the older signerless schema version.
    assert decode_source_inspection(manifest, payload) == inspection
    with pytest.raises(ValueError):
        decode_source_inspection(manifest.replace(b"/v6", b"/v5"), payload)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_creation",
        "missing_candidate",
        # Each fault targets a different obligation of independent source-read reconciliation.
        "changed_candidate",
        "wrong_signer",
        "ambiguous_candidate",
    ],
)
# Every independent-read discrepancy rejects the whole receipt set.
def test_copy_evidence_rejects_incomplete_or_changed_independent_reads(fault: str) -> None:
    # A missing creation must reject the cut rather than remove the candidate mint.
    source, reader = composition(), CopyReader()
    if fault == "missing_creation":
        reader.rows[CapabilityStream.TOKEN_LAUNCH] = ()
    elif fault == "missing_candidate":
        reader.candidate_rows = ()
    # A valid-looking market stream is still invalid when its independent candidate differs.
    else:
        rows = [dict(row) for row in reader.candidate_rows]
        field, value = {
            "changed_candidate": ("fee_payer", _key(99)),
            "wrong_signer": ("signing_wallet", _key(99)),
            # Ambiguous duplicates cannot be accepted just because one payload happens to match.
            "ambiguous_candidate": ("payload_variant_count", 2),
        }[fault]
        rows[-1][field] = value
        reader.candidate_rows = tuple(rows)
    with pytest.raises(PumpfunLiveSourceError):
        # All altered or incomplete reads fail before receipt construction.
        inspect(source, reader)


def test_copy_receipt_cannot_be_reinterpreted_as_old_schema_or_other_wallet() -> None:
    source = composition()
    receipt = inspect(source, CopyReader())[0]
    with pytest.raises(ValueError):
        replace(receipt, schema="bounded-source-evidence/v2")
    # Request operands are checked before reading any rows.
    changed = replace(source.selection, signing_wallets=(AccountId(_key(99)),))
    with pytest.raises(PumpfunLiveSourceError):
        source.inspect_bounded_evidence(
            cast(ClickHouseSourceReader, CopyReader()),
            replace(request_for(source), copy_selection=changed),
            # Changing only wallet selection invalidates an otherwise identical proof request.
            projector_digest=source.projector.config_digest,
        )


class PreparationHarness:
    """All fixture reads enter through the same source ports used in production."""

    def __init__(self, source, reader) -> None:
        self.source, self.reader = source, reader
        self.request = replace(request_for(source), block_range=_range(10, 30))

    def inspect_metadata(self, source_id):
        """Discovery contains UNKNOWN claims; only bounded inspection may promote them."""
        return SourceMetadata(
            source_id,
            self.request.block_range.network_id,
            self.request.block_range.position_schema_id,
            "unit-fixture",
            # The fake endpoint label carries no semantic source evidence.
            (),
            self.source.metadata_capabilities,
            self.source.capability_mapping_digest,
            self.source.query_template_digest,
        )

    def inspect_bounded_evidence(self, request):
        """Every receipt is produced by real normalization and cross-stream checks."""
        return self.source.inspect_bounded_evidence(
            self.reader, request, projector_digest=self.source.projector.config_digest
        )

    def scan(self, request):
        """Source replay never invents canonical events or bypasses the configured projector."""
        return self.source.scan(self.reader, request)


def planned_fixture(tmp_path, *, hold_seconds=4, decision_start=12, initial_transactions=3):
    """Publish a verified inspection and compile a copy-only plan with explicit lookback."""
    source, reader = composition(decision_start=decision_start), CopyReader()
    warmup = decision_start - 10
    # Extra non-Pump transactions exercise the compact global clock before migration.
    rows = reader.rows[CapabilityStream.BLOCK_CLOCK]
    reader.rows[CapabilityStream.BLOCK_CLOCK] = (
        dict(rows[0], transaction_count=initial_transactions),
        *rows[1:],
    )
    # The right tail contains enough real clock boundaries for all four attempts.
    reader.rows[CapabilityStream.BLOCK_CLOCK] += tuple(
        _block_row(block, transactions=3, block_time=_TIME_S + block - 10)
        for block in range(13, 30)
    )
    harness, artifacts = PreparationHarness(source, reader), LocalArtifactRepository(tmp_path)
    # Use the production artifact publisher for the validated inspection prerequisite.
    stored = StoreSourceInspection(
        InspectSource(harness, evidence_reader=harness), artifacts
    ).execute(InspectSourceRequest(harness.request.source_id, harness.request))
    # Exact timing is shared across requirements; no single-round-trip fallback is possible.
    # Both fixture decisions share the exact inspected right frontier at block thirty.
    requirement = CopyBuySettlementRequirement(0, 1, hold_seconds, 1, 29 - decision_start)
    requirements = tuple(
        DataRequirement(
            RequirementOrigin.EXECUTION,
            "copy-test-v1",
            # Every required stream carries the same explicit copy evidence contract.
            item.capability_id,
            (),
            evidence_contracts=(COPYBUY_SOURCE_CONTRACT,),
            warmup_blocks=warmup,
            settlement_requirement=requirement,
            # The maximum path is attached to preparation, not inferred during execution.
        )
        for item in source.metadata_capabilities
    )
    budget, limits = BudgetLimits(10**9, 10**9, 1, 0, 0), QueryLimits(30, 256 * 1024**2, 10_000)
    policy = DatasetPlanningPolicy(budget, limits, 100, 100, 32)
    # The planner reads the committed inspection through the verified artifact loader.
    plan = PlanDataset(ArtifactSourceInspectionLoader(artifacts), policy).execute(
        PlanDatasetRequest(
            harness.request.source_id,
            stored.artifact.artifact_id,
            # Planner input binds immutable chain identity to the exact decision range.
            source.selection.decision_range.network_id,
            source.selection.decision_range.position_schema_id,
            source.selection.decision_range,
            warmup,
            0,
            # Shard and row caps keep the fixture on the ordinary bounded extraction path.
            32,
            1,
            requirements,
            budget,
            limits,
            # All planning costs remain within the explicit local and remote budget.
        )
    )
    # Canonical storage validates the whole snapshot before publishing its root.
    store = LocalArrowCanonicalStore(
        artifacts, memory_limit_mb=256, build_tools=BuildToolBundleRegistry().pin()
    )
    return plan, PrepareDataset(harness, source.projector, store), artifacts, source


def test_copy_plan_and_preparation_publish_exact_local_snapshot(tmp_path) -> None:
    plan, prepare, artifacts, source = planned_fixture(tmp_path)
    assert plan.spec.spec_version == 6
    assert b"backtest.dataset-plan/v5" in dataset_plan_bytes(plan)
    assert dataset_plan_from_bytes(dataset_plan_bytes(plan)) == plan
    # Copy plans and specs retain separate new versions across both codec round trips.
    assert dataset_spec_from_document(dataset_spec_document(plan.spec)) == plan.spec
    # Trade is both signal and settlement stream only under the explicit copy contract.
    assert all(item.block_range.from_block_ordinal == 10 for item in plan.spec.capability_ranges)
    prepared = prepare.execute(PrepareDatasetRequest(plan))
    replay = CanonicalParquetReplaySource(
        artifacts,
        prepared.snapshot_id,
        # The committed reader verifies the pinned projector rather than trusting ID strings.
        expected_projector_bundle_id=source.projector.bundle_id,
        build_tools=BuildToolBundleRegistry().pin(),
    )
    assert replay.dataset_spec == plan.spec
    # The fixture must produce real canonical events, never a marker-only snapshot.
    assert sum(1 for _ in replay.events()) > 20


def test_copy_short_settlement_tail_rejects_snapshot_publication(tmp_path) -> None:
    plan, prepare, _, _ = planned_fixture(tmp_path, hold_seconds=100)
    with pytest.raises(SnapshotValidationError) as raised:
        prepare.execute(PrepareDatasetRequest(plan))
    assert raised.value.reason is SnapshotValidationErrorCode.SETTLEMENT_TAIL_INSUFFICIENT


def test_copy_settlement_and_coverage_tampering_is_rejected(tmp_path) -> None:
    plan, _, _, _ = planned_fixture(tmp_path)
    document = dataset_spec_document(plan.spec)
    document["spec_version"] = 5
    # Downgrading the version cannot erase the signer and four-attempt settlement obligations.
    with pytest.raises(ValueError):
        dataset_spec_from_document(document)
    # Fixed retry semantics cannot be altered even when all old digest strings are retained.
    document = dataset_spec_document(plan.spec)
    document["settlement_requirement"]["maximum_sell_attempts"] = 5
    with pytest.raises(ValueError):
        dataset_spec_from_document(document)


def test_copy_candidate_enumeration_respects_smaller_query_cap() -> None:
    """Candidate reads honor the deployment query cap as well as the full selection bounds."""
    from backtest.adapters.source.clickhouse.query import ClickHouseQueryPolicy
    from backtest.bootstrap.pumpfun_copy_source import _CopyCoverageAccumulator

    selection = CopySourceSelection((AccountId(_key(51)),), _range(10, 13), _range(10, 13))
    source = build_pumpfun_copy_source_composition(
        _capabilities(),
        # A one-block query cap must produce three separately bounded candidate reads.
        selection,
        build_tools=BuildToolBundleRegistry().pin(),
        query_policy=ClickHouseQueryPolicy(evidence_max_block_span=1),
    )
    coverage = _CopyCoverageAccumulator(selection)
    # The fixed query builder rejects an over-wide shard before a fake reader could accept it.
    source._read_candidates(CopyReader(), request_for(source), coverage)
    assert len(coverage.queries) == 3
    assert len(coverage.candidates) == 2
