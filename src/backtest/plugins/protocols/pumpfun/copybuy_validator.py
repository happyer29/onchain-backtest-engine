"""Read-only proof of the complete copy settlement path before snapshot-root publication."""

from backtest.application.copy_source_contracts import require_copy_source_contract
from backtest.application.errors import SnapshotValidationError, SnapshotValidationErrorCode
from backtest.application.models import (
    CapabilityStream,
    CopyBuySettlementRequirement,
    # The separate copy settlement schema proves every possible exit retry.
    DatasetSpec,
    PlannedCapability,
)
from backtest.application.ports.canonical import CanonicalSnapshotCandidate
from backtest.application.source_evidence import PumpfunCopyBuySourceEvidenceBinding

# The immutable binding identifies the exact selected wallets and source coverage.
# Core supplies deterministic grouping and the exact full four-attempt clock path.
from backtest.domain.identifiers import AssetId, CapabilityId
from backtest.domain.market_events import CanonicalEvent, EventKind, TokenLaunchEvent
from backtest.engine.copytrading import copy_event_groups
from backtest.engine.copytrading_state import maximum_copy_settlement_position
from backtest.engine.sniping_contracts import ProtocolContractError

# Clock failures distinguish malformed history from an insufficient right tail.
from backtest.engine.transaction_clock import TransactionClockError, TransactionClockErrorCode

# This protocol reducer is disposable validation state, never strategy or portfolio state.
from backtest.plugins.protocols.pumpfun.copybuy import PumpfunCopyBuyProtocolRuntime
from backtest.plugins.protocols.pumpfun.copybuy_coverage import CopySignalCoverage
from backtest.plugins.protocols.pumpfun.model import PumpFeeProfile

# A capability cannot supply events from another semantic stream.
_KINDS = {
    CapabilityStream.BLOCK_CLOCK: EventKind.BLOCK,
    CapabilityStream.TOKEN_LAUNCH: EventKind.TOKEN_LAUNCH,
    CapabilityStream.PUMP_CURVE_TRADE: EventKind.VENUE_TRADE,
    # Lifecycle events prove terminal state but cannot replace market trade events.
    CapabilityStream.PUMP_CURVE_LIFECYCLE: EventKind.VENUE_LIFECYCLE,
}


class PumpfunCopySnapshotValidator:
    """A valid source receipt is necessary but does not prove the local settlement tail."""

    def validate_snapshot_candidate(
        self, spec: DatasetSpec, candidate: CanonicalSnapshotCandidate
    ) -> None:
        """Reject identity, stream, actor, state or duration gaps before publishing the root."""
        require_copy_source_contract(spec)
        binding, requirement = spec.source_evidence_binding, spec.settlement_requirement
        if not isinstance(binding, PumpfunCopyBuySourceEvidenceBinding) or not isinstance(
            requirement, CopyBuySettlementRequirement
        ):
            # Signerless source evidence cannot authorize a copy snapshot.
            raise SnapshotValidationError(SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID)
        # Candidate bytes must belong to the same immutable network and position schema.
        if (candidate.network_id, candidate.position_schema_id) != (
            spec.network_id,
            spec.position_schema_id,
        ):
            raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_POSITION_INVALID)
        # Clock identity is independently checked rather than inferred from candidate metadata.
        clock = candidate.transaction_clock()
        if (clock.network_id, clock.position_schema_id) != (
            spec.network_id,
            spec.position_schema_id,
        ):
            # Settlement duration and global transaction counts must use this exact chain clock.
            raise SnapshotValidationError(SnapshotValidationErrorCode.CLOCK_INVALID)
        expected = binding.copy_coverage
        coverage = CopySignalCoverage(
            expected.selection, maximum_mints=max(1, expected.eligible_mints)
        )
        # Every eligible Pump capability must refer to one supported program version.
        versions = {
            item.protocol_version
            for item in spec.capabilities
            if item.stream is not CapabilityStream.BLOCK_CLOCK
        }
        # A mixed program-version cut has no single valid state reducer.
        if len(versions) != 1:
            raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
        # State math and account-mode validation are the same as the execution protocol.
        runtime = PumpfunCopyBuyProtocolRuntime(
            quote_asset_id=AssetId("SOL"),
            protocol_version=next(iter(versions)),
            fee_profile=PumpFeeProfile.static_95_30(
                profile_id="copy-snapshot-validation-v1",
                # The pinned 95/30 formula validates derived fee components, not observed fee
                # splits.
                effective_from_unix_s=0,
                effective_until_unix_s=(1 << 64) - 1,
            ),
        )
        capabilities = {item.capability_id: item for item in spec.capabilities}
        # Count initialization events independently of trade occurrence coverage.
        launches = 0
        try:
            for group in copy_event_groups(candidate.events(), clock=clock):
                # Validate whole groups before any callback can observe state.
                for event in group:
                    _require_event_family(event, capabilities, spec)
                    launches += isinstance(event, TokenLaunchEvent)
                    if launches > expected.eligible_mints:
                        raise SnapshotValidationError(
                            # Extra launches indicate a mismatch between candidate selection and
                            # canonical content.
                            SnapshotValidationErrorCode.EVENT_STREAM_INVALID
                        )
                runtime.apply_group(
                    group,
                    effective_at_unix_s=clock.block_time_for_block(
                        # Apply the complete historical transaction atomically at its clock-derived
                        # timestamp.
                        group[0].envelope.position.block_ordinal
                    )
                    // 1_000_000_000,
                )
                # Prove the maximum path for repeated purchases too.
                for event in group:
                    if coverage.consume(event):
                        maximum_copy_settlement_position(
                            clock,
                            event.envelope.position,
                            # Observation latency and own buy latency are separate operands in the
                            # maximal path.
                            observation_delay_transactions=requirement.observation_delay_transactions,
                            buy_delay_transactions=requirement.buy_delay_transactions,
                            # Durations require produced, nonempty transaction boundaries.
                            maximum_hold_ns=requirement.maximum_hold_seconds * 1_000_000_000,
                            sell_delay_transactions=requirement.sell_delay_transactions,
                        )
        except TransactionClockError as error:
            reason = SnapshotValidationErrorCode.CLOCK_INVALID
            # Exhausted duration or transaction clocks reject publication as insufficient
            # settlement.
            if error.code in (
                TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED,
                TransactionClockErrorCode.DURATION_TARGET_OUTSIDE_CLOCK,
            ):
                reason = SnapshotValidationErrorCode.SETTLEMENT_TAIL_INSUFFICIENT
            # Only specific clock exhaustion codes qualify as a short tail.
            raise SnapshotValidationError(reason) from error
        except ProtocolContractError as error:
            raise SnapshotValidationError(
                SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID
            ) from error
        # Count and hash reconciliation binds extracted bytes to independent source enumeration.
        if (coverage.count, coverage.mint_count, coverage.digest, launches) != (
            expected.eligible_occurrences,
            expected.eligible_mints,
            expected.eligible_signal_digest,
            expected.eligible_mints,
            # Published coverage must match source occurrence count, mint count and ordered digest.
        ):
            raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)


def _require_event_family(
    event: CanonicalEvent, capabilities: dict[CapabilityId, PlannedCapability], spec: DatasetSpec
) -> None:
    """Every event belongs to its declared source stream, protocol version and extraction range."""
    capability = capabilities.get(event.envelope.capability_id)
    if capability is None or _KINDS[capability.stream] is not event.kind:
        raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
    if (
        event.envelope.protocol != capability.protocol
        # Matching event kind alone cannot substitute another protocol or version.
        or event.envelope.protocol_version != capability.protocol_version
    ):
        raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
    # Creation events can initialize older tokens but must never come from the settlement tail.
    cut = next(
        item.block_range
        for item in spec.capability_ranges
        if item.capability_id == capability.capability_id
    )
    # Every event must remain inside its capability-specific extraction interval.
    if not cut.contains_block(event.envelope.position.block_ordinal):
        raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_POSITION_INVALID)
