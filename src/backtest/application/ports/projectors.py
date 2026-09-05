"""Semantic protocol-projector boundary for canonical event production."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from backtest.application.ports.canonical import CanonicalSnapshotValidator
from backtest.application.ports.source import IndexedBatch

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import BundleId, CapabilityId, ContentDigest
from backtest.domain.market_events import CanonicalEvent, EventKind


# Keep the protocol projector contract and validation rules together.
@runtime_checkable
class ProtocolProjector(CanonicalSnapshotValidator, Protocol):
    @property
    def bundle_id(self) -> BundleId: ...

    @property
    def config_digest(self) -> ContentDigest: ...

    def supports(self, capability_id: CapabilityId) -> bool: ...

    # Define protocol projector event kind as one focused operation with an explicit
    # boundary.
    def event_kind(self, capability_id: CapabilityId) -> EventKind: ...

    def project(self, batch: IndexedBatch) -> Iterable[CanonicalEvent]: ...


__all__ = ["ProtocolProjector"]
