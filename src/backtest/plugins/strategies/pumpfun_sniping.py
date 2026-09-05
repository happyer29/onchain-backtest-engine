"""Immutable Pump.fun launch sniping strategy with developer cooldown."""

from __future__ import annotations

from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AssetId, BundleId, ContentDigest
from backtest.domain.intents import (
    PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS,
    # Include pumpfun sniping sell decision delay ns so the intents dependency remains
    # explicit.
    PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS,
    RoundTripIntent,
)
from backtest.engine.sniping_contracts import (
    LaunchDecision,
    # Include launch decision status so the sniping contracts dependency remains explicit.
    LaunchDecisionStatus,
    LaunchTarget,
    ProtocolContractError,
    ProtocolContractErrorCode,
)

# Bind pumpfun sniping cooldown ns once as an explicit module-level contract.
PUMPFUN_SNIPING_COOLDOWN_NS = 600_000_000_000

PUMPFUN_SNIPING_STRATEGY_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.pumpfun-sniping-strategy-bundle.v2",
        {
            # Keep api version named so the v1 and api version payload passed to
            # domain_digest remains self-describing within module.
            "api_version": 2,
            "buy_delay_transactions": 500,
            "cooldown_seconds": 600,
            "execution_modes": [
                "EXOGENOUS_REPLAY",
                "EXOGENOUS_VIRTUAL_SETTLEMENT",
            ],
            "sell_all": True,
            # Keep sell decision delay seconds named so the v1 and api version payload
            # passed to domain_digest remains self-describing within module.
            "sell_decision_delay_seconds": 2,
        },
    ).hex
)


class PumpfunSnipingStrategy:
    """Emit one generic round-trip intent for every cooldown-eligible launch."""

    buy_delay_transactions = PUMPFUN_SNIPING_BUY_DELAY_TRANSACTIONS
    sell_decision_delay_ns = PUMPFUN_SNIPING_SELL_DECISION_DELAY_NS

    def __init__(
        self,
        *,
        # Keep the quote asset id input explicit in the init contract.
        quote_asset_id: AssetId,
        gross_buy_budget_atomic: int,
        buy_slippage_bps: int,
        sell_slippage_bps: int,
        sell_delay_transactions: int,
        execution_mode: ExecutionMode = ExecutionMode.EXOGENOUS_REPLAY,
        # Keep the bundle id input explicit in the init contract.
        bundle_id: BundleId | None = None,
    ) -> None:
        # Execute the pumpfun sniping strategy init workflow in explicit, reviewable
        # steps.
        if (
            isinstance(gross_buy_budget_atomic, bool)
            or not isinstance(gross_buy_budget_atomic, int)
            or gross_buy_budget_atomic <= 0
        ):
            # Fail the pumpfun sniping strategy init path with ValueError for gross buy
            # budget must be a positive integer when isinstance and gross buy budget
            # atomic is true; do not continue ambiguously.
            raise ValueError("gross buy budget must be a positive integer")
        for field_name, value in (
            ("buy_slippage_bps", buy_slippage_bps),
            ("sell_slippage_bps", sell_slippage_bps),
        ):
            # Process buy slippage bps and sell slippage bps inside the bounded pumpfun
            # sniping strategy init loop.
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
                raise ValueError(f"{field_name} must be in [0, 10000]")
        if (
            isinstance(sell_delay_transactions, bool)
            or not isinstance(sell_delay_transactions, int)
            # Keep sell delay transactions visible while evaluating the isinstance and
            # sell delay transactions guard.
            or sell_delay_transactions < 1
        ):
            raise ValueError("sell delay transactions must be positive")
        # The strategy may emit intents only for the two reviewed Pump.fun modes.
        supported_modes = {
            ExecutionMode.EXOGENOUS_REPLAY,
            ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        }
        # Raw strings must not bypass the typed strategy boundary.
        if not isinstance(execution_mode, ExecutionMode) or execution_mode not in supported_modes:
            raise ValueError("unsupported Pump.fun Sniping execution mode")
        self.quote_asset_id = quote_asset_id
        self.gross_buy_budget_atomic = gross_buy_budget_atomic
        # Assemble self buy slippage bps once so the pumpfun sniping strategy init
        # workflow shares one value.
        self.buy_slippage_bps = buy_slippage_bps
        self.sell_slippage_bps = sell_slippage_bps
        self.sell_delay_transactions = sell_delay_transactions
        self.execution_mode = execution_mode
        # Installed code identity and user-selected semantics stay separate.
        self._bundle_id = PUMPFUN_SNIPING_STRATEGY_BUNDLE_ID if bundle_id is None else bundle_id
        self._component_id = domain_digest(
            # Pass version tag explicitly so domain_digest receives a reviewable v1 and
            # bundle id input in pumpfun sniping strategy init.
            "backtest.configured-pumpfun-sniping-strategy.v2",
            {
                "bundle_id": self._bundle_id.hex,
                "buy_slippage_bps": buy_slippage_bps,
                "execution_mode": execution_mode.value,
                "gross_buy_budget_atomic": gross_buy_budget_atomic,
                # Keep quote asset id named so the v1 and bundle id payload passed to
                # domain_digest remains self-describing within pumpfun sniping strategy
                # init.
                "quote_asset_id": quote_asset_id.value,
                "sell_delay_transactions": sell_delay_transactions,
                "sell_slippage_bps": sell_slippage_bps,
            },
        )
        # Assemble self developer cooldown until ns once so the pumpfun sniping strategy
        # init workflow shares one value.
        self._developer_cooldown_until_ns: dict[str, int] = {}

    @property
    def bundle_id(self) -> BundleId:
        return self._bundle_id

    @property
    # Define pumpfun sniping strategy component id as one focused operation with an
    # explicit boundary.
    def component_id(self) -> ContentDigest:
        return self._component_id

    def decide(
        self,
        target: LaunchTarget,
        # Close the decide signature after its explicit inputs.
        *,
        decision_time_ns: int,
    ) -> LaunchDecision:
        # Execute the pumpfun sniping strategy decide workflow in explicit, reviewable
        # steps.
        current_until = self._developer_cooldown_until_ns.get(target.developer_id.value)
        decision = self.decide_from_cooldown(
            target,
            decision_time_ns=decision_time_ns,
            cooldown_until_ns=current_until,
            # Complete decide_from_cooldown only after its target and decision time ns inputs
            # are visible in pumpfun sniping strategy decide.
        )
        if decision.status is LaunchDecisionStatus.ELIGIBLE:
            if decision.cooldown_until_ns is None:  # pragma: no cover - constructor invariant
                raise AssertionError("eligible cooldown decision has no expiry")
            self._developer_cooldown_until_ns[target.developer_id.value] = (
                decision.cooldown_until_ns
            )
        return decision

    # Define pumpfun sniping strategy decide from cooldown as one focused operation with
    # an explicit boundary.
    def decide_from_cooldown(
        self,
        target: LaunchTarget,
        *,
        decision_time_ns: int,
        # Keep the cooldown until ns input explicit in the decide from cooldown contract.
        cooldown_until_ns: int | None,
    ) -> LaunchDecision:
        """Pure primitive decision seam for a caller-owned cooldown arena."""

        if (
            isinstance(decision_time_ns, bool)
            or not isinstance(decision_time_ns, int)
            or decision_time_ns < 0
            or decision_time_ns % 1_000_000_000
            # Evaluate the complete pumpfun sniping strategy decide from cooldown isinstance
            # and decision time ns condition before guarded effects.
        ):
            raise ValueError("decision time must have non-negative second resolution")
        if target.quote_asset_id != self.quote_asset_id:
            raise ProtocolContractError(ProtocolContractErrorCode.NON_SUPPORTED_QUOTE_ASSET)
        roundtrip_id = domain_digest(
            # Pass version tag explicitly so domain_digest receives a reviewable v1 and
            # block ordinal input in pumpfun sniping strategy decide from cooldown.
            "backtest.pumpfun-sniping-roundtrip.v1",
            {
                "block_ordinal": target.position.block_ordinal,
                "event_index": target.position.event_index,
                "network_id": target.position.network_id.value,
                # Keep position schema id named so the v1 and block ordinal payload passed
                # to domain_digest remains self-describing within pumpfun sniping strategy
                # decide from cooldown.
                "position_schema_id": target.position.position_schema_id.value,
                "strategy_component_id": self.component_id.hex,
                "target_event_id": target.target_event_id.hex,
                "transaction_index": target.position.transaction_index,
            },
            # Complete domain_digest only after its v1 and block ordinal inputs are visible in
            # pumpfun sniping strategy decide from cooldown.
        )
        if cooldown_until_ns is not None and (
            isinstance(cooldown_until_ns, bool)
            or not isinstance(cooldown_until_ns, int)
            or cooldown_until_ns < 0
            # Evaluate the complete pumpfun sniping strategy decide from cooldown cooldown
            # until ns and isinstance condition before guarded effects.
        ):
            raise ValueError("cooldown expiry must be a non-negative integer or None")
        if cooldown_until_ns is not None and decision_time_ns < cooldown_until_ns:
            # Handle the pumpfun sniping strategy decide from cooldown cooldown until ns
            # and decision time ns condition as a distinct block.
            return LaunchDecision(
                roundtrip_id=roundtrip_id,
                status=LaunchDecisionStatus.COOLDOWN_SUPPRESSED,
                cooldown_until_ns=cooldown_until_ns,
                intent=None,
                # Complete LaunchDecision only after its cooldown suppressed and roundtrip id
                # inputs are visible in pumpfun sniping strategy decide from cooldown.
            )

        cooldown_until = decision_time_ns + PUMPFUN_SNIPING_COOLDOWN_NS
        return LaunchDecision(
            roundtrip_id=roundtrip_id,
            status=LaunchDecisionStatus.ELIGIBLE,
            # Pass cooldown until ns explicitly so LaunchDecision receives a reviewable
            # eligible and target event id input in pumpfun sniping strategy decide from
            # cooldown.
            cooldown_until_ns=cooldown_until,
            intent=RoundTripIntent(
                roundtrip_id=roundtrip_id,
                target_event_id=target.target_event_id,
                target_position=target.position,
                # Pass asset id explicitly so RoundTripIntent receives a reviewable target
                # event id and position input in pumpfun sniping strategy decide from
                # cooldown.
                asset_id=target.asset_id,
                developer_id=target.developer_id,
                creation_user_id=target.creation_user_id,
                venue_id=target.venue_id,
                quote_asset_id=target.quote_asset_id,
                # Pass gross buy budget atomic explicitly so RoundTripIntent receives a
                # reviewable target event id and position input in pumpfun sniping
                # strategy decide from cooldown.
                gross_buy_budget_atomic=self.gross_buy_budget_atomic,
                buy_slippage_bps=self.buy_slippage_bps,
                sell_slippage_bps=self.sell_slippage_bps,
                sell_delay_transactions=self.sell_delay_transactions,
                # Mode is part of the intent and therefore downstream order identity.
                created_boundary_ordinal=target.position.boundary_ordinal,
                execution_mode=self.execution_mode,
                # Complete RoundTripIntent only after its target event id and position inputs
                # are visible in pumpfun sniping strategy decide from cooldown.
            ),
        )


__all__ = [
    "PUMPFUN_SNIPING_COOLDOWN_NS",
    "PUMPFUN_SNIPING_STRATEGY_BUNDLE_ID",
    # Keep the pumpfun sniping strategy component named inside the all contract.
    "PumpfunSnipingStrategy",
]
