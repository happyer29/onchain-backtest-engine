"""Bounded zero-event-object engine for the checked-in reference vertical slice.

The readable :class:`ReferenceBacktestEngine` remains the semantic oracle.  This
backend specializes only the exact FirstSwap + constant-product + static-risk
stack injected by the composition root.  It consumes already verified ReplayPack
arrays, never calls ``NumpyMmapReplaySource._event`` and fails closed for every
other component, overlay, schedule, layout or execution mode.
"""

from __future__ import annotations

import json
from binascii import hexlify
from collections.abc import Mapping
from typing import Any, Protocol, cast

# Import numpy at the visible module dependency boundary.
import numpy as np
import numpy.typing as npt

from backtest.adapters.columnar.numpy import layout as physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.domain.chain import ChainPosition

# Import execution at the visible module dependency boundary.
from backtest.domain.execution import (
    ExecutionMode,
    ExecutionNotification,
    ExecutionRejected,
    OrderStatus,
    # Close the execution import after its required symbols are visible.
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    AssetId,
    ContentDigest,
    # Include network id so the identifiers dependency remains explicit.
    NetworkId,
    PoolId,
    PositionSchemaId,
)
from backtest.domain.intents import Intent, SwapExactInIntent

# Import audit at the visible module dependency boundary.
from backtest.engine.audit import (
    CanonicalStreamHasher,
    fill_document,
    ledger_document,
)

# Import causal data at the visible module dependency boundary.
from backtest.engine.causal_data import CausalScalarProvider, CausalScalarView
from backtest.engine.contracts import (
    DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    CanonicalAuditBytesSink,
    EnginePhysicalSettings,
    # Include observed market view so the contracts dependency remains explicit.
    ObservedMarketView,
    PortfolioView,
    RiskPolicy,
    RunEventSink,
    StrategyContext,
    # Include strategy instance so the contracts dependency remains explicit.
    StrategyInstance,
    VenueExecutionModel,
)
from backtest.engine.portfolio import PortfolioState
from backtest.engine.reference import (
    # Include engine invariant error so the reference dependency remains explicit.
    EngineInvariantError,
    NullRunEventSink,
    ReferenceRunConfig,
    RunSummary,
    _release_transaction,
    # Include reservation transaction so the reference dependency remains explicit.
    _reservation_transaction,
    _settlement_transaction,
    _validate_execution_plan,
)
from backtest.engine.replay import HistoricalEventSource, ObservationDeliverySource

# Import rng at the visible module dependency boundary.
from backtest.engine.rng import KeyedRng
from backtest.engine.scheduler import SchedulerInstant, SchedulerPhase
from backtest.engine.state import (
    ObservedState,
    PoolSnapshot,
    # Include simulation venue state so the state dependency remains explicit.
    SimulationVenueState,
    VenueStateCommit,
)

NUMPY_MMAP_FIRST_SWAP_BACKEND = "numpy-mmap-first-swap-exact-v1"
_MAX_BATCH_ROWS = 256 * 1024
# Bind exact fidelity codes once as an explicit module-level contract.
_EXACT_FIDELITY_CODES = (2, 3)


class OptimizedBackendUnsupported(EngineInvariantError):
    """The requested run is outside this backend's explicit exact capability."""


class _PrimitiveFirstSwapStrategy(Protocol):
    pool_id: PoolId

    def on_exact_primitive_swap(
        self,
        *,
        # Keep the event id input explicit in the on exact primitive swap contract.
        event_id: ContentDigest,
        decision_boundary_ordinal: int,
    ) -> tuple[Intent, ...]: ...


class NumpyMmapFirstSwapEngine:
    """Sequential specialized reducer over verified ReplayPack numeric arrays."""

    def __init__(
        self,
        *,
        strategy_type: type[object],
        execution_model_type: type[object],
        # Keep the risk policy type input explicit in the init contract.
        risk_policy_type: type[object],
    ) -> None:
        # Execute the numpy mmap first swap engine init workflow in explicit, reviewable
        # steps.
        self._strategy_type = strategy_type
        self._execution_type = execution_model_type
        self._risk_type = risk_policy_type

    def preflight(
        self,
        # Close the preflight signature after its explicit inputs.
        *,
        source: HistoricalEventSource,
        strategy: StrategyInstance,
        execution_model: VenueExecutionModel,
        risk_policy: RiskPolicy,
        # Keep the config input explicit in the preflight contract.
        config: ReferenceRunConfig,
        features: CausalScalarProvider | None,
        predictions: CausalScalarProvider | None,
        delivery_schedule: ObservationDeliverySource | None,
        physical_settings: EnginePhysicalSettings,
        # Close the preflight signature after its explicit inputs.
    ) -> None:
        # Execute the numpy mmap first swap engine preflight workflow in explicit,
        # reviewable steps.
        if type(source) is not NumpyMmapReplaySource:
            # Handle the numpy mmap first swap engine preflight numpy mmap replay source,
            # type and source condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend requires the verified NumPy ReplayPack reader"
            )
        if type(strategy) is not self._strategy_type:
            # Handle the numpy mmap first swap engine preflight strategy type, type and
            # strategy condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend supports only the exact FirstSwap strategy"
            )
        if type(execution_model) is not self._execution_type:
            # Handle the numpy mmap first swap engine preflight execution type, type and
            # execution model condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend supports only the exact constant-product execution model"
            )
        if type(risk_policy) is not self._risk_type:
            # Handle the numpy mmap first swap engine preflight risk type, type and risk
            # policy condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend supports only the exact static risk policy"
            )
        if config.execution_mode not in {
            ExecutionMode.EXOGENOUS_REPLAY,
            # Keep execution mode visible while evaluating the execution mode, config and
            # exogenous replay guard.
            ExecutionMode.SHADOW_STATE_REPLAY,
        }:
            # Handle the numpy mmap first swap engine preflight execution mode, config and
            # exogenous replay condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend does not implement conditional protocol replay"
            )
        if features is not None or predictions is not None:
            # Handle the numpy mmap first swap engine preflight features and predictions
            # condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized reference strategy does not consume causal overlays"
            )
        if delivery_schedule is not None:
            # Handle the numpy mmap first swap engine preflight delivery_schedule is not
            # None branch as a distinct logical block.
            raise OptimizedBackendUnsupported(
                "optimized backend currently supports the equivalent dynamic latency merge only"
            )
        if physical_settings.threads != 1:
            # Handle the numpy mmap first swap engine preflight physical_settings.threads
            # != 1 branch as a distinct logical block.
            raise OptimizedBackendUnsupported(
                "one optimized run requires exactly one sequential engine thread"
            )
        if physical_settings.reader_batch_rows > _MAX_BATCH_ROWS:
            # Handle the numpy mmap first swap engine preflight reader batch rows, max
            # batch rows and physical settings condition as a distinct block.
            raise OptimizedBackendUnsupported(
                "optimized reader batch exceeds the 256k-row bounded limit"
            )
        _validate_primitive_contract(source, physical_settings.reader_batch_rows)

    def run(
        # Keep the remaining run inputs visible at the numpy mmap first swap engine run
        # boundary.
        self,
        *,
        source: HistoricalEventSource,
        strategy: StrategyInstance,
        execution_model: VenueExecutionModel,
        # Keep the risk policy input explicit in the run contract.
        risk_policy: RiskPolicy,
        config: ReferenceRunConfig,
        sink: RunEventSink | None = None,
        features: CausalScalarProvider | None = None,
        predictions: CausalScalarProvider | None = None,
        # Keep the delivery schedule input explicit in the run contract.
        delivery_schedule: ObservationDeliverySource | None = None,
        physical_settings: EnginePhysicalSettings = DEFAULT_ENGINE_PHYSICAL_SETTINGS,
    ) -> RunSummary:
        # Execute the numpy mmap first swap engine run workflow in explicit, reviewable
        # steps.
        self.preflight(
            source=source,
            strategy=strategy,
            execution_model=execution_model,
            risk_policy=risk_policy,
            # Pass config explicitly so preflight receives a reviewable source and
            # strategy input in numpy mmap first swap engine run.
            config=config,
            features=features,
            predictions=predictions,
            delivery_schedule=delivery_schedule,
            physical_settings=physical_settings,
            # Complete preflight only after its source and strategy inputs are visible in
            # numpy mmap first swap engine run.
        )
        replay = cast(NumpyMmapReplaySource, source)
        primitive_strategy = cast(_PrimitiveFirstSwapStrategy, strategy)
        arrays = replay.arrays()
        recorder = _PrimitiveRecorder(NullRunEventSink() if sink is None else sink)
        # Assemble portfolio once so the numpy mmap first swap engine run workflow shares
        # one value.
        portfolio = PortfolioState(config.initial_available)
        portfolio_view = PortfolioView(portfolio)
        observed_state = ObservedState()

        boundary_ordinals = arrays[physical.BOUNDARY_ORDINAL]
        boundary_blocks = arrays[physical.BOUNDARY_BLOCK_ORDINAL]
        # Assemble offsets once so the numpy mmap first swap engine run workflow shares
        # one value.
        offsets = arrays[physical.BOUNDARY_OFFSETS]
        event_kinds = arrays[physical.ENVELOPE_EVENT_KIND_CODE]
        payload_indexes = arrays[physical.ENVELOPE_PAYLOAD_INDEX]
        event_ids = arrays[physical.ENVELOPE_CANONICAL_EVENT_ID]
        group_ids = arrays[physical.ENVELOPE_TRANSACTION_GROUP_ID]
        # Assemble swap pool codes once so the numpy mmap first swap engine run workflow
        # shares one value.
        swap_pool_codes = arrays[physical.SWAP_POOL_CODE]
        reserve_a_valid = arrays[physical.SWAP_RESERVE_A_VALID]
        reserve_b_valid = arrays[physical.SWAP_RESERVE_B_VALID]

        target_pool_code = replay.dictionary_code("venues", primitive_strategy.pool_id.value)
        boundary_count = replay.manifest.boundary_count
        # Assemble next delivery source once so the numpy mmap first swap engine run
        # workflow shares one value.
        next_delivery_source = 0
        next_delivery_release = _observation_release_index(
            boundary_blocks,
            0,
            config.latency.observation_slots,
            # Complete _observation_release_index only after its observation slots and latency
            # inputs are visible in numpy mmap first swap engine run.
        )
        pending_observations = 0
        pending_order: tuple[int, SwapExactInIntent] | None = None
        historical_pool_payload: int | None = None
        venue_pool_payload: int | None = None
        # Assemble observed pool exists once so the numpy mmap first swap engine run
        # workflow shares one value.
        observed_pool_exists = False
        submitted = False

        delivered_count = 0
        accepted_count = 0
        rejected_count = 0
        # Assemble filled order count once so the numpy mmap first swap engine run
        # workflow shares one value.
        filled_order_count = 0
        failed_order_count = 0

        for batch_start, batch_stop in _boundary_batches(
            offsets,
            physical_settings.reader_batch_rows,
            # Pass physical settings explicitly so _boundary_batches receives a reviewable
            # reader batch rows and reader readahead input in numpy mmap first swap engine
            # run.
            physical_settings.reader_readahead,
        ):
            # Process boundary batches, offsets and reader batch rows inside the bounded
            # numpy mmap first swap engine run loop.
            for boundary_index in range(batch_start, batch_stop):
                # Process range(batch_start, batch_stop) inside the bounded numpy mmap
                # first swap engine run loop.
                boundary = int(boundary_ordinals[boundary_index])
                row_start = int(offsets[boundary_index])
                row_stop = int(offsets[boundary_index + 1])
                group_raw = group_ids[row_start].tobytes()

                touched_target = False
                # Traverse range(row_start, row_stop) explicitly so each numpy mmap first
                # swap engine run iteration remains traceable.
                for row in range(row_start, row_stop):
                    # Process range(row_start, row_stop) inside the bounded numpy mmap
                    # first swap engine run loop.
                    if int(event_kinds[row]) != 3:
                        continue
                    payload = int(payload_indexes[row])
                    if (
                        target_pool_code is None
                        # Keep int visible while evaluating the target pool code, swap
                        # pool codes and payload guard.
                        or int(swap_pool_codes[payload]) != target_pool_code
                    ):
                        continue
                    touched_target = True
                    if _valid(reserve_a_valid, payload) and _valid(reserve_b_valid, payload):
                        # Assemble historical pool payload once so the numpy mmap first
                        # swap engine run workflow shares one value.
                        historical_pool_payload = payload
                if touched_target and historical_pool_payload is not None:
                    venue_pool_payload = historical_pool_payload

                recorder.append_encoded_audit(
                    _historical_group_record(boundary, event_ids, row_start, row_stop, group_raw),
                    # Pass boundary explicitly so append_encoded_audit receives a
                    # reviewable historical group applied and historical reference apply
                    # input in numpy mmap first swap engine run.
                    boundary,
                    SchedulerPhase.HISTORICAL_REFERENCE_APPLY,
                    "HISTORICAL_GROUP_APPLIED",
                )
                recorder.append_encoded_audit(
                    # Pass simulation record explicitly to append_encoded_audit for
                    # simulation reconciled and execution mode.
                    _simulation_record(boundary, config.execution_mode, group_raw),
                    boundary,
                    SchedulerPhase.SIMULATION_STATE_RECONCILE,
                    "SIMULATION_RECONCILED",
                )

                # Assemble source release once so the numpy mmap first swap engine run
                # workflow shares one value.
                source_release = _observation_release_index(
                    boundary_blocks,
                    boundary_index,
                    config.latency.observation_slots,
                )
                # Guard this path with source_release is None before applying effects.
                if source_release is None:
                    # Handle the numpy mmap first swap engine run source_release is None
                    # branch as a distinct logical block.
                    for row in range(row_start, row_stop):
                        # Process range(row_start, row_stop) inside the bounded numpy mmap
                        # first swap engine run loop.
                        recorder.append_encoded_audit(
                            _outside_horizon_record(boundary, event_ids[row].tobytes()),
                            boundary,
                            SchedulerPhase.OBSERVATION_DELIVERY,
                            "OBSERVATION_OUTSIDE_HORIZON",
                            # Complete append_encoded_audit only after its observation outside
                            # horizon and tobytes inputs are visible in numpy mmap first swap
                            # engine run.
                        )
                else:
                    pending_observations += row_stop - row_start
                _check_dynamic_budget(
                    pending_observations,
                    # Pass pending order explicitly so _check_dynamic_budget receives a
                    # reviewable maximum dynamic items and pending observations input in
                    # numpy mmap first swap engine run.
                    pending_order is not None,
                    config.maximum_dynamic_items,
                )

                proposed: SwapExactInIntent | None = None
                while (
                    # Repeat the numpy mmap first swap engine run step only while next
                    # delivery source, boundary index and next delivery release remains
                    # true.
                    next_delivery_source <= boundary_index
                    and next_delivery_release == boundary_index
                ):
                    # Keep the next delivery source, boundary index and next delivery
                    # release loop body bounded within numpy mmap first swap engine run.
                    delivery_start = int(offsets[next_delivery_source])
                    delivery_stop = int(offsets[next_delivery_source + 1])
                    source_boundary = int(boundary_ordinals[next_delivery_source])
                    for row in range(delivery_start, delivery_stop):
                        # Process range(delivery_start, delivery_stop) inside the bounded
                        # numpy mmap first swap engine run loop.
                        recorder.append_encoded_audit(
                            _delivered_record(
                                boundary,
                                event_ids[row].tobytes(),
                                source_boundary,
                                # Complete _delivered_record only after its tobytes and
                                # boundary inputs are visible in numpy mmap first swap engine
                                # run.
                            ),
                            boundary,
                            SchedulerPhase.OBSERVATION_DELIVERY,
                            "OBSERVATION_DELIVERED",
                        )
                        # Assemble delivered count once so the numpy mmap first swap
                        # engine run workflow shares one value.
                        delivered_count += 1
                        pending_observations -= 1
                        if submitted or int(event_kinds[row]) != 3:
                            continue
                        payload = int(payload_indexes[row])
                        # Evaluate the complete numpy mmap first swap engine run target
                        # pool code, swap pool codes and payload condition before guarded
                        # effects.
                        if (
                            target_pool_code is None
                            or int(swap_pool_codes[payload]) != target_pool_code
                        ):
                            continue
                        # Evaluate the complete numpy mmap first swap engine run valid,
                        # reserve a valid and payload condition before guarded effects.
                        if _valid(reserve_a_valid, payload) and _valid(reserve_b_valid, payload):
                            observed_pool_exists = True
                        if not observed_pool_exists:
                            continue
                        intents = primitive_strategy.on_exact_primitive_swap(
                            # Keep the content digest and hex ContentDigest step visible
                            # while building intents.
                            event_id=ContentDigest(event_ids[row].tobytes().hex()),
                            decision_boundary_ordinal=boundary,
                        )
                        if len(intents) != 1 or not isinstance(intents[0], SwapExactInIntent):
                            # Handle the numpy mmap first swap engine run intents,
                            # isinstance and swap exact in intent condition as a distinct
                            # block.
                            raise EngineInvariantError(
                                "optimized FirstSwap strategy returned an invalid intent"
                            )
                        proposed = intents[0]
                        submitted = True
                        # Invoke append_audit for intent proposed and boundary ordinal as
                        # a visible numpy mmap first swap engine run step.
                        recorder.append_audit(
                            {
                                "boundary_ordinal": boundary,
                                "order_id": proposed.order_id.hex,
                                "phase": int(SchedulerPhase.STRATEGY_CALLBACK),
                                # Keep record type named so the intent proposed and
                                # boundary ordinal payload passed to append_audit remains
                                # self-describing within numpy mmap first swap engine run.
                                "record_type": "INTENT_PROPOSED",
                            }
                        )
                    next_delivery_source += 1
                    next_delivery_release = (
                        # Complete the next delivery release group only after its semantic
                        # components are visible.
                        None
                        if next_delivery_source >= boundary_count
                        else _observation_release_index(
                            boundary_blocks,
                            next_delivery_source,
                            # Pass config explicitly so _observation_release_index
                            # receives a reviewable observation slots and latency input in
                            # numpy mmap first swap engine run.
                            config.latency.observation_slots,
                        )
                    )

                notifications: list[ExecutionNotification] = []
                if proposed is not None:
                    # Handle the numpy mmap first swap engine run proposed is not None
                    # branch as a distinct logical block.
                    order_release = _order_release_index(
                        boundary_blocks,
                        boundary_index,
                        config.latency.order_slots,
                    )
                    # Evaluate the complete numpy mmap first swap engine run order
                    # release, accept and proposed condition before guarded effects.
                    if order_release is None or not risk_policy.accept(proposed, portfolio_view):
                        # Handle the numpy mmap first swap engine run order release,
                        # accept and proposed condition as a distinct block.
                        rejected_count += 1
                        reason = "HORIZON_EXHAUSTED" if order_release is None else "RISK_REJECTED"
                        recorder.append_audit(
                            {
                                "boundary_ordinal": boundary,
                                # Keep order id named so the reason and order rejected
                                # payload passed to append_audit remains self-describing
                                # within numpy mmap first swap engine run.
                                "order_id": proposed.order_id.hex,
                                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                                "reason": reason,
                                "record_type": "ORDER_REJECTED",
                            }
                            # Complete append_audit only after its reason and order rejected
                            # inputs are visible in numpy mmap first swap engine run.
                        )
                        notifications.append(
                            ExecutionNotification(
                                proposed.order_id,
                                OrderStatus.REJECTED,
                                # Pass boundary explicitly so ExecutionNotification
                                # receives a reviewable order id and rejected input in
                                # numpy mmap first swap engine run.
                                boundary,
                                reports=(reason,),
                            )
                        )
                    else:
                        # Handle the numpy mmap first swap engine run complement of order
                        # release, accept and proposed explicitly.
                        reservation = _reservation_transaction(proposed, boundary)
                        portfolio.apply(reservation)
                        recorder.append_ledger(reservation)
                        accepted_count += 1
                        recorder.append_audit(
                            # Open the order accepted and reserved and boundary ordinal
                            # payload explicitly for append_audit within numpy mmap first
                            # swap engine run.
                            {
                                "boundary_ordinal": boundary,
                                "eligible_boundary_ordinal": int(boundary_ordinals[order_release]),
                                "order_id": proposed.order_id.hex,
                                "phase": int(SchedulerPhase.RISK_AND_ORDER_ACCEPTANCE),
                                # Keep record type named so the order accepted and
                                # reserved and boundary ordinal payload passed to
                                # append_audit remains self-describing within numpy mmap
                                # first swap engine run.
                                "record_type": "ORDER_ACCEPTED_AND_RESERVED",
                            }
                        )
                        pending_order = (order_release, proposed)
                        notifications.append(
                            # Pass execution notification explicitly to append for order
                            # id and accepted.
                            ExecutionNotification(
                                proposed.order_id,
                                OrderStatus.ACCEPTED,
                                boundary,
                            )
                            # Complete append only after its order id and accepted inputs are
                            # visible in numpy mmap first swap engine run.
                        )
                _check_dynamic_budget(
                    pending_observations,
                    pending_order is not None,
                    config.maximum_dynamic_items,
                    # Complete _check_dynamic_budget only after its maximum dynamic items and
                    # pending observations inputs are visible in numpy mmap first swap engine
                    # run.
                )

                if pending_order is not None and pending_order[0] == boundary_index:
                    # Handle the numpy mmap first swap engine run pending order and
                    # boundary index condition as a distinct block.
                    intent = pending_order[1]
                    venue = _venue_state(
                        replay,
                        arrays,
                        primitive_strategy.pool_id,
                        # Pass venue pool payload explicitly so _venue_state receives a
                        # reviewable pool id and execution mode input in numpy mmap first
                        # swap engine run.
                        venue_pool_payload,
                        boundary,
                        config.execution_mode,
                    )
                    try:
                        # Perform the protected numpy mmap first swap engine run operation
                        # before explicit failure handling.
                        plan = execution_model.execute(
                            intent,
                            venue,
                            boundary_ordinal=boundary,
                            mode=config.execution_mode,
                            # Complete execute only after its execution mode and intent inputs
                            # are visible in numpy mmap first swap engine run.
                        )
                    except ExecutionRejected as error:
                        # Translate the ExecutionRejected failure through the numpy mmap
                        # first swap engine run boundary.
                        release = _release_transaction(intent, boundary, error.code)
                        portfolio.apply(release)
                        recorder.append_ledger(release)
                        failed_order_count += 1
                        recorder.append_audit(
                            # Open the code and order execution failed and released
                            # payload explicitly for append_audit within numpy mmap first
                            # swap engine run.
                            {
                                "boundary_ordinal": boundary,
                                "order_id": intent.order_id.hex,
                                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                                "reason": error.code,
                                # Keep record type named so the code and order execution
                                # failed and released payload passed to append_audit
                                # remains self-describing within numpy mmap first swap
                                # engine run.
                                "record_type": "ORDER_EXECUTION_FAILED_AND_RELEASED",
                            }
                        )
                        notifications.append(
                            ExecutionNotification(
                                # Pass intent explicitly so ExecutionNotification receives
                                # a reviewable order id and execution failed input in
                                # numpy mmap first swap engine run.
                                intent.order_id,
                                OrderStatus.EXECUTION_FAILED,
                                boundary,
                                reports=(error.code,),
                            )
                            # Complete append only after its order id and execution failed
                            # inputs are visible in numpy mmap first swap engine run.
                        )
                    else:
                        # Handle the alternative path after the protected numpy mmap first
                        # swap engine run operation.
                        _validate_execution_plan(
                            intent,
                            plan,
                            boundary,
                            config.execution_mode,
                            # Complete _validate_execution_plan only after its execution mode
                            # and intent inputs are visible in numpy mmap first swap engine
                            # run.
                        )
                        settlement = _settlement_transaction(
                            intent,
                            plan.ledger_postings,
                            boundary,
                            # Complete _settlement_transaction only after its ledger postings
                            # and intent inputs are visible in numpy mmap first swap engine
                            # run.
                        )
                        portfolio_candidate = portfolio.preview(settlement)
                        venue_candidate = (
                            None
                            if plan.transition is None
                            # Route all remaining cases through the explicit alternative
                            # branch.
                            else venue.preview_transition(plan.transition)
                        )
                        portfolio.commit(portfolio_candidate)
                        if venue_candidate is not None:
                            venue.commit(venue_candidate)
                        # Invoke append_ledger for settlement as a visible numpy mmap
                        # first swap engine run step.
                        recorder.append_ledger(settlement)
                        for fill in sorted(plan.fills, key=lambda value: value.order_id.hex):
                            recorder.append_fill(fill)
                        filled_order_count += 1
                        recorder.append_audit(
                            # Open the order filled atomically and boundary ordinal
                            # payload explicitly for append_audit within numpy mmap first
                            # swap engine run.
                            {
                                "boundary_ordinal": boundary,
                                "fill_count": len(plan.fills),
                                "order_id": intent.order_id.hex,
                                "phase": int(SchedulerPhase.VENUE_EXECUTION_AND_LEDGER_COMMIT),
                                # Keep record type named so the order filled atomically
                                # and boundary ordinal payload passed to append_audit
                                # remains self-describing within numpy mmap first swap
                                # engine run.
                                "record_type": "ORDER_FILLED_ATOMICALLY",
                            }
                        )
                        notifications.append(
                            ExecutionNotification(
                                # Pass intent explicitly so ExecutionNotification receives
                                # a reviewable order id and filled input in numpy mmap
                                # first swap engine run.
                                intent.order_id,
                                OrderStatus.FILLED,
                                boundary,
                                fills=plan.fills,
                                reports=plan.reports,
                                # Complete ExecutionNotification only after its order id and
                                # filled inputs are visible in numpy mmap first swap engine
                                # run.
                            )
                        )
                    pending_order = None

                notifications.sort(key=lambda item: (item.order_id.hex, item.status.value))
                if notifications:
                    # Handle the numpy mmap first swap engine run notifications branch as
                    # a distinct logical block.
                    notification_context = _notification_context(
                        config,
                        observed_state,
                        portfolio,
                        boundary,
                        # Keep the boundary blocks and boundary index int step visible
                        # while building notification context.
                        int(boundary_blocks[boundary_index]),
                        replay.network_id,
                        replay.position_schema_id,
                    )
                    for notification in notifications:
                        # Process notifications inside the bounded numpy mmap first swap
                        # engine run loop.
                        strategy.on_execution(notification, notification_context)
                        recorder.append_audit(
                            {
                                "boundary_ordinal": boundary,
                                "order_id": notification.order_id.hex,
                                # Pass phase explicitly to append_audit for strategy
                                # notified and value.
                                "phase": int(SchedulerPhase.STRATEGY_EXECUTION_NOTIFICATION),
                                "record_type": "STRATEGY_NOTIFIED",
                                "status": notification.status.value,
                            }
                        )
                # Invoke append_encoded_audit for boundary checkpoint and checkpoint as a
                # visible numpy mmap first swap engine run step.
                recorder.append_encoded_audit(
                    _checkpoint_record(boundary),
                    boundary,
                    SchedulerPhase.CHECKPOINT,
                    "BOUNDARY_CHECKPOINT",
                    # Complete append_encoded_audit only after its boundary checkpoint and
                    # checkpoint inputs are visible in numpy mmap first swap engine run.
                )

        if pending_observations or pending_order is not None:
            raise EngineInvariantError("replay ended with supposedly reachable dynamic items")
        final_balances = portfolio.semantic_balances()
        result_document: dict[str, object] = {
            # Keep the accepted order count component named inside the result document
            # contract.
            "accepted_order_count": accepted_count,
            "failed_order_count": failed_order_count,
            "fill_count": recorder.fills.count,
            "fill_hash": recorder.fills.digest.hex,
            "filled_order_count": filled_order_count,
            # Register row through list so the result document table remains scannable.
            "final_balances": [list(row) for row in final_balances],
            "ledger_hash": recorder.ledger.digest.hex,
            "ledger_transaction_count": recorder.ledger.count,
            "rejected_order_count": rejected_count,
        }
        # Return the completed numpy mmap first swap engine run result without a hidden
        # fallback.
        return RunSummary(
            dataset_logical_content_hash=replay.logical_content_hash,
            replay_semantics_id=replay.replay_semantics_id,
            engine_bundle_id=config.engine_bundle_id,
            latency_bundle_id=config.latency.bundle_id,
            # Pass historical group count explicitly so RunSummary receives a reviewable
            # v1 and logical content hash input in numpy mmap first swap engine run.
            historical_group_count=replay.manifest.group_count,
            historical_event_count=replay.event_count,
            delivered_event_count=delivered_count,
            accepted_order_count=accepted_count,
            rejected_order_count=rejected_count,
            # Pass filled order count explicitly so RunSummary receives a reviewable v1
            # and logical content hash input in numpy mmap first swap engine run.
            filled_order_count=filled_order_count,
            failed_order_count=failed_order_count,
            ledger_transaction_count=recorder.ledger.count,
            fill_count=recorder.fills.count,
            audit_hash=recorder.audit.digest,
            # Pass ledger hash explicitly so RunSummary receives a reviewable v1 and
            # logical content hash input in numpy mmap first swap engine run.
            ledger_hash=recorder.ledger.digest,
            fill_hash=recorder.fills.digest,
            result_hash=domain_digest("backtest.canonical-run-result.v1", result_document),
            final_balances=final_balances,
        )


# Keep the primitive recorder contract and validation rules together.
class _PrimitiveRecorder:
    def __init__(self, sink: RunEventSink) -> None:
        # Execute the primitive recorder init workflow in explicit, reviewable steps.
        self.sink = sink
        self.audit = CanonicalStreamHasher("backtest.canonical-audit-stream.v1")
        self.ledger = CanonicalStreamHasher("backtest.canonical-ledger-stream.v2")
        self.fills = CanonicalStreamHasher("backtest.canonical-fill-stream.v1")
        self._encoded_sink = (
            # Keep the canonical audit bytes sink cast step visible while building self.
            # encoded sink.
            cast(CanonicalAuditBytesSink, sink)
            if isinstance(sink, CanonicalAuditBytesSink)
            else None
        )

    def append_encoded_audit(
        # Keep the remaining append encoded audit inputs visible at the primitive recorder
        # append encoded audit boundary.
        self,
        record: bytes,
        boundary: int,
        phase: SchedulerPhase,
        record_type: str,
        # Close the append encoded audit signature after its explicit inputs.
    ) -> None:
        # Execute the primitive recorder append encoded audit workflow in explicit,
        # reviewable steps.
        self.audit.append_canonical_bytes(record)
        if self._encoded_sink is not None:
            # Handle the primitive recorder append encoded audit self._encoded_sink is not
            # None branch as a distinct logical block.
            self._encoded_sink.append_canonical_audit(
                record,
                boundary_ordinal=boundary,
                phase=int(phase),
                record_type=record_type,
                # Complete append_canonical_audit only after its int and record inputs are
                # visible in primitive recorder append encoded audit.
            )
            return
        value = json.loads(record)
        if not isinstance(value, dict):  # pragma: no cover - module-authored bytes
            raise AssertionError("canonical audit encoder produced a non-object")
        self.sink.append_audit(cast(dict[str, object], value))

    def append_audit(self, record: dict[str, object]) -> None:
        # Execute the primitive recorder append audit workflow in explicit, reviewable
        # steps.
        self.audit.append(record)
        self.sink.append_audit(record)

    def append_ledger(self, transaction: Any) -> None:
        # Execute the primitive recorder append ledger workflow in explicit, reviewable
        # steps.
        self.ledger.append(ledger_document(transaction))
        self.sink.append_ledger(transaction)

    def append_fill(self, fill: Any) -> None:
        # Execute the primitive recorder append fill workflow in explicit, reviewable
        # steps.
        self.fills.append(fill_document(fill))
        self.sink.append_fill(fill)


def _validate_primitive_contract(replay: NumpyMmapReplaySource, batch_rows: int) -> None:
    # Execute the validate primitive contract workflow in explicit, reviewable steps.
    arrays = replay.arrays()
    offsets = arrays[physical.BOUNDARY_OFFSETS]
    groups = arrays[physical.GROUP_OFFSETS]
    if not np.array_equal(offsets, groups):
        # Handle the validate primitive contract not np.array_equal(offsets, groups)
        # branch as a distinct logical block.
        raise OptimizedBackendUnsupported(
            "optimized backend requires exactly one transaction group per boundary"
        )
    group_sizes = np.diff(offsets)
    if group_sizes.size and int(group_sizes.max()) > batch_rows:
        # Handle the validate primitive contract size, group sizes and batch rows
        # condition as a distinct block.
        raise OptimizedBackendUnsupported(
            "one historical transaction group exceeds the configured reader batch"
        )
    fidelity = arrays[physical.ENVELOPE_ORDERING_FIDELITY_CODE]
    if not bool(np.all(np.isin(fidelity, _EXACT_FIDELITY_CODES))):
        # Handle the validate primitive contract all, np and isin condition as a distinct
        # block.
        raise OptimizedBackendUnsupported(
            "optimized backend requires exact transaction/instruction ordering"
        )
    if not _all_valid(arrays[physical.ENVELOPE_EVENT_INDEX_VALID], replay.event_count):
        # Handle the validate primitive contract all valid, event count and arrays
        # condition as a distinct block.
        raise OptimizedBackendUnsupported(
            "optimized backend requires an exact event index on every row"
        )
    event_indexes = arrays[physical.ENVELOPE_EVENT_INDEX]
    stable_ids = arrays[physical.ENVELOPE_STABLE_CAUSAL_ID]
    # Traverse range(replay.manifest.boundary_count) explicitly so each validate primitive
    # contract iteration remains traceable.
    for boundary_index in range(replay.manifest.boundary_count):
        # Process range(replay.manifest.boundary_count) inside the bounded validate
        # primitive contract loop.
        start = int(offsets[boundary_index])
        stop = int(offsets[boundary_index + 1])
        if stop - start > 1 and not bool(np.all(np.diff(event_indexes[start:stop]) > 0)):
            # Handle the validate primitive contract stop, start and all condition as a
            # distinct block.
            raise OptimizedBackendUnsupported(
                "optimized backend requires strictly increasing event indexes within a group"
            )
        previous: bytes | None = None
        for row in range(start, stop):
            # Process range(start, stop) inside the bounded validate primitive contract
            # loop.
            current = stable_ids[row].tobytes()
            if previous is not None and current <= previous:
                # Handle the validate primitive contract previous and current condition as
                # a distinct block.
                raise OptimizedBackendUnsupported(
                    "optimized backend requires canonical causal-ID delivery order within a group"
                )
            previous = current
    _validate_payload_semantics(replay, arrays)


# Define validate payload semantics as one focused operation with an explicit boundary.
def _validate_payload_semantics(
    replay: NumpyMmapReplaySource,
    arrays: Mapping[str, npt.NDArray[np.generic]],
) -> None:
    # Execute the validate payload semantics workflow in explicit, reviewable steps.
    token_count = replay.manifest.payload_counts.token_launches
    token_valid = _validity_values(arrays[physical.TOKEN_DECIMALS_VALID], token_count)
    token_decimals = cast(
        npt.NDArray[np.uint8],
        arrays[physical.TOKEN_DECIMALS],
        # Complete cast only after its ndarray and uint8 inputs are visible in validate
        # payload semantics.
    )
    if token_count and bool(np.any(token_valid & (token_decimals > 38))):
        raise OptimizedBackendUnsupported("ReplayPack token decimals violate canonical semantics")

    swap_count = replay.manifest.payload_counts.venue_trades
    if not swap_count:
        # Return explicit absence from the validate payload semantics path.
        return
    if not _all_valid(arrays[physical.REFERENCE_AMM_VALID], swap_count):
        # Handle the validate payload semantics all valid, swap count and arrays condition
        # as a distinct block.
        raise OptimizedBackendUnsupported(
            "optimized FirstSwap backend requires reference AMM payloads on every venue trade"
        )
    sold = arrays[physical.SWAP_SOLD_ASSET_CODE]
    bought = arrays[physical.SWAP_BOUGHT_ASSET_CODE]
    # Assemble asset a once so the validate payload semantics workflow shares one value.
    asset_a = arrays[physical.SWAP_POOL_ASSET_A_CODE]
    asset_b = arrays[physical.SWAP_POOL_ASSET_B_CODE]
    pairs_match = ((sold == asset_a) & (bought == asset_b)) | (
        (sold == asset_b) & (bought == asset_a)
    )
    # Evaluate the complete validate payload semantics any, np and sold condition before
    # guarded effects.
    if (
        bool(np.any(sold == bought))
        or bool(np.any(asset_a == asset_b))
        or not bool(np.all(pairs_match))
    ):
        # Fail the validate payload semantics path with OptimizedBackendUnsupported for
        # replay pack swap asset pairs violate canonical semantics when any, np and sold
        # is true; do not continue ambiguously.
        raise OptimizedBackendUnsupported("ReplayPack swap asset pairs violate canonical semantics")
    sold_amount = _wide_bytes(arrays[physical.SWAP_SOLD_AMOUNT])
    bought_amount = _wide_bytes(arrays[physical.SWAP_BOUGHT_AMOUNT])
    fee_amount = _wide_bytes(arrays[physical.SWAP_FEE_AMOUNT])
    if not _all_positive_int128(sold_amount) or not _all_positive_int128(bought_amount):
        # Fail the validate payload semantics path with OptimizedBackendUnsupported for
        # replay pack swap amounts must be positive int128 when all positive int128, sold
        # amount and bought amount is true; do not continue ambiguously.
        raise OptimizedBackendUnsupported("ReplayPack swap amounts must be positive Int128")
    if not _all_nonnegative_int128(fee_amount) or not _unsigned_rows_less_equal(
        fee_amount,
        sold_amount,
    ):
        # Fail the validate payload semantics path with OptimizedBackendUnsupported for
        # replay pack swap fee violates canonical semantics when all nonnegative int128,
        # fee amount and unsigned rows less equal is true; do not continue ambiguously.
        raise OptimizedBackendUnsupported("ReplayPack swap fee violates canonical semantics")
    reserve_a_valid = _validity_values(arrays[physical.SWAP_RESERVE_A_VALID], swap_count)
    reserve_b_valid = _validity_values(arrays[physical.SWAP_RESERVE_B_VALID], swap_count)
    if not bool(np.array_equal(reserve_a_valid, reserve_b_valid)):
        raise OptimizedBackendUnsupported("ReplayPack swap reserve validity is not paired")
    # Guard this path with bool(np.any(reserve_a_valid)) before applying effects.
    if bool(np.any(reserve_a_valid)):
        # Handle the validate payload semantics bool(np.any(reserve_a_valid)) branch as a
        # distinct logical block.
        reserve_a = _wide_bytes(arrays[physical.SWAP_RESERVE_A])
        reserve_b = _wide_bytes(arrays[physical.SWAP_RESERVE_B])
        if not _selected_nonnegative_int128(reserve_a, reserve_a_valid) or not (
            _selected_nonnegative_int128(reserve_b, reserve_b_valid)
        ):
            # Fail the validate payload semantics path with OptimizedBackendUnsupported
            # for replay pack swap reserves must be non-negative when selected nonnegative
            # int128, reserve a and reserve a valid is true; do not continue ambiguously.
            raise OptimizedBackendUnsupported("ReplayPack swap reserves must be non-negative")


def _boundary_batches(
    offsets: npt.NDArray[np.generic],
    batch_rows: int,
    readahead: int,
    # Keep the tuple input explicit in the boundary batches contract.
) -> tuple[tuple[int, int], ...]:
    """Plan bounded complete-group windows; no event object or row queue is built."""

    boundary_count = len(offsets) - 1
    batches: list[tuple[int, int]] = []
    start = 0
    while start < boundary_count:
        # Keep the start < boundary_count loop body bounded within boundary batches.
        row_start = int(offsets[start])
        stop = start
        while stop < boundary_count and int(offsets[stop + 1]) - row_start <= batch_rows:
            stop += 1
        if stop == start:  # guarded by preflight
            raise OptimizedBackendUnsupported("historical group cannot fit the reader batch")
        batches.append((start, stop))
        start = stop
    # Readahead changes only the grouping of already bounded sequential windows.
    if readahead == 1:
        return tuple(batches)
    grouped: list[tuple[int, int]] = []
    for index in range(0, len(batches), readahead):
        # Process range(0, len(batches), readahead) inside the bounded boundary batches
        # loop.
        window = batches[index : index + readahead]
        grouped.append((window[0][0], window[-1][1]))
    return tuple(grouped)


def _observation_release_index(
    slots: npt.NDArray[np.generic],
    # Keep the source index input explicit in the observation release index contract.
    source_index: int,
    delay_slots: int,
) -> int | None:
    # Execute the observation release index workflow in explicit, reviewable steps.
    if delay_slots == 0:
        return source_index
    target = int(slots[source_index]) + delay_slots
    candidate = max(source_index, int(np.searchsorted(slots, target, side="left")))
    return None if candidate >= len(slots) else candidate


# Define order release index as one focused operation with an explicit boundary.
def _order_release_index(
    slots: npt.NDArray[np.generic],
    decision_index: int,
    delay_slots: int,
) -> int | None:
    # Execute the order release index workflow in explicit, reviewable steps.
    if delay_slots == 0:
        # Handle the order release index delay_slots == 0 branch as a distinct logical
        # block.
        candidate = decision_index + 1
        return None if candidate >= len(slots) else candidate
    target = int(slots[decision_index]) + delay_slots
    candidate = max(decision_index + 1, int(np.searchsorted(slots, target, side="left")))
    return None if candidate >= len(slots) else candidate


# Define check dynamic budget as one focused operation with an explicit boundary.
def _check_dynamic_budget(observations: int, has_order: bool, maximum: int) -> None:
    # Execute the check dynamic budget workflow in explicit, reviewable steps.
    if observations + int(has_order) > maximum:
        raise EngineInvariantError("dynamic scheduler item budget exceeded")


def _venue_state(
    replay: NumpyMmapReplaySource,
    arrays: Mapping[str, npt.NDArray[np.generic]],
    # Keep the pool id input explicit in the venue state contract.
    pool_id: PoolId,
    payload: int | None,
    boundary: int,
    mode: ExecutionMode,
) -> SimulationVenueState:
    # Execute the venue state workflow in explicit, reviewable steps.
    venue = SimulationVenueState(mode)
    if payload is None:
        return venue
    asset_a = AssetId(
        replay.dictionary_value(
            # Pass assets explicitly so dictionary_value receives a reviewable assets and
            # swap pool asset a code input in venue state.
            "assets",
            int(arrays[physical.SWAP_POOL_ASSET_A_CODE][payload]),
        )
    )
    asset_b = AssetId(
        # Keep the assets dictionary_value step visible while building asset b.
        replay.dictionary_value(
            "assets",
            int(arrays[physical.SWAP_POOL_ASSET_B_CODE][payload]),
        )
    )
    # Assemble snapshot once so the venue state workflow shares one value.
    snapshot = PoolSnapshot(
        pool_id,
        asset_a,
        asset_b,
        _int128(arrays[physical.SWAP_RESERVE_A], payload),
        # Keep the int128 and payload _int128 step visible while building snapshot.
        _int128(arrays[physical.SWAP_RESERVE_B], payload),
        boundary,
    )
    venue.commit(VenueStateCommit({pool_id: snapshot}))
    return venue


# Define notification context as one focused operation with an explicit boundary.
def _notification_context(
    config: ReferenceRunConfig,
    observed: ObservedState,
    portfolio: PortfolioState,
    boundary: int,
    # Keep the block ordinal input explicit in the notification context contract.
    block_ordinal: int,
    network_id: NetworkId,
    position_schema_id: PositionSchemaId,
) -> StrategyContext:
    # Execute the notification context workflow in explicit, reviewable steps.
    position = ChainPosition.from_boundary_ordinal(
        network_id=network_id,
        position_schema_id=position_schema_id,
        boundary_ordinal_value=boundary,
    )
    # Evaluate the complete notification context block ordinal and position condition
    # before guarded effects.
    if position.block_ordinal != block_ordinal:
        raise EngineInvariantError("optimized boundary block differs from its ordinal")
    return StrategyContext(
        SchedulerInstant(boundary, position),
        ObservedMarketView(observed),
        # Include portfolio view in the completed notification context result.
        PortfolioView(portfolio),
        KeyedRng(config.root_seed),
        CausalScalarView(_NoScalars(), boundary),
        CausalScalarView(_NoScalars(), boundary),
    )


# Keep the no scalars contract and validation rules together.
class _NoScalars:
    def value_at(self, name: str, entity_id: int, boundary_ordinal: int) -> None:
        # Execute the no scalars value at workflow in explicit, reviewable steps.
        del name, entity_id, boundary_ordinal
        return None


def _historical_group_record(
    boundary: int,
    event_ids: npt.NDArray[np.generic],
    # Keep the start input explicit in the historical group record contract.
    start: int,
    stop: int,
    group_id: bytes,
) -> bytes:
    # Execute the historical group record workflow in explicit, reviewable steps.
    record = bytearray(b'{"boundary_ordinal":')
    record.extend(str(boundary).encode("ascii"))
    record.extend(b',"event_ids":[')
    for row in range(start, stop):
        # Process range(start, stop) inside the bounded historical group record loop.
        if row != start:
            record.extend(b",")
        record.extend(b'"')
        record.extend(hexlify(event_ids[row].tobytes()))
        record.extend(b'"')
    # Invoke extend as a visible step within the historical group record workflow.
    record.extend(b'],"group_id":"')
    record.extend(hexlify(group_id))
    record.extend(b'","phase":10,"record_type":"HISTORICAL_GROUP_APPLIED"}')
    return bytes(record)


def _simulation_record(boundary: int, mode: ExecutionMode, group_id: bytes) -> bytes:
    # Execute the simulation record workflow in explicit, reviewable steps.
    return (
        b'{"boundary_ordinal":'
        + str(boundary).encode("ascii")
        + b',"execution_mode":"'
        + mode.value.encode("ascii")
        # Include group id in the completed simulation record result.
        + b'","group_id":"'
        + hexlify(group_id)
        + b'","phase":20,"record_type":"SIMULATION_RECONCILED"}'
    )


def _outside_horizon_record(boundary: int, event_id: bytes) -> bytes:
    # Execute the outside horizon record workflow in explicit, reviewable steps.
    return (
        b'{"boundary_ordinal":'
        + str(boundary).encode("ascii")
        + b',"event_id":"'
        + hexlify(event_id)
        # Include phase in the completed outside horizon record result.
        + b'","phase":30,"record_type":"OBSERVATION_OUTSIDE_HORIZON"}'
    )


def _delivered_record(boundary: int, event_id: bytes, source_boundary: int) -> bytes:
    # Execute the delivered record workflow in explicit, reviewable steps.
    return (
        b'{"boundary_ordinal":'
        + str(boundary).encode("ascii")
        + b',"event_id":"'
        + hexlify(event_id)
        # Include phase in the completed delivered record result.
        + b'","phase":30,"record_type":"OBSERVATION_DELIVERED",'
        + b'"source_boundary_ordinal":'
        + str(source_boundary).encode("ascii")
        + b"}"
    )


# Define checkpoint record as one focused operation with an explicit boundary.
def _checkpoint_record(boundary: int) -> bytes:
    # Execute the checkpoint record workflow in explicit, reviewable steps.
    return (
        b'{"boundary_ordinal":'
        + str(boundary).encode("ascii")
        + b',"phase":80,"record_type":"BOUNDARY_CHECKPOINT"}'
    )


# Define all valid as one focused operation with an explicit boundary.
def _all_valid(bitmap: npt.NDArray[np.generic], count: int) -> bool:
    return bool(np.all(_validity_values(bitmap, count)))


def _validity_values(
    bitmap: npt.NDArray[np.generic],
    count: int,
    # Keep the npt input explicit in the validity values contract.
) -> npt.NDArray[np.bool_]:
    # Execute the validity values workflow in explicit, reviewable steps.
    byte_bitmap = cast(npt.NDArray[np.uint8], bitmap)
    unpacked = np.unpackbits(byte_bitmap, bitorder="little", count=count)
    return cast(npt.NDArray[np.bool_], unpacked.astype(np.bool_, copy=False))


def _valid(bitmap: npt.NDArray[np.generic], index: int) -> bool:
    # Execute the valid workflow in explicit, reviewable steps.
    byte_index, bit_index = divmod(index, 8)
    return bool(int(bitmap[byte_index]) & (1 << bit_index))


def _wide_bytes(array: npt.NDArray[np.generic]) -> npt.NDArray[np.uint8]:
    return array.view(np.uint8).reshape((-1, 16))


def _all_positive_int128(values: npt.NDArray[np.uint8]) -> bool:
    # Return the completed all positive int128 result without a hidden fallback.
    return _all_nonnegative_int128(values) and bool(np.all(np.any(values != 0, axis=1)))


def _all_nonnegative_int128(values: npt.NDArray[np.uint8]) -> bool:
    return bool(np.all((values[:, 0] & 0x80) == 0))


def _selected_nonnegative_int128(
    values: npt.NDArray[np.uint8],
    # Keep the selected input explicit in the selected nonnegative int128 contract.
    selected: npt.NDArray[np.bool_],
) -> bool:
    return bool(np.all((values[selected, 0] & 0x80) == 0))


def _unsigned_rows_less_equal(
    left: npt.NDArray[np.uint8],
    # Keep the right input explicit in the unsigned rows less equal contract.
    right: npt.NDArray[np.uint8],
) -> bool:
    # Execute the unsigned rows less equal workflow in explicit, reviewable steps.
    less = np.zeros(len(left), dtype=np.bool_)
    equal = np.ones(len(left), dtype=np.bool_)
    for column in range(16):
        # Process range(16) inside the bounded unsigned rows less equal loop.
        less |= equal & (left[:, column] < right[:, column])
        equal &= left[:, column] == right[:, column]
    return bool(np.all(less | equal))


def _int128(array: npt.NDArray[np.generic], index: int) -> int:
    return int.from_bytes(array[index].tobytes(), "big", signed=True)


# Bind all once as an explicit module-level contract.
__all__ = [
    "NUMPY_MMAP_FIRST_SWAP_BACKEND",
    "NumpyMmapFirstSwapEngine",
    "OptimizedBackendUnsupported",
]
