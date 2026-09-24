# Project documentation

[Static demo and GitHub Pages](demo.md)

## Using the engine

1. [Getting Started](getting-started.md) — installation on Linux, macOS, or
   Windows through WSL2, local configuration, Web UI, and the first backtest.
2. [Web UI guide](ui-guide.md) — a screenshot-led tour of data preparation,
   strategy runs, jobs, results, ML, research, artifacts, and resources.
3. [Configuration](configuration.md) — TOML settings, secret references,
   capability declarations, and projection mappings.
4. [CLI and workflows](cli-reference.md) — commands, input JSON, and direct or
   queued execution.
5. [Project layout](project-layout.md) — packages, tests, and local artifacts.
6. [Performance measurement](performance-baseline.md) — benchmark commands,
   comparison methodology, and admission criteria.
7. [Wallet research](wallet-research.md) — observed activity, shared purchases,
   exact trade evidence and the boundary between a hypothesis and a strategy.
8. [Synthetic ML baseline](ml-baseline.md) — one logistic model, four simple
   causal features, a temporal holdout and explicit missing-label accounting.

## Architecture and contributions

The [architecture deep dive](architecture-deep-dive.md) is the sole normative
source for the target architecture. The [overview](architecture.md) summarizes
it without introducing independent decisions. Read the affected sections and
[contribution guide](../.github/CONTRIBUTING.md) before proposing changes.

Section 3.4 of the deep dive describes the implemented boundary. Target
extension points are not available merely because a port or catalog entry
exists. Unsupported semantics stop with a typed error.

Live replay-source admission requires generated evidence for the exact selected
range and source mapping. Fixture verification does not establish the
completeness or fidelity of an external source. Measurements apply only to
their verified input, execution mode, hardware, and physical settings.
Research-only snapshots preserve `UNKNOWN` source fidelity and cannot replace
this execution admission.

English files without a language suffix are canonical. Russian and Chinese
guides are translations or concise entry points; if they disagree, English
applies.

---

**Language:** English · [Русский](index.ru.md) · [简体中文](index.zh-CN.md)
