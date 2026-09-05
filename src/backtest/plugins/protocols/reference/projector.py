"""Column-mapped projector for proven block, creation and swap semantics.

This plugin deliberately consumes logical capability columns, not ClickHouse
table names.  A source adapter may map a second indexer into the same contract
without changing protocol semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

# Import typing at the visible module dependency boundary.
from typing import Any

from backtest.application.build_tool_roles import CANONICAL_PROJECTOR_ROLE
from backtest.application.code_bundles import (
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
    # Close the code bundles import after its required symbols are visible.
)
from backtest.application.errors import SnapshotValidationError, SnapshotValidationErrorCode
from backtest.application.models import DatasetSpec
from backtest.application.ports.canonical import CanonicalSnapshotCandidate
from backtest.application.ports.source import IndexedBatch

# Import chain at the visible module dependency boundary.
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import IdentityFidelity, OrderingFidelity

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    AccountId,
    AssetId,
    BundleId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    FeeComponentId,
    ProtocolPayloadSchemaId,
    VenueId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.market_events import (
    REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
    BlockEvent,
    CanonicalEvent,
    # Include chain position so the market events dependency remains explicit.
    ChainPosition,
    EventEnvelope,
    EventKind,
    FeeComponent,
    SwapEvent,
    # Include token creation event so the market events dependency remains explicit.
    TokenCreationEvent,
    reference_amm_trade_payload,
)

_REFERENCE_LAUNCH_PAYLOAD_SCHEMA_ID = ProtocolPayloadSchemaId("reference-token-launch-payload-v1")
_REFERENCE_QUOTE_ASSET_ID = AssetId("SOL")

# Bind unit projector code bundle id once as an explicit module-level contract.
_UNIT_PROJECTOR_CODE_BUNDLE_ID = BundleId(
    domain_digest(
        "backtest.reference-protocol-projector-unit-code.v1",
        {"authority": "isolated-unit-default-only"},
    ).hex
    # Complete BundleId only after its v1 and authority inputs are visible in module.
)


def _unit_projector_tools() -> PinnedCodeBundleSet:
    # Execute the unit projector tools workflow in explicit, reviewable steps.
    return PinnedCodeBundleSet(
        (
            PinnedCodeBundleIdentity.for_unit_tests(
                CANONICAL_PROJECTOR_ROLE,
                _UNIT_PROJECTOR_CODE_BUNDLE_ID,
                # Complete for_unit_tests only after its canonical projector role and unit
                # projector code bundle id inputs are visible in unit projector tools.
            ),
        )
    )


# Keep the projection kind contract and validation rules together.
class ProjectionKind(StrEnum):
    BLOCK = "BLOCK"
    TOKEN_CREATION = "TOKEN_CREATION"
    SWAP = "SWAP"


# Keep the projection spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    capability_id: CapabilityId
    kind: ProjectionKind
    protocol: str
    # Declare protocol version explicitly in the projection spec contract.
    protocol_version: str
    identity_fidelity: IdentityFidelity
    ordering_fidelity: OrderingFidelity
    source_total_key: tuple[str, ...]
    source_total_key_is_proven: bool
    # Declare columns explicitly in the projection spec contract.
    columns: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        # Execute the projection spec post init workflow in explicit, reviewable steps.
        if not self.protocol or self.protocol != self.protocol.strip():
            raise ValueError("projection protocol must be non-empty and trimmed")
        if not self.protocol_version or self.protocol_version != self.protocol_version.strip():
            raise ValueError("projection protocol_version must be non-empty and trimmed")
        names = tuple(name for name, _ in self.columns)
        # Assemble physical once so the projection spec post init workflow shares one
        # value.
        physical = tuple(name for _, name in self.columns)
        if len(set(names)) != len(names) or len(set(physical)) != len(physical):
            raise ValueError("projection column aliases and sources must be unique")
        if any(not column or column != column.strip() for column in self.source_total_key):
            raise ValueError("source total-key columns must be non-empty and trimmed")
        # Evaluate the complete projection spec post init source total key condition
        # before guarded effects.
        if len(set(self.source_total_key)) != len(self.source_total_key):
            raise ValueError("source total-key columns must be unique")
        if self.source_total_key_is_proven and not self.source_total_key:
            raise ValueError("proven source total key must not be empty")
        if self.source_total_key and not self.source_total_key_is_proven:
            # Fail the projection spec post init path with ValueError for an unproven
            # source total key cannot identify occurrences when source total key and
            # source total key is proven is true; do not continue ambiguously.
            raise ValueError("an unproven source total key cannot identify occurrences")
        if self.identity_fidelity is IdentityFidelity.EXACT and not self.source_total_key_is_proven:
            raise ValueError("exact source identity requires a proven total key")
        required = {
            ProjectionKind.BLOCK: {"slot"},
            # Keep the projection kind component named inside the required contract.
            ProjectionKind.TOKEN_CREATION: {
                "slot",
                "transaction_index",
                "event_index",
                "signature",
                # Keep the asset id component named inside the required contract.
                "asset_id",
                "creator_id",
            },
            ProjectionKind.SWAP: {
                "slot",
                # Keep the transaction index component named inside the required contract.
                "transaction_index",
                "event_index",
                "signature",
                "pool_id",
                "sold_asset_id",
                # Keep the bought asset id component named inside the required contract.
                "bought_asset_id",
                "sold_amount_atomic",
                "bought_amount_atomic",
                "fee_amount_atomic",
                "pool_asset_a_id",
                # Keep the pool asset b id component named inside the required contract.
                "pool_asset_b_id",
            },
        }[self.kind]
        missing = required.difference(names)
        if missing:
            # Fail the projection spec post init path with ValueError for projection is
            # missing semantic columns: and sorted when missing is true; do not continue
            # ambiguously.
            raise ValueError(f"projection is missing semantic columns: {sorted(missing)}")
        if self.kind is not ProjectionKind.BLOCK and self.ordering_fidelity not in {
            OrderingFidelity.TRANSACTION_EXACT,
            OrderingFidelity.INSTRUCTION_EXACT,
        }:
            # Fail the projection spec post init path with ValueError for reference row
            # projector requires exact within-group ordering when kind, block and ordering
            # fidelity is true; do not continue ambiguously.
            raise ValueError("reference row projector requires exact within-group ordering")

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self.columns)

    def identity_document(self) -> dict[str, object]:
        # Execute the projection spec identity document workflow in explicit, reviewable
        # steps.
        return {
            "capability_id": self.capability_id.value,
            "columns": [[logical, source] for logical, source in self.columns],
            "identity_fidelity": self.identity_fidelity.value,
            "kind": self.kind.value,
            # Include ordering fidelity in the completed projection spec identity document
            # result.
            "ordering_fidelity": self.ordering_fidelity.value,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "source_total_key": list(self.source_total_key),
            "source_total_key_is_proven": self.source_total_key_is_proven,
            # Return the completed projection spec identity document result without a hidden
            # fallback.
        }


class ReferenceProtocolProjector:
    """Deterministic semantic decoder for explicitly proven logical columns."""

    def __init__(
        self,
        specs: tuple[ProjectionSpec, ...],
        *,
        build_tools: PinnedCodeBundleSet | None = None,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the reference protocol projector init workflow in explicit, reviewable
        # steps.
        ordered = tuple(sorted(specs, key=lambda item: item.capability_id.value))
        if not ordered:
            raise ValueError("at least one projection spec is required")
        if len({item.capability_id for item in ordered}) != len(ordered):
            raise ValueError("projection specs must have unique capability IDs")
        # Assemble self specs once so the reference protocol projector init workflow
        # shares one value.
        self._specs = {item.capability_id: item for item in ordered}
        self._build_tools = build_tools or _unit_projector_tools()
        code_bundle_id = self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)
        self._config_digest = domain_digest(
            "backtest.reference-protocol-projector-config.v1",
            # Keep the identity document and item identity_document step visible while
            # building self. config digest.
            [item.identity_document() for item in ordered],
        )
        self._bundle_id = BundleId(
            domain_digest(
                "backtest.reference-protocol-projector.v3",
                # Open the v3 and code bundle id payload explicitly for domain_digest
                # within reference protocol projector init.
                {
                    "code_bundle_id": code_bundle_id.hex,
                    "projection_config_digest": self._config_digest.hex,
                },
            ).hex
            # Complete BundleId only after its v3 and code bundle id inputs are visible in
            # reference protocol projector init.
        )

    @property
    def bundle_id(self) -> BundleId:
        # Execute the reference protocol projector bundle id workflow in explicit,
        # reviewable steps.
        self._require_current()
        return self._bundle_id

    @property
    def config_digest(self) -> ContentDigest:
        return self._config_digest

    # Define reference protocol projector supports as one focused operation with an
    # explicit boundary.
    def supports(self, capability_id: CapabilityId) -> bool:
        return capability_id in self._specs

    def event_kind(self, capability_id: CapabilityId) -> EventKind:
        # Execute the reference protocol projector event kind workflow in explicit,
        # reviewable steps.
        spec = self._spec(capability_id)
        return EventKind[spec.kind.name]

    def project(self, batch: IndexedBatch) -> tuple[CanonicalEvent, ...]:
        # Execute the reference protocol projector project workflow in explicit,
        # reviewable steps.
        self._require_current()
        spec = self._spec(batch.capability_id)
        indexes = {name: index for index, name in enumerate(batch.columns)}
        missing = set(spec.mapping.values()).difference(indexes)
        missing.update(set(spec.source_total_key).difference(indexes))
        # Guard this path with missing before applying effects.
        if missing:
            raise ValueError(f"source batch misses projector columns: {sorted(missing)}")
        projected = tuple(self._project_row(spec, row, indexes) for row in batch.rows)
        if len({event.envelope.source_record_id for event in projected}) != len(projected):
            raise ValueError("projector encountered indistinguishable source occurrences")
        # Return the completed reference protocol projector project result without a
        # hidden fallback.
        return projected

    def validate_snapshot_candidate(
        self,
        spec: DatasetSpec,
        candidate: CanonicalSnapshotCandidate,
        # Close the validate snapshot candidate signature after its explicit inputs.
    ) -> None:
        # Execute the reference protocol projector validate snapshot candidate workflow in
        # explicit, reviewable steps.
        del candidate
        if spec.settlement_requirement is not None:
            raise SnapshotValidationError(SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID)

    def _require_current(self) -> None:
        self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)

    # Define reference protocol projector project row as one focused operation with an
    # explicit boundary.
    def _project_row(
        self,
        spec: ProjectionSpec,
        row: tuple[Any, ...],
        indexes: dict[str, int],
        # Keep the canonical event input explicit in the project row contract.
    ) -> CanonicalEvent:
        # Execute the reference protocol projector project row workflow in explicit,
        # reviewable steps.
        mapping = spec.mapping

        def value(name: str, default: object = None) -> object:
            # Execute the reference protocol projector value workflow in explicit,
            # reviewable steps.
            source_name = mapping.get(name)
            return default if source_name is None else row[indexes[source_name]]

        block_ordinal = _integer(value("slot"), "slot", minimum=0)
        if spec.kind is ProjectionKind.BLOCK:
            # Handle the reference protocol projector project row spec.kind is
            # ProjectionKind.BLOCK branch as a distinct logical block.
            position = ChainPosition(
                network_id=SOLANA_MAINNET_NETWORK_ID,
                position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
                block_ordinal=block_ordinal,
                transaction_index=-1,
                # Pass event index explicitly so ChainPosition receives a reviewable
                # solana mainnet network id and block32 transaction32 position schema id
                # input in reference protocol projector project row.
                event_index=0,
            )
            source_occurrence = _source_occurrence(
                spec,
                row,
                # Pass indexes explicitly so _source_occurrence receives a reviewable slot
                # and spec input in reference protocol projector project row.
                indexes,
                candidate_position={"slot": block_ordinal},
            )
            envelope = _envelope(spec, position, source_occurrence, transaction=None)
            return BlockEvent(
                # Pass envelope explicitly so BlockEvent receives a reviewable block time
                # and tx count input in reference protocol projector project row.
                envelope=envelope,
                block_time_ns=_time_ns(value("block_time", None)),
                tx_count=_optional_integer(value("tx_count", None), "tx_count", minimum=0),
                block_hash=_optional_string(value("block_hash", None), "block_hash"),
            )

        # Assemble transaction index once so the reference protocol projector project row
        # workflow shares one value.
        transaction_index = _integer(value("transaction_index"), "transaction_index", minimum=0)
        event_index = _integer(value("event_index"), "event_index", minimum=0)
        signature = _string(value("signature"), "signature")
        position = ChainPosition(
            network_id=SOLANA_MAINNET_NETWORK_ID,
            # Pass position schema id explicitly so ChainPosition receives a reviewable
            # solana mainnet network id and block32 transaction32 position schema id input
            # in reference protocol projector project row.
            position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
            block_ordinal=block_ordinal,
            transaction_index=transaction_index,
            event_index=event_index,
        )
        # Assemble source occurrence once so the reference protocol projector project row
        # workflow shares one value.
        source_occurrence = _source_occurrence(
            spec,
            row,
            indexes,
            candidate_position={
                # Keep event index named so the event index and signature payload passed
                # to _source_occurrence remains self-describing within reference protocol
                # projector project row.
                "event_index": event_index,
                "signature": signature,
                "slot": block_ordinal,
                "transaction_index": transaction_index,
            },
            # Complete _source_occurrence only after its event index and signature inputs are
            # visible in reference protocol projector project row.
        )

        if spec.kind is ProjectionKind.TOKEN_CREATION:
            # Handle the reference protocol projector project row kind, token creation and
            # spec condition as a distinct block.
            asset_id = _string(value("asset_id"), "asset_id")
            creator_id = _string(value("creator_id"), "creator_id")
            decimals = _optional_integer(value("decimals", None), "decimals", minimum=0)
            envelope = _envelope(spec, position, source_occurrence, transaction=signature)
            return TokenCreationEvent(
                # Pass envelope explicitly so TokenCreationEvent receives a reviewable
                # launch: and asset id input in reference protocol projector project row.
                envelope=envelope,
                asset_id=AssetId(asset_id),
                developer_id=AccountId(creator_id),
                creation_user_id=AccountId(creator_id),
                venue_id=VenueId(f"launch:{asset_id}"),
                # Pass quote asset id explicitly so TokenCreationEvent receives a
                # reviewable launch: and asset id input in reference protocol projector
                # project row.
                quote_asset_id=_REFERENCE_QUOTE_ASSET_ID,
                protocol_payload_schema=_REFERENCE_LAUNCH_PAYLOAD_SCHEMA_ID,
                protocol_payload=b"",
                decimals=decimals,
            )

        # Assemble bought amount once so the reference protocol projector project row
        # workflow shares one value.
        bought_amount = _integer(value("bought_amount_atomic"), "bought_amount_atomic", minimum=1)
        bought_asset = _string(value("bought_asset_id"), "bought_asset_id")
        fee_amount = _integer(value("fee_amount_atomic"), "fee_amount_atomic", minimum=0)
        pool_asset_a = _string(value("pool_asset_a_id"), "pool_asset_a_id")
        pool_asset_b = _string(value("pool_asset_b_id"), "pool_asset_b_id")
        # Assemble pool id once so the reference protocol projector project row workflow
        # shares one value.
        pool_id = _string(value("pool_id"), "pool_id")
        reserve_a = _optional_integer(
            value("reserve_a_after_atomic", None), "reserve_a_after_atomic", minimum=0
        )
        reserve_b = _optional_integer(
            # Keep the reserve b after atomic value step visible while building reserve b.
            value("reserve_b_after_atomic", None),
            "reserve_b_after_atomic",
            minimum=0,
        )
        sold_amount = _integer(value("sold_amount_atomic"), "sold_amount_atomic", minimum=1)
        # Assemble sold asset once so the reference protocol projector project row
        # workflow shares one value.
        sold_asset = _string(value("sold_asset_id"), "sold_asset_id")
        envelope = _envelope(spec, position, source_occurrence, transaction=signature)
        # Return the completed reference protocol projector project row result without a
        # hidden fallback.
        return SwapEvent(
            envelope=envelope,
            venue_id=VenueId(pool_id),
            sold_asset_id=AssetId(sold_asset),
            bought_asset_id=AssetId(bought_asset),
            # Pass sold amount atomic explicitly so SwapEvent receives a reviewable
            # protocol and venue id input in reference protocol projector project row.
            sold_amount_atomic=sold_amount,
            bought_amount_atomic=bought_amount,
            fee_components=(
                ()
                if fee_amount == 0
                # Route all remaining cases through the explicit alternative branch.
                else (
                    FeeComponent(
                        FeeComponentId("protocol"),
                        AssetId(sold_asset),
                        fee_amount,
                        # Complete FeeComponent only after its protocol and fee component id
                        # inputs are visible in reference protocol projector project row.
                    ),
                )
            ),
            protocol_payload_schema=REFERENCE_AMM_TRADE_PAYLOAD_SCHEMA_ID,
            protocol_payload=reference_amm_trade_payload(
                # Include asset a id in the completed reference protocol projector project
                # row result.
                asset_a_id=AssetId(pool_asset_a),
                asset_b_id=AssetId(pool_asset_b),
                reserve_a_after_atomic=reserve_a,
                reserve_b_after_atomic=reserve_b,
            ),
            # Complete SwapEvent only after its protocol and venue id inputs are visible in
            # reference protocol projector project row.
        )

    def _spec(self, capability_id: CapabilityId) -> ProjectionSpec:
        # Execute the reference protocol projector spec workflow in explicit, reviewable
        # steps.
        try:
            return self._specs[capability_id]
        except KeyError:
            raise ValueError(f"no projector for capability {capability_id}") from None


def _envelope(
    # Keep the spec input explicit in the envelope contract.
    spec: ProjectionSpec,
    position: ChainPosition,
    source_occurrence: Mapping[str, object],
    *,
    transaction: str | None,
    # Keep the event envelope input explicit in the envelope contract.
) -> EventEnvelope:
    # Execute the envelope workflow in explicit, reviewable steps.
    group_material = (
        {
            "block_ordinal": position.block_ordinal,
            "network_id": position.network_id.value,
            "position_schema_id": position.position_schema_id.value,
            # Complete the group material group only after its semantic components are
            # visible.
        }
        if position.transaction_index == -1
        else {
            "block_ordinal": position.block_ordinal,
            "network_id": position.network_id.value,
            # Keep the position schema id component named inside the group material
            # contract.
            "position_schema_id": position.position_schema_id.value,
            "transaction_index": position.transaction_index,
            "transaction": transaction,
        }
    )
    # Assemble group id once so the envelope workflow shares one value.
    group_id = domain_digest("backtest.transaction-group.v3", group_material)
    source_record_id = domain_digest(
        "backtest.source-record-occurrence.v3",
        {
            "capability_id": spec.capability_id.value,
            # Keep identity fidelity named so the v3 and capability id payload passed to
            # domain_digest remains self-describing within envelope.
            "identity_fidelity": spec.identity_fidelity.value,
            "network_id": position.network_id.value,
            "occurrence": source_occurrence,
            "position_schema_id": position.position_schema_id.value,
        },
        # Complete domain_digest only after its v3 and capability id inputs are visible in
        # envelope.
    )
    canonical_event_id = domain_digest(
        "backtest.canonical-event.v3",
        {
            "group_id": group_id.hex,
            # Keep kind named so the v3 and group id payload passed to domain_digest
            # remains self-describing within envelope.
            "kind": EventKind[spec.kind.name].name,
            "network_id": position.network_id.value,
            "position_schema_id": position.position_schema_id.value,
            "protocol": spec.protocol,
            "protocol_version": spec.protocol_version,
            # Keep source record id named so the v3 and group id payload passed to
            # domain_digest remains self-describing within envelope.
            "source_record_id": source_record_id.hex,
        },
    )
    stable_causal_id = domain_digest(
        "backtest.stable-causal-id.v2",
        # Open the v2 and canonical event id payload explicitly for domain_digest within
        # envelope.
        {
            "canonical_event_id": canonical_event_id.hex,
            "source_record_id": source_record_id.hex,
        },
    )
    # Return the completed envelope result without a hidden fallback.
    return EventEnvelope(
        position=position,
        transaction_group_id=ContentDigest(group_id.hex),
        source_record_id=source_record_id,
        canonical_event_id=canonical_event_id,
        # Pass stable causal id explicitly so EventEnvelope receives a reviewable hex and
        # capability id input in envelope.
        stable_causal_id=stable_causal_id,
        capability_id=spec.capability_id,
        protocol=spec.protocol,
        protocol_version=spec.protocol_version,
        ordering_fidelity=spec.ordering_fidelity,
        # Complete EventEnvelope only after its hex and capability id inputs are visible in
        # envelope.
    )


def _source_occurrence(
    spec: ProjectionSpec,
    row: tuple[Any, ...],
    indexes: Mapping[str, int],
    # Close the source occurrence signature after its explicit inputs.
    *,
    candidate_position: Mapping[str, object],
) -> dict[str, object]:
    """Return an occurrence key without upgrading advertised identity fidelity.

    A proven total key identifies a stable source-row occurrence independently
    of source batch order.  Without that proof we retain only a candidate chain
    position.  Duplicate candidate keys are rejected by projector/canonical QA;
    an arbitrary local ordinal is never invented to distinguish them.
    """

    if spec.source_total_key_is_proven:
        # Handle the source occurrence spec.source_total_key_is_proven branch as a
        # distinct logical block.
        return {
            "basis": "PROVEN_SOURCE_TOTAL_KEY",
            "values": [
                [column, _identity_value(row[indexes[column]], field=column)]
                for column in spec.source_total_key
                # Return the completed source occurrence result without a hidden fallback.
            ],
        }
    return {
        "basis": "CANDIDATE_CHAIN_POSITION",
        "values": dict(candidate_position),
        # Return the completed source occurrence result without a hidden fallback.
    }


def _identity_value(value: object, *, field: str) -> object:
    """Normalize the deliberately small scalar vocabulary allowed in keys."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, datetime):
        # Handle the identity value isinstance(value, datetime) branch as a distinct
        # logical block.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"source total-key column {field!r} has a naive datetime")
        return {"type": "datetime", "value": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    # Fail the identity value path with ValueError for source total-key column and has
    # unsupported type; do not continue ambiguously.
    raise ValueError(
        f"source total-key column {field!r} has unsupported type {type(value).__name__}"
    )


def _integer(value: object, field: str, *, minimum: int) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _optional_integer(value: object, field: str, *, minimum: int) -> int | None:
    return None if value is None else _integer(value, field, minimum=minimum)


# Define string as one focused operation with an explicit boundary.
def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


# Define time ns as one focused operation with an explicit boundary.
def _time_ns(value: object) -> int | None:
    # Execute the time ns workflow in explicit, reviewable steps.
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("block_time must not be boolean")
    if isinstance(value, int):
        # Return the completed time ns result without a hidden fallback.
        return value
    if isinstance(value, datetime):
        # Handle the time ns isinstance(value, datetime) branch as a distinct logical
        # block.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("block_time datetime must be timezone-aware")
        utc = value.astimezone(UTC)
        return int(utc.timestamp()) * 1_000_000_000 + utc.microsecond * 1_000
    raise ValueError("block_time must be an integer nanosecond timestamp or aware datetime")


# Bind all once as an explicit module-level contract.
__all__ = ["ProjectionKind", "ProjectionSpec", "ReferenceProtocolProjector"]
