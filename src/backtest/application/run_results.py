"""Bounded network-aware successful Run artifact contracts.

The root manifest contains only bounded metadata. Potentially unbounded
round-trip and final-balance rows live in verified columnar payloads described
by :class:`ResultTableDescriptor`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, fields

# Import datetime at the visible module dependency boundary.
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast

from backtest.application.errors import ReprepareRequiredError
from backtest.application.run_specs import (
    # Include replay contract so the run specs dependency remains explicit.
    ReplayContract,
    ResolvedRunSpec,
    resolved_run_spec_from_bytes,
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import canonical_json_bytes, domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    ExecutionAttemptId,
    # Include logical run id so the identifiers dependency remains explicit.
    LogicalRunId,
)
from backtest.domain.roundtrips import (
    ROUNDTRIP_RESULT_SCHEMA_V3,
    ROUNDTRIP_RESULT_SCHEMA_V4,
    # Legacy row schemas retain their original meaning beside the new copy family.
)
from backtest.engine.copytrading_results import COPY_POSITION_SCHEMA
from backtest.engine.copytrading_run import CopyFinancialTotals, CopyRunSummary
from backtest.engine.reference import RunSummary
from backtest.engine.sniping import SnipingRunSummary, SnipingValuationStatus

# Mode-specific liquidity policies remain validated independently of summary projection.
from backtest.engine.sniping_contracts import liquidity_policy_id_for_execution_mode

SUCCESSFUL_RUN_SCHEMA: Final = "successful-run/v3"
# Bind first swap summary schema once as an explicit module-level contract.
FIRST_SWAP_SUMMARY_SCHEMA: Final = "first-swap-run-summary/v1"
LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA: Final = "pumpfun-sniping-run-summary/v2"
PUMPFUN_SNIPING_SUMMARY_SCHEMA: Final = "pumpfun-sniping-run-summary/v3"
RESULT_TABLE_DESCRIPTOR_SCHEMA: Final = "run-result-table-descriptor/v1"
RUN_PHYSICAL_SETTINGS_SCHEMA: Final = "backtest.run-physical-settings/v2"
SUPPORTED_READER_READAHEAD: Final = frozenset({1, 2, 4})
# Compatibility export only. V3 does not enforce the old embedded-row limit.
MAX_COMPARISON_FINAL_BALANCES: Final = 16_384
MAX_RESULT_TABLE_ROWS: Final = (1 << 64) - 1
MAX_COMPARISON_LABEL_LENGTH: Final = 256
MAX_RUN_WARNINGS: Final = 16
MAX_RUN_WARNING_LENGTH: Final = 256
# Bind max successful run manifest bytes once as an explicit module-level contract.
MAX_SUCCESSFUL_RUN_MANIFEST_BYTES: Final = 1024 * 1024

_FIRST_SWAP_ROUNDTRIP_DIGEST_DOMAIN: Final = "backtest.first-swap-roundtrip-stream.v1"
_FIRST_SWAP_BALANCE_DIGEST_DOMAIN: Final = "backtest.final-balances.v1"


class RunBackend(StrEnum):
    """Installed exact engine implementations selectable per physical attempt."""

    REFERENCE_PYTHON = "reference-python-v1"
    NUMPY_MMAP_FIRST_SWAP_EXACT = "numpy-mmap-first-swap-exact-v1"
    REFERENCE_PUMPFUN_SNIPING = "reference-pumpfun-sniping-v1"
    NUMPY_MMAP_PUMPFUN_SNIPING = "numpy-mmap-pumpfun-sniping-v1"
    # Copy admission is reference-only until its own optimized equivalence/performance gate.
    REFERENCE_PUMPFUN_COPY_BUY = "reference-pumpfun-copy-buy-v1"

    @property
    # Define run backend is pumpfun sniping as one focused operation with an explicit
    # boundary.
    def is_pumpfun_sniping(self) -> bool:
        # Execute the run backend is pumpfun sniping workflow in explicit, reviewable
        # steps.
        return self in {
            RunBackend.REFERENCE_PUMPFUN_SNIPING,
            RunBackend.NUMPY_MMAP_PUMPFUN_SNIPING,
        }


# Keep the run result table role contract and validation rules together.
class RunResultTableRole(StrEnum):
    FINAL_BALANCES = "final_balances"
    ROUNDTRIPS = "roundtrips"


_RESULT_TABLE_CONTRACT: Final = {
    RunResultTableRole.FINAL_BALANCES: ("final_balances.parquet", "run-final-balances/v1"),
    # Keep the run result table role component named inside the result table contract
    # contract.
    RunResultTableRole.ROUNDTRIPS: ("roundtrips.parquet", ROUNDTRIP_RESULT_SCHEMA_V4),
}


@dataclass(frozen=True, slots=True, order=True)
class ResultTableDescriptor:
    """Bounded reference to one verified table inside a Run artifact."""

    role: RunResultTableRole
    schema_id: str
    relative_name: str
    row_count: int
    canonical_digest: ContentDigest

    # Define result table descriptor post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the result table descriptor post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.role, RunResultTableRole):
            raise TypeError("result table role must be a RunResultTableRole")
        expected_name, expected_schema = _RESULT_TABLE_CONTRACT[self.role]
        supported_schemas = {expected_schema}
        if self.role is RunResultTableRole.ROUNDTRIPS:
            # The reader preserves committed v3 descriptors while all new writes use v4.
            supported_schemas.add(ROUNDTRIP_RESULT_SCHEMA_V3)
            supported_schemas.add(COPY_POSITION_SCHEMA)
        if self.relative_name != expected_name or self.schema_id not in supported_schemas:
            raise ValueError("result table descriptor differs from its fixed v1 contract")
        # Invoke _require_result_row_count for result table row count and row count as a
        # visible result table descriptor post init step.
        _require_result_row_count(self.row_count, "result table row count")
        if not isinstance(self.canonical_digest, ContentDigest):
            raise TypeError("result table canonical digest must be a ContentDigest")

    def document(self) -> dict[str, object]:
        # Execute the result table descriptor document workflow in explicit, reviewable
        # steps.
        return {
            "canonical_digest": self.canonical_digest.hex,
            "relative_name": self.relative_name,
            "role": self.role.value,
            "row_count": self.row_count,
            # Include schema in the completed result table descriptor document result.
            "schema": RESULT_TABLE_DESCRIPTOR_SCHEMA,
            "schema_id": self.schema_id,
        }

    @classmethod
    def from_document(cls, value: object) -> ResultTableDescriptor:
        # Execute the result table descriptor from document workflow in explicit,
        # reviewable steps.
        document = _object(value, "result table descriptor")
        expected = {
            "canonical_digest",
            "relative_name",
            "role",
            # Keep the row count component named inside the expected contract.
            "row_count",
            "schema",
            "schema_id",
        }
        if set(document) != expected or document["schema"] != RESULT_TABLE_DESCRIPTOR_SCHEMA:
            # Fail the result table descriptor from document path with ValueError for
            # result table descriptor schema is invalid when expected, result table
            # descriptor schema and document is true; do not continue ambiguously.
            raise ValueError("result table descriptor schema is invalid")
        try:
            role = RunResultTableRole(_string(document["role"], "result table role"))
        except ValueError as error:
            raise ValueError("unsupported result table role") from error
        # Assemble result once so the result table descriptor from document workflow
        # shares one value.
        result = cls(
            role=role,
            schema_id=_string(document["schema_id"], "result table schema ID"),
            relative_name=_string(document["relative_name"], "result table relative name"),
            row_count=_non_negative_integer(document["row_count"], "result table row count"),
            # Keep the content digest and string ContentDigest step visible while building
            # result.
            canonical_digest=ContentDigest(
                _string(document["canonical_digest"], "result table canonical digest")
            ),
        )
        if result.document() != document:
            # Fail the result table descriptor from document path with ValueError for
            # result table descriptor does not round-trip exactly when document and result
            # is true; do not continue ambiguously.
            raise ValueError("result table descriptor does not round-trip exactly")
        return result


class RunComparisonMetric(StrEnum):
    """Closed set of values already calculated by an exact successful run."""

    ACCEPTED_ORDER_COUNT = "accepted_order_count"
    AUDIT_HASH = "audit_hash"
    CANONICAL_RESULT_HASH = "canonical_result_hash"
    DELIVERED_EVENT_COUNT = "delivered_event_count"
    FAILED_ORDER_COUNT = "failed_order_count"
    # Declare fill count explicitly in the run comparison metric contract.
    FILL_COUNT = "fill_count"
    FILL_HASH = "fill_hash"
    FILLED_ORDER_COUNT = "filled_order_count"
    FINAL_BALANCES_COUNT = "final_balances_count"
    FINAL_BALANCES_DIGEST = "final_balances_digest"
    # Declare historical event count explicitly in the run comparison metric contract.
    HISTORICAL_EVENT_COUNT = "historical_event_count"
    HISTORICAL_GROUP_COUNT = "historical_group_count"
    LEDGER_HASH = "ledger_hash"
    LEDGER_TRANSACTION_COUNT = "ledger_transaction_count"
    REJECTED_ORDER_COUNT = "rejected_order_count"


# Apply dataclass semantics to the following run comparison projection contract.
@dataclass(frozen=True, slots=True)
class RunComparisonProjection:
    """Canonical valuation-free scalar projection shared by exact run types."""

    canonical_result_hash: ContentDigest
    audit_hash: ContentDigest
    ledger_hash: ContentDigest
    fill_hash: ContentDigest
    historical_group_count: int
    # Declare historical event count explicitly in the run comparison projection contract.
    historical_event_count: int
    delivered_event_count: int
    accepted_order_count: int
    rejected_order_count: int
    filled_order_count: int
    # Declare failed order count explicitly in the run comparison projection contract.
    failed_order_count: int
    ledger_transaction_count: int
    fill_count: int
    final_balances_count: int
    final_balances_digest: ContentDigest

    # Define run comparison projection post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the run comparison projection post init workflow in explicit, reviewable
        # steps.
        for field_name in (
            "canonical_result_hash",
            "audit_hash",
            "ledger_hash",
            "fill_hash",
            # Traverse canonical result hash, audit hash and ledger hash explicitly so
            # each run comparison projection post init iteration remains traceable.
            "final_balances_digest",
        ):
            # Process canonical result hash, audit hash and ledger hash inside the bounded
            # run comparison projection post init loop.
            if not isinstance(getattr(self, field_name), ContentDigest):
                raise TypeError(f"{field_name} must be a content digest")
        for field_name in (
            "historical_group_count",
            "historical_event_count",
            # Traverse historical group count, historical event count and delivered event
            # count explicitly so each run comparison projection post init iteration
            # remains traceable.
            "delivered_event_count",
            "accepted_order_count",
            "rejected_order_count",
            "filled_order_count",
            "failed_order_count",
            # Traverse historical group count, historical event count and delivered event
            # count explicitly so each run comparison projection post init iteration
            # remains traceable.
            "ledger_transaction_count",
            "fill_count",
            "final_balances_count",
        ):
            _require_result_row_count(getattr(self, field_name), field_name)

    # Apply classmethod semantics to the following run comparison projection from summary
    # contract.
    @classmethod
    def from_summary(
        cls,
        summary: RunSummary | SnipingRunSummary | CopyRunSummary | SuccessfulRunSummary,
    ) -> RunComparisonProjection:
        # Execute the run comparison projection from summary workflow in explicit,
        # reviewable steps.
        if isinstance(summary, CopyRunSummary):
            return _copy_summary_metadata(summary).comparison
        if isinstance(
            summary, (FirstSwapSummaryMetadata, PumpfunSnipingSummaryMetadata, CopySummaryMetadata)
        ):
            # Already normalized summaries preserve their immutable comparison projection.
            return summary.comparison
        balances = validate_final_balances(summary.final_balances)
        balance_domain = (
            "backtest.sniping-final-balances.v1"
            # Keep the summary isinstance step visible while building balance domain.
            if isinstance(summary, SnipingRunSummary)
            else _FIRST_SWAP_BALANCE_DIGEST_DOMAIN
        )
        balance_values = [list(row) for row in balances]
        balance_digest = (
            # Keep the balance domain _stream_digest step visible while building balance
            # digest.
            _stream_digest(balance_domain, balance_values)
            if isinstance(summary, SnipingRunSummary)
            else domain_digest(balance_domain, balance_values)
        )
        if (
            # Keep isinstance visible while evaluating the isinstance, summary and sniping
            # run summary guard.
            isinstance(summary, SnipingRunSummary)
            and balance_digest != summary.final_balances_digest
        ):
            raise ValueError("sniping final balance rows differ from the engine digest")
        return cls(
            # Pass canonical result hash explicitly so cls receives a reviewable result
            # hash and audit hash input in run comparison projection from summary.
            canonical_result_hash=summary.result_hash,
            audit_hash=summary.audit_hash,
            ledger_hash=summary.ledger_hash,
            fill_hash=summary.fill_hash,
            historical_group_count=summary.historical_group_count,
            # Pass historical event count explicitly so cls receives a reviewable result
            # hash and audit hash input in run comparison projection from summary.
            historical_event_count=summary.historical_event_count,
            delivered_event_count=summary.delivered_event_count,
            accepted_order_count=summary.accepted_order_count,
            rejected_order_count=summary.rejected_order_count,
            filled_order_count=summary.filled_order_count,
            # Pass failed order count explicitly so cls receives a reviewable result hash
            # and audit hash input in run comparison projection from summary.
            failed_order_count=summary.failed_order_count,
            ledger_transaction_count=summary.ledger_transaction_count,
            fill_count=summary.fill_count,
            final_balances_count=len(balances),
            final_balances_digest=balance_digest,
            # Complete cls only after its result hash and audit hash inputs are visible in run
            # comparison projection from summary.
        )

    def selected_document(
        self,
        metrics: tuple[RunComparisonMetric, ...],
    ) -> dict[str, object]:
        # Execute the run comparison projection selected document workflow in explicit,
        # reviewable steps.
        if metrics != normalize_comparison_metrics(metrics):
            raise ValueError("comparison metrics must be canonically ordered and unique")
        values: dict[str, object] = {}
        for metric in metrics:
            # Process metrics inside the bounded run comparison projection selected
            # document loop.
            raw = getattr(self, _COMPARISON_ATTRIBUTE[metric])
            values[metric.value] = raw.hex if isinstance(raw, ContentDigest) else raw
        return values

    def document(self) -> dict[str, object]:
        # Execute the run comparison projection document workflow in explicit, reviewable
        # steps.
        return self.selected_document(
            tuple(sorted(RunComparisonMetric, key=lambda item: item.value))
        )

    @classmethod
    def from_document(cls, value: object) -> RunComparisonProjection:
        # Execute the run comparison projection from document workflow in explicit,
        # reviewable steps.
        document = _object(value, "run comparison")
        if set(document) != {item.value for item in RunComparisonMetric}:
            raise ValueError("run comparison schema is invalid")
        return cls(
            canonical_result_hash=ContentDigest(
                # Include string in the completed run comparison projection from document
                # result.
                _string(document["canonical_result_hash"], "canonical result hash")
            ),
            audit_hash=ContentDigest(_string(document["audit_hash"], "audit hash")),
            ledger_hash=ContentDigest(_string(document["ledger_hash"], "ledger hash")),
            fill_hash=ContentDigest(_string(document["fill_hash"], "fill hash")),
            # Include historical group count in the completed run comparison projection
            # from document result.
            historical_group_count=_non_negative_integer(
                document["historical_group_count"], "historical group count"
            ),
            historical_event_count=_non_negative_integer(
                document["historical_event_count"],
                # Pass historical event count explicitly so _non_negative_integer receives
                # a reviewable historical event count and document input in run comparison
                # projection from document.
                "historical event count",
                # Complete _non_negative_integer only after its historical event count and
                # document inputs are visible in run comparison projection from document.
            ),
            delivered_event_count=_non_negative_integer(
                document["delivered_event_count"], "delivered event count"
            ),
            accepted_order_count=_non_negative_integer(
                # Pass document explicitly so _non_negative_integer receives a reviewable
                # accepted order count and document input in run comparison projection
                # from document.
                document["accepted_order_count"],
                "accepted order count",
            ),
            rejected_order_count=_non_negative_integer(
                document["rejected_order_count"],
                # Pass rejected order count explicitly so _non_negative_integer receives a
                # reviewable rejected order count and document input in run comparison
                # projection from document.
                "rejected order count",
                # Complete _non_negative_integer only after its rejected order count and
                # document inputs are visible in run comparison projection from document.
            ),
            # Include filled order count in the completed run comparison projection from
            # document result.
            filled_order_count=_non_negative_integer(
                document["filled_order_count"], "filled order count"
            ),
            failed_order_count=_non_negative_integer(
                document["failed_order_count"],
                # Pass failed order count explicitly so _non_negative_integer receives a
                # reviewable failed order count and document input in run comparison
                # projection from document.
                "failed order count",
                # Complete _non_negative_integer only after its failed order count and
                # document inputs are visible in run comparison projection from document.
            ),
            ledger_transaction_count=_non_negative_integer(
                document["ledger_transaction_count"], "ledger transaction count"
            ),
            fill_count=_non_negative_integer(document["fill_count"], "fill count"),
            # Include final balances count in the completed run comparison projection from
            # document result.
            final_balances_count=_non_negative_integer(
                document["final_balances_count"], "final balances count"
            ),
            final_balances_digest=ContentDigest(
                _string(document["final_balances_digest"], "final balances digest")
                # Complete ContentDigest only after its final balances digest and string
                # inputs are visible in run comparison projection from document.
            ),
        )


_COMPARISON_ATTRIBUTE: Final = {
    RunComparisonMetric.ACCEPTED_ORDER_COUNT: "accepted_order_count",
    RunComparisonMetric.AUDIT_HASH: "audit_hash",
    # Keep the run comparison metric component named inside the comparison attribute
    # contract.
    RunComparisonMetric.CANONICAL_RESULT_HASH: "canonical_result_hash",
    RunComparisonMetric.DELIVERED_EVENT_COUNT: "delivered_event_count",
    RunComparisonMetric.FAILED_ORDER_COUNT: "failed_order_count",
    RunComparisonMetric.FILL_COUNT: "fill_count",
    RunComparisonMetric.FILL_HASH: "fill_hash",
    # Keep the run comparison metric component named inside the comparison attribute
    # contract.
    RunComparisonMetric.FILLED_ORDER_COUNT: "filled_order_count",
    RunComparisonMetric.FINAL_BALANCES_COUNT: "final_balances_count",
    RunComparisonMetric.FINAL_BALANCES_DIGEST: "final_balances_digest",
    RunComparisonMetric.HISTORICAL_EVENT_COUNT: "historical_event_count",
    RunComparisonMetric.HISTORICAL_GROUP_COUNT: "historical_group_count",
    # Keep the run comparison metric component named inside the comparison attribute
    # contract.
    RunComparisonMetric.LEDGER_HASH: "ledger_hash",
    RunComparisonMetric.LEDGER_TRANSACTION_COUNT: "ledger_transaction_count",
    RunComparisonMetric.REJECTED_ORDER_COUNT: "rejected_order_count",
}


# Keep the first swap summary metadata contract and validation rules together.
@dataclass(frozen=True, slots=True)
class FirstSwapSummaryMetadata:
    dataset_logical_content_hash: ContentDigest
    replay_semantics_id: ContentDigest
    engine_bundle_id: BundleId
    # Declare latency bundle id explicitly in the first swap summary metadata contract.
    latency_bundle_id: BundleId
    comparison: RunComparisonProjection

    @property
    def result_hash(self) -> ContentDigest:
        return self.comparison.canonical_result_hash

    # Apply property semantics to the following first swap summary metadata audit hash
    # contract.
    @property
    def audit_hash(self) -> ContentDigest:
        return self.comparison.audit_hash

    def document(self) -> dict[str, object]:
        # Execute the first swap summary metadata document workflow in explicit,
        # reviewable steps.
        return {
            "comparison": self.comparison.document(),
            "dataset_logical_content_hash": self.dataset_logical_content_hash.hex,
            "engine_bundle_id": self.engine_bundle_id.hex,
            "latency_bundle_id": self.latency_bundle_id.hex,
            # Include replay semantics id in the completed first swap summary metadata
            # document result.
            "replay_semantics_id": self.replay_semantics_id.hex,
            "schema": FIRST_SWAP_SUMMARY_SCHEMA,
        }


# Keep the pumpfun sniping summary metadata contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpfunSnipingSummaryMetadata:
    dataset_logical_content_hash: ContentDigest
    replay_semantics_id: ContentDigest
    engine_bundle_id: BundleId
    # Declare strategy bundle id explicitly in the pumpfun sniping summary metadata
    # contract.
    strategy_bundle_id: BundleId
    protocol_bundle_id: BundleId
    network_cost_bundle_id: BundleId
    comparison: RunComparisonProjection
    target_count: int
    # Declare cooldown skipped count explicitly in the pumpfun sniping summary metadata
    # contract.
    cooldown_skipped_count: int
    accepted_buy_count: int
    closed_roundtrip_count: int
    open_position_count: int
    failed_buy_count: int
    # Declare failed sell count explicitly in the pumpfun sniping summary metadata
    # contract.
    failed_sell_count: int
    roundtrip_count: int
    roundtrip_digest: ContentDigest
    realized_cash_pnl_atomic: int
    valuation_status: SnipingValuationStatus
    # Declare unvalued open position count explicitly in the pumpfun sniping summary
    # metadata contract.
    unvalued_open_position_count: int
    valued_economic_pnl_subtotal_atomic: int
    economic_pnl_atomic: int | None
    cashback_receivable_atomic: int
    protocol_fee_paid_atomic: int
    # Declare creator fee paid atomic explicitly in the pumpfun sniping summary metadata
    # contract.
    creator_fee_paid_atomic: int
    network_base_fee_paid_atomic: int
    network_priority_fee_paid_atomic: int
    account_deposit_paid_atomic: int
    account_deposit_refunded_atomic: int
    # Declare account deposit locked atomic explicitly in the pumpfun sniping summary
    # metadata contract.
    account_deposit_locked_atomic: int
    favorable_slippage_count: int
    adverse_slippage_count: int
    buy_slippage_failure_count: int
    sell_slippage_failure_count: int
    # Summary v3 makes the synthetic settlement assumption queryable and auditable.
    execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY
    settlement_policy_id: str = "real-reserve-capped-v1"
    filled_sell_count: int = 0
    real_liquidity_sufficient_filled_sell_count: int = 0
    synthetic_liquidity_used_sell_count: int = 0
    # Gross output is conserved across the venue and explicit synthetic source.
    gross_sell_settlement_atomic: int = 0
    venue_funded_sell_atomic: int = 0
    synthetic_funded_sell_atomic: int = 0
    source_schema_id: str = PUMPFUN_SNIPING_SUMMARY_SCHEMA

    # Apply property semantics to the following pumpfun sniping summary metadata result
    # hash contract.
    @property
    def result_hash(self) -> ContentDigest:
        return self.comparison.canonical_result_hash

    @property
    def audit_hash(self) -> ContentDigest:
        # Return the completed pumpfun sniping summary metadata audit hash result without
        # a hidden fallback.
        return self.comparison.audit_hash

    def __post_init__(self) -> None:
        # Execute the pumpfun sniping summary metadata post init workflow in explicit,
        # reviewable steps.
        for field_name in (
            "target_count",
            "cooldown_skipped_count",
            "accepted_buy_count",
            "closed_roundtrip_count",
            # Traverse target count, cooldown skipped count and accepted buy count
            # explicitly so each pumpfun sniping summary metadata post init iteration
            # remains traceable.
            "open_position_count",
            "failed_buy_count",
            "failed_sell_count",
            "roundtrip_count",
            "cashback_receivable_atomic",
            # Traverse target count, cooldown skipped count and accepted buy count
            # explicitly so each pumpfun sniping summary metadata post init iteration
            # remains traceable.
            "unvalued_open_position_count",
            "protocol_fee_paid_atomic",
            "creator_fee_paid_atomic",
            "network_base_fee_paid_atomic",
            "network_priority_fee_paid_atomic",
            # Traverse target count, cooldown skipped count and accepted buy count
            # explicitly so each pumpfun sniping summary metadata post init iteration
            # remains traceable.
            "account_deposit_paid_atomic",
            "account_deposit_refunded_atomic",
            "account_deposit_locked_atomic",
            "favorable_slippage_count",
            "adverse_slippage_count",
            # Traverse target count, cooldown skipped count and accepted buy count
            # explicitly so each pumpfun sniping summary metadata post init iteration
            # remains traceable.
            "buy_slippage_failure_count",
            "sell_slippage_failure_count",
            "filled_sell_count",
            "real_liquidity_sufficient_filled_sell_count",
            "synthetic_liquidity_used_sell_count",
            "gross_sell_settlement_atomic",
            "venue_funded_sell_atomic",
            "synthetic_funded_sell_atomic",
        ):
            _require_result_row_count(getattr(self, field_name), field_name)
        for field_name in (
            # Traverse realized cash pnl atomic and valued economic pnl subtotal atomic
            # explicitly so each pumpfun sniping summary metadata post init iteration
            # remains traceable.
            "realized_cash_pnl_atomic",
            "valued_economic_pnl_subtotal_atomic",
        ):
            # Process realized cash pnl atomic and valued economic pnl subtotal atomic
            # inside the bounded pumpfun sniping summary metadata post init loop.
            if isinstance(getattr(self, field_name), bool) or not isinstance(
                getattr(self, field_name), int
            ):
                raise ValueError(f"{field_name} must be an integer")
        if self.economic_pnl_atomic is not None and (
            # Keep isinstance visible while evaluating the economic pnl atomic and
            # isinstance guard.
            isinstance(self.economic_pnl_atomic, bool)
            or not isinstance(self.economic_pnl_atomic, int)
        ):
            raise ValueError("economic_pnl_atomic must be an integer or None")
        if not isinstance(self.valuation_status, SnipingValuationStatus):
            # Fail the pumpfun sniping summary metadata post init path with TypeError for
            # valuation status must be a sniping valuation status when isinstance,
            # valuation status and sniping valuation status is true; do not continue
            # ambiguously.
            raise TypeError("valuation_status must be a SnipingValuationStatus")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        _require_nonempty_trimmed("settlement policy ID", self.settlement_policy_id)
        if self.source_schema_id not in {
            LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA,
            PUMPFUN_SNIPING_SUMMARY_SCHEMA,
        }:
            raise ValueError("unsupported Pump.fun Sniping summary schema")
        if self.roundtrip_count != self.target_count:
            raise ValueError("sniping roundtrip count must equal the target count")
        if self.closed_roundtrip_count + self.open_position_count > self.roundtrip_count:
            raise ValueError("closed and open sniping positions exceed round trips")
        # Evaluate the complete pumpfun sniping summary metadata post init unvalued open
        # position count and open position count condition before guarded effects.
        if self.unvalued_open_position_count > self.open_position_count:
            raise ValueError("unvalued open positions exceed all open positions")
        if self.valuation_status is SnipingValuationStatus.COMPLETE:
            # Handle the pumpfun sniping summary metadata post init valuation status,
            # complete and sniping valuation status condition as a distinct block.
            if self.unvalued_open_position_count or (
                self.economic_pnl_atomic != self.valued_economic_pnl_subtotal_atomic
            ):
                raise ValueError("complete valuation must publish its full economic PnL")
        # Handle the pumpfun sniping summary metadata post init complement of valuation
        # status, complete and sniping valuation status explicitly.
        elif self.unvalued_open_position_count == 0 or self.economic_pnl_atomic is not None:
            raise ValueError("partial valuation must expose unknown full economic PnL")
        if (
            self.account_deposit_refunded_atomic + self.account_deposit_locked_atomic
            > self.account_deposit_paid_atomic
            # Evaluate the complete pumpfun sniping summary metadata post init account deposit
            # paid atomic, account deposit refunded atomic and account deposit locked atomic
            # condition before guarded effects.
        ):
            raise ValueError("refunded and locked deposits exceed paid deposits")
        if self.source_schema_id == PUMPFUN_SNIPING_SUMMARY_SCHEMA:
            self._validate_v3_settlement_totals()
        else:
            self._validate_legacy_v2_projection()

    def _validate_legacy_v2_projection(self) -> None:
        """Allow only the unique compatibility projection implied by old bytes."""

        if (
            self.execution_mode is not ExecutionMode.EXOGENOUS_REPLAY
            or self.settlement_policy_id != "real-reserve-capped-v1"
        ):
            raise ValueError("legacy summary must retain its fixed exogenous policy")
        if (
            self.filled_sell_count != self.closed_roundtrip_count
            or self.real_liquidity_sufficient_filled_sell_count != self.closed_roundtrip_count
        ):
            raise ValueError("legacy summary sell counts differ from its closed count")
        if any(
            (
                self.synthetic_liquidity_used_sell_count,
                self.gross_sell_settlement_atomic,
                self.venue_funded_sell_atomic,
                self.synthetic_funded_sell_atomic,
            )
        ):
            raise ValueError("legacy summary cannot invent absent settlement totals")

    def _validate_v3_settlement_totals(self) -> None:
        """Validate exact count and amount conservation for new summaries."""

        if self.filled_sell_count != self.closed_roundtrip_count:
            raise ValueError("filled sell count must equal closed round trips")
        classified = (
            self.real_liquidity_sufficient_filled_sell_count
            + self.synthetic_liquidity_used_sell_count
        )
        if classified != self.filled_sell_count:
            raise ValueError("filled sells must have exactly one liquidity classification")
        if bool(self.filled_sell_count) != bool(self.gross_sell_settlement_atomic):
            raise ValueError("filled sell count and gross settlement amount disagree")

        # Settlement money is conserved independently from fill/order count metrics.
        if (
            self.venue_funded_sell_atomic + self.synthetic_funded_sell_atomic
            != self.gross_sell_settlement_atomic
        ):
            raise ValueError("sell settlement funding does not conserve gross output")
        if bool(self.synthetic_liquidity_used_sell_count) != bool(
            self.synthetic_funded_sell_atomic
        ):
            raise ValueError("synthetic sell count and funded amount disagree")

        # The selected mode and versioned policy are one semantic identity decision.
        try:
            expected_policy = liquidity_policy_id_for_execution_mode(self.execution_mode)
        except ValueError as error:
            raise ValueError("unsupported summary execution mode") from error
        if self.settlement_policy_id != expected_policy:
            raise ValueError("settlement policy differs from execution mode")
        if self.execution_mode is ExecutionMode.EXOGENOUS_REPLAY and (
            self.synthetic_liquidity_used_sell_count or self.synthetic_funded_sell_atomic
        ):
            raise ValueError("strict exogenous replay cannot use synthetic liquidity")

    def document(self) -> dict[str, object]:
        # Execute the pumpfun sniping summary metadata document workflow in explicit,
        # reviewable steps.
        document = {
            "accepted_buy_count": self.accepted_buy_count,
            "account_deposit_locked_atomic": self.account_deposit_locked_atomic,
            "account_deposit_paid_atomic": self.account_deposit_paid_atomic,
            "account_deposit_refunded_atomic": self.account_deposit_refunded_atomic,
            # Include adverse slippage count in the completed pumpfun sniping summary
            # metadata document result.
            "adverse_slippage_count": self.adverse_slippage_count,
            "buy_slippage_failure_count": self.buy_slippage_failure_count,
            "cashback_receivable_atomic": self.cashback_receivable_atomic,
            "closed_roundtrip_count": self.closed_roundtrip_count,
            "comparison": self.comparison.document(),
            # Include cooldown skipped count in the completed pumpfun sniping summary
            # metadata document result.
            "cooldown_skipped_count": self.cooldown_skipped_count,
            "creator_fee_paid_atomic": self.creator_fee_paid_atomic,
            "dataset_logical_content_hash": self.dataset_logical_content_hash.hex,
            "economic_pnl_atomic": self.economic_pnl_atomic,
            "engine_bundle_id": self.engine_bundle_id.hex,
            "execution_mode": self.execution_mode.value,
            # Include failed buy count in the completed pumpfun sniping summary metadata
            # document result.
            "failed_buy_count": self.failed_buy_count,
            "failed_sell_count": self.failed_sell_count,
            "favorable_slippage_count": self.favorable_slippage_count,
            "filled_sell_count": self.filled_sell_count,
            "gross_sell_settlement_atomic": self.gross_sell_settlement_atomic,
            "network_cost_bundle_id": self.network_cost_bundle_id.hex,
            "network_base_fee_paid_atomic": self.network_base_fee_paid_atomic,
            # Include network priority fee paid atomic in the completed pumpfun sniping
            # summary metadata document result.
            "network_priority_fee_paid_atomic": self.network_priority_fee_paid_atomic,
            "open_position_count": self.open_position_count,
            "protocol_bundle_id": self.protocol_bundle_id.hex,
            "protocol_fee_paid_atomic": self.protocol_fee_paid_atomic,
            "realized_cash_pnl_atomic": self.realized_cash_pnl_atomic,
            "real_liquidity_sufficient_filled_sell_count": (
                self.real_liquidity_sufficient_filled_sell_count
            ),
            # Include replay semantics id in the completed pumpfun sniping summary
            # metadata document result.
            "replay_semantics_id": self.replay_semantics_id.hex,
            "roundtrip_count": self.roundtrip_count,
            "roundtrip_digest": self.roundtrip_digest.hex,
            "schema": PUMPFUN_SNIPING_SUMMARY_SCHEMA,
            "sell_slippage_failure_count": self.sell_slippage_failure_count,
            "settlement_policy_id": self.settlement_policy_id,
            # Include strategy bundle id in the completed pumpfun sniping summary metadata
            # document result.
            "strategy_bundle_id": self.strategy_bundle_id.hex,
            "target_count": self.target_count,
            "synthetic_funded_sell_atomic": self.synthetic_funded_sell_atomic,
            "synthetic_liquidity_used_sell_count": self.synthetic_liquidity_used_sell_count,
            "unvalued_open_position_count": self.unvalued_open_position_count,
            "valuation_status": self.valuation_status.value,
            "valued_economic_pnl_subtotal_atomic": (self.valued_economic_pnl_subtotal_atomic),
            "venue_funded_sell_atomic": self.venue_funded_sell_atomic,
            # Return the completed pumpfun sniping summary metadata document result without a
            # hidden fallback.
        }
        if self.source_schema_id == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA:
            # Re-emit committed v2 bytes without adding or rehashing v3-only fields.
            for field_name in (
                "execution_mode",
                "filled_sell_count",
                "gross_sell_settlement_atomic",
                "real_liquidity_sufficient_filled_sell_count",
                "settlement_policy_id",
                "synthetic_funded_sell_atomic",
                "synthetic_liquidity_used_sell_count",
                "venue_funded_sell_atomic",
            ):
                document.pop(field_name)
            document["schema"] = LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
        return document


@dataclass(frozen=True, slots=True)
class CopySummaryMetadata:
    """Bounded copy summary; full positions and final balances remain external tables."""

    dataset_logical_content_hash: ContentDigest
    replay_semantics_id: ContentDigest
    engine_bundle_id: BundleId
    strategy_bundle_id: BundleId
    protocol_bundle_id: BundleId
    # The same network/account economics retain an independent copy execution identity.
    network_cost_bundle_id: BundleId
    execution_mode: ExecutionMode
    comparison: RunComparisonProjection
    totals: CopyFinancialTotals
    roundtrip_digest: ContentDigest

    def __post_init__(self) -> None:
        """Cross-check common counters against copy-specific terminal outcomes."""
        totals = self.totals
        if self.comparison.fill_count != totals.filled_buy_count + totals.closed_position_count:
            raise ValueError("copy summary fill counts differ from position outcomes")
        if self.comparison.failed_order_count != totals.failed_buy_count + totals.failed_sell_count:
            raise ValueError("copy summary failed order counts differ from position outcomes")
        # Pre-submit rejects are distinct from submitted instructions and their fees.
        if (
            self.comparison.rejected_order_count
            != totals.rejected_buy_count + totals.rejected_sell_count
        ):
            raise ValueError("copy summary rejected order counts differ from position outcomes")
        # Accepted orders are exactly filled plus landed-failed instructions.
        expected = self.comparison.fill_count + self.comparison.failed_order_count
        if self.comparison.accepted_order_count != expected:
            raise ValueError("copy summary accepted order counts do not reconcile")
        # Strict execution cannot manufacture spendable sell funding.
        if (
            self.execution_mode is ExecutionMode.EXOGENOUS_REPLAY
            and totals.synthetic_funded_sell_atomic
        ):
            raise ValueError("strict copy execution cannot contain synthetic proceeds")
        # Unknown execution modes cannot pass through zero synthetic funding as a fallback.
        liquidity_policy_id_for_execution_mode(self.execution_mode)

    @property
    def result_hash(self) -> ContentDigest:
        """Common run interfaces expose the same canonical result digest."""
        return self.comparison.canonical_result_hash

    @property
    def audit_hash(self) -> ContentDigest:
        """Audit framing is copy-specific while the manifest projection stays bounded."""
        return self.comparison.audit_hash

    @property
    def roundtrip_count(self) -> int:
        """The common external table role contains one actual copy position per mint."""
        return self.totals.position_count

    def document(self) -> dict[str, object]:
        """No developer, cooldown or single-sale Sniping fields are fabricated."""
        return {
            "schema": "pumpfun-copy-run-summary/v1",
            "dataset_logical_content_hash": self.dataset_logical_content_hash.hex,
            "replay_semantics_id": self.replay_semantics_id.hex,
            "engine_bundle_id": self.engine_bundle_id.hex,
            # Strategy, protocol and costs are checked against the resolved spec.
            "strategy_bundle_id": self.strategy_bundle_id.hex,
            "protocol_bundle_id": self.protocol_bundle_id.hex,
            "network_cost_bundle_id": self.network_cost_bundle_id.hex,
            "execution_mode": self.execution_mode.value,
            "settlement_policy_id": liquidity_policy_id_for_execution_mode(self.execution_mode),
            # Common comparison scalars and specialized economics have separate fixed schemas.
            "comparison": self.comparison.document(),
            "totals": self.totals.document(),
            "position_count": self.roundtrip_count,
            "position_digest": self.roundtrip_digest.hex,
        }


# One successful-run container carries exactly one closed summary family.
SuccessfulRunSummary = (
    FirstSwapSummaryMetadata | PumpfunSnipingSummaryMetadata | CopySummaryMetadata
)


def normalize_comparison_metrics(
    values: tuple[str | RunComparisonMetric, ...],
) -> tuple[RunComparisonMetric, ...]:
    # Execute the normalize comparison metrics workflow in explicit, reviewable steps.
    parsed: list[RunComparisonMetric] = []
    for value in values:
        # Process values inside the bounded normalize comparison metrics loop.
        if not isinstance(value, str):
            raise ValueError("comparison metrics must be strings from the supported allowlist")
        try:
            parsed.append(RunComparisonMetric(value))
        except ValueError as error:
            # Fail the normalize comparison metrics path with ValueError for unsupported
            # run comparison metric: and value; do not continue ambiguously.
            raise ValueError(f"unsupported run comparison metric: {value}") from error
    return tuple(sorted(set(parsed), key=lambda item: item.value))


def validate_run_warnings(values: tuple[str, ...]) -> tuple[str, ...]:
    # Execute the validate run warnings workflow in explicit, reviewable steps.
    if len(values) > MAX_RUN_WARNINGS:
        raise ValueError("run warnings exceed the bounded count limit")
    if tuple(sorted(set(values))) != values:
        raise ValueError("run warnings must be sorted and unique")
    if any(
        # Pass value explicitly so any receives a reviewable strip and isprintable input
        # in validate run warnings.
        not value
        or value != value.strip()
        or len(value) > MAX_RUN_WARNING_LENGTH
        or not value.isprintable()
        for value in values
        # Complete any only after its strip and isprintable inputs are visible in validate run
        # warnings.
    ):
        raise ValueError("run warnings must be bounded printable strings")
    return values


def validate_final_balances(
    balances: tuple[tuple[str, str, str, int], ...],
    # Keep the tuple input explicit in the validate final balances contract.
) -> tuple[tuple[str, str, str, int], ...]:
    """Validate canonical external rows without an embedded-row count limit."""

    _require_result_row_count(len(balances), "final balances count")
    if balances != tuple(sorted(balances)):
        raise ValueError("final balances must be canonically ordered")
    keys: set[tuple[str, str, str]] = set()
    for account, bucket, asset, amount in balances:
        # Process balances inside the bounded validate final balances loop.
        for label, value in (
            ("balance account", account),
            ("balance bucket", bucket),
            ("balance asset", asset),
        ):
            # Process account, bucket and asset inside the bounded validate final balances
            # loop.
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > MAX_COMPARISON_LABEL_LENGTH
                # Keep value visible while evaluating the value, max comparison label
                # length and isinstance guard.
                or not value.isprintable()
            ):
                raise ValueError(f"{label} is invalid")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ValueError("balance amount must be an integer")
        # Assemble key once so the validate final balances workflow shares one value.
        key = (account, bucket, asset)
        if key in keys:
            raise ValueError("final balances must have unique account/bucket/asset keys")
        keys.add(key)
    return balances


# Keep the run physical settings contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RunPhysicalSettings:
    backend: RunBackend
    reader_batch_rows: int
    reader_readahead: int
    # Declare output buffer rows explicitly in the run physical settings contract.
    output_buffer_rows: int
    threads: int

    def __post_init__(self) -> None:
        # Execute the run physical settings post init workflow in explicit, reviewable
        # steps.
        if not isinstance(self.backend, RunBackend):
            raise TypeError("run backend must be an installed RunBackend")
        for field_name in ("reader_batch_rows", "output_buffer_rows", "threads"):
            # Process reader batch rows, output buffer rows and threads inside the bounded
            # run physical settings post init loop.
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            isinstance(self.reader_readahead, bool)
            # Keep isinstance visible while evaluating the isinstance, reader readahead
            # and supported reader readahead guard.
            or not isinstance(self.reader_readahead, int)
            or self.reader_readahead not in SUPPORTED_READER_READAHEAD
        ):
            raise ValueError("reader_readahead must be one of 1, 2 or 4")

    def document(self) -> dict[str, object]:
        # Execute the run physical settings document workflow in explicit, reviewable
        # steps.
        return {
            "backend": self.backend.value,
            "output_buffer_rows": self.output_buffer_rows,
            "reader_batch_rows": self.reader_batch_rows,
            "reader_readahead": self.reader_readahead,
            # Include schema in the completed run physical settings document result.
            "schema": RUN_PHYSICAL_SETTINGS_SCHEMA,
            "threads": self.threads,
        }

    @classmethod
    def from_document(cls, value: object) -> RunPhysicalSettings:
        # Execute the run physical settings from document workflow in explicit, reviewable
        # steps.
        document = _object(value, "physical run settings")
        expected = {
            "backend",
            "output_buffer_rows",
            "reader_batch_rows",
            # Keep the reader readahead component named inside the expected contract.
            "reader_readahead",
            "schema",
            "threads",
        }
        if set(document) != expected or document["schema"] != RUN_PHYSICAL_SETTINGS_SCHEMA:
            # Fail the run physical settings from document path with ValueError for
            # physical run settings v2 schema is invalid when expected, run physical
            # settings schema and document is true; do not continue ambiguously.
            raise ValueError("physical run settings v2 schema is invalid")
        try:
            backend = RunBackend(_string(document["backend"], "run backend"))
        except ValueError as error:
            raise ValueError("the selected run backend is not installed") from error
        # Assemble result once so the run physical settings from document workflow shares
        # one value.
        result = cls(
            backend=backend,
            reader_batch_rows=_positive_integer(document["reader_batch_rows"], "reader batch"),
            reader_readahead=_positive_integer(document["reader_readahead"], "reader readahead"),
            output_buffer_rows=_positive_integer(
                # Pass document explicitly so _positive_integer receives a reviewable
                # output buffer rows and document input in run physical settings from
                # document.
                document["output_buffer_rows"],
                "output buffer rows",
            ),
            threads=_positive_integer(document["threads"], "run threads"),
        )
        # Guard this path with result.document() != document before applying effects.
        if result.document() != document:
            # Fail the run physical settings from document path with ValueError for
            # physical run settings do not round-trip exactly when document and result is
            # true; do not continue ambiguously.
            raise ValueError("physical run settings do not round-trip exactly")
        return result

    @property
    def identity_digest(self) -> ContentDigest:
        return domain_digest("backtest.run-physical-settings.v2", self.document())


# Keep the successful run manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SuccessfulRunManifest:
    resolved_spec: ResolvedRunSpec
    attempt_nonce: ContentDigest
    execution_attempt_id: ExecutionAttemptId
    # Declare input artifact ids explicitly in the successful run manifest contract.
    input_artifact_ids: tuple[ArtifactId, ...]
    summary: SuccessfulRunSummary | RunSummary | SnipingRunSummary | CopyRunSummary
    physical_settings: RunPhysicalSettings
    started_at: datetime
    completed_at: datetime
    # Declare warnings explicitly in the successful run manifest contract.
    warnings: tuple[str, ...] = ()
    result_tables: tuple[ResultTableDescriptor, ...] = ()

    def __post_init__(self) -> None:
        # Execute the successful run manifest post init workflow in explicit, reviewable
        # steps.
        raw_summary = self.summary
        if isinstance(raw_summary, (RunSummary, SnipingRunSummary, CopyRunSummary)):
            object.__setattr__(self, "summary", _summary_metadata(raw_summary))
        summary = self.bounded_summary
        if not self.result_tables:
            # Invoke __setattr__ for result tables and result tables for summary as a
            # visible successful run manifest post init step.
            object.__setattr__(self, "result_tables", _result_tables_for_summary(summary))
        inputs = tuple(sorted(self.input_artifact_ids, key=lambda item: item.hex))
        if inputs != self.input_artifact_ids or len(set(inputs)) != len(inputs):
            raise ValueError("run input artifact IDs must be sorted and unique")
        tables = tuple(sorted(self.result_tables, key=lambda item: item.role.value))
        # Assemble expected roles once so the successful run manifest post init workflow
        # shares one value.
        expected_roles = tuple(sorted(RunResultTableRole, key=lambda item: item.value))
        if tables != self.result_tables or tuple(item.role for item in tables) != expected_roles:
            raise ValueError("successful run must describe each result table exactly once")
        for field_name in ("started_at", "completed_at"):
            # Process ('started_at', 'completed_at') inside the bounded successful run
            # manifest post init loop.
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("run completion cannot precede its start")
        # Assemble expected attempt once so the successful run manifest post init workflow
        # shares one value.
        expected_attempt = self.resolved_spec.execution_attempt_id(
            self.attempt_nonce, self.physical_settings.identity_digest
        )
        if self.execution_attempt_id != expected_attempt:
            raise ValueError("execution attempt ID differs from its physical provenance")
        # Evaluate the complete successful run manifest post init replay contract,
        # canonical exact and resolved spec condition before guarded effects.
        if self.resolved_spec.replay_contract is not ReplayContract.CANONICAL_EXACT:
            raise ValueError("successful canonical manifest requires CANONICAL_EXACT")
        _validate_summary_against_spec(summary, self.resolved_spec)
        _validate_result_tables(summary, self.result_tables)
        validate_run_warnings(self.warnings)

    # Apply classmethod semantics to the following successful run manifest create
    # contract.
    @classmethod
    def create(
        cls,
        *,
        resolved_spec: ResolvedRunSpec,
        # Keep the attempt nonce input explicit in the create contract.
        attempt_nonce: ContentDigest,
        execution_attempt_id: ExecutionAttemptId,
        input_artifact_ids: tuple[ArtifactId, ...],
        summary: RunSummary | SnipingRunSummary | CopyRunSummary,
        physical_settings: RunPhysicalSettings,
        # Keep the started at input explicit in the create contract.
        started_at: datetime,
        completed_at: datetime,
        warnings: tuple[str, ...] = (),
    ) -> SuccessfulRunManifest:
        # Execute the successful run manifest create workflow in explicit, reviewable
        # steps.
        metadata = _summary_metadata(summary)
        return cls(
            resolved_spec=resolved_spec,
            attempt_nonce=attempt_nonce,
            execution_attempt_id=execution_attempt_id,
            # Pass input artifact ids explicitly so cls receives a reviewable result
            # tables for summary and resolved spec input in successful run manifest
            # create.
            input_artifact_ids=input_artifact_ids,
            summary=metadata,
            physical_settings=physical_settings,
            started_at=started_at,
            completed_at=completed_at,
            # Pass warnings explicitly so cls receives a reviewable result tables for
            # summary and resolved spec input in successful run manifest create.
            warnings=warnings,
            result_tables=_result_tables_for_summary(metadata),
        )

    @property
    def logical_run_id(self) -> LogicalRunId:
        # Return the completed successful run manifest logical run id result without a
        # hidden fallback.
        return self.resolved_spec.logical_run_id

    @property
    def canonicality(self) -> ReplayContract:
        return ReplayContract.CANONICAL_EXACT

    @property
    # Define successful run manifest comparison as one focused operation with an explicit
    # boundary.
    def comparison(self) -> RunComparisonProjection:
        return self.bounded_summary.comparison

    @property
    def bounded_summary(self) -> SuccessfulRunSummary:
        # Execute the successful run manifest bounded summary workflow in explicit,
        # reviewable steps.
        summary = self.summary
        if not isinstance(
            summary, (FirstSwapSummaryMetadata, PumpfunSnipingSummaryMetadata, CopySummaryMetadata)
        ):
            raise TypeError("successful Run summary was not normalized")
        # Only a recognized normalized summary may leave the manifest boundary.
        return summary

    def result_table(self, role: RunResultTableRole) -> ResultTableDescriptor:
        # Return the completed successful run manifest result table result without a
        # hidden fallback.
        return next(item for item in self.result_tables if item.role is role)

    def document(self) -> dict[str, object]:
        # Execute the successful run manifest document workflow in explicit, reviewable
        # steps.
        return {
            "artifact_schema": SUCCESSFUL_RUN_SCHEMA,
            "attempt_nonce": self.attempt_nonce.hex,
            "canonicality": self.canonicality.value,
            "completed_at": _utc_text(self.completed_at),
            # Include execution attempt id in the completed successful run manifest
            # document result.
            "execution_attempt_id": self.execution_attempt_id.hex,
            "input_artifact_ids": [item.hex for item in self.input_artifact_ids],
            "logical_run_id": self.logical_run_id.hex,
            "physical_settings": self.physical_settings.document(),
            "resolved_run_spec": self.resolved_spec.document(),
            # Include result tables in the completed successful run manifest document
            # result.
            "result_tables": [item.document() for item in self.result_tables],
            "started_at": _utc_text(self.started_at),
            "summary": self.bounded_summary.document(),
            "warnings": list(self.warnings),
        }

    # Define successful run manifest identity document as one focused operation with an
    # explicit boundary.
    def identity_document(self) -> dict[str, object]:
        # Execute the successful run manifest identity document workflow in explicit,
        # reviewable steps.
        document = self.document()
        return {
            key: document[key]
            for key in (
                "artifact_schema",
                # Include attempt nonce in the completed successful run manifest identity
                # document result.
                "attempt_nonce",
                "canonicality",
                "execution_attempt_id",
                "input_artifact_ids",
                "logical_run_id",
                # Include physical settings in the completed successful run manifest
                # identity document result.
                "physical_settings",
                "resolved_run_spec",
                "result_tables",
                "summary",
                "warnings",
                # Return the completed successful run manifest identity document result
                # without a hidden fallback.
            )
        }

    def manifest_bytes(self) -> bytes:
        # Execute the successful run manifest manifest bytes workflow in explicit,
        # reviewable steps.
        payload = canonical_json_bytes(self.document())
        if len(payload) > MAX_SUCCESSFUL_RUN_MANIFEST_BYTES:
            raise ValueError("successful run manifest exceeds the bounded metadata limit")
        return payload

    def identity_bytes(self) -> bytes:
        # Execute the successful run manifest identity bytes workflow in explicit,
        # reviewable steps.
        payload = canonical_json_bytes(self.identity_document())
        if len(payload) > MAX_SUCCESSFUL_RUN_MANIFEST_BYTES:
            raise ValueError("successful run identity exceeds the bounded metadata limit")
        return payload


def successful_run_manifest_from_bytes(payload: bytes) -> SuccessfulRunManifest:
    """Strictly reconstruct v3 and cleanly reject the pre-network v2 schema."""

    if not payload or len(payload) > MAX_SUCCESSFUL_RUN_MANIFEST_BYTES:
        raise ValueError("successful run manifest is empty or exceeds the bounded limit")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        # Fail the successful run manifest from bytes path with ValueError for successful
        # run manifest is invalid json; do not continue ambiguously.
        raise ValueError("successful run manifest is invalid JSON") from error
    document = _object(value, "successful run manifest")
    if document.get("artifact_schema") == "successful-run/v2":
        raise ReprepareRequiredError("successful-run/v2")
    if canonical_json_bytes(document) != payload:
        # Fail the successful run manifest from bytes path with ValueError for successful
        # run manifest must use canonical json when payload, canonical json bytes and
        # document is true; do not continue ambiguously.
        raise ValueError("successful run manifest must use canonical JSON")
    expected = {
        "artifact_schema",
        "attempt_nonce",
        "canonicality",
        # Keep the completed at component named inside the expected contract.
        "completed_at",
        "execution_attempt_id",
        "input_artifact_ids",
        "logical_run_id",
        "physical_settings",
        # Keep the resolved run spec component named inside the expected contract.
        "resolved_run_spec",
        "result_tables",
        "started_at",
        "summary",
        "warnings",
        # Complete the expected group only after its semantic components are visible.
    }
    if set(document) != expected or document["artifact_schema"] != SUCCESSFUL_RUN_SCHEMA:
        raise ValueError("successful run manifest schema is invalid")
    if document["canonicality"] != ReplayContract.CANONICAL_EXACT.value:
        raise ValueError("successful run manifest is not canonical exact v3")
    # Assemble spec once so the successful run manifest from bytes workflow shares one
    # value.
    spec = resolved_run_spec_from_bytes(
        canonical_json_bytes(_object(document["resolved_run_spec"], "resolved run spec"))
    )
    manifest = SuccessfulRunManifest(
        resolved_spec=spec,
        # Keep the content digest and string ContentDigest step visible while building
        # manifest.
        attempt_nonce=ContentDigest(_string(document["attempt_nonce"], "attempt nonce")),
        execution_attempt_id=ExecutionAttemptId(
            _string(document["execution_attempt_id"], "execution attempt ID")
        ),
        input_artifact_ids=tuple(
            # Keep the artifact id and string ArtifactId step visible while building
            # manifest.
            ArtifactId(_string(item, "run input artifact ID"))
            for item in _list(document["input_artifact_ids"], "run input artifact IDs")
        ),
        summary=_summary_metadata_from_document(document["summary"]),
        physical_settings=RunPhysicalSettings.from_document(document["physical_settings"]),
        # Keep the timestamp and document _timestamp step visible while building manifest.
        started_at=_timestamp(document["started_at"], "run started_at"),
        completed_at=_timestamp(document["completed_at"], "run completed_at"),
        warnings=tuple(
            _string(item, "run warning") for item in _list(document["warnings"], "run warnings")
        ),
        # Keep the from document and item tuple step visible while building manifest.
        result_tables=tuple(
            ResultTableDescriptor.from_document(item)
            for item in _list(document["result_tables"], "run result tables")
        ),
    )
    # Evaluate the complete successful run manifest from bytes hex, document and logical
    # run id condition before guarded effects.
    if document["logical_run_id"] != manifest.logical_run_id.hex:
        raise ValueError("successful run logical identity differs from its resolved spec")
    if manifest.document() != document:
        raise ValueError("successful run manifest does not round-trip exactly")
    return manifest


# Define summary metadata as one focused operation with an explicit boundary.
def _copy_summary_metadata(summary: CopyRunSummary) -> CopySummaryMetadata:
    """Discard unbounded in-memory balance rows when constructing the manifest projection."""
    balances = validate_final_balances(summary.final_balances)
    digest = _stream_digest("backtest.copy-final-balances.v1", [list(row) for row in balances])
    if digest != summary.final_balances_digest:
        raise ValueError("copy final balance rows differ from the engine digest")
    # Scalar comparison data is materialized only after independently checking balance bytes.
    totals = summary.totals
    failed = totals.failed_buy_count + totals.failed_sell_count
    comparison = RunComparisonProjection(
        canonical_result_hash=summary.result_hash,
        audit_hash=summary.audit_hash,
        # Each stream has an independently verified digest and count in the output writer.
        ledger_hash=summary.ledger_hash,
        fill_hash=summary.fill_hash,
        historical_group_count=summary.historical_group_count,
        historical_event_count=summary.historical_event_count,
        delivered_event_count=summary.delivered_event_count,
        # Accepted order counts include paid landed failures but exclude free rejections.
        accepted_order_count=summary.fill_count + failed,
        # Rejections carry no fee; failed accepted orders paid their network costs.
        rejected_order_count=totals.rejected_buy_count + totals.rejected_sell_count,
        filled_order_count=summary.fill_count,
        failed_order_count=failed,
        ledger_transaction_count=summary.ledger_transaction_count,
        fill_count=summary.fill_count,
        # Final balances are external content with their own bounded descriptor count.
        final_balances_count=len(summary.final_balances),
        final_balances_digest=summary.final_balances_digest,
    )
    # Copy metadata pins every runtime component beside its exact stream digests.
    return CopySummaryMetadata(
        summary.dataset_logical_content_hash,
        summary.replay_semantics_id,
        summary.config.engine_bundle_id,
        summary.config.strategy_bundle_id,
        # Preserve all code identities while excluding physical batching and paths.
        summary.config.protocol_bundle_id,
        summary.config.network_cost_bundle_id,
        summary.config.execution_mode,
        comparison,
        totals,
        # Position framing remains independent of scalar financial totals.
        summary.roundtrip_digest,
    )


def copy_summary_from_document(document: dict[str, object]) -> CopySummaryMetadata:
    """Reconstruct the closed copy schema and reject altered counters or unknown fields."""
    raw_totals = _object(document.get("totals"), "copy totals")
    totals = CopyFinancialTotals(
        **{
            field.name: _integer(raw_totals.get(field.name), field.name)
            for field in fields(CopyFinancialTotals)
            # Construct only the declared integer aggregate fields; extra fields fail round-trip
            # equality.
        }
    )
    # The constructor checks fee/funding/count conservation; exact roundtrip checks schema extras.
    summary = CopySummaryMetadata(
        ContentDigest(
            _string(document.get("dataset_logical_content_hash"), "copy logical content")
        ),
        ContentDigest(_string(document.get("replay_semantics_id"), "copy replay semantics")),
        # Runtime bundle identities remain explicit in decoded committed metadata.
        BundleId(_string(document.get("engine_bundle_id"), "copy engine bundle")),
        BundleId(_string(document.get("strategy_bundle_id"), "copy strategy bundle")),
        # Bundle and mode tags remain mandatory for a verified result reader.
        BundleId(_string(document.get("protocol_bundle_id"), "copy protocol bundle")),
        BundleId(_string(document.get("network_cost_bundle_id"), "copy cost bundle")),
        ExecutionMode(_string(document.get("execution_mode"), "copy mode")),
        RunComparisonProjection.from_document(document.get("comparison")),
        totals,
        # The position digest binds all immutable terminal rows independently of the summary.
        ContentDigest(_string(document.get("position_digest"), "copy position digest")),
    )
    if summary.document() != document:
        raise ValueError("copy summary does not round-trip exactly")
    return summary


def _summary_metadata(
    summary: RunSummary | SnipingRunSummary | CopyRunSummary,
) -> SuccessfulRunSummary:
    # Execute the summary metadata workflow in explicit, reviewable steps.
    if isinstance(summary, CopyRunSummary):
        return _copy_summary_metadata(summary)
    comparison = RunComparisonProjection.from_summary(summary)
    if isinstance(summary, RunSummary):
        # Handle the summary metadata isinstance(summary, RunSummary) branch as a distinct
        # logical block.
        return FirstSwapSummaryMetadata(
            ContentDigest(summary.dataset_logical_content_hash.hex),
            summary.replay_semantics_id,
            BundleId(summary.engine_bundle_id.hex),
            BundleId(summary.latency_bundle_id.hex),
            # Pass comparison explicitly so FirstSwapSummaryMetadata receives a reviewable
            # hex and dataset logical content hash input in summary metadata.
            comparison,
        )
    return PumpfunSnipingSummaryMetadata(
        dataset_logical_content_hash=ContentDigest(summary.dataset_logical_content_hash.hex),
        replay_semantics_id=summary.replay_semantics_id,
        # Pass engine bundle id explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable hex and dataset logical content hash input in summary metadata.
        engine_bundle_id=summary.engine_bundle_id,
        strategy_bundle_id=summary.strategy_bundle_id,
        protocol_bundle_id=summary.protocol_bundle_id,
        network_cost_bundle_id=summary.network_cost_bundle_id,
        comparison=comparison,
        # Pass target count explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable hex and dataset logical content hash input in summary metadata.
        target_count=summary.target_count,
        cooldown_skipped_count=summary.cooldown_skipped_count,
        accepted_buy_count=summary.accepted_buy_count,
        closed_roundtrip_count=summary.closed_roundtrip_count,
        open_position_count=summary.open_position_count,
        # Pass failed buy count explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable hex and dataset logical content hash input in summary metadata.
        failed_buy_count=summary.failed_buy_count,
        failed_sell_count=summary.failed_sell_count,
        roundtrip_count=summary.roundtrip_count,
        roundtrip_digest=summary.roundtrip_digest,
        realized_cash_pnl_atomic=summary.realized_cash_pnl_atomic,
        # Pass valuation status explicitly so PumpfunSnipingSummaryMetadata receives a
        # reviewable hex and dataset logical content hash input in summary metadata.
        valuation_status=summary.valuation_status,
        unvalued_open_position_count=summary.unvalued_open_position_count,
        valued_economic_pnl_subtotal_atomic=(summary.valued_economic_pnl_subtotal_atomic),
        economic_pnl_atomic=summary.economic_pnl_atomic,
        cashback_receivable_atomic=summary.cashback_receivable_atomic,
        # Pass protocol fee paid atomic explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable hex and dataset logical content hash input in summary
        # metadata.
        protocol_fee_paid_atomic=summary.protocol_fee_paid_atomic,
        creator_fee_paid_atomic=summary.creator_fee_paid_atomic,
        network_base_fee_paid_atomic=summary.network_base_fee_paid_atomic,
        network_priority_fee_paid_atomic=summary.network_priority_fee_paid_atomic,
        account_deposit_paid_atomic=summary.account_deposit_paid_atomic,
        # Pass account deposit refunded atomic explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable hex and dataset logical content hash input in summary
        # metadata.
        account_deposit_refunded_atomic=summary.account_deposit_refunded_atomic,
        account_deposit_locked_atomic=summary.account_deposit_locked_atomic,
        favorable_slippage_count=summary.favorable_slippage_count,
        adverse_slippage_count=summary.adverse_slippage_count,
        buy_slippage_failure_count=summary.buy_slippage_failure_count,
        # Persist mode-specific liquidity aggregates from the authoritative engine summary.
        execution_mode=summary.execution_mode,
        settlement_policy_id=summary.settlement_policy_id,
        filled_sell_count=summary.filled_sell_count,
        real_liquidity_sufficient_filled_sell_count=(
            summary.real_liquidity_sufficient_filled_sell_count
        ),
        synthetic_liquidity_used_sell_count=summary.synthetic_liquidity_used_sell_count,
        gross_sell_settlement_atomic=summary.gross_sell_settlement_atomic,
        venue_funded_sell_atomic=summary.venue_funded_sell_atomic,
        synthetic_funded_sell_atomic=summary.synthetic_funded_sell_atomic,
        # Pass sell slippage failure count explicitly so PumpfunSnipingSummaryMetadata
        # receives a reviewable hex and dataset logical content hash input in summary
        # metadata.
        sell_slippage_failure_count=summary.sell_slippage_failure_count,
    )


def _summary_metadata_from_document(value: object) -> SuccessfulRunSummary:
    # Execute the summary metadata from document workflow in explicit, reviewable steps.
    document = _object(value, "run summary")
    schema = document.get("schema")
    if schema == "pumpfun-copy-run-summary/v1":
        return copy_summary_from_document(document)
    if schema == FIRST_SWAP_SUMMARY_SCHEMA:
        # Handle the summary metadata from document schema == FIRST_SWAP_SUMMARY_SCHEMA
        # branch as a distinct logical block.
        expected = {
            "comparison",
            "dataset_logical_content_hash",
            "engine_bundle_id",
            "latency_bundle_id",
            # Keep the replay semantics id component named inside the expected contract.
            "replay_semantics_id",
            "schema",
        }
        if set(document) != expected:
            raise ValueError("FirstSwap run summary schema is invalid")
        # Return the completed summary metadata from document result without a hidden
        # fallback.
        return FirstSwapSummaryMetadata(
            ContentDigest(
                _string(document["dataset_logical_content_hash"], "dataset logical content hash")
            ),
            ContentDigest(_string(document["replay_semantics_id"], "replay semantics ID")),
            # Include bundle id in the completed summary metadata from document result.
            BundleId(_string(document["engine_bundle_id"], "engine bundle ID")),
            BundleId(_string(document["latency_bundle_id"], "latency bundle ID")),
            RunComparisonProjection.from_document(document["comparison"]),
        )
    if schema in {
        LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA,
        PUMPFUN_SNIPING_SUMMARY_SCHEMA,
    }:
        # The legacy branch is strict to its original fields and never upgrades bytes.
        legacy_expected = {
            "accepted_buy_count",
            "account_deposit_locked_atomic",
            "account_deposit_paid_atomic",
            "account_deposit_refunded_atomic",
            # Keep the adverse slippage count component named inside the expected
            # contract.
            "adverse_slippage_count",
            "buy_slippage_failure_count",
            "cashback_receivable_atomic",
            "closed_roundtrip_count",
            "comparison",
            # Keep the cooldown skipped count component named inside the expected
            # contract.
            "cooldown_skipped_count",
            "creator_fee_paid_atomic",
            "dataset_logical_content_hash",
            "economic_pnl_atomic",
            "engine_bundle_id",
            # Keep the failed buy count component named inside the expected contract.
            "failed_buy_count",
            "failed_sell_count",
            "favorable_slippage_count",
            "network_cost_bundle_id",
            "network_base_fee_paid_atomic",
            # Keep the network priority fee paid atomic component named inside the
            # expected contract.
            "network_priority_fee_paid_atomic",
            "open_position_count",
            "protocol_bundle_id",
            "protocol_fee_paid_atomic",
            "realized_cash_pnl_atomic",
            # Keep the replay semantics id component named inside the expected contract.
            "replay_semantics_id",
            "roundtrip_count",
            "roundtrip_digest",
            "schema",
            "sell_slippage_failure_count",
            # Keep the strategy bundle id component named inside the expected contract.
            "strategy_bundle_id",
            "target_count",
            "unvalued_open_position_count",
            "valuation_status",
            "valued_economic_pnl_subtotal_atomic",
            # Complete the expected group only after its semantic components are visible.
        }
        v3_expected = legacy_expected | {
            "execution_mode",
            "filled_sell_count",
            "gross_sell_settlement_atomic",
            "real_liquidity_sufficient_filled_sell_count",
            "settlement_policy_id",
            "synthetic_funded_sell_atomic",
            "synthetic_liquidity_used_sell_count",
            "venue_funded_sell_atomic",
        }
        expected = v3_expected if schema == PUMPFUN_SNIPING_SUMMARY_SCHEMA else legacy_expected
        if set(document) != expected:
            raise ValueError("Pump.fun Sniping run summary schema is invalid")
        return PumpfunSnipingSummaryMetadata(
            dataset_logical_content_hash=ContentDigest(
                # Include string in the completed summary metadata from document result.
                _string(document["dataset_logical_content_hash"], "dataset logical content hash")
            ),
            replay_semantics_id=ContentDigest(
                _string(document["replay_semantics_id"], "replay semantics ID")
            ),
            # Include engine bundle id in the completed summary metadata from document
            # result.
            engine_bundle_id=BundleId(_string(document["engine_bundle_id"], "engine bundle ID")),
            strategy_bundle_id=BundleId(
                _string(document["strategy_bundle_id"], "strategy bundle ID")
            ),
            protocol_bundle_id=BundleId(
                # Include string in the completed summary metadata from document result.
                _string(document["protocol_bundle_id"], "protocol bundle ID")
            ),
            network_cost_bundle_id=BundleId(
                _string(document["network_cost_bundle_id"], "network cost bundle ID")
            ),
            # Include comparison in the completed summary metadata from document result.
            comparison=RunComparisonProjection.from_document(document["comparison"]),
            target_count=_non_negative_integer(document["target_count"], "target count"),
            cooldown_skipped_count=_non_negative_integer(
                document["cooldown_skipped_count"], "cooldown skipped count"
            ),
            # Include accepted buy count in the completed summary metadata from document
            # result.
            accepted_buy_count=_non_negative_integer(
                document["accepted_buy_count"], "accepted buy count"
            ),
            closed_roundtrip_count=_non_negative_integer(
                document["closed_roundtrip_count"],
                # Pass closed roundtrip count explicitly so _non_negative_integer receives
                # a reviewable closed roundtrip count and document input in summary
                # metadata from document.
                "closed roundtrip count",
                # Complete _non_negative_integer only after its closed roundtrip count and
                # document inputs are visible in summary metadata from document.
            ),
            open_position_count=_non_negative_integer(
                document["open_position_count"], "open position count"
            ),
            failed_buy_count=_non_negative_integer(
                # Pass document explicitly so _non_negative_integer receives a reviewable
                # failed buy count and document input in summary metadata from document.
                document["failed_buy_count"],
                "failed buy count",
            ),
            failed_sell_count=_non_negative_integer(
                document["failed_sell_count"],
                # Pass failed sell count explicitly so _non_negative_integer receives a
                # reviewable failed sell count and document input in summary metadata from
                # document.
                "failed sell count",
                # Complete _non_negative_integer only after its failed sell count and document
                # inputs are visible in summary metadata from document.
            ),
            # Include roundtrip count in the completed summary metadata from document
            # result.
            roundtrip_count=_non_negative_integer(document["roundtrip_count"], "roundtrip count"),
            roundtrip_digest=ContentDigest(
                _string(document["roundtrip_digest"], "roundtrip digest")
            ),
            realized_cash_pnl_atomic=_integer(
                # Pass document explicitly so _integer receives a reviewable realized cash
                # pnl atomic and realized cash pn l input in summary metadata from
                # document.
                document["realized_cash_pnl_atomic"],
                "realized cash PnL",
            ),
            valuation_status=SnipingValuationStatus(
                _string(document["valuation_status"], "valuation status")
                # Complete SnipingValuationStatus only after its valuation status and string
                # inputs are visible in summary metadata from document.
            ),
            # Include unvalued open position count in the completed summary metadata from
            # document result.
            unvalued_open_position_count=_non_negative_integer(
                document["unvalued_open_position_count"], "unvalued open position count"
            ),
            valued_economic_pnl_subtotal_atomic=_integer(
                document["valued_economic_pnl_subtotal_atomic"],
                # Pass valued economic pn l subtotal explicitly so _integer receives a
                # reviewable valued economic pnl subtotal atomic and valued economic pn l
                # subtotal input in summary metadata from document.
                "valued economic PnL subtotal",
            ),
            economic_pnl_atomic=_optional_integer(document["economic_pnl_atomic"], "economic PnL"),
            cashback_receivable_atomic=_non_negative_integer(
                document["cashback_receivable_atomic"],
                # Pass cashback receivable explicitly so _non_negative_integer receives a
                # reviewable cashback receivable atomic and cashback receivable input in
                # summary metadata from document.
                "cashback receivable",
                # Complete _non_negative_integer only after its cashback receivable atomic and
                # cashback receivable inputs are visible in summary metadata from document.
            ),
            protocol_fee_paid_atomic=_non_negative_integer(
                document["protocol_fee_paid_atomic"], "protocol fee paid"
            ),
            creator_fee_paid_atomic=_non_negative_integer(
                # Pass document explicitly so _non_negative_integer receives a reviewable
                # creator fee paid atomic and creator fee paid input in summary metadata
                # from document.
                document["creator_fee_paid_atomic"],
                "creator fee paid",
            ),
            network_base_fee_paid_atomic=_non_negative_integer(
                document["network_base_fee_paid_atomic"],
                # Pass network base fee paid explicitly so _non_negative_integer receives
                # a reviewable network base fee paid atomic and network base fee paid
                # input in summary metadata from document.
                "network base fee paid",
                # Complete _non_negative_integer only after its network base fee paid atomic
                # and network base fee paid inputs are visible in summary metadata from
                # document.
            ),
            # Include network priority fee paid atomic in the completed summary metadata
            # from document result.
            network_priority_fee_paid_atomic=_non_negative_integer(
                document["network_priority_fee_paid_atomic"], "network priority fee paid"
            ),
            account_deposit_paid_atomic=_non_negative_integer(
                document["account_deposit_paid_atomic"],
                # Pass account deposit paid explicitly so _non_negative_integer receives a
                # reviewable account deposit paid atomic and account deposit paid input in
                # summary metadata from document.
                "account deposit paid",
                # Complete _non_negative_integer only after its account deposit paid atomic
                # and account deposit paid inputs are visible in summary metadata from
                # document.
            ),
            account_deposit_refunded_atomic=_non_negative_integer(
                document["account_deposit_refunded_atomic"], "account deposit refunded"
            ),
            account_deposit_locked_atomic=_non_negative_integer(
                # Pass document explicitly so _non_negative_integer receives a reviewable
                # account deposit locked atomic and account deposit locked input in
                # summary metadata from document.
                document["account_deposit_locked_atomic"],
                "account deposit locked",
            ),
            favorable_slippage_count=_non_negative_integer(
                document["favorable_slippage_count"],
                # Pass favorable slippage count explicitly so _non_negative_integer
                # receives a reviewable favorable slippage count and document input in
                # summary metadata from document.
                "favorable slippage count",
                # Complete _non_negative_integer only after its favorable slippage count and
                # document inputs are visible in summary metadata from document.
            ),
            # Include adverse slippage count in the completed summary metadata from
            # document result.
            adverse_slippage_count=_non_negative_integer(
                document["adverse_slippage_count"], "adverse slippage count"
            ),
            buy_slippage_failure_count=_non_negative_integer(
                document["buy_slippage_failure_count"],
                # Pass buy slippage failure count explicitly so _non_negative_integer
                # receives a reviewable buy slippage failure count and document input in
                # summary metadata from document.
                "buy slippage failure count",
                # Complete _non_negative_integer only after its buy slippage failure count and
                # document inputs are visible in summary metadata from document.
            ),
            sell_slippage_failure_count=_non_negative_integer(
                document["sell_slippage_failure_count"], "sell slippage failure count"
            ),
            # V2 had one fixed real-reserve execution mode and no aggregate funding totals.
            execution_mode=(
                ExecutionMode.EXOGENOUS_REPLAY
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else ExecutionMode(_string(document["execution_mode"], "execution mode"))
            ),
            settlement_policy_id=(
                "real-reserve-capped-v1"
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _string(document["settlement_policy_id"], "settlement policy ID")
            ),
            filled_sell_count=(
                _non_negative_integer(document["closed_roundtrip_count"], "closed round trips")
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(document["filled_sell_count"], "filled sell count")
            ),
            real_liquidity_sufficient_filled_sell_count=(
                _non_negative_integer(document["closed_roundtrip_count"], "closed round trips")
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(
                    document["real_liquidity_sufficient_filled_sell_count"],
                    "real-liquidity-sufficient filled sell count",
                )
            ),
            synthetic_liquidity_used_sell_count=(
                0
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(
                    document["synthetic_liquidity_used_sell_count"],
                    "synthetic-liquidity-used sell count",
                )
            ),
            # Legacy summaries cannot invent amount aggregates absent from committed bytes.
            gross_sell_settlement_atomic=(
                0
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(
                    document["gross_sell_settlement_atomic"], "gross sell settlement"
                )
            ),
            venue_funded_sell_atomic=(
                0
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(
                    document["venue_funded_sell_atomic"], "venue-funded sell settlement"
                )
            ),
            synthetic_funded_sell_atomic=(
                0
                if schema == LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA
                else _non_negative_integer(
                    document["synthetic_funded_sell_atomic"],
                    "synthetic-funded sell settlement",
                )
            ),
            source_schema_id=schema,
        )
    # Fail the summary metadata from document path with ValueError for unsupported run
    # summary schema; do not continue ambiguously.
    raise ValueError("unsupported run summary schema")


def _validate_summary_against_spec(summary: SuccessfulRunSummary, spec: ResolvedRunSpec) -> None:
    # Execute the validate summary against spec workflow in explicit, reviewable steps.
    if summary.dataset_logical_content_hash.hex != spec.logical_content_hash.hex:
        raise ValueError("run summary logical content differs from resolved input")
    if summary.replay_semantics_id != spec.replay_semantics_id:
        raise ValueError("run summary replay semantics differs from resolved input")
    components = {item.role: item for item in spec.components}
    # Evaluate the complete validate summary against spec engine bundle id, bundle id and
    # summary condition before guarded effects.
    if summary.engine_bundle_id != components["engine"].bundle_id:
        raise ValueError("run summary engine bundle differs from resolved input")
    if isinstance(summary, FirstSwapSummaryMetadata):
        # Handle the validate summary against spec summary first swap summary metadata
        # type condition as a distinct block.
        if summary.latency_bundle_id != components["latency"].bundle_id:
            raise ValueError("run summary latency bundle differs from resolved input")
        return
    if summary.strategy_bundle_id != components["strategy"].bundle_id:
        raise ValueError("sniping summary strategy bundle differs from resolved input")
    # Evaluate the complete validate summary against spec protocol bundle id, bundle id
    # and summary condition before guarded effects.
    if summary.protocol_bundle_id != components["protocol:pumpfun"].bundle_id:
        raise ValueError("sniping summary protocol bundle differs from resolved input")
    if summary.network_cost_bundle_id != components["network:solana"].bundle_id:
        raise ValueError("sniping summary network bundle differs from resolved input")
    if summary.execution_mode is not spec.execution_mode():
        raise ValueError("sniping summary execution mode differs from resolved input")


def _validate_result_tables(
    # Keep the summary input explicit in the validate result tables contract.
    summary: SuccessfulRunSummary,
    tables: tuple[ResultTableDescriptor, ...],
) -> None:
    # Execute the validate result tables workflow in explicit, reviewable steps.
    by_role = {item.role: item for item in tables}
    balances = by_role[RunResultTableRole.FINAL_BALANCES]
    if (
        balances.row_count != summary.comparison.final_balances_count
        or balances.canonical_digest != summary.comparison.final_balances_digest
        # Evaluate the complete validate result tables row count, final balances count and
        # canonical digest condition before guarded effects.
    ):
        raise ValueError("final balance descriptor differs from the bounded summary")
    roundtrips = by_role[RunResultTableRole.ROUNDTRIPS]
    expected_count = 0
    expected_digest = _empty_stream_digest(_FIRST_SWAP_ROUNDTRIP_DIGEST_DOMAIN)
    # Evaluate the complete validate result tables summary pumpfun sniping summary
    # metadata type condition before guarded effects.
    if isinstance(summary, (PumpfunSnipingSummaryMetadata, CopySummaryMetadata)):
        # Handle the validate result tables summary pumpfun sniping summary metadata type
        # condition as a distinct block.
        expected_count = summary.roundtrip_count
        expected_digest = summary.roundtrip_digest
    expected_schema = _roundtrip_schema_for_summary(summary)
    if roundtrips.schema_id != expected_schema:
        raise ValueError("roundtrip descriptor schema differs from its summary generation")
    if roundtrips.row_count != expected_count or roundtrips.canonical_digest != expected_digest:
        raise ValueError("roundtrip descriptor differs from the bounded summary")


def _result_tables_for_summary(
    # Keep the summary input explicit in the result tables for summary contract.
    summary: SuccessfulRunSummary,
) -> tuple[ResultTableDescriptor, ...]:
    # Execute the result tables for summary workflow in explicit, reviewable steps.
    roundtrip_count = 0
    roundtrip_digest = _empty_stream_digest(_FIRST_SWAP_ROUNDTRIP_DIGEST_DOMAIN)
    if isinstance(summary, (PumpfunSnipingSummaryMetadata, CopySummaryMetadata)):
        # Handle the result tables for summary summary pumpfun sniping summary metadata
        # type condition as a distinct block.
        roundtrip_count = summary.roundtrip_count
        roundtrip_digest = summary.roundtrip_digest
    return tuple(
        sorted(
            (
                # Include result descriptor in the completed result tables for summary
                # result.
                _result_descriptor(
                    RunResultTableRole.FINAL_BALANCES,
                    summary.comparison.final_balances_count,
                    summary.comparison.final_balances_digest,
                ),
                # Include result descriptor in the completed result tables for summary
                # result.
                _result_descriptor(
                    RunResultTableRole.ROUNDTRIPS,
                    roundtrip_count,
                    roundtrip_digest,
                    schema_id=_roundtrip_schema_for_summary(summary),
                ),
                # Complete sorted only after its final balances and final balances count
                # inputs are visible in result tables for summary.
            ),
            key=lambda item: item.role.value,
        )
    )


def _result_descriptor(
    # Keep the role input explicit in the result descriptor contract.
    role: RunResultTableRole,
    row_count: int,
    digest: ContentDigest,
    *,
    schema_id: str | None = None,
) -> ResultTableDescriptor:
    # Execute the result descriptor workflow in explicit, reviewable steps.
    relative_name, default_schema_id = _RESULT_TABLE_CONTRACT[role]
    selected_schema_id = default_schema_id if schema_id is None else schema_id
    return ResultTableDescriptor(role, selected_schema_id, relative_name, row_count, digest)


def _roundtrip_schema_for_summary(summary: SuccessfulRunSummary) -> str:
    """Select a table generation without upgrading committed legacy manifests."""

    if isinstance(summary, CopySummaryMetadata):
        return COPY_POSITION_SCHEMA
    if (
        isinstance(summary, PumpfunSnipingSummaryMetadata)
        and summary.source_schema_id == PUMPFUN_SNIPING_SUMMARY_SCHEMA
        # Old Sniping roots continue to select their original v3 or v4 row codec.
    ):
        return ROUNDTRIP_RESULT_SCHEMA_V4
    return ROUNDTRIP_RESULT_SCHEMA_V3


def _stream_digest(domain: str, values: Sequence[object]) -> ContentDigest:
    # Execute the stream digest workflow in explicit, reviewable steps.
    digest = hashlib.sha256(domain.encode("utf-8") + b"\x00")
    for value in values:
        # Process values inside the bounded stream digest loop.
        encoded = canonical_json_bytes(value)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return ContentDigest(digest.hexdigest())


def _empty_stream_digest(domain: str) -> ContentDigest:
    # Return the completed empty stream digest result without a hidden fallback.
    return ContentDigest(hashlib.sha256(domain.encode("utf-8") + b"\x00").hexdigest())


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _require_nonempty_trimmed(field: str, value: str) -> None:
    """Keep semantic identifiers stable and safe for canonical JSON."""

    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be non-empty, trimmed and NUL-free")


def _list(value: object, field: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return cast(list[object], value)


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    # Execute the optional integer workflow in explicit, reviewable steps.
    if value is None:
        return None
    return _integer(value, field)


def _non_negative_integer(value: object, field: str) -> int:
    # Execute the non negative integer workflow in explicit, reviewable steps.
    result = _integer(value, field)
    if result < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return result


def _positive_integer(value: object, field: str) -> int:
    # Execute the positive integer workflow in explicit, reviewable steps.
    result = _integer(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return result


def _require_result_row_count(value: int, field: str) -> None:
    # Execute the require result row count workflow in explicit, reviewable steps.
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_RESULT_TABLE_ROWS
    ):
        # Fail the require result row count path with ValueError for must fit unsigned
        # 64-bit and field when isinstance, value and max result table rows is true; do
        # not continue ambiguously.
        raise ValueError(f"{field} must fit unsigned 64-bit")


def _timestamp(value: object, field: str) -> datetime:
    # Execute the timestamp workflow in explicit, reviewable steps.
    raw = _string(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO timestamp") from error
    # Evaluate the complete timestamp tzinfo, parsed and utcoffset condition before
    # guarded effects.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


__all__ = [
    "FIRST_SWAP_SUMMARY_SCHEMA",
    "LEGACY_PUMPFUN_SNIPING_SUMMARY_SCHEMA",
    # Keep the max comparison final balances component named inside the all contract.
    "MAX_COMPARISON_FINAL_BALANCES",
    "MAX_COMPARISON_LABEL_LENGTH",
    "MAX_RESULT_TABLE_ROWS",
    "MAX_RUN_WARNINGS",
    "MAX_RUN_WARNING_LENGTH",
    # Keep the max successful run manifest bytes component named inside the all contract.
    "MAX_SUCCESSFUL_RUN_MANIFEST_BYTES",
    "PUMPFUN_SNIPING_SUMMARY_SCHEMA",
    "RESULT_TABLE_DESCRIPTOR_SCHEMA",
    "RUN_PHYSICAL_SETTINGS_SCHEMA",
    "SUCCESSFUL_RUN_SCHEMA",
    # Keep the supported reader readahead component named inside the all contract.
    "SUPPORTED_READER_READAHEAD",
    "FirstSwapSummaryMetadata",
    "PumpfunSnipingSummaryMetadata",
    "ResultTableDescriptor",
    "RunBackend",
    # Keep the run comparison metric component named inside the all contract.
    "RunComparisonMetric",
    "RunComparisonProjection",
    "RunPhysicalSettings",
    "RunResultTableRole",
    "SuccessfulRunManifest",
    # Keep the successful run summary component named inside the all contract.
    "SuccessfulRunSummary",
    "normalize_comparison_metrics",
    "successful_run_manifest_from_bytes",
    "validate_final_balances",
    "validate_run_warnings",
    # Complete the all group only after its semantic components are visible.
]
