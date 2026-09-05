"""SQLite-backed local catalog adapters."""

from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.adapters.catalog.sqlite.backup import SQLiteCheckpointRepository
from backtest.adapters.catalog.sqlite.canonical_outputs import (
    CanonicalOutputIndexError,
    SQLiteCanonicalOutputObserver,
    # Close the canonical outputs import after its required symbols are visible.
)
from backtest.adapters.catalog.sqlite.errors import (
    AttemptNotFoundError,
    JobQueueError,
    QueueCorruptionError,
    # Close the errors import after its required symbols are visible.
)
from backtest.adapters.catalog.sqlite.job_queue import SQLiteJobQueue
from backtest.adapters.catalog.sqlite.retention_index import (
    SQLiteRetentionIndex,
    SQLiteRetentionRootProvider,
    # Close the retention index import after its required symbols are visible.
)
from backtest.adapters.catalog.sqlite.shard_ledger import SQLiteShardLedger
from backtest.application.completion import UnverifiedJobCompletionError
from backtest.application.errors import (
    IdempotencyConflictError,
    # Include invalid idempotency key error so the errors dependency remains explicit.
    InvalidIdempotencyKeyError,
    JobNotFoundError,
    JobStateConflictError,
)

__all__ = [
    # Keep the attempt not found error component named inside the all contract.
    "AttemptNotFoundError",
    "CanonicalOutputIndexError",
    "IdempotencyConflictError",
    "InvalidIdempotencyKeyError",
    "JobNotFoundError",
    # Keep the job queue error component named inside the all contract.
    "JobQueueError",
    "JobStateConflictError",
    "QueueCorruptionError",
    "SQLiteArtifactCatalog",
    "SQLiteCanonicalOutputObserver",
    # Keep the sqlite checkpoint repository component named inside the all contract.
    "SQLiteCheckpointRepository",
    "SQLiteJobQueue",
    "SQLiteRetentionIndex",
    "SQLiteRetentionRootProvider",
    "SQLiteShardLedger",
    # Keep the unverified job completion error component named inside the all contract.
    "UnverifiedJobCompletionError",
]
