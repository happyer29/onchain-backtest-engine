"""Port for committed source revisions and gap-safe source frontiers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.source_ledger import CommittedShardRevision, SourceFrontier
from backtest.domain.identifiers import (
    CapabilityId,
    # Include network id so the identifiers dependency remains explicit.
    NetworkId,
    PositionSchemaId,
    SourceId,
)
from backtest.domain.time import BlockRange


# Keep the shard ledger contract and validation rules together.
@runtime_checkable
class ShardLedger(Protocol):
    def record_revision(self, revision: CommittedShardRevision) -> None: ...

    def contiguous_frontier(
        self,
        # Close the contiguous frontier signature after its explicit inputs.
        *,
        source_id: SourceId,
        capability_id: CapabilityId,
        capability_schema_version: str,
        network_id: NetworkId,
        # Keep the position schema id input explicit in the contiguous frontier contract.
        position_schema_id: PositionSchemaId,
        coverage_from_block_ordinal: int,
    ) -> SourceFrontier: ...

    def committed_revisions(
        self,
        # Close the committed revisions signature after its explicit inputs.
        *,
        source_id: SourceId,
        capability_id: CapabilityId,
        capability_schema_version: str,
        block_range: BlockRange,
        # Keep the tuple step explicit within the shard ledger committed revisions workflow.
    ) -> tuple[CommittedShardRevision, ...]: ...


__all__ = ["ShardLedger"]
