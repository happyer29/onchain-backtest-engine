# Project layout

The project uses a `src/` layout and one installable package, `backtest`.
`src/backtest/` is not merely a folder for the backtest engine; it is the
namespace for the entire platform: domain, engine, workflows, adapters,
plugins, CLI/API/UI, and composition roots.

## Repository root

```text
backtest/
  LICENSE
  README.md
  pyproject.toml
  uv.lock
  .importlinter
  configs/
  docs/
  scripts/
  src/backtest/
  tests/
  var/                 # created locally, gitignored
  .venv/               # local environment, gitignored
  dist/                # generated package builds, gitignored
```

| Path | Contents |
|---|---|
| `LICENSE` | MIT project license |
| `README.md` | Concise entry point |
| `pyproject.toml` | Package metadata, dependencies, and tool settings |
| `uv.lock` | Exact dependency resolution for supported platforms |
| `.importlinter` | Executable dependency-direction rules |
| `configs/` | Committed profiles/examples and gitignored local configs |
| `docs/` | User and architecture documentation |
| `scripts/` | Platform setup and smoke helpers, including Windows 11/WSL2 |
| `src/backtest/` | Production Python package |
| `tests/` | Architecture, unit, contract, integration, golden, and performance tests |
| `var/` | Mutable operational state and immutable local artifacts |

The Windows entry point is `scripts/setup-windows-wsl2.ps1`; it invokes
`scripts/windows-wsl2-smoke.sh` inside Ubuntu and rejects repositories under
`/mnt`. Native Win32 execution is intentionally outside this layout's current
runtime contract.

## Layers under `src/backtest`

The normative dependency direction is:

```text
interfaces / adapters / plugins -> application ports -> engine / domain
bootstrap -> concrete wiring
```

### `domain/`

Pure value objects and invariants:

- identifiers and content digests;
- chain and causal time;
- market events and intents;
- execution values;
- double-entry ledger;
- fidelity vocabulary.

This layer must not contain ClickHouse, SQLite, filesystem, FastAPI, DuckDB,
PyArrow, or NumPy/DataFrame infrastructure.

### `engine/`

Deterministic replay semantics:

- scheduler and phase ordering;
- historical, observed, simulation, and portfolio state;
- reference reducer;
- accounting and audit;
- keyed RNG;
- causal feature and prediction views.

The Engine knows nothing about source adapters, the API, CLI, runtime
supervisor, or bootstrap.

### `application/`

Use cases and shared contracts:

```text
application/
  ports/       # replaceable interfaces used by the use cases
  use_cases/   # orchestration of one user action
  *.py         # resolved specs, jobs, artifacts, ML, and shared application models
```

Application coordinates operations but does not import concrete adapters,
interfaces, or plugin implementations. Add a new port only at a real
replaceable seam.

### `adapters/`

Concrete I/O and physical formats:

| Subdirectory | Role |
|---|---|
| `source/clickhouse/` | Read-only ClickHouse query planning and streaming |
| `artifacts/localfs/` | Atomic publication, manifests, verification, and retention |
| `catalog/sqlite/` | Durable jobs, events, indexes, and shard ledger |
| `columnar/arrow/` | Canonical Parquet/Arrow reading and writing |
| `columnar/numpy/` | Dense local mmap representations |
| `replay/` | Reference/optimized replay backend selection |
| `delivery_schedule/` | Materialized delivery stream |
| `ml/numpy/` | Point-in-time ML artifacts and exact linear runtime |
| `process/` and `processes/` | Local child execution and progress transport |
| `results/` | Buffered Parquet results and sweep output |
| `control/` | Strict loopback Control API client |
| `backup/` | Different-device backup and restore |
| `performance/` | Artifact-bound benchmark adapters |
| `system/` | Host resource observations |

An adapter implements an application-owned port and does not leak its
infrastructure semantics into the core.

### `plugins/`

Checked-in replaceable trading semantics:

```text
plugins/
  networks/solana/
    costs.py
    sniping.py
  protocols/
    reference/projector.py
    pumpfun/
      model.py
      projector.py
      sniping.py
  strategies/
    first_swap.py
    pumpfun_sniping.py
  execution/constant_product.py
  risk/static.py
```

The current runtime composition statically allowlists the FirstSwap and
Pump.fun Sniping stacks by exact source-bundle digest. Merely placing a new
`.py` file in the directory is insufficient: it must implement the core-owned
contract, declare a versioned bundle/config, be wired only in `bootstrap`, add
fidelity/preflight/golden tests, and preserve dependency direction. Automatic
plugin discovery is not implemented.

An indexer adapter and a protocol plugin are different components. The former
knows the transport and table schema; the latter owns protocol lifecycle,
direction, atomic units, fees, rounding, and venue transition.

### `runtime/`

Single-host operational mechanics:

- resource budget and admission;
- host memory and swap probes;
- controller and file locks;
- runtime lock identity;
- thread limits and system clock.

Runtime does not define strategy or engine semantics.

### `interfaces/`

Inbound adapters:

- `interfaces/cli/` — Typer commands;
- `interfaces/api/` — FastAPI routes and typed DTOs;
- `interfaces/web/static/` — prebuilt HTML/CSS/JS assets for the main Control
  UI and the separate bounded Pump.fun Sniping result dashboard.

The CLI and API validate input, call application use cases, and transform the
response. They must not read SQLite, Parquet, or arbitrary paths directly. The
UI does not require a Node.js process.

### `bootstrap/`

The sole composition root. Concrete adapters are wired to ports here for three
entry modes:

- Direct CLI;
- `backtest serve`;
- isolated `backtest-job-child`.

Choose implementations from local configuration here, never in
domain/application.

### Why `__init__.py` files exist

`__init__.py` makes a directory an explicit Python package, defines a
controlled public import surface, and lets package tooling include modules in
the distribution. Most such files are intentionally empty or only re-export
stable symbols; they do not contain business logic.

## Test layout

| Path | What it proves |
|---|---|
| `tests/architecture/` | Forbidden imports and module boundaries |
| `tests/unit/` | Local semantics of one component |
| `tests/contract/source/` | Shared source-adapter contract and optional live test |
| `tests/contract/jobs/` | SQLite queue/supervisor contract |
| `tests/integration/data/` | Prepare/Parquet/ReplayPack/equivalence lifecycle |
| `tests/integration/jobs/` | Process isolation, locks, cancel/restart, and receipts |
| `tests/integration/performance/` | Spawn/control benchmark lifecycle |
| `tests/golden/` | Fixed canonical expected documents/hashes; Pump RPC/IDL vectors live under `pumpfun/program-v1/` |
| `tests/performance/` | Explicit opt-in capacity and throughput measurements |

Live and performance tests are not part of the normal hermetic gate without an
explicit opt-in.

## Local data root

By default, `[paths].data_root = "var"`:

```text
var/
  catalog/catalog.sqlite
  locks/
  staging/
  job_receipts/
  cache/raw/
  canonical/
  snapshots/
  replay/
  delivery_schedules/
  features/
  predictions/
  models/
  pins/
  runs/
  tmp/
  trash/
```

| Directory | Contents and authority |
|---|---|
| `catalog/` | SQLite operational queue/indexes; not authority for artifact bytes |
| `locks/` | Controller/writer/publication/retention/run OS locks |
| `staging/` | Invisible incomplete writes before publication |
| `job_receipts/` | Durable completion receipts for restart reconciliation |
| `cache/raw/` | Optional evictable source cache |
| `canonical/` | Immutable canonical Parquet distributions |
| `snapshots/` | Root manifests with exact distribution references |
| `replay/` | Rebuildable content-addressed mmap ReplayPacks |
| `delivery_schedules/` | Optional derived observation schedules |
| `features/`, `predictions/`, `models/` | Point-in-time ML artifacts |
| `pins/` | Authoritative durable retention roots |
| `runs/` | Immutable attempts, manifests, trades, ledger, and audit |
| `tmp/` | Quota-limited temporary files |
| `trash/` | GC batches before grace-period purge |

Do not edit or remove artifact leaves manually. A directory listing is not a
manifest; readers trust only verified content-addressed references, manifests,
durable publication evidence, and the `COMMITTED` protocol.

## Where to make a typical change

| Task | Primary location | Also verify |
|---|---|---|
| New domain invariant | `domain/` | Unit/property tests and absence of infrastructure imports |
| Scheduler/replay semantics | `engine/` | Causality, golden hashes, and batch equivalence |
| New workflow | `application/use_cases/` | Existing port or a justified replaceable seam |
| New indexer | `adapters/source/` | Source contract, bounds, redaction, and fidelity |
| New protocol/launchpad | `plugins/protocols/` | Golden on-chain semantics and projector/venue contracts |
| New strategy | `plugins/strategies/` | Requirements, immutable bundle, and causality/preflight |
| Execution/risk policy | `plugins/execution/`, `plugins/risk/` | Integer math, conservation, and atomic commit |
| New storage/process implementation | `adapters/` | Application-owned port and crash/concurrency tests |
| CLI/API form | `interfaces/` | Same use case, typed DTO, and bounded/security tests |
| Implementation selection | `bootstrap/` | The sole composition root |
| Host limits | `configs/local.toml` | Measured RAM/swap/I/O and config validation |

Before a non-trivial code change, read the affected sections of the
[normative architecture](architecture-deep-dive.md), then run the full quality gate.

---

**Language:** English · [Русский](project-layout.ru.md)
