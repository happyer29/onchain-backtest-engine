"""Fixed bounded copy-buy queries over the audited physical OnchainDivers profile."""

from dataclasses import dataclass
from typing import Any

from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    _TABLES,
    # Reuse the pinned physical projection and bounds without inheriting launch-only selection.
    PumpfunIndexerV1Profile,
    PumpfunIndexerV1Query,
    _aggregated_projection,
    _common_parameters,
    _eligible_launch_sql,
    # Query identity records exact SQL and typed operands before any remote read.
    _query_fingerprint,
    _trade_source_projection,
    _validate_ranges,
)
from backtest.adapters.source.clickhouse.query import ClickHouseQueryPolicy, quoted_identifier

# Wallet selection is an application contract; source slot mapping stays in this adapter.
from backtest.application.copy_source import CopySourceSelection
from backtest.application.models import CapabilityStream
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest

# Slot mapping, physical names and exact duplicate checks remain adapter-owned.
from backtest.domain.time import BlockRange


@dataclass(frozen=True, slots=True)
class PumpfunCopyBuyQueryProfile:
    """Candidate enumeration is independent of creation availability and classification."""

    selection: CopySourceSelection
    physical: PumpfunIndexerV1Profile

    @property
    def template_digest(self) -> ContentDigest:
        """Pin the shared physical transform and separate candidate/history selection logic."""
        return domain_digest(
            "backtest.pumpfun-copy-query-template.v1",
            {
                "physical_template_digest": self.physical.template_digest.hex,
                "candidate_enumeration": "independent-successful-sol-buy-occurrences-v1",
                # All market actors must be retained after the candidate mint set is fixed.
                "market_selection": "all-signers-candidate-mints-bounded-creation-v1",
            },
        )

    def build_candidates(
        self, *, database: str, block_range: BlockRange, policy: ClickHouseQueryPolicy
    ) -> PumpfunIndexerV1Query:
        """Enumerate all candidate occurrences before any JOIN can hide a missing mint."""
        _validate_ranges(block_range, self.selection.decision_range, policy)
        _require_contained(block_range, self.selection.decision_range)
        values = tuple(item for item in _trade_source_projection() if not item[1].startswith("l."))
        # Candidate enumeration deliberately has no creation join that could hide missing mints.
        projection = _aggregated_projection(
            values, grouped_names=frozenset({"signature", "raw_instruction_index"})
        )
        # Multiplicity is preserved and exact duplicate collapse retains its variant proof.
        variants = ", ".join(expression for _, expression in values)
        sql = f"""SELECT {projection},
    count() AS source_row_count,
    uniqExact(tuple({variants})) AS payload_variant_count
FROM {_table(database, CapabilityStream.PUMP_CURVE_TRADE)} AS s
PREWHERE s.slot >= {{from_block_ordinal:UInt64}}
    AND s.slot < {{to_block_ordinal:UInt64}}
WHERE s.failed = {{successful_failed_flag:UInt8}}
    AND s.direction = {{copy_buy_direction:String}}
    AND s.quote_coin = {{wrapped_sol_quote:String}}
    AND s.signing_wallet IN {{copy_signing_wallets:Array(String)}}
GROUP BY s.signature, s.ix_idx
ORDER BY block_ordinal, transaction_index, raw_instruction_index, signature"""
        # Wallets and range values are typed parameters, never SQL interpolation.
        parameters = _common_parameters(block_range)
        parameters.update(self._candidate_parameters())
        columns = (*tuple(name for name, _ in values), "source_row_count", "payload_variant_count")
        return self._query("candidates", sql, parameters, columns)

    def build_query(
        self,
        *,
        stream: CapabilityStream,
        database: str,
        # Every extraction call carries a typed half-open range and hard query limits.
        block_range: BlockRange,
        policy: ClickHouseQueryPolicy,
    ) -> PumpfunIndexerV1Query:
        """Read complete market history only for independently enumerated candidate mints."""
        _validate_ranges(block_range, self.selection.history_range, policy)
        if block_range.from_block_ordinal < self.selection.history_range.from_block_ordinal:
            raise ValueError("copy shard precedes declared initialization history")
        if stream is CapabilityStream.TOKEN_LAUNCH:
            _require_contained(block_range, self.selection.history_range)
        # The shared fixed templates retain reserve, fee, skipped-slot and migration details.
        base = self.physical.build_query(
            stream=stream,
            database=database,
            block_range=block_range,
            decision_range=self.selection.history_range,
            # Creation history is broader than the decision range but remains explicitly bounded.
            policy=policy,
        )
        sql, parameters = base.sql, dict(base.parameters)
        if stream is not CapabilityStream.BLOCK_CLOCK:
            membership = self._candidate_mints_sql(database)
            # Only non-clock streams restrict membership; latency counts all global transactions.
            sql = self._restrict_mints(sql, stream, database, membership)
            # Independent candidate selection keeps its own actual decision-range operands.
            parameters.update(self._candidate_parameters())
            parameters["copy_from_block_ordinal"] = self.selection.decision_range.from_block_ordinal
            parameters["copy_to_block_ordinal"] = self.selection.decision_range.to_block_ordinal
        return self._query(stream.value.lower().replace("_", "-"), sql, parameters, base.columns)

    def _restrict_mints(
        self, sql: str, stream: CapabilityStream, database: str, membership: str
    ) -> str:
        """Require an exact known template fragment; a changed base template fails closed."""
        if stream is CapabilityStream.TOKEN_LAUNCH:
            fragment = "WHERE quote_coin = {native_sol_quote:String}"
            if sql.count(fragment) != 1:
                raise ValueError("copy launch template no longer matches the pinned source")
            # Known Mayhem creations are retained for classification and exclusion evidence.
            return sql.replace(
                fragment, fragment + f"\n    AND toStringCutToZero(mint) IN ({membership})"
            )
        # The pinned launch fragment must match before applying copy mint membership.
        fragment = _eligible_launch_sql(_table(database, CapabilityStream.TOKEN_LAUNCH))
        if fragment not in sql:
            raise ValueError("copy market template no longer matches the pinned source")
        # Every required trade/lifecycle branch uses the same bounded eligible mint set.
        return sql.replace(
            fragment, fragment + f"\n        AND toStringCutToZero(mint) IN ({membership})"
        )

    def _candidate_mints_sql(self, database: str) -> str:
        """DISTINCT is set membership only; source event multiplicity is validated separately."""
        return f"""SELECT DISTINCT base_coin
    FROM {_table(database, CapabilityStream.PUMP_CURVE_TRADE)}
    PREWHERE slot >= {{copy_from_block_ordinal:UInt64}}
        AND slot < {{copy_to_block_ordinal:UInt64}}
    WHERE failed = {{successful_failed_flag:UInt8}}
        AND direction = {{copy_buy_direction:String}}
        AND quote_coin = {{wrapped_sol_quote:String}}
        AND signing_wallet IN {{copy_signing_wallets:Array(String)}}"""

    def _candidate_parameters(self) -> dict[str, Any]:
        """The signer whitelist never substitutes fee payer or inferred ownership."""
        return {
            "successful_failed_flag": 0,
            "copy_buy_direction": "buy",
            "wrapped_sol_quote": self.physical.wrapped_sol_quote,
            "copy_signing_wallets": tuple(
                # Wallet tuples remain immutable here and become driver arrays only at the wire
                # boundary.
                wallet.value
                for wallet in self.selection.signing_wallets
            ),
        }

    def _query(
        self, suffix: str, sql: str, parameters: dict[str, Any], columns: tuple[str, ...]
    ) -> PumpfunIndexerV1Query:
        """Keep physical-profile validation while versioning copy-specific query identity."""
        template_id = f"pumpfun-copybuy-{suffix}-v1"
        fingerprint = _query_fingerprint(
            profile_id=self.physical.profile_id,
            template_id=template_id,
            template_digest=self.template_digest,
            # Physical SQL and parameters both enter the query fingerprint.
            sql=sql,
            parameters=parameters,
        )
        # The reader independently rebuilds this exact query from immutable operands.
        return PumpfunIndexerV1Query(
            profile_id=self.physical.profile_id,
            template_id=template_id,
            sql=sql,
            parameters=parameters,
            # Explicit result columns support streaming decoding without SELECT star.
            columns=columns,
            block_ordinal_column_index=columns.index("block_ordinal"),
            fingerprint=fingerprint,
        )


def _table(database: str, stream: CapabilityStream) -> str:
    """Only the audited table mapping and validated deployment database can enter SQL."""
    return f"{quoted_identifier(database)}.{quoted_identifier(_TABLES[stream])}"


def _require_contained(candidate: BlockRange, outer: BlockRange) -> None:
    """A candidate/creation query cannot scan outside its declared half-open range."""
    if (candidate.network_id, candidate.position_schema_id) != (
        outer.network_id,
        outer.position_schema_id,
    ):
        raise ValueError("copy source ranges have different chain identities")
    # Containment is checked only after confirming the same immutable network and schema.
    if (
        candidate.from_block_ordinal < outer.from_block_ordinal
        or candidate.to_block_ordinal > outer.to_block_ordinal
    ):
        raise ValueError("copy source subrange is outside its declared range")
