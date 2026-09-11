# Начало работы

Эта инструкция доводит окружение от чистой checkout до запуска Web UI и
показывает полный network-aware путь Pump.fun Sniping: source inspection,
selective snapshot, ReplayPack, strict run resolution и просмотр сделок.
Команды выполняются из корня репозитория.

## 1. Системные требования

Поддерживаемые runtime targets:

- Linux x86_64;
- macOS arm64;
- Windows 11 x86_64 через WSL2 с Ubuntu x86_64.

Native Win32 execution сейчас не поддерживается и не проверен. На Windows
храните repository и operational `data_root` внутри Linux filesystem WSL,
например под `~/backtest`. Не используйте `/mnt/c`, `/mnt/d`, другие DrvFS
mounts или network mounts для operational artifacts.

Для всех платформ также нужны:

- Python `>=3.13,<3.14`;
- `uv` в `PATH`;
- 16 GB RAM минимум, 32 GB рекомендовано;
- локальный SSD/NVMe для `data_root`;
- доступ к ClickHouse нужен только для inspection и подготовки dataset.

Docker, Node.js и отдельные database servers для обычного запуска не нужны.
DuckDB и SQLite используются как embedded libraries внутри Python processes.

## 2. Установка окружения

На Linux или macOS выполните:

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
python --version
backtest --help
```

На Windows сначала установите и откройте Ubuntu из PowerShell:

```powershell
wsl --install -d Ubuntu
wsl --distribution Ubuntu
```

После первой команды Windows может потребовать restart. Клонируйте или
скопируйте repository в Linux filesystem WSL, откройте его root в Ubuntu shell
и выполните те же Bash-команды:

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
python --version
backtest --help
```

Когда checkout находится в `~/backtest`, запустите полный repository-provided
profile smoke прямо из Windows PowerShell:

```powershell
wsl --distribution Ubuntu --cd '~/backtest' -- bash scripts/windows-wsl2-smoke.sh
```

Эквивалентная обёртка — `scripts/setup-windows-wsl2.ps1`, если script
запускается из доступной Windows копии checkout.

Ожидаемая версия Python — `3.13.x`. Можно не активировать окружение и вызывать
команды как `.venv/bin/backtest` на каждом supported runtime, включая Ubuntu
под WSL2.

## 3. Локальный профиль

Выберите исходный профиль:

- `configs/local-16gb.toml` — не более одного run child одновременно;
- `configs/local-32gb.toml` — больше aggregate memory и не более двух
  независимых run children при достаточных измеренных ресурсах;
- `configs/local-windows-wsl2-16gb.toml` — Windows 11/WSL2 profile для 16 GB;
  используйте его только из Ubuntu внутри WSL2 и храните `data_root` в Linux
  filesystem WSL.

Если `configs/local.toml` ещё не настроен, скопируйте профиль в локальный
gitignored файл:

```bash
cp configs/local-16gb.toml configs/local.toml
```

На Windows 11/WSL2 из Ubuntu shell:

```bash
cp configs/local-windows-wsl2-16gb.toml configs/local.toml
```

Отредактируйте `configs/local.toml`. Минимально проверьте:

```toml
[paths]
data_root = "var"

[control]
host = "127.0.0.1"
port = 8081

[planning]
# Illustrative acquisition budget across all requested capabilities.
max_total_blocks = 65536
max_shard_blocks = 4096

[source]
source_id = "my-indexer"
host = "127.0.0.1"
port = 8123
database = "default"
username = "readonly-user"
secret_ref = "BACKTEST_INDEXER_PASSWORD"
secure = false
verified_private_tunnel = false
allow_insecure_remote_http = false
```

`data_root` и остальные relative paths разрешаются относительно текущей
рабочей директории, поэтому команды рекомендуется всегда запускать из корня
проекта. Не копируйте baseline поверх уже настроенного `configs/local.toml`.
Примеры ниже используют условные source ID и block ranges. Настройте
локальные mappings под свой источник и выберите ограниченный диапазон;
увеличение resource ceiling само по себе не допускает источник.
Полное описание полей: [configuration.ru.md](configuration.ru.md).

## 4. Запуск Web UI без индексера

React UI открывается на английском; **Language → Русский** переключает язык,
**Appearance** — оформление. **Launch strategy** содержит выбор Sniping, Copy Buy
и FirstSwap, с раскрывающимися разделами комиссий, аккаунтов и ресурсов.

![Форма Copy Buy на английском языке в тёмной теме, изолированные тестовые данные](assets/launch-strategy.png)


UI можно открыть до настройки live source:

```bash
backtest serve --config configs/local.toml
```

Откройте `http://127.0.0.1:<control.port>`. Например, для конфигурации выше:

```text
http://127.0.0.1:8081
```

Логин и пароль не нужны. Localhost UI использует автоматически созданную
HttpOnly session cookie. Остановить сервер можно `Ctrl+C`; уже завершённые
committed artifacts и durable queue останутся в `data_root`.

Если адрес показывает чужой интерфейс или Basic Auth, проверьте владельца
порта и выберите другой `[control].port`:

На Linux или Ubuntu под WSL2:

```bash
ss -ltnp
```

На macOS:

```bash
lsof -nP -iTCP:8081 -sTCP:LISTEN
```

В Windows PowerShell для проверки проброшенного host-side порта:

```powershell
Get-NetTCPConnection -LocalPort 8081 -State Listen
```

Не вводите credentials в prompt неизвестного процесса.

В режиме `serve` один process обслуживает API/static UI и один supervisor loop.
Тяжёлая job ставится в SQLite queue и исполняется отдельным child process, а не
в HTTP request.

## 5. Настройка индексера

Connection settings находятся в `[source]`, но пароль в TOML записывать нельзя.
Значение читается из переменной, имя которой задано в `secret_ref`:

Используйте Bash shell на Linux, macOS или Ubuntu под WSL2:

```bash
export BACKTEST_INDEXER_PASSWORD='your-indexer-secret'
```

Скомпрометированные учётные данные необходимо заменить до использования.

Кроме connection settings нужны два secret-free mapping:

- capability mapping: source table/columns, typed network identity, bounded
  query key и заявленная fidelity;
- projection mapping: перевод logical capability columns в canonical event
  kinds `BLOCK`, `TOKEN_LAUNCH`, `VENUE_TRADE` и `VENUE_LIFECYCLE`.

Создайте локальные файлы, например:

```text
configs/indexer-capabilities.local.toml
configs/indexer-projections.local.toml
```

Оба имени уже подходят под `.gitignore`. В настроенном локальном окружении эти
файлы уже описывают проверенную физическую схему индексера:

- capability mapping содержит ровно четыре raw stream контракта
  `pumpfun-indexer-v1`;
- projection mapping принимает только canonical columns, которые выдаёт
  установленный Pump-owned normalizer
  `pumpfun-indexer-v1-live-normalizer-v2`;
- bootstrap выбирает fixed SQL profile и normalizer только при полном совпадении
  четырёх таблиц, колонок и version tokens. Частично совпавший или изменённый
  mapping отклоняется.

Подключите оба файла в `configs/local.toml`:

```toml
capabilities_file = "configs/indexer-capabilities.local.toml"
projections_file = "configs/indexer-projections.local.toml"
```

TOML не содержит Pump formulas, joins или `CASE`: fixed adapter строит
explicit-column read-only SQL, Pump plugin проверяет и нормализует raw rows, и
только затем projection mapping создаёт canonical events. Exact digests этого
query/normalizer/projector pipeline входят в generated evidence и DatasetSpec.

Наличие этих двух local files означает, что software знает, **как проверить**
данный индексер. Оно не означает, что source уже допущен. Exact admission
требует успешно сгенерированные `bounded-source-evidence/v2` receipts для
конкретного диапазона; static TOML по-прежнему содержит только `UNKNOWN`.

Репозиторий содержит согласованную пару примеров:

- [`configs/indexer-capabilities.example.toml`](../configs/indexer-capabilities.example.toml);
- [`configs/indexer-projections.example.toml`](../configs/indexer-projections.example.toml).

Если local mappings ещё не настроены, examples можно использовать только как
шаблон:

```bash
cp configs/indexer-capabilities.example.toml configs/indexer-capabilities.local.toml
cp configs/indexer-projections.example.toml configs/indexer-projections.local.toml
```

Не выполняйте эти `cp` поверх уже настроенных
`configs/indexer-*.local.toml`: example-пара иллюстративная и не описывает
конкретную live-схему. Все checked-in proofs намеренно равны `UNKNOWN`, поэтому
копирование examples само по себе не разрешает exact Sniping run.
Схема и доказательства конкретного источника определяются через `inspect-source`.

Для remote endpoint выберите ровно один transport mode:

- `secure = true` с проверяемым TLS;
- non-loopback endpoint через уже аутентифицированный VPN/SSH tunnel с
  `verified_private_tunnel = true`;
- loopback endpoint локального tunnel.

Если индексер доступен только по прямому non-loopback HTTP и оператор явно
принимает риск, локальный config может содержать:

```toml
[source]
secure = false
verified_private_tunnel = false
allow_insecure_remote_http = true
```

Это аварийный opt-in, а не защита: password, запросы и результаты передаются
без шифрования и могут быть перехвачены или изменены. Runtime показывает
явный warning. Flag взаимоисключается с `secure = true` и
`verified_private_tunnel = true`, не нужен для loopback, не разрешает public
Control API/UI и не повышает source fidelity. Checked-in profiles оставляют
его `false`; включайте его только в gitignored `configs/local.toml`.

## 6. Inspection источника

Остановите `backtest serve`, если хотите выполнить mutating/direct CLI path.
Обычный metadata-only inspection запускается так:

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml
```

Команда читает metadata, сверяет настроенные capabilities и публикует локальный
`source-inspection/v5` artifact. Он не скачивает full mirror и не повышает
`UNKNOWN` только потому, что таблица или колонка существует.

Для Pump.fun Sniping нужен отдельный bounded evidence pass. Ниже приведены
условные координаты: они не обозначают допущенный dataset и должны быть
заменены диапазоном, который вы намерены проверить.

- decision range `[1000000, 1004096)`;
- evidence range `[1000000, 1008192)` с правым tail в 4096 blocks;
- пример budget: `requested_days = 1`, maximum sell delay 200 transactions.

`requested_days` проверяет budget limit и не преобразует даты в block
ordinals. Поэтому plan и inspection используют уже разрешённые exact ranges,
а не только UTC timestamps.

Обе пары границ half-open. Передайте decision range явно, чтобы Mayhem
classification и launch-universe digest считались только по target window, а
не по settlement tail:

```bash
backtest inspect-source \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml \
  --evidence-from-block 1000000 \
  --evidence-to-block 1008192 \
  --decision-from-block 1000000 \
  --decision-to-block 1004096
```

Обе evidence-границы и обе decision-границы задаются парами; decision range
должен лежать внутри evidence range. Если decision flags не указаны, CLI
считает весь evidence range decision range — для Sniping с tail это неверный
операторский выбор.

Один внешний evidence cut может быть больше 4096 blocks. Composition layer
детерминированно делит его на contiguous internal subshards не шире 4096
blocks. `TOKEN_LAUNCH` читается только по decision range; `BLOCK_CLOCK`,
`PUMP_CURVE_TRADE` и `PUMP_CURVE_LIFECYCLE` — по полному evidence range.
Каждый внутренний запрос остаётся bounded, streaming, read-only и использует
explicit columns. Наружу всё равно публикуется ровно один агрегированный
receipt на capability, а не отдельный artifact на каждый subshard.
Количество последовательных запросов зависит от выбранных диапазонов;
проверка evidence может занять больше времени, чем metadata-only inspection.

Только при успешном evidence pass ответ содержит `artifact_id`,
`evidence_receipt_ids`, `cut_evidence` и proof statuses. Тогда сохраните именно
`artifact_id` последнего inspection для `plan.json`. Каждый
`bounded-source-evidence/v2` receipt связывает source,
NetworkId/PositionSchemaId, capability/version, mapping/query digests,
точный evidence и decision ranges, fingerprints всех внутренних queries,
normalizer/projector digests, digest результата и число наблюдавшихся rows.
Дополнительно receipts закрепляют launch classification/exclusion, skipped-slot
sentinels и derived terminal lifecycle order. Credentials и сами source rows в
artifact не попадают.

Receipt доказывает факт и результат конкретной bounded проверки, но не
автоматически весь `pumpfun-sniping-source-v2`. Fixed evaluator выдаёт
`PROVEN` только после полного успешного прохода exact raw profile,
normalizer и cross-stream checks на одном cut. Gap, конфликт, неизвестный mode,
нарушение clock/curve/lifecycle/bundle semantics или несовпавший digest дают
typed отказ. Текущий bounded placeholder считает bundled buy только как
последующий successful `BUY` той же `signature` и `mint` в той же creation
transaction. Successful `SELL` в этой transaction тоже применяется к curve
atomically до decision, но не классифицируется как bundled buy; source
`bundled_buys_count` не является самостоятельным proof. Raw trade не содержит
отдельных protocol/creator fee columns: normalizer выводит 95/30 components из
exact curve SOL leg по pinned integer formula/profile, и receipt связывает их
как derived-not-observed provenance. Inspection artifact с ложным admission не
публикуется. Нельзя вручную менять static TOML proof с `UNKNOWN` на `PROVEN`:
parser это отклоняет.

Используйте content IDs, возвращённые вашими собственными командами.
При gap или несогласованном переходе состояния inspection и зависимые
артефакты не публикуются. Ручной `PROVEN` и отключение проверки не устраняют
ошибку источника.

Старые `bounded-source-evidence/v1`, `source-inspection/v1`–`v4`,
`backtest.dataset-plan/v1`–`v3` и DatasetSpec v1–v4 не мигрируются на месте:
при попытке reuse возвращается `REPREPARE_REQUIRED`.

## 7. План selective dataset

Создайте `plan.json`. Все значения с угловыми скобками ниже нужно заменить.
`network_id` содержит family и immutable chain reference; alias вроде
`solana:mainnet`, endpoint или имя индексера использовать нельзя. Текущий
Solana contract — `block32-transaction32-v1`, а ranges всегда half-open:
`[from_block_ordinal, to_block_ordinal)`.

```json
{
  "source_id": "my-indexer",
  "source_inspection_artifact_id": "<64-hex inspection artifact ID>",
  "network_id": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d",
  "position_schema_id": "block32-transaction32-v1",
  "from_block_ordinal": 1000000,
  "to_block_ordinal": 1004096,
  "warmup_blocks": 0,
  "settlement_tail_blocks": 0,
  "max_shard_blocks": 4096,
  "requested_days": 1,
  "requirements": [
    {
      "origin": "EXECUTION",
      "origin_id": "pumpfun-sniping-block-clock-v1",
      "capability_id": "pumpfun.block-clock.v2",
      "columns": ["block_ordinal", "block_time", "transaction_count", "block_hash"],
      "minimum_fidelity": {
        "identity": "EXACT",
        "ordering": "UNKNOWN",
        "state": "NONE",
        "fees": "UNKNOWN",
        "chain_finality": "FINALIZED",
        "completeness": "COMPLETE_TO_WATERMARK",
        "consistency": "SNAPSHOT_CONSISTENT"
      },
      "accepted_protocol_versions": ["solana-block-clock-v1"],
      "evidence_contracts": ["pumpfun-sniping-source-v2"],
      "warmup_blocks": 0,
      "settlement_tail_blocks": 0,
      "settlement_requirement": {
        "schema": "global-transaction-duration-roundtrip/v1",
        "target_stream": "TOKEN_LAUNCH",
        "settlement_streams": [
          "BLOCK_CLOCK",
          "PUMP_CURVE_LIFECYCLE",
          "PUMP_CURVE_TRADE"
        ],
        "initial_delay_transactions": 500,
        "minimum_duration_ns": 2000000000,
        "maximum_followup_delay_transactions": 200,
        "maximum_tail_blocks": 4096
      }
    },
    {
      "origin": "STRATEGY",
      "origin_id": "pumpfun-sniping-launch-v1",
      "capability_id": "pumpfun.token-launch.v2",
      "columns": ["transaction_succeeded", "mint", "creator", "creation_user"],
      "minimum_fidelity": {
        "identity": "EXACT",
        "ordering": "INSTRUCTION_EXACT",
        "state": "AFTER_ONLY",
        "fees": "UNKNOWN",
        "chain_finality": "FINALIZED",
        "completeness": "COMPLETE_TO_WATERMARK",
        "consistency": "SNAPSHOT_CONSISTENT"
      },
      "accepted_protocol_versions": ["pump-program-static-fee-v1"],
      "evidence_contracts": ["pumpfun-sniping-source-v2"],
      "warmup_blocks": 0,
      "settlement_tail_blocks": 0
    },
    {
      "origin": "EXECUTION",
      "origin_id": "pumpfun-sniping-curve-trade-v1",
      "capability_id": "pumpfun.curve-trade.v2",
      "columns": ["side", "base_amount_atomic", "quote_amount_atomic", "protocol_fee_atomic", "creator_fee_atomic"],
      "minimum_fidelity": {
        "identity": "EXACT",
        "ordering": "INSTRUCTION_EXACT",
        "state": "AFTER_ONLY",
        "fees": "COMPONENTS",
        "chain_finality": "FINALIZED",
        "completeness": "COMPLETE_TO_WATERMARK",
        "consistency": "SNAPSHOT_CONSISTENT"
      },
      "accepted_protocol_versions": ["pump-program-static-fee-v1"],
      "evidence_contracts": ["pumpfun-sniping-source-v2"],
      "warmup_blocks": 0,
      "settlement_tail_blocks": 0
    },
    {
      "origin": "EXECUTION",
      "origin_id": "pumpfun-sniping-lifecycle-v1",
      "capability_id": "pumpfun.curve-lifecycle.v2",
      "columns": ["lifecycle_kind", "lifecycle", "mode"],
      "minimum_fidelity": {
        "identity": "EXACT",
        "ordering": "INSTRUCTION_EXACT",
        "state": "AFTER_ONLY",
        "fees": "UNKNOWN",
        "chain_finality": "FINALIZED",
        "completeness": "COMPLETE_TO_WATERMARK",
        "consistency": "SNAPSHOT_CONSISTENT"
      },
      "accepted_protocol_versions": ["pump-program-static-fee-v1"],
      "evidence_contracts": ["pumpfun-sniping-source-v2"],
      "warmup_blocks": 0,
      "settlement_tail_blocks": 0
    }
  ],
  "budget": {
    "max_remote_bytes": 17179869184,
    "max_local_bytes": 17179869184,
    "max_days": 1,
    "temporary_reserve_bytes": 4294967296,
    "disk_low_watermark_bytes": 34359738368
  },
  "query": {
    "max_execution_seconds": 300,
    "max_memory_bytes": 4294967296,
    "max_result_rows": 10000000
  },
  "request_remote_estimate": false
}
```

Capability IDs и protocol versions должны точно совпадать с конкретным
inspection artifact. Planner добавляет `mandatory_columns` из capability
mapping. `settlement_requirement` обязателен для Sniping и входит в
DatasetSpec v5 identity. В этом example dataset поддерживает
`sell_delay_transactions <= 200`; если нужна большая задержка,
увеличьте `maximum_followup_delay_transactions` **до preparation** и
подготовьте новый dataset. Resolver не позволит запустить более
длинную sell latency на уже prepared snapshot.

`maximum_tail_blocks: 4096` — hard acquisition cap, а не утверждение,
что 4096 blocks обязательно хватит. Planner одноразово расширит
`BLOCK_CLOCK`, `PUMP_CURVE_TRADE` и `PUMP_CURVE_LIFECYCLE` ровно до
этого cap; `TOKEN_LAUNCH` останется в decision range, поэтому tail не
создаёт новые targets. Затем pre-root validator проверит по actual
compact clock, что каждый target успевает пройти 500 transactions,
две секунды и maximum sell delay. Caller tail выше 4096, source
watermark ниже cap или фактически недостаточный clock дают typed
fail-closed без неограниченной дозагрузки.

Для условных ranges выше суммарная ширина четырёх capability ranges —
28 672 blocks: 4096 для launch и по 8192 для трёх settlement streams.
`max_total_blocks` должен покрывать эту сумму. Это resource ceiling,
а не доказательство fidelity или достаточности settlement tail.

Проверка плана ничего не скачивает:

```bash
backtest plan-dataset plan.json \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml
```

Plan проходит source admission только с `source-inspection/v5`, созданным
предыдущей bounded командой на exact ranges и успешно связавшим четыре
`bounded-source-evidence/v2` receipts. Metadata-only inspection или
checked-in `UNKNOWN` examples дают typed `SOURCE_EVIDENCE_MISMATCH`; это не
следует обходить редактированием JSON/TOML.

План должен показывать исходный decision range, capability-specific extraction
ranges с правым settlement tail, только нужные columns и допустимые host
quotas. Не увеличивайте лимиты только ради обхода отказа: сначала уменьшите
диапазон или измерьте реальное потребление. Недостаточный tail, четыре streams
из разных source cuts или недоказанная fidelity дают typed отказ.

## 8. Подготовка snapshot

`prepare-dataset` принимает тот же versioned plan request:

```bash
backtest prepare-dataset plan.json \
  --config configs/local.toml \
  --capabilities configs/indexer-capabilities.local.toml
```

Успешный ответ содержит:

- `snapshot_id` — exact root snapshot;
- `dataset_revision_id` — logical dataset плюс source boundaries;
- `logical_content_hash` — hash canonical records/schema.

Для Sniping этот ответ возможен только после pre-root validation
целого candidate. Validator проверяет canonical order/groups, Pump state,
compact transaction clock и maximum settlement path каждого launch в
decision range. `SETTLEMENT_TAIL_INSUFFICIENT` или другой validation error
означает, что snapshot root не опубликован; отдельные already
committed distributions нельзя использовать как snapshot.

После commit дальнейшие compile/backtest команды не обращаются к индексеру.

## 9. ReplayPack для повторных прогонов

`reference-pumpfun-sniping-v1` умеет читать canonical Parquet напрямую. Для
серии прогонов и для `numpy-mmap-pumpfun-sniping-v1` сначала соберите mmap
ReplayPack:

```bash
backtest compile-replay <snapshot_id> --config configs/local.toml
```

Сохраните `replay_pack_id` из ответа. ReplayPack — rebuildable fast path, а не
источник истины; authoritative input остаётся committed snapshot. Pack содержит
compact arrays block ordinal, полного `transaction_count`, cumulative prefix и
`block_time_ns`, а не Python object на каждую Solana transaction.

## 10. Pump.fun Sniping draft v3

Текущий исполняемый contract — строго валидируемый
`pumpfun-sniping-run-draft/v3`. Его `execution_mode` обязателен; draft v2
не исполняется как v3 и получает `RERESOLVE_REQUIRED`.

Сначала посмотрите поддерживаемые editable поля и зафиксированные semantics:

```bash
backtest describe-run-contract pumpfun-sniping-run-draft/v3 \
  --config configs/local.toml
```

Создайте `run-draft.json`, подставив exact IDs из предыдущих ответов:

```json
{
  "contract_schema": "pumpfun-sniping-run-draft/v3",
  "dataset_revision_id": "<64-hex dataset revision ID>",
  "snapshot_id": "<64-hex snapshot ID>",
  "replay_pack_id": "<64-hex ReplayPack ID>",
  "delivery_schedule_id": null,
  "execution_mode": "EXOGENOUS_REPLAY",
  "initial_sol_balance_lamports": "2000000000",
  "gross_buy_budget_lamports": "200000000",
  "buy_slippage_bps": 3500,
  "sell_slippage_bps": 3500,
  "sell_delay_transactions": 200,
  "wallet_account_profile": {
    "schema": "pumpfun-solana-wallet-account-profile/v2",
    "profile_id": "pumpfun-solana-accounts-v2",
    "initial_uva_state": "fresh",
    "effective_from_unix_s": 0,
    "effective_until_unix_s": 4102444800,
    "account_costs": [
      {
        "requirement_schema_id": "pumpfun-user-volume-accumulator-v1",
        "deposit_lamports": "1844400"
      },
      {
        "requirement_schema_id": "solana-associated-token-account-legacy-v1",
        "deposit_lamports": "2039280"
      },
      {
        "requirement_schema_id": "solana-associated-token-account-token-2022-immutable-owner-v1",
        "deposit_lamports": "2074080"
      }
    ]
  },
  "pump_fee_profile": {
    "profile_id": "pump-static-95-30-v1",
    "program_version": "pump-program-static-fee-v1",
    "buy_formula_version": "pump-buy-exact-gross-sol-v1",
    "sell_formula_version": "pump-sell-exact-token-in-v1",
    "effective_from_unix_s": 0,
    "effective_until_unix_s": 4102444800,
    "protocol_fee_bps": 95,
    "creator_fee_bps": 30
  },
  "buy_solana_fee_profile": {
    "profile_id": "solana-buy-v1",
    "formula_version": "solana-legacy-v0-base-priority-v1",
    "transaction_format": "V0",
    "effective_from_unix_s": 0,
    "effective_until_unix_s": 4102444800,
    "charged_signature_count": 1,
    "lamports_per_signature": "5000",
    "compute_unit_limit": 86000,
    "micro_lamports_per_compute_unit": "10"
  },
  "sell_solana_fee_profile": {
    "profile_id": "solana-sell-v1",
    "formula_version": "solana-legacy-v0-base-priority-v1",
    "transaction_format": "V0",
    "effective_from_unix_s": 0,
    "effective_until_unix_s": 4102444800,
    "charged_signature_count": 1,
    "lamports_per_signature": "5000",
    "compute_unit_limit": 100000,
    "micro_lamports_per_compute_unit": "10"
  },
  "root_seed": "42"
}
```

Atomic amounts, включая каждый `deposit_lamports`, fee-profile atomic fields и
`root_seed`, передаются decimal strings: это сохраняет точность в Web UI/JSON.
Параметры примера соответствуют запросу: 2 SOL initial balance, 0.2 SOL gross
buy budget, 35% (`3500` bps) для обеих slippage limits, sell delay 200,
buy/sell CU limits 86000/100000 и 10 micro-lamports/CU. Effective interval и
все component prices должны оставаться корректными для выбранного dataset.
Для one-off reference Parquet run можно указать настоящий JSON `null` в
`replay_pack_id`. Для optimized backend нужен exact `replay_pack_id`.

`fresh` означает только отсутствие wallet-scoped Pump UserVolumeAccumulator в
начале run. Это не означает заранее созданный ATA: каждый successful buy
создаёт mode-specific ATA для mint, successful sell закрывает его, а failed
sell оставляет ATA и token balance locked. Профиль поэтому содержит три
отдельные effective-dated prices: UVA, legacy ATA и Token-2022 ATA.

Draft намеренно не позволяет менять fixed cooldown 600 seconds, buy delay
500 global Solana transactions, sell-decision delay 2 seconds, SOL-only и
sell-all: resolver материализует их в semantic identity. При этом draft
требует ровно одно из значений `EXOGENOUS_REPLAY` и
`EXOGENOUS_VIRTUAL_SETTLEMENT`. Оба режима
воспроизводят чужие сделки в наблюдаемом виде, строят quote из причинно
доступного historical state, учитывают размер нашей заявки и никогда не меняют
исторические резервы. Virtual settlement меняет только sell-side проверку
наличия real SOL: successful sell явно делит gross output на SOL из
наблюдаемого venue и synthetic shortfall. Buy-side real-token cap, lifecycle,
slippage, fees, accounts и migration behavior не меняются. Synthetic proceeds
можно использовать внутри simulated wallet, но они не доказывают, что sell
исполнился бы on-chain.

Для смены mode измените `execution_mode` в draft v3 и снова
выполните `resolve-run`. Это создаст новые logical/order/round-trip
identities и другой `logical_run_id`, но повторно использует те же Dataset,
Snapshot и ReplayPack: заново выполнять `prepare-dataset` и `compile-replay`
не нужно.

## 11. Resolution и запуск

Draft не исполняется. Сначала resolver закрепляет exact artifacts, defaults,
runtime и bundle closure. Он также повторно проверяет NetworkId,
`block32-transaction32-v1`, four-stream source evidence и settlement tail:

```bash
backtest resolve-run run-draft.json \
  --config configs/local.toml > resolved-run.json
```

По умолчанию `delivery_schedule_id: null`: observation delivery строится
динамически. Для многократных прогонов одной ReplayPack/latency/clock/seed
policy можно materialize эквивалентный stream:

```bash
backtest compile-delivery-schedule resolved-run.json \
  --config configs/local.toml
```

Скопируйте возвращённый `delivery_schedule_id` в `run-draft.json` и ещё раз
выполните `resolve-run`. Schedule допустим только вместе с exact ReplayPack;
resolver проверяет build key, network, position schema и decision range до
execution. Он materializes post-group observation order, но не заменяет
динамические buy/sell timers.

Запустите один последовательный deterministic run с уникальным physical nonce.
Для Parquet выберите reference backend; при ReplayPack можно выбрать reference
или dedicated optimized backend:

```bash
RUN_ATTEMPT_NONCE="$(python -c 'import secrets; print(secrets.token_hex(32))')"
backtest run resolved-run.json \
  --attempt-nonce "$RUN_ATTEMPT_NONCE" \
  --backend numpy-mmap-pumpfun-sniping-v1 \
  --config configs/local.toml
```

Ответ содержит `logical_run_id`, `execution_attempt_id` и `run_artifact_id`.
Nonce меняет физическую попытку, но не semantic identity эксперимента.
CLI flags backend/batch/readahead/output buffer/threads и одноимённые поля Web
UI являются отдельными physical-attempt settings: API передаёт их через
`RunPhysicalSettingsCommand`, а canonical durable job — через
`backtest.run-job/v2`. Они намеренно отсутствуют в
`pumpfun-sniping-run-draft/v3` и не меняют `logical_run_id`.

## 12. Просмотр результата

```bash
backtest list-runs --config configs/local.toml
backtest show-run-summary <run_artifact_id> --config configs/local.toml
backtest list-roundtrips <run_artifact_id> --limit 200 --config configs/local.toml
backtest list-roundtrips <run_artifact_id> \
  --after '<boundary_ordinal>:<roundtrip_id>' \
  --limit 200 \
  --config configs/local.toml
backtest verify-artifact <run_artifact_id> --config configs/local.toml
backtest show-lineage <run_artifact_id> --config configs/local.toml
```

`show-run-summary` возвращает
`pumpfun-sniping-run-summary/v3`: bounded counts/hashes, selected execution/
settlement policies, realized PnL, protocol/creator/network fee totals,
paid/refunded/locked account deposits, slippage counters и reconciled
gross/venue/synthetic settlement totals. Если хотя бы одну open position нельзя оценить,
`valuation_status` равен `PARTIAL_UNVALUED_OPEN_POSITIONS`, full
`economic_pnl_atomic` равен `null`, а частичная сумма остаётся только в
`valued_economic_pnl_subtotal_atomic`.
`list-roundtrips` читает verified `roundtrips.parquet` keyset-страницами не
больше 200 строк; cursor из `next_cursor` передаётся в следующий вызов. Точные
reference/min/landing amounts, signed slippage, component fees, account/rent,
cashback, realized и MTM values остаются integer atomic values. Current
`pumpfun-roundtrips/v4` показывает `account_profile_id` и ordered
`account_components[]`. Каждый component содержит requirement schema, scope,
release policy, attribution, lifecycle и exact reserved/paid/released/refunded/
locked amounts; это заменяет неоднозначные scalar account fields v2 и
добавляет mode-specific reference/landing liquidity evidence. Potential shortfall
хранится отдельно от фактически settled synthetic funding, а projected MTM
shortfall — без ledger posting. Failure code каждой leg остаётся отдельным
полем; все финансовые rows сводятся с correlated `run-ledger/v2`.
Committed summary v2/round-trip v3 остаются читаемыми по исходным schemas и
не перезаписываются.

Те же данные доступны в общем React-интерфейсе: **Strategy results → Results**.
Точный `run_artifact_id` открывается по `/runs/{id}` с общими вкладками
**Overview**, **Entries**, **Exits**, **Trades**, **Verification**.
По умолчанию используются английские подписи; **Language → Русский** включает
перевод. Карточки читают verified summary, диаграммы — отдельную ограниченную
аналитику всего run. UI хранит одну страницу из 25 записей (API допускает 200);
поиск и сортировки page-local, стрелки запрашивают следующую страницу.
Полный PnL при partial valuation остаётся недоступным, subtotal показан отдельно.

В **Trades** токен и кнопка деталей открывают overlay с Pump-историей в SOL,
сигналом и фактическими исходами попыток. **Around trade** / **Full history**
меняет локальный масштаб. История заканчивается при completion/migration;
missing evidence и превышенный лимит дают явные ошибки. У FirstSwap нет
определённого round-trip PnL или Pump-истории. **Verification → Open manifest
and lineage → Lineage** показывает проверенный граф зависимостей.
UI читает API, а не SQLite/Parquet/пути. Предупреждение о synthetic settlement
остаётся видимым и не подтверждает возможность исполнения on-chain.

Основной UI аналогично показывает по 20 jobs и 10 runs. Jobs глобально
выбираются newest-first; runs также выбираются глобально по completion time до
чтения bounded-страницы. Стрелки запрашивают следующую server page, а
альтернативные allowlisted sorts остаются page-local. Runs загружаются при
startup, manual refresh или после завершения run-producing job; быстрый polling
остаётся только пока есть active jobs.

## 13. Direct CLI или queue

- Direct mode: `serve` выключен, heavy команда durable-submit-ится, запускает
  local supervisor/child и ждёт terminal state.
- UI/API mode: `serve` держит controller authority, команда быстро попадает в
  SQLite queue, а UI опрашивает status/progress.
- Для `run`, `sweep` и ML CLI aliases при работающем server используется
  `--enqueue --idempotency-key <stable-key>`.
- Не запускайте второй server или direct writer для того же `data_root`.
  `controller.lock` намеренно отклоняет такую гонку.

Пример queued run:

```bash
backtest run resolved-run.json \
  --attempt-nonce <64-hex nonce> \
  --enqueue \
  --idempotency-key example-experiment-v1 \
  --config configs/local.toml
```

## 14. Границы допуска

Capability/projection examples и hermetic tests описывают программный
контракт, но не доказывают полноту live indexer. Каждый exact cut требует
собственных authoritative `PROVEN` receipts для всех четырёх streams. Новый
или расширенный диапазон без них остаётся fail closed; local TOML и normalizer
не могут заменить доказательства, а ручная замена `UNKNOWN` запрещена.

Производительность и ресурсы проверяются на выбранных данных и целевом host
по [методике измерений](performance-baseline.ru.md). Проверка одного диапазона
не доказывает другие ranges, больший capacity или cold-cache performance.
Windows поддерживается через WSL2/Ubuntu; native Win32 не поддерживается.

## 15. Следующие шаги

- Все команды: [CLI reference](cli-reference.ru.md).
- Настройка RAM, диска и backup: [configuration.ru.md](configuration.ru.md).
- Где добавлять strategy/indexer/protocol code: [project-layout.ru.md](project-layout.ru.md).
- Почему действуют эти ограничения:
  [architecture-deep-dive.ru.md](architecture-deep-dive.ru.md).

---

**Язык:** [English](getting-started.md) · Русский
