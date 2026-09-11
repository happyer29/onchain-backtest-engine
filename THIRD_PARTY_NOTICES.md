# Third-Party Notices

> This English document is authoritative. The Russian translation is provided
> for convenience only.

This repository includes narrow Pump program IDL event-layout projections used
only by the hermetic golden tests under `tests/golden/pumpfun/program-v1/`.
The projections retain event names, discriminators, ordered fields and the
defined types required to decode the checked-in RPC evidence.

## Browser interface dependencies

The packaged React interface includes JavaScript libraries under their
respective licenses. Full notices and locked versions are bundled in
[`third-party-licenses.txt`](src/backtest/interfaces/web/static/third-party-licenses.txt)
and served at `/static/third-party-licenses.txt`. The build generates this file
from installed production packages and shipped Tailwind/Vite helpers, including
the D3 notices vendored by
`victory-vendor`; it contains no operational configuration or data.

## Pump package sources

### `pump-rust-client 0.1.10`

- Registry record: <https://crates.io/api/v1/crates/pump-rust-client/0.1.10>
- Registry archive: <https://crates.io/api/v1/crates/pump-rust-client/0.1.10/download>
- Archive SHA-256: `b506959627ec272b37c54769180010d413df3a153f4adebda2879eea76e98345`
- Projected source: `pump-rust-client-0.1.10/idls/pump.json`
- Source SHA-256: `6edaa1f67f7003514df97eb0ec40ff7e60d1278667521fabb679be1bb0ddd01e`
- License declaration: `MIT` in
  `pump-rust-client-0.1.10/Cargo.toml.orig` (`package.license`)
- Publisher evidence: the crates.io owners record identifies the team
  `github:pump-fun:mobile-blockchain`:
  <https://crates.io/api/v1/crates/pump-rust-client/owners>

### `@pump-fun/pump-sdk 1.2.0`

- Registry record: <https://registry.npmjs.org/%40pump-fun%2Fpump-sdk/1.2.0>
- Registry archive: <https://registry.npmjs.org/@pump-fun/pump-sdk/-/pump-sdk-1.2.0.tgz>
- Archive SHA-256: `22703838d09ea32ab09a680f543a0bd153cb17e328c7954337f80fc2d7acec19`
- npm integrity: `sha512-N2NT2OU1yCydz8Htko1j5AUuQmu5elmigsUN9nTGTd1gnoKNXF03COp538aNrZoflgBG8gfYvi07E2q8XOtGSg==`
- Projected source: `package/src/idl/pump.json`
- Source SHA-256: `1c81b2064995b75bb256c0bc17b0e30878583787e30a932975dfd505ff8ba9fb`
- License declaration: `MIT` in `package/package.json` (`license`)
- Publisher attribution: the npm version record identifies the package author
  as `pump-fun`.

Both pinned package records declare the SPDX expression `MIT`. The canonical
MIT license text is available at <https://spdx.org/licenses/MIT.html>.

Neither pinned archive contains a standalone license file or an explicit
copyright-holder notice. Attribution here follows the package metadata;
no additional copyright-holder notice is available in those archives.

## Non-redistribution equivalence references

The following `pump-public-docs` revisions were used only to verify that the
licensed-package projections preserve the event layouts previously exercised
by the tests. They are not the redistribution or licensing basis for the
checked-in projections:

- current equivalence reference:
  `pump-fun/pump-public-docs@9c82f61cb711b044a17f770ab8ce9f9bdf78f333`,
  `idl/pump.json`, SHA-256
  `b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49`;
- historical equivalence reference:
  `pump-fun/pump-public-docs@e2b66e4fce2fc130955912315167dc41e56956ad`,
  `idl/pump.json`, SHA-256
  `312051ac07f38dfc231819cbed35c90b048201b67e1d86503fabfdbffe52f010`.

The complete provenance records, archive identities and projection digests are
stored in `tests/golden/pumpfun/program-v1/provenance.json` and repeated in the
two projected IDL subset files and their aggregate schema.

---

Language: **English** · [Русский](THIRD_PARTY_NOTICES.ru.md)
