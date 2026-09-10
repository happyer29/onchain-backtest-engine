"""Composition-owned exact copy strategy/protocol/account instances."""

from backtest.application.copy_run_contract import (
    COPY_MAXIMUM_DYNAMIC_ITEMS,
    COPY_MAXIMUM_EVENTS,
    COPY_MAXIMUM_POSITIONS,
    # Canonical draft reconstruction enforces fixed once-per-mint and retry policies.
    copy_draft_from_spec,
)
from backtest.application.ports.copy_runs import ResolvedCopyRuntime

# Bundle verification precedes plugin construction and every wallet mutation.
from backtest.application.ports.runs import RuntimeComponentReceipt
from backtest.application.run_specs import ReplayContract, ResolvedRunSpec
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_QUOTE_ASSET_ID
from backtest.bootstrap.copy_bundles import PumpfunCopyBuyBundleRegistry
from backtest.bootstrap.sniping_runtime import (
    # Financial profiles reuse the already verified Pump account and fee parsers.
    _pump_fee_profile,
    _solana_fee_profile,
    _wallet_account_profile,
)
from backtest.domain.hashing import domain_digest

# Reuse existing fee/account profile reducers with a separate copy execution identity.
from backtest.domain.identifiers import RuntimeLockId
from backtest.engine.copytrading import CopyReplayLimits
from backtest.engine.copytrading_run import CopyRunConfig
from backtest.engine.wallet_accounts import initial_wallet_provisioning_state
from backtest.plugins.networks.solana import SolanaSnipingCostModel

# The copy plugin retains original signer-bearing payloads and independent state views.
from backtest.plugins.protocols.pumpfun import PUMPFUN_UVA_SCHEMA_ID
from backtest.plugins.protocols.pumpfun.copybuy import PumpfunCopyBuyProtocolRuntime
from backtest.plugins.strategies.pumpfun_copybuy import PumpfunCopyBuyStrategy


class PumpfunCopyRuntimeResolver:
    """Reject stale config, runtime or bundle identities before preparing execution."""

    def __init__(
        self, runtime_lock_id: RuntimeLockId, registry: PumpfunCopyBuyBundleRegistry | None = None
    ) -> None:
        self._runtime_lock_id = runtime_lock_id
        self._registry = registry or PumpfunCopyBuyBundleRegistry()

    def resolve(self, spec: ResolvedRunSpec) -> ResolvedCopyRuntime:
        """Only the exact reference copy closure is currently admitted."""
        if (
            spec.runtime_lock_id != self._runtime_lock_id
            or spec.replay_contract is not ReplayContract.CANONICAL_EXACT
        ):
            raise ValueError("copy runtime requires its exact runtime lock and canonical contract")
        # Pinned bundle closure must match before constructing any strategy or protocol.
        closure = self._registry.snapshot()
        closure.require_components(spec.components, spec.dependency_merkle_root)
        draft = copy_draft_from_spec(spec)
        # Shared profile parsers reject unsupported versions and missing account schema prices.
        uva, account_profile = _wallet_account_profile(draft.wallet_account_profile.document())
        pump = _pump_fee_profile(draft.pump_fee_profile.document())
        buy_fee = _solana_fee_profile(draft.buy_solana_fee_profile.document())
        sell_fee = _solana_fee_profile(draft.sell_solana_fee_profile.document())
        bundles = {item.role: item.bundle_id for item in spec.components}

        def protocol_factory() -> PumpfunCopyBuyProtocolRuntime:
            """Each caller gets an empty reducer; historical and observed views cannot alias."""
            return PumpfunCopyBuyProtocolRuntime(
                quote_asset_id=PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                fee_profile=pump,
                protocol_version=pump.program_version,
                bundle_id=bundles["protocol:pumpfun"],
                # The protocol reducer starts empty and receives only later verified local events.
            )

        # Initial assets and all four runtime component identities are explicit run inputs.
        config = CopyRunConfig(
            PUMPFUN_SNIPING_QUOTE_ASSET_ID,
            draft.initial_sol_balance_lamports,
            draft.execution_mode,
            bundles["engine"],
            # Strategy and protocol identities are distinct even when they share pure math.
            bundles["strategy"],
            bundles["protocol:pumpfun"],
            bundles["network:solana"],
            # These are hard admission bounds; exceeding one fails the run rather than sampling it.
            initial_wallet_provisioning_state(uva, uva_schema_id=PUMPFUN_UVA_SCHEMA_ID),
            CopyReplayLimits(
                COPY_MAXIMUM_EVENTS, COPY_MAXIMUM_POSITIONS, COPY_MAXIMUM_DYNAMIC_ITEMS
            ),
            # Bind wallet list and profiles even if no source signal produces a fill.
            domain_digest(
                "backtest.copy-configured-run.v1",
                {
                    "components": [
                        {
                            # Each role binds implementation bytes, canonical config and interface
                            # version.
                            "role": item.role,
                            "bundle_id": item.bundle_id.hex,
                            "config_digest": item.config_digest.hex,
                            "api_version": item.api_version,
                        }
                        # Canonical component order comes from the resolved specification.
                        for item in spec.components
                    ],
                    "root_seed": spec.root_seed,
                },
            ),
            # Even a signal-free run remains bound to its explicit seed and component set.
        )
        # Selection and fee-free price policy are materialized before any signal can be consumed.
        strategy = PumpfunCopyBuyStrategy(
            signing_wallets=draft.signing_wallets,
            policy=draft.policy,
            bundle_id=bundles["strategy"],
            execution_mode=draft.execution_mode,
            # Strategy receives no source client, future labels or snapshot statistics.
            quote_asset_id=PUMPFUN_SNIPING_QUOTE_ASSET_ID,
            maximum_consumed_mints=COPY_MAXIMUM_POSITIONS,
        )
        # Buy and sell fees retain separate effective-dated profiles and account prices.
        costs = SolanaSnipingCostModel(
            buy_fee_profile=buy_fee,
            sell_fee_profile=sell_fee,
            account_cost_profile=account_profile,
            # The instantiated network component must match its resolved receipt.
            bundle_id=bundles["network:solana"],
        )
        # Receipts bind instantiated implementations to the exact resolved component configs.
        receipts = tuple(
            RuntimeComponentReceipt(item.role, item.bundle_id, item.config_digest)
            for item in spec.components
        )
        return ResolvedCopyRuntime(strategy, protocol_factory, costs, config, receipts)
