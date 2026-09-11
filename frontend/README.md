# React interface

This is the complete browser interface for the Python modular monolith.
Its architecture is defined by [deep-dive §34.2](../docs/architecture-deep-dive.md#342-web-ui);
the implemented execution boundary is [§3.4](../docs/architecture-deep-dive.md#34-current-project-state).
The build is checked in under `src/backtest/interfaces/web/static` and packaged
in the Python wheel. There is no production Node process or second API.

## Components and rationale

The previous surface contained three HTML roots and 5,026 lines across four
manual JavaScript files, including separate Sniping and Copy result renderers.
The migration replaces those roots with one route tree and one result contract.
These dependencies fill browser interaction gaps; no Python analytical engine
or runtime dependency was added.

| Component | Responsibility |
|---|---|
| React + TypeScript + Vite | One component tree, typed build and lazy route/chart chunks |
| React Router | Same-origin routes and old result bookmark aliases |
| Radix + local CSS/Tailwind tokens | Accessible tabs/expandable forms and shared warm/dark controls |
| React Hook Form + Zod | Exact lexical field validation, error disclosures and strict result checks |
| TanStack Query | Cancellation, separate summary/page lifetimes and bounded adaptive polling |
| TanStack Table | Semantic table rendering with explicitly page-local search/sort |
| Recharts | Distributions, fees/funding and causal Pump history with exact accessible values |
| React Flow + dagre | Bounded verified lineage with a keyboard-accessible text alternative |
| Cytoscape.js 3.34.3 | Existing research canvas, now bundled as an ESM dependency with React-owned controls |
| lossless-json | Round-trip wide JSON integers when forwarding server-resolved specifications |

Native `<dialog>` provides the large detail overlay, inert background and
focus restoration. Financial arithmetic remains BigInt; floating-point numbers
are used only for normalized drawing geometry. Market-cap views keep exact
transaction ordering, explicit local zoom and an automatic vertical range.
Geometry is never an execution quote or a new accounting result.

## Language and presentation

English is the default even with a non-English browser locale. The sidebar
**Language** control persists an explicit `en`/`ru` choice in
`backtest.ui.language`. `i18n.ts` and `messages.ru.json` supply plain text
translations and exact localized number/date formatting; no external service
or runtime translation dependency is used. Components subscribe without
remounting forms, dialogs or queries. `public/theme.js` applies both saved
appearance and language before first paint. Unknown preferences reset to
English; denied storage keeps an explicit tab-only selection.

`npm run build` also writes `third-party-licenses.txt` from the installed,
locked production dependency notices, plus Tailwind CSS and Vite browser helpers. It accompanies the browser code in the
Python package. Missing notices fail the build.

## Development and checks

Use Node.js 22.12+ and the repository's Python 3.13 virtual environment.
From the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend run generate
npm --prefix frontend test
npm --prefix frontend run build
```

`generate` exports schemas from an inert API app, without opening operational
storage. `dev` watches production assets; serve them using the existing
`backtest serve` process so cookies, origin validation and CSP stay unchanged.
The external classic `theme.js` runs before React to avoid a theme flash; Vite's
message that this script is not bundled is expected. It is copied locally.

Install Playwright Chromium with `cd frontend` then
`npx playwright install chromium`, and run:

```bash
npm --prefix frontend run test:browser
```

Alternatively, `BACKTEST_BROWSER_CHANNEL=chrome` selects an installed Chrome
with a fresh isolated profile. Browser tests own a temporary hermetic data root
and a single loopback controller. They perform a real FirstSwap launch and
result/lineage flow. Pump chart rendering uses explicitly marked transport
fixtures; real Sniping/Copy result adapters are checked by Python integration
tests. No test connects to an operational source or publishes a mock Run.

Keep generated OpenAPI/types and static build output synchronized. Node modules,
TypeScript build caches, browser traces and test screenshots are excluded from the
deliverable. CI runs the frontend checks, browser tests, full Python gate and
installed-wheel CLI/API/static smoke.

## On-chain research

`/research?artifact=<exact ID>` opens ResearchSnapshot/ResearchResult v1 or v2
inside the same shell. Preparation and analysis submit typed forms through the
existing application resolver and supervisor; an empty signer field means all
observed signers. Completed research jobs link to verified output both on this
page and in the shared queue. Token-mode selection, missing-creation warnings,
all paged tables, exact-pair purchases and lineage preserve deep-dive §24.6.

React owns the entire UI and renderer lifecycle. The old standalone HTML,
CSS/global DOM controllers and vendor script are removed. The already admitted
Cytoscape version remains unchanged: npm packaging replaces vendoring, not the
analytical engine or grouping algorithm. The complete result stays in one
bounded display model; only the current overview/group/wallet projection enters
the canvas. Recharts and React Flow retain their existing strategy/lineage roles.
The representative comparison is in [research capacity](../docs/research-capacity.md#react-workspace-integration-2026-09-11).

The required Cytoscape container rule is an actual external
`public/graph-canvas.css` link with the library's recognized stylesheet ID.
This prevents runtime inline-style injection without relaxing CSP. Vite's
message that `/static/graph-canvas.css` resolves at runtime is expected: the
public asset is copied into the wheel, and API/browser/installed-wheel tests
verify its contents and effect. The graph has a local React error boundary, so
a missing optional chunk cannot hide verified purchase evidence or forms.

`npm test` also runs the original bounded loader/grouping oracles. Their pure
JavaScript modules are unchanged apart from ESM exports and have explicit
TypeScript display contracts. The retired DOM harness is replaced by real-core
projection tests, React submission tests and browser lifecycle tests. Browser
research tests publish real hermetic snapshots (including a data issue), run
all-signer analysis through an isolated child, and check output, modes,
three-level navigation, cancellation/retry, evidence, themes, mobile layout and
CSP. They never contact ClickHouse.
