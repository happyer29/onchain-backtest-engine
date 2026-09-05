"""Model-artifact lookup boundary.

Actual training/inference contracts are intentionally deferred to architecture
section 24; this port only resolves an immutable committed model bundle.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.models import CommittedArtifact
from backtest.domain.identifiers import ArtifactId


@runtime_checkable
# Keep the model repository contract and validation rules together.
class ModelRepository(Protocol):
    def open_model_bundle(self, model_bundle_id: ArtifactId) -> CommittedArtifact: ...


__all__ = ["ModelRepository"]
