# Contributing

Thank you for your interest in On-Chain Backtest Engine. The project accepts small,
verifiable changes that preserve determinism, source fidelity, and fail-closed
behavior.

## Before you begin

1. Read “How to read this document,” §3.4, every affected section, and §38 of
   the [architecture deep dive](docs/architecture-deep-dive.md).
2. Check existing issues to avoid duplicating work.
3. For a material change, open a feature request first and describe a bounded
   vertical slice.

An ordinary feature or refactoring does not change the normative architecture.
If a proposal requires an architectural deviation, the deep dive change and
its consequences must be approved explicitly before implementation.

## Local environment

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
backtest --help
```

Never commit `.env`, `configs/*.local.toml`, the contents of `var/`,
credentials, a private indexer endpoint, or extracted data.

## Workflow

1. Create a separate branch from the current `main`.
2. Describe the affected architectural sections, invariants, and failure
   verification in the PR description.
3. Make the smallest complete change, including failure semantics and tests.
4. Update user documentation when observable behavior changes.
5. Run the full gate.

```bash
.venv/bin/ruff format --check src tests
.venv/bin/ruff check src tests
.venv/bin/mypy src/backtest
.venv/bin/lint-imports
.venv/bin/pytest --cov=backtest --cov-report=term-missing
```

Live-source and performance checks must remain explicit, read-only, and
bounded. Do not add skips/xfails, silent exception handling, or weaker coverage
merely to make CI green.

## Pull request

A good PR includes:

- A concise explanation of the problem and outcome.
- The affected layer, use case, and port.
- The effects on identity, causality, fidelity, determinism, and resources.
- Failure cases and how they were verified.
- Commands run and their results.
- Screenshots for visible UI changes, with secrets, paths, wallet addresses,
  and sensitive artifact IDs removed.

Keep the PR small. Put unrelated cleanup and refactoring in a separate change.

## Bug reports and security

Use the bug report template for ordinary defects. Do not disclose a
vulnerability or possible data leak in a public issue; follow
[SECURITY.md](SECURITY.md).

---

Language: **English** · [Русский](CONTRIBUTING.ru.md)
