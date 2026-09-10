"""Pump.fun copy-buy entry decisions with permanent per-run mint consumption."""

from __future__ import annotations

from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuyIntent, CopyBuyPolicy, CopyBuySignal
from backtest.domain.execution import ExecutionMode

# Inputs and policy are hashed separately from the installed code bundle.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, BundleId, ContentDigest


class PumpfunCopyBuyStrategy:
    """Claim the first delivered eligible BUY before any execution checks."""

    def __init__(
        self,
        *,
        signing_wallets: tuple[AccountId, ...],
        # User policy is separate from the installed immutable implementation bundle.
        policy: CopyBuyPolicy,
        bundle_id: BundleId,
        execution_mode: ExecutionMode,
        quote_asset_id: AssetId,
        # Admission bounds the consumed set; it never silently evicts old mints.
        maximum_consumed_mints: int,
    ) -> None:
        # A canonical wallet set cannot depend on input order or duplicate aliases.
        if not isinstance(signing_wallets, tuple) or not signing_wallets:
            raise ValueError("signing_wallets must be a nonempty tuple")
        if any(not isinstance(wallet, AccountId) for wallet in signing_wallets):
            raise TypeError("signing_wallets must contain AccountId values")
        ordered = tuple(sorted(set(signing_wallets), key=lambda wallet: wallet.value))
        # Resolver canonicalizes input; the executable component accepts exact bytes.
        if ordered != signing_wallets:
            raise ValueError("signing_wallets must be sorted and unique")
        if type(maximum_consumed_mints) is not int or maximum_consumed_mints < 1:
            raise ValueError("maximum_consumed_mints must be a positive integer")
        # Raw strings cannot bypass the closed exogenous execution contract.
        supported = (ExecutionMode.EXOGENOUS_REPLAY, ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT)
        if not isinstance(execution_mode, ExecutionMode) or execution_mode not in supported:
            raise ValueError("unsupported copy-buy execution mode")
        self.policy = policy
        self.bundle_id = bundle_id
        # Memory admission is operational and does not alter the meaning of a run.
        self._maximum_consumed_mints = maximum_consumed_mints
        self._wallets = frozenset(signing_wallets)
        self._consumed_mints: set[AssetId] = set()
        self._execution_mode = execution_mode
        self._quote_asset_id = quote_asset_id
        # Every selectable semantic operand is materialized before engine mutation.
        self.component_id = domain_digest(
            "backtest.configured-pumpfun-copy-buy.v1",
            {
                # Wallet spelling/order is canonicalized before hashing this closure.
                "bundle_id": bundle_id.hex,
                "signing_wallets": [wallet.value for wallet in signing_wallets],
                "policy": policy.document(),
                "execution_mode": execution_mode.value,
                # Quote units are part of identity, not inferred from account fees.
                "quote_asset_id": quote_asset_id.value,
            },
        )

    @property
    def signing_wallets(self) -> tuple[AccountId, ...]:
        """Expose immutable selection for preflight without consuming an entry signal."""
        return tuple(sorted(self._wallets, key=lambda wallet: wallet.value))

    def decide(
        self,
        signal: CopyBuySignal,
        *,
        # This is observation time, distinct from the historical BUY's position.
        decision_position: ChainPosition,
    ) -> CopyBuyIntent | None:
        """The caller supplies only in-range, non-Mayhem, proven BUY signals."""

        if signal.signing_wallet not in self._wallets:
            return None
        if signal.quote_asset_id != self._quote_asset_id:
            raise ValueError("copy signal has an unsupported quote asset")
        # A repeated leader BUY cannot reopen a closed or rejected position.
        if signal.asset_id in self._consumed_mints:
            return None
        if len(self._consumed_mints) >= self._maximum_consumed_mints:
            raise ValueError("copy-buy consumed-mint resource limit exceeded")
        # Identity binds the real source instruction and actual observation boundary.
        position_id = self._position_id(signal, decision_position)
        intent = CopyBuyIntent(
            position_id, signal, decision_position, self.policy, self._execution_mode
        )
        # This irreversible-in-run claim happens before any balance or quote check.
        self._consumed_mints.add(signal.asset_id)
        return intent

    def _position_id(self, signal: CopyBuySignal, decision: ChainPosition) -> ContentDigest:
        """The winning wallet and its signal cannot be substituted in results."""

        return domain_digest(
            "backtest.pumpfun-copy-buy-position.v1",
            {
                # The source event identifies a real instruction, not a content hash.
                "component_id": self.component_id.hex,
                "signal_event_id": signal.event_id.hex,
                "signing_wallet": signal.signing_wallet.value,
                # Exact typed coordinates prevent cross-chain and observation ambiguity.
                "network_id": signal.position.network_id.value,
                "position_schema_id": signal.position.position_schema_id.value,
                # Event index disambiguates several BUYs inside the same transaction.
                "signal_boundary": signal.position.boundary_ordinal,
                "signal_event_index": signal.position.event_index,
                "decision_boundary": decision.boundary_ordinal,
            },
        )
