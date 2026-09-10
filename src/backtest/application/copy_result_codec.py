"""Strict reconstruction of the separate immutable copy position table schema."""

from backtest.application.copy_run_contract import copy_policy_from_document
from backtest.domain.account_requirements import account_component_from_document
from backtest.domain.chain import ChainPosition
from backtest.domain.copytrading import CopyBuyIntent, CopyBuySignal, CopyExitReason, TokenPrice
from backtest.domain.execution import ExecutionMode

# These identities cannot be inferred from filenames, row order or a parent table label.
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    ContentDigest,
    NetworkId,
    # Order, venue and position schema identities are decoded without aliases.
    OrderId,
    PositionSchemaId,
    VenueId,
)
from backtest.domain.roundtrips import MtmStatus

# Frozen core records revalidate position and attempt conservation on reconstruction.
from backtest.engine.copytrading_execution import CopyAttemptStatus
from backtest.engine.copytrading_results import CopyAttemptRecord, CopyPositionRecord
from backtest.engine.copytrading_state import CopyPositionStatus

# Immutable quote validation enforces integer amount/fee conservation and funding evidence.
from backtest.engine.sniping_contracts import (
    ProtocolLiquidityEvidence,
    ProtocolQuote,
    ProtocolQuoteSide,
)


def copy_decimal_document(value: object) -> object:
    """Transport every integer as canonical decimal text without touching identities."""
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return [copy_decimal_document(item) for item in value]
    # Booleans are policy values, not amounts, and must remain JSON booleans.
    if isinstance(value, dict):
        return {key: copy_decimal_document(item) for key, item in value.items()}
    return value


def copy_document_from_decimal(value: object, *, key: str = "") -> object:
    """Decode only declared numeric field families, never numeric-looking wallet addresses."""
    if isinstance(value, dict):
        return {name: copy_document_from_decimal(item, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [copy_document_from_decimal(item) for item in value]
    # Canonical amount, count and coordinate names are fixed by the copy v1 schemas.
    numeric = key.endswith(("_atomic", "_count", "_bps", "_seconds", "_transactions", "_ns"))
    numeric = numeric or key in {
        "attempt",
        "maximum_sell_attempts",
        "block_ordinal",
        # Coordinate fields are numeric; an all-digit wallet string is still an identity.
        "transaction_index",
        "event_index",
    }
    if value is None or not numeric:
        return value
    # Reject JSON numbers and aliases such as +1, leading zeroes or negative zero.
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("copy API integer must be bounded decimal text")
    try:
        result = int(value)
    except ValueError:
        # Malformed numeric text is a bounded codec error, not a leaked parser traceback.
        raise ValueError("copy API integer is not decimal text") from None
    # Reject signs, whitespace and leading zeros that would change canonical bytes.
    if str(result) != value:
        raise ValueError("copy API integer is not canonical")
    return result


def copy_position_from_document(value: object) -> CopyPositionRecord:
    """Reject unknown fields, stale schemas and any noncanonical reconstruction."""
    document = _object(value)
    # The signal retains the original signer and historical event coordinates.
    signal = CopyBuySignal(
        ContentDigest(_text(document["signal_event_id"])),
        _position(document["signal_position"]),
        AccountId(_text(document["signing_wallet"])),
        AssetId(_text(document["asset_id"])),
        # Source identity is the real successful BUY instruction and exact signer.
        VenueId(_text(document["venue_id"])),
        AssetId(_text(document["quote_asset_id"])),
    )
    intent = CopyBuyIntent(
        ContentDigest(_text(document["position_id"])),
        # Observation coordinates are separate from both source event and own fill coordinates.
        signal,
        _position(document["observation_position"]),
        copy_policy_from_document(document["policy"]),
        ExecutionMode(_text(document["execution_mode"])),
    )
    # Bound arrays before constructing record objects, even when a row file is otherwise verified.
    attempts = _array(document["attempts"], maximum=5)
    accounts = _array(document["account_components"], maximum=3)
    reason = document["exit_reason"]
    record = CopyPositionRecord(
        intent,
        # At most one entry and four sales can be reconstructed for a position.
        CopyPositionStatus(_text(document["status"])),
        tuple(_attempt(item) for item in attempts),
        # Ratios are reconstructed as positive reduced integer values, not floats.
        _integer(document["acquired_tokens_atomic"]),
        _price(document["entry_price"]),
        None if reason is None else CopyExitReason(_text(reason)),
        _optional_position(document["trigger_position"]),
        _price(document["trigger_price"]),
        # Account rows and cash postings remain separate from fee-free price triggers.
        tuple(account_component_from_document(item) for item in accounts),
        _integer(document["quote_cashflow_atomic"]),
        _optional_integer(document["realized_cash_pnl_atomic"]),
        # Complete/open economics retains its explicit nullable state across roundtrip decoding.
        _integer(document["cashback_receivable_atomic"]),
        MtmStatus(_text(document["mtm_status"])),
        _optional_integer(document["mtm_liquidation_value_atomic"]),
        _quote(document["mtm_quote"]),
        _optional_integer(document["economic_pnl_atomic"]),
        # Unknown liquidation keeps the full economic result nullable.
    )
    if record.document() != document:
        raise ValueError("copy position does not round-trip exactly")
    return record


def _attempt(value: object) -> CopyAttemptRecord:
    """A finalized instruction preserves reference/landing distinctions and actual paid costs."""
    row = _object(value)
    failure = row["failure_code"]
    return CopyAttemptRecord(
        OrderId(_text(row["order_id"])),
        _integer(row["attempt"]),
        # Decision and expected landing retain their explicit chain coordinates.
        _position(row["decision_position"]),
        # The original planned landing is kept even when no transaction was submitted.
        _position(row["expected_landing_position"]),
        CopyAttemptStatus(_text(row["status"])),
        _optional_position(row["landing_position"]),
        _quote(row["reference_quote"]),
        _quote(row["landing_quote"]),
        # Reference and landing quotes are not evidence of a successful fill by themselves.
        _integer(row["minimum_out_atomic"]),
        None if failure is None else _text(failure),
        _text(row["network_fee_asset_id"]),
        _integer(row["network_base_fee_paid_atomic"]),
        _integer(row["network_priority_fee_paid_atomic"]),
        # Actual paid network components stay separate from quoted protocol charges.
    )


def _quote(value: object) -> ProtocolQuote | None:
    """Quotes are pure immutable evidence; an attempt status determines whether they filled."""
    if value is None:
        return None
    row = _object(value)
    return ProtocolQuote(
        ProtocolQuoteSide(_text(row["side"])),
        # Quote assets are explicit so native network fees cannot change denomination.
        AssetId(_text(row["input_asset_id"])),
        # Amounts stay in explicit input/output atomic units, with no decimal conversion.
        AssetId(_text(row["output_asset_id"])),
        _integer(row["amount_in_atomic"]),
        _integer(row["amount_out_atomic"]),
        _integer(row["venue_input_atomic"]),
        _integer(row["venue_output_atomic"]),
        # Venue legs precede component fees and cashback; no float conversion is permitted.
        _integer(row["protocol_fee_atomic"]),
        _integer(row["creator_fee_atomic"]),
        _integer(row["cashback_receivable_atomic"]),
        # Fee destinations and synthetic sources stay available for ledger reconciliation.
        AccountId(_text(row["protocol_fee_account_id"])),
        AccountId(_text(row["creator_fee_account_id"])),
        AccountId(_text(row["cashback_source_account_id"])),
        _liquidity(row["liquidity"]),
    )


def _liquidity(value: object) -> ProtocolLiquidityEvidence | None:
    """The typed constructor proves shortfall math and strict/synthetic source consistency."""
    if value is None:
        return None
    row = _object(value)
    source = row["synthetic_source_account_id"]
    return ProtocolLiquidityEvidence(
        # Reference shortfall evidence is never automatically settled money.
        _text(row["policy_id"]),
        AssetId(_text(row["asset_id"])),
        _integer(row["required_output_atomic"]),
        _integer(row["observed_available_output_atomic"]),
        _integer(row["synthetic_shortfall_atomic"]),
        # Synthetic funding names its external ledger source when the mode permits it.
        None if source is None else AccountId(_text(source)),
    )


def _position(value: object) -> ChainPosition:
    """Decode the full immutable network/schema/coordinate tuple."""
    row = _object(value)
    return ChainPosition(
        NetworkId(_text(row["network_id"])),
        PositionSchemaId(_text(row["position_schema_id"])),
        _integer(row["block_ordinal"]),
        # An event index remains optional at an atomic transaction boundary.
        _integer(row["transaction_index"]),
        _optional_integer(row["event_index"]),
    )


def _optional_position(value: object) -> ChainPosition | None:
    """Missing execution boundaries remain absent instead of inheriting the signal position."""
    return None if value is None else _position(value)


def _price(value: object) -> TokenPrice | None:
    """No active price and a zero price are different states."""
    if value is None:
        return None
    row = _object(value)
    return TokenPrice(_integer(row["quote_atomic"]), _integer(row["token_atomic"]))


def _object(value: object) -> dict[str, object]:
    """Only JSON objects can carry named versioned record fields."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("copy result field must be an object")
    return value


def _array(value: object, *, maximum: int) -> list[object]:
    """A bounded row cannot expand into an unbounded instruction or account list."""
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("copy result array exceeds its fixed row contract")
    return value


def _integer(value: object) -> int:
    """Reject booleans, floats and numeric strings in canonical result bytes."""
    if type(value) is not int:
        raise ValueError("copy result amount must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    """Unknown economic amounts must not become zero during decoding."""
    return None if value is None else _integer(value)


def _text(value: object) -> str:
    """Every identifier or enum is an explicit bounded canonical string."""
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ValueError("copy result text must be bounded and trimmed")
    return value
