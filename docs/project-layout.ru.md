# Структура проекта

Проект использует `src/` layout и один installable package `backtest`.
`src/backtest/` — не «папка только бэктеста», а namespace всей платформы:
domain, engine, workflows, adapters, plugins, CLI/API/UI и composition roots.

## Репозиторий верхнего уровня

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
  var/                 # создаётся локально, gitignored
  .venv/               # локальное окружение, gitignored
  dist/                # generated package builds, gitignored
```

| Путь | Что находится |
|---|---|
| `LICENSE` | Лицензия проекта MIT |
| `README.md` | Короткая точка входа |
| `pyproject.toml` | Package metadata, dependencies и tool settings |
| `uv.lock` | Exact dependency resolution для поддерживаемых платформ |
| `.importlinter` | Исполняемые правила направления импортов |
| `configs/` | Коммитимые profiles/examples и gitignored local configs |
| `docs/` | Пользовательские и архитектурные документы |
| `scripts/` | Platform setup и smoke helpers, включая Windows 11/WSL2 |
| `src/backtest/` | Production Python package |
| `tests/` | Architecture, unit, contract, integration, golden и performance tests |
| `var/` | Mutable operational state и immutable local artifacts |

Windows entry point — `scripts/setup-windows-wsl2.ps1`: он вызывает
`scripts/windows-wsl2-smoke.sh` внутри Ubuntu и отклоняет repository под
`/mnt`. Native Win32 execution намеренно не входит в текущий runtime contract
этой структуры.

## Слои `src/backtest`

Нормативное направление зависимостей:

```text
interfaces / adapters / plugins -> application ports -> engine / domain
bootstrap -> concrete wiring
```

### `domain/`

Pure value objects и инварианты:

- identifiers/content digests;
- chain/causal time;
- market events и intents;
- execution values;
- double-entry ledger;
- fidelity vocabulary.

Здесь не должно быть ClickHouse, SQLite, filesystem, FastAPI, DuckDB, PyArrow
или NumPy/DataFrame infrastructure.

### `engine/`

Deterministic replay semantics:

- scheduler и phase ordering;
- historical/observed/simulation/portfolio state;
- reference reducer;
- accounting/audit;
- keyed RNG;
- causal feature/prediction views.

Engine не знает о source adapters, API, CLI, runtime supervisor или bootstrap.

### `application/`

Use cases и общие contracts:

```text
application/
  ports/       # заменяемые interfaces, которыми пользуются use cases
  use_cases/   # orchestration одного пользовательского действия
  *.py         # resolved specs, jobs, artifacts, ML и shared application models
```

Application координирует операции, но не импортирует concrete adapters,
interfaces или plugin implementations. Новый port добавляется только на
реальном заменяемом шве.

### `adapters/`

Concrete I/O и physical formats:

| Подпапка | Роль |
|---|---|
| `source/clickhouse/` | Read-only ClickHouse query planning/streaming |
| `artifacts/localfs/` | Atomic publication, manifests, verification, retention |
| `catalog/sqlite/` | Durable jobs, events, indexes и shard ledger |
| `columnar/arrow/` | Canonical Parquet/Arrow чтение и запись |
| `columnar/numpy/` | Dense local mmap representations |
| `replay/` | Выбор reference/optimized replay backend |
| `delivery_schedule/` | Materialized delivery stream |
| `ml/numpy/` | Point-in-time ML artifacts и exact linear runtime |
| `process/` и `processes/` | Local child execution/progress transport |
| `results/` | Buffered Parquet results и sweep output |
| `control/` | Strict loopback Control API client |
| `backup/` | Different-device backup/restore |
| `performance/` | Artifact-bound benchmark adapters |
| `system/` | Host resource observations |

Adapter реализует application-owned port и не протаскивает свою
infrastructure semantics в core.

### `plugins/`

Checked-in заменяемая торговая semantics:

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

Текущая runtime composition статически allowlist-ит FirstSwap и Pump.fun
Sniping stacks по
exact source bundle digest. Просто положить новый `.py` в папку недостаточно:
нужно реализовать core-owned contract, объявить versioned bundle/config,
подключить его только в `bootstrap`, добавить fidelity/preflight/golden tests и
сохранить dependency direction. Автоматический plugin discovery пока не
реализован.

Indexer adapter и protocol plugin — разные вещи. Первый знает transport/table
schema; второй отвечает за protocol lifecycle, direction, atomic units, fees,
rounding и venue transition.

### `runtime/`

Single-host operational mechanics:

- resource budget/admission;
- host memory/swap probes;
- controller/file locks;
- runtime lock identity;
- thread limits и system clock.

Runtime не задаёт strategy или engine semantics.

### `interfaces/`

Inbound adapters:

- `interfaces/cli/` — Typer commands;
- `interfaces/api/` — FastAPI routes и typed DTO;
- `interfaces/web/static/` — готовые HTML/CSS/JS assets основного Control UI и
  отдельного bounded Pump.fun Sniping result dashboard.

CLI и API валидируют input, вызывают application use cases и преобразуют
response. Они не должны напрямую читать SQLite, Parquet или arbitrary paths.
Node.js process для UI не нужен.

### `bootstrap/`

Единственный composition root. Здесь concrete adapters связываются с ports для
трёх entry modes:

- Direct CLI;
- `backtest serve`;
- isolated `backtest-job-child`.

Если нужно выбрать implementation по local config, делать это следует здесь,
а не в domain/application.

### Зачем нужны `__init__.py`

`__init__.py` делает каталог явным Python package, задаёт контролируемый public
import surface и позволяет package tooling включить модули в distribution.
Большинство таких файлов здесь намеренно пустые или только re-export-ят
стабильные symbols; бизнес-логика в них не хранится.

## Структура tests

| Путь | Что доказывает |
|---|---|
| `tests/architecture/` | Запрещённые imports и module boundaries |
| `tests/unit/` | Локальная semantics одного component |
| `tests/contract/source/` | Общий contract source adapters, optional live test |
| `tests/contract/jobs/` | SQLite queue/supervisor contract |
| `tests/integration/data/` | Prepare/Parquet/ReplayPack/equivalence lifecycle |
| `tests/integration/jobs/` | Process isolation, locks, cancel/restart/receipts |
| `tests/integration/performance/` | Spawn/control benchmark lifecycle |
| `tests/golden/` | Fixed canonical expected documents/hashes; Pump RPC/IDL vectors лежат в `pumpfun/program-v1/` |
| `tests/performance/` | Explicit opt-in capacity/throughput measurements |

Live и performance tests не входят в обычный hermetic gate без явного opt-in.

## Local data root

По умолчанию `[paths].data_root = "var"`:

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

| Каталог | Содержимое и authority |
|---|---|
| `catalog/` | SQLite operational queue/indexes; не authority для artifact bytes |
| `locks/` | Controller/writer/publication/retention/run OS locks |
| `staging/` | Невидимые incomplete writes до publication |
| `job_receipts/` | Durable completion receipts для restart reconciliation |
| `cache/raw/` | Optional evictable source cache |
| `canonical/` | Immutable canonical Parquet distributions |
| `snapshots/` | Root manifests с exact distribution refs |
| `replay/` | Rebuildable content-addressed mmap ReplayPacks |
| `delivery_schedules/` | Optional derived observation schedules |
| `features/`, `predictions/`, `models/` | Point-in-time ML artifacts |
| `pins/` | Authoritative durable retention roots |
| `runs/` | Immutable attempts, manifests, trades, ledger и audit |
| `tmp/` | Quota-limited temporary files |
| `trash/` | GC batches до grace-period purge |

Не редактируйте и не удаляйте artifact leaves вручную. Directory listing не
является manifest; reader доверяет только verified content-addressed refs,
manifest, durable publication evidence и `COMMITTED` protocol.

## Куда вносить типичное изменение

| Задача | Основное место | Что ещё проверить |
|---|---|---|
| Новый domain invariant | `domain/` | Unit/property tests, отсутствие infrastructure imports |
| Scheduler/replay semantics | `engine/` | Causality, golden hashes, batch equivalence |
| Новый workflow | `application/use_cases/` | Существующий port или обоснованный replaceable seam |
| Новый индексер | `adapters/source/` | Source contract, bounds, redaction, fidelity |
| Новый protocol/launchpad | `plugins/protocols/` | Golden on-chain semantics, projector/venue contracts |
| Новая strategy | `plugins/strategies/` | Requirements, immutable bundle, causality/preflight |
| Execution/risk policy | `plugins/execution/`, `plugins/risk/` | Integer math, conservation, atomic commit |
| Новый storage/process implementation | `adapters/` | Application-owned port, crash/concurrency tests |
| CLI/API form | `interfaces/` | Same use case, typed DTO, bounded/security tests |
| Выбор implementations | `bootstrap/` | Единственный composition root |
| Host limits | `configs/local.toml` | Измерения RAM/swap/I/O, config validation |

Перед нетривиальным изменением прочитайте затрагиваемые разделы
[нормативной архитектуры](architecture-deep-dive.ru.md) и запустите полный quality gate.

---

**Язык:** [English](project-layout.md) · Русский
