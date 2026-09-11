# Changelog

Notable user-facing changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] — release candidate

### Added

- Pump.fun Copy Buy reference execution through CLI/API/Web UI: exact
  `signing_wallet` purchases, one entry per token, fee-free price TP/SL and
  maximum holding time, four sale attempts with two-second retry waits, and
  separately verified source coverage and immutable position results.
- A complete React/TypeScript workspace and shared Strategy results for Sniping,
  Copy Buy and FirstSwap, with charts, entry/exit analytics and verified lineage.
- English by default, optional Russian, local language/theme preferences and
  the **onchain backtest engine** sidebar brand.
- Pump trade overlays with retained SOL market-cap history, original signals,
  actual filled entry/exit markers and distinct failed/rejected attempts.
- Browser dependency license notices and documented interface screenshots
  using isolated test fixtures.

### Changed

- Replaced the legacy HTML/JavaScript dashboards; existing bookmarks open React.
- Chart selection now filters the selected venue in bounded columnar batches,
  admitting up to 10 million snapshot rows and 1 GiB, with 4,000 output points.
  Missing evidence and quota failures remain explicit; no source fallback occurs.
- Updated public guides, package version and frontend CI; excluded private
  operational notes, source inventories and local experiment reports.

## [0.1.0]


### Added

- Deterministic local replay from verified immutable Parquet snapshots, with
  optional ReplayPack acceleration.
- Pump.fun Sniping with strict source-evidence admission and separate
  `EXOGENOUS_REPLAY` and `EXOGENOUS_VIRTUAL_SETTLEMENT` execution modes.
- Typed CLI and same-origin Web UI over a durable job queue with isolated child
  processes, cancellation, retry, and restart recovery.
- Linux x86_64, macOS arm64, and Windows 11 through WSL2/Ubuntu profiles.
- English and Russian product documentation.
- Installed-package checks for CLI entrypoints, loopback API, and static UI
  assets, with CI quality gates for Linux x86_64 and macOS arm64.

### Changed

- Deterministic newest-first run pagination uses a rebuildable, manifest-bound
  catalog index and verifies every selected artifact.
- Job/run tables and the Sniping dashboard retain one bounded page, with
  page-local sort/search, adaptive polling, and a combined summary/page query.
- Repeated artifact reads reuse bounded, fingerprint-guarded verification
  evidence while committed filesystem bytes remain authoritative.
- Clean restarts can reuse a verified catalog receipt; crashes, inventory
  changes, or corruption require full verification.

### Fixed

- Preserved the existing `jobs` CLI JSON envelope while the HTTP response
  carries the pagination cursor.
- Rejected malformed Solana genesis identities and endpoint or credential
  delimiters before source configuration enters artifact identity. Complete
  base58 references retain their exact bytes; mixed-network guards stay active.

---

Language: **English** · [Русский](CHANGELOG.ru.md)
