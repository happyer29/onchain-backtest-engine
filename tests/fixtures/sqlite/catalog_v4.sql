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
CREATE TABLE "attempt_failures" (
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
INSERT INTO "attempt_failures" VALUES('attempt-v4-retry','RESOURCE_EXHAUSTED','MEMORY_LIMIT_EXCEEDED',1,900,800);
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
, temporary_disk_bytes INTEGER NOT NULL DEFAULT 0
                CHECK (temporary_disk_bytes >= 0), output_disk_bytes INTEGER NOT NULL DEFAULT 0
                CHECK (output_disk_bytes >= 0));
INSERT INTO "attempt_runtime" VALUES('attempt-v4-running','supervisor-v4',4242,'process-token','RUN',1048576,2,1,500,501,601,701,8192,16384);
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
INSERT INTO "completion_receipt_outputs" VALUES('attempt-v4-succeeded','6666666666666666666666666666666666666666666666666666666666666666','7777777777777777777777777777777777777777777777777777777777777777',0);
CREATE TABLE completion_receipts (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id),
    resolved_spec_id TEXT NOT NULL CHECK (length(resolved_spec_id) = 64),
    receipt_digest TEXT NOT NULL CHECK (length(receipt_digest) = 64),
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "completion_receipts" VALUES('attempt-v4-succeeded','36f62ed077bdb8c7079725cc8f2711d0f4866a1b975aed643a9a30fe740b4314','5555555555555555555555555555555555555555555555555555555555555555',18);
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
INSERT INTO "job_attempts" VALUES('attempt-v4-running','job-v4-running',1,'supervisor-v4','RUNNING',2,NULL,300,400);
INSERT INTO "job_attempts" VALUES('attempt-v4-succeeded','job-v4-succeeded',1,'supervisor-v4','SUCCEEDED',3,'6666666666666666666666666666666666666666666666666666666666666666',301,401);
INSERT INTO "job_attempts" VALUES('attempt-v4-retry','job-v4-retry',1,'supervisor-v4','FAILED',3,NULL,302,402);
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
INSERT INTO "job_events" VALUES(1,'job-v4-succeeded','attempt-v4-succeeded','ATTEMPT_SUCCEEDED',3,19,NULL);
CREATE TABLE job_retry_schedule (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    previous_attempt_id TEXT NOT NULL REFERENCES job_attempts(attempt_id),
    not_before_ns INTEGER NOT NULL CHECK (not_before_ns >= 0),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);
INSERT INTO "job_retry_schedule" VALUES('job-v4-retry','attempt-v4-retry',900,800);
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
INSERT INTO "jobs" VALUES('job-v4-queued','COMPILE_REPLAY','key-v4-queued','653aa8b2cec36307bf760b161cde057222136a5c7d762d3be1edb4049f636fa1',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276345C222C5C226F7264696E616C5C223A307D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A22434F4D50494C455F5245504C4159222C227061796C6F61645F646967657374223A2238656536336332396165636536633635653237643932306135633938623231633462643262303530323762346263663138396566666332303930356634386165222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2263363835373332363232613262623733376538613863376462633234653061366465643962333736343662383163366364343836306637626332663664323761222C22737065635F76657273696F6E223A317D','QUEUED',0,0,NULL,100,200);
INSERT INTO "jobs" VALUES('job-v4-running','RUN_BACKTEST','key-v4-running','89b3d47ea6ee679c6221ec81688ea0909d3d5a5b5d15f4af26cb6c543013085c',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276345C222C5C226F7264696E616C5C223A317D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2231623635386636343936666264376232316236643038353738356562643638343836363833373033636261386535363931656539663735646361393365623038222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2234656237383235303462663562383865346164643238303537336433383637656566306464333033643965306338653539376332653635343035336431633438222C22737065635F76657273696F6E223A317D','RUNNING',2,0,'attempt-v4-running',101,201);
INSERT INTO "jobs" VALUES('job-v4-succeeded','RUN_BACKTEST','key-v4-succeeded','b73cf31258ef8a3c04273fe51ac22bd682fd9ec662b19073cd04873098878287',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276345C222C5C226F7264696E616C5C223A327D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2236303862656232663436663366356365306237656137323563366535323230633763346437626661656662396438343631653866333565636533383061663532222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2233366636326564303737626462386337303739373235636338663237313164306634383636613162393735616564363433613961333066653734306234333134222C22737065635F76657273696F6E223A317D','SUCCEEDED',3,0,'attempt-v4-succeeded',102,202);
INSERT INTO "jobs" VALUES('job-v4-retry','RUN_SWEEP','key-v4-retry','eb6c4b81b80dd0d0bbcfa24c6e73121b2e94687781f8847e3c2956415fce24a4',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276345C222C5C226F7264696E616C5C223A337D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F5357454550222C227061796C6F61645F646967657374223A2261636536383730333366346333656237626263316661313661323534656336383764306165346530363762646466626539666639613539633366656564663637222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2233626530346166353137323461313265386135373436643439336131653634386539386239316431396538653461323536396231623566326339613830333631222C22737065635F76657273696F6E223A317D','QUEUED',3,0,NULL,103,203);
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
INSERT INTO "pin_roots" VALUES('pin-v4','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0);
CREATE TABLE pins (
    pin_id TEXT PRIMARY KEY,
    record_digest TEXT NOT NULL CHECK (length(record_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'INVALID')),
    reason TEXT NOT NULL,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "pins" VALUES('pin-v4','ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff','ACTIVE','frozen fixture root',15);
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
PRAGMA user_version = 4;
