"""Integer price and immutable policy contracts for copy-buy execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import gcd

# Core policy identity is independent of source transport and physical replay.
from backtest.domain.chain import ChainPosition
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import AccountId, AssetId, ContentDigest, VenueId

# These version tags distinguish copy-buy inputs from the fixed Sniping contract.
COPY_BUY_POLICY_SCHEMA = "pumpfun-copy-buy-policy/v1"
COPY_BUY_PRICE_POLICY = "fill-curve-input-to-observed-marginal-price/v1"
MAXIMUM_SELL_ATTEMPTS = 4
# Retry time starts at failure, separately from the next order's latency.
SELL_RETRY_DELAY_NS = 2_000_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000


class CopyExitReason(StrEnum):
    """The first causal exit reason remains latched across retries."""

    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAXIMUM_HOLD = "MAXIMUM_HOLD"


def require_integer(value: int, name: str, *, minimum: int = 0) -> None:
    """Booleans and fractional numbers cannot enter integer execution policy."""

    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def require_solana_wallet(wallet: AccountId) -> None:
    """Validate a canonical 32-byte base58 address without an external dependency."""
    if not isinstance(wallet, AccountId):
        raise TypeError("copy signing wallet must be an AccountId")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value = wallet.value
    # Public keys have a bounded spelling; no arbitrary-size integer enters validation.
    if not 32 <= len(value) <= 44 or any(character not in alphabet for character in value):
        raise ValueError("copy signing wallet must be a Solana public key")
    number = 0
    for character in value:
        number = number * 58 + alphabet.index(character)
    # Leading zero bytes are represented by exactly one leading '1' each.
    leading = len(value) - len(value.lstrip("1"))
    if leading + (number.bit_length() + 7) // 8 != 32:
        raise ValueError("copy signing wallet must decode to exactly 32 bytes")


@dataclass(frozen=True, slots=True)
class TokenPrice:
    """Reduced positive ratio of quote atomic units to token atomic units."""

    quote_atomic: int
    token_atomic: int

    def __post_init__(self) -> None:
        # Reduction gives equivalent ratios one canonical representation.
        require_integer(self.quote_atomic, "quote_atomic", minimum=1)
        require_integer(self.token_atomic, "token_atomic", minimum=1)
        divisor = gcd(self.quote_atomic, self.token_atomic)
        object.__setattr__(self, "quote_atomic", self.quote_atomic // divisor)
        object.__setattr__(self, "token_atomic", self.token_atomic // divisor)

    def scaled_comparison(self, entry: TokenPrice, multiplier_bps: int) -> int:
        """Return a signed exact comparison with entry * multiplier / 10000."""

        require_integer(multiplier_bps, "multiplier_bps")
        current_scaled = self.quote_atomic * entry.token_atomic * 10_000
        entry_scaled = entry.quote_atomic * self.token_atomic * multiplier_bps
        return current_scaled - entry_scaled

    def document(self) -> dict[str, int]:
        """The unit-bearing ratio is retained without a floating-point price."""

        return {"quote_atomic": self.quote_atomic, "token_atomic": self.token_atomic}


@dataclass(frozen=True, slots=True)
class CopyBuyPolicy:
    """Explicit thresholds and independent latencies; retry rules are fixed."""

    gross_buy_budget_atomic: int
    take_profit_bps: int
    stop_loss_bps: int
    maximum_hold_seconds: int
    # Observation may be immediate; submitted instructions always land later.
    observation_delay_transactions: int
    buy_delay_transactions: int
    sell_delay_transactions: int
    buy_slippage_bps: int
    sell_slippage_bps: int

    def __post_init__(self) -> None:
        # Positive durations make the compact-clock duration ceiling unambiguous.
        positive = (
            "gross_buy_budget_atomic",
            "take_profit_bps",
            "stop_loss_bps",
            "maximum_hold_seconds",
            # Zero order delay would violate strictly later landing causality.
            "buy_delay_transactions",
            "sell_delay_transactions",
        )
        # Validate all numerics before allowing them into a semantic digest.
        for name in positive:
            require_integer(getattr(self, name), name, minimum=1)
        require_integer(self.observation_delay_transactions, "observation_delay_transactions")
        if self.stop_loss_bps > 10_000:
            raise ValueError("stop_loss_bps must be <= 10000")
        # Full slippage tolerance is permitted consistently with existing execution.
        for name in ("buy_slippage_bps", "sell_slippage_bps"):
            require_integer(getattr(self, name), name)
            if getattr(self, name) > 10_000:
                raise ValueError(f"{name} must be <= 10000")

    @property
    def maximum_hold_ns(self) -> int:
        """Modeled holding duration uses the source clock's second resolution."""

        return self.maximum_hold_seconds * NANOSECONDS_PER_SECOND

    def price_exit(self, entry: TokenPrice, current: TokenPrice) -> CopyExitReason | None:
        """Inclusive integer thresholds; transaction fees do not enter this test."""

        if current.scaled_comparison(entry, 10_000 - self.stop_loss_bps) <= 0:
            return CopyExitReason.STOP_LOSS
        if current.scaled_comparison(entry, 10_000 + self.take_profit_bps) >= 0:
            return CopyExitReason.TAKE_PROFIT
        return None

    def document(self) -> dict[str, object]:
        """Materialize fixed rules alongside user inputs for semantic identity."""

        return {
            "schema": COPY_BUY_POLICY_SCHEMA,
            "price_policy": COPY_BUY_PRICE_POLICY,
            "gross_buy_budget_atomic": self.gross_buy_budget_atomic,
            # Exit and retry policies are versioned even when not user-selectable.
            "take_profit_bps": self.take_profit_bps,
            "stop_loss_bps": self.stop_loss_bps,
            "maximum_hold_seconds": self.maximum_hold_seconds,
            "maximum_sell_attempts": MAXIMUM_SELL_ATTEMPTS,
            "sell_retry_delay_ns": SELL_RETRY_DELAY_NS,
            # A failed entry consumes the mint; successful close never releases it.
            "consume_mint_on_signal": True,
            "sell_all": True,
            "observation_delay_transactions": self.observation_delay_transactions,
            "buy_delay_transactions": self.buy_delay_transactions,
            "sell_delay_transactions": self.sell_delay_transactions,
            # Slippage is execution policy, separate from the TP/SL price test.
            "buy_slippage_bps": self.buy_slippage_bps,
            "sell_slippage_bps": self.sell_slippage_bps,
        }

    @property
    def identity(self) -> ContentDigest:
        """Changing any policy operand creates a different configured strategy."""

        return domain_digest("backtest.copy-buy-policy.v1", self.document())


@dataclass(frozen=True, slots=True)
class CopyBuySignal:
    """A proven successful BUY, delivered only after its atomic transaction."""

    event_id: ContentDigest
    position: ChainPosition
    signing_wallet: AccountId
    asset_id: AssetId
    # Venue identity and the quote asset are supplied by protocol projection.
    venue_id: VenueId
    quote_asset_id: AssetId

    def __post_init__(self) -> None:
        # A signal must identify an instruction, not only its transaction group.
        if self.position.event_index is None:
            raise ValueError("copy signal requires an exact event position")
        if self.asset_id == self.quote_asset_id:
            raise ValueError("copy signal must exchange different assets")


@dataclass(frozen=True, slots=True)
class CopyBuyIntent:
    """A position intent whose target is a BUY, not a fabricated launch."""

    roundtrip_id: ContentDigest
    signal: CopyBuySignal
    decision_position: ChainPosition
    policy: CopyBuyPolicy
    # The two existing modes retain their explicit financial interpretation.
    execution_mode: ExecutionMode

    def __post_init__(self) -> None:
        # Delayed observation may move a decision into the proven settlement tail.
        source = self.signal.position
        decision = self.decision_position
        source_chain = (source.network_id, source.position_schema_id)
        decision_chain = (decision.network_id, decision.position_schema_id)
        # Matching numeric ordinals on different chains are not comparable.
        if source_chain != decision_chain:
            raise ValueError("copy decision has a different chain identity")
        # Integer ordinals may be compared only after matching their schemas.
        if decision.boundary_ordinal < source.boundary_ordinal:
            raise ValueError("copy decision precedes its source purchase")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        # Virtual settlement changes sell solvency only, never signal eligibility.
        if self.execution_mode not in (
            ExecutionMode.EXOGENOUS_REPLAY,
            ExecutionMode.EXOGENOUS_VIRTUAL_SETTLEMENT,
        ):
            raise ValueError("unsupported copy-buy execution mode")

    @property
    def target_position(self) -> ChainPosition:
        """Shared quote/account math uses the real signal's network identity."""

        return self.signal.position

    @property
    def asset_id(self) -> AssetId:
        """The position always holds the token named by the original signal."""

        return self.signal.asset_id

    @property
    def quote_asset_id(self) -> AssetId:
        """Fees must remain explicitly asset-tagged by the execution layer."""

        return self.signal.quote_asset_id

    @property
    def venue_id(self) -> VenueId:
        """Every retry remains on the original pre-migration venue."""

        return self.signal.venue_id

    @property
    def gross_buy_budget_atomic(self) -> int:
        """Shared buy math receives the configured budget including Pump fees."""

        return self.policy.gross_buy_budget_atomic
