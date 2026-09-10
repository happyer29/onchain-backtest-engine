"""Verified copy preparation, exact resolution, reference execution and result publication."""

from contextlib import contextmanager
from dataclasses import replace

import pytest
import test_pumpfun_copy_source as source_fixture
import test_sniping_runtime as profile_fixture

# Unit fixtures use the production immutable stores and component/source verifiers.
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.numpy.compiler import LocalNumpyReplayPackCompiler
from backtest.adapters.columnar.numpy.layout import COMPILER_VERSION
from backtest.adapters.control.http import _roundtrip_page, _run_result_summary
from backtest.adapters.replay.factory import LocalReplaySourceFactory
from backtest.adapters.results.market_charts import LocalCopyMarketChartReader

# Production result stores verify immutable manifests and external row digests.
from backtest.adapters.results.parquet import (
    LocalParquetRunOutputStore,
    LocalParquetRunResultReaderFactory,
)

# Both physical input formats feed the same application use case and exact engine.
from backtest.application.copy_run_contract import copy_draft_from_spec
from backtest.application.market_charts import MarketChartQueryError, MarketLifecycle
from backtest.application.run_drafts import PumpfunCopyBuyRunDraft
from backtest.application.run_results import CopySummaryMetadata, RunBackend, RunPhysicalSettings
from backtest.application.run_specs import ReplayInputFormat
from backtest.application.use_cases.prepare_dataset import PrepareDatasetRequest
from backtest.application.use_cases.query_copy_market_chart import QueryCopyMarketChart

# Summary queries reconstruct verified result artifacts after publication.
from backtest.application.use_cases.query_run_results import CopyRunSummaryView, QueryRunResults

# Execution and result projection use the same public application use cases as CLI and API.
from backtest.application.use_cases.run_backtest import (
    RunBacktest,
    RunBacktestRequest,
    RunPreflightError,
)

# Bootstrap remains the only place that instantiates concrete strategies and protocols.
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.copy_run_resolver import (
    CopyRunResolutionError,
    PumpfunCopyBuyRunSpecResolver,
)

# The copy runtime owns independent protocol states and the shared financial reducers.
from backtest.bootstrap.copy_runtime import PumpfunCopyRuntimeResolver
from backtest.bootstrap.runtime_plugins import ReferenceRuntimeComponentsResolver
from backtest.domain.copytrading import CopyBuyPolicy
from backtest.domain.execution import ExecutionMode

# Stable test identities never stand in for operational production source evidence.
from backtest.domain.identifiers import ContentDigest, RuntimeLockId
from backtest.engine import ReferenceBacktestEngine
from backtest.engine.copytrading_results import CopyPositionRecord
from backtest.interfaces.api.market_charts import CopyMarketChartResponse
from backtest.interfaces.api.schemas import CopyRunSummaryResponse, RoundTripPageResponse
from backtest.plugins.protocols.pumpfun.market_charts import pump_market_cap_state


@pytest.mark.parametrize(
    "decision_start, early_virtual_exit", [(10, False), (12, False), (10, True)]
)
def test_copy_verified_parquet_and_replay_publish_equivalent_results(
    # Cover rejected entry, strict exhausted inventory and successful virtual settlement.
    tmp_path,
    decision_start,
    early_virtual_exit,
) -> None:
    # Each scenario prepares a real immutable snapshot from bounded synthetic source fixtures.
    plan, prepare, artifacts, source = source_fixture.planned_fixture(
        tmp_path / "data",
        decision_start=decision_start,
        initial_transactions=4 if early_virtual_exit else 3,
    )
    # Compilation starts only after pre-root clock, coverage and full settlement validation.
    prepared = prepare.execute(PrepareDatasetRequest(plan))
    tools = BuildToolBundleRegistry().pin()
    runtime_lock = RuntimeLockId("7" * 64)

    def canonical(snapshot_id, batch=65_536, readahead=1):
        """The compiler reads only the verified committed snapshot and pinned projector."""
        return CanonicalParquetReplaySource(
            artifacts,
            snapshot_id,
            expected_projector_bundle_id=source.projector.bundle_id,
            build_tools=tools,
            # The compiler has a bounded analytical memory budget and one deterministic worker.
            duckdb_memory_limit_mb=256,
            threads=1,
            # Exercise actual reader controls, independently of attempt provenance hints.
            reader_batch_rows=batch,
            reader_readahead=readahead,
        )

    # ReplayPack derives from the exact canonical snapshot with pinned build tools.
    replay = LocalNumpyReplayPackCompiler(
        artifacts,
        canonical,
        runtime_lock_id=runtime_lock,
        # The compiler pins the same build tools used by the canonical reader.
        build_tools=tools,
    ).compile(prepared.snapshot_id, COMPILER_VERSION)
    # The run keeps the existing explicit account and network profiles.
    profiles = profile_fixture._draft()
    # Explicit profiles prevent a changed environment default from altering test semantics.
    draft = PumpfunCopyBuyRunDraft(
        prepared.dataset_revision_id,
        prepared.snapshot_id,
        None,
        source.selection.signing_wallets,
        # Policy is no larger than the exact four-attempt path proven by preparation.
        1_000_000_000,
        CopyBuyPolicy(100_000_000, 2000, 1 if early_virtual_exit else 1000, 4, 0, 1, 1, 100, 100),
        ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT
        if early_virtual_exit
        else profiles.execution_mode,
        # Financial profiles remain explicit even when only an exit trigger changes.
        profiles.wallet_account_profile,
        profiles.pump_fee_profile,
        profiles.buy_solana_fee_profile,
        profiles.sell_solana_fee_profile,
        7,
        # Seed and profiles are canonical draft inputs rather than process defaults.
    )
    resolver = PumpfunCopyBuyRunSpecResolver(
        artifacts,
        runtime_lock,
        parquet_memory_limit_mb=256,
        # Resolution verifies the snapshot against the exact source projector bundle.
        threads=1,
        expected_projector_bundle_id=source.projector.bundle_id,
        build_tools=tools,
    )
    specs = (
        # Logical run identity must be independent of the optional compiled input format.
        resolver.resolve(draft),
        resolver.resolve(replace(draft, replay_pack_id=replay.replay_pack_id)),
    )
    assert specs[0].logical_run_id == specs[1].logical_run_id
    assert copy_draft_from_spec(specs[0]) == draft
    # Changed source coverage or longer timing must fail before any engine mutation.
    with pytest.raises(CopyRunResolutionError):
        resolver.resolve(replace(draft, policy=replace(draft.policy, maximum_hold_seconds=5)))

    # The runner uses production source verification, core execution and immutable output
    # publication.
    class PhysicalSourceFactory(LocalReplaySourceFactory):
        """Vary the concrete reader at the existing replaceable source seam."""

        batch, readahead = 2, 1

        @contextmanager
        def open_resolved(self, spec):
            """Only canonical readers have physical batch/readahead controls in this oracle."""
            if spec.replay_input.format is ReplayInputFormat.CANONICAL_PARQUET:
                yield canonical(spec.snapshot_id, self.batch, self.readahead)
                return
            # ReplayPack keeps the production mmap reader and exact verification path.
            with super().open_resolved(spec) as replay_source:
                yield replay_source

    # Independent attempts reuse only the source factory, never wallet or protocol state.
    physical_source = PhysicalSourceFactory(
        artifacts,
        parquet_memory_limit_mb=256,
        expected_projector_bundle_id=source.projector.bundle_id,
        # The source factory cannot resolve an unpinned projector from a newer checkout.
        build_tools=tools,
    )
    # The same source factory is reused in another order to detect leaked runtime state.
    runner = RunBacktest(
        physical_source,
        ReferenceRuntimeComponentsResolver(runtime_lock),
        ReferenceBacktestEngine(),
        # The ordinary durable publication protocol writes bounded external result tables.
        LocalParquetRunOutputStore(artifacts, tmp_path / "outputs"),
        copy_components=PumpfunCopyRuntimeResolver(runtime_lock),
        required_threads=1,
    )
    readers = LocalParquetRunResultReaderFactory(artifacts)
    # Collect normalized result rows separately from physical attempt provenance.
    results, rows = [], []
    for index, spec in enumerate((*specs, specs[0])):
        physical_source.batch, physical_source.readahead = (2, 1) if index == 0 else (65_536, 2)
        # Attempt hints stay distinct from the actual concrete-reader settings tested above.
        physical = RunPhysicalSettings(RunBackend.REFERENCE_PUMPFUN_COPY_BUY, 2 + index, 1, 1, 1)
        result = runner.execute(
            RunBacktestRequest(spec, ContentDigest(str(index + 1) * 64), physical)
            # Each attempt gets a distinct nonce while preserving its semantic specification.
        )
        results.append(result)
        # A terminal historical migration rejects the own buy after the whole group is observed.
        with readers.open_exact(result.artifact.artifact_id) as reader:
            reader.verify()
            summary = reader.manifest.bounded_summary
            assert isinstance(summary, CopySummaryMetadata)
            assert summary.totals.position_count == 1
            # A migration already observed at the decision boundary must reject the entry for free.
            if decision_start == 12:
                assert summary.totals.rejected_buy_count == 1
                assert (
                    summary.totals.quote_cashflow_atomic
                    == summary.totals.network_base_fee_paid_atomic
                    # A rejected entry has no network fee or wallet cash movement.
                    == 0
                )
            elif early_virtual_exit:
                # A pre-migration virtual close must expose its actual synthetic funding.
                assert summary.totals.closed_position_count == 1
                assert summary.totals.synthetic_funded_sell_atomic > 0
                assert summary.totals.account_deposit_refunded_atomic > 0
            else:
                # Entry fills before migration; timeout consumes four free quote rejections.
                assert (
                    summary.totals.filled_buy_count == summary.totals.exhausted_position_count == 1
                )
                assert summary.totals.rejected_sell_count == 4
                assert summary.totals.quote_cashflow_atomic < 0
                # A landed entry pays its network fee even if all later sale quotes are rejected.
                assert summary.totals.network_base_fee_paid_atomic == 5000
            page = reader.roundtrips(after=None, limit=1)
            assert len(page.items) == 1 and isinstance(page.items[0], CopyPositionRecord)
            rows.append(page.items[0].document())
        # The shared query/API/delegated-client path preserves exact integer result meaning.
        # API and delegated-client codecs must preserve the exact domain summary.
        view = QueryRunResults(readers).summary(result.artifact.artifact_id)
        assert isinstance(view, CopyRunSummaryView)
        response = CopyRunSummaryResponse.from_domain(view).model_dump(mode="json")
        assert _run_result_summary(response) == view
        page_response = RoundTripPageResponse.from_domain(page).model_dump(mode="json")
        # Position paging must also preserve every integer and nullable result field.
        assert _roundtrip_page(page_response, after=None, limit=1) == page
        # Historical charts reopen the pinned canonical snapshot even for a ReplayPack run.
        chart_reader = LocalCopyMarketChartReader(artifacts, pump_market_cap_state, tools)
        query = QueryCopyMarketChart(readers, chart_reader)
        position = page.items[0]
        assert isinstance(position, CopyPositionRecord)
        # The requested row binds history to the same run even across alternate input formats.
        chart = query.execute(
            result.artifact.artifact_id,
            position.roundtrip_id,
            position.target_position.boundary_ordinal,
        )
        # Whole-transaction terminal normalization must leave no active state at migration.
        assert chart.snapshot_id == prepared.snapshot_id
        assert chart.asset_id == position.intent.asset_id
        assert chart.points[-1].lifecycle is MarketLifecycle.MIGRATED
        assert len(chart.markers) == len(position.attempts) + 1
        _assert_chart_attempts(chart, position)
        # The wire format preserves wide amounts and original outcome distinctions.
        chart_document = CopyMarketChartResponse.from_domain(chart).model_dump(mode="json")
        assert chart_document["points"][0]["market_cap_atomic"] == str(
            chart.points[0].market_cap_atomic
        )
        # A valid digest from another position cannot select this row by boundary alone.
        with pytest.raises(MarketChartQueryError, match="COPY_POSITION_NOT_FOUND"):
            query.execute(
                result.artifact.artifact_id,
                ContentDigest("f" * 64),
                position.target_position.boundary_ordinal,
                # A correct boundary with another position digest must still reject.
            )
        # Concurrent reads reject before opening another canonical stream and release admission.
        with (
            chart_reader._admission,
            pytest.raises(MarketChartQueryError, match="MARKET_CHART_BUSY"),
        ):
            # Single-flight admission applies to the complete verified history read.
            query.execute(
                result.artifact.artifact_id,
                position.roundtrip_id,
                position.target_position.boundary_ordinal,
            )
    # Physical format/batch/attempt provenance cannot alter normalized results or signal identity.
    assert len({result.canonical_result_hash for result in results}) == 1
    assert all(result.comparison == results[0].comparison for result in results)
    assert rows[0] == rows[1] == rows[2]

    class WrongWalletRuntime(PumpfunCopyRuntimeResolver):
        """Forge an instance while retaining valid receipts to exercise actual-instance checks."""

        def resolve(self, spec):
            runtime = super().resolve(spec)
            # The existing genuine wallet is valid, but this empty selection violates its receipt.
            runtime.strategy._wallets = frozenset()
            return runtime

    runner._copy_components = WrongWalletRuntime(runtime_lock)
    # Preflight must reject the altered signer set before opening an output publication attempt.
    with pytest.raises(RunPreflightError, match="strategy instance"):
        runner.execute(RunBacktestRequest(specs[0], ContentDigest("f" * 64), physical))


def _assert_chart_attempts(chart, position) -> None:
    """Independent record assertions keep rejected decisions separate from landed orders."""
    signal = chart.markers[0]
    assert signal.kind == "SIGNAL" and signal.status == "OBSERVED_SOURCE"
    assert signal.point.position == replace(position.target_position, event_index=None)
    # Every attempt retains its actual coordinate and its original failure, when present.
    for marker, attempt in zip(chart.markers[1:], position.attempts, strict=True):
        assert marker.point.position == replace(
            attempt.landed_at or attempt.decision, event_index=None
        )
        assert marker.status == attempt.status.value
        assert marker.failure_code == attempt.failure_code
        assert marker.attempt == attempt.number
        # The market-cap ordinate is the historical as-of value, not the own fill quote.
        prior = [
            p
            for p in chart.points
            if p.position.boundary_ordinal <= marker.point.position.boundary_ordinal
        ]
        assert marker.point.market_cap_atomic == prior[-1].market_cap_atomic
        if marker.status == "FILLED":
            assert marker.point.lifecycle is MarketLifecycle.ACTIVE
