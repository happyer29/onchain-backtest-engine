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
INSERT INTO "completion_receipt_outputs" VALUES('attempt-v2-succeeded','6666666666666666666666666666666666666666666666666666666666666666','7777777777777777777777777777777777777777777777777777777777777777',0);
CREATE TABLE completion_receipts (
    attempt_id TEXT PRIMARY KEY REFERENCES job_attempts(attempt_id),
    resolved_spec_id TEXT NOT NULL CHECK (length(resolved_spec_id) = 64),
    receipt_digest TEXT NOT NULL CHECK (length(receipt_digest) = 64),
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "completion_receipts" VALUES('attempt-v2-succeeded','d510b2f9fc13ae778fdff25ec92fdc77e3e3fe2dfa577995a080297d574166fb','5555555555555555555555555555555555555555555555555555555555555555',18);
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
INSERT INTO "job_attempts" VALUES('attempt-v2-running','job-v2-running',1,'supervisor-v2','RUNNING',2,NULL,300,400);
INSERT INTO "job_attempts" VALUES('attempt-v2-succeeded','job-v2-succeeded',1,'supervisor-v2','SUCCEEDED',3,'6666666666666666666666666666666666666666666666666666666666666666',301,401);
INSERT INTO "job_attempts" VALUES('attempt-v2-retry','job-v2-retry',1,'supervisor-v2','FAILED',3,NULL,302,402);
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
INSERT INTO "job_events" VALUES(1,'job-v2-succeeded','attempt-v2-succeeded','ATTEMPT_SUCCEEDED',3,19,NULL);
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
INSERT INTO "jobs" VALUES('job-v2-queued','COMPILE_REPLAY','key-v2-queued','3086e68cbfb2c83e5b9588244e8736d080008e388135bd0f3dccb65b407c7e7a',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276325C222C5C226F7264696E616C5C223A307D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A22434F4D50494C455F5245504C4159222C227061796C6F61645F646967657374223A2236323737356434643934356239396566623533356666653236663836326435666531633064333561353561393133376539346665396166386530623866326665222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2261313731333433653432396531353133316439383933643436353766316138393164353637306330343432376366343238303161373839646138376332633166222C22737065635F76657273696F6E223A317D','QUEUED',0,0,NULL,100,200);
INSERT INTO "jobs" VALUES('job-v2-running','RUN_BACKTEST','key-v2-running','5e143b7e9cf1bda910f51a6614858ddbb44c6e0840cd61c1aaa49c5d668cd46a',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276325C222C5C226F7264696E616C5C223A317D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2235623566663133313637376661323031323533323139323864373537663435303639383734656633306337303036656565616136373763306438613239383133222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2238366438653036613133333735356534323738346136386266626634343538383238616234303863633162353462356662666437613530666164313133306532222C22737065635F76657273696F6E223A317D','RUNNING',2,0,'attempt-v2-running',101,201);
INSERT INTO "jobs" VALUES('job-v2-succeeded','RUN_BACKTEST','key-v2-succeeded','5ef24038cb1b0cc39a7800d02dede08b8bda922e5c3aaf399ba8cc23d13bab79',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276325C222C5C226F7264696E616C5C223A327D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F4241434B54455354222C227061796C6F61645F646967657374223A2263383439346337393466373635363735346164336437663532633661303230613632633662623139346232373336326466373032373661626138336263316430222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2264353130623266396663313361653737386664666632356563393266646337376533653366653264666135373739393561303830323937643537343136366662222C22737065635F76657273696F6E223A317D','SUCCEEDED',3,0,'attempt-v2-succeeded',102,202);
INSERT INTO "jobs" VALUES('job-v2-retry','RUN_SWEEP','key-v2-retry','5e2877486398963cf869bb262473a5103d711013f903492aae9f7c3d98e7508a',X'7B2263616E6F6E6963616C5F7061796C6F6164223A227B5C22666978747572655C223A5C2276325C222C5C226F7264696E616C5C223A337D222C22696E7075745F61727469666163745F696473223A5B5D2C226A6F625F74797065223A2252554E5F5357454550222C227061796C6F61645F646967657374223A2263393934656237373762393437386363663261303536353732663265623434393266383737313039333432306238313637666261373838323034396535353464222C22736368656D615F76657273696F6E223A322C22737065635F6964223A2230303332343265626464303638353738663436303333393132316435386464396234353063383530323138623836303861663434346565666639613866363462222C22737065635F76657273696F6E223A317D','QUEUED',3,0,NULL,103,203);
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
INSERT INTO "pin_roots" VALUES('pin-v2','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0);
CREATE TABLE pins (
    pin_id TEXT PRIMARY KEY,
    record_digest TEXT NOT NULL CHECK (length(record_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'INVALID')),
    reason TEXT NOT NULL,
    indexed_at_ns INTEGER NOT NULL CHECK (indexed_at_ns >= 0)
);
INSERT INTO "pins" VALUES('pin-v2','ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff','ACTIVE','frozen fixture root',15);
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
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('job_events',1);
COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;
