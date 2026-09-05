## Outcome

<!-- What changed for the user or the system? -->

## Architecture check

- normative sections:
- current vs target boundary:
- affected layer/use case/port:
- identities and artifacts affected:
- causality/fidelity/determinism/resource invariants:
- failure cases and verification:

## Verification

- [ ] `ruff format --check src tests`
- [ ] `ruff check src tests`
- [ ] `mypy src/backtest`
- [ ] `lint-imports`
- [ ] `pytest --cov=backtest --cov-report=term-missing`
- [ ] The additional gate for the affected area was run or explained

## Security and data

- [ ] No credentials, `.env`, local TOML, private endpoint/path, or generated data
- [ ] No test, coverage, or fail-closed guard was weakened
- [ ] UI screenshots and logs were sanitized of sensitive values
- [ ] README, deep dive, and current status were synchronized if the working boundary changed

---

Language: **English** · [Русский](PULL_REQUEST_TEMPLATE.ru.md)
