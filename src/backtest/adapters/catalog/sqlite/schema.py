"""SQLite connection policy and versioned local-catalog migrations.

The database mixes two classes of state with deliberately different recovery
semantics:

* the job queue is authoritative operational state and must be restored from a
  SQLite backup (or explicitly started empty);
* artifact, lineage, pin and frontier tables are rebuildable indexes over
  verified filesystem authority.

Migrations are append-only and applied under ``BEGIN IMMEDIATE``.  SQLite's
``user_version`` is the durable schema-version boundary; opening a database
created by newer code fails closed.
"""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path
from threading import Lock

# Import typing at the visible module dependency boundary.
from typing import Final, NoReturn

LATEST_SCHEMA_VERSION: Final = 10
_INITIALIZE_LOCK: Final = Lock()


class SQLiteSchemaError(RuntimeError):
    """The local catalog cannot be opened as a complete supported schema."""


_QUEUE_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    command_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    resolved_spec BLOB NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('QUEUED', 'STARTING', 'RUNNING', 'SUCCEEDED',
                  'FAILED', 'CANCELLED', 'INTERRUPTED')
    ),
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    current_attempt_id TEXT,
    submitted_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL,
    UNIQUE (command_type, idempotency_key),
    FOREIGN KEY (current_attempt_id) REFERENCES job_attempts(attempt_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS job_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    supervisor_instance_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('STARTING', 'RUNNING', 'SUCCEEDED',
                  'FAILED', 'CANCELLED', 'INTERRUPTED')
    ),
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    result_artifact_id TEXT,
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL,
    UNIQUE (job_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS jobs_claim_order_idx
    ON jobs(state, cancel_requested, submitted_at_ns, job_id);
CREATE INDEX IF NOT EXISTS job_attempts_job_idx
    ON job_attempts(job_id, attempt_number);

CREATE TRIGGER IF NOT EXISTS jobs_immutable_command
BEFORE UPDATE OF command_type, idempotency_key, request_digest, resolved_spec ON jobs
BEGIN
    SELECT RAISE(ABORT, 'resolved job command is immutable');
END;
"""

_CATALOG_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS artifact_index (
    artifact_id TEXT PRIMARY KEY CHECK (length(artifact_id) = 64),
    kind TEXT NOT NULL,
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    build_key TEXT NOT NULL CHECK (length(build_key) = 64),
    status TEXT NOT NULL CHECK (status IN ('VERIFIED', 'QUARANTINED', 'INVALID')),
    status_reason TEXT,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0),
    verified_at_ns INTEGER NOT NULL CHECK (verified_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS build_key_mapping (
    build_key TEXT PRIMARY KEY CHECK (length(build_key) = 64),
    artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id),
    status TEXT NOT NULL CHECK (status IN ('VERIFIED', 'CONFLICT')),
    first_seen_at_ns INTEGER NOT NULL CHECK (first_seen_at_ns >= 0),
    updated_at_ns INTEGER NOT NULL CHECK (updated_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS artifact_build_conflicts (
    build_key TEXT NOT NULL CHECK (length(build_key) = 64),
    artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id),
    detected_at_ns INTEGER NOT NULL CHECK (detected_at_ns >= 0),
    PRIMARY KEY (build_key, artifact_id)
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    output_artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id) ON DELETE CASCADE,
    input_artifact_id TEXT NOT NULL CHECK (length(input_artifact_id) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (output_artifact_id, input_artifact_id),
    UNIQUE (output_artifact_id, ordinal),
    CHECK (output_artifact_id <> input_artifact_id)
);

CREATE INDEX IF NOT EXISTS artifact_index_kind_status_idx
    ON artifact_index(kind, status, artifact_id);
CREATE INDEX IF NOT EXISTS artifact_index_build_key_idx
    ON artifact_index(build_key, status, artifact_id);
CREATE INDEX IF NOT EXISTS lineage_edges_input_idx
    ON lineage_edges(input_artifact_id, output_artifact_id);

CREATE TABLE IF NOT EXISTS pins (
    pin_id TEXT PRIMARY KEY,
    record_digest TEXT NOT NULL CHECK (length(record_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'INVALID')),
    reason TEXT NOT NULL,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS pin_roots (
    pin_id TEXT NOT NULL REFERENCES pins(pin_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (pin_id, artifact_id),
    UNIQUE (pin_id, ordinal)
);

CREATE INDEX IF NOT EXISTS pin_roots_artifact_idx
    ON pin_roots(artifact_id, pin_id);

CREATE TABLE IF NOT EXISTS shard_ledger (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    from_slot INTEGER NOT NULL CHECK (from_slot >= 0),
    to_slot INTEGER NOT NULL CHECK (to_slot > from_slot),
    internal_revision TEXT NOT NULL CHECK (length(internal_revision) = 64),
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    snapshot_cut_to_slot INTEGER NOT NULL CHECK (snapshot_cut_to_slot = to_slot),
    chain_finality TEXT NOT NULL,
    ingestion_watermark_to_slot INTEGER,
    upstream_revision TEXT,
    source_consistency TEXT NOT NULL,
    completeness TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    committed_at_ns INTEGER NOT NULL CHECK (committed_at_ns >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision
    ),
    UNIQUE (artifact_id),
    CHECK (
        ingestion_watermark_to_slot IS NULL
        OR ingestion_watermark_to_slot >= 0
    )
);

CREATE TABLE IF NOT EXISTS shard_query_fingerprints (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    from_slot INTEGER NOT NULL,
    to_slot INTEGER NOT NULL,
    internal_revision TEXT NOT NULL,
    query_fingerprint TEXT NOT NULL CHECK (length(query_fingerprint) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision, query_fingerprint
    ),
    UNIQUE (
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision, ordinal
    ),
    FOREIGN KEY (
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision
    ) REFERENCES shard_ledger (
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision
    ) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS shard_ledger_frontier_idx
    ON shard_ledger(
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision
    );

CREATE TABLE IF NOT EXISTS source_frontiers (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    coverage_from_slot INTEGER NOT NULL CHECK (coverage_from_slot >= 0),
    frontier_slot INTEGER NOT NULL CHECK (frontier_slot >= 0),
    computed_at_ns INTEGER NOT NULL CHECK (computed_at_ns >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version, coverage_from_slot
    ),
    CHECK (frontier_slot >= coverage_from_slot)
);

CREATE TABLE IF NOT EXISTS completion_receipts (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id),
    resolved_spec_id TEXT NOT NULL CHECK (length(resolved_spec_id) = 64),
    receipt_digest TEXT NOT NULL CHECK (length(receipt_digest) = 64),
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS completion_receipt_outputs (
    attempt_id TEXT NOT NULL REFERENCES completion_receipts(attempt_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (attempt_id, artifact_id),
    UNIQUE (attempt_id, ordinal)
);

CREATE TABLE IF NOT EXISTS job_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    details BLOB,
    CHECK (details IS NULL OR length(details) <= 65536)
);

CREATE INDEX IF NOT EXISTS job_events_job_idx
    ON job_events(job_id, event_id);
CREATE INDEX IF NOT EXISTS job_events_attempt_idx
    ON job_events(attempt_id, event_id);
"""

_SUPERVISOR_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS attempt_runtime (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    supervisor_instance_id TEXT NOT NULL,
    process_id INTEGER NOT NULL CHECK (process_id > 0),
    process_start_token TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('BUILD', 'RUN')),
    private_memory_bytes INTEGER NOT NULL CHECK (private_memory_bytes > 0),
    native_threads INTEGER NOT NULL CHECK (native_threads > 0),
    io_units INTEGER NOT NULL CHECK (io_units > 0),
    registered_at_ns INTEGER NOT NULL CHECK (registered_at_ns >= 0),
    heartbeat_at_ns INTEGER NOT NULL CHECK (heartbeat_at_ns >= registered_at_ns),
    lease_expires_at_ns INTEGER NOT NULL CHECK (lease_expires_at_ns > heartbeat_at_ns),
    deadline_at_ns INTEGER NOT NULL CHECK (deadline_at_ns > registered_at_ns)
);

CREATE INDEX IF NOT EXISTS attempt_runtime_lease_idx
    ON attempt_runtime(lease_expires_at_ns, attempt_id);

CREATE TABLE IF NOT EXISTS attempt_failures (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    failure_kind TEXT NOT NULL CHECK (
        failure_kind IN (
            'TRANSIENT', 'RESOURCE_EXHAUSTED', 'USER_ERROR', 'INTERNAL_ERROR',
            'TIMEOUT', 'ORPHANED', 'COMPLETION_INVALID'
        )
    ),
    failure_code TEXT NOT NULL CHECK (
        failure_code IN (
            'SPAWN_FAILED', 'REGISTRATION_FAILED', 'CHILD_EXITED',
                'CHILD_SIGNALED', 'TIMEOUT', 'ORPHANED_ON_RESTART',
                'COMPLETION_MISSING', 'COMPLETION_INVALID', 'ADMISSION_LOST'
        )
    ),
    retry_scheduled INTEGER NOT NULL CHECK (retry_scheduled IN (0, 1)),
    retry_not_before_ns INTEGER,
    recorded_at_ns INTEGER NOT NULL CHECK (recorded_at_ns >= 0),
    CHECK (
        (retry_scheduled = 1 AND retry_not_before_ns IS NOT NULL)
        OR (retry_scheduled = 0 AND retry_not_before_ns IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS job_retry_schedule (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    previous_attempt_id TEXT NOT NULL REFERENCES job_attempts(attempt_id),
    not_before_ns INTEGER NOT NULL CHECK (not_before_ns >= 0),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);

CREATE INDEX IF NOT EXISTS job_retry_due_idx
    ON job_retry_schedule(not_before_ns, job_id);
"""

_RESOURCE_ADMISSION_SCHEMA_V4 = """
CREATE TABLE attempt_failures_v4 (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    failure_kind TEXT NOT NULL CHECK (
        failure_kind IN (
            'TRANSIENT', 'RESOURCE_EXHAUSTED', 'USER_ERROR', 'INTERNAL_ERROR',
            'TIMEOUT', 'ORPHANED', 'COMPLETION_INVALID'
        )
    ),
    failure_code TEXT NOT NULL CHECK (
        failure_code IN (
            'SPAWN_FAILED', 'REGISTRATION_FAILED', 'CHILD_EXITED',
            'CHILD_SIGNALED', 'TIMEOUT', 'ORPHANED_ON_RESTART',
            'COMPLETION_MISSING', 'COMPLETION_INVALID', 'ADMISSION_LOST',
            'DISK_EMERGENCY', 'MEMORY_LIMIT_EXCEEDED', 'SUSTAINED_SWAP',
            'TEMPORARY_DISK_QUOTA_EXCEEDED'
        )
    ),
    retry_scheduled INTEGER NOT NULL CHECK (retry_scheduled IN (0, 1)),
    retry_not_before_ns INTEGER,
    recorded_at_ns INTEGER NOT NULL CHECK (recorded_at_ns >= 0),
    CHECK (
        (retry_scheduled = 1 AND retry_not_before_ns IS NOT NULL)
        OR (retry_scheduled = 0 AND retry_not_before_ns IS NULL)
    )
);

INSERT INTO attempt_failures_v4
SELECT * FROM attempt_failures;

DROP TABLE attempt_failures;
ALTER TABLE attempt_failures_v4 RENAME TO attempt_failures;
"""

_RESOURCE_OBSERVATION_SCHEMA_V5 = """
CREATE TABLE attempt_failures_v5 (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    failure_kind TEXT NOT NULL CHECK (
        failure_kind IN (
            'TRANSIENT', 'RESOURCE_EXHAUSTED', 'USER_ERROR', 'INTERNAL_ERROR',
            'TIMEOUT', 'ORPHANED', 'COMPLETION_INVALID'
        )
    ),
    failure_code TEXT NOT NULL CHECK (
        failure_code IN (
            'SPAWN_FAILED', 'REGISTRATION_FAILED', 'CHILD_EXITED',
            'CHILD_SIGNALED', 'TIMEOUT', 'ORPHANED_ON_RESTART',
            'COMPLETION_MISSING', 'COMPLETION_INVALID', 'ADMISSION_LOST',
            'DISK_EMERGENCY', 'MEMORY_LIMIT_EXCEEDED', 'SUSTAINED_SWAP',
            'TEMPORARY_DISK_QUOTA_EXCEEDED', 'RESOURCE_OBSERVATION_UNAVAILABLE'
        )
    ),
    retry_scheduled INTEGER NOT NULL CHECK (retry_scheduled IN (0, 1)),
    retry_not_before_ns INTEGER,
    recorded_at_ns INTEGER NOT NULL CHECK (recorded_at_ns >= 0),
    CHECK (
        (retry_scheduled = 1 AND retry_not_before_ns IS NOT NULL)
        OR (retry_scheduled = 0 AND retry_not_before_ns IS NULL)
    )
);

INSERT INTO attempt_failures_v5
SELECT * FROM attempt_failures;

DROP TABLE attempt_failures;
ALTER TABLE attempt_failures_v5 RENAME TO attempt_failures;
"""

# Bind network source index schema v6 once as an explicit module-level contract.
_NETWORK_SOURCE_INDEX_SCHEMA_V6 = """
-- Source ledger rows are rebuildable indexes over immutable artifacts.  The
-- legacy rows do not carry an immutable NetworkId/PositionSchemaId, so they
-- are discarded instead of being assigned an implicit Solana identity.
DROP TABLE source_frontiers;
DROP TABLE shard_query_fingerprints;
DROP TABLE shard_ledger;

CREATE TABLE shard_ledger (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    network_id TEXT NOT NULL,
    position_schema_id TEXT NOT NULL,
    from_block_ordinal INTEGER NOT NULL CHECK (from_block_ordinal >= 0),
    to_block_ordinal INTEGER NOT NULL CHECK (to_block_ordinal > from_block_ordinal),
    internal_revision TEXT NOT NULL CHECK (length(internal_revision) = 64),
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    snapshot_cut_to_block INTEGER NOT NULL CHECK (
        snapshot_cut_to_block = to_block_ordinal
    ),
    chain_finality TEXT NOT NULL,
    ingestion_watermark_to_block INTEGER,
    upstream_revision TEXT,
    source_consistency TEXT NOT NULL,
    completeness TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    committed_at_ns INTEGER NOT NULL CHECK (committed_at_ns >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision
    ),
    UNIQUE (artifact_id),
    CHECK (
        ingestion_watermark_to_block IS NULL
        OR ingestion_watermark_to_block >= 0
    )
);

CREATE TABLE shard_query_fingerprints (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    network_id TEXT NOT NULL,
    position_schema_id TEXT NOT NULL,
    from_block_ordinal INTEGER NOT NULL,
    to_block_ordinal INTEGER NOT NULL,
    internal_revision TEXT NOT NULL,
    query_fingerprint TEXT NOT NULL CHECK (length(query_fingerprint) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision,
        query_fingerprint
    ),
    UNIQUE (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, ordinal
    ),
    FOREIGN KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision
    ) REFERENCES shard_ledger (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision
    ) ON DELETE CASCADE
);

CREATE INDEX shard_ledger_frontier_idx
    ON shard_ledger(
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision
    );

CREATE TABLE source_frontiers (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    network_id TEXT NOT NULL,
    position_schema_id TEXT NOT NULL,
    coverage_from_block_ordinal INTEGER NOT NULL CHECK (
        coverage_from_block_ordinal >= 0
    ),
    frontier_block_ordinal INTEGER NOT NULL CHECK (frontier_block_ordinal >= 0),
    computed_at_ns INTEGER NOT NULL CHECK (computed_at_ns >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id, coverage_from_block_ordinal
    ),
    CHECK (frontier_block_ordinal >= coverage_from_block_ordinal)
);
"""

_MULTI_ARTIFACT_SHARD_LEDGER_SCHEMA_V7 = """
-- One logical source revision may have several immutable physical
-- distributions (for example after a writer-bundle/layout change).  Keep the
-- artifact in the relational identity so reconciliation can index every
-- verified variant without conflating their query provenance.
CREATE TABLE shard_ledger_v7 (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    network_id TEXT NOT NULL,
    position_schema_id TEXT NOT NULL,
    from_block_ordinal INTEGER NOT NULL CHECK (from_block_ordinal >= 0),
    to_block_ordinal INTEGER NOT NULL CHECK (to_block_ordinal > from_block_ordinal),
    internal_revision TEXT NOT NULL CHECK (length(internal_revision) = 64),
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    snapshot_cut_to_block INTEGER NOT NULL CHECK (
        snapshot_cut_to_block = to_block_ordinal
    ),
    chain_finality TEXT NOT NULL,
    ingestion_watermark_to_block INTEGER,
    upstream_revision TEXT,
    source_consistency TEXT NOT NULL,
    completeness TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    committed_at_ns INTEGER NOT NULL CHECK (committed_at_ns >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id
    ),
    UNIQUE (artifact_id),
    CHECK (
        ingestion_watermark_to_block IS NULL
        OR ingestion_watermark_to_block >= 0
    )
);

CREATE TABLE shard_query_fingerprints_v7 (
    source_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_schema_version TEXT NOT NULL,
    network_id TEXT NOT NULL,
    position_schema_id TEXT NOT NULL,
    from_block_ordinal INTEGER NOT NULL,
    to_block_ordinal INTEGER NOT NULL,
    internal_revision TEXT NOT NULL,
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    query_fingerprint TEXT NOT NULL CHECK (length(query_fingerprint) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id,
        query_fingerprint
    ),
    UNIQUE (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id,
        ordinal
    ),
    FOREIGN KEY (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id
    ) REFERENCES shard_ledger_v7 (
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id
    ) ON DELETE CASCADE
);

INSERT INTO shard_ledger_v7 (
    source_id, capability_id, capability_schema_version,
    network_id, position_schema_id,
    from_block_ordinal, to_block_ordinal, internal_revision, artifact_id,
    snapshot_cut_to_block, chain_finality, ingestion_watermark_to_block,
    upstream_revision, source_consistency, completeness, validation_status,
    committed_at_ns
)
SELECT
    source_id, capability_id, capability_schema_version,
    network_id, position_schema_id,
    from_block_ordinal, to_block_ordinal, internal_revision, artifact_id,
    snapshot_cut_to_block, chain_finality, ingestion_watermark_to_block,
    upstream_revision, source_consistency, completeness, validation_status,
    committed_at_ns
FROM shard_ledger;

INSERT INTO shard_query_fingerprints_v7 (
    source_id, capability_id, capability_schema_version,
    network_id, position_schema_id,
    from_block_ordinal, to_block_ordinal, internal_revision, artifact_id,
    query_fingerprint, ordinal
)
SELECT
    fingerprints.source_id,
    fingerprints.capability_id,
    fingerprints.capability_schema_version,
    fingerprints.network_id,
    fingerprints.position_schema_id,
    fingerprints.from_block_ordinal,
    fingerprints.to_block_ordinal,
    fingerprints.internal_revision,
    ledger.artifact_id,
    fingerprints.query_fingerprint,
    fingerprints.ordinal
FROM shard_query_fingerprints AS fingerprints
JOIN shard_ledger AS ledger
  ON ledger.source_id = fingerprints.source_id
 AND ledger.capability_id = fingerprints.capability_id
 AND ledger.capability_schema_version = fingerprints.capability_schema_version
 AND ledger.network_id = fingerprints.network_id
 AND ledger.position_schema_id = fingerprints.position_schema_id
 AND ledger.from_block_ordinal = fingerprints.from_block_ordinal
 AND ledger.to_block_ordinal = fingerprints.to_block_ordinal
 AND ledger.internal_revision = fingerprints.internal_revision;

DROP TABLE shard_query_fingerprints;
DROP TABLE shard_ledger;
ALTER TABLE shard_ledger_v7 RENAME TO shard_ledger;
ALTER TABLE shard_query_fingerprints_v7 RENAME TO shard_query_fingerprints;

CREATE INDEX shard_ledger_frontier_idx
    ON shard_ledger(
        source_id, capability_id, capability_schema_version,
        network_id, position_schema_id,
        from_block_ordinal, to_block_ordinal, internal_revision, artifact_id
    );
"""

_RUN_INDEX_SCHEMA_V8 = """
-- Run ordering is a rebuildable projection over an exact verified manifest.
-- Filesystem publication remains authoritative; this table only makes bounded
-- newest-first and logical-run pagination indexable.
CREATE TABLE run_index_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    status TEXT NOT NULL CHECK (status IN ('DIRTY', 'COMPLETE')),
    generation INTEGER NOT NULL CHECK (generation >= 0)
);

-- An upgraded catalog with existing Runs must be rebuilt before it can answer
-- globally ordered pages; a genuinely empty projection is already complete.
INSERT INTO run_index_state (singleton, status, generation)
SELECT 1,
       CASE WHEN EXISTS (
           SELECT 1 FROM artifact_index WHERE kind = 'RUN' AND status = 'VERIFIED'
       ) THEN 'DIRTY' ELSE 'COMPLETE' END,
       0;

CREATE TABLE run_index (
    artifact_id TEXT PRIMARY KEY
        REFERENCES artifact_index(artifact_id) ON DELETE CASCADE,
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    is_queryable INTEGER NOT NULL CHECK (is_queryable IN (0, 1)),
    -- Non-successful legacy/debug Run artifacts remain explicitly unqueryable.
    logical_run_id TEXT,
    execution_attempt_id TEXT,
    started_at_ns INTEGER,
    completed_at_ns INTEGER,
    CHECK (
        (is_queryable = 0
         AND logical_run_id IS NULL
         AND execution_attempt_id IS NULL
         AND started_at_ns IS NULL
         AND completed_at_ns IS NULL)
        OR
        (is_queryable = 1
         AND length(logical_run_id) = 64
         AND length(execution_attempt_id) = 64
         AND started_at_ns >= 0
         AND completed_at_ns >= started_at_ns)
    )
);

CREATE INDEX run_index_completed_idx
    ON run_index(is_queryable, completed_at_ns DESC, artifact_id ASC);
CREATE INDEX run_index_logical_completed_idx
    ON run_index(is_queryable, logical_run_id, completed_at_ns DESC, artifact_id ASC);

-- A projection row cannot be attached to a non-Run, quarantined, or different
-- manifest descriptor even inside a buggy catalog transaction.
CREATE TRIGGER run_index_verified_artifact_insert
BEFORE INSERT ON run_index
WHEN NOT EXISTS (
    SELECT 1
    FROM artifact_index
    WHERE artifact_id = NEW.artifact_id
      AND manifest_digest = NEW.manifest_digest
      -- Only a currently verified Run descriptor may acquire a projection.
      AND kind = 'RUN'
      AND status = 'VERIFIED'
)
BEGIN
    SELECT RAISE(ABORT, 'run index requires a matching verified Run artifact');
END;

-- Committed Run projection fields are immutable between explicit atomic
-- rebuilds, matching the immutable filesystem artifact they describe.
CREATE TRIGGER run_index_immutable
BEFORE UPDATE ON run_index
BEGIN
    SELECT RAISE(ABORT, 'run index entries are immutable');
END;

-- Any row-set mutation invalidates global ordering until the catalog adapter
-- proves completeness and closes the surrounding transaction.
CREATE TRIGGER run_index_dirty_after_insert
AFTER INSERT ON run_index
BEGIN
    UPDATE run_index_state
    SET status = 'DIRTY', generation = generation + 1
    WHERE singleton = 1;
END;

CREATE TRIGGER run_index_dirty_after_delete
AFTER DELETE ON run_index
BEGIN
    UPDATE run_index_state
    SET status = 'DIRTY', generation = generation + 1
    WHERE singleton = 1;
END;
"""

_ARTIFACT_RECONCILIATION_SCHEMA_V9 = """
-- Restart evidence only decides whether full payload re-hashing is required.
-- It never makes a missing or invalid committed artifact authoritative.
CREATE TABLE artifact_reconciliation_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    status TEXT NOT NULL CHECK (status IN ('CLEAN', 'UNCLEAN')),
    inventory_digest TEXT CHECK (
        inventory_digest IS NULL OR length(inventory_digest) = 64
    ),
    artifact_count INTEGER CHECK (
        artifact_count IS NULL OR artifact_count >= 0
    ),
    CHECK (
        (inventory_digest IS NULL AND artifact_count IS NULL)
        OR (inventory_digest IS NOT NULL AND artifact_count IS NOT NULL)
    ),
    CHECK (status = 'UNCLEAN' OR inventory_digest IS NOT NULL)
);

-- A migration or fresh database has no clean-shutdown proof and must full-scan.
INSERT INTO artifact_reconciliation_state (
    singleton, status, inventory_digest, artifact_count
) VALUES (1, 'UNCLEAN', NULL, NULL);
"""

_JOB_LIST_INDEX_SCHEMA_V10 = """
-- Browser keyset pages use these complete orders rather than the claim index.
CREATE INDEX jobs_list_submitted_idx
    ON jobs(submitted_at_ns DESC, job_id DESC);
CREATE INDEX jobs_state_list_submitted_idx
    ON jobs(state, submitted_at_ns DESC, job_id DESC);

-- Any schema migration invalidates prior clean-start evidence.
UPDATE artifact_reconciliation_state
SET status = 'UNCLEAN', inventory_digest = NULL, artifact_count = NULL
WHERE singleton = 1;
"""

_MIGRATIONS: Final[tuple[str, ...]] = (
    _QUEUE_SCHEMA_V1,
    _CATALOG_SCHEMA_V2,
    _SUPERVISOR_SCHEMA_V3,
    # Keep the resource admission schema v4 component named inside the migrations
    # contract.
    _RESOURCE_ADMISSION_SCHEMA_V4,
    _RESOURCE_OBSERVATION_SCHEMA_V5,
    _NETWORK_SOURCE_INDEX_SCHEMA_V6,
    _MULTI_ARTIFACT_SHARD_LEDGER_SCHEMA_V7,
    _RUN_INDEX_SCHEMA_V8,
    # Restart fast-path evidence is operational and remains outside artifact identity.
    _ARTIFACT_RECONCILIATION_SCHEMA_V9,
    # Dedicated list indexes keep global and state-filtered keyset reads bounded.
    _JOB_LIST_INDEX_SCHEMA_V10,
)

_EXPECTED_V9_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    # Keep the jobs component named inside the expected v6 columns contract.
    "jobs": (
        "job_id",
        "command_type",
        "idempotency_key",
        "request_digest",
        # Keep the resolved spec component named inside the expected v6 columns contract.
        "resolved_spec",
        "state",
        "state_version",
        "cancel_requested",
        "current_attempt_id",
        # Keep the submitted at ns component named inside the expected v6 columns
        # contract.
        "submitted_at_ns",
        "updated_at_ns",
    ),
    "job_attempts": (
        "attempt_id",
        # Keep the job id component named inside the expected v6 columns contract.
        "job_id",
        "attempt_number",
        "supervisor_instance_id",
        "state",
        "state_version",
        # Keep the result artifact id component named inside the expected v6 columns
        # contract.
        "result_artifact_id",
        "created_at_ns",
        "updated_at_ns",
    ),
    "artifact_index": (
        # Keep the artifact id component named inside the expected v6 columns contract.
        "artifact_id",
        "kind",
        "manifest_digest",
        "build_key",
        "status",
        # Keep the status reason component named inside the expected v6 columns contract.
        "status_reason",
        "indexed_at_ns",
        "verified_at_ns",
    ),
    "build_key_mapping": (
        # Keep the build key component named inside the expected v6 columns contract.
        "build_key",
        "artifact_id",
        "status",
        "first_seen_at_ns",
        "updated_at_ns",
        # Complete the expected v6 columns group only after its semantic components are
        # visible.
    ),
    "artifact_build_conflicts": ("build_key", "artifact_id", "detected_at_ns"),
    "lineage_edges": ("output_artifact_id", "input_artifact_id", "ordinal"),
    "run_index_state": ("singleton", "status", "generation"),
    "artifact_reconciliation_state": (
        "singleton",
        "status",
        "inventory_digest",
        "artifact_count",
    ),
    "run_index": (
        "artifact_id",
        "manifest_digest",
        "is_queryable",
        "logical_run_id",
        # Physical attempt identity detects a semantically stale projection row.
        "execution_attempt_id",
        "started_at_ns",
        "completed_at_ns",
    ),
    "pins": ("pin_id", "record_digest", "status", "reason", "indexed_at_ns"),
    "pin_roots": ("pin_id", "artifact_id", "ordinal"),
    # Keep the shard ledger component named inside the expected v6 columns contract.
    "shard_ledger": (
        "source_id",
        "capability_id",
        "capability_schema_version",
        "network_id",
        # Keep the position schema id component named inside the expected v6 columns
        # contract.
        "position_schema_id",
        "from_block_ordinal",
        "to_block_ordinal",
        "internal_revision",
        "artifact_id",
        # Keep the snapshot cut to block component named inside the expected v6 columns
        # contract.
        "snapshot_cut_to_block",
        "chain_finality",
        "ingestion_watermark_to_block",
        "upstream_revision",
        "source_consistency",
        # Keep the completeness component named inside the expected v6 columns contract.
        "completeness",
        "validation_status",
        "committed_at_ns",
    ),
    "shard_query_fingerprints": (
        # Keep the source id component named inside the expected v6 columns contract.
        "source_id",
        "capability_id",
        "capability_schema_version",
        "network_id",
        "position_schema_id",
        # Keep the from block ordinal component named inside the expected v6 columns
        # contract.
        "from_block_ordinal",
        "to_block_ordinal",
        "internal_revision",
        "artifact_id",
        "query_fingerprint",
        "ordinal",
        # Complete the expected v6 columns group only after its semantic components are
        # visible.
    ),
    "source_frontiers": (
        "source_id",
        "capability_id",
        "capability_schema_version",
        # Keep the network id component named inside the expected v6 columns contract.
        "network_id",
        "position_schema_id",
        "coverage_from_block_ordinal",
        "frontier_block_ordinal",
        "computed_at_ns",
        # Complete the expected v6 columns group only after its semantic components are
        # visible.
    ),
    "completion_receipts": (
        "attempt_id",
        "resolved_spec_id",
        "receipt_digest",
        # Keep the indexed at ns component named inside the expected v6 columns contract.
        "indexed_at_ns",
    ),
    "completion_receipt_outputs": (
        "attempt_id",
        "artifact_id",
        # Keep the manifest digest component named inside the expected v6 columns
        # contract.
        "manifest_digest",
        "ordinal",
    ),
    "job_events": (
        "event_id",
        # Keep the job id component named inside the expected v6 columns contract.
        "job_id",
        "attempt_id",
        "event_type",
        "state_version",
        "created_at_ns",
        # Keep the details component named inside the expected v6 columns contract.
        "details",
    ),
    "attempt_runtime": (
        "attempt_id",
        "supervisor_instance_id",
        # Keep the process id component named inside the expected v6 columns contract.
        "process_id",
        "process_start_token",
        "lane",
        "private_memory_bytes",
        "native_threads",
        # Keep the io units component named inside the expected v6 columns contract.
        "io_units",
        "registered_at_ns",
        "heartbeat_at_ns",
        "lease_expires_at_ns",
        "deadline_at_ns",
        # Keep the temporary disk bytes component named inside the expected v6 columns
        # contract.
        "temporary_disk_bytes",
        "output_disk_bytes",
    ),
    "attempt_failures": (
        "attempt_id",
        # Keep the failure kind component named inside the expected v6 columns contract.
        "failure_kind",
        "failure_code",
        "retry_scheduled",
        "retry_not_before_ns",
        "recorded_at_ns",
        # Complete the expected v6 columns group only after its semantic components are
        # visible.
    ),
    "job_retry_schedule": (
        "job_id",
        "previous_attempt_id",
        "not_before_ns",
        # Keep the created at ns component named inside the expected v6 columns contract.
        "created_at_ns",
    ),
}
_REQUIRED_V9_INDEXES: Final = frozenset(
    {
        # Pass artifact index build key idx explicitly so frozenset receives a reviewable
        # artifact index build key idx and artifact index kind status idx input in module.
        "artifact_index_build_key_idx",
        "artifact_index_kind_status_idx",
        "attempt_runtime_lease_idx",
        "job_attempts_job_idx",
        "job_events_attempt_idx",
        # Pass job events job idx explicitly so frozenset receives a reviewable artifact
        # index build key idx and artifact index kind status idx input in module.
        "job_events_job_idx",
        "job_retry_due_idx",
        "jobs_claim_order_idx",
        "jobs_list_submitted_idx",
        "jobs_state_list_submitted_idx",
        "lineage_edges_input_idx",
        "pin_roots_artifact_idx",
        "run_index_completed_idx",
        "run_index_logical_completed_idx",
        # Pass shard ledger frontier idx explicitly so frozenset receives a reviewable
        # artifact index build key idx and artifact index kind status idx input in module.
        "shard_ledger_frontier_idx",
    }
)


def connect(path: Path, *, busy_timeout_seconds: float) -> sqlite3.Connection:
    # Execute the connect workflow in explicit, reviewable steps.
    if busy_timeout_seconds <= 0:
        raise ValueError("busy_timeout_seconds must be positive")
    connection = sqlite3.connect(
        path,
        timeout=busy_timeout_seconds,
        # Pass isolation level explicitly so connect receives a reviewable path and busy
        # timeout seconds input in connect.
        isolation_level=None,
    )
    try:
        # Perform the protected connect operation before explicit failure handling.
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_seconds * 1_000)}")
        connection.execute("PRAGMA synchronous = FULL")
    except BaseException:
        # Translate the BaseException failure through the connect boundary.
        with suppress(sqlite3.Error):
            connection.close()
        raise
    return connection


def initialize(path: Path, *, busy_timeout_seconds: float) -> None:
    # ``PRAGMA journal_mode`` does not reliably honor busy_timeout when two
    # threads initialize the same new file simultaneously.  The deployment has
    # one controller process, so serialize its in-process adapter construction;
    # migration transactions still provide the cross-process fail-closed edge.
    with _INITIALIZE_LOCK:
        # Keep initialize lock active only for the bounded initialize operation.
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = connect(path, busy_timeout_seconds=busy_timeout_seconds)
        except sqlite3.DatabaseError as error:
            _raise_safe_schema_error(error)
        # Keep expected failures inside the initialize error boundary.
        try:
            # Perform the protected initialize operation before explicit failure handling.
            current_version = _read_supported_schema_version(connection)
            if current_version == LATEST_SCHEMA_VERSION:
                _validate_latest_schema(connection)
            journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                # Fail the initialize path with SQLiteSchemaError for sqlite catalog
                # requires wal journal mode when journal mode, wal and lower is true; do
                # not continue ambiguously.
                raise SQLiteSchemaError("SQLite catalog requires WAL journal mode")
            _apply_migrations(connection)
        except sqlite3.DatabaseError as error:
            _raise_safe_schema_error(error)
        finally:
            # Invoke close as a visible step within the initialize workflow.
            connection.close()


def schema_version(path: Path, *, busy_timeout_seconds: float = 5.0) -> int:
    """Return the durable schema version without mutating the database."""

    connection = connect(path, busy_timeout_seconds=busy_timeout_seconds)
    try:
        # Perform the protected schema version operation before explicit failure handling.
        row = connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return user_version")
        return int(row[0])
    finally:
        # Invoke close as a visible step within the schema version workflow.
        connection.close()


def _apply_migrations(connection: sqlite3.Connection) -> None:
    # Execute the apply migrations workflow in explicit, reviewable steps.
    current_version = _read_supported_schema_version(connection)

    for target_version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
        # Process current version and latest schema version inside the bounded apply
        # migrations loop.
        migration = _MIGRATIONS[target_version - 1]
        if target_version == 4:
            # Handle the apply migrations target_version == 4 branch as a distinct logical
            # block.
            columns = {
                str(item[1])
                for item in connection.execute("PRAGMA table_info(attempt_runtime)").fetchall()
            }
            additions = ""
            # Guard this path with 'temporary_disk_bytes' not in columns before applying
            # effects.
            if "temporary_disk_bytes" not in columns:
                additions += """
ALTER TABLE attempt_runtime
ADD COLUMN temporary_disk_bytes INTEGER NOT NULL DEFAULT 0
CHECK (temporary_disk_bytes >= 0);
"""
            if "output_disk_bytes" not in columns:
                additions += """
ALTER TABLE attempt_runtime
ADD COLUMN output_disk_bytes INTEGER NOT NULL DEFAULT 0
CHECK (output_disk_bytes >= 0);
"""
            migration = additions + migration
        # Keep expected failures inside the apply migrations error boundary.
        try:
            # Perform the protected apply migrations operation before explicit failure
            # handling.
            connection.executescript(
                f"BEGIN IMMEDIATE;\n{migration}\nPRAGMA user_version = {target_version};\nCOMMIT;"
            )
        except BaseException:
            # Translate the BaseException failure through the apply migrations boundary.
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            raise

    _validate_latest_schema(connection)


def _read_supported_schema_version(connection: sqlite3.Connection) -> int:
    # Execute the read supported schema version workflow in explicit, reviewable steps.
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise SQLiteSchemaError("SQLite did not return a schema version")
    current_version = int(row[0])
    if current_version < 0 or current_version > LATEST_SCHEMA_VERSION:
        # Fail the read supported schema version path with SQLiteSchemaError for sqlite
        # catalog schema is newer than this application supports when current version and
        # latest schema version is true; do not continue ambiguously.
        raise SQLiteSchemaError("SQLite catalog schema is newer than this application supports")
    return current_version


def _validate_latest_schema(connection: sqlite3.Connection) -> None:
    # Execute the validate latest schema workflow in explicit, reviewable steps.
    quick_check = tuple(str(row[0]).lower() for row in connection.execute("PRAGMA quick_check"))
    if quick_check != ("ok",):
        raise SQLiteSchemaError("SQLite catalog integrity verification failed")

    objects = connection.execute(
        """
        SELECT type, name, tbl_name
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        """
        # Complete fetchall only after its declared inputs are visible in validate latest
        # schema.
    ).fetchall()
    table_names = {
        str(row["name"])
        for row in objects
        if row["type"] == "table" and not str(row["name"]).startswith("sqlite_")
        # Complete the table names group only after its semantic components are visible.
    }
    if table_names != set(_EXPECTED_V9_COLUMNS):
        raise SQLiteSchemaError("SQLite catalog schema verification failed")
    for table_name, expected_columns in _EXPECTED_V9_COLUMNS.items():
        # Process expected tables inside the bounded validate-latest-schema loop.
        # loop.
        actual_columns = tuple(
            str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        )
        if actual_columns != expected_columns:
            raise SQLiteSchemaError("SQLite catalog schema verification failed")

    # Assemble index names once so the validate latest schema workflow shares one value.
    index_names = {str(row["name"]) for row in objects if row["type"] == "index"}
    if not index_names.issuperset(_REQUIRED_V9_INDEXES):
        raise SQLiteSchemaError("SQLite catalog schema verification failed")
    immutable_trigger = tuple(
        row
        # Pass row explicitly so tuple receives a reviewable trigger and jobs immutable
        # command input in validate latest schema.
        for row in objects
        if row["type"] == "trigger" and row["name"] == "jobs_immutable_command"
    )
    if len(immutable_trigger) != 1 or immutable_trigger[0]["tbl_name"] != "jobs":
        raise SQLiteSchemaError("SQLite catalog schema verification failed")

    # Mutation dirties the generation; inserts and updates also enforce row invariants.
    run_triggers = {
        str(row["name"])
        for row in objects
        if row["type"] == "trigger" and row["tbl_name"] == "run_index"
    }
    if run_triggers != {
        "run_index_dirty_after_delete",
        "run_index_dirty_after_insert",
        "run_index_immutable",
        "run_index_verified_artifact_insert",
    }:
        raise SQLiteSchemaError("SQLite catalog schema verification failed")

    # Assemble violations once so the validate latest schema workflow shares one value.
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SQLiteSchemaError("SQLite catalog foreign-key verification failed")


def _raise_safe_schema_error(error: sqlite3.DatabaseError) -> NoReturn:
    # Execute the raise safe schema error workflow in explicit, reviewable steps.
    error_code = getattr(error, "sqlite_errorcode", None)
    primary_code = error_code & 0xFF if isinstance(error_code, int) else None
    if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        raise SQLiteSchemaError("SQLite catalog integrity verification failed") from None
    raise error


# Bind all once as an explicit module-level contract.
__all__ = [
    "LATEST_SCHEMA_VERSION",
    "SQLiteSchemaError",
    "connect",
    "initialize",
    # Keep the schema version component named inside the all contract.
    "schema_version",
]
