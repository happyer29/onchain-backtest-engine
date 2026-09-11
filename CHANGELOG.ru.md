# Журнал изменений

Здесь перечислены заметные для пользователя изменения. Формат следует
[Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии —
[Semantic Versioning](https://semver.org/lang/ru/).

## [0.2.0] — кандидат в релиз

- Полный React/TypeScript UI и общий Strategy results для Sniping, Copy Buy и
  FirstSwap: диаграммы, аналитика входов/выходов, детали токена и lineage.
- Английский язык по умолчанию, русский по выбору, сохранение языка/темы и
  название **onchain backtest engine** в меню.
- История Pump из сохранённого snapshot: сигнал, фактические вход/выход,
  отдельные ошибки/отказы; bounded columnar selection до 10 миллионов строк,
  1 GiB и 4 000 точек. Нет source fallback или усечения истории.
- Старые HTML/JS удалены, bookmarks ведут в React. Обновлены публичные руководства,
  скриншоты на тестовых fixtures, лицензии browser dependencies и CI.

Полная история изменений ведётся в каноническом [CHANGELOG.md](CHANGELOG.md).
