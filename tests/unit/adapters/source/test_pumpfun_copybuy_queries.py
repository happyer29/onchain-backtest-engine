"""Bounded independent candidate enumeration and full-history query contracts."""

from dataclasses import replace

import pytest
import test_pumpfun_indexer_v1 as base

# Adapter selection is immutable and independent of credentials or query execution.
from backtest.adapters.source.clickhouse.pumpfun_copybuy import PumpfunCopyBuyQueryProfile
from backtest.adapters.source.clickhouse.query import ClickHouseQueryPolicy
from backtest.adapters.source.clickhouse.reader import _stream_driver_parameters
from backtest.application.copy_source import CopySourceSelection
from backtest.application.models import CapabilityStream

# The copied wallet is a validated public key, never an interpolated SQL fragment.
from backtest.domain.identifiers import AccountId

WALLET = AccountId("4YK36Hp1f5ZN9Br1JroURgXk2f5R7CNunRPXkpdvkGmU")


def _profile():
    """Creation history explicitly begins before the leader-buy decision window."""
    selection = CopySourceSelection((WALLET,), base._range(100, 200), base._range(50, 200))
    return PumpfunCopyBuyQueryProfile(selection, base.PUMPFUN_INDEXER_V1_PROFILE)


def test_candidates_do_not_join_away_missing_creations() -> None:
    query = _profile().build_candidates(
        database="default", block_range=base._range(100, 150), policy=ClickHouseQueryPolicy()
    )
    assert "JOIN" not in query.sql and "pumpfun_token_creation" not in query.sql
    # Missing initialization cannot be hidden by joining candidates to creation rows.
    assert "signing_wallet IN {copy_signing_wallets:Array(String)}" in query.sql
    # Complete duplicate variants and multiplicity survive source occurrence grouping.
    assert "source_row_count" in query.columns and "payload_variant_count" in query.columns
    assert "fee_payer" in query.columns and "signing_wallet" in query.columns
    assert query.parameters["from_block_ordinal"] == 100
    assert query.parameters["to_block_ordinal"] == 150
    assert WALLET.value not in query.sql
    # Driver tuple serialization is not ClickHouse Array(String) syntax; convert at I/O only.
    parameters = _stream_driver_parameters(query)
    assert parameters["copy_signing_wallets"] == [WALLET.value]
    assert query.parameters["copy_signing_wallets"] == (WALLET.value,)


@pytest.mark.parametrize(
    "stream", (CapabilityStream.PUMP_CURVE_TRADE, CapabilityStream.PUMP_CURVE_LIFECYCLE)
)
def test_market_history_includes_all_signers_and_older_initialization(stream) -> None:
    # Every actor is needed to reconstruct the selected curves from bounded creation history.
    query = _profile().build_query(
        stream=stream,
        database="default",
        block_range=base._range(50, 250),
        # The query includes the bounded older history and right settlement extension.
        policy=ClickHouseQueryPolicy(),
    )
    # The outer market history is not restricted to leader trades; only mint membership is.
    assert "AND s.signing_wallet IN" not in query.sql
    assert query.parameters["decision_from_block_ordinal"] == 50
    assert query.parameters["decision_to_block_ordinal"] == 200
    assert query.parameters["copy_from_block_ordinal"] == 100
    assert query.parameters["copy_to_block_ordinal"] == 200
    # Original terminal migration and component reserve evidence stays in the shared template.
    assert "payload_variant_count" in query.sql
    assert "SELECT DISTINCT base_coin" in query.sql


def test_launch_history_keeps_known_mayhem_for_explicit_classification() -> None:
    query = _profile().build_query(
        stream=CapabilityStream.TOKEN_LAUNCH,
        database="default",
        block_range=base._range(50, 200),
        # Known Mayhem remains visible for explicit exclusion evidence rather than disappearing in
        # SQL.
        policy=ClickHouseQueryPolicy(),
    )
    assert "FINAL" in query.sql and "mayhem_mode" in query.columns
    assert "eligible_mayhem_mode" not in query.parameters
    # No creation target is extracted from the settlement-only suffix.
    with pytest.raises(ValueError, match="outside"):
        _profile().build_query(
            stream=CapabilityStream.TOKEN_LAUNCH,
            database="default",
            block_range=base._range(190, 210),
            # A launch query may not extend beyond the declared bounded initialization history.
            policy=ClickHouseQueryPolicy(),
        )


def test_source_queries_are_parameterized_bounded_and_identity_sensitive() -> None:
    profile = _profile()
    first = profile.build_candidates(
        database="default", block_range=base._range(100, 150), policy=ClickHouseQueryPolicy()
    )
    # Changing a typed source bound must change the immutable query fingerprint.
    second = profile.build_candidates(
        database="default", block_range=base._range(100, 151), policy=ClickHouseQueryPolicy()
    )
    assert first.fingerprint != second.fingerprint
    # Physical driver batch size is operational and cannot change logical query meaning.
    smaller = profile.build_candidates(
        database="default",
        block_range=base._range(100, 150),
        policy=ClickHouseQueryPolicy(max_block_size=1),
    )
    # Streaming batch size is physical and cannot change the selected logical query.
    assert smaller == first
    for forbidden in ("SELECT *", "OFFSET", "DELETE", ";"):
        assert forbidden not in first.sql


@pytest.mark.parametrize("wallets", ((), (WALLET, WALLET), (AccountId("leader"),)))
def test_source_selection_rejects_unknown_or_noncanonical_wallets(wallets) -> None:
    with pytest.raises(ValueError):
        CopySourceSelection(wallets, base._range(100, 200), base._range(50, 200))


def test_unsafe_database_and_outside_candidate_range_fail_before_query_execution() -> None:
    profile = _profile()
    with pytest.raises(ValueError):
        profile.build_candidates(
            database="default;SELECT",
            # Unsafe identifiers must fail during query construction before any driver call.
            block_range=base._range(100, 150),
            policy=ClickHouseQueryPolicy(),
        )
    # A candidate query cannot accidentally enumerate new entries in the settlement tail.
    with pytest.raises(ValueError):
        profile.build_candidates(
            database="default", block_range=base._range(190, 210), policy=ClickHouseQueryPolicy()
        )
    with pytest.raises(ValueError):
        # The initialization range cannot begin after the first possible decision.
        replace(profile.selection, history_range=base._range(101, 200))
