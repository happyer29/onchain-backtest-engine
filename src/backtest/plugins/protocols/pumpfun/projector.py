"""Exact row projector for the versioned Pump.fun source contract.

The projector owns Pump payload construction.  Canonical core sees only the
generic launch/trade/lifecycle events and immutable canonical payload bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

# Import typing at the visible module dependency boundary.
from typing import Any

from backtest.application.build_tool_roles import CANONICAL_PROJECTOR_ROLE
from backtest.application.code_bundles import PinnedCodeBundleIdentity, PinnedCodeBundleSet
from backtest.application.errors import SnapshotValidationError, SnapshotValidationErrorCode
from backtest.application.models import CapabilityStream, DatasetSpec, SettlementRequirement

# Import canonical at the visible module dependency boundary.
from backtest.application.ports.canonical import CanonicalSnapshotCandidate
from backtest.application.ports.source import IndexedBatch
from backtest.application.source_contracts import require_pumpfun_sniping_source_contract
from backtest.domain.chain import ChainIdentityMismatchError, ChainPosition
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
    NetworkId,
    PositionSchemaId,
    # Include protocol payload schema id so the identifiers dependency remains explicit.
    ProtocolPayloadSchemaId,
    VenueId,
)
from backtest.domain.market_events import (
    BlockEvent,
    # Include canonical event so the market events dependency remains explicit.
    CanonicalEvent,
    EventEnvelope,
    EventKind,
    EventKindName,
    FeeComponent,
    # Include token launch event so the market events dependency remains explicit.
    TokenLaunchEvent,
    VenueLifecycleEvent,
    VenueLifecycleKind,
    VenueTradeEvent,
    canonical_event_sort_key,
    # Close the market events import after its required symbols are visible.
)
from backtest.engine.sniping_contracts import ProtocolContractError
from backtest.engine.transaction_clock import (
    CompactTransactionClock,
    TransactionClockError,
    # Include transaction clock error code so the transaction clock dependency remains
    # explicit.
    TransactionClockErrorCode,
)
from backtest.plugins.protocols.pumpfun.model import (
    PumpCurveLifecycle,
    PumpCurveStateV1,
    # Include pump fee profile so the model dependency remains explicit.
    PumpFeeProfile,
    PumpMode,
)
from backtest.plugins.protocols.pumpfun.sniping import (
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    # Include pumpfun lifecycle payload schema id so the sniping dependency remains
    # explicit.
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
    PUMPFUN_PROTOCOL_NAME,
    PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    PumpfunSnipingProtocolRuntime,
    encode_launch_payload,
    # Include encode lifecycle payload so the sniping dependency remains explicit.
    encode_lifecycle_payload,
    encode_trade_payload,
)

_UNIT_PROJECTOR_CODE_BUNDLE_ID = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v2 and
        # authority input in module.
        "backtest.pumpfun-projector-unit-code.v2",
        {"authority": "isolated-unit-default-only"},
    ).hex
)

_STATE_COLUMNS = {
    # Keep the lifecycle component named inside the state columns contract.
    "lifecycle",
    "mode",
    "real_sol_reserves_lamports",
    "real_token_reserves_atomic",
    "token_total_supply_atomic",
    # Keep the virtual sol reserves lamports component named inside the state columns
    # contract.
    "virtual_sol_reserves_lamports",
    "virtual_token_reserves_atomic",
}

_REQUIRED_COLUMNS = {
    EventKindName.BLOCK: {
        # Keep the block hash component named inside the required columns contract.
        "block_hash",
        "block_ordinal",
        "block_time",
        "transaction_count",
    },
    # Keep the event kind name component named inside the required columns contract.
    EventKindName.TOKEN_LAUNCH: {
        "asset",
        "block_ordinal",
        "creation_user",
        "developer",
        # Keep the event index component named inside the required columns contract.
        "event_index",
        "quote_asset",
        "signature",
        "transaction_succeeded",
        "transaction_index",
        # Keep the venue component named inside the required columns contract.
        "venue",
        *_STATE_COLUMNS,
    },
    EventKindName.VENUE_TRADE: {
        "asset",
        # Keep the base amount atomic component named inside the required columns
        # contract.
        "base_amount_atomic",
        "block_ordinal",
        "creator_fee_atomic",
        "event_index",
        "protocol_fee_atomic",
        # Keep the quote amount atomic component named inside the required columns
        # contract.
        "quote_amount_atomic",
        "quote_asset",
        "side",
        "signature",
        "transaction_index",
        # Keep the venue component named inside the required columns contract.
        "venue",
        *_STATE_COLUMNS,
    },
    EventKindName.VENUE_LIFECYCLE: {
        "block_ordinal",
        # Keep the event index component named inside the required columns contract.
        "event_index",
        "lifecycle_kind",
        "signature",
        "transaction_index",
        "venue",
        # Keep the state columns component named inside the required columns contract.
        *_STATE_COLUMNS,
    },
}


class PumpfunProjectionErrorCode(StrEnum):
    """Stable reasons why a source row cannot become an exact Pump event."""

    LAUNCH_TRANSACTION_STATUS_INVALID = "LAUNCH_TRANSACTION_STATUS_INVALID"
    LAUNCH_TRANSACTION_FAILED = "LAUNCH_TRANSACTION_FAILED"


class PumpfunProjectionError(ValueError):
    """A source launch row violates the exact successful-launch invariant."""

    def __init__(self, code: PumpfunProjectionErrorCode) -> None:
        # Execute the pumpfun projection error init workflow in explicit, reviewable
        # steps.
        if not isinstance(code, PumpfunProjectionErrorCode):
            raise TypeError("code must be a PumpfunProjectionErrorCode")
        self.code = code
        super().__init__(code.value)


_PAYLOAD_SCHEMA_BY_KIND = {
    # Keep the event kind name component named inside the payload schema by kind contract.
    EventKindName.TOKEN_LAUNCH: PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    EventKindName.VENUE_TRADE: PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
    EventKindName.VENUE_LIFECYCLE: PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
}


# Keep the pumpfun projection spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PumpfunProjectionSpec:
    capability_id: CapabilityId
    kind: EventKindName
    protocol: str
    # Declare protocol version explicitly in the pumpfun projection spec contract.
    protocol_version: str
    identity_fidelity: IdentityFidelity
    ordering_fidelity: OrderingFidelity
    source_total_key: tuple[str, ...]
    source_total_key_is_proven: bool
    # Declare protocol payload schema id explicitly in the pumpfun projection spec
    # contract.
    protocol_payload_schema_id: ProtocolPayloadSchemaId | None
    columns: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        # Execute the pumpfun projection spec post init workflow in explicit, reviewable
        # steps.
        if self.kind not in _REQUIRED_COLUMNS:
            raise ValueError("unsupported Pump projection event kind")
        if not self.protocol or self.protocol != self.protocol.strip():
            raise ValueError("projection protocol must be non-empty and trimmed")
        if not self.protocol_version or self.protocol_version != self.protocol_version.strip():
            # Fail the pumpfun projection spec post init path with ValueError for
            # projection protocol version must be non-empty and trimmed when protocol
            # version and strip is true; do not continue ambiguously.
            raise ValueError("projection protocol_version must be non-empty and trimmed")
        if self.kind is EventKindName.BLOCK:
            # Handle the pumpfun projection spec post init self.kind is
            # EventKindName.BLOCK branch as a distinct logical block.
            if self.protocol != "solana" or self.protocol_payload_schema_id is not None:
                raise ValueError("Pump block clock must use the Solana protocol without payload")
        else:
            # Handle the pumpfun projection spec post init complement of self.kind is
            # EventKindName.BLOCK explicitly.
            if self.protocol != PUMPFUN_PROTOCOL_NAME:
                raise ValueError("Pump events must use the pumpfun protocol family")
            if self.protocol_payload_schema_id != _PAYLOAD_SCHEMA_BY_KIND[self.kind]:
                raise ValueError("Pump payload schema does not match event kind")
            if self.ordering_fidelity is not OrderingFidelity.INSTRUCTION_EXACT:
                # Fail the pumpfun projection spec post init path with ValueError for pump
                # event projection requires instruction-exact ordering when ordering
                # fidelity and instruction exact is true; do not continue ambiguously.
                raise ValueError("Pump event projection requires instruction-exact ordering")
        names = tuple(name for name, _ in self.columns)
        sources = tuple(name for _, name in self.columns)
        if len(set(names)) != len(names) or len(set(sources)) != len(sources):
            raise ValueError("projection column aliases and sources must be unique")
        # Assemble missing once so the pumpfun projection spec post init workflow shares
        # one value.
        missing = _REQUIRED_COLUMNS[self.kind].difference(names)
        if missing:
            raise ValueError(f"Pump projection misses semantic columns: {sorted(missing)}")
        if self.source_total_key_is_proven and not self.source_total_key:
            raise ValueError("proven source total key must not be empty")
        # Evaluate the complete pumpfun projection spec post init source total key and
        # source total key is proven condition before guarded effects.
        if self.source_total_key and not self.source_total_key_is_proven:
            raise ValueError("an unproven source total key cannot identify occurrences")
        if self.identity_fidelity is IdentityFidelity.EXACT and not self.source_total_key_is_proven:
            raise ValueError("exact source identity requires a proven total key")

    @property
    # Define pumpfun projection spec mapping as one focused operation with an explicit
    # boundary.
    def mapping(self) -> dict[str, str]:
        return dict(self.columns)

    def identity_document(self) -> dict[str, object]:
        # Execute the pumpfun projection spec identity document workflow in explicit,
        # reviewable steps.
        return {
            "capability_id": self.capability_id.value,
            "columns": [[semantic, logical] for semantic, logical in self.columns],
            "identity_fidelity": self.identity_fidelity.value,
            "kind": self.kind.value,
            # Include ordering fidelity in the completed pumpfun projection spec identity
            # document result.
            "ordering_fidelity": self.ordering_fidelity.value,
            "protocol": self.protocol,
            "protocol_payload_schema_id": (
                None
                if self.protocol_payload_schema_id is None
                # Route all remaining cases through the explicit alternative branch.
                else self.protocol_payload_schema_id.value
            ),
            "protocol_version": self.protocol_version,
            "source_total_key": list(self.source_total_key),
            "source_total_key_is_proven": self.source_total_key_is_proven,
            # Return the completed pumpfun projection spec identity document result without a
            # hidden fallback.
        }


class PumpfunProtocolProjector:
    """Project the exact four-stream Solana/Pump contract to generic events."""

    def __init__(
        self,
        *,
        network_id: NetworkId,
        position_schema_id: PositionSchemaId,
        # Keep the specs input explicit in the init contract.
        specs: tuple[PumpfunProjectionSpec, ...],
        source_normalizer_digest: ContentDigest | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the pumpfun protocol projector init workflow in explicit, reviewable
        # steps.
        ordered = tuple(sorted(specs, key=lambda item: item.capability_id.value))
        if not ordered or len({item.capability_id for item in ordered}) != len(ordered):
            raise ValueError("Pump projection specs must be non-empty and capability-unique")
        if {item.kind for item in ordered} != set(_REQUIRED_COLUMNS):
            raise ValueError("Pump projector requires exactly one declaration for every stream")
        # Assemble self network id once so the pumpfun protocol projector init workflow
        # shares one value.
        self._network_id = network_id
        self._position_schema_id = position_schema_id
        self._specs = {item.capability_id: item for item in ordered}
        self._build_tools = build_tools or _unit_projector_tools()
        code_bundle_id = self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)
        # Assemble self config digest once so the pumpfun protocol projector init workflow
        # shares one value.
        self._config_digest = domain_digest(
            "backtest.pumpfun-protocol-projector-config.v2",
            {
                "network_id": network_id.value,
                "position_schema_id": position_schema_id.value,
                "source_normalizer_digest": (
                    None if source_normalizer_digest is None else source_normalizer_digest.hex
                ),
                # Keep the identity document and item identity_document step visible while
                # building self. config digest.
                "specs": [item.identity_document() for item in ordered],
            },
        )
        self._bundle_id = BundleId(
            domain_digest(
                # Pass version tag explicitly so domain_digest receives a reviewable v2
                # and code bundle id input in pumpfun protocol projector init.
                "backtest.pumpfun-protocol-projector.v2",
                {
                    "code_bundle_id": code_bundle_id.hex,
                    "projection_config_digest": self._config_digest.hex,
                },
                # Complete domain_digest only after its v1 and code bundle id inputs are
                # visible in pumpfun protocol projector init.
            ).hex
        )

    @property
    def bundle_id(self) -> BundleId:
        # Execute the pumpfun protocol projector bundle id workflow in explicit,
        # reviewable steps.
        self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)
        return self._bundle_id

    @property
    def config_digest(self) -> ContentDigest:
        return self._config_digest

    # Define pumpfun protocol projector supports as one focused operation with an explicit
    # boundary.
    def supports(self, capability_id: CapabilityId) -> bool:
        return capability_id in self._specs

    def event_kind(self, capability_id: CapabilityId) -> EventKind:
        return EventKind[self._spec(capability_id).kind.name]

    def project(self, batch: IndexedBatch) -> tuple[CanonicalEvent, ...]:
        # Execute the pumpfun protocol projector project workflow in explicit, reviewable
        # steps.
        self._build_tools.require_current(CANONICAL_PROJECTOR_ROLE)
        spec = self._spec(batch.capability_id)
        indexes = {name: index for index, name in enumerate(batch.columns)}
        missing = set(spec.mapping.values()).difference(indexes)
        missing.update(set(spec.source_total_key).difference(indexes))
        # Guard this path with missing before applying effects.
        if missing:
            raise ValueError(f"source batch misses Pump projector columns: {sorted(missing)}")
        projected = tuple(self._project_row(spec, row, indexes) for row in batch.rows)
        if len({event.envelope.source_record_id for event in projected}) != len(projected):
            raise ValueError("Pump projector encountered indistinguishable source occurrences")
        # Return the completed pumpfun protocol projector project result without a hidden
        # fallback.
        return projected

    def validate_snapshot_candidate(
        self,
        spec: DatasetSpec,
        candidate: CanonicalSnapshotCandidate,
        # Close the validate snapshot candidate signature after its explicit inputs.
    ) -> None:
        PumpfunSnapshotValidator().validate_snapshot_candidate(spec, candidate)

    def _project_row(
        self,
        spec: PumpfunProjectionSpec,
        # Keep the row input explicit in the project row contract.
        row: tuple[Any, ...],
        indexes: Mapping[str, int],
    ) -> CanonicalEvent:
        # Execute the pumpfun protocol projector project row workflow in explicit,
        # reviewable steps.
        mapping = spec.mapping

        def value(name: str, default: object = None) -> object:
            # Execute the pumpfun protocol projector value workflow in explicit,
            # reviewable steps.
            source_name = mapping.get(name)
            return default if source_name is None else row[indexes[source_name]]

        block_ordinal = _integer(value("block_ordinal"), "block_ordinal", minimum=0)
        if spec.kind is EventKindName.BLOCK:
            # Handle the pumpfun protocol projector project row spec.kind is
            # EventKindName.BLOCK branch as a distinct logical block.
            position = ChainPosition(
                self._network_id,
                self._position_schema_id,
                block_ordinal,
                -1,
                # Keep chain position, network id and position schema id visible while
                # completing ChainPosition within pumpfun protocol projector project row.
                0,
            )
            envelope = self._envelope(
                spec,
                position,
                # Keep the spec _source_occurrence step visible while building envelope.
                _source_occurrence(
                    spec,
                    row,
                    indexes,
                    candidate_position={"block_ordinal": block_ordinal},
                    # Complete _source_occurrence only after its block ordinal and spec inputs
                    # are visible in pumpfun protocol projector project row.
                ),
                transaction=None,
            )
            return BlockEvent(
                envelope,
                # Include time ns in the completed pumpfun protocol projector project row
                # result.
                _time_ns(value("block_time")),
                _integer(value("transaction_count"), "transaction_count", minimum=0),
                _string(value("block_hash"), "block_hash"),
            )

        transaction_index = _integer(value("transaction_index"), "transaction_index", minimum=0)
        # Assemble event index once so the pumpfun protocol projector project row workflow
        # shares one value.
        event_index = _integer(value("event_index"), "event_index", minimum=0)
        signature = _string(value("signature"), "signature")
        position = ChainPosition(
            self._network_id,
            self._position_schema_id,
            # Pass block ordinal explicitly so ChainPosition receives a reviewable network
            # id and position schema id input in pumpfun protocol projector project row.
            block_ordinal,
            transaction_index,
            event_index,
        )
        occurrence = _source_occurrence(
            # Pass spec explicitly so _source_occurrence receives a reviewable block
            # ordinal and event index input in pumpfun protocol projector project row.
            spec,
            row,
            indexes,
            candidate_position={
                "block_ordinal": block_ordinal,
                # Keep event index named so the block ordinal and event index payload
                # passed to _source_occurrence remains self-describing within pumpfun
                # protocol projector project row.
                "event_index": event_index,
                "signature": signature,
                "transaction_index": transaction_index,
            },
        )
        # Assemble envelope once so the pumpfun protocol projector project row workflow
        # shares one value.
        envelope = self._envelope(spec, position, occurrence, transaction=signature)
        if spec.kind is EventKindName.TOKEN_LAUNCH:
            _require_successful_launch_transaction(value("transaction_succeeded"))
        state = _curve_state(value)

        if spec.kind is EventKindName.TOKEN_LAUNCH:
            # Handle the pumpfun protocol projector project row kind, token launch and
            # spec condition as a distinct block.
            if state.lifecycle is not PumpCurveLifecycle.ACTIVE:
                raise ValueError("a Pump launch must expose active creation-time state")
            return TokenLaunchEvent(
                envelope=envelope,
                asset_id=AssetId(_string(value("asset"), "asset")),
                # Include developer id in the completed pumpfun protocol projector project
                # row result.
                developer_id=AccountId(_string(value("developer"), "developer")),
                creation_user_id=AccountId(_string(value("creation_user"), "creation_user")),
                venue_id=VenueId(_string(value("venue"), "venue")),
                quote_asset_id=AssetId(_string(value("quote_asset"), "quote_asset")),
                protocol_payload_schema=PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
                # Include protocol payload in the completed pumpfun protocol projector
                # project row result.
                protocol_payload=encode_launch_payload(state),
            )

        if spec.kind is EventKindName.VENUE_TRADE:
            # Handle the pumpfun protocol projector project row spec.kind is
            # EventKindName.VENUE_TRADE branch as a distinct logical block.
            asset = AssetId(_string(value("asset"), "asset"))
            quote_asset = AssetId(_string(value("quote_asset"), "quote_asset"))
            side = _string(value("side"), "side")
            base_amount = _integer(value("base_amount_atomic"), "base_amount_atomic", minimum=1)
            quote_amount = _integer(value("quote_amount_atomic"), "quote_amount_atomic", minimum=0)
            # Guard this path with side == 'BUY' before applying effects.
            if side == "BUY":
                # Handle the pumpfun protocol projector project row side == 'BUY' branch
                # as a distinct logical block.
                if quote_amount == 0:
                    raise ValueError("Pump buy quote amount must be positive")
                sold_asset, bought_asset = quote_asset, asset
                sold_amount, bought_amount = quote_amount, base_amount
            # Handle the pumpfun protocol projector project row complement of side ==
            # 'BUY' explicitly.
            elif side == "SELL":
                # Handle the pumpfun protocol projector project row side == 'SELL' branch
                # as a distinct logical block.
                sold_asset, bought_asset = asset, quote_asset
                sold_amount, bought_amount = base_amount, quote_amount
            else:
                raise ValueError("Pump trade side must be BUY or SELL")
            fees = tuple(
                # Keep the sorted and fee component sorted step visible while building
                # fees.
                sorted(
                    (
                        FeeComponent(FeeComponentId(component), quote_asset, amount)
                        for component, amount in (
                            (
                                # Pass creator explicitly so sorted receives a reviewable
                                # creator and protocol input in pumpfun protocol projector
                                # project row.
                                "creator",
                                _integer(
                                    value("creator_fee_atomic"),
                                    "creator_fee_atomic",
                                    minimum=0,
                                    # Complete _integer only after its creator fee atomic and
                                    # value inputs are visible in pumpfun protocol projector
                                    # project row.
                                ),
                            ),
                            (
                                "protocol",
                                _integer(
                                    # Keep the protocol fee atomic value step visible
                                    # while building fees.
                                    value("protocol_fee_atomic"),
                                    "protocol_fee_atomic",
                                    minimum=0,
                                ),
                            ),
                            # Complete sorted only after its creator and protocol inputs are
                            # visible in pumpfun protocol projector project row.
                        )
                        if amount
                    ),
                    key=lambda item: (item.component_id.value, item.asset_id.value),
                )
                # Complete tuple only after its creator and protocol inputs are visible in
                # pumpfun protocol projector project row.
            )
            return VenueTradeEvent(
                envelope=envelope,
                venue_id=VenueId(_string(value("venue"), "venue")),
                sold_asset_id=sold_asset,
                # Pass bought asset id explicitly so VenueTradeEvent receives a reviewable
                # venue and venue id input in pumpfun protocol projector project row.
                bought_asset_id=bought_asset,
                sold_amount_atomic=sold_amount,
                bought_amount_atomic=bought_amount,
                fee_components=fees,
                protocol_payload_schema=PUMPFUN_TRADE_PAYLOAD_SCHEMA_ID,
                # Include protocol payload in the completed pumpfun protocol projector
                # project row result.
                protocol_payload=encode_trade_payload(state),
            )

        lifecycle_kind = VenueLifecycleKind(_string(value("lifecycle_kind"), "lifecycle_kind"))
        expected = {
            VenueLifecycleKind.COMPLETED: PumpCurveLifecycle.COMPLETED,
            # Pass venue lifecycle kind explicitly so get receives a reviewable lifecycle
            # kind input in pumpfun protocol projector project row.
            VenueLifecycleKind.MIGRATED: PumpCurveLifecycle.MIGRATED,
        }.get(lifecycle_kind)
        if expected is None or state.lifecycle is not expected:
            raise ValueError("Pump lifecycle kind and after-state disagree")
        return VenueLifecycleEvent(
            # Pass envelope explicitly so VenueLifecycleEvent receives a reviewable venue
            # and venue id input in pumpfun protocol projector project row.
            envelope=envelope,
            venue_id=VenueId(_string(value("venue"), "venue")),
            lifecycle_kind=lifecycle_kind,
            protocol_payload_schema=PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
            protocol_payload=encode_lifecycle_payload(state),
            # Complete VenueLifecycleEvent only after its venue and venue id inputs are
            # visible in pumpfun protocol projector project row.
        )

    def _envelope(
        self,
        spec: PumpfunProjectionSpec,
        position: ChainPosition,
        # Keep the source occurrence input explicit in the envelope contract.
        source_occurrence: Mapping[str, object],
        *,
        transaction: str | None,
    ) -> EventEnvelope:
        # Execute the pumpfun protocol projector envelope workflow in explicit, reviewable
        # steps.
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
        # Assemble group id once so the pumpfun protocol projector envelope workflow
        # shares one value.
        group_id = domain_digest("backtest.transaction-group.v3", group_material)
        source_record_id = domain_digest(
            "backtest.source-record-occurrence.v3",
            {
                "capability_id": spec.capability_id.value,
                # Keep identity fidelity named so the v3 and capability id payload passed
                # to domain_digest remains self-describing within pumpfun protocol
                # projector envelope.
                "identity_fidelity": spec.identity_fidelity.value,
                "network_id": position.network_id.value,
                "occurrence": source_occurrence,
                "position_schema_id": position.position_schema_id.value,
            },
            # Complete domain_digest only after its v3 and capability id inputs are visible in
            # pumpfun protocol projector envelope.
        )
        kind = EventKind[spec.kind.name]
        canonical_event_id = domain_digest(
            "backtest.canonical-event.v3",
            {
                # Keep group id named so the v3 and group id payload passed to
                # domain_digest remains self-describing within pumpfun protocol projector
                # envelope.
                "group_id": group_id.hex,
                "kind": kind.name,
                "network_id": position.network_id.value,
                "position_schema_id": position.position_schema_id.value,
                "protocol": spec.protocol,
                # Keep protocol version named so the v3 and group id payload passed to
                # domain_digest remains self-describing within pumpfun protocol projector
                # envelope.
                "protocol_version": spec.protocol_version,
                "source_record_id": source_record_id.hex,
            },
        )
        stable_causal_id = domain_digest(
            # Pass version tag explicitly so domain_digest receives a reviewable v2 and
            # canonical event id input in pumpfun protocol projector envelope.
            "backtest.stable-causal-id.v2",
            {
                "canonical_event_id": canonical_event_id.hex,
                "source_record_id": source_record_id.hex,
            },
            # Complete domain_digest only after its v2 and canonical event id inputs are
            # visible in pumpfun protocol projector envelope.
        )
        return EventEnvelope(
            position=position,
            transaction_group_id=ContentDigest(group_id.hex),
            source_record_id=source_record_id,
            # Pass canonical event id explicitly so EventEnvelope receives a reviewable
            # hex and capability id input in pumpfun protocol projector envelope.
            canonical_event_id=canonical_event_id,
            stable_causal_id=stable_causal_id,
            capability_id=spec.capability_id,
            protocol=spec.protocol,
            protocol_version=spec.protocol_version,
            # Pass ordering fidelity explicitly so EventEnvelope receives a reviewable hex
            # and capability id input in pumpfun protocol projector envelope.
            ordering_fidelity=spec.ordering_fidelity,
        )

    def _spec(self, capability_id: CapabilityId) -> PumpfunProjectionSpec:
        # Execute the pumpfun protocol projector spec workflow in explicit, reviewable
        # steps.
        try:
            return self._specs[capability_id]
        except KeyError:
            raise ValueError(f"no Pump projector for capability {capability_id}") from None


class PumpfunSnapshotValidator:
    """Read-only pre-root proof of Pump stream structure and settlement coverage."""

    def validate_snapshot_candidate(
        self,
        spec: DatasetSpec,
        candidate: CanonicalSnapshotCandidate,
    ) -> None:
        # Execute the pumpfun snapshot validator validate snapshot candidate workflow in
        # explicit, reviewable steps.
        require_pumpfun_sniping_source_contract(spec)
        if (
            candidate.network_id != spec.network_id
            or candidate.position_schema_id != spec.position_schema_id
        ):
            # Fail the pumpfun snapshot validator validate snapshot candidate path with
            # SnapshotValidationError for event position invalid and snapshot validation
            # error code when network id, position schema id and candidate is true; do not
            # continue ambiguously.
            raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_POSITION_INVALID)
        requirement = spec.settlement_requirement
        if requirement is None:  # pragma: no cover - source contract proves it
            raise SnapshotValidationError(SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID)
        clock = candidate.transaction_clock()
        if (
            clock.network_id != spec.network_id
            or clock.position_schema_id != spec.position_schema_id
            # Evaluate the complete pumpfun snapshot validator validate snapshot candidate
            # network id, position schema id and clock condition before guarded effects.
        ):
            raise SnapshotValidationError(SnapshotValidationErrorCode.CLOCK_INVALID)

        capabilities = {item.capability_id: item for item in spec.capabilities}
        pump_versions = {
            item.protocol_version
            # Keep the item component named inside the pump versions contract.
            for item in spec.capabilities
            if item.stream is not CapabilityStream.BLOCK_CLOCK
        }
        if len(pump_versions) != 1:
            raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
        # Assemble runtime once so the pumpfun snapshot validator validate snapshot
        # candidate workflow shares one value.
        runtime = PumpfunSnipingProtocolRuntime(
            quote_asset_id=AssetId("SOL"),
            fee_profile=PumpFeeProfile.static_95_30(
                profile_id="snapshot-validation-only-v1",
                effective_from_unix_s=0,
                # Pass effective until unix s explicitly so static_95_30 receives a
                # reviewable snapshot-validation-only-v1 input in pumpfun snapshot
                # validator validate snapshot candidate.
                effective_until_unix_s=(1 << 64) - 1,
            ),
            protocol_version=next(iter(pump_versions)),
        )

        current: list[CanonicalEvent] = []
        # Assemble current identity once so the pumpfun snapshot validator validate
        # snapshot candidate workflow shares one value.
        current_identity: tuple[int, ContentDigest] | None = None
        previous_key: tuple[str, str, int, str, int, str] | None = None
        previous_event_index: int | None = None
        for event in candidate.events():
            # Process candidate.events() inside the bounded pumpfun snapshot validator
            # validate snapshot candidate loop.
            capability = capabilities.get(event.envelope.capability_id)
            if capability is None or _event_kind_for_stream(capability.stream) is not event.kind:
                raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
            if (
                event.envelope.protocol != capability.protocol
                # Keep event visible while evaluating the protocol, protocol version and
                # envelope guard.
                or event.envelope.protocol_version != capability.protocol_version
            ):
                raise SnapshotValidationError(SnapshotValidationErrorCode.EVENT_STREAM_INVALID)
            position = event.envelope.position
            if position.transaction_index >= 0:
                # Handle the pumpfun snapshot validator validate snapshot candidate
                # position.transaction_index >= 0 branch as a distinct logical block.
                try:
                    clock.require_position(position)
                except (ChainIdentityMismatchError, TransactionClockError) as error:
                    # Translate the chain identity mismatch error and transaction clock
                    # error failure through the pumpfun snapshot validator validate
                    # snapshot candidate boundary.
                    raise SnapshotValidationError(
                        SnapshotValidationErrorCode.EVENT_POSITION_INVALID
                    ) from error
            key = canonical_event_sort_key(event)
            if previous_key is not None and key <= previous_key:
                # Fail the pumpfun snapshot validator validate snapshot candidate path
                # with SnapshotValidationError for transaction group invalid and snapshot
                # validation error code when previous key and key is true; do not continue
                # ambiguously.
                raise SnapshotValidationError(SnapshotValidationErrorCode.TRANSACTION_GROUP_INVALID)
            previous_key = key
            identity = (
                event.envelope.boundary_ordinal,
                event.envelope.transaction_group_id,
                # Complete the identity group only after its semantic components are visible.
            )
            if current_identity is not None and identity != current_identity:
                # Handle the pumpfun snapshot validator validate snapshot candidate
                # current identity and identity condition as a distinct block.
                if identity[0] == current_identity[0]:
                    # Handle the pumpfun snapshot validator validate snapshot candidate
                    # identity[0] == current_identity[0] branch as a distinct logical
                    # block.
                    raise SnapshotValidationError(
                        SnapshotValidationErrorCode.TRANSACTION_GROUP_INVALID
                    )
                _apply_validation_group(runtime, clock, tuple(current))
                current.clear()
                # Assemble previous event index once so the pumpfun snapshot validator
                # validate snapshot candidate workflow shares one value.
                previous_event_index = None
            event_index = position.event_index
            if event_index is None or (
                previous_event_index is not None and event_index <= previous_event_index
            ):
                # Fail the pumpfun snapshot validator validate snapshot candidate path
                # with SnapshotValidationError for transaction group invalid and snapshot
                # validation error code when event index and previous event index is true;
                # do not continue ambiguously.
                raise SnapshotValidationError(SnapshotValidationErrorCode.TRANSACTION_GROUP_INVALID)
            previous_event_index = event_index
            current_identity = identity
            current.append(event)

            if isinstance(event, TokenLaunchEvent) and spec.decision_range.contains_position(
                # Pass position explicitly so contains_position receives a reviewable
                # position input in pumpfun snapshot validator validate snapshot
                # candidate.
                position
            ):
                _require_settlement_path(clock, position, requirement)
        if current:
            _apply_validation_group(runtime, clock, tuple(current))


# Define event kind for stream as one focused operation with an explicit boundary.
def _event_kind_for_stream(stream: CapabilityStream) -> EventKind:
    # Execute the event kind for stream workflow in explicit, reviewable steps.
    return {
        CapabilityStream.BLOCK_CLOCK: EventKind.BLOCK,
        CapabilityStream.TOKEN_LAUNCH: EventKind.TOKEN_LAUNCH,
        CapabilityStream.PUMP_CURVE_TRADE: EventKind.VENUE_TRADE,
        CapabilityStream.PUMP_CURVE_LIFECYCLE: EventKind.VENUE_LIFECYCLE,
        # Include stream in the completed event kind for stream result.
    }[stream]


def _apply_validation_group(
    runtime: PumpfunSnipingProtocolRuntime,
    clock: CompactTransactionClock,
    events: tuple[CanonicalEvent, ...],
    # Close the apply validation group signature after its explicit inputs.
) -> None:
    # Execute the apply validation group workflow in explicit, reviewable steps.
    transaction_event = next(
        (event for event in events if event.envelope.position.transaction_index >= 0),
        None,
    )
    if isinstance(events[0], BlockEvent):
        # Handle the apply validation group isinstance(events[0], BlockEvent) branch as a
        # distinct logical block.
        if events[0].block_time_ns is None:
            raise SnapshotValidationError(SnapshotValidationErrorCode.CLOCK_INVALID)
        effective_at_unix_s = events[0].block_time_ns // 1_000_000_000
    else:
        if transaction_event is None:  # pragma: no cover - canonical event union proves it
            raise SnapshotValidationError(SnapshotValidationErrorCode.TRANSACTION_GROUP_INVALID)
        effective_at_unix_s = (
            clock.block_time_for_position(transaction_event.envelope.position) // 1_000_000_000
        )
    try:
        # Invoke apply_historical_group for events and effective at unix s as a visible
        # apply validation group step.
        runtime.apply_historical_group(events, effective_at_unix_s=effective_at_unix_s)
    except ProtocolContractError as error:
        raise SnapshotValidationError(SnapshotValidationErrorCode.PROTOCOL_STATE_INVALID) from error


def _require_settlement_path(
    clock: CompactTransactionClock,
    # Keep the position input explicit in the require settlement path contract.
    position: ChainPosition,
    requirement: SettlementRequirement,
) -> None:
    # Execute the require settlement path workflow in explicit, reviewable steps.
    try:
        # Perform the protected require settlement path operation before explicit failure
        # handling.
        initial_landing = clock.transaction_after(
            position,
            requirement.initial_delay_transactions,
        )
        followup_decision = clock.first_nonempty_transaction_at_or_after(
            # Pass after position explicitly so first_nonempty_transaction_at_or_after
            # receives a reviewable minimum duration ns and block time for position input
            # in require settlement path.
            after_position=initial_landing,
            target_time_ns=(
                clock.block_time_for_position(initial_landing) + requirement.minimum_duration_ns
            ),
        )
        # Invoke transaction_after for maximum followup delay transactions and followup
        # decision as a visible require settlement path step.
        clock.transaction_after(
            followup_decision,
            requirement.maximum_followup_delay_transactions,
        )
    except TransactionClockError as error:
        # Translate the TransactionClockError failure through the require settlement path
        # boundary.
        reason = (
            SnapshotValidationErrorCode.SETTLEMENT_TAIL_INSUFFICIENT
            if error.code
            in {
                TransactionClockErrorCode.DURATION_TARGET_OUTSIDE_CLOCK,
                # Keep the transaction clock error code component named inside the reason
                # contract.
                TransactionClockErrorCode.SETTLEMENT_TAIL_EXHAUSTED,
            }
            else SnapshotValidationErrorCode.EVENT_POSITION_INVALID
        )
        raise SnapshotValidationError(reason) from error


# Define unit projector tools as one focused operation with an explicit boundary.
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


def _curve_state(value: Any) -> PumpCurveStateV1:
    # Execute the curve state workflow in explicit, reviewable steps.
    try:
        # Perform the protected curve state operation before explicit failure handling.
        lifecycle = PumpCurveLifecycle(_string(value("lifecycle"), "lifecycle"))
        mode = PumpMode(_string(value("mode"), "mode"))
    except ValueError as error:
        raise ValueError("Pump state contains an unknown lifecycle or mode") from error
    if lifecycle is PumpCurveLifecycle.UNKNOWN or mode is PumpMode.UNKNOWN:
        # Fail the curve state path with ValueError for pump state contains an unknown
        # lifecycle or mode when lifecycle, unknown and mode is true; do not continue
        # ambiguously.
        raise ValueError("Pump state contains an unknown lifecycle or mode")
    return PumpCurveStateV1(
        virtual_token_reserves_atomic=_integer(
            value("virtual_token_reserves_atomic"),
            "virtual_token_reserves_atomic",
            # Pass minimum explicitly so _integer receives a reviewable virtual token
            # reserves atomic and value input in curve state.
            minimum=1,
        ),
        virtual_sol_reserves_lamports=_integer(
            value("virtual_sol_reserves_lamports"),
            "virtual_sol_reserves_lamports",
            # Pass minimum explicitly so _integer receives a reviewable virtual sol
            # reserves lamports and value input in curve state.
            minimum=1,
        ),
        real_token_reserves_atomic=_integer(
            value("real_token_reserves_atomic"),
            "real_token_reserves_atomic",
            # Pass minimum explicitly so _integer receives a reviewable real token
            # reserves atomic and value input in curve state.
            minimum=0,
        ),
        real_sol_reserves_lamports=_integer(
            value("real_sol_reserves_lamports"),
            "real_sol_reserves_lamports",
            # Pass minimum explicitly so _integer receives a reviewable real sol reserves
            # lamports and value input in curve state.
            minimum=0,
        ),
        token_total_supply_atomic=_integer(
            value("token_total_supply_atomic"),
            "token_total_supply_atomic",
            # Pass minimum explicitly so _integer receives a reviewable token total supply
            # atomic and value input in curve state.
            minimum=1,
        ),
        lifecycle=lifecycle,
        mode=mode,
    )


# Define source occurrence as one focused operation with an explicit boundary.
def _source_occurrence(
    spec: PumpfunProjectionSpec,
    row: tuple[Any, ...],
    indexes: Mapping[str, int],
    *,
    # Keep the candidate position input explicit in the source occurrence contract.
    candidate_position: Mapping[str, object],
) -> dict[str, object]:
    # Execute the source occurrence workflow in explicit, reviewable steps.
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
    return {"basis": "CANDIDATE_CHAIN_POSITION", "values": dict(candidate_position)}


def _identity_value(value: object, *, field: str) -> object:
    # Execute the identity value workflow in explicit, reviewable steps.
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


def _require_successful_launch_transaction(value: object) -> None:
    # Execute the require successful launch transaction workflow in explicit, reviewable
    # steps.
    if not isinstance(value, bool):
        raise PumpfunProjectionError(PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_STATUS_INVALID)
    if not value:
        raise PumpfunProjectionError(PumpfunProjectionErrorCode.LAUNCH_TRANSACTION_FAILED)


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    return value


def _time_ns(value: object) -> int:
    # Execute the time ns workflow in explicit, reviewable steps.
    if isinstance(value, bool):
        raise ValueError("block_time must not be boolean")
    if isinstance(value, int):
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
__all__ = [
    "PumpfunProjectionError",
    "PumpfunProjectionErrorCode",
    "PumpfunProjectionSpec",
    "PumpfunProtocolProjector",
    # Keep the pumpfun snapshot validator component named inside the all contract.
    "PumpfunSnapshotValidator",
]
