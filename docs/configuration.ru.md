# Конфигурация проекта

Host configuration хранится в TOML и не входит в semantic identity run. Exact
strategy/execution/ML configs закрепляются отдельно внутри resolved specs и
artifact manifests.

## Где находятся файлы

| Файл | Назначение | Можно коммитить |
|---|---|---|
| `configs/local-16gb.toml` | Базовый host profile 16 GB для Linux или macOS | Да, без secrets |
| `configs/local-32gb.toml` | Базовый host profile 32 GB для Linux или macOS | Да, без secrets |
| `configs/local-windows-wsl2-16gb.toml` | Базовый профиль 16 GB для Windows 11 через WSL2/Ubuntu | Да, без secrets |
| `configs/local.toml` | Настройки конкретного PC/server | Нет, gitignored |
| `configs/indexer-capabilities.example.toml` | Структурный пример четырёх Pump source streams с `UNKNOWN` evidence | Да |
| `configs/indexer-projections.example.toml` | Согласованный пример четырёх canonical event projections | Да |
| `configs/indexer-capabilities.local.toml` | Проверенный raw mapping для fixed `pumpfun-indexer-v1` | Нет, gitignored |
| `configs/indexer-projections.local.toml` | Canonical mapping после installed fixed normalizer | Нет, gitignored |
| `.env` | Локальные secrets, если используется внешним loader | Нет, gitignored |

CLI по умолчанию читает `configs/local-16gb.toml`. Для воспроизводимой
эксплуатации всегда передавайте выбранный файл явно:

```bash
backtest <command> --config configs/local.toml
```

Один CLI и configuration contract работают на native Linux x86_64, macOS
arm64 и Windows 11 x86_64 через WSL2 с Ubuntu x86_64. Native Win32 сейчас не
поддерживается и не проверен. На Windows начните с
`configs/local-windows-wsl2-16gb.toml`, запускайте CLI внутри Ubuntu, а
repository и `data_root` храните внутри Linux filesystem WSL. Operational
paths на `/mnt/c`, `/mnt/d`, других DrvFS mounts и network mounts не
поддерживаются.

Не помещайте password, token или DSN в TOML. `secret_ref` содержит только имя
environment variable.

## `[paths]`

| Параметр | Смысл |
|---|---|
| `data_root` | Корень SQLite, immutable artifacts, runs, tmp и locks |

Relative path разрешается относительно директории, из которой запущена
команда. Для другого NVMe задайте абсолютный путь. Один artifact staging и
final directory должны оставаться на одном filesystem, иначе atomic rename не
гарантирован.

Перенос `data_root` не меняет logical hashes, но нельзя вручную копировать
отдельные files без manifests и проверки. Для durability используйте backup
protocol.

На Windows/WSL2 поддерживаемый relative setting вроде `data_root = "var"`
разрешается внутри WSL repository. Absolute path также должен быть Linux path
внутри WSL filesystem, а не `C:\...` и не его отображение `/mnt/c/...`.

## `[resources]`

| Параметр | Смысл |
|---|---|
| `max_aggregate_child_memory_mb` | Общий потолок private memory всех child processes |
| `max_builder_memory_mb` | Внутренний memory limit builder/analytical operation |
| `builder_peak_private_memory_mb` | Консервативная admission-оценка peak builder RSS |
| `run_peak_private_memory_mb` | Admission-оценка peak private RSS одного run |
| `max_parallel_runs` | Максимум независимых run processes после admission |
| `tmp_quota_gb` | Общая квота temporary data |
| `max_run_tmp_gb` | Temporary quota одной run attempt |
| `max_run_output_gb` | Максимальный output одной run attempt |
| `disk_low_watermark_gb` | Ниже этого free-space builder не стартует |
| `disk_emergency_watermark_gb` | Emergency boundary для остановки builders |
| `native_threads_per_process` | Native threads одного child |
| `memory_safety_reserve_mb` | RAM, которую admission оставляет как safety reserve |
| `page_cache_floor_mb` | Резерв для OS page cache/mmap |
| `host_staging_output_reserve_mb` | Резерв host-level staging/output peaks |
| `fixed_shared_overhead_mb` | Измеренный fixed/shared overhead host |
| `memory_breach_samples` | Последовательные memory samples до breach action |
| `swap_activity_samples` | Последовательные swap samples до breach action |

Встроенные проверки требуют:

- все лимиты — положительные integers;
- peak одного child не выше aggregate ceiling;
- `run_peak * max_parallel_runs` не выше aggregate ceiling;
- builder peak выше его внутреннего memory limit;
- emergency watermark не выше low watermark;
- параллельная temporary demand помещается в `tmp_quota_gb`.

Значения профилей — начальные консервативные limits, а не обещание скорости.
Меняйте их после измерения private RSS, page faults, swap и I/O. Нулевая
доступная child budget не ломает запуск UI, но heavy jobs останутся в queue до
появления безопасной capacity.

## `[replay]`

| Параметр | Смысл |
|---|---|
| `backend` | Physical execution backend |
| `batch_rows` | Rows в одном bounded reader batch |
| `readahead` | Число bounded read-ahead batches |
| `output_buffer_rows` | Размер буфера audit/result output |
| `threads` | Native threads run process |

Поддерживаемые backend values:

- `reference-python-v1` — общий читаемый reference path;
- `numpy-mmap-first-swap-exact-v1` — узкий optimized exact path только для
  совместимого FirstSwap + constant-product + static-risk surface;
- `reference-pumpfun-sniping-v1` — readable Pump.fun Sniping oracle для
  canonical Parquet или ReplayPack;
- `numpy-mmap-pumpfun-sniping-v1` — dedicated Pump.fun Sniping SoA/mmap path,
  которому нужен exact ReplayPack и allowlisted semantic closure.

`[replay].threads` обязан совпадать с
`[resources].native_threads_per_process`. Batch/readahead/backend являются
physical settings и не меняют `logical_run_id`, но входят в provenance
physical attempt.

## `[retention]`

| Параметр | Смысл |
|---|---|
| `minimum_artifact_age_seconds` | Минимальный возраст GC candidate |
| `trash_grace_seconds` | Пауза между move-to-trash и physical delete |
| `maximum_sweep_gb` | Верхняя граница bytes одной GC sweep |

GC всегда остаётся reachability-based. Возраст не разрешает удалить pinned,
referenced, leased или active artifact. Сначала выполняйте `backtest gc`
(dry-run), затем при проверенном плане — `backtest gc --execute`.

## `[backup]`

Секция необязательна:

```toml
[backup]
target_root = "/path/on-another-device/backtest-backup"
restore_verify_parent = "/path/on-another-device/backtest-restore-drills"
allow_same_device_for_drill = false
target_encryption_verified = true
```

Эти paths являются примерами. На Linux, macOS и Ubuntu под WSL2 замените их на
paths другого physical device/host, смонтированного в активный runtime. Вторая
directory на том же NVMe не является backup. На Windows/WSL2 нельзя
использовать DrvFS для operational `data_root`; явно проверенный внешний target
допустим только при выполнении different-device/host и encryption contract.

| Параметр | Смысл |
|---|---|
| `target_root` | Root backup generations на другом physical device/host |
| `restore_verify_parent` | Отдельный parent для empty-directory restore drills |
| `allow_same_device_for_drill` | Разрешить same-device только как drill, не как backup claim |
| `target_encryption_verified` | Явное подтверждение шифрования external target |

`target_root` и `restore_verify_parent` задаются вместе и не могут
пересекаться. Другая папка того же NVMe не считается backup.

## `[planning]`

| Параметр | Смысл |
|---|---|
| `max_remote_gb` | Host ceiling для remote bytes одного dataset request |
| `max_local_gb` | Host ceiling ожидаемого local dataset output |
| `max_days` | Максимальный requested day range |
| `staging_reserve_gb` | Обязательный свободный staging reserve |
| `max_total_blocks` | Максимальная суммарная ширина capability extraction ranges в block ordinals |
| `max_total_shards` | Максимальное число shards в плане |
| `max_shard_blocks` | Максимальная ширина одного half-open shard в block ordinals |
| `max_query_execution_seconds` | Ceiling ClickHouse execution time |
| `max_query_memory_mb` | Ceiling ClickHouse query memory |
| `max_query_result_rows` | Ceiling rows одного query |

Request/API может только сузить эти ceilings, но не повысить их. Remote
estimate остаётся `UNKNOWN`, если verified estimator не настроен; это нельзя
переименовывать в нулевую стоимость.

Суммарная ширина capability ranges учитывает каждый запрашиваемый stream:
launch использует decision range, а clock/trade/lifecycle — evidence range.
`max_total_blocks` должен покрывать эту сумму. Это host admission ceiling,
а не доказательство source fidelity, размер одного query или число уникальных
blocks.

Для bounded source evidence отдельной TOML-секции нет. `inspect-source` берёт
`max_query_execution_seconds`, `max_query_memory_mb` и
`max_query_result_rows` из этого host profile. Один requested evidence range
fixed composition внутренне делит на contiguous subshards не шире 4096 blocks;
это не нужно и нельзя вручную описывать в TOML. Adapter применяет к каждому
внутреннему query более строгие hard caps: до 60 seconds, 512 MiB memory,
100000 result rows, 64 MiB result bytes, 2000000 read rows и 1 GiB read bytes,
один thread. Эти пределы нельзя повысить configuration option.

## `[control]`

| Параметр | Смысл |
|---|---|
| `host` | Bind address: только `127.0.0.1`, `::1` или `localhost` |
| `port` | Локальный TCP port `1..65535` |
| `progress_interval_ms` | Минимальный interval coalesced progress |
| `max_request_mb` | Hard limit HTTP request body |
| `secure_cookie` | Добавить cookie flag `Secure` при HTTPS proxy |

Текущие checked-in profiles используют разные порты: 16 GB — `8081`, 32 GB —
`8080`. Источник истины для адреса — выбранный local TOML.
Windows/WSL2 profile использует тот же loopback-only control contract;
получившийся localhost URL можно открыть в браузере на Windows host.

Прямой bind на `0.0.0.0` запрещён. Для доступа с другого устройства оставьте
API на loopback и используйте authenticated TLS reverse proxy либо VPN/SSH
tunnel. При HTTPS включите `secure_cookie = true`.

Localhost UI не имеет формы логина: OS user boundary и случайная session cookie
являются базовой защитой. Basic Auth prompt обычно означает, что порт уже занят
другим приложением.

## `[source]`

| Параметр | Смысл |
|---|---|
| `source_id` | Стабильное logical имя индексера |
| `host` | Hostname/IP без URL scheme и path |
| `port` | ClickHouse HTTP/HTTPS port |
| `database` | Default database |
| `username` | Read-only user |
| `secret_ref` | Имя environment variable с password |
| `capabilities_file` | Secret-free raw capability mapping; для этого индексера — exact fixed-profile declaration |
| `projections_file` | Canonical projection mapping после установленного normalizer; обязателен для prepare |
| `secure` | Использовать TLS и certificate verification |
| `verified_private_tunnel` | Явно подтверждённый private transport для non-loopback endpoint |
| `allow_insecure_remote_http` | Явно принять риск прямого plaintext HTTP к non-loopback read-only source |

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

Здесь `127.0.0.1:18123` может быть локальным концом SSH tunnel. Endpoint,
username и secret никогда не входят в run/artifact IDs; password не должен
попадать в config, query ID, logs, exceptions или manifests.

Для metadata-only `inspect-source` достаточно `capabilities_file`. Bounded
exact inspection также требует установленную projection/normalizer composition,
потому что receipt связывает query, normalizer и projector digests.
`prepare-dataset` требует обе настройки. Web UI можно открыть и без них, но
это не создаёт source admission.

Безопасный default — `allow_insecure_remote_http = false`. Для remote source
допустим один transport mode:

- `secure = true` и проверяемый TLS;
- `verified_private_tunnel = true` для аутентифицированного VPN/SSH transport к
  non-loopback endpoint либо обычный loopback endpoint локального SSH tunnel;
- только если других вариантов нет — direct non-loopback HTTP с
  `secure = false`, `verified_private_tunnel = false` и явным
  `allow_insecure_remote_http = true`.

Последний вариант не обеспечивает защиту: password, запросы и результаты могут
быть перехвачены, прочитаны или изменены посредником. При старте source-facing
operation runtime обязан показать warning без endpoint и credential. Opt-in
взаимоисключается с `secure = true` и `verified_private_tunnel = true`, а на
loopback он не нужен и отклоняется. Он действует только для read-only
`inspect-source`, optional estimate и `prepare-dataset`; Control API остаётся
loopback-only. Это operational host setting: он не входит в run/artifact
identity и не повышает fidelity, finality, completeness или consistency.

### Выбор источника Copy Buy

`[source.copy_selection]` в локальном ignored TOML задаёт 1–128 отсортированных
уникальных Solana `signing_wallets`, typed `decision_range` и `history_range`.
History начинается не позже decision и заканчивается на той же исключающей
верхней границе, с теми же NetworkId/PositionSchemaId. Для старых токенов нужна
полная ограниченная история создания/начального состояния, а evidence должен
доказать отдельный правый settlement tail всех четырёх попыток продажи.

Команды остаются `inspect-source`, `plan-dataset`, `prepare-dataset`. Copy-only
receipt v3, inspection v6, plan v5 и DatasetSpec v6 фиксируют точную выборку;
Sniping snapshot не переинтерпретируется. См. полный шаблон и ограничения в
[английском руководстве](configuration.md#copy-buy-source-selection).

### Capability mapping

Capability file описывает transport/source schema, а не protocol math:

- versioned format/schema;
- один `NetworkId` вида `family:immutable-chain-reference` и один
  `PositionSchemaId` для всего mapping;
- logical capability ID и protocol version;
- source database/table;
- logical-to-physical columns;
- authoritative logical `block_ordinal` column; physical Solana `slot`
  остаётся только правой стороной adapter mapping;
- mandatory columns;
- proven total/keyset key и `order_by` либо их отсутствие;
- отдельно доказанные identity/order/state/fees/finality/completeness/
  consistency fidelity;
- optional proven-safe UTC pruning superset.

Для `BLOCK_CLOCK` normative logical field называется `transaction_count`.
Physical source column может называться `tx_count`, но это только правая часть
adapter mapping и не является доказательством, что count включает successful,
failed и vote transactions.

Нельзя ставить `EXACT`, `COMPLETE_TO_WATERMARK`, `FINALIZED` или отдельный
Pump proof только по названию столбца. `inspect-source` фиксирует live
metadata/fingerprint, но обычная local schema validation не повышает upstream
fidelity. Checked-in example намеренно остаётся `UNKNOWN` и не является
production evidence.

Все поля `[capabilities.proofs]` в static TOML обязаны быть `UNKNOWN`.
`PROVEN` и `REFUTED` являются результатами generated bounded inspection, а не
operator assertions; parser отклоняет их в config.

Для адаптера `pumpfun-indexer-v1` local mapping должен в точности совпасть с
installed profile `pumpfun-indexer-v1`: четыре raw capabilities используют
`protocol_version = "pumpfun-indexer-v1-raw"` и
`capability_schema_version = "pumpfun-indexer-v1-raw-v1"`. Это внутренние
physical version tokens. После fixed SQL и Pump-owned normalizer
`pumpfun-indexer-v1-live-normalizer-v2` inspection публикует другие logical
versions:

| Stream | Logical protocol | Logical schema |
|---|---|---|
| `BLOCK_CLOCK` | `solana-block-clock-v1` | `solana-block-clock-normalized-v1` |
| `TOKEN_LAUNCH` | `pump-program-static-fee-v1` | `pumpfun-token-launch-normalized-v2` |
| `PUMP_CURVE_TRADE` | `pump-program-static-fee-v1` | `pumpfun-curve-trade-normalized-v2` |
| `PUMP_CURVE_LIFECYCLE` | `pump-program-static-fee-v1` | `pumpfun-curve-lifecycle-normalized-v2` |

Plan requirements используют logical versions из inspection artifact, а не
raw tokens из local TOML.

### Bounded source evidence

Evidence range является параметром конкретного inspection invocation, а не
долгоживущей настройкой `[source]`:

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block <inclusive_block_ordinal> \
  --evidence-to-block <exclusive_block_ordinal> \
  --decision-from-block <inclusive_target_block_ordinal> \
  --decision-to-block <exclusive_target_block_ordinal>
```

Обе evidence-границы передаются вместе и образуют typed half-open `BlockRange`
с NetworkId/PositionSchemaId из capability mapping. Обе decision-границы также
задаются только парой, требуют evidence range и должны лежать внутри него.
Decision range определяет target/universe window; evidence range дополнительно
покрывает capability-specific settlement tail. Если decision flags опустить,
весь evidence range станет decision range.

Условный пример: decision range `[1000000,1004096)` и tail в 4096 blocks.
Эти координаты не обозначают допущенный dataset; замените их диапазоном,
который вы намерены проверить.

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block 1000000 \
  --evidence-to-block 1008192 \
  --decision-from-block 1000000 \
  --decision-to-block 1004096
```

Этот cut соответствует plan с `requested_days = 1`, maximum sell delay 200
transactions и `maximum_tail_blocks = 4096`. `requested_days` остаётся
budget operand plan, а не способом автоматически преобразовать UTC dates в
block ordinals.

Composition layer разбивает этот большой cut на internal subshards ≤4096
blocks. Launch query покрывает только decision range, остальные три streams —
весь evidence range. Команда публикует `source-inspection/v5` с четырьмя
embedded `bounded-source-evidence/v2` receipts: по одному агрегированному
receipt на capability. Каждый receipt связывает все internal query
fingerprints, exact ranges, mapping/query/normalizer/projector digests,
aggregate result digest и bounded observations.

Local TOML не выдаёт admission. Fixed evaluator генерирует `PROVEN` только
после успешной проверки contiguous block/sentinel coverage, global transaction
clock, launch universe, bundled-buy placeholder, curve transitions, fee
rounding и lifecycle order на одном cut. Malformed, missing, conflicting или
unknown данные дают typed fail-closed до публикации допустимого inspection.
Bundled placeholder считает только последующий successful `BUY` с той же парой
signature/mint после create в той же transaction. Successful `SELL` в этой
transaction применяется к curve atomically, но не классифицируется как bundled
buy; `bundled_buys_count` не используется как proof.

Raw `pumpfun_v2_swaps` row не содержит отдельных protocol/creator fee columns.
Fixed normalizer выводит 95/30 components из exact curve SOL leg по pinned
effective-dated integer formula/profile. Receipt связывает formula/profile и
normalizer digest как derived-not-observed provenance; TOML не может выдать
эти values за наблюдавшиеся source transfers.

Каждый диапазон проходит собственную проверку. Пропущенные переходы или
несогласованное состояние дают typed отказ, например
`CURVE_TRANSITION_MISMATCH`, до публикации inspection. Флаг TOML или ручной
`PROVEN` не устраняет такую ошибку источника.

Evidence v1, source inspection v1–v4, dataset plan v1–v3 и DatasetSpec v1–v4
нельзя переиспользовать под этим контрактом: требуется новая preparation.

Evidence range нужно выбирать с учётом DatasetSpec v5 settlement
requirement. Его `maximum_tail_blocks` — hard cap one-shot extraction, а не
доказательство достаточности. Planner отклоняет requested tail выше
cap, а `prepare-dataset` до публикации root проверяет actual maximum
settlement path. Точная request structure приведена в
[getting-started.ru.md](getting-started.ru.md).

### Projection mapping

Projection file связывает уже нормализованный capability с canonical event
kind и versioned protocol payload schema. Он не описывает physical ClickHouse
expressions и не заменяет fixed normalizer. Текущая Pump.fun пара использует:

| Capability stream | `event_kind` | Payload schema |
|---|---|---|
| `BLOCK_CLOCK` | `BLOCK` | Не требуется |
| `TOKEN_LAUNCH` | `TOKEN_LAUNCH` | `pump-launch-state-v1` |
| `PUMP_CURVE_TRADE` | `VENUE_TRADE` | `pump-trade-state-v1` |
| `PUMP_CURVE_LIFECYCLE` | `VENUE_LIFECYCLE` | `pump-lifecycle-state-v1` |

Полная согласованная пара примеров находится в
[`indexer-capabilities.example.toml`](../configs/indexer-capabilities.example.toml)
и
[`indexer-projections.example.toml`](../configs/indexer-projections.example.toml).
Она показывает структуру всех четырёх streams, но намеренно содержит
`UNKNOWN` evidence. Например, launch declaration имеет форму:

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

Правая сторона каждой пары — logical column из capability mapping, а не
обязательно физическое имя ClickHouse column. Остальные обязательные state и
lifecycle mappings перечислены в example. Pump projector требует ровно один
stream каждого вида, successful launch field и доказанный within-transaction
order; missing/unsupported semantics fail closed.

## Secrets и shell environment

Пример текущей Bash session на Linux, macOS или Ubuntu под WSL2:

```bash
export BACKTEST_INDEXER_PASSWORD='your-indexer-secret'
backtest inspect-source --config configs/local.toml
```

Если используете `.env`, загрузите его внешним shell/tooling до запуска. Сам
проект не должен сериализовать `.env` в artifacts или backup export. Не
передавайте password через CLI argument: он попадает в process history.
На Windows задавайте variable внутри WSL Ubuntu shell, где работает runtime;
не храните secret в checked-in PowerShell или TOML files.

---

**Язык:** [English](configuration.md) · Русский
