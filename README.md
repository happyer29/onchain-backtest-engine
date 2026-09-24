# On-Chain Backtest Engine

**Language:** English · [Русский](docs/README.ru.md) · [简体中文](docs/README.zh-CN.md)

A self-hosted, single-host research and backtesting engine. It prepares bounded
read-only source data as verified local artifacts, then runs deterministic
strategy replays without SQL or network access in the event loop. The project is
an alpha-stage example, not a live-trading system or financial advice.

## What's included

| Tool | What it does |
| --- | --- |
| Data preparation | Inspect a source, plan a bounded dataset, and publish immutable Parquet snapshots. |
| Replay and strategies | Run the reference engine, Sniping, Copy Buy, and FirstSwap using explicit execution contracts. |
| On-chain research | Inspect signing-wallet activity and shared purchases from verified local research artifacts. |
| Model infrastructure | Build point-in-time feature/label/universe artifacts and run the existing safe exact-model workflow. |
| Operations | Manage a durable job queue, verify artifacts and lineage, inspect results, pin and collect artifacts, and check backups. |
| Interfaces | Use the typed CLI, loopback-only Control API, and bundled React Web UI over the same application contracts. |

The separate [ML baseline example](docs/ml-baseline.md) uses only synthetic data,
one logistic-regression model, and four simple features. It is deliberately not
an admitted trading strategy, production model, or claim of predictive quality.
The exact-model UI can also train on earlier rows of a ReplayPack and predict
later rows: select “No prediction before first model” when building predictions,
then use the matching inference policy in a FirstSwap run. Early rows stay
unscored; uncovered gaps after the first model remain errors.

Watch the [project overview (99 s, Russian narration)](docs/assets/project-overview-demo-ru.mp4)
or the focused [ML workflow (67 s, Russian narration)](docs/assets/ml-workflow-demo-ru.mp4).
Both use synthetic UI fixtures; neither records a live source or a complete ML
job run through the UI.

## Quick start

Use Python 3.13 and [`uv`](https://docs.astral.sh/uv/). Linux x86_64 and macOS
arm64 are native targets; on Windows 11 x86_64, use WSL2 with Ubuntu.

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
backtest --help
cp configs/local-16gb.toml configs/local.toml
backtest serve --config configs/local.toml
```

Configure the data root, source capabilities, and credentials before connecting
to a real indexer. Keep credentials in an environment or local secret provider;
never commit them. The Web UI listens on the configured `127.0.0.1` port.
See [Getting started](docs/getting-started.md) for the complete workflow and
[Configuration](docs/configuration.md) for the security and source settings.

Try the offline ML example without a source connection:

```bash
python -m backtest.examples.ml_baseline
```

It prints train/test counts, explicit unknown and purged labels, and basic
holdout metrics. Feature vectors use only earlier synthetic events; the split
purges training labels unavailable before the test period.

## Core workflow

```text
inspect-source → plan-dataset → prepare-dataset → compile-replay (optional)
               → resolve-run → run / sweep → inspect and verify results
```

`backtest research` handles bounded wallet research; `backtest serve` opens the
local workspace. Run `backtest <command> --help` for current syntax, or use the
[CLI reference](docs/cli-reference.md).

Source completeness and causal delivery are not assumed. Unsupported, stale,
corrupt, or over-budget inputs fail explicitly. Research findings do not gain
strategy or execution admission automatically; synthetic virtual settlement
is labelled as such. See [architecture and limitations](docs/architecture-deep-dive.md)
for the exact contracts.

## Documentation and contribution

- [Documentation index](docs/README.md)
- [Static interface demo](docs/demo.md)
- [Contributing](.github/CONTRIBUTING.md)
- [Security policy](.github/SECURITY.md)
- [Support](docs/SUPPORT.md)
- [Changelog](docs/CHANGELOG.md)

The project is distributed under the [MIT License](LICENSE). Third-party
attributions are in [notices](docs/THIRD_PARTY_NOTICES.md).
