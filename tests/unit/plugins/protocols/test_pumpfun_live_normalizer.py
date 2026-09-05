from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backtest.application.models import CapabilityStream
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange
from backtest.plugins.protocols.pumpfun import (
    PUMPFUN_CANONICAL_SOL_ASSET,
    PUMPFUN_LAUNCH_SOL_SOURCE_ASSET,
    PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
    PUMPFUN_LEGACY_TOKEN_PROGRAM,
    PUMPFUN_MIGRATION_MINT_AMOUNT,
    PUMPFUN_POOL_MIGRATION_FEE,
    PUMPFUN_REAL_SOL_OFFSET,
    PUMPFUN_REAL_TOKEN_OFFSET,
    PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
    PUMPFUN_TOKEN_2022_PROGRAM,
    PUMPFUN_TOKEN_TOTAL_SUPPLY,
    PUMPFUN_TRADE_SOL_SOURCE_ASSET,
    SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
    DerivedLifecycleGroupObservation,
    ExcludedLaunchObservation,
    PumpFeeProfile,
    PumpfunLiveNormalizationError,
    PumpfunLiveNormalizationErrorCode,
    PumpfunLiveNormalizer,
    SkippedSlotObservation,
)

_TIME = datetime(2026, 9, 1, tzinfo=UTC)
_FINGERPRINT = ContentDigest("a" * 64)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True, slots=True)
class _Batch:
    capability_id: CapabilityId
    covered_range: BlockRange
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    query_fingerprint: ContentDigest | None = _FINGERPRINT

    @property
    def row_count(self) -> int:
        return len(self.rows)


def test_block_stream_closes_every_slot_but_omits_exact_sentinel() -> None:
    normalizer = _normalizer()
    covered = _range(10, 14)
    capability = CapabilityId("pumpfun.block-clock.v2")
    observations: list[object] = []
    session = normalizer.begin(
        stream=CapabilityStream.BLOCK_CLOCK,
        capability_id=capability,
        covered_range=covered,
        observation_sink=observations.append,
    )
    first = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.BLOCK_CLOCK,
            covered,
            (_block_row(10, transactions=3), _sentinel_row(11)),
        )
    )
    second = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.BLOCK_CLOCK,
            covered,
            (_block_row(12, transactions=0), _block_row(13, transactions=9)),
        )
    )
    summary = session.finish()

    assert [row[0] for row in (*first.rows, *second.rows)] == [10, 12, 13]
    assert first.rows[0][1] == int(_TIME.timestamp()) * 1_000_000_000
    assert second.rows[0][2] == 0
    assert summary.raw_row_count == 4
    assert summary.normalized_row_count == 3
    assert summary.recognized_sentinel_count == 1
    assert observations == [
        SkippedSlotObservation(
            profile_id=SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
            block_ordinal=11,
        )
    ]
    assert session.result == summary


@pytest.mark.parametrize("case", ("gap", "duplicate", "malformed-sentinel", "conflict"))
def test_block_stream_rejects_gaps_duplicates_and_malformed_coverage(
    case: str,
) -> None:
    normalizer = _normalizer()
    covered = _range(10, 12)
    session = normalizer.begin(
        stream=CapabilityStream.BLOCK_CLOCK,
        capability_id=CapabilityId("pumpfun.block-clock.v2"),
        covered_range=covered,
    )
    rows = {
        "gap": (_block_row(10), _block_row(12)),
        "duplicate": (_block_row(10), _block_row(10)),
        "malformed-sentinel": (_block_row(10), _sentinel_row(11, validator="BROKEN")),
        "conflict": (_block_row(10), _block_row(11, payload_variant_count=2)),
    }[case]
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.normalize(
            _batch(
                normalizer,
                CapabilityId("pumpfun.block-clock.v2"),
                CapabilityStream.BLOCK_CLOCK,
                covered,
                rows,
            )
        )
    assert raised.value.code is PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE


def test_block_finish_rejects_an_unobserved_range_suffix() -> None:
    normalizer = _normalizer()
    covered = _range(10, 12)
    session = normalizer.begin(
        stream=CapabilityStream.BLOCK_CLOCK,
        capability_id=CapabilityId("pumpfun.block-clock.v2"),
        covered_range=covered,
    )
    session.normalize(
        _batch(
            normalizer,
            CapabilityId("pumpfun.block-clock.v2"),
            CapabilityStream.BLOCK_CLOCK,
            covered,
            (_block_row(10),),
        )
    )
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.finish()
    assert raised.value.code is PumpfunLiveNormalizationErrorCode.INCOMPLETE_BLOCK_RANGE


def test_produced_zero_transaction_block_accepts_nonsemantic_unknown_validator() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    session = normalizer.begin(
        stream=CapabilityStream.BLOCK_CLOCK,
        capability_id=CapabilityId("pumpfun.block-clock.v2"),
        covered_range=covered,
    )

    output = session.normalize(
        _batch(
            normalizer,
            CapabilityId("pumpfun.block-clock.v2"),
            CapabilityStream.BLOCK_CLOCK,
            covered,
            (_block_row(10, transactions=0, validator=b"UNKNOWN" + b"\x00" * 41),),
        )
    )

    assert output.rows[0][0] == 10
    assert output.rows[0][2] == 0
    assert session.finish().recognized_sentinel_count == 0


def test_launch_stream_maps_three_modes_and_excludes_mayhem_before_output() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.token-launch.v2")
    observations: list[object] = []
    session = normalizer.begin(
        stream=CapabilityStream.TOKEN_LAUNCH,
        capability_id=capability,
        covered_range=covered,
        observation_sink=observations.append,
    )
    output = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.TOKEN_LAUNCH,
            covered,
            (
                _launch_row(transaction=0, seed=1),
                _launch_row(
                    transaction=1,
                    seed=2,
                    token_program=PUMPFUN_TOKEN_2022_PROGRAM,
                ),
                _launch_row(
                    transaction=2,
                    seed=3,
                    token_program=PUMPFUN_TOKEN_2022_PROGRAM,
                    cashback_enabled=1,
                ),
                _launch_row(
                    transaction=3,
                    seed=4,
                    token_program=PUMPFUN_TOKEN_2022_PROGRAM,
                    mayhem_mode=1,
                ),
            ),
        )
    )
    summary = session.finish()
    mode_index = output.columns.index("mode")
    quote_index = output.columns.index("quote_asset")
    event_index = output.columns.index("event_index")

    assert [row[mode_index] for row in output.rows] == ["NORMAL", "TOKEN_2022", "CASHBACK"]
    assert {row[quote_index] for row in output.rows} == {PUMPFUN_CANONICAL_SOL_ASSET}
    assert [row[event_index] for row in output.rows] == [4, 4, 4]
    assert (summary.launch_classified_count, summary.launch_eligible_count) == (4, 3)
    assert summary.launch_excluded_count == 1
    assert observations == [
        ExcludedLaunchObservation(
            policy_id=PUMPFUN_LAUNCH_UNIVERSE_POLICY_ID,
            reason="MAYHEM_EXCLUDED",
            block_ordinal=10,
            transaction_index=3,
            event_index=4,
            signature=_signature(4),
            mint=_key(14),
        )
    ]


@pytest.mark.parametrize(
    "case", ("wrong-quote", "legacy-cashback", "unknown-program", "embedded-nul")
)
def test_launch_stream_rejects_wrong_quote_unknown_mode_and_identifier_junk(
    case: str,
) -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    session = normalizer.begin(
        stream=CapabilityStream.TOKEN_LAUNCH,
        capability_id=CapabilityId("pumpfun.token-launch.v2"),
        covered_range=covered,
    )
    cases: dict[str, dict[str, object]] = {
        "wrong-quote": {"quote_asset": PUMPFUN_TRADE_SOL_SOURCE_ASSET},
        "legacy-cashback": {
            "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
            "cashback_enabled": 1,
        },
        "unknown-program": {"token_program": _key(99)},
        "embedded-nul": {"mint": f"{_key(9)}\x00BROKEN"},
    }
    overrides = cases[case]
    row = _launch_row(transaction=0, seed=1) | overrides
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.normalize(
            _batch(
                normalizer,
                CapabilityId("pumpfun.token-launch.v2"),
                CapabilityStream.TOKEN_LAUNCH,
                covered,
                (row,),
            )
        )
    assert raised.value.code in {
        PumpfunLiveNormalizationErrorCode.IDENTIFIER_INVALID,
        PumpfunLiveNormalizationErrorCode.LAUNCH_CONTRACT_INVALID,
        PumpfunLiveNormalizationErrorCode.UNSUPPORTED_PROGRAM_MODE,
    }


def test_trade_stream_derives_curve_state_component_fees_and_preserves_dust_sell() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-trade.v2")
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        capability_id=capability,
        covered_range=covered,
    )
    output = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.PUMP_CURVE_TRADE,
            covered,
            (
                _trade_row(transaction=0, raw_instruction=2, quote_amount=101),
                _trade_row(
                    transaction=1,
                    raw_instruction=3,
                    direction="sell",
                    instruction_type="sell_v2",
                    quote_amount=0,
                ),
            ),
        )
    )
    summary = session.finish()
    indexes = {name: index for index, name in enumerate(output.columns)}

    assert output.rows[0][indexes["event_index"]] == 4
    assert output.rows[0][indexes["side"]] == "BUY"
    assert output.rows[0][indexes["protocol_fee_atomic"]] == 1
    assert output.rows[0][indexes["creator_fee_atomic"]] == 1
    assert output.rows[0][indexes["real_token_reserves_atomic"]] == 500
    assert output.rows[0][indexes["real_sol_reserves_lamports"]] == 101
    assert output.rows[1][indexes["side"]] == "SELL"
    assert output.rows[1][indexes["quote_amount_atomic"]] == 0
    assert output.rows[1][indexes["protocol_fee_atomic"]] == 0
    assert summary.normalized_row_count == 2


@pytest.mark.parametrize(
    "overrides",
    (
        {"direction": "buy", "instruction_type": "sell"},
        {"direction": "buy", "quote_amount_atomic": 0},
        {"failed": 1},
        {"payload_variant_count": 2},
        {"virtual_token_reserves_after_atomic": PUMPFUN_REAL_TOKEN_OFFSET - 1},
        {"mayhem_mode": 1},
    ),
)
def test_trade_stream_fails_closed_on_unsupported_or_conflicting_rows(
    overrides: dict[str, object],
) -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-trade.v2")
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        capability_id=capability,
        covered_range=covered,
    )
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.normalize(
            _batch(
                normalizer,
                capability,
                CapabilityStream.PUMP_CURVE_TRADE,
                covered,
                (_trade_row(transaction=0, raw_instruction=2) | overrides,),
            )
        )
    assert raised.value.code in {
        PumpfunLiveNormalizationErrorCode.BATCH_CONTRACT_INVALID,
        PumpfunLiveNormalizationErrorCode.TRADE_CONTRACT_INVALID,
        PumpfunLiveNormalizationErrorCode.UNSUPPORTED_PROGRAM_MODE,
    }


def test_lifecycle_stream_orders_terminal_completion_and_same_transaction_migration() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-lifecycle.v2")
    observations: list[object] = []
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_LIFECYCLE,
        capability_id=capability,
        covered_range=covered,
        observation_sink=observations.append,
    )
    signature = _signature(5)
    mint = _key(15)
    migration_sol = 900_000_000
    virtual_sol = migration_sol + PUMPFUN_POOL_MIGRATION_FEE + PUMPFUN_REAL_SOL_OFFSET
    completion = _completion_row(
        signature=signature,
        mint=mint,
        virtual_sol=virtual_sol,
    )
    migration = _migration_row(
        signature=signature,
        mint=mint,
        migration_sol=migration_sol,
        terminal_raw_instruction=2,
        terminal_virtual_sol=virtual_sol,
    )
    first = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
            covered,
            (completion,),
        )
    )
    second = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
            covered,
            (migration,),
        )
    )
    summary = session.finish()
    indexes = {name: index for index, name in enumerate(first.columns)}

    assert first.rows[0][indexes["event_index"]] == 5
    assert first.rows[0][indexes["lifecycle_kind"]] == "COMPLETED"
    assert second.rows[0][indexes["event_index"]] == 6
    assert second.rows[0][indexes["lifecycle_kind"]] == "MIGRATED"
    assert second.rows[0][indexes["real_sol_reserves_lamports"]] == (
        migration_sol + PUMPFUN_POOL_MIGRATION_FEE
    )
    assert summary.derived_lifecycle_group_count == 1
    assert observations == [
        DerivedLifecycleGroupObservation(
            profile_id=PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
            block_ordinal=10,
            transaction_index=7,
            terminal_event_index=4,
            completion_event_index=5,
            migration_event_index=6,
            signature=signature,
            mint=mint,
            curve_address=_key(25),
        )
    ]


def test_standalone_migration_uses_event_zero_and_derived_terminal_state() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-lifecycle.v2")
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_LIFECYCLE,
        capability_id=capability,
        covered_range=covered,
    )
    output = session.normalize(
        _batch(
            normalizer,
            capability,
            CapabilityStream.PUMP_CURVE_LIFECYCLE,
            covered,
            (_migration_row(),),
        )
    )
    indexes = {name: index for index, name in enumerate(output.columns)}

    assert output.rows[0][indexes["event_index"]] == 0
    assert output.rows[0][indexes["virtual_token_reserves_atomic"]] == (PUMPFUN_REAL_TOKEN_OFFSET)
    assert output.rows[0][indexes["token_total_supply_atomic"]] == PUMPFUN_TOKEN_TOTAL_SUPPLY
    assert output.rows[0][indexes["lifecycle"]] == "MIGRATED"
    assert session.finish().derived_lifecycle_group_count == 0


@pytest.mark.parametrize("case", ("unproved-terminal", "mint-profile", "fee-profile"))
def test_lifecycle_stream_rejects_unproved_suffix_and_profile_drift(
    case: str,
) -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-lifecycle.v2")
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_LIFECYCLE,
        capability_id=capability,
        covered_range=covered,
    )
    row = {
        "unproved-terminal": _migration_row(
            terminal_raw_instruction=2,
            terminal_virtual_sol=PUMPFUN_REAL_SOL_OFFSET + PUMPFUN_POOL_MIGRATION_FEE + 1,
        ),
        "mint-profile": _migration_row(
            migration_mint_amount_atomic=PUMPFUN_MIGRATION_MINT_AMOUNT - 1
        ),
        "fee-profile": _migration_row(pool_migration_fee_lamports=PUMPFUN_POOL_MIGRATION_FEE - 1),
    }[case]
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.normalize(
            _batch(
                normalizer,
                capability,
                CapabilityStream.PUMP_CURVE_LIFECYCLE,
                covered,
                (row,),
            )
        )
    assert raised.value.code is PumpfunLiveNormalizationErrorCode.LIFECYCLE_CONTRACT_INVALID


def test_normalized_stream_digest_is_independent_of_driver_batch_boundaries() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.token-launch.v2")
    rows = (_launch_row(transaction=0, seed=1), _launch_row(transaction=1, seed=2))

    one = normalizer.begin(
        stream=CapabilityStream.TOKEN_LAUNCH,
        capability_id=capability,
        covered_range=covered,
    )
    one.normalize(_batch(normalizer, capability, CapabilityStream.TOKEN_LAUNCH, covered, rows))
    one_summary = one.finish()

    split = normalizer.begin(
        stream=CapabilityStream.TOKEN_LAUNCH,
        capability_id=capability,
        covered_range=covered,
    )
    for row in rows:
        split.normalize(
            _batch(normalizer, capability, CapabilityStream.TOKEN_LAUNCH, covered, (row,))
        )
    split_summary = split.finish()

    assert split_summary.normalized_stream_digest == one_summary.normalized_stream_digest
    assert split_summary.ordered_exclusion_digest == one_summary.ordered_exclusion_digest


def test_raw_schema_fingerprint_and_fee_interval_are_strict() -> None:
    normalizer = _normalizer()
    covered = _range(10, 11)
    capability = CapabilityId("pumpfun.curve-trade.v2")
    session = normalizer.begin(
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        capability_id=capability,
        covered_range=covered,
    )
    wrong_columns = normalizer.raw_columns(CapabilityStream.PUMP_CURVE_TRADE)[:-1]
    with pytest.raises(PumpfunLiveNormalizationError) as raised:
        session.normalize(
            _Batch(
                capability_id=capability,
                covered_range=covered,
                columns=wrong_columns,
                rows=(),
            )
        )
    assert raised.value.code is PumpfunLiveNormalizationErrorCode.RAW_SCHEMA_MISMATCH

    expired = _normalizer(effective_until=_TIME)
    expired_session = expired.begin(
        stream=CapabilityStream.PUMP_CURVE_TRADE,
        capability_id=capability,
        covered_range=covered,
    )
    with pytest.raises(PumpfunLiveNormalizationError) as expired_error:
        expired_session.normalize(
            _batch(
                expired,
                capability,
                CapabilityStream.PUMP_CURVE_TRADE,
                covered,
                (_trade_row(transaction=0, raw_instruction=2),),
            )
        )
    assert expired_error.value.code is PumpfunLiveNormalizationErrorCode.FEE_PROFILE_INVALID


def test_config_digest_changes_with_effective_fee_profile() -> None:
    first = _normalizer()
    second = PumpfunLiveNormalizer(
        PumpFeeProfile.static_95_30(
            profile_id="pump-static-95-30-september-v2",
            effective_from_unix_s=int((_TIME - timedelta(days=1)).timestamp()),
            effective_until_unix_s=int((_TIME + timedelta(days=4)).timestamp()),
        )
    )
    assert first.config_digest == first.config_digest
    assert first.config_digest != second.config_digest


def _normalizer(*, effective_until: datetime | None = None) -> PumpfunLiveNormalizer:
    return PumpfunLiveNormalizer(
        PumpFeeProfile.static_95_30(
            profile_id="pump-static-95-30-september-v1",
            effective_from_unix_s=int((_TIME - timedelta(days=1)).timestamp()),
            effective_until_unix_s=int(
                (effective_until or (_TIME + timedelta(days=3))).timestamp()
            ),
        )
    )


def _range(start: int, end: int) -> BlockRange:
    return BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        start,
        end,
    )


def _batch(
    normalizer: PumpfunLiveNormalizer,
    capability: CapabilityId,
    stream: CapabilityStream,
    covered: BlockRange,
    rows: tuple[dict[str, object], ...],
) -> _Batch:
    columns = normalizer.raw_columns(stream)
    return _Batch(
        capability_id=capability,
        covered_range=covered,
        columns=columns,
        rows=tuple(tuple(row[column] for column in columns) for row in rows),
    )


def _block_row(
    block: int,
    *,
    transactions: int = 1,
    payload_variant_count: int = 1,
    validator: object | None = None,
) -> dict[str, object]:
    return {
        "block_ordinal": block,
        "block_time": _TIME + timedelta(seconds=block - 10),
        "block_hash": _fixed(_key(1)),
        "validator": _fixed(_key(2)) if validator is None else validator,
        "rewards": 0,
        "transaction_count": transactions,
        "source_row_count": 1,
        "payload_variant_count": payload_variant_count,
        "is_nonproduced_sentinel": 0,
    }


def _sentinel_row(block: int, *, validator: str | None = None) -> dict[str, object]:
    return {
        "block_ordinal": block,
        "block_time": datetime(1970, 1, 1, tzinfo=UTC),
        "block_hash": " " * 48,
        "validator": validator or ("MISSING" + " " * 41),
        "rewards": 0,
        "transaction_count": 0,
        "source_row_count": 1,
        "payload_variant_count": 1,
        "is_nonproduced_sentinel": 1,
    }


def _launch_row(
    *,
    transaction: int,
    seed: int,
    token_program: str = PUMPFUN_LEGACY_TOKEN_PROGRAM,
    cashback_enabled: int = 0,
    mayhem_mode: int = 0,
) -> dict[str, object]:
    return {
        "block_ordinal": 10,
        "block_time": _TIME,
        "transaction_index": transaction,
        "raw_instruction_index": 2,
        "signature": _signature(seed),
        "mint": _fixed(_key(seed + 10)),
        "creator": _fixed(_key(seed + 20)),
        "creation_user": _key(seed + 30),
        "curve_address": _fixed(_key(seed + 40)),
        "quote_asset": PUMPFUN_LAUNCH_SOL_SOURCE_ASSET,
        "mayhem_mode": mayhem_mode,
        "token_program": token_program,
        "cashback_enabled": cashback_enabled,
        "direct_pump_invocation": 1,
        "pump_program_index": 4,
        "parent_program": _key(80),
        "source_version": _TIME,
        "bundle_size": 1,
        "bundle_structure": "[]",
        "bundled_buys": 0,
        "bundled_buys_count": 0,
        "dev_balance": 0,
    }


def _trade_row(
    *,
    transaction: int,
    raw_instruction: int,
    direction: str = "buy",
    instruction_type: str = "buy_v2",
    quote_amount: int = 101,
) -> dict[str, object]:
    return {
        "block_ordinal": 10,
        "block_time": _TIME,
        "transaction_index": transaction,
        "raw_instruction_index": raw_instruction,
        "signature": _signature(transaction + 30),
        "mint": _key(10),
        "quote_asset": PUMPFUN_TRADE_SOL_SOURCE_ASSET,
        "direction": direction,
        "instruction_type": instruction_type,
        "base_amount_atomic": 100,
        "quote_amount_atomic": quote_amount,
        "virtual_token_reserves_after_atomic": PUMPFUN_REAL_TOKEN_OFFSET + 500,
        "virtual_sol_reserves_after_lamports": PUMPFUN_REAL_SOL_OFFSET + 101,
        "failed": 0,
        "signing_wallet": _key(11),
        "fee_payer": _key(12),
        "parent_program": _key(13),
        "provided_gas_fee_lamports": 1,
        "provided_gas_limit": 100_000,
        "network_fee_lamports": 5_001,
        "consumed_gas": 50_000,
        "pump_program_account_index": 3,
        "cu_price_instruction_index": 0,
        "cu_limit_instruction_index": 1,
        "tip_instruction_index": -1,
        "num_signatures": 1,
        "transaction_version": 0,
        "blockhash_prefix": "abc",
        "creation_block_ordinal": 9,
        "creation_transaction_index": 0,
        "creation_raw_instruction_index": 1,
        "creator": _key(14),
        "creation_user": _key(15),
        "curve_address": _key(16),
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _completion_row(
    *,
    signature: str | None = None,
    mint: str | None = None,
    virtual_sol: int = PUMPFUN_REAL_SOL_OFFSET + 1,
) -> dict[str, object]:
    return {
        "candidate_kind": "COMPLETION_CANDIDATE",
        "block_ordinal": 10,
        "block_time": _TIME,
        "transaction_index": 7,
        "raw_instruction_index": 2,
        "signature": signature or _signature(5),
        "mint": mint or _key(15),
        "curve_address": _key(25),
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "creation_block_ordinal": 9,
        "creation_transaction_index": 1,
        "creation_raw_instruction_index": 2,
        "terminal_raw_instruction_index": 2,
        "terminal_virtual_token_reserves_after_atomic": PUMPFUN_REAL_TOKEN_OFFSET,
        "terminal_virtual_sol_reserves_after_lamports": virtual_sol,
        "terminal_candidate_count": 1,
        "terminal_source_row_count": 1,
        "terminal_payload_variant_count": 1,
        "migration_user": None,
        "migration_mint_amount_atomic": None,
        "migration_sol_amount_lamports": None,
        "pool_migration_fee_lamports": None,
        "migration_pool": None,
        "migration_timestamp": None,
        "migration_parent_program": None,
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _migration_row(
    *,
    signature: str | None = None,
    mint: str | None = None,
    migration_sol: int = 1,
    terminal_raw_instruction: int | None = None,
    terminal_virtual_sol: int | None = None,
    migration_mint_amount_atomic: int = PUMPFUN_MIGRATION_MINT_AMOUNT,
    pool_migration_fee_lamports: int = PUMPFUN_POOL_MIGRATION_FEE,
) -> dict[str, object]:
    terminal = terminal_raw_instruction is not None
    return {
        "candidate_kind": "MIGRATION_CANDIDATE",
        "block_ordinal": 10,
        "block_time": _TIME,
        "transaction_index": 7,
        "raw_instruction_index": None,
        "signature": signature or _signature(5),
        "mint": mint or _key(15),
        "curve_address": _key(25),
        "token_program": PUMPFUN_LEGACY_TOKEN_PROGRAM,
        "cashback_enabled": 0,
        "mayhem_mode": 0,
        "creation_block_ordinal": 9,
        "creation_transaction_index": 1,
        "creation_raw_instruction_index": 2,
        "terminal_raw_instruction_index": terminal_raw_instruction,
        "terminal_virtual_token_reserves_after_atomic": (
            PUMPFUN_REAL_TOKEN_OFFSET if terminal else None
        ),
        "terminal_virtual_sol_reserves_after_lamports": terminal_virtual_sol,
        "terminal_candidate_count": 1 if terminal else 0,
        "terminal_source_row_count": 1 if terminal else 0,
        "terminal_payload_variant_count": 1 if terminal else 0,
        "migration_user": _key(35),
        "migration_mint_amount_atomic": migration_mint_amount_atomic,
        "migration_sol_amount_lamports": migration_sol,
        "pool_migration_fee_lamports": pool_migration_fee_lamports,
        "migration_pool": _key(45),
        "migration_timestamp": int(_TIME.timestamp()),
        "migration_parent_program": _key(55),
        "source_row_count": 1,
        "payload_variant_count": 1,
    }


def _fixed(value: str) -> str:
    return value + "\x00" * (48 - len(value))


def _key(seed: int) -> str:
    return _base58(bytes([seed]) * 32)


def _signature(seed: int) -> str:
    return _base58(bytes([seed]) * 64)


def _base58(value: bytes) -> str:
    leading_zeroes = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        encoded.append(_BASE58_ALPHABET[remainder])
    return "1" * leading_zeroes + "".join(reversed(encoded))
