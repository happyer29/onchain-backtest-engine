# CLI and workflows

The entry point is installed from `pyproject.toml` as `backtest`. The current
source of truth for syntax in a particular version is:

```bash
backtest --help
backtest <command> --help
```

Examples start from the repository root and explicitly use
`configs/local.toml`. Replace symbolic values with the exact inputs for your
source and dataset.

## Core concepts

### Exact IDs

Commands do not accept aliases such as `latest` at the execution boundary.
They normally use:

- `artifact_id` — exact committed artifact;
- `dataset_revision_id` — logical dataset plus exact source boundaries;
- `snapshot_id` — exact root snapshot;
- `replay_pack_id` — exact derived mmap pack;
- `delivery_schedule_id` — optional exact materialized observation stream;
- `run_artifact_id` — exact committed `successful-run/v3` artifact;
- `logical_run_id` — semantic experiment identity;
- `execution_attempt_id` — a particular physical attempt;
- `job_id` — operational queue record.

Obtain an ID from the JSON response of the preceding command or from a verified
manifest. A file path is not a substitute for a content ID.

### JSON inputs

Heavy commands accept typed JSON files:

- `plan-dataset`/`prepare-dataset` — versioned dataset plan request;
- `resolve-run` — closed typed RunSpecDraft, including the separate
  `pumpfun-sniping-run-draft/v3` with required `execution_mode`;
- `run` — exact ResolvedRunSpec;
- `sweep` — exact canonical ResolvedSweepSpec;
- ML commands — the corresponding resolved typed ML command.

Unknown fields, unresolved aliases, incorrect IDs, and incompatible closures
are rejected before child execution. Forms are easier to create through the
Web UI; the UI intentionally has no generic JSON editor.

Legacy Sniping draft v2 is not reinterpreted with a default mode: it returns
`RERESOLVE_REQUIRED`. Create and resolve a v3 draft instead.

## Source and dataset

| Command | Input | Result |
|---|---|---|
| `inspect-source` | Host config + capability TOML; optional bounded evidence + decision ranges | Committed `source-inspection/v5` artifact |
| `plan-dataset REQUEST.json` | Requirements, range, budget, inspection ID | Dry-run selective plan, without download |
| `prepare-dataset REQUEST.json` | The same plan request + projection config | Canonical distributions and snapshot |

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml

backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block <inclusive_block_ordinal> \
  --evidence-to-block <exclusive_block_ordinal> \
  --decision-from-block <inclusive_target_block_ordinal> \
  --decision-to-block <exclusive_target_block_ordinal>

backtest plan-dataset plan.json \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml

backtest prepare-dataset plan.json \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml
```

Only the source-facing path uses the network. A core request contains an
immutable `NetworkId`, `PositionSchemaId`, and typed half-open `BlockRange`;
only the Solana source adapter maps a block ordinal to physical `slot`.
Extraction is always bounded, with explicit columns and hard query limits.

Without evidence flags, the command performs metadata-only inspection. Both
evidence boundaries are required together. Decision boundaries likewise form
a pair, require an evidence range, and must lie inside it. If decision flags
are omitted, the entire evidence range is treated as the decision range; with
a separate settlement tail this is normally wrong because launches in the tail
must not become targets.

One external cut may be much wider than 4096 blocks. Fixed
`pumpfun-indexer-v1` composition divides it into contiguous internal subshards
no wider than 4096 blocks. The launch stream is read only over the decision
range, while the other three streams use the complete evidence range.
`[planning]` supplies requested query ceilings, and the adapter applies
stricter hard caps to each internal query: at most 60 seconds, 512 MiB memory,
100000 result rows, 64 MiB result bytes, 2000000 read rows, and 1 GiB read
bytes, with one thread.

The bounded pass reads metadata/schema first, then runs fixed read-only
streaming queries and publishes four secret-free
`bounded-source-evidence/v2` receipts inside the inspection — one aggregate
receipt per capability, not per subshard. The response exposes `artifact_id`,
`evidence_receipt_ids`, per-capability proof statuses, and `cut_evidence`.
Receipts bind exact source/mapping/query/normalizer/projector contracts,
evidence + decision ranges, every query fingerprint, aggregate result digest,
and bounded observations, but contain no raw rows or credentials.

To inspect a decision range with a separate settlement tail, substitute your
selected block ordinals in this command template:

```text
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block BLOCK_FROM \
  --evidence-to-block EVIDENCE_BLOCK_TO \
  --decision-from-block BLOCK_FROM \
  --decision-to-block DECISION_BLOCK_TO
```

`BLOCK_FROM`, `DECISION_BLOCK_TO`, and `EVIDENCE_BLOCK_TO` are placeholders
for integer block ordinals. The upper bounds are exclusive. The evidence
range must cover the entire decision range and the settlement tail required
by the dataset's declared transaction and duration limits.

Set `requested_days`, `maximum_followup_delay_transactions`,
`maximum_tail_blocks`, and the local `[planning]` ceilings for the selected
range. The full plan schema appears in [getting-started.md](getting-started.md).
A wider query budget does not increase source fidelity. Changing a range
requires fresh bounded evidence; a missing curve transition produces
`CURVE_TRANSITION_MISMATCH` before inspection publication.

The bounded evidence range is currently available specifically through the
CLI. HTTP `POST /api/v1/sources/{source_id}/inspect` performs metadata-only
inspection and is not a hidden route for obtaining receipts.

For Pump.fun Sniping, the inspection must contain one consistent cut of four
streams:

| Stream | Canonical event | Requirement |
|---|---|---|
| `BLOCK_CLOCK` | `BLOCK` | Block time/hash and complete `transaction_count`, including successful/failed/vote |
| `TOKEN_LAUNCH` | `TOKEN_LAUNCH` | Exact transaction/instruction position, successful creation, immutable creator, and creation-time state |
| `PUMP_CURVE_TRADE` | `VENUE_TRADE` | Direction, atomic amounts, complete after-state, and fee components |
| `PUMP_CURVE_LIFECYCLE` | `VENUE_LIFECYCLE` | Completion/migration coverage |

Fixed profile `pumpfun-indexer-v1` and normalizer
`pumpfun-indexer-v1-live-normalizer-v2` publish these logical contracts:

| Stream | `protocol_version` | `schema_version` |
|---|---|---|
| `BLOCK_CLOCK` | `solana-block-clock-v1` | `solana-block-clock-normalized-v1` |
| `TOKEN_LAUNCH` | `pump-program-static-fee-v1` | `pumpfun-token-launch-normalized-v2` |
| `PUMP_CURVE_TRADE` | `pump-program-static-fee-v1` | `pumpfun-curve-trade-normalized-v2` |
| `PUMP_CURVE_LIFECYCLE` | `pump-program-static-fee-v1` | `pumpfun-curve-lifecycle-normalized-v2` |

Read these strings from the inspection artifact. Do not replace them with raw
version tokens from TOML or introduce them manually as aliases.

Checked-in mappings have `UNKNOWN` proofs and are only secret-free structural
examples. They do not admit a live Sniping dataset. Evidence v1, source
inspection v1–v4, dataset plan v1–v3, and DatasetSpec v1–v4 are rejected with
`REPREPARE_REQUIRED`; there is no implicit Solana default or in-place migration.

The canonical prepared contract uses `backtest.dataset-plan/v4` and embedded
DatasetSpec v5. For Sniping, one `DataRequirement` must specify
`global-transaction-duration-roundtrip/v1`: `maximum_tail_blocks` defines a
hard bounded extraction cap, while `maximum_followup_delay_transactions`
defines the greatest sell latency that this dataset permits. The planner
extends only settlement streams exactly to the cap and rejects a caller tail
above it. Before snapshot-root publication, the validator checks the actual
`+500`, `+2s`, and maximum follow-up path for every launch. Plan v1–v3 and
DatasetSpec v1–v4 are not migrated in place and return `REPREPARE_REQUIRED`.
The complete JSON example is in [getting-started.md](getting-started.md).

Static capability TOML must keep every generated proof field set to `UNKNOWN`;
the parser rejects manual `PROVEN` or `REFUTED`. Local mappings only enable
exact fixed-profile validation. A new range or another evidence operand
requires a newly generated bounded pass; an unchanged exact inspection
artifact may be reused for the same closure. The fixed evaluator publishes
`PROVEN` only when block/sentinel, global transaction clock,
launch-classification, bundled-buy classification, curve transition, fee
rounding, and terminal lifecycle checks all pass for one cut. The classifier
uses a later successful buy with the same signature + mint in the
same transaction; it does not trust `bundled_buys_count`. Any
unknown/conflict/gap produces a typed rejection before planner/engine mutation.

## Replay and run resolution

| Command | Input | Result |
|---|---|---|
| `compile-replay SNAPSHOT_ID` | Verified snapshot | Rebuildable mmap ReplayPack |
| `compile-delivery-schedule RESOLVED.json` | ResolvedRunSpec with ReplayPack | Optional materialized delivery stream |
| `resolve-run DRAFT.json` | Draft + exact local IDs | Immutable ResolvedRunSpec JSON |

```bash
backtest compile-replay <snapshot_id> --config configs/local.toml

backtest resolve-run run-draft.json \
  --config configs/local.toml > resolved-run.json

backtest compile-delivery-schedule resolved-run.json \
  --config configs/local.toml
```

DeliverySchedule is useful only for a frequently repeated identical
latency/clock policy. Dynamic and materialized paths must produce one scheduler
result. To use the result, first resolve the source draft with an exact
`replay_pack_id` and `delivery_schedule_id: null`; compile the schedule; then
put the exact returned ID into the source draft and resolve it again. Do not
edit a `ResolvedRunSpec` manually. A schedule is prohibited without ReplayPack;
the resolver checks its build key, clock/latency/scheduler semantics, root seed,
runtime lock, NetworkId/PositionSchemaId, and decision range. A schedule is a
physical fast path: `logical_run_id` remains unchanged while attempt provenance
changes.

For Sniping, a schedule materializes post-transaction-group observation
delivery. Fixed `+500` buy landing and `+2s`/separate sell-transaction latency
remain dynamic order/timer semantics and are not embedded in the generic
ReplayPack.

## Pump.fun Sniping run contract

The current discovery command returns the exact executable v3 DTO shape and
fixed semantics:

```bash
backtest describe-run-contract pumpfun-sniping-run-draft/v3 \
  --config configs/local.toml
```

Editable strict-draft fields:

- exact `dataset_revision_id`, `snapshot_id`, optional `replay_pack_id`, and
  optional `delivery_schedule_id`;
- initial SOL and gross buy budget as decimal strings;
- separate buy/sell slippage bps and positive `sell_delay_transactions`;
- `pumpfun-solana-wallet-account-profile/v2` with initial UVA state, effective
  interval, and three schema-addressed account costs;
- an effective-dated Pump fee profile;
- separate effective-dated Solana buy/sell fee profiles;
- required closed-enum `execution_mode`, exactly `EXOGENOUS_REPLAY` or
  `EXOGENOUS_VIRTUAL_SETTLEMENT`;
- root seed as an unsigned decimal string.

The resolver, not the UI, adds the immutable 600-second developer cooldown,
buy `+500` global Solana transactions, sell decision `+2s`, SOL-only, sell-all,
and the mode-specific settlement policy. Do not add these values as custom
nullable fields. Both supported modes use
the causal historical curve and never mutate it or recompute external trades.
The virtual mode relaxes only sell real-SOL solvency: a successful sell records
venue-funded plus explicit synthetic-funded gross output. It does not relax
buy real-token availability, lifecycle, slippage, fee, account, or migration
checks, and its synthetic proceeds are not evidence of on-chain executability.
The complete JSON walkthrough is in [getting-started.md](getting-started.md).

To change mode, resolve a fresh v3 draft instead of editing a ResolvedRunSpec
or reinterpreting v2. The mode and settlement policy change
logical/order/round-trip identities, but Dataset, Snapshot, and ReplayPack IDs
remain unchanged; no new prepare or replay compilation is needed.

## One backtest

`run` and `run-backtest` are two names for the same semantics:

```bash
backtest run resolved-run.json \
  --attempt-nonce <unique-64-hex> \
  --config configs/local.toml
```

Optional physical overrides:

```text
--backend reference-python-v1
          |numpy-mmap-first-swap-exact-v1
          |reference-pumpfun-sniping-v1
          |numpy-mmap-pumpfun-sniping-v1
--reader-batch-rows N
--reader-readahead N
--output-buffer-rows N
--threads N
```

They do not change semantic `logical_run_id`, but enter physical provenance.
UI/API pass them as a separate `RunPhysicalSettingsCommand` inside
`RunBacktestCommand`; the canonical durable job has schema
`backtest.run-job/v2`. These fields do not belong to
`pumpfun-sniping-run-draft/v3`, even when one form collects both sets.
Optimized backends fail closed for any unsupported strategy/protocol/latency/
risk surface.

For Sniping, `reference-pumpfun-sniping-v1` is the readable oracle and works
with canonical Parquet or ReplayPack. `numpy-mmap-pumpfun-sniping-v1` is a
separate allowlisted SoA/mmap backend; it requires ReplayPack and is not a
generic replacement for the reference engine. Both execute one run
sequentially in one child process.

## Sweep

`sweep` and `run-sweep` launch independent resolved attempts:

```bash
backtest sweep resolved-sweep.json --config configs/local.toml
```

One stateful run is never divided into time shards. Admission determines
parallelism from measured host memory, CPU/native threads, and I/O budget. A
`ResolvedSweepSpec` must be canonical JSON; it is easier to build with the
typed UI/API resolver and save its `resolved_sweep_spec` field in canonical
compact form.

## Exact ML lifecycle

| Command | Result |
|---|---|
| `build-features REQUEST.json` | Point-in-time FeatureSet |
| `build-universe REQUEST.json` | Point-in-time Universe |
| `build-labels REQUEST.json` | Training-only LabelSet |
| `train REQUEST.json` | Exact integer-linear ModelBundle |
| `build-model-schedule REQUEST.json` | Walk-forward ModelSchedule |
| `predict REQUEST.json` | Frozen PredictionSet |

Example direct execution:

```bash
backtest build-features build-features.json --config configs/local.toml
```

Example queue execution while `serve` is running:

```bash
backtest build-features build-features.json \
  --enqueue \
  --idempotency-key features-snapshot-a-v1 \
  --config configs/local.toml
```

Labels are physically unavailable to the Strategy API. The current exact
runtime supports frozen or bounded precomputed embedded integer-linear
inference. Tree/ONNX/GPU tolerance and stateful modes are not enabled.

## Job queue

| Command | Purpose |
|---|---|
| `submit-job` | Advanced: durably enqueue an exact job type/payload |
| `jobs` | Bounded list of operational records |
| `get-job JOB_ID` | Current state/version of one job |
| `cancel-job JOB_ID` | Durable cancel request |
| `retry-job JOB_ID` | New attempt for a failed/interrupted immutable command |

```bash
backtest jobs --state RUNNING --limit 50 --config configs/local.toml
backtest get-job <job_id> --config configs/local.toml
backtest cancel-job <job_id> --config configs/local.toml
backtest retry-job <job_id> --config configs/local.toml
```

`submit-job` requires `--type`, `--payload`, and a stable
`--idempotency-key`; repeatable `--input-artifact` supplies exact inputs. Typed
command aliases or the UI are safer for normal use.

The same idempotency key with the same canonical payload returns the existing
job. The same key with a different payload produces a conflict.

## Results and lineage

```bash
backtest list-runs --limit 50 --offset 0 --config configs/local.toml
backtest show-run-summary <run_artifact_id> --config configs/local.toml
backtest list-roundtrips <run_artifact_id> --limit 200 --config configs/local.toml
backtest list-roundtrips <run_artifact_id> \
  --after '<boundary_ordinal>:<roundtrip_id>' \
  --limit 200 \
  --config configs/local.toml
backtest verify-artifact <artifact_id> --config configs/local.toml
backtest show-lineage <artifact_id> --config configs/local.toml
```

List endpoints return bounded summaries: scalar metrics, hashes, counts, and
warnings. Complete Parquet/ReplayPack bytes are not returned through CLI/API
list responses; authoritative details live in the verified manifest.

`show-run-summary` and `list-roundtrips` accept an exact committed Pump.fun
Sniping Run artifact ID, not `logical_run_id` or a path. Summary returns
`pumpfun-sniping-run-summary/v3`: counts/hashes, execution/settlement policies,
fee/deposit/slippage totals, gross/venue/synthetic settlement totals, realized
PnL, and valuation completeness. With an unvalued open position,
`economic_pnl_atomic` remains `null`, while
`valued_economic_pnl_subtotal_atomic` is explicitly partial. Round-trip pages
use keyset cursor `BOUNDARY_ORDINAL:ROUNDTRIP_ID` and contain at most 200 rows.
The reader verifies `successful-run/v3`, descriptors, and canonical digests
before returning data; the API never returns complete `roundtrips.parquet` or
`final_balances.parquet` files. `pumpfun-roundtrips/v4` exposes
`account_profile_id`, ordered `account_components[]`, execution mode, liquidity
evidence, and actual venue/synthetic settlement. Potential reference/landing
and projected MTM shortfall remain separate from actually settled synthetic
funding. Leg failure codes remain explicit, and cashflow reconciles with
correlated `run-ledger/v2`. Committed summary v2/round-trip v3 remain readable
as their original immutable schemas.

## Retention and GC

```bash
backtest pin important-experiment \
  --root <artifact_id> \
  --reason "baseline before strategy change" \
  --config configs/local.toml

backtest gc --dry-run --config configs/local.toml
backtest gc --execute --config configs/local.toml
backtest gc-purge <batch_id> --config configs/local.toml
backtest unpin important-experiment --config configs/local.toml
```

`gc-purge` physically deletes an already moved trash batch only after the
configured grace period. Always start with a dry run, and never delete `var/`
manually.

## Backup and restore drill

After configuring `[backup]` on another physical device/host:

```bash
backtest backup --config configs/local.toml
backtest restore-verify <backup_cut_id> --config configs/local.toml
```

The backup command publishes a consistent SQLite + artifact-closure
generation. A copy in another directory on the same NVMe is not a durability
backup.

## Benchmark

```bash
backtest benchmark <target_artifact_id> \
  --attempt-nonce <unique-64-hex> \
  --workload REPLAY_PACK_SCAN \
  --launch-route LOCAL_ARTIFACT \
  --cache-condition WARM \
  --capacity-days 1 \
  --batch-rows 65536 \
  --readahead 1 \
  --process-count 1 \
  --native-threads 1 \
  --config configs/local.toml
```

`backtest benchmark --help` lists the accepted workloads. Capacity 7/30 in the
harness may mean a repeated independent base stream and is not a claim about
representative stateful market history. `EXTERNALLY_COLD` requires an external
verified cache-eviction controller.

## Pump.fun Copy Buy

Use the ordinary `inspect-source`, `plan-dataset`, `prepare-dataset`,
`compile-replay`, `resolve-run` and `run` commands with the separate Copy
contracts. Configure the exact [Copy source selection](configuration.md#copy-buy-source-selection)
first. Preparation requires signer-bearing coverage and a complete four-attempt
settlement tail; a creation-only Sniping dataset cannot supply that evidence.

`describe-run-contract --help` lists the contract selector. The Copy draft is
`pumpfun-copy-buy-run-draft/v1`; it adds exact `signing_wallets`,
`take_profit_bps`, `stop_loss_bps`, `maximum_hold_seconds`,
`observation_delay_transactions` and `buy_delay_transactions`, alongside the
shared explicit execution mode, fees, wallet accounts and sell delay. The
currently admitted backend is `reference-pumpfun-copy-buy-v1`. Optimized Copy,
materialized delivery schedules and ML overlays remain unavailable.

The React **Launch strategy → Pump.fun Copy Buy** form exposes these fields
and passes the typed draft to the same resolver. **Strategy results** exposes
the common summary, signals/entries, exits, trade details and lineage. Wallet
BUYs are exact source signals, not recommendations or automatically selected
leaders; each mint consumes its one entry even if the buy is rejected.

## Web UI and Control API

```bash
backtest serve --config configs/local.toml
```

The UI is at `http://127.0.0.1:<control.port>` and the API is under `/api/v1`
on the same origin. Typed prepare/backtest/sweep/ML forms, queue/progress,
cancel/retry, run comparison, artifacts/lineage, and resource status are
available. A separate Pump.fun Sniping form discovers its schema through the
run contract, accepts decimal strings as `BigInt`, displays fixed semantics as
read-only, and lets the user choose the reference or dedicated optimized
backend. Sniping, Copy Buy and FirstSwap open one React **Strategy results**
view through **Results**. It shows summary cards, bounded whole-run analytics,
entry/exit distributions, 25-entry keyset pages and a trade-detail overlay.
Stored details preserve lifecycle, slippage, component fees, account/rent,
cashback and realized/open PnL. Missing full valuation is never replaced with
zero or the valued subtotal. English is the default; **Language** in the
sidebar selects Russian without changing the submitted command.

Contract discovery exposes the v3 form with a required choice between
`EXOGENOUS_REPLAY` and `EXOGENOUS_VIRTUAL_SETTLEMENT`. Virtual settlement
shows a persistent warning: shortfall-funded SOL is synthetic and spendable
only in the simulated wallet; it is not proof that the corresponding sale
could execute on-chain.

Main Sniping API routes:

| Method and path | Purpose |
|---|---|
| `GET /api/v1/run-contracts` | Typed discovery of editable/fixed run contract |
| `POST /api/v1/run-specs/resolve` | Resolve strict draft into an exact `ResolvedRunSpec` |
| `POST /api/v1/backtests` | Fast durable submit without running a backtest in the request |
| `GET /api/v1/run-artifacts/{id}/summary` | Bounded verified summary of an exact run artifact |
| `GET /api/v1/run-artifacts/{id}/roundtrips` | Keyset page, `limit=1..200` |

The HTTP round-trip cursor has two parts: `after_target_boundary_ordinal` and
`after_roundtrip_id`; pass either both or neither. These are the same values
that the CLI encodes in one `BOUNDARY_ORDINAL:ROUNDTRIP_ID` string.

Common read-only result routes (existing family-specific APIs remain compatible):

| Route under `/api/v1/run-artifacts/{id}` | Purpose |
|---|---|
| `GET strategy-summary` | Verified common summary |
| `GET strategy-dashboard?limit=25` | Summary and one entry page |
| `GET entries?limit=25` | Keyset page; same two-part cursor |
| `GET entries/{entry_id}?boundary_ordinal=DECIMAL` | Exact stored entry details |
| `GET entries/{entry_id}/chart?boundary_ordinal=DECIMAL` | Bounded retained Pump history and actual markers |
| `GET analytics` | Whole-run distributions with explicit denominators |

Chart queries are bounded to 10 million input rows (500,000 clock rows), 128
files, 1 GiB of Parquet, 50,000 selected venue events, 4,000 points and six
markers, with a ten-second scan deadline. Optional analytics has separate
limits of 100,000 rows, 64 MiB and five seconds. Busy/quota failures return
explicit codes and never partial global statistics or truncated charts.

An HTTP request does not execute a heavy job. Browser disconnect or reload does
not cancel the child process. SSE is not implemented; the current UI uses
bounded polling.

A form submission still requires exact four-stream evidence for its selected
source range. Checked-in `UNKNOWN` examples and hermetic HTTP/static tests do
not replace source receipts. Missing or incompatible evidence produces a typed
rejection before execution.

## Direct and queued execution

| State | How to run |
|---|---|
| `serve` stopped | Direct heavy command; CLI waits for terminal state |
| `serve` running | UI/API or supported CLI `--enqueue` |
| Only status/result needed | Query CLI automatically verifies and uses the running loopback controller |

Direct and API paths create one `ResolvedJobSpec` and launch the same isolated
child. A second controller for one `data_root` is prohibited. An unavailable
or mismatched lock owner does not trigger a hidden local fallback.

## Exit codes and errors

The CLI prints a machine-readable safe JSON error without raw tracebacks,
credentials, or absolute secret paths. Common causes include:

- `LOCAL_CONFIG_INVALID` — invalid TOML or resource invariant;
- missing or mismatched capability/projection mapping;
- an exact artifact/closure is missing or failed verification;
- fidelity is insufficient for the reference strategy;
- another controller owns `data_root`;
- host admission does not permit a heavy child;
- no backup target is configured on another physical device/host.

Do not replace a typed failure with `latest`, lower fidelity, or a synthetic
result.

## Useful checks

```bash
backtest --help
backtest serve --help
backtest run --help
backtest jobs --config configs/local.toml
```

For the complete source-to-first-run path with JSON examples, see
[getting-started.md](getting-started.md).

---

**Language:** English · [Русский](cli-reference.ru.md)
