# Уведомления о сторонних компонентах

> Это неофициальный перевод для удобства. В случае расхождений действует
> [английская версия](THIRD_PARTY_NOTICES.md).

Этот репозиторий содержит узкие проекции схем событий IDL программы Pump,
которые используются только герметичными эталонными тестами в
`tests/golden/pumpfun/program-v1/`. Проекции сохраняют названия событий,
дискриминаторы, порядок полей и определённые типы, необходимые для
декодирования включённых в репозиторий свидетельств RPC.

## Библиотеки браузерного интерфейса

Полные уведомления и версии зафиксированных production-зависимостей React
поставляются в [third-party-licenses.txt](src/backtest/interfaces/web/static/third-party-licenses.txt)
и доступны по `/static/third-party-licenses.txt`. Файл собирается из лицензий
установленных пакетов, включая vendored D3; локальные конфигурации и данные
в него не входят.

## Источники пакетов Pump

### `pump-rust-client 0.1.10`

- Запись в реестре: <https://crates.io/api/v1/crates/pump-rust-client/0.1.10>
- Архив реестра: <https://crates.io/api/v1/crates/pump-rust-client/0.1.10/download>
- SHA-256 архива: `b506959627ec272b37c54769180010d413df3a153f4adebda2879eea76e98345`
- Источник проекции: `pump-rust-client-0.1.10/idls/pump.json`
- SHA-256 источника: `6edaa1f67f7003514df97eb0ec40ff7e60d1278667521fabb679be1bb0ddd01e`
- Заявленная лицензия: `MIT` в
  `pump-rust-client-0.1.10/Cargo.toml.orig` (`package.license`)
- Свидетельство об издателе: запись о владельцах crates.io указывает команду
  `github:pump-fun:mobile-blockchain`:
  <https://crates.io/api/v1/crates/pump-rust-client/owners>

### `@pump-fun/pump-sdk 1.2.0`

- Запись в реестре: <https://registry.npmjs.org/%40pump-fun%2Fpump-sdk/1.2.0>
- Архив реестра: <https://registry.npmjs.org/@pump-fun/pump-sdk/-/pump-sdk-1.2.0.tgz>
- SHA-256 архива: `22703838d09ea32ab09a680f543a0bd153cb17e328c7954337f80fc2d7acec19`
- npm integrity: `sha512-N2NT2OU1yCydz8Htko1j5AUuQmu5elmigsUN9nTGTd1gnoKNXF03COp538aNrZoflgBG8gfYvi07E2q8XOtGSg==`
- Источник проекции: `package/src/idl/pump.json`
- SHA-256 источника: `1c81b2064995b75bb256c0bc17b0e30878583787e30a932975dfd505ff8ba9fb`
- Заявленная лицензия: `MIT` в `package/package.json` (`license`)
- Атрибуция издателя: запись версии npm указывает автора пакета `pump-fun`.

Обе зафиксированные записи пакетов объявляют SPDX-выражение `MIT`.
Канонический текст лицензии MIT доступен по адресу
<https://spdx.org/licenses/MIT.html>.

Ни один из зафиксированных архивов не содержит отдельного файла лицензии или
явного уведомления о правообладателе. Атрибуция здесь соответствует метаданным
пакетов; дополнительного уведомления о правообладателе в этих архивах нет.

## Ссылки для проверки эквивалентности без распространения

Следующие ревизии `pump-public-docs` использовались только для проверки того,
что проекции из лицензированных пакетов сохраняют схемы событий, ранее
использованные тестами. Они не являются основанием для распространения или
лицензирования включённых в репозиторий проекций:

- ссылка для проверки текущей версии:
  `pump-fun/pump-public-docs@9c82f61cb711b044a17f770ab8ce9f9bdf78f333`,
  `idl/pump.json`, SHA-256
  `b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49`;
- ссылка для проверки исторической версии:
  `pump-fun/pump-public-docs@e2b66e4fce2fc130955912315167dc41e56956ad`,
  `idl/pump.json`, SHA-256
  `312051ac07f38dfc231819cbed35c90b048201b67e1d86503fabfdbffe52f010`.

Полные сведения о происхождении, идентификаторы архивов и дайджесты проекций
хранятся в `tests/golden/pumpfun/program-v1/provenance.json` и повторяются в
двух файлах подмножеств IDL и их совокупной схеме.

---

Язык: [English](THIRD_PARTY_NOTICES.md) · **Русский**
