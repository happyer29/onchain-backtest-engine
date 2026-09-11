# Project configuration

Host configuration is stored in TOML and is not part of a run's semantic
identity. Exact strategy, execution, and ML configurations are pinned
separately inside resolved specs and artifact manifests.

## File locations

| File | Purpose | Safe to commit |
|---|---|---|
| `configs/local-16gb.toml` | Base 16 GB host profile for Linux or macOS | Yes, without secrets |
| `configs/local-32gb.toml` | Base 32 GB host profile for Linux or macOS | Yes, without secrets |
| `configs/local-windows-wsl2-16gb.toml` | Base 16 GB profile for Windows 11 through WSL2/Ubuntu | Yes, without secrets |
| `configs/local.toml` | Settings for a particular PC/server | No, gitignored |
| `configs/indexer-capabilities.example.toml` | Structural example of four Pump source streams with `UNKNOWN` evidence | Yes |
| `configs/indexer-projections.example.toml` | Consistent example of four canonical event projections | Yes |
| `configs/indexer-capabilities.local.toml` | Verified raw mapping for fixed `pumpfun-indexer-v1` | No, gitignored |
| `configs/indexer-projections.local.toml` | Canonical mapping after the installed fixed normalizer | No, gitignored |
| `.env` | Local secrets, if consumed by external loader tooling | No, gitignored |

The CLI reads `configs/local-16gb.toml` by default. For reproducible operation,
always pass the selected file explicitly:

```bash
backtest <command> --config configs/local.toml
```

The same CLI and configuration contract runs on native Linux x86_64, macOS
arm64, and Windows 11 x86_64 through WSL2 with Ubuntu x86_64. Native Win32 is
not currently supported or verified. On Windows, start with
`configs/local-windows-wsl2-16gb.toml`, run the CLI inside Ubuntu, and keep the
repository and `data_root` inside the WSL Linux filesystem. Operational paths
on `/mnt/c`, `/mnt/d`, other DrvFS mounts, or network mounts are unsupported.

Do not place passwords, tokens, or DSNs in TOML. `secret_ref` contains only the
name of an environment variable.

## `[paths]`

| Parameter | Meaning |
|---|---|
| `data_root` | Root for SQLite, immutable artifacts, runs, temporary data, and locks |

A relative path is resolved from the directory where the command starts. Set
an absolute path for another NVMe. An artifact's staging and final directories
must remain on one filesystem; otherwise atomic rename is not guaranteed.

Moving `data_root` does not change logical hashes, but do not manually copy
individual files without their manifests and verification. Use the backup
protocol for durability.

On Windows/WSL2, a supported relative setting such as `data_root = "var"`
resolves inside the WSL repository. An absolute path must also be a Linux path
inside the WSL filesystem, not a `C:\...` path or `/mnt/c/...` translation.

## `[resources]`

| Parameter | Meaning |
|---|---|
| `max_aggregate_child_memory_mb` | Aggregate private-memory ceiling for all child processes |
| `max_builder_memory_mb` | Internal memory limit for a builder/analytical operation |
| `builder_peak_private_memory_mb` | Conservative admission estimate for peak builder RSS |
| `run_peak_private_memory_mb` | Admission estimate for peak private RSS of one run |
| `max_parallel_runs` | Maximum independent run processes after admission |
| `tmp_quota_gb` | Aggregate quota for temporary data |
| `max_run_tmp_gb` | Temporary quota for one run attempt |
| `max_run_output_gb` | Maximum output for one run attempt |
| `disk_low_watermark_gb` | Free-space boundary below which a builder does not start |
| `disk_emergency_watermark_gb` | Emergency boundary for stopping builders |
| `native_threads_per_process` | Native threads for one child |
| `memory_safety_reserve_mb` | RAM kept by admission as a safety reserve |
| `page_cache_floor_mb` | Reserve for OS page cache/mmap |
| `host_staging_output_reserve_mb` | Reserve for host-level staging/output peaks |
| `fixed_shared_overhead_mb` | Measured fixed/shared host overhead |
| `memory_breach_samples` | Consecutive memory samples before breach action |
| `swap_activity_samples` | Consecutive swap samples before breach action |

Built-in checks require:

- every limit to be a positive integer;
- one child's peak not to exceed the aggregate ceiling;
- `run_peak * max_parallel_runs` not to exceed the aggregate ceiling;
- builder peak to exceed its internal memory limit;
- the emergency watermark not to exceed the low watermark;
- parallel temporary demand to fit within `tmp_quota_gb`.

Profile values are conservative starting limits, not a speed promise. Adjust
them only after measuring private RSS, page faults, swap, and I/O. Zero
available child budget does not prevent the UI from starting, but heavy jobs
remain queued until safe capacity is available.

## `[replay]`

| Parameter | Meaning |
|---|---|
| `backend` | Physical execution backend |
| `batch_rows` | Rows in one bounded reader batch |
| `readahead` | Number of bounded read-ahead batches |
| `output_buffer_rows` | Audit/result output buffer size |
| `threads` | Native threads for the run process |

Supported backend values:

- `reference-python-v1` — general readable reference path;
- `numpy-mmap-first-swap-exact-v1` — narrow optimized exact path only for the
  compatible FirstSwap + constant-product + static-risk surface;
- `reference-pumpfun-sniping-v1` — readable Pump.fun Sniping oracle for
  canonical Parquet or ReplayPack;
- `numpy-mmap-pumpfun-sniping-v1` — dedicated Pump.fun Sniping SoA/mmap path
  that requires an exact ReplayPack and allowlisted semantic closure.

`[replay].threads` must equal `[resources].native_threads_per_process`.
Batch/readahead/backend are physical settings and do not change
`logical_run_id`, but are recorded in physical-attempt provenance.

## `[retention]`

| Parameter | Meaning |
|---|---|
| `minimum_artifact_age_seconds` | Minimum age of a GC candidate |
| `trash_grace_seconds` | Delay between moving to trash and physical deletion |
| `maximum_sweep_gb` | Maximum bytes in one GC sweep |

GC always remains reachability-based. Age does not permit deletion of a
pinned, referenced, leased, or active artifact. Run `backtest gc` first as a
dry run, then use `backtest gc --execute` only after validating the plan.

## `[backup]`

This section is optional:

```toml
[backup]
target_root = "/path/on-another-device/backtest-backup"
restore_verify_parent = "/path/on-another-device/backtest-restore-drills"
allow_same_device_for_drill = false
target_encryption_verified = true
```

The paths above are examples. On Linux, macOS, and Ubuntu under WSL2, replace
them with paths on a different physical device or host that are mounted into
the active runtime. A second directory on the same NVMe is not a backup. On
Windows/WSL2, do not use DrvFS as the operational `data_root`; an explicitly
verified external target may be used only when it satisfies the different-
device/host and encryption contract.

| Parameter | Meaning |
|---|---|
| `target_root` | Root of backup generations on another physical device/host |
| `restore_verify_parent` | Separate parent for empty-directory restore drills |
| `allow_same_device_for_drill` | Allow the same device only for a drill, not a backup claim |
| `target_encryption_verified` | Explicit confirmation that the external target is encrypted |

`target_root` and `restore_verify_parent` must be set together and must not
overlap.

## `[planning]`

| Parameter | Meaning |
|---|---|
| `max_remote_gb` | Host ceiling for remote bytes in one dataset request |
| `max_local_gb` | Host ceiling for expected local dataset output |
| `max_days` | Maximum requested day range |
| `staging_reserve_gb` | Required free staging reserve |
| `max_total_blocks` | Maximum aggregate width of capability extraction ranges in block ordinals |
| `max_total_shards` | Maximum shards in a plan |
| `max_shard_blocks` | Maximum width of one half-open shard in block ordinals |
| `max_query_execution_seconds` | ClickHouse execution-time ceiling |
| `max_query_memory_mb` | ClickHouse query-memory ceiling |
| `max_query_result_rows` | Row ceiling for one query |

A request/API may only narrow these ceilings, never raise them. A remote
estimate remains `UNKNOWN` unless a verified estimator is configured; do not
rename that state to zero cost.

Aggregate capability width counts each requested stream: launches use the
decision range, while clock/trade/lifecycle use the evidence range.
`max_total_blocks` must cover their sum. This host-admission ceiling is not
evidence of source fidelity, the size of one query, or the number of unique
blocks.

There is no separate TOML section for bounded source evidence.
`inspect-source` reads `max_query_execution_seconds`, `max_query_memory_mb`,
and `max_query_result_rows` from this host profile. Fixed composition splits a
requested evidence range internally into contiguous subshards no wider than
4096 blocks; this need not and must not be described manually in TOML. The
adapter applies stricter hard caps to each internal query: at most 60 seconds,
512 MiB memory, 100000 result rows, 64 MiB result bytes, 2000000 read rows, and
1 GiB read bytes, with one thread. Configuration cannot raise these limits.

## `[control]`

| Parameter | Meaning |
|---|---|
| `host` | Bind address: only `127.0.0.1`, `::1`, or `localhost` |
| `port` | Local TCP port `1..65535` |
| `progress_interval_ms` | Minimum coalesced-progress interval |
| `max_request_mb` | Hard HTTP request-body limit |
| `secure_cookie` | Add the `Secure` cookie flag behind an HTTPS proxy |

Current checked-in profiles use different ports: 16 GB uses `8081`, while
32 GB uses `8080`. The selected local TOML is the source of truth for the
address. The Windows/WSL2 profile uses the same loopback-only control contract;
open the resulting localhost URL from a browser on the Windows host.

Direct binding to `0.0.0.0` is prohibited. For access from another device,
keep the API on loopback and use an authenticated TLS reverse proxy or VPN/SSH
tunnel. Set `secure_cookie = true` with HTTPS.

The localhost UI has no login form: the OS-user boundary and a random session
cookie provide the base protection. A Basic Auth prompt usually means another
application already owns the port.

## `[source]`

| Parameter | Meaning |
|---|---|
| `source_id` | Stable logical indexer name |
| `host` | Hostname/IP without URL scheme or path |
| `port` | ClickHouse HTTP/HTTPS port |
| `database` | Default database |
| `username` | Read-only user |
| `secret_ref` | Name of the environment variable containing the password |
| `capabilities_file` | Secret-free raw capability mapping; for this indexer, an exact fixed-profile declaration |
| `projections_file` | Canonical projection mapping after the installed normalizer; required for prepare |
| `secure` | Use TLS and certificate verification |
| `verified_private_tunnel` | Explicitly verified private transport for a non-loopback endpoint |
| `allow_insecure_remote_http` | Explicitly accept the risk of direct plaintext HTTP to a non-loopback read-only source |

Example:

```toml
[source]
source_id = "research-indexer"
host = "127.0.0.1"
port = 18123
database = "default"
username = "readonly"
secret_ref = "BACKTEST_INDEXER_PASSWORD"
capabilities_file = "configs/indexer-capabilities.local.toml"
projections_file = "configs/indexer-projections.local.toml"
secure = false
verified_private_tunnel = false
allow_insecure_remote_http = false
```

Here, `127.0.0.1:18123` may be the local end of an SSH tunnel. Endpoint,
username, and secret never enter run/artifact IDs; the password must not appear
in configuration, query IDs, logs, exceptions, or manifests.

For metadata-only `inspect-source`, `capabilities_file` is sufficient. Bounded
exact inspection also requires the installed projection/normalizer composition
because the receipt binds query, normalizer, and projector digests.
`prepare-dataset` requires both settings. You may open the Web UI without them,
but doing so does not create source admission.

The secure default is `allow_insecure_remote_http = false`. For a remote
source, choose one transport mode:

- `secure = true` with verified TLS;
- `verified_private_tunnel = true` for authenticated VPN/SSH transport to a
  non-loopback endpoint, or an ordinary loopback endpoint of a local SSH
  tunnel;
- only when neither is possible, direct non-loopback HTTP with
  `secure = false`, `verified_private_tunnel = false`, and an explicit
  `allow_insecure_remote_http = true`.

The last option provides no protection: an intermediary may intercept, read,
or alter the password, queries, and results. Before a source-facing operation,
runtime must emit a warning without the endpoint or credential. The opt-in is
mutually exclusive with `secure = true` and `verified_private_tunnel = true`,
and is unnecessary and rejected on loopback. It applies only to read-only
`inspect-source`, optional estimates, and `prepare-dataset`; the Control API
remains loopback-only. This operational host setting does not enter
run/artifact identity and does not raise fidelity, finality, completeness, or
consistency.

### Copy Buy source selection

Copy Buy preparation uses the same source transport and commands, with an
explicit `[source.copy_selection]` in your ignored local configuration. It
selects signer-bearing evidence independently of Sniping. Replace every
placeholder below with the exact intended selection before loading it:

```toml
[source.copy_selection]
signing_wallets = ["<base58-signing-wallet>"]

[source.copy_selection.decision_range]
network_id = "solana:<complete-genesis-hash>"
position_schema_id = "block32-transaction32-v1"
from_block_ordinal = 100
to_block_ordinal = 200

[source.copy_selection.history_range]
network_id = "solana:<complete-genesis-hash>"
position_schema_id = "block32-transaction32-v1"
from_block_ordinal = 50
to_block_ordinal = 200
```

The small block numbers above describe the range relationship only; they are
not an admitted source cut. Supply 1–128 sorted, unique canonical Solana
wallets. History starts no later than the decision range and ends at the same
exclusive block, under the identical network/position schema. It provides the
bounded creation/initial-state lookback. The evidence range must also prove the
right settlement tail for all four permitted sell attempts.

`inspect-source`, `plan-dataset` and `prepare-dataset` remain the command names.
Copy-only receipt v3, inspection v6, plan v5 and DatasetSpec v6 pin the selection
and coverage. Missing old creation, incomplete market history, a different
wallet selection or insufficient settlement evidence fails closed. An existing
Sniping snapshot is not silently reinterpreted as a Copy dataset. The selected
wallets and source cut are semantic inputs; source endpoints and credentials
remain operational configuration.

### Capability mapping

The capability file describes transport/source schema, not protocol math:

- a versioned format/schema;
- one `NetworkId` of the form `family:immutable-chain-reference` and one
  `PositionSchemaId` for the whole mapping;
- logical capability ID and protocol version;
- source database/table;
- logical-to-physical columns;
- an authoritative logical `block_ordinal` column; the physical Solana `slot`
  remains only on the right side of the adapter mapping;
- mandatory columns;
- a proven total/keyset key and `order_by`, or an explicit absence of them;
- separately proven identity/order/state/fees/finality/completeness/
  consistency fidelity;
- an optional proven-safe UTC pruning superset.

For `BLOCK_CLOCK`, the normative logical field is named `transaction_count`.
The physical source column may be named `tx_count`, but that is only the right
side of the adapter mapping and does not prove that the count includes
successful, failed, and vote transactions.

Do not set `EXACT`, `COMPLETE_TO_WATERMARK`, `FINALIZED`, or a separate Pump
proof merely because of a column name. `inspect-source` records live
metadata/fingerprint, but ordinary local schema validation does not raise
upstream fidelity. The checked-in example intentionally remains `UNKNOWN` and
is not production evidence.

Every `[capabilities.proofs]` field in static TOML must be `UNKNOWN`. `PROVEN`
and `REFUTED` are generated bounded-inspection results, not operator assertions;
the configuration parser rejects them.

For this adapter, the local mapping must match the installed
`pumpfun-indexer-v1` profile exactly: four raw capabilities use
`protocol_version = "pumpfun-indexer-v1-raw"` and
`capability_schema_version = "pumpfun-indexer-v1-raw-v1"`. These are internal
physical version tokens. After fixed SQL and the Pump-owned
`pumpfun-indexer-v1-live-normalizer-v2` normalizer, inspection publishes
different logical versions:

| Stream | Logical protocol | Logical schema |
|---|---|---|
| `BLOCK_CLOCK` | `solana-block-clock-v1` | `solana-block-clock-normalized-v1` |
| `TOKEN_LAUNCH` | `pump-program-static-fee-v1` | `pumpfun-token-launch-normalized-v2` |
| `PUMP_CURVE_TRADE` | `pump-program-static-fee-v1` | `pumpfun-curve-trade-normalized-v2` |
| `PUMP_CURVE_LIFECYCLE` | `pump-program-static-fee-v1` | `pumpfun-curve-lifecycle-normalized-v2` |

Plan requirements use logical versions from the inspection artifact, not raw
tokens from local TOML.

### Bounded source evidence

The evidence range is a parameter of one inspection invocation, not a
long-lived `[source]` setting:

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block <inclusive_block_ordinal> \
  --evidence-to-block <exclusive_block_ordinal> \
  --decision-from-block <inclusive_target_block_ordinal> \
  --decision-to-block <exclusive_target_block_ordinal>
```

Both evidence boundaries are supplied together and form a typed half-open
`BlockRange` with NetworkId/PositionSchemaId from the capability mapping. Both
decision boundaries are likewise valid only as a pair, require an evidence
range, and must lie inside it. The decision range defines the target/universe
window; the evidence range additionally covers capability-specific settlement
tail. If decision flags are omitted, the entire evidence range becomes the
decision range.

An illustrative example uses decision range `[1000000,1004096)` and a
4096-block tail. These coordinates do not identify an admitted dataset;
replace them with the bounded range you intend to inspect.

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block 1000000 \
  --evidence-to-block 1008192 \
  --decision-from-block 1000000 \
  --decision-to-block 1004096
```

This example corresponds to a plan with `requested_days = 1`, maximum sell delay
of 200 transactions, and `maximum_tail_blocks = 4096`. `requested_days`
remains a plan budget operand, not a way to convert UTC dates automatically
into block ordinals.

The composition layer divides a requested cut into internal subshards of at
most 4096 blocks. The launch query covers only the decision range; the other
three streams cover the complete evidence range. The command publishes a
`source-inspection/v5` with four embedded `bounded-source-evidence/v2`
receipts: one aggregate receipt per capability. Each receipt binds all internal
query fingerprints, exact ranges, mapping/query/normalizer/projector digests,
aggregate result digest, and bounded observations.

Local TOML does not grant admission. The fixed evaluator generates `PROVEN`
only after contiguous block/sentinel coverage, global transaction clock,
launch universe, bundled-buy placeholder, curve transitions, fee rounding,
and lifecycle order all pass for one cut. Malformed, missing, conflicting, or
unknown data fails closed before a valid inspection is published. The bundled
placeholder counts only a later successful `BUY` with the same signature/mint
pair after create in the same transaction. A successful `SELL` in that
transaction is applied to the curve atomically but is not classified as a
bundled buy; `bundled_buys_count` is not used as proof.

A raw `pumpfun_v2_swaps` row does not contain separate protocol/creator fee
columns. The fixed normalizer derives 95/30 components from the exact curve SOL
leg under the pinned effective-dated integer formula/profile. The receipt binds
the formula/profile and normalizer digest as derived-not-observed provenance;
TOML cannot present those values as observed source transfers.

Every range requires its own successful checks. Missing transitions or
inconsistent state produce a typed failure, such as
`CURVE_TRANSITION_MISMATCH`, before an inspection is published. A TOML flag or
manual `PROVEN` cannot repair that source failure.

Evidence v1, source inspection v1–v4, dataset plan v1–v3, and DatasetSpec
v1–v4 cannot be reused under this contract; new preparation is required.

Choose the evidence range with the DatasetSpec v5 settlement requirement in
mind. Its `maximum_tail_blocks` is a hard cap for one-shot extraction, not
proof of sufficiency. The planner rejects a requested tail above the cap, and
`prepare-dataset` checks the actual maximum settlement path before publishing
the root. The exact request structure appears in
[getting-started.md](getting-started.md).

### Projection mapping

The projection file binds an already normalized capability to a canonical
event kind and versioned protocol-payload schema. It does not describe physical
ClickHouse expressions and does not replace the fixed normalizer. The current
Pump.fun pair uses:

| Capability stream | `event_kind` | Payload schema |
|---|---|---|
| `BLOCK_CLOCK` | `BLOCK` | Not required |
| `TOKEN_LAUNCH` | `TOKEN_LAUNCH` | `pump-launch-state-v1` |
| `PUMP_CURVE_TRADE` | `VENUE_TRADE` | `pump-trade-state-v1` |
| `PUMP_CURVE_LIFECYCLE` | `VENUE_LIFECYCLE` | `pump-lifecycle-state-v1` |

The complete consistent example pair is in
[`indexer-capabilities.example.toml`](../configs/indexer-capabilities.example.toml)
and
[`indexer-projections.example.toml`](../configs/indexer-projections.example.toml).
It demonstrates all four stream structures but intentionally contains
`UNKNOWN` evidence. For example, the launch declaration is:

```toml
[[projections]]
capability_id = "pumpfun.token-launch.v2"
event_kind = "TOKEN_LAUNCH"
protocol_payload_schema_id = "pump-launch-state-v1"

[projections.columns]
block_ordinal = "block_ordinal"
transaction_index = "transaction_index"
event_index = "event_index"
signature = "signature"
transaction_succeeded = "transaction_succeeded"
asset = "mint"
developer = "creator"
creation_user = "creation_user"
venue = "venue"
quote_asset = "quote_asset"
```

The right side of each pair is a logical column from the capability mapping,
not necessarily the physical ClickHouse column name. The example lists all
other required state and lifecycle mappings. The Pump projector requires
exactly one stream of each kind, the successful-launch field, and proven
within-transaction order; missing or unsupported semantics fail closed.

## Secrets and shell environment

Example for the current Bash session on Linux, macOS, or Ubuntu under WSL2:

```bash
export BACKTEST_INDEXER_PASSWORD='your-indexer-secret'
backtest inspect-source --config configs/local.toml
```

If you use `.env`, load it through external shell/tooling before starting the
application. The project must not serialize `.env` into artifacts or a backup
export. Do not pass the password as a CLI argument because it enters process
history. On Windows, set the variable inside the WSL Ubuntu shell where the
runtime executes; do not put the secret in checked-in PowerShell or TOML files.

---

**Language:** English · [Русский](configuration.ru.md)
