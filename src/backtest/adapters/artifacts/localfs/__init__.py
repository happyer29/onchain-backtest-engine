"""Durable local-filesystem artifact repository."""

from backtest.adapters.artifacts.localfs.capacity import LocalDiskCapacityProbe
from backtest.adapters.artifacts.localfs.completion_receipts import (
    LocalCompletionReceiptStore,
)
from backtest.adapters.artifacts.localfs.layout import (
    # Include data root layout so the layout dependency remains explicit.
    DataRootLayout,
    UnsafeDataRootIdentifierError,
)
from backtest.adapters.artifacts.localfs.materialize import (
    ArtifactClosureMaterializationError,
    # Include materialized artifact closure so the materialize dependency remains
    # explicit.
    MaterializedArtifactClosure,
    materialize_verified_artifact_closure,
)
from backtest.adapters.artifacts.localfs.repository import (
    LocalArtifactRepository,
    # Include staging quota exceeded error so the repository dependency remains explicit.
    StagingQuotaExceededError,
)
from backtest.adapters.artifacts.localfs.retention import LocalRetentionRepository
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner

__all__ = [
    # Keep the artifact closure materialization error component named inside the all
    # contract.
    "ArtifactClosureMaterializationError",
    "DataRootLayout",
    "LocalArtifactRepository",
    "LocalCommittedArtifactScanner",
    "LocalCompletionReceiptStore",
    # Keep the local disk capacity probe component named inside the all contract.
    "LocalDiskCapacityProbe",
    "LocalRetentionRepository",
    "MaterializedArtifactClosure",
    "StagingQuotaExceededError",
    "UnsafeDataRootIdentifierError",
    # Keep the materialize verified artifact closure component named inside the all
    # contract.
    "materialize_verified_artifact_closure",
]
