# CLI и рабочие сценарии

Entry point устанавливается из `pyproject.toml` как `backtest`. Актуальная
истина о синтаксисе конкретной версии:

```bash
backtest --help
backtest <command> --help
```

Примеры запускаются из корня репозитория и явно используют
`configs/local.toml`. Замените символические значения точными входными данными
своего источника и набора данных.

## Общие понятия

### Exact IDs

Команды не принимают aliases вроде `latest` на execution boundary. Обычно
используются:

- `artifact_id` — exact committed artifact;
- `dataset_revision_id` — logical dataset плюс exact source boundaries;
- `snapshot_id` — exact root snapshot;
- `replay_pack_id` — exact derived mmap pack;
- `delivery_schedule_id` — optional exact materialized observation stream;
- `run_artifact_id` — exact committed `successful-run/v3` artifact;
- `logical_run_id` — semantic experiment identity;
- `execution_attempt_id` — конкретная physical attempt;
- `job_id` — operational queue record.

ID берётся из JSON-ответа предыдущей команды или verified manifest. Путь к
файлу не заменяет content ID.

### JSON inputs

Heavy commands принимают typed JSON files:

- `plan-dataset`/`prepare-dataset` — versioned dataset plan request;
- `resolve-run` — closed typed RunSpecDraft, включая отдельный
  `pumpfun-sniping-run-draft/v3` с required `execution_mode`;
- `run` — exact ResolvedRunSpec;
- `sweep` — exact canonical ResolvedSweepSpec;
- ML commands — соответствующий resolved typed ML command.

Unknown поля, unresolved aliases, неправильные IDs и несовместимая closure
отклоняются до child execution. Формы проще создавать через Web UI; generic
JSON editor в UI намеренно отсутствует.

Legacy Sniping draft v2 не переосмысляется с default mode: он
получает `RERESOLVE_REQUIRED`. Вместо него создайте и resolve-ните draft v3.

## Source и dataset

| Команда | Вход | Результат |
|---|---|---|
| `inspect-source` | Host config + capability TOML; optional bounded evidence + decision ranges | Committed `source-inspection/v5` artifact |
| `plan-dataset REQUEST.json` | Requirements, range, budget, inspection ID | Dry-run selective plan, без download |
| `prepare-dataset REQUEST.json` | Тот же plan request + projection config | Canonical distributions и snapshot |

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

Только source-facing path использует network. Core request задаёт immutable
`NetworkId`, `PositionSchemaId` и typed half-open `BlockRange`; только Solana
source adapter отображает block ordinal на physical `slot`. Extraction всегда
bounded, с explicit columns и hard query limits.

Без evidence flags команда делает metadata-only inspection. Evidence-границы
обязательны вместе. Decision-границы тоже передаются только парой, требуют
evidence range и должны находиться внутри него. Если decision flags опущены,
весь evidence range считается decision range; при отдельном settlement tail
это обычно неверно, потому что tail launches не должны становиться targets.

Один внешний cut может быть значительно шире 4096 blocks. Fixed
`pumpfun-indexer-v1` composition делит его на contiguous internal subshards
шириной не более 4096 blocks. Launch stream читается только по decision range,
остальные три streams — по полному evidence range. `[planning]` задаёт
requested query ceilings, а adapter применяет к каждому внутреннему query
более строгие hard caps: максимум 60 seconds, 512 MiB memory, 100000 result
rows, 64 MiB result bytes, 2000000 read rows и 1 GiB read bytes, один thread.

Bounded pass сначала читает metadata/schema, затем выполняет fixed read-only
streaming queries и публикует четыре secret-free
`bounded-source-evidence/v2` receipts внутри inspection — по одному
агрегированному receipt на capability, не на subshard. Ответ показывает
`artifact_id`, `evidence_receipt_ids`, per-capability proof statuses и
`cut_evidence`; receipts закрепляют exact source/mapping/query/normalizer/
projector contracts, evidence + decision ranges, все query fingerprints,
aggregate result digest и bounded observations, но не хранят raw rows или
credentials.

Для проверки диапазона решений с отдельным хвостом расчётов подставьте
выбранные номера блоков в этот шаблон команды:

```text
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block BLOCK_FROM \
  --evidence-to-block EVIDENCE_BLOCK_TO \
  --decision-from-block BLOCK_FROM \
  --decision-to-block DECISION_BLOCK_TO
```

`BLOCK_FROM`, `DECISION_BLOCK_TO` и `EVIDENCE_BLOCK_TO` — обозначения целых
номеров блоков. Верхние границы не включаются в диапазон. Диапазон evidence
должен покрывать весь диапазон решений и хвост расчётов, необходимый для
заявленных ограничений набора данных по транзакциям и времени.

Задайте `requested_days`, `maximum_followup_delay_transactions`,
`maximum_tail_blocks` и локальные ограничения `[planning]` для выбранного
диапазона. Полная схема plan приведена в
[getting-started.ru.md](getting-started.ru.md). Увеличение бюджета запроса не
повышает source fidelity. Изменение диапазона требует нового bounded evidence;
пропущенный переход состояния кривой приводит к `CURVE_TRANSITION_MISMATCH`
до публикации inspection.

Bounded evidence range сейчас доступен именно через CLI. HTTP
`POST /api/v1/sources/{source_id}/inspect` выполняет metadata-only inspection и
не является скрытым способом получить receipts.

Для Pump.fun Sniping inspection должен содержать один согласованный cut четырёх
streams:

| Stream | Canonical event | Что требуется |
|---|---|---|
| `BLOCK_CLOCK` | `BLOCK` | Block time/hash и полный `transaction_count`, включая successful/failed/vote |
| `TOKEN_LAUNCH` | `TOKEN_LAUNCH` | Exact transaction/instruction position, successful creation, immutable creator и creation-time state |
| `PUMP_CURVE_TRADE` | `VENUE_TRADE` | Direction, atomic amounts, complete after-state и fee components |
| `PUMP_CURVE_LIFECYCLE` | `VENUE_LIFECYCLE` | Completion/migration coverage |

Fixed profile `pumpfun-indexer-v1` и normalizer
`pumpfun-indexer-v1-live-normalizer-v2` публикуют следующие logical contracts:

| Stream | `protocol_version` | `schema_version` |
|---|---|---|
| `BLOCK_CLOCK` | `solana-block-clock-v1` | `solana-block-clock-normalized-v1` |
| `TOKEN_LAUNCH` | `pump-program-static-fee-v1` | `pumpfun-token-launch-normalized-v2` |
| `PUMP_CURVE_TRADE` | `pump-program-static-fee-v1` | `pumpfun-curve-trade-normalized-v2` |
| `PUMP_CURVE_LIFECYCLE` | `pump-program-static-fee-v1` | `pumpfun-curve-lifecycle-normalized-v2` |

Эти строки берутся из inspection artifact. Их нельзя заменять raw version
tokens из TOML или вводить вручную как aliases.

Checked-in mappings имеют `UNKNOWN` proofs и являются только secret-free
структурными examples. Они не допускают live Sniping dataset. Evidence v1,
source inspection v1–v4, dataset plan v1–v3 и DatasetSpec v1–v4 отклоняются с
`REPREPARE_REQUIRED`; implicit Solana default и in-place migration отсутствуют.

Canonical prepared contract использует
`backtest.dataset-plan/v4` и embedded DatasetSpec v5. Для Sniping один
`DataRequirement` обязан задать
`global-transaction-duration-roundtrip/v1`: `maximum_tail_blocks` задаёт
hard bounded extraction cap, а `maximum_followup_delay_transactions` —
наибольшую sell latency, которую разрешит этот dataset. Planner
расширяет только settlement streams ровно до cap; caller tail выше
cap отклоняется. Перед snapshot-root publication validator проверяет
actual `+500`, `+2s` и maximum follow-up path каждого launch. Plan v1–v3 и
DatasetSpec v1–v4 не мигрируются на месте и получают
`REPREPARE_REQUIRED`. Полный JSON example находится в
[getting-started.ru.md](getting-started.ru.md).

Static capability TOML обязан оставлять все generated proof fields равными
`UNKNOWN`; ручной `PROVEN` или `REFUTED` parser отклоняет. Local mappings лишь
активируют exact fixed-profile проверку. Новый range или другой evidence
operand требует нового generated bounded pass; неизменный exact inspection
artifact можно переиспользовать для той же closure. Fixed evaluator публикует
`PROVEN` только когда
полностью прошли block/sentinel, global transaction clock,
launch-classification, bundled-buy classification, curve transition, fee rounding
и terminal lifecycle checks на одном cut. Классификатор bundled buy использует
последующий successful buy той же signature + mint в той же transaction, а не
доверяет `bundled_buys_count`. Любой unknown/conflict/gap приводит к typed
отказу до planner/engine mutation.

## Replay и run resolution

| Команда | Вход | Результат |
|---|---|---|
| `compile-replay SNAPSHOT_ID` | Verified snapshot | Rebuildable mmap ReplayPack |
| `compile-delivery-schedule RESOLVED.json` | ResolvedRunSpec с ReplayPack | Optional materialized delivery stream |
| `resolve-run DRAFT.json` | Draft + exact local IDs | Immutable ResolvedRunSpec JSON |

```bash
backtest compile-replay <snapshot_id> --config configs/local.toml

backtest resolve-run run-draft.json \
  --config configs/local.toml > resolved-run.json

backtest compile-delivery-schedule resolved-run.json \
  --config configs/local.toml
```

DeliverySchedule нужен только для часто повторяемой одинаковой latency/clock
policy. Dynamic и materialized пути обязаны давать один scheduler result.
Чтобы использовать результат, сначала resolve исходный draft с exact
`replay_pack_id` и `delivery_schedule_id: null`, скомпилируйте schedule, затем
поместите exact returned ID в исходный draft и resolve его заново. Не
редактируйте `ResolvedRunSpec` вручную. Schedule запрещён без ReplayPack;
resolver сверяет его build key, clock/latency/scheduler semantics, root seed,
runtime lock, NetworkId/PositionSchemaId и decision range. Schedule является
physical fast path: `logical_run_id` не меняется, а attempt provenance
меняется.

Для Sniping schedule materializes post-transaction-group observation delivery;
фиксированные `+500` buy landing и `+2s`/отдельная sell transaction latency
остаются dynamic order/timer semantics и не встраиваются в generic ReplayPack.

## Pump.fun Sniping run contract

Текущая discovery-команда возвращает точную форму исполняемого DTO v3 и fixed
semantics:

```bash
backtest describe-run-contract pumpfun-sniping-run-draft/v3 \
  --config configs/local.toml
```

Editable поля strict draft:

- exact `dataset_revision_id`, `snapshot_id`, optional `replay_pack_id` и
  optional `delivery_schedule_id`;
- initial SOL и gross buy budget как decimal strings;
- отдельные buy/sell slippage bps и positive `sell_delay_transactions`;
- `pumpfun-solana-wallet-account-profile/v2` с initial UVA state,
  effective interval и тремя schema-addressed account costs;
- effective-dated Pump fee profile;
- отдельные effective-dated Solana buy/sell fee profiles;
- required closed-enum `execution_mode`: `EXOGENOUS_REPLAY` или
  `EXOGENOUS_VIRTUAL_SETTLEMENT`;
- root seed как unsigned decimal string.

Resolver, а не UI, добавляет неизменяемые 600-second developer cooldown,
buy `+500` global Solana transactions, sell decision `+2s`, SOL-only, sell-all
и mode-specific settlement policy. Не добавляйте эти значения как самодельные nullable
поля. Оба supported mode используют причинно доступный
historical curve и никогда не меняют его и не пересчитывают чужие сделки.
Virtual mode ослабляет только sell real-SOL solvency: successful sell хранит
venue-funded и явную synthetic-funded части gross output. Buy real-token
availability, lifecycle, slippage, fee, account и migration checks не
ослабляются, а synthetic proceeds не доказывают on-chain исполнение. Полный JSON
walkthrough: [getting-started.ru.md](getting-started.ru.md).

Для смены mode создайте и resolve-ните новый draft v3 вместо ручного
редактирования ResolvedRunSpec или переинтерпретации v2. Mode и
settlement policy меняют logical/order/round-trip identities, но Dataset,
Snapshot и ReplayPack IDs остаются прежними: новый prepare или compile-replay
не нужен.

## Один бэктест

`run` и `run-backtest` — два имени одной semantics:

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

Они не меняют semantic `logical_run_id`, но входят в physical provenance.
UI/API передают их отдельным `RunPhysicalSettingsCommand` в
`RunBacktestCommand`; canonical durable job имеет schema
`backtest.run-job/v2`. Эти поля не входят в
`pumpfun-sniping-run-draft/v3`, даже когда одна форма собирает оба набора.
Optimized backend fail closed для любой неподдерживаемой strategy/protocol/
latency/risk surface.

Для Sniping `reference-pumpfun-sniping-v1` является readable oracle и работает
с canonical Parquet или ReplayPack. `numpy-mmap-pumpfun-sniping-v1` — отдельный
allowlisted SoA/mmap backend; он требует ReplayPack и не является generic
заменой reference engine. Оба исполняют один run последовательно в одном child
process.

## Sweep

`sweep` и `run-sweep` запускают независимые resolved attempts:

```bash
backtest sweep resolved-sweep.json --config configs/local.toml
```

Один stateful run никогда не делится по time shards. Admission определяет
параллелизм по measured host memory, CPU/native threads и I/O budget.
`ResolvedSweepSpec` должен быть canonical JSON; удобнее собрать его typed
UI/API resolver-ом и сохранить поле `resolved_sweep_spec` в canonical compact
form.

## Exact ML lifecycle

| Команда | Результат |
|---|---|
| `build-features REQUEST.json` | Point-in-time FeatureSet |
| `build-universe REQUEST.json` | Point-in-time Universe |
| `build-labels REQUEST.json` | Training-only LabelSet |
| `train REQUEST.json` | Exact integer-linear ModelBundle |
| `build-model-schedule REQUEST.json` | Walk-forward ModelSchedule |
| `predict REQUEST.json` | Frozen PredictionSet |

Пример direct execution:

```bash
backtest build-features build-features.json --config configs/local.toml
```

Пример queue execution при работающем `serve`:

```bash
backtest build-features build-features.json \
  --enqueue \
  --idempotency-key features-snapshot-a-v1 \
  --config configs/local.toml
```

Labels физически недоступны Strategy API. Текущий exact runtime поддерживает
frozen или bounded precomputed embedded integer-linear inference. Tree/ONNX/GPU
tolerance и stateful modes не включены.

## Job queue

| Команда | Назначение |
|---|---|
| `submit-job` | Advanced: durably enqueue exact job type/payload |
| `jobs` | Bounded список operational records |
| `get-job JOB_ID` | Текущий state/version одной job |
| `cancel-job JOB_ID` | Durable cancel request |
| `retry-job JOB_ID` | Новая attempt для failed/interrupted immutable command |

```bash
backtest jobs --state RUNNING --limit 50 --config configs/local.toml
backtest get-job <job_id> --config configs/local.toml
backtest cancel-job <job_id> --config configs/local.toml
backtest retry-job <job_id> --config configs/local.toml
```

`submit-job` требует `--type`, `--payload` и stable
`--idempotency-key`; repeatable `--input-artifact` передаёт exact inputs.
Обычным пользователям безопаснее typed command aliases или UI.

Одинаковый idempotency key с одинаковым canonical payload возвращает
существующую job. Тот же key с другим payload получает conflict.

## Results и lineage

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

List endpoints возвращают bounded summary: scalar metrics, hashes, counts и
warnings. Полные Parquet/ReplayPack bytes через CLI/API list response не
раздаются; authoritative details находятся в verified manifest.

`show-run-summary` и `list-roundtrips` принимают именно exact committed
Pump.fun Sniping Run artifact ID, а не `logical_run_id` или path. Summary
возвращает `pumpfun-sniping-run-summary/v3`: counts/hashes, execution/settlement
policies, fee/deposit/slippage totals, gross/venue/synthetic settlement totals,
realized PnL и valuation completeness. При unvalued open
position `economic_pnl_atomic` остаётся `null`, а
`valued_economic_pnl_subtotal_atomic` явно остаётся partial. Round-trip pages используют keyset
cursor `BOUNDARY_ORDINAL:ROUNDTRIP_ID`, максимум 200 строк. Reader проверяет
`successful-run/v3`, descriptors и canonical digests до выдачи данных;
`roundtrips.parquet` и `final_balances.parquet` целиком через API не выдаются.
`pumpfun-roundtrips/v4` показывает `account_profile_id`, ordered
`account_components[]`, execution mode, liquidity evidence и actual
venue/synthetic settlement. Potential reference/landing и projected MTM
shortfall остаются отдельно от фактически settled synthetic funding. Leg failure
codes остаются явными, а cashflow сверяется с correlated `run-ledger/v2`.
Committed summary v2/round-trip v3 остаются читаемыми как исходные immutable
schemas.

## Retention и GC

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

`gc-purge` physically удаляет уже перемещённый trash batch только после
configured grace period. Всегда начинайте с dry-run и не удаляйте `var/`
вручную.

## Backup и restore drill

После настройки `[backup]` на другом physical device/host:

```bash
backtest backup --config configs/local.toml
backtest restore-verify <backup_cut_id> --config configs/local.toml
```

Backup command публикует consistent SQLite + artifact closure generation.
Копия в другой directory того же NVMe не считается durability backup.

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

Допустимые workloads перечисляет `backtest benchmark --help`. Capacity 7/30
в harness может означать repeated independent base stream и не является
утверждением о representative stateful market history. `EXTERNALLY_COLD`
требует внешнего verified cache-eviction controller.

## Web UI и Control API

```bash
backtest serve --config configs/local.toml
```

UI находится на `http://127.0.0.1:<control.port>`, API — под `/api/v1` на том же
origin. Работают typed prepare/backtest/sweep/ML forms, queue/progress,
cancel/retry, run comparison, artifacts/lineage и resource status. Отдельная
Pump.fun Sniping form получает schema через run-contract discovery, принимает
decimal strings как `BigInt`, показывает fixed semantics read-only и позволяет
выбрать reference либо dedicated optimized backend. Кнопка **Results** открывает
общий React-экран **Strategy results** для Sniping, Copy Buy и FirstSwap:
проверенная сводка, ограниченные диаграммы всего прогона, аналитика входов/выходов,
одна keyset-страница из 25 записей и детали сделки. API допускает до 200 записей.
English — язык по умолчанию; **Language** в меню включает русский. Ни язык,
ни оформление не меняют command. Полный PnL не заменяется нулём/subtotal.

Contract discovery предоставляет форму v3 с обязательным выбором между
`EXOGENOUS_REPLAY` и `EXOGENOUS_VIRTUAL_SETTLEMENT`. Virtual settlement
постоянно показывает предупреждение: SOL, покрывающий недостаток ликвидности,
является синтетическим и доступен для трат только в моделируемом кошельке;
это не доказывает возможность соответствующей продажи on-chain.

Общие read-only routes под `/api/v1/run-artifacts/{id}`: `strategy-summary`,
`strategy-dashboard`, `entries`, `entries/{entry_id}`, `entries/{entry_id}/chart`
и `analytics`. Chart/detail требуют `boundary_ordinal`; страницы используют
тот же двухчастный cursor. Параметры и лимиты определены в английском
[§34.2](architecture-deep-dive.md#342-web-ui). Старые API остаются совместимыми.

Основные Sniping API routes:

| Method и path | Назначение |
|---|---|
| `GET /api/v1/run-contracts` | Typed discovery editable/fixed run contract |
| `POST /api/v1/run-specs/resolve` | Resolver strict draft в exact `ResolvedRunSpec` |
| `POST /api/v1/backtests` | Быстрый durable submit, без выполнения run в request |
| `GET /api/v1/run-artifacts/{id}/summary` | Bounded verified summary exact run artifact |
| `GET /api/v1/run-artifacts/{id}/roundtrips` | Keyset page, `limit=1..200` |

У HTTP roundtrip cursor две части:
`after_target_boundary_ordinal` и `after_roundtrip_id`; их передают либо обе,
либо ни одну. Это те же значения, которые CLI кодирует одной строкой
`BOUNDARY_ORDINAL:ROUNDTRIP_ID`.

HTTP request не выполняет тяжёлую job. Disconnect или reload браузера не
отменяет child process. SSE не реализован; current UI использует bounded
polling.

Отправка формы по-прежнему требует точных four-stream evidence для выбранного
диапазона источника. Включённые в репозиторий примеры с `UNKNOWN` и hermetic
HTTP/static tests не заменяют source receipts. Отсутствующие или несовместимые
доказательства приводят к typed отказу до исполнения.

## Direct и queued execution

| Состояние | Как запускать |
|---|---|
| `serve` выключен | Direct heavy command; CLI ждёт terminal state |
| `serve` запущен | UI/API либо supported CLI `--enqueue` |
| Нужен только status/result | Query CLI автоматически проверяет и использует running loopback controller |

Direct и API paths создают один `ResolvedJobSpec` и запускают тот же isolated
child. Второй controller для одного `data_root` запрещён. Недоступный или
mismatched lock owner не вызывает скрытый local fallback.

## Exit codes и ошибки

CLI печатает machine-readable safe JSON error без raw traceback, credentials и
absolute secret paths. Типичные причины:

- `LOCAL_CONFIG_INVALID` — TOML или resource invariant неверен;
- capability/projection mapping отсутствует или не совпадает;
- exact artifact/closure не найден либо не прошёл verification;
- fidelity недостаточна для reference strategy;
- другой controller владеет `data_root`;
- host admission не разрешает heavy child;
- backup target не настроен на другом physical device/host.

Не заменяйте typed failure на `latest`, меньшую fidelity или synthetic result.

## Полезные проверки

```bash
backtest --help
backtest serve --help
backtest run --help
backtest jobs --config configs/local.toml
```

Путь от source до первого run с примерами JSON:
[getting-started.ru.md](getting-started.ru.md).

---

**Язык:** [English](cli-reference.md) · Русский
