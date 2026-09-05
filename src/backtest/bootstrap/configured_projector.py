"""Composition of strict projection declarations with installed plugins."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from backtest.adapters.source.clickhouse import ClickHouseCapability
from backtest.application.code_bundles import PinnedCodeBundleSet

# Import models at the visible module dependency boundary.
from backtest.application.models import CapabilityStream
from backtest.application.ports.projectors import ProtocolProjector
from backtest.bootstrap.projector_config import (
    ProjectorConfigError,
    load_projection_declarations,
    # Include load projection specs so the projector config dependency remains explicit.
    load_projection_specs,
)
from backtest.domain.identifiers import ContentDigest
from backtest.domain.market_events import EventKindName
from backtest.plugins.protocols.pumpfun.projector import (
    PumpfunProjectionSpec,
    # Include pumpfun protocol projector so the projector dependency remains explicit.
    PumpfunProtocolProjector,
)
from backtest.plugins.protocols.reference import ReferenceProtocolProjector

_PUMP_STREAMS = {
    CapabilityStream.BLOCK_CLOCK,
    # Keep the capability stream component named inside the pump streams contract.
    CapabilityStream.TOKEN_LAUNCH,
    CapabilityStream.PUMP_CURVE_TRADE,
    CapabilityStream.PUMP_CURVE_LIFECYCLE,
}


def build_configured_projector(
    # Keep the path input explicit in the build configured projector contract.
    path: Path,
    capabilities: Sequence[ClickHouseCapability],
    *,
    build_tools: PinnedCodeBundleSet,
    source_normalizer_digest: ContentDigest | None = None,
) -> ProtocolProjector:
    """Build one closed projector; protocol mixtures fail at composition."""

    configuration = load_projection_declarations(path, capabilities)
    by_id = {item.descriptor.capability_id: item.descriptor for item in capabilities}
    selected = tuple(by_id[item.capability_id] for item in configuration.declarations)
    streams = {item.stream for item in selected}
    is_pump_contract = bool(
        # Keep the intersection and streams intersection step visible while building is
        # pump contract.
        streams.intersection(
            {
                CapabilityStream.TOKEN_LAUNCH,
                CapabilityStream.PUMP_CURVE_TRADE,
                CapabilityStream.PUMP_CURVE_LIFECYCLE,
                # Close the token launch and pump curve trade payload only after all build
                # configured projector fields are present.
            }
        )
    )
    if not is_pump_contract:
        # Handle the build configured projector not is_pump_contract branch as a distinct
        # logical block.
        return ReferenceProtocolProjector(
            load_projection_specs(path, capabilities),
            build_tools=build_tools,
        )
    if streams != _PUMP_STREAMS or len(selected) != len(_PUMP_STREAMS):
        # Handle the build configured projector streams, pump streams and selected
        # condition as a distinct block.
        raise ProjectorConfigError(
            "Pump projection requires exactly one block, launch, trade and lifecycle stream"
        )
    declarations = {item.capability_id: item for item in configuration.declarations}
    specs: list[PumpfunProjectionSpec] = []
    # Traverse selected explicitly so each build configured projector iteration remains
    # traceable.
    for descriptor in selected:
        # Process selected inside the bounded build configured projector loop.
        declaration = declarations[descriptor.capability_id]
        if (
            descriptor.stream is CapabilityStream.BLOCK_CLOCK
            and declaration.event_kind is not EventKindName.BLOCK
        ):
            # Fail the build configured projector path with ProjectorConfigError for pump
            # block capability has an invalid event kind when stream, block clock and
            # event kind is true; do not continue ambiguously.
            raise ProjectorConfigError("Pump block capability has an invalid event kind")
        try:
            # Perform the protected build configured projector operation before explicit
            # failure handling.
            specs.append(
                PumpfunProjectionSpec(
                    capability_id=descriptor.capability_id,
                    kind=declaration.event_kind,
                    protocol=descriptor.protocol,
                    # Pass protocol version explicitly so PumpfunProjectionSpec receives a
                    # reviewable capability id and event kind input in build configured
                    # projector.
                    protocol_version=descriptor.protocol_version,
                    identity_fidelity=descriptor.fidelity.identity,
                    ordering_fidelity=descriptor.fidelity.ordering,
                    source_total_key=descriptor.total_key,
                    source_total_key_is_proven=descriptor.keyset_key_is_proven,
                    # Pass protocol payload schema id explicitly so PumpfunProjectionSpec
                    # receives a reviewable capability id and event kind input in build
                    # configured projector.
                    protocol_payload_schema_id=declaration.protocol_payload_schema_id,
                    columns=declaration.columns,
                )
            )
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the build configured
            # projector boundary.
            raise ProjectorConfigError(
                f"projection is not supported by the installed Pump projector: {error}"
            ) from None
    try:
        # Perform the protected build configured projector operation before explicit
        # failure handling.
        return PumpfunProtocolProjector(
            network_id=configuration.network_id,
            position_schema_id=configuration.position_schema_id,
            specs=tuple(specs),
            source_normalizer_digest=source_normalizer_digest,
            build_tools=build_tools,
            # Complete PumpfunProtocolProjector only after its network id and position schema
            # id inputs are visible in build configured projector.
        )
    except (TypeError, ValueError) as error:
        raise ProjectorConfigError(f"Pump projector configuration is invalid: {error}") from None


__all__ = ["build_configured_projector"]
