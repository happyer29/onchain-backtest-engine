"""Strict reference projector used by the first canonical vertical slice."""

from backtest.plugins.protocols.reference.projector import (
    ProjectionKind,
    ProjectionSpec,
    ReferenceProtocolProjector,
)

# Bind all once as an explicit module-level contract.
__all__ = ["ProjectionKind", "ProjectionSpec", "ReferenceProtocolProjector"]
