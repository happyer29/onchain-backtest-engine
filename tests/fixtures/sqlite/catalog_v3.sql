-- Frozen pristine SQLite catalog fixture; do not derive from the latest schema.
PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;
CREATE TABLE artifact_build_conflicts (
    build_key TEXT NOT NULL CHECK (length(build_key) = 64),
    artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id),
    detected_at_ns INTEGER NOT NULL CHECK (detected_at_ns >= 0),
    PRIMARY KEY (build_key, artifact_id)
);
INSERT INTO "artifact_build_conflicts" VALUES('eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',14);
CREATE TABLE artifact_index (
    artifact_id TEXT PRIMARY KEY CHECK (length(artifact_id) = 64),
    kind TEXT NOT NULL,
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    build_key TEXT NOT NULL CHECK (length(build_key) = 64),
    status TEXT NOT NULL CHECK (status IN ('VERIFIED', 'QUARANTINED', 'INVALID')),
    status_reason TEXT,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0),
    verified_at_ns INTEGER NOT NULL CHECK (verified_at_ns >= 0)
);
INSERT INTO "artifact_index" VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','SNAPSHOT','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc','VERIFIED',NULL,10,11);
CREATE TABLE attempt_failures (
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
INSERT INTO "attempt_failures" VALUES('attempt-v3-retry','TRANSIENT','CHILD_EXITED',1,900,800);
CREATE TABLE attempt_runtime (
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
INSERT INTO "attempt_runtime" VALUES('attempt-v3-running','supervisor-v3',4242,'process-token','RUN',1048576,2,1,500,501,601,701);
CREATE TABLE build_key_mapping (
    build_key TEXT PRIMARY KEY CHECK (length(build_key) = 64),
    artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id),
    status TEXT NOT NULL CHECK (status IN ('VERIFIED', 'CONFLICT')),
    first_seen_at_ns INTEGER NOT NULL CHECK (first_seen_at_ns >= 0),
    updated_at_ns INTEGER NOT NULL CHECK (updated_at_ns >= 0)
);
INSERT INTO "build_key_mapping" VALUES('cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','VERIFIED',12,13);
CREATE TABLE completion_receipt_outputs (
    attempt_id TEXT NOT NULL REFERENCES completion_receipts(attempt_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (attempt_id, artifact_id),
    UNIQUE (attempt_id, ordinal)
);
INSERT INTO "completion_receipt_outputs" VALUES('attempt-v3-succeeded','6666666666666666666666666666666666666666666666666666666666666666','7777777777777777777777777777777777777777777777777777777777777777',0);
CREATE TABLE completion_receipts (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id),
    resolved_spec_id TEXT NOT NULL CHECK (length(resolved_spec_id) = 64),
    receipt_digest TEXT NOT NULL CHECK (length(receipt_digest) = 64),
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "completion_receipts" VALUES('attempt-v3-succeeded','b94a578ba54cdfb969f65ef650683359039940ce9caacd57c80715ca42855824','5555555555555555555555555555555555555555555555555555555555555555',18);
CREATE TABLE job_attempts (
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
INSERT INTO "job_attempts" VALUES('attempt-v3-running','job-v3-running',1,'supervisor-v3','RUNNING',2,NULL,300,400);
INSERT INTO "job_attempts" VALUES('attempt-v3-succeeded','job-v3-succeeded',1,'supervisor-v3','SUCCEEDED',3,'6666666666666666666666666666666666666666666666666666666666666666',301,401);
INSERT INTO "job_attempts" VALUES('attempt-v3-retry','job-v3-retry',1,'supervisor-v3','FAILED',3,NULL,302,402);
CREATE TABLE job_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES job_attempts(attempt_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    details BLOB,
    CHECK (details IS NULL OR length(details) <= 65536)
);
INSERT INTO "job_events" VALUES(1,'job-v3-succeeded','attempt-v3-succeeded','ATTEMPT_SUCCEEDED',3,19,NULL);
CREATE TABLE job_retry_schedule (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    previous_attempt_id TEXT NOT NULL REFERENCES job_attempts(attempt_id),
    not_before_ns INTEGER NOT NULL CHECK (not_before_ns >= 0),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);
INSERT INTO "job_retry_schedule" VALUES('job-v3-retry','attempt-v3-retry',900,800);
CREATE TABLE jobs (
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
INSERT INTO "jobs" VALUES('job-v3-queued','COMPILE_REPLAY','key-v3-queued','58198ac667cc7525f99a8f61815c78130d221aa91f7d65fa02618feaae440291',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276335C222C5C226F7264696E616C5C223A307D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A22434F4D50494C455F5245504C4159222C227061796C6F61645F646967657374223A2233306563633036386230353930666162626332646633363233346431633863613432363063376263626137623631663530613531613330313138626635663139222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2264343332663461336332313465643739323739636630626261653834336166313738653237623165393934363566343936326164613562343939353561333562222C22737065635F76657273696F6E223A317D','QUEUED',0,0,NULL,100,200);
INSERT INTO "jobs" VALUES('job-v3-running','RUN_BACKTEST','key-v3-running','26bb30958f88b38091c40e5f562c9407160ac9873897c79d3f64cfcac2f6f25c',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276335C222C5C226F7264696E616C5C223A317D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2238323166303237323239366338346664356132343764613364616138626139303361613261643432636463336465313136383337643837646466613162653335222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2264306662346433623930656539653737666163333362653831376164363135366439356536396234323835346661386262306338373231336639346431313661222C22737065635F76657273696F6E223A317D','RUNNING',2,0,'attempt-v3-running',101,201);
INSERT INTO "jobs" VALUES('job-v3-succeeded','RUN_BACKTEST','key-v3-succeeded','c84c560c5753e0918422edb68d18a16ef6aa2ae27c147472588caa6a18fd1db5',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276335C222C5C226F7264696E616C5C223A327D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2261353934633638633666626264613937316231623930313638623638323132313136363539663338353363323665316264396233333766373761363536383965222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2262393461353738626135346364666239363966363565663635303638333335393033393934306365396361616364353763383037313563613432383535383234222C22737065635F76657273696F6E223A317D','SUCCEEDED',3,0,'attempt-v3-succeeded',102,202);
INSERT INTO "jobs" VALUES('job-v3-retry','RUN_SWEEP','key-v3-retry','9134848bcbefe134e778ef248272b98b40181f472b0ce41784ab0f1aedca1c25',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276335C222C5C226F7264696E616C5C223A337D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F5357454550222C227061796C6F61645F646967657374223A2237653362656435613735316635636564393461336336303461346364643331346436303466346134663761653834346435393564323165643165393366303663222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2238653261316466343762396466343136363364316531396365656338346465646163643935336561666334376533633864303838353631383531323961663266222C22737065635F76657273696F6E223A317D','QUEUED',3,0,NULL,103,203);
CREATE TABLE lineage_edges (
    output_artifact_id TEXT NOT NULL REFERENCES artifact_index(artifact_id) ON DELETE CASCADE,
    input_artifact_id TEXT NOT NULL CHECK (length(input_artifact_id) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (output_artifact_id, input_artifact_id),
    UNIQUE (output_artifact_id, ordinal),
    CHECK (output_artifact_id <> input_artifact_id)
);
INSERT INTO "lineage_edges" VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',0);
CREATE TABLE pin_roots (
    pin_id TEXT NOT NULL REFERENCES pins(pin_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL CHECK (length(artifact_id) = 64),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (pin_id, artifact_id),
    UNIQUE (pin_id, ordinal)
);
INSERT INTO "pin_roots" VALUES('pin-v3','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0);
CREATE TABLE pins (
    pin_id TEXT PRIMARY KEY,
    record_digest TEXT NOT NULL CHECK (length(record_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'INVALID')),
    reason TEXT NOT NULL,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "pins" VALUES('pin-v3','ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff','ACTIVE','frozen fixture root',15);
CREATE TABLE shard_ledger (
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
INSERT INTO "shard_ledger" VALUES('source-fixture','swaps.v1','1',10,20,'2222222222222222222222222222222222222222222222222222222222222222','1111111111111111111111111111111111111111111111111111111111111111',20,'FINALIZED',20,'upstream-1','SNAPSHOT','PROVEN_COMPLETE','VALID',16);
CREATE TABLE shard_query_fingerprints (
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
INSERT INTO "shard_query_fingerprints" VALUES('source-fixture','swaps.v1','1',10,20,'2222222222222222222222222222222222222222222222222222222222222222','3333333333333333333333333333333333333333333333333333333333333333',0);
CREATE TABLE source_frontiers (
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
INSERT INTO "source_frontiers" VALUES('source-fixture','swaps.v1','1',10,20,17);
CREATE INDEX jobs_claim_order_idx
    ON jobs(state, cancel_requested, submitted_at_ns, job_id);
CREATE INDEX job_attempts_job_idx
    ON job_attempts(job_id, attempt_number);
CREATE TRIGGER jobs_immutable_command
BEFORE UPDATE OF command_type, idempotency_key, request_digest, resolved_spec ON jobs
BEGIN
    SELECT RAISE(ABORT, 'resolved job command is immutable');
END;
CREATE INDEX artifact_index_kind_status_idx
    ON artifact_index(kind, status, artifact_id);
CREATE INDEX artifact_index_build_key_idx
    ON artifact_index(build_key, status, artifact_id);
CREATE INDEX lineage_edges_input_idx
    ON lineage_edges(input_artifact_id, output_artifact_id);
CREATE INDEX pin_roots_artifact_idx
    ON pin_roots(artifact_id, pin_id);
CREATE INDEX shard_ledger_frontier_idx
    ON shard_ledger(
        source_id, capability_id, capability_schema_version,
        from_slot, to_slot, internal_revision
    );
CREATE INDEX job_events_job_idx
    ON job_events(job_id, event_id);
CREATE INDEX job_events_attempt_idx
    ON job_events(attempt_id, event_id);
CREATE INDEX attempt_runtime_lease_idx
    ON attempt_runtime(lease_expires_at_ns, attempt_id);
CREATE INDEX job_retry_due_idx
    ON job_retry_schedule(not_before_ns, job_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('job_events',1);
COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA user_version = 3;
