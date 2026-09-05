# Project documentation

## Using the engine

1. [Getting Started](getting-started.md) — installation on Linux, macOS, or
   Windows through WSL2, local configuration, Web UI, and the first backtest.
2. [Configuration](configuration.md) — TOML settings, secret references,
   capability declarations, and projection mappings.
3. [CLI and workflows](cli-reference.md) — commands, input JSON, and direct or
   queued execution.
4. [Project layout](project-layout.md) — packages, tests, and local artifacts.
5. [Performance measurement](performance-baseline.md) — benchmark commands,
   comparison methodology, and admission criteria.

## Architecture and contributions

The [architecture deep dive](architecture-deep-dive.md) is the sole normative
source for the target architecture. The [overview](architecture.md) summarizes
it without introducing independent decisions. Read the affected sections and
[contribution guide](../CONTRIBUTING.md) before proposing changes.

Section 3.4 of the deep dive describes the implemented boundary. Target
extension points are not available merely because a port or catalog entry
exists. Unsupported semantics stop with a typed error.

Live source admission requires generated evidence for the exact selected
range and source mapping. Fixture verification does not establish the
completeness or fidelity of an external source. Measurements apply only to
their verified input, execution mode, hardware, and physical settings.

English files without a language suffix are canonical. Russian files are
translations; if they disagree, the English version applies.

---

**Language:** English · [Русский](README.ru.md)
