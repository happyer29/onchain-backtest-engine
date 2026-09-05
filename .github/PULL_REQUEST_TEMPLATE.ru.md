## Результат

<!-- Что изменилось для пользователя или системы? -->

## Architecture check

- normative sections:
- current vs target boundary:
- affected layer/use case/port:
- identities and artifacts affected:
- causality/fidelity/determinism/resource invariants:
- failure cases and verification:

## Проверки

- [ ] `ruff format --check src tests`
- [ ] `ruff check src tests`
- [ ] `mypy src/backtest`
- [ ] `lint-imports`
- [ ] `pytest --cov=backtest --cov-report=term-missing`
- [ ] Дополнительная проверка для затронутой области выполнена или объяснена

## Безопасность и данные

- [ ] Нет учётных данных, `.env`, локального TOML, частного адреса или пути либо
      сгенерированных данных
- [ ] Не ослаблены тесты, покрытие или защиты `fail-closed`
- [ ] Снимки экрана интерфейса и журналы очищены от чувствительных значений
- [ ] README, подробное описание архитектуры и текущий статус синхронизированы,
      если изменилась граница работающей реализации

---

Язык: [English](PULL_REQUEST_TEMPLATE.md) · **Русский**
