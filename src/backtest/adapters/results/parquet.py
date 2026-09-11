"""Bounded Parquet output buffers and successful Run artifact publication."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import OrderedDict
from collections.abc import Callable, Iterator

# Import contextlib at the visible module dependency boundary.
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from threading import Lock
from typing import IO, Any, cast

import pyarrow as pa

# Parquet serialization remains outside core execution and uses bounded output buffers.
import pyarrow.parquet as pq

from backtest.adapters.results.analytics import bounded_entry_records
from backtest.adapters.results.copy_reconciliation import CopyLedgerReconciler
from backtest.application.copy_result_codec import copy_position_from_document

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.ports.artifacts import (
    ArtifactHandle,
    ArtifactRepository,
    ArtifactWriter,
    # Close the artifacts import after its required symbols are visible.
)
from backtest.application.ports.run_results import (
    RoundTripCursor,
    RoundTripPage,
    VerifiedRunResultReader,
    # Close the run results import after its required symbols are visible.
)
from backtest.application.run_results import (
    MAX_COMPARISON_LABEL_LENGTH,
    MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
    CopySummaryMetadata,
    # Sniping metadata retains its original summary validation independently of copy totals.
    PumpfunSnipingSummaryMetadata,
    # Copy summaries are a separate bounded family under the common immutable manifest.
    RunBackend,
    # Include run physical settings so the run results dependency remains explicit.
    RunPhysicalSettings,
    RunResultTableRole,
    SuccessfulRunManifest,
    successful_run_manifest_from_bytes,
    validate_final_balances,
    # Close the run results import after its required symbols are visible.
)
from backtest.application.run_specs import ResolvedRunSpec
from backtest.domain.account_requirements import (
    AccountReleasePolicy,
    AccountRequirementScope,
)
from backtest.domain.execution import Fill
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    ContentDigest,
    ExecutionAttemptId,
)

# Import ledger at the visible module dependency boundary.
from backtest.domain.ledger import AccountKind, LedgerCorrelationKind, LedgerTransaction
from backtest.domain.roundtrips import (
    ROUNDTRIP_RESULT_SCHEMA_V3,
    ROUNDTRIP_RESULT_SCHEMA_V4,
    MtmStatus,
    RoundTripRecord,
    RoundTripStatus,
    # Include roundtrip record from document so the roundtrips dependency remains
    # explicit.
    roundtrip_record_from_document,
    validate_roundtrip_record_v4,
)
from backtest.engine.audit import (
    CanonicalStreamHasher,
    fill_document,
    # Include ledger document so the audit dependency remains explicit.
    ledger_document,
)
from backtest.engine.copytrading_results import (
    COPY_AUDIT_STREAM,
    COPY_BALANCE_STREAM,
    # Copy streams retain distinct canonical framing for fills, ledger and position rows.
    COPY_FILL_STREAM,
    COPY_LEDGER_STREAM,
    COPY_POSITION_SCHEMA,
    COPY_POSITION_STREAM,
    CopyPositionRecord,
    # Scalar copy totals are recomputed during verified columnar reads.
)
from backtest.engine.copytrading_run import CopyTotalsAccumulator
from backtest.engine.sniping_contracts import synthetic_liquidity_account_id


class RunOutputIntegrityError(RuntimeError):
    """Buffered outputs do not match the engine's canonical summary."""


# Keep source-account identity beside its exact positive debit magnitude.
_SettlementFundingPosting = tuple[AccountId, AssetId, int]

# A fixed stripe set bounds synchronization state while separating unrelated cold runs.
_SEMANTIC_VERIFICATION_LOCK_STRIPES = 64
# At most this many sparse row-group checkpoints are retained per cached Run.
_MAX_ROUNDTRIP_PAGE_CHECKPOINTS = 1_024

type _RoundTripKey = tuple[int, str]
type _RoundTripPageIndex = tuple[tuple[int, _RoundTripKey], ...]


_NO_LEDGER_ROUNDTRIP_STATUSES = frozenset(
    {
        RoundTripStatus.COOLDOWN_SKIPPED,
        RoundTripStatus.BUY_REFERENCE_REJECTED,
        RoundTripStatus.BUY_PRE_SUBMIT_INSUFFICIENT_FUNDS,
        # Close the cooldown skipped and buy reference rejected payload only after all module
        # fields are present.
    }
)


class _SnipingLedgerReconciler:
    """Join bounded round-trip financial projections to committed ledger rows."""

    def __init__(self) -> None:
        # Execute the sniping ledger reconciler init workflow in explicit, reviewable
        # steps.
        self._unmatched_cashflows: dict[ContentDigest, dict[AssetId, int]] = {}
        self._roundtrip_ids: set[ContentDigest] = set()
        self._realized_cash_pnl_atomic = 0
        self._valued_economic_pnl_atomic = 0
        self._unvalued_open_position_count = 0
        # Assemble self cashback receivable atomic once so the sniping ledger reconciler
        # init workflow shares one value.
        self._cashback_receivable_atomic = 0
        self._unmatched_venue_funding: dict[ContentDigest, list[_SettlementFundingPosting]] = {}
        self._unmatched_synthetic_funding: dict[ContentDigest, list[_SettlementFundingPosting]] = {}
        self._filled_sell_count = 0
        self._real_liquidity_sufficient_filled_sell_count = 0
        self._synthetic_liquidity_used_sell_count = 0
        # Funding amount totals reconcile rows, summary metadata, and ledger sources.
        self._gross_sell_settlement_atomic = 0
        self._venue_funded_sell_atomic = 0
        self._synthetic_funded_sell_atomic = 0

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        # Execute the sniping ledger reconciler append ledger workflow in explicit,
        # reviewable steps.
        if transaction.correlation_kind is not LedgerCorrelationKind.ROUNDTRIP:
            raise RunOutputIntegrityError("sniping ledger row is not ROUNDTRIP-correlated")
        if transaction.correlation_id in self._roundtrip_ids:
            raise RunOutputIntegrityError("sniping ledger row follows its terminal round trip")
        amounts = self._unmatched_cashflows.setdefault(transaction.correlation_id, {})
        # Traverse transaction.postings explicitly so each sniping ledger reconciler
        # append ledger iteration remains traceable.
        for posting in transaction.postings:
            # Process transaction.postings inside the bounded sniping ledger reconciler
            # append ledger loop.
            if posting.account.kind is AccountKind.VENUE and posting.amount_atomic < 0:
                funding = self._unmatched_venue_funding.setdefault(
                    transaction.correlation_id,
                    [],
                )
                funding.append(
                    (posting.account.account_id, posting.asset_id, -posting.amount_atomic)
                )
            if (
                posting.account.kind is AccountKind.EXTERNAL
                and posting.account.account_id.value.startswith("synthetic-liquidity:")
            ):
                self._append_synthetic_funding(
                    transaction,
                    posting.account.account_id,
                    posting.asset_id,
                    posting.amount_atomic,
                )
            if posting.account.kind not in (
                AccountKind.PORTFOLIO_AVAILABLE,
                AccountKind.PORTFOLIO_RESERVED,
            ):
                continue
            # Assemble amounts[posting asset id] once so the sniping ledger reconciler
            # append ledger workflow shares one value.
            amounts[posting.asset_id] = amounts.get(posting.asset_id, 0) + posting.amount_atomic

    def _append_synthetic_funding(
        self,
        transaction: LedgerTransaction,
        account_id: AccountId,
        asset_id: AssetId,
        amount_atomic: int,
    ) -> None:
        """Collect only the versioned synthetic sell source debit."""

        if transaction.reason != "SNIPING_SELL_FILLED_ACCOUNT_CLOSED" or amount_atomic >= 0:
            raise RunOutputIntegrityError("synthetic liquidity posting has invalid semantics")
        postings = self._unmatched_synthetic_funding.setdefault(transaction.correlation_id, [])
        if any(item[0] == account_id and item[1] == asset_id for item in postings):
            raise RunOutputIntegrityError("synthetic liquidity source is duplicated")
        postings.append((account_id, asset_id, -amount_atomic))

    def append_roundtrip(self, record: RoundTripRecord) -> None:
        # Execute the sniping ledger reconciler append roundtrip workflow in explicit,
        # reviewable steps.
        if record.roundtrip_id in self._roundtrip_ids:
            raise RunOutputIntegrityError("round-trip correlation ID is duplicated")
        has_ledger = record.roundtrip_id in self._unmatched_cashflows
        cashflows = self._unmatched_cashflows.pop(record.roundtrip_id, {})
        venue_funding = self._unmatched_venue_funding.pop(record.roundtrip_id, [])
        synthetic_funding = self._unmatched_synthetic_funding.pop(record.roundtrip_id, [])
        requires_ledger = record.status not in _NO_LEDGER_ROUNDTRIP_STATUSES
        # Guard this path with has_ledger != requires_ledger before applying effects.
        if has_ledger != requires_ledger:
            raise RunOutputIntegrityError("round trip and correlated ledger presence differ")
        if requires_ledger and not cashflows:
            raise RunOutputIntegrityError("correlated ledger has no portfolio cash postings")
        quote_cashflow = cashflows.get(record.quote_asset_id, 0)
        self._verify_settlement_funding(record, venue_funding, synthetic_funding)
        # Invoke _verify_financial_projection for record and quote cashflow as a visible
        # sniping ledger reconciler append roundtrip step.
        self._verify_financial_projection(record, quote_cashflow)
        self._roundtrip_ids.add(record.roundtrip_id)
        self._realized_cash_pnl_atomic += record.realized_cash_pnl_atomic or 0
        self._valued_economic_pnl_atomic += record.economic_pnl_atomic or 0
        self._unvalued_open_position_count += (
            # Keep the record component named inside the self unvalued open position count
            # contract.
            record.acquired_token_amount_atomic > 0
            and record.status is not RoundTripStatus.CLOSED
            and record.economic_pnl_atomic is None
        )
        self._cashback_receivable_atomic += record.cashback_receivable_atomic
        if record.status is RoundTripStatus.CLOSED:
            self._append_sell_settlement(record)

    @staticmethod
    def _verify_settlement_funding(
        record: RoundTripRecord,
        venue_funding: list[_SettlementFundingPosting],
        synthetic_funding: list[_SettlementFundingPosting],
    ) -> None:
        """Require exact quote-asset funding accounts and debit magnitudes."""

        # Buy-side venue token debits are unrelated to sell-side quote funding.
        quote_venue_funding = [item for item in venue_funding if item[1] == record.quote_asset_id]
        expected_venue = []
        if record.settled_venue_funded_atomic:
            expected_venue = [
                (
                    AccountId(f"venue:{record.venue_id.value}"),
                    record.quote_asset_id,
                    record.settled_venue_funded_atomic,
                )
            ]

        # Synthetic funding is protocol-scoped and cannot use another asset or account.
        expected_synthetic = []
        if record.settled_synthetic_funded_atomic:
            expected_synthetic = [
                (
                    synthetic_liquidity_account_id(
                        protocol_namespace="pumpfun",
                        network_id=record.network_id,
                        venue_id=record.venue_id,
                    ),
                    record.quote_asset_id,
                    record.settled_synthetic_funded_atomic,
                )
            ]
        if synthetic_funding != expected_synthetic:
            raise RunOutputIntegrityError("synthetic ledger funding differs from round-trip row")
        if quote_venue_funding != expected_venue:
            raise RunOutputIntegrityError("venue ledger funding differs from round-trip row")

    def _append_sell_settlement(self, record: RoundTripRecord) -> None:
        """Aggregate the exact v4 funding classification for one successful sell."""

        self._filled_sell_count += 1
        used_synthetic = record.settled_synthetic_funded_atomic > 0
        self._synthetic_liquidity_used_sell_count += used_synthetic
        self._real_liquidity_sufficient_filled_sell_count += not used_synthetic
        # Aggregate exact gross funding independently from net portfolio proceeds.
        self._venue_funded_sell_atomic += record.settled_venue_funded_atomic
        self._synthetic_funded_sell_atomic += record.settled_synthetic_funded_atomic
        self._gross_sell_settlement_atomic += (
            record.settled_venue_funded_atomic + record.settled_synthetic_funded_atomic
        )

    # Define sniping ledger reconciler verify summary as one focused operation with an
    # explicit boundary.
    def verify_summary(self, summary: PumpfunSnipingSummaryMetadata) -> None:
        # Execute the sniping ledger reconciler verify summary workflow in explicit,
        # reviewable steps.
        if self._unmatched_cashflows:
            raise RunOutputIntegrityError("sniping ledger contains orphan correlations")
        if self._unmatched_venue_funding:
            raise RunOutputIntegrityError("sniping ledger contains orphan venue funding")
        if self._unmatched_synthetic_funding:
            raise RunOutputIntegrityError("sniping ledger contains orphan synthetic funding")
        if summary.realized_cash_pnl_atomic != self._realized_cash_pnl_atomic:
            raise RunOutputIntegrityError("round-trip realized PnL differs from run summary")
        if summary.valued_economic_pnl_subtotal_atomic != self._valued_economic_pnl_atomic:
            # Fail the sniping ledger reconciler verify summary path with
            # RunOutputIntegrityError for round-trip economic pn l differs from run
            # summary when valued economic pnl subtotal atomic, valued economic pnl atomic
            # and summary is true; do not continue ambiguously.
            raise RunOutputIntegrityError("round-trip economic PnL differs from run summary")
        if summary.unvalued_open_position_count != self._unvalued_open_position_count:
            raise RunOutputIntegrityError("round-trip valuation completeness differs from summary")
        expected_economic = (
            None if self._unvalued_open_position_count else self._valued_economic_pnl_atomic
            # Complete the expected economic group only after its semantic components are
            # visible.
        )
        if summary.economic_pnl_atomic != expected_economic:
            raise RunOutputIntegrityError("full economic PnL differs from round-trip rows")
        if summary.cashback_receivable_atomic != self._cashback_receivable_atomic:
            raise RunOutputIntegrityError("cashback receivable differs from round-trip rows")
        settlement_values = (
            (summary.filled_sell_count, self._filled_sell_count),
            (
                summary.real_liquidity_sufficient_filled_sell_count,
                self._real_liquidity_sufficient_filled_sell_count,
            ),
            (
                summary.synthetic_liquidity_used_sell_count,
                self._synthetic_liquidity_used_sell_count,
            ),
            (summary.gross_sell_settlement_atomic, self._gross_sell_settlement_atomic),
            (summary.venue_funded_sell_atomic, self._venue_funded_sell_atomic),
            (summary.synthetic_funded_sell_atomic, self._synthetic_funded_sell_atomic),
        )
        if any(actual != expected for actual, expected in settlement_values):
            raise RunOutputIntegrityError("sell liquidity totals differ from round-trip rows")

    # Apply staticmethod semantics to the following sniping ledger reconciler verify
    # financial projection contract.
    @staticmethod
    def _verify_financial_projection(record: RoundTripRecord, quote_cashflow: int) -> None:
        # Execute the sniping ledger reconciler verify financial projection workflow in
        # explicit, reviewable steps.
        is_open = (
            record.acquired_token_amount_atomic > 0 and record.status is not RoundTripStatus.CLOSED
        )
        if is_open:
            # Handle the sniping ledger reconciler verify financial projection is_open
            # branch as a distinct logical block.
            if record.realized_cash_pnl_atomic is not None:
                raise RunOutputIntegrityError("open round trip cannot publish realized cash PnL")
            if record.mtm_status is MtmStatus.NOT_APPLICABLE:
                raise RunOutputIntegrityError("open round trip requires an explicit MTM status")
        # Handle the sniping ledger reconciler verify financial projection complement of
        # is_open explicitly.
        elif (
            record.realized_cash_pnl_atomic != quote_cashflow
            or record.mtm_status is not MtmStatus.NOT_APPLICABLE
        ):
            raise RunOutputIntegrityError("realized cash PnL differs from correlated ledger")

        # Evaluate the complete sniping ledger reconciler verify financial projection mtm
        # status, record and executable condition before guarded effects.
        if record.mtm_status in {MtmStatus.EXECUTABLE, MtmStatus.STALE_PRE_MIGRATION}:
            # Handle the sniping ledger reconciler verify financial projection mtm status,
            # record and executable condition as a distinct block.
            if (
                record.mtm_liquidation_value_atomic is None
                or record.mtm_cash_pnl_atomic
                != quote_cashflow + record.mtm_liquidation_value_atomic
            ):
                # Fail the sniping ledger reconciler verify financial projection path with
                # RunOutputIntegrityError for mtm cash pn l differs from correlated ledger
                # when mtm liquidation value atomic, mtm cash pnl atomic and record is
                # true; do not continue ambiguously.
                raise RunOutputIntegrityError("MTM cash PnL differs from correlated ledger")
        # Handle the sniping ledger reconciler verify financial projection complement of
        # mtm status, record and executable explicitly.
        elif record.mtm_status is MtmStatus.UNAVAILABLE and any(
            value is not None
            for value in (
                record.mtm_liquidation_value_atomic,
                record.mtm_cash_pnl_atomic,
                # Pass record explicitly so any receives a reviewable mtm liquidation
                # value atomic and mtm cash pnl atomic input in sniping ledger reconciler
                # verify financial projection.
                record.economic_pnl_atomic,
            )
        ):
            raise RunOutputIntegrityError("unavailable MTM cannot publish valuation amounts")

        pnl_before_cashback = (
            # Keep the record component named inside the pnl before cashback contract.
            record.mtm_cash_pnl_atomic if is_open else record.realized_cash_pnl_atomic
        )
        run_locked_quote_value = sum(
            component.locked_delta_atomic
            for component in record.account_components
            if component.asset_id == record.quote_asset_id
            and component.scope is AccountRequirementScope.WALLET
            and component.release_policy is AccountReleasePolicy.RUN_LOCKED
        )
        if pnl_before_cashback is not None and record.economic_pnl_atomic != (
            pnl_before_cashback + record.cashback_receivable_atomic + run_locked_quote_value
        ):
            # Fail the sniping ledger reconciler verify financial projection path with
            # RunOutputIntegrityError for economic pn l differs from ledger pn l plus
            # cashback when pnl before cashback, economic pnl atomic and record is true;
            # do not continue ambiguously.
            raise RunOutputIntegrityError("economic PnL differs from ledger PnL plus cashback")


# Keep the local parquet run output store contract and validation rules together.
class LocalParquetRunOutputStore:
    def __init__(
        self,
        artifacts: ArtifactRepository,
        work_root: Path,
        # Close the init signature after its explicit inputs.
        *,
        compression: str = "zstd",
    ) -> None:
        # Execute the local parquet run output store init workflow in explicit, reviewable
        # steps.
        if not compression or compression != compression.strip():
            raise ValueError("Parquet compression must be non-empty and trimmed")
        self._artifacts = artifacts
        self._work_root = work_root.resolve()
        self._compression = compression
        # Invoke mkdir as a visible step within the local parquet run output store init
        # workflow.
        self._work_root.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        *,
        spec: ResolvedRunSpec,
        # Keep the execution attempt id input explicit in the start contract.
        execution_attempt_id: ExecutionAttemptId,
        physical_settings: RunPhysicalSettings,
    ) -> _LocalParquetRunOutputSession:
        # Execute the local parquet run output store start workflow in explicit,
        # reviewable steps.
        root = Path(tempfile.mkdtemp(prefix="run-output-", dir=self._work_root))
        return _LocalParquetRunOutputSession(
            self._artifacts,
            root,
            spec,
            # Pass execution attempt id explicitly so _LocalParquetRunOutputSession
            # receives a reviewable artifacts and compression input in local parquet run
            # output store start.
            execution_attempt_id,
            physical_settings,
            compression=self._compression,
        )


class LocalParquetRunResultReaderFactory:
    """Open only exact committed Run artifacts through fixed payload names."""

    def __init__(
        self,
        artifacts: ArtifactRepository,
        *,
        semantic_cache_entries: int = 64,
    ) -> None:
        if (
            isinstance(semantic_cache_entries, bool)
            or not isinstance(semantic_cache_entries, int)
            # A zero-sized cache would violate the configured bounded reuse contract.
            or semantic_cache_entries < 1
        ):
            # Refuse silent cache disablement so performance behavior stays explicit.
            raise ValueError("semantic_cache_entries must be a positive integer")
        self._artifacts = artifacts
        self._semantic_cache_entries = semantic_cache_entries
        # Each LRU value is a bounded sparse seek index proven by the full table scan.
        self._semantically_verified: OrderedDict[
            str,
            _RoundTripPageIndex | None,
        ] = OrderedDict()
        self._semantic_cache_lock = Lock()
        # A fixed stripe set bounds locks and permits unrelated cold scans to overlap.
        self._semantic_verification_locks = tuple(
            Lock() for _ in range(_SEMANTIC_VERIFICATION_LOCK_STRIPES)
        )

    def _is_semantically_verified(self, artifact_id: ArtifactId) -> bool:
        with self._semantic_cache_lock:
            if artifact_id.hex not in self._semantically_verified:
                return False
            self._semantically_verified.move_to_end(artifact_id.hex)
            return True

    def _roundtrip_page_index(self, artifact_id: ArtifactId) -> _RoundTripPageIndex | None:
        """Return seek evidence only while the exact semantic LRU entry exists."""

        with self._semantic_cache_lock:
            if artifact_id.hex not in self._semantically_verified:
                return None
            index = self._semantically_verified[artifact_id.hex]
            self._semantically_verified.move_to_end(artifact_id.hex)
            return index

    def _mark_semantically_verified(
        self,
        artifact_id: ArtifactId,
        page_index: _RoundTripPageIndex | None = None,
    ) -> None:
        with self._semantic_cache_lock:
            self._semantically_verified[artifact_id.hex] = page_index
            self._semantically_verified.move_to_end(artifact_id.hex)
            while len(self._semantically_verified) > self._semantic_cache_entries:
                self._semantically_verified.popitem(last=False)

    def _semantic_verification_lock_for(self, artifact_id: ArtifactId) -> Lock:
        """Choose one stable bounded lock from the exact content identifier."""

        stripe = int(artifact_id.hex, 16) % len(self._semantic_verification_locks)
        # Hash collisions only serialize unrelated validation; they cannot share evidence.
        return self._semantic_verification_locks[stripe]

    @contextmanager
    def open_exact(self, artifact_id: ArtifactId) -> Iterator[VerifiedRunResultReader]:
        # Execute the local parquet run result reader factory open exact workflow in
        # explicit, reviewable steps.
        handle = self._artifacts.open_committed(artifact_id)
        try:
            yield _LocalParquetRunResultReader(
                handle,
                semantic_verified=self._is_semantically_verified(artifact_id),
                semantic_verified_probe=lambda: self._is_semantically_verified(artifact_id),
                roundtrip_page_index=self._roundtrip_page_index(artifact_id),
                roundtrip_page_index_probe=lambda: self._roundtrip_page_index(artifact_id),
                # Mark only after both canonical result tables verify successfully.
                semantic_verified_callback=(
                    lambda page_index: self._mark_semantically_verified(artifact_id, page_index)
                ),
                semantic_verification_lock=self._semantic_verification_lock_for(artifact_id),
            )
        finally:
            handle.close()


# Keep the local parquet run result reader contract and validation rules together.
class _LocalParquetRunResultReader:
    def entry_records(
        self,
    ) -> AbstractContextManager[Iterator[RoundTripRecord | CopyPositionRecord | dict[str, object]]]:
        """Supplemental analytics uses the same exact leased result authority."""
        return bounded_entry_records(self._handle, self._manifest, self.verify)

    def __init__(
        self,
        handle: ArtifactHandle,
        *,
        semantic_verified: bool = False,
        semantic_verified_probe: Callable[[], bool] | None = None,
        roundtrip_page_index: _RoundTripPageIndex | None = None,
        roundtrip_page_index_probe: Callable[[], _RoundTripPageIndex | None] | None = None,
        # Optional callbacks keep this reader usable in focused uncached tests.
        semantic_verified_callback: Callable[[_RoundTripPageIndex | None], None] | None = None,
        semantic_verification_lock: Lock | None = None,
    ) -> None:
        # Execute the local parquet run result reader init workflow in explicit,
        # reviewable steps.
        self._handle = handle
        if handle.descriptor.kind is not ArtifactKind.RUN:
            raise RunOutputIntegrityError("artifact is not a successful Run")
        with handle.open_binary("manifest.json") as stream:
            payload = _read_bounded(stream, MAX_SUCCESSFUL_RUN_MANIFEST_BYTES)
        # Assemble self manifest once so the local parquet run result reader init workflow
        # shares one value.
        self._manifest = successful_run_manifest_from_bytes(payload)
        if handle.descriptor.input_artifact_ids != self._manifest.input_artifact_ids:
            raise RunOutputIntegrityError("Run descriptor closure differs from its manifest")
        self._balances_verified = semantic_verified
        self._roundtrips_verified = semantic_verified
        self._semantic_verified_probe = semantic_verified_probe
        self._roundtrip_page_index = roundtrip_page_index
        self._roundtrip_page_index_probe = roundtrip_page_index_probe
        self._semantic_verified_callback = semantic_verified_callback
        # The factory supplies the stable lock selected for this exact artifact ID.
        self._semantic_verification_lock = semantic_verification_lock

    # Apply property semantics to the following local parquet run result reader manifest
    # contract.
    @property
    def manifest(self) -> SuccessfulRunManifest:
        return self._manifest

    def verify(self) -> None:
        # Execute the local parquet run result reader verify workflow in explicit,
        # reviewable steps.
        if self._is_semantically_verified():
            return
        lock = self._semantic_verification_lock
        # Standalone readers preserve the original direct verification path.
        if lock is None:
            self._verify_all()
            return
        # Same-ID readers recheck the shared token after entering single-flight.
        with lock:
            if self._is_semantically_verified():
                return
            self._verify_all()

    def roundtrips(
        self,
        # Close the roundtrips signature after its explicit inputs.
        *,
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        # Execute the local parquet run result reader roundtrips workflow in explicit,
        # reviewable steps.
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("round-trip page limit must be between 1 and 200")
        if not isinstance(
            self._manifest.bounded_summary, (PumpfunSnipingSummaryMetadata, CopySummaryMetadata)
        ):
            # Unsupported result families cannot expose misleading Pump position pages.
            raise RunOutputIntegrityError("Run has no Pump.fun Sniping results")
        if self._is_semantically_verified():
            return self._read_roundtrip_page(after=after, limit=limit)
        lock = self._semantic_verification_lock
        # Focused standalone readers retain the uncached full-scan semantics.
        if lock is None:
            self._verify_final_balances()
            return self._scan_roundtrips(after=after, limit=limit)
        # A waiting peer may consume the shared proof instead of scanning again.
        with lock:
            if self._is_semantically_verified():
                return self._read_roundtrip_page(after=after, limit=limit)
            self._verify_final_balances()
            return self._scan_roundtrips(after=after, limit=limit)

    def _is_semantically_verified(self) -> bool:
        if self._balances_verified and self._roundtrips_verified:
            return True
        if self._semantic_verified_probe is None or not self._semantic_verified_probe():
            return False
        self._balances_verified = True
        self._roundtrips_verified = True
        if self._roundtrip_page_index_probe is not None:
            # A peer publishes seek evidence atomically with the semantic cache token.
            self._roundtrip_page_index = self._roundtrip_page_index_probe()
        return True

    def _verify_all(self) -> None:
        self._verify_final_balances()
        if not self._roundtrips_verified:
            self._scan_roundtrips(after=None, limit=0)

    def _mark_semantically_verified(self) -> None:
        if not (self._balances_verified and self._roundtrips_verified):
            return
        if self._semantic_verified_callback is not None:
            self._semantic_verified_callback(self._roundtrip_page_index)

    def _verify_final_balances(self) -> None:
        # Execute the local parquet run result reader verify final balances workflow in
        # explicit, reviewable steps.
        if self._balances_verified:
            return
        descriptor = self._manifest.result_table(RunResultTableRole.FINAL_BALANCES)
        # Final balances use the selected result family framing without changing their asset
        # semantics.
        hasher = CanonicalStreamHasher(
            COPY_BALANCE_STREAM
            if isinstance(self._manifest.bounded_summary, CopySummaryMetadata)
            else "backtest.sniping-final-balances.v1"
            # Keep the bounded summary isinstance step visible while building hasher.
            if isinstance(self._manifest.bounded_summary, PumpfunSnipingSummaryMetadata)
            else "backtest.final-balances.v1"
        )
        first_swap_rows: list[list[object]] | None = (
            None
            # Keep the bounded summary isinstance step visible while building first swap
            # rows.
            if isinstance(
                self._manifest.bounded_summary, (PumpfunSnipingSummaryMetadata, CopySummaryMetadata)
            )
            else []
        )
        # Balance verification tracks prior keys without retaining the complete table.
        previous: tuple[str, str, str, int] | None = None
        # Key ordering prevents duplicate balance rows from hiding behind a valid row count.
        previous_key: tuple[str, str, str] | None = None
        # Acquire open binary, relative name and handle at an explicit local parquet run
        # result reader verify final balances context boundary so cleanup remains scoped.
        with self._handle.open_binary(descriptor.relative_name) as stream:
            # Keep open binary, relative name and handle active only for the bounded local
            # parquet run result reader verify final balances operation.
            parquet = pq.ParquetFile(stream)
            _require_parquet_schema(parquet, _final_balance_schema(), descriptor.row_count)
            for batch in parquet.iter_batches(batch_size=8_192):
                # Process parquet.iter_batches(batch_size=8192) inside the bounded local
                # parquet run result reader verify final balances loop.
                for raw in batch.to_pylist():
                    # Process batch.to_pylist() inside the bounded local parquet run
                    # result reader verify final balances loop.
                    row = cast(dict[str, object], raw)
                    account_id = _required_text(row.get("account_id"), "balance account")
                    bucket = _required_text(row.get("bucket"), "balance bucket")
                    asset_id = _required_text(row.get("asset_id"), "balance asset")
                    amount = _decode_signed_int128(row.get("amount_atomic"), "balance amount")
                    # Assemble value once so the local parquet run result reader verify
                    # final balances workflow shares one value.
                    value = (account_id, bucket, asset_id, amount)
                    key = value[:3]
                    if previous is not None and value <= previous:
                        raise RunOutputIntegrityError("final balances are not canonically ordered")
                    if key == previous_key:
                        # Fail the local parquet run result reader verify final balances
                        # path with RunOutputIntegrityError for final balances contain a
                        # duplicate key when key and previous key is true; do not continue
                        # ambiguously.
                        raise RunOutputIntegrityError("final balances contain a duplicate key")
                    hasher.append(list(value))
                    if first_swap_rows is not None:
                        first_swap_rows.append(list(value))
                    previous = value
                    # Assemble previous key once so the local parquet run result reader
                    # verify final balances workflow shares one value.
                    previous_key = key
        canonical_digest = hasher.digest
        if first_swap_rows is not None:
            canonical_digest = domain_digest("backtest.final-balances.v1", first_swap_rows)
        if hasher.count != descriptor.row_count or canonical_digest != descriptor.canonical_digest:
            # Fail the local parquet run result reader verify final balances path with
            # RunOutputIntegrityError for final balance table differs from its descriptor
            # when count, row count and canonical digest is true; do not continue
            # ambiguously.
            raise RunOutputIntegrityError("final balance table differs from its descriptor")
        self._balances_verified = True
        self._mark_semantically_verified()

    def _decode_roundtrip_row(
        self,
        row: dict[str, object],
        *,
        schema_id: str,
        # The schema selects the strict position decoder and its canonical paging key.
    ) -> tuple[bytes, RoundTripRecord | CopyPositionRecord, tuple[int, str]]:
        """Decode and reconcile every logical field exposed by a returned row."""

        encoded = _required_bytes(row.get("record_json"), "round-trip record")
        try:
            document = json.loads(encoded)
        except (UnicodeDecodeError, ValueError) as error:
            raise RunOutputIntegrityError("round-trip row is invalid JSON") from error

        # Canonical JSON prevents two byte representations from sharing one row meaning.
        if canonical_json_bytes(document) != encoded:
            raise RunOutputIntegrityError("round-trip row is not canonical JSON")
        try:
            record: RoundTripRecord | CopyPositionRecord
            if schema_id == COPY_POSITION_SCHEMA:
                # Copy positions cannot pass through a legacy Sniping record constructor.
                record = copy_position_from_document(document)
            else:
                record = roundtrip_record_from_document(document, schema_id=schema_id)
        except (KeyError, TypeError, ValueError) as error:
            raise RunOutputIntegrityError("round-trip row contract is invalid") from error
        # Indexed columns must be exact projections of the authenticated record payload.
        key = (record.target_position.boundary_ordinal, record.roundtrip_id.hex)
        if (
            row.get("target_boundary_ordinal") != key[0]
            or _required_bytes(row.get("roundtrip_id"), "round-trip ID") != bytes.fromhex(key[1])
            or row.get("status") != record.status.value
        ):
            raise RunOutputIntegrityError("round-trip indexed columns differ from record")
        if (
            record.network_id != self._manifest.resolved_spec.network_id
            or record.position_schema_id != self._manifest.resolved_spec.position_schema_id
        ):
            raise RunOutputIntegrityError("round-trip chain identity differs from Run")
        return encoded, record, key

    def _read_roundtrip_page(
        self,
        *,
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        """Decode only one requested page after prior full semantic verification."""

        descriptor = self._manifest.result_table(RunResultTableRole.ROUNDTRIPS)
        cursor_key = (
            None if after is None else (after.target_boundary_ordinal, after.roundtrip_id.hex)
        )
        selected: list[RoundTripRecord | CopyPositionRecord] = []

        # The file is reopened under its artifact read lease for every bounded request.
        with self._handle.open_binary(descriptor.relative_name) as stream:
            # Cached semantics still authenticate the physical envelope on every page.
            parquet = pq.ParquetFile(stream)
            _require_parquet_schema(
                parquet,
                _roundtrip_schema(descriptor.schema_id),
                descriptor.row_count,
            )
            row_groups = self._roundtrip_row_groups_after(
                parquet,
                cursor_key=cursor_key,
            )
            for batch in parquet.iter_batches(batch_size=1_024, row_groups=row_groups):
                # Read bounded batches and retain only the requested page plus lookahead.
                for raw in batch.to_pylist():
                    row = cast(dict[str, object], raw)
                    boundary = row.get("target_boundary_ordinal")
                    if isinstance(boundary, bool) or not isinstance(boundary, int) or boundary < 0:
                        raise RunOutputIntegrityError(
                            "round-trip target boundary ordinal is invalid"
                        )
                    indexed_key = (
                        boundary,
                        _required_bytes(row.get("roundtrip_id"), "round-trip ID").hex(),
                    )
                    # Rows before the authenticated keyset cursor are never returned.
                    if cursor_key is not None and indexed_key <= cursor_key:
                        continue
                    _, record, key = self._decode_roundtrip_row(
                        row,
                        schema_id=descriptor.schema_id,
                    )
                    if key != indexed_key:
                        raise RunOutputIntegrityError(
                            "round-trip indexed columns differ from record"
                        )
                    # One extra row proves whether a forward cursor should be emitted.
                    selected.append(record)
                    if len(selected) > limit:
                        break
                if len(selected) > limit:
                    break
        has_more = len(selected) > limit
        items = tuple(selected[:limit])
        next_cursor = None
        # The next cursor names the final visible row, never the hidden lookahead row.
        if has_more and items:
            last = items[-1]
            next_cursor = RoundTripCursor(
                last.target_position.boundary_ordinal,
                last.roundtrip_id,
            )
        return RoundTripPage(items, next_cursor)

    def _roundtrip_row_groups_after(
        self,
        parquet: pq.ParquetFile,
        *,
        cursor_key: _RoundTripKey | None,
    ) -> tuple[int, ...] | None:
        """Use only full-scan-proven sparse checkpoints to skip earlier row groups."""

        index = self._roundtrip_page_index
        if cursor_key is None or index is None:
            return None
        if index and index[-1][0] != parquet.num_row_groups - 1:
            raise RunOutputIntegrityError("round-trip page index does not cover the table")

        start_group = 0
        previous_group = -1
        previous_key: _RoundTripKey | None = None
        for group_index, maximum_key in index:
            # Checkpoints are trusted only in their canonical table order.
            if group_index <= previous_group or group_index >= parquet.num_row_groups:
                raise RunOutputIntegrityError("round-trip page index is invalid")
            if previous_key is not None and maximum_key < previous_key:
                raise RunOutputIntegrityError("round-trip page index is not ordered")
            previous_group = group_index
            previous_key = maximum_key
            # Every row through this checkpoint is at or before its proven maximum.
            if maximum_key <= cursor_key:
                start_group = group_index + 1
            else:
                break
        return tuple(range(start_group, parquet.num_row_groups))

    def _scan_roundtrips(
        self,
        *,
        # Keep the after input explicit in the scan roundtrips contract.
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        # Execute the local parquet run result reader scan roundtrips workflow in
        # explicit, reviewable steps.
        descriptor = self._manifest.result_table(RunResultTableRole.ROUNDTRIPS)
        is_sniping = isinstance(self._manifest.bounded_summary, PumpfunSnipingSummaryMetadata)
        copy_totals = (
            CopyTotalsAccumulator()
            if isinstance(self._manifest.bounded_summary, CopySummaryMetadata)
            # Only the copy family accumulates the separate copy financial totals.
            else None
        )
        roundtrip_domain = "backtest.first-swap-roundtrip-stream.v1"
        if copy_totals is not None:
            roundtrip_domain = COPY_POSITION_STREAM
        # Sniping records retain their version-specific digest domains.
        if is_sniping:
            # Hash committed rows in their original generation-specific domain.
            roundtrip_domain = (
                "backtest.sniping-roundtrip-stream.v4"
                if descriptor.schema_id == ROUNDTRIP_RESULT_SCHEMA_V4
                else "backtest.sniping-roundtrip-stream.v3"
            )
        # Hashing and bounded paging share one verified sequential table traversal.
        hasher = CanonicalStreamHasher(roundtrip_domain)
        previous: tuple[int, str] | None = None
        page_checkpoints: list[tuple[int, _RoundTripKey]] = []
        selected: list[RoundTripRecord | CopyPositionRecord] = []
        cursor_key = (
            # The cursor key is physical paging state, not a new semantic result identity.
            None if after is None else (after.target_boundary_ordinal, after.roundtrip_id.hex)
            # Complete the cursor key group only after its semantic components are visible.
        )
        with self._handle.open_binary(descriptor.relative_name) as stream:
            # Keep open binary, relative name and handle active only for the bounded local
            # parquet run result reader scan roundtrips operation.
            parquet = pq.ParquetFile(stream)
            _require_parquet_schema(
                parquet,
                _roundtrip_schema(descriptor.schema_id),
                descriptor.row_count,
            )
            checkpoint_stride = max(
                1,
                (parquet.num_row_groups + _MAX_ROUNDTRIP_PAGE_CHECKPOINTS - 1)
                // _MAX_ROUNDTRIP_PAGE_CHECKPOINTS,
            )
            for row_group in range(parquet.num_row_groups):
                # Explicit row groups let the verified scan build a sparse seek proof.
                for batch in parquet.iter_batches(batch_size=8_192, row_groups=[row_group]):
                    for raw in batch.to_pylist():
                        # Decode every row while building semantic and seek evidence.
                        row = cast(dict[str, object], raw)
                        encoded, record, key = self._decode_roundtrip_row(
                            row,
                            schema_id=descriptor.schema_id,
                        )
                        # Every decoded copy row must belong to the same family as the root summary.
                        if copy_totals is not None:
                            if not isinstance(record, CopyPositionRecord):
                                raise RunOutputIntegrityError(
                                    "copy table contains a different result family"
                                )
                            # Aggregate only validated records before comparing the recomputed
                            # scalar summary.
                            copy_totals.append(record)
                        if previous is not None and key <= previous:
                            raise RunOutputIntegrityError("round-trip table is not keyset ordered")
                        hasher.append_canonical_bytes(encoded)
                        previous = key
                        # Keyset paging skips verified prior rows without using SQL OFFSET.
                        if cursor_key is not None and key <= cursor_key:
                            continue
                        if limit > 0 and len(selected) <= limit:
                            selected.append(record)
                # A sampled group maximum proves that every preceding row may be skipped.
                is_checkpoint = (row_group + 1) % checkpoint_stride == 0
                is_final_group = row_group + 1 == parquet.num_row_groups
                if previous is not None and (is_checkpoint or is_final_group):
                    page_checkpoints.append((row_group, previous))
        # Evaluate the complete local parquet run result reader scan roundtrips count, row
        # count and digest condition before guarded effects.
        if hasher.count != descriptor.row_count or hasher.digest != descriptor.canonical_digest:
            raise RunOutputIntegrityError("round-trip table differs from its descriptor")
        if copy_totals is not None:
            summary = self._manifest.bounded_summary
            if (
                # The recomputed position totals must equal the immutable bounded summary.
                not isinstance(summary, CopySummaryMetadata)
                or copy_totals.finish() != summary.totals
            ):
                raise RunOutputIntegrityError(
                    "copy position totals differ from the bounded summary"
                    # A valid stream digest alone cannot legitimize inconsistent aggregate money
                    # fields.
                )
        if len(page_checkpoints) > _MAX_ROUNDTRIP_PAGE_CHECKPOINTS:
            raise RunOutputIntegrityError("round-trip page index exceeds its memory bound")
        self._roundtrip_page_index = tuple(page_checkpoints)
        self._roundtrips_verified = True
        # Mark semantic verification complete only after counts, hashes and totals reconcile.
        self._mark_semantically_verified()
        has_more = len(selected) > limit
        items = tuple(selected[:limit])
        # Assemble next cursor once so the local parquet run result reader scan roundtrips
        # workflow shares one value.
        next_cursor = None
        if has_more and items:
            # Handle the local parquet run result reader scan roundtrips has_more and
            # items branch as a distinct logical block.
            last = items[-1]
            next_cursor = RoundTripCursor(
                last.target_position.boundary_ordinal,
                last.roundtrip_id,
            )
        # Return the completed local parquet run result reader scan roundtrips result
        # without a hidden fallback.
        return RoundTripPage(items, next_cursor)


# Keep the local parquet run output session contract and validation rules together.
class _LocalParquetRunOutputSession:
    def __init__(
        self,
        artifacts: ArtifactRepository,
        root: Path,
        # Keep the spec input explicit in the init contract.
        spec: ResolvedRunSpec,
        execution_attempt_id: ExecutionAttemptId,
        physical_settings: RunPhysicalSettings,
        *,
        compression: str,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local parquet run output session init workflow in explicit,
        # reviewable steps.
        self._artifacts = artifacts
        self._root = root
        self._spec = spec
        self._attempt_id = execution_attempt_id
        self._settings = physical_settings
        # Assemble self state once so the local parquet run output session init workflow
        # shares one value.
        self._state = "open"
        self._audit_values: list[dict[str, object]] = []
        self._ledger_values: list[dict[str, object]] = []
        self._fill_values: list[dict[str, object]] = []
        self._roundtrip_values: list[dict[str, object]] = []
        # Assemble self final balance values once so the local parquet run output session
        # init workflow shares one value.
        self._final_balance_values: list[dict[str, object]] = []
        self._last_roundtrip_key: tuple[int, str] | None = None
        self._first_swap_balance_rows: list[list[object]] | None = None
        self._sniping_ledger_reconciler: _SnipingLedgerReconciler | None = None
        self._copy_ledger_reconciler: CopyLedgerReconciler | None = None
        # Output framing is selected once from the admitted backend before any row is written.
        if physical_settings.backend is RunBackend.REFERENCE_PUMPFUN_COPY_BUY:
            audit_domain, ledger_domain, fill_domain = (
                COPY_AUDIT_STREAM,
                COPY_LEDGER_STREAM,
                COPY_FILL_STREAM,
                # Copy framing cannot collide with the pre-existing Sniping audit domains.
            )
            # Copy positions keep their own logical schema inside the common external table role.
            roundtrip_domain, final_balance_domain = COPY_POSITION_STREAM, COPY_BALANCE_STREAM
            self._roundtrip_schema_id = COPY_POSITION_SCHEMA
            self._copy_ledger_reconciler = CopyLedgerReconciler()
        elif physical_settings.backend.is_pumpfun_sniping:
            # Handle the local parquet run output session init is pumpfun sniping, backend
            # and physical settings condition as a distinct block.
            audit_domain = "backtest.sniping-audit-stream.v1"
            ledger_domain = "backtest.sniping-ledger-stream.v2"
            fill_domain = "backtest.sniping-fill-stream.v1"
            roundtrip_domain = "backtest.sniping-roundtrip-stream.v4"
            self._roundtrip_schema_id = ROUNDTRIP_RESULT_SCHEMA_V4
            final_balance_domain = "backtest.sniping-final-balances.v1"
            # Assemble self sniping ledger reconciler once so the local parquet run output
            # session init workflow shares one value.
            self._sniping_ledger_reconciler = _SnipingLedgerReconciler()
        else:
            # Handle the local parquet run output session init complement of is pumpfun
            # sniping, backend and physical settings explicitly.
            audit_domain = "backtest.canonical-audit-stream.v1"
            ledger_domain = "backtest.canonical-ledger-stream.v2"
            fill_domain = "backtest.canonical-fill-stream.v1"
            roundtrip_domain = "backtest.first-swap-roundtrip-stream.v1"
            self._roundtrip_schema_id = ROUNDTRIP_RESULT_SCHEMA_V3
            final_balance_domain = "backtest.final-balances.v1"
            # Assemble self first swap balance rows once so the local parquet run output
            # session init workflow shares one value.
            self._first_swap_balance_rows = []
        self._audit_hash = CanonicalStreamHasher(audit_domain)
        self._ledger_hash = CanonicalStreamHasher(ledger_domain)
        self._fill_hash = CanonicalStreamHasher(fill_domain)
        self._roundtrip_hash = CanonicalStreamHasher(roundtrip_domain)
        # Assemble self final balance hash once so the local parquet run output session
        # init workflow shares one value.
        self._final_balance_hash = CanonicalStreamHasher(final_balance_domain)
        self._audit_writer = pq.ParquetWriter(
            root / "audit.parquet",
            _audit_schema(),
            compression=compression,
            # Pass use dictionary explicitly so ParquetWriter receives a reviewable
            # parquet and record type input in local parquet run output session init.
            use_dictionary=("record_type",),
        )
        self._ledger_writer = pq.ParquetWriter(
            root / "ledger.parquet",
            _ledger_schema(),
            # Pass compression explicitly so ParquetWriter receives a reviewable parquet
            # and correlation kind input in local parquet run output session init.
            compression=compression,
            use_dictionary=("correlation_kind", "reason"),
        )
        self._fill_writer = pq.ParquetWriter(
            root / "fills.parquet",
            # Keep the fill schema _fill_schema step visible while building self. fill
            # writer.
            _fill_schema(),
            compression=compression,
            use_dictionary=("pool_id", "sold_asset_id", "bought_asset_id"),
        )
        self._roundtrip_writer = pq.ParquetWriter(
            # Pass root explicitly so ParquetWriter receives a reviewable parquet and
            # status input in local parquet run output session init.
            root / "roundtrips.parquet",
            _roundtrip_schema(self._roundtrip_schema_id),
            compression=compression,
            use_dictionary=("status",),
        )
        # Assemble self final balance writer once so the local parquet run output session
        # init workflow shares one value.
        self._final_balance_writer = pq.ParquetWriter(
            root / "final_balances.parquet",
            _final_balance_schema(),
            compression=compression,
            use_dictionary=("account_id", "bucket", "asset_id"),
            # Complete ParquetWriter only after its parquet and account id inputs are visible
            # in local parquet run output session init.
        )

    def append_audit(self, record: dict[str, object]) -> None:
        # Execute the local parquet run output session append audit workflow in explicit,
        # reviewable steps.
        self._require_open()
        encoded = canonical_json_bytes(record)
        boundary = record.get("boundary_ordinal")
        phase = record.get("phase")
        record_type = record.get("record_type")
        # Evaluate the complete local parquet run output session append audit isinstance,
        # boundary and phase condition before guarded effects.
        if (
            isinstance(boundary, bool)
            or not isinstance(boundary, int)
            or boundary < 0
            or isinstance(phase, bool)
            # Keep isinstance visible while evaluating the isinstance, boundary and phase
            # guard.
            or not isinstance(phase, int)
            or not 0 <= phase <= 255
            or not isinstance(record_type, str)
        ):
            raise RunOutputIntegrityError("audit record has invalid indexed fields")
        # Invoke _append_canonical_audit for encoded and boundary as a visible local
        # parquet run output session append audit step.
        self._append_canonical_audit(
            encoded,
            boundary_ordinal=boundary,
            phase=phase,
            record_type=record_type,
            # Complete _append_canonical_audit only after its encoded and boundary inputs are
            # visible in local parquet run output session append audit.
        )

    def append_canonical_audit(
        self,
        record_json: bytes,
        *,
        # Keep the boundary ordinal input explicit in the append canonical audit contract.
        boundary_ordinal: int,
        phase: int,
        record_type: str,
    ) -> None:
        """Append engine-authored canonical bytes without parsing a row object."""

        self._require_open()
        if (
            not record_json
            or boundary_ordinal < 0
            or not 0 <= phase <= 255
            # Keep record type visible while evaluating the record json, boundary ordinal
            # and record type guard.
            or not record_type
            or record_type != record_type.strip()
        ):
            raise RunOutputIntegrityError("encoded audit record has invalid indexed fields")
        self._append_canonical_audit(
            # Pass record json explicitly so _append_canonical_audit receives a reviewable
            # record json and boundary ordinal input in local parquet run output session
            # append canonical audit.
            record_json,
            boundary_ordinal=boundary_ordinal,
            phase=phase,
            record_type=record_type,
        )

    # Define local parquet run output session append canonical audit as one focused
    # operation with an explicit boundary.
    def _append_canonical_audit(
        self,
        record_json: bytes,
        *,
        boundary_ordinal: int,
        # Keep the phase input explicit in the append canonical audit contract.
        phase: int,
        record_type: str,
    ) -> None:
        # Execute the local parquet run output session append canonical audit workflow in
        # explicit, reviewable steps.
        self._audit_hash.append_canonical_bytes(record_json)
        self._audit_values.append(
            {
                "boundary_ordinal": boundary_ordinal,
                "phase": phase,
                # Keep record json named so the record type and boundary ordinal payload
                # passed to append remains self-describing within local parquet run output
                # session append canonical audit.
                "record_json": record_json,
                "record_type": record_type,
            }
        )
        if len(self._audit_values) >= self._settings.output_buffer_rows:
            # Invoke _flush_audit as a visible step within the local parquet run output
            # session append canonical audit workflow.
            self._flush_audit()

    def append_ledger(self, transaction: LedgerTransaction) -> None:
        # Execute the local parquet run output session append ledger workflow in explicit,
        # reviewable steps.
        self._require_open()
        if self._copy_ledger_reconciler is not None:
            self._copy_ledger_reconciler.append_ledger(transaction)
        if self._sniping_ledger_reconciler is not None:
            self._sniping_ledger_reconciler.append_ledger(transaction)
        # The canonical ledger stream records the same postings used by family reconciliation.
        document = ledger_document(transaction)
        self._ledger_hash.append(document)
        # Invoke append for value and reason as a visible local parquet run output session
        # append ledger step.
        self._ledger_values.append(
            {
                "boundary_ordinal": transaction.boundary_ordinal,
                "correlation_id": bytes.fromhex(transaction.correlation_id.hex),
                "correlation_kind": transaction.correlation_kind.value,
                # Pass postings json explicitly to append for value and reason.
                "postings_json": canonical_json_bytes(document["postings"]),
                "reason": transaction.reason,
                "transaction_id": bytes.fromhex(transaction.transaction_id.hex),
            }
        )
        # Evaluate the complete local parquet run output session append ledger output
        # buffer rows, ledger values and settings condition before guarded effects.
        if len(self._ledger_values) >= self._settings.output_buffer_rows:
            self._flush_ledger()

    def append_fill(self, fill: Fill) -> None:
        # Execute the local parquet run output session append fill workflow in explicit,
        # reviewable steps.
        self._require_open()
        document = fill_document(fill)
        self._fill_hash.append(document)
        self._fill_values.append(
            {
                # Pass amount in atomic explicitly to append for amount in atomic and
                # amount out atomic.
                "amount_in_atomic": _signed_int128(fill.amount_in_atomic),
                "amount_out_atomic": _signed_int128(fill.amount_out_atomic),
                "boundary_ordinal": fill.boundary_ordinal,
                "bought_asset_id": fill.bought_asset_id.value,
                "fee_amount_atomic": _signed_int128(fill.fee_amount_atomic),
                # Pass order id explicitly to append for amount in atomic and amount out
                # atomic.
                "order_id": bytes.fromhex(fill.order_id.hex),
                "pool_id": fill.pool_id.value,
                "sold_asset_id": fill.sold_asset_id.value,
            }
        )
        # Evaluate the complete local parquet run output session append fill output buffer
        # rows, fill values and settings condition before guarded effects.
        if len(self._fill_values) >= self._settings.output_buffer_rows:
            self._flush_fills()

    def append_copy_position(self, record: CopyPositionRecord) -> None:
        """Publish the real BUY target and bounded retry history without Sniping-only fields."""
        self._require_open()
        if self._copy_ledger_reconciler is None:
            raise RunOutputIntegrityError("copy positions require the copy output contract")
        if (
            record.network_id != self._spec.network_id
            # A position cannot introduce another chain into a resolved single-network run.
            or record.position_schema_id != self._spec.position_schema_id
        ):
            raise RunOutputIntegrityError("copy position chain differs from the resolved run")
        # Semantic row validation and strict keyset ordering precede the buffered write.
        document = record.document()
        if copy_position_from_document(document) != record:
            raise RunOutputIntegrityError("copy position failed immutable roundtrip validation")
        key = (record.target_position.boundary_ordinal, record.roundtrip_id.hex)
        if self._last_roundtrip_key is not None and key <= self._last_roundtrip_key:
            # Canonical source-position ordering is required for stable result keyset paging.
            raise RunOutputIntegrityError("copy positions must be strictly keyset ordered")
        self._copy_ledger_reconciler.append_position(record)
        # The verified publication protocol is shared; no new artifact commit path is introduced.
        encoded = canonical_json_bytes(document)
        self._roundtrip_hash.append_canonical_bytes(encoded)
        self._roundtrip_values.append(
            {
                "record_json": encoded,
                # The row index retains bounded keys alongside the complete canonical record bytes.
                "roundtrip_id": bytes.fromhex(record.roundtrip_id.hex),
                "status": record.status.value,
                "target_boundary_ordinal": record.target_position.boundary_ordinal,
            }
        )
        # Advance the paging key only after the immutable record has entered the output buffer.
        self._last_roundtrip_key = key
        # At most output_buffer_rows encoded records are retained by the physical writer.
        if len(self._roundtrip_values) >= self._settings.output_buffer_rows:
            self._flush_roundtrips()

    def append_roundtrip(self, record: RoundTripRecord) -> None:
        """Append one canonical target lifecycle in strict keyset order."""

        self._require_open()
        if not self._settings.backend.is_pumpfun_sniping:
            raise RunOutputIntegrityError("FirstSwap output cannot contain round-trip rows")
        if (
            record.network_id != self._spec.network_id
            # Keep record visible while evaluating the network id, position schema id and
            # record guard.
            or record.position_schema_id != self._spec.position_schema_id
        ):
            raise RunOutputIntegrityError("round-trip chain identity differs from the run")
        key = (record.target_position.boundary_ordinal, record.roundtrip_id.hex)
        if self._last_roundtrip_key is not None and key <= self._last_roundtrip_key:
            # Fail the local parquet run output session append roundtrip path with
            # RunOutputIntegrityError for round-trip rows must be strictly keyset ordered
            # when last roundtrip key and key is true; do not continue ambiguously.
            raise RunOutputIntegrityError("round-trip rows must be strictly keyset ordered")
        if self._sniping_ledger_reconciler is None:  # pragma: no cover - narrowed by backend
            raise RunOutputIntegrityError("sniping reconciliation is unavailable")
        validate_roundtrip_record_v4(record)
        self._sniping_ledger_reconciler.append_roundtrip(record)
        document = record.document()
        encoded = canonical_json_bytes(document)
        self._roundtrip_hash.append_canonical_bytes(encoded)
        # Invoke append for value and record json as a visible local parquet run output
        # session append roundtrip step.
        self._roundtrip_values.append(
            {
                "record_json": encoded,
                "roundtrip_id": bytes.fromhex(record.roundtrip_id.hex),
                "status": record.status.value,
                # Keep target boundary ordinal named so the value and record json payload
                # passed to append remains self-describing within local parquet run output
                # session append roundtrip.
                "target_boundary_ordinal": record.target_position.boundary_ordinal,
            }
        )
        self._last_roundtrip_key = key
        if len(self._roundtrip_values) >= self._settings.output_buffer_rows:
            # Invoke _flush_roundtrips as a visible step within the local parquet run
            # output session append roundtrip workflow.
            self._flush_roundtrips()

    def finalize(
        self,
        manifest: SuccessfulRunManifest,
        *,
        # Keep the final balances input explicit in the finalize contract.
        final_balances: tuple[tuple[str, str, str, int], ...],
    ) -> CommittedArtifact:
        # Execute the local parquet run output session finalize workflow in explicit,
        # reviewable steps.
        self._require_open()
        if (
            manifest.resolved_spec != self._spec
            or manifest.execution_attempt_id != self._attempt_id
        ):
            # Fail the local parquet run output session finalize path with
            # RunOutputIntegrityError for run manifest differs from the staged output
            # identity when resolved spec, spec and execution attempt id is true; do not
            # continue ambiguously.
            raise RunOutputIntegrityError("run manifest differs from the staged output identity")
        writer: ArtifactWriter | None = None
        try:
            # Perform the protected local parquet run output session finalize operation
            # before explicit failure handling.
            self._append_final_balances(final_balances)
            self._close_parquet()
            if self._copy_ledger_reconciler is not None:
                copy_summary = manifest.bounded_summary
                if not isinstance(copy_summary, CopySummaryMetadata):
                    # Copy outputs require the matching bounded summary before publication can
                    # complete.
                    raise RunOutputIntegrityError("copy output requires a copy summary")
                self._copy_ledger_reconciler.verify_summary(copy_summary)
            # Existing Sniping reconciliation remains independent of the new copy family.
            if self._sniping_ledger_reconciler is not None:
                # Handle the local parquet run output session finalize sniping ledger
                # reconciler condition as a distinct block.
                bounded_summary = manifest.bounded_summary
                if not isinstance(bounded_summary, PumpfunSnipingSummaryMetadata):
                    raise RunOutputIntegrityError("sniping output requires a sniping summary")
                self._sniping_ledger_reconciler.verify_summary(bounded_summary)
            _verify_summary(
                # Pass manifest explicitly so _verify_summary receives a reviewable audit
                # hash and ledger hash input in local parquet run output session finalize.
                manifest,
                self._audit_hash,
                self._ledger_hash,
                self._fill_hash,
                self._roundtrip_hash,
                # Pass self explicitly so _verify_summary receives a reviewable audit hash
                # and ledger hash input in local parquet run output session finalize.
                self._final_balance_hash,
                self._first_swap_balance_rows,
            )
            writer = self._artifacts.stage(
                ArtifactDraft(
                    # Pass kind explicitly so ArtifactDraft receives a reviewable run and
                    # hex input in local parquet run output session finalize.
                    kind=ArtifactKind.RUN,
                    build_key=ContentDigest(self._attempt_id.hex),
                    input_artifact_ids=manifest.input_artifact_ids,
                )
            )
            # Traverse parquet explicitly so each local parquet run output session
            # finalize iteration remains traceable.
            for name in (
                "audit.parquet",
                "fills.parquet",
                "ledger.parquet",
                "roundtrips.parquet",
                # Traverse parquet explicitly so each local parquet run output session
                # finalize iteration remains traceable.
                "final_balances.parquet",
            ):
                # Process parquet inside the bounded local parquet run output session
                # finalize loop.
                with (self._root / name).open("rb") as source, writer.open_binary(name) as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            committed = writer.commit(
                manifest.manifest_bytes(),
                identity_manifest_bytes=manifest.identity_bytes(),
                # Complete commit only after its manifest bytes and identity bytes inputs are
                # visible in local parquet run output session finalize.
            )
            if committed.kind is not ArtifactKind.RUN:
                raise RunOutputIntegrityError("repository returned a non-Run artifact")
            self._state = "committed"
            return committed
        # Translate base exception through the local parquet run output session finalize
        # boundary without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the local parquet run output
            # session finalize boundary.
            if writer is not None:
                writer.abort()
            self._state = "failed"
            raise
        finally:
            # Invoke _remove_work_root as a visible step within the local parquet run
            # output session finalize workflow.
            self._remove_work_root()

    def abort(self) -> None:
        # Execute the local parquet run output session abort workflow in explicit,
        # reviewable steps.
        if self._state in {"aborted", "committed"}:
            return
        try:
            self._close_parquet()
        finally:
            # Handle the cleanup path after the protected local parquet run output session
            # abort operation.
            self._state = "aborted"
            self._remove_work_root()

    def _flush_audit(self) -> None:
        # Execute the local parquet run output session flush audit workflow in explicit,
        # reviewable steps.
        _write_rows(self._audit_writer, self._audit_values, _audit_schema())
        self._audit_values.clear()

    def _flush_ledger(self) -> None:
        # Execute the local parquet run output session flush ledger workflow in explicit,
        # reviewable steps.
        _write_rows(self._ledger_writer, self._ledger_values, _ledger_schema())
        self._ledger_values.clear()

    def _flush_fills(self) -> None:
        # Execute the local parquet run output session flush fills workflow in explicit,
        # reviewable steps.
        _write_rows(self._fill_writer, self._fill_values, _fill_schema())
        self._fill_values.clear()

    def _flush_roundtrips(self) -> None:
        # Execute the local parquet run output session flush roundtrips workflow in
        # explicit, reviewable steps.
        _write_rows(
            self._roundtrip_writer,
            self._roundtrip_values,
            _roundtrip_schema(self._roundtrip_schema_id),
        )
        self._roundtrip_values.clear()

    def _flush_final_balances(self) -> None:
        # Execute the local parquet run output session flush final balances workflow in
        # explicit, reviewable steps.
        _write_rows(
            self._final_balance_writer,
            self._final_balance_values,
            _final_balance_schema(),
        )
        # Invoke clear as a visible step within the local parquet run output session flush
        # final balances workflow.
        self._final_balance_values.clear()

    def _append_final_balances(
        self,
        values: tuple[tuple[str, str, str, int], ...],
    ) -> None:
        # Execute the local parquet run output session append final balances workflow in
        # explicit, reviewable steps.
        for account_id, bucket, asset_id, amount_atomic in validate_final_balances(values):
            # Process validate_final_balances(values) inside the bounded local parquet run
            # output session append final balances loop.
            row = [account_id, bucket, asset_id, amount_atomic]
            self._final_balance_hash.append(row)
            if self._first_swap_balance_rows is not None:
                self._first_swap_balance_rows.append(row)
            self._final_balance_values.append(
                # Open the account id and amount atomic payload explicitly for append
                # within local parquet run output session append final balances.
                {
                    "account_id": account_id,
                    "amount_atomic": _signed_int128(amount_atomic),
                    "asset_id": asset_id,
                    "bucket": bucket,
                    # Close the account id and amount atomic payload only after all local
                    # parquet run output session append final balances fields are present.
                }
            )
            if len(self._final_balance_values) >= self._settings.output_buffer_rows:
                self._flush_final_balances()

    def _close_parquet(self) -> None:
        # Execute the local parquet run output session close parquet workflow in explicit,
        # reviewable steps.
        if self._state != "open":
            return
        self._flush_audit()
        self._flush_ledger()
        self._flush_fills()
        # Invoke _flush_roundtrips as a visible step within the local parquet run output
        # session close parquet workflow.
        self._flush_roundtrips()
        self._flush_final_balances()
        self._audit_writer.close()
        self._ledger_writer.close()
        self._fill_writer.close()
        # Invoke close as a visible step within the local parquet run output session close
        # parquet workflow.
        self._roundtrip_writer.close()
        self._final_balance_writer.close()
        self._state = "closed"

    def _remove_work_root(self) -> None:
        # Execute the local parquet run output session remove work root workflow in
        # explicit, reviewable steps.
        if self._root.exists():
            shutil.rmtree(self._root)

    def _require_open(self) -> None:
        # Execute the local parquet run output session require open workflow in explicit,
        # reviewable steps.
        if self._state != "open":
            raise RuntimeError(f"run output session is {self._state}")


def _verify_summary(
    manifest: SuccessfulRunManifest,
    audit: CanonicalStreamHasher,
    # Keep the ledger input explicit in the verify summary contract.
    ledger: CanonicalStreamHasher,
    fills: CanonicalStreamHasher,
    roundtrips: CanonicalStreamHasher,
    final_balances: CanonicalStreamHasher,
    first_swap_balance_rows: list[list[object]] | None,
    # Close the verify summary signature after its explicit inputs.
) -> None:
    # Execute the verify summary workflow in explicit, reviewable steps.
    summary = manifest.comparison
    if audit.digest != summary.audit_hash:
        raise RunOutputIntegrityError("buffered audit hash differs from engine summary")
    if ledger.digest != summary.ledger_hash or ledger.count != summary.ledger_transaction_count:
        raise RunOutputIntegrityError("buffered ledger differs from engine summary")
    # Evaluate the complete verify summary digest, fill hash and count condition before
    # guarded effects.
    if fills.digest != summary.fill_hash or fills.count != summary.fill_count:
        raise RunOutputIntegrityError("buffered fills differ from engine summary")
    roundtrip_descriptor = manifest.result_table(RunResultTableRole.ROUNDTRIPS)
    if (
        roundtrips.digest != roundtrip_descriptor.canonical_digest
        # Keep roundtrips visible while evaluating the digest, canonical digest and count
        # guard.
        or roundtrips.count != roundtrip_descriptor.row_count
    ):
        raise RunOutputIntegrityError("buffered round trips differ from their descriptor")
    balance_descriptor = manifest.result_table(RunResultTableRole.FINAL_BALANCES)
    balance_digest = final_balances.digest
    # Guard this path with first_swap_balance_rows is not None before applying effects.
    if first_swap_balance_rows is not None:
        # Handle the verify summary first_swap_balance_rows is not None branch as a
        # distinct logical block.
        balance_digest = domain_digest(
            "backtest.final-balances.v1",
            first_swap_balance_rows,
        )
    if (
        # Keep balance digest visible while evaluating the balance digest, canonical
        # digest and count guard.
        balance_digest != balance_descriptor.canonical_digest
        or final_balances.count != balance_descriptor.row_count
    ):
        raise RunOutputIntegrityError("buffered final balances differ from their descriptor")


def _write_rows(
    # Keep the writer input explicit in the write rows contract.
    writer: pq.ParquetWriter,
    rows: list[dict[str, object]],
    schema: pa.Schema,
) -> None:
    # Execute the write rows workflow in explicit, reviewable steps.
    if rows:
        writer.write_table(pa.Table.from_pylist(cast(list[dict[str, Any]], rows), schema=schema))


def _audit_schema() -> pa.Schema:
    # Execute the audit schema workflow in explicit, reviewable steps.
    return pa.schema(
        [
            pa.field("boundary_ordinal", pa.uint64(), nullable=False),
            pa.field("phase", pa.uint8(), nullable=False),
            pa.field("record_type", pa.string(), nullable=False),
            # Include nullable in the completed audit schema result.
            pa.field("record_json", pa.binary(), nullable=False),
        ],
        metadata={b"backtest.schema": b"run-audit/v1"},
    )


def _ledger_schema() -> pa.Schema:
    # Execute the ledger schema workflow in explicit, reviewable steps.
    return pa.schema(
        [
            pa.field("transaction_id", pa.binary(32), nullable=False),
            pa.field("correlation_kind", pa.string(), nullable=False),
            pa.field("correlation_id", pa.binary(32), nullable=False),
            # Include nullable in the completed ledger schema result.
            pa.field("boundary_ordinal", pa.uint64(), nullable=False),
            pa.field("reason", pa.string(), nullable=False),
            pa.field("postings_json", pa.binary(), nullable=False),
        ],
        metadata={b"backtest.schema": b"run-ledger/v2"},
        # Complete schema only after its transaction id and correlation kind inputs are
        # visible in ledger schema.
    )


def _fill_schema() -> pa.Schema:
    # Execute the fill schema workflow in explicit, reviewable steps.
    return pa.schema(
        [
            pa.field("order_id", pa.binary(32), nullable=False),
            pa.field("pool_id", pa.string(), nullable=False),
            pa.field("sold_asset_id", pa.string(), nullable=False),
            # Include nullable in the completed fill schema result.
            pa.field("bought_asset_id", pa.string(), nullable=False),
            pa.field("amount_in_atomic", pa.binary(16), nullable=False),
            pa.field("amount_out_atomic", pa.binary(16), nullable=False),
            pa.field("fee_amount_atomic", pa.binary(16), nullable=False),
            pa.field("boundary_ordinal", pa.uint64(), nullable=False),
            # Close the order id and pool id payload only after all fill schema fields are
            # present.
        ],
        metadata={b"backtest.integer_encoding": b"signed-int128-big-endian-v1"},
    )


def _roundtrip_schema(schema_id: str) -> pa.Schema:
    """Build the fixed physical envelope for one supported logical generation."""

    if schema_id not in {
        ROUNDTRIP_RESULT_SCHEMA_V3,
        ROUNDTRIP_RESULT_SCHEMA_V4,
        COPY_POSITION_SCHEMA,
    }:
        # Unknown row schemas cannot be written under the shared Parquet container.
        raise ValueError("unsupported round-trip Parquet schema")
    # The external index stores only stable paging fields and bounded canonical record bytes.
    return pa.schema(
        [
            pa.field("target_boundary_ordinal", pa.uint64(), nullable=False),
            pa.field("roundtrip_id", pa.binary(32), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            # Include nullable in the completed roundtrip schema result.
            pa.field("record_json", pa.binary(), nullable=False),
        ],
        metadata={b"backtest.schema": schema_id.encode("ascii")},
    )


def _final_balance_schema() -> pa.Schema:
    # Execute the final balance schema workflow in explicit, reviewable steps.
    return pa.schema(
        [
            pa.field("account_id", pa.string(), nullable=False),
            pa.field("bucket", pa.string(), nullable=False),
            pa.field("asset_id", pa.string(), nullable=False),
            # Include nullable in the completed final balance schema result.
            pa.field("amount_atomic", pa.binary(16), nullable=False),
        ],
        metadata={
            b"backtest.integer_encoding": b"signed-int128-big-endian-v1",
            b"backtest.schema": b"run-final-balances/v1",
            # Close the account id and bucket payload only after all final balance schema
            # fields are present.
        },
    )


def _signed_int128(value: int) -> bytes:
    # Execute the signed int128 workflow in explicit, reviewable steps.
    if not -(1 << 127) <= value < 1 << 127:
        raise OverflowError("run output amount does not fit signed Int128")
    return value.to_bytes(16, "big", signed=True)


def _decode_signed_int128(value: object, field: str) -> int:
    # Execute the decode signed int128 workflow in explicit, reviewable steps.
    encoded = _required_bytes(value, field)
    if len(encoded) != 16:
        raise RunOutputIntegrityError(f"{field} is not a signed Int128")
    return int.from_bytes(encoded, "big", signed=True)


def _required_bytes(value: object, field: str) -> bytes:
    # Execute the required bytes workflow in explicit, reviewable steps.
    if not isinstance(value, bytes) or not value:
        raise RunOutputIntegrityError(f"{field} must be non-empty bytes")
    return value


def _required_text(value: object, field: str) -> str:
    # Execute the required text workflow in explicit, reviewable steps.
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_COMPARISON_LABEL_LENGTH
        # Keep value visible while evaluating the value, max comparison label length and
        # isinstance guard.
        or not value.isprintable()
    ):
        raise RunOutputIntegrityError(f"{field} is invalid")
    return value


def _require_parquet_schema(
    # Keep the parquet input explicit in the require parquet schema contract.
    parquet: pq.ParquetFile,
    expected: pa.Schema,
    expected_rows: int,
) -> None:
    # Execute the require parquet schema workflow in explicit, reviewable steps.
    if not parquet.schema_arrow.equals(expected, check_metadata=True):
        raise RunOutputIntegrityError("result table Parquet schema is invalid")
    if parquet.metadata.num_rows != expected_rows:
        raise RunOutputIntegrityError("result table Parquet row count differs from descriptor")


def _read_bounded(stream: IO[bytes], limit: int) -> bytes:
    # Execute the read bounded workflow in explicit, reviewable steps.
    payload = stream.read(limit + 1)
    if not payload or len(payload) > limit:
        raise RunOutputIntegrityError("Run manifest is empty or exceeds its metadata limit")
    return payload


__all__ = [
    # Keep the local parquet run output store component named inside the all contract.
    "LocalParquetRunOutputStore",
    "LocalParquetRunResultReaderFactory",
    "RunOutputIntegrityError",
]
