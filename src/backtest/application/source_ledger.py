"""Application contracts for immutable source-shard revisions and frontiers."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.application.canonical_data import SourceBoundary
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.domain.identifiers import CapabilityId, NetworkId, PositionSchemaId, SourceId


# Keep the shard ledger error contract and validation rules together.
class ShardLedgerError(RuntimeError):
    """Base failure in the committed source-shard ledger."""


class ShardLedgerConflictError(ShardLedgerError):
    """An immutable shard revision was presented with different metadata."""


class ShardArtifactNotVerifiedError(ShardLedgerError):
    """A shard cannot enter the ledger without verified filesystem authority."""


@dataclass(frozen=True, slots=True)
class CommittedShardRevision:
    artifact: CommittedArtifact
    boundary: SourceBoundary

    def __post_init__(self) -> None:
        # Execute the committed shard revision post init workflow in explicit, reviewable
        # steps.
        if self.artifact.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
            raise ValueError("a shard revision must reference a canonical distribution")


# Keep the source frontier contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SourceFrontier:
    source_id: SourceId
    capability_id: CapabilityId
    capability_schema_version: str
    # Declare network id explicitly in the source frontier contract.
    network_id: NetworkId
    position_schema_id: PositionSchemaId
    coverage_from_block_ordinal: int
    frontier_block_ordinal: int

    def __post_init__(self) -> None:
        # Execute the source frontier post init workflow in explicit, reviewable steps.
        if not self.capability_schema_version:
            raise ValueError("capability schema version must be non-empty")
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            # Fail the source frontier post init path with TypeError for position schema
            # id must be a position schema id when isinstance and position schema id is
            # true; do not continue ambiguously.
            raise TypeError("position_schema_id must be a PositionSchemaId")
        if self.coverage_from_block_ordinal < 0:
            raise ValueError("coverage start must be non-negative")
        if self.frontier_block_ordinal < self.coverage_from_block_ordinal:
            raise ValueError("frontier cannot precede its coverage start")


# Bind all once as an explicit module-level contract.
__all__ = [
    "CommittedShardRevision",
    "ShardArtifactNotVerifiedError",
    "ShardLedgerConflictError",
    "ShardLedgerError",
    # Keep the source frontier component named inside the all contract.
    "SourceFrontier",
]
