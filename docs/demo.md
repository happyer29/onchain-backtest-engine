# Static demo

The demo shows the existing React interface using generated test inputs. It is
ready for static hosting, including GitHub Pages, without a Python server at
runtime. Preparation and publication are separate actions; the repository does
not publish the demo on push.

## What to explore

| Example | What it shows |
|---|---|
| Wallet research | 60 wallets in four planted groups, 423 pairs without Mayhem, 426 with all modes |
| Graph | Whole result → group → wallet neighbourhood; search, zoom, display threshold and exact pair purchases |
| Source observations | Repeat buys, a sell, Mayhem, unknown mode and missing creation-signature warnings |
| Copy Buy, strict replay | One entry with exhausted sell attempts under observed reserves |
| Copy Buy, virtual settlement | The same small scenario with a closed position and explicit synthetic sell funding |
| Result details | Entry/exit analytics, market history, actual attempts, exact amounts and offline lineage |

The two research results use a 60-second window and at least two shared tokens.
The method compares each wallet's **first successful purchase of each token in
the snapshot**. Later repeated purchases do not add a match. Groups are a visual
partition of those pairs; they are not proof of a shared owner or coordination.
The fixture was deliberately constructed to make navigation and limitations
visible. It is not market research or evidence of strategy profitability.

The selector opens results computed during preparation; display filters change
only visible links. Source acquisition, arbitrary dates/windows, preparation,
strategy execution, job queues and live updates require the local application.
The static site has no operational API and cannot create a job.

## Prepare and open locally

Use Python 3.13, uv and Node.js 22.12+ (Node 24 in CI). From the repository root:

```bash
uv sync --all-groups --frozen
npm ci --prefix frontend
npm --prefix frontend run demo:prepare
npm --prefix frontend run demo:build
npm --prefix frontend run demo:serve
```

Open [the local demo](http://127.0.0.1:18744/onchain-backtest-engine/).
Research is at `#/research`; result and lineage links also use hash routing, so
reloading a deep link works under a GitHub project path. The preview binds only
to loopback. `BACKTEST_DEMO_PORT` changes its port. Opening `index.html` directly
with `file://` is unsupported; the browser needs HTTP/HTTPS and Web Crypto.

`demo:prepare` runs existing preparation, research and reference execution use
cases in a fresh temporary root with network connections blocked. It obtains
presentation DTOs from the real API in process. It never reads the operational
data root or `configs/local.toml`. No ClickHouse credentials or `.env` are needed.
Do not replace the generator with a copy of your local artifacts.

The generated, gitignored directories are:

- `frontend/demo-data`: manifest and content-addressed JSON responses.
- `frontend/demo-dist`: complete static site, local graph worker, notices,
  `.nojekyll`, data and a `distribution.json` file inventory with SHA-256 hashes.
- `frontend/demo-test-results`: browser test output.

The initial recipe exports 933 request variants and about 4.3 MB of response
bytes. Every pair has its full original-purchase evidence. The build rejects
extra files, local-path/credential metadata, incorrect lengths/hashes and
oversized output. The browser checks the manifest hash embedded in the build
and each response's length/hash before decoding. Missing or corrupt files show
an error; they never trigger a live API fallback. These checks establish file
integrity, not real-source fidelity.

The manifest also records the recipe and exact generated example IDs. Rebuild
the entire distribution after regenerating data; do not mix files from builds.
IDs from an earlier build need not remain valid after regeneration. Only
`demo-dist` is suitable for hosting. SQLite, Parquet, executable manifests and
source configuration are not part of it. Demo exports cannot be imported into
the operational engine as snapshots or runs.

## Verify

```bash
npm --prefix frontend test
npm --prefix frontend run demo:build
cd frontend
npx playwright install chromium
cd ..
npm --prefix frontend run demo:test
```

An installed Chrome can be selected with `BACKTEST_BROWSER_CHANNEL=chrome`.
Tests serve the distribution under `/onchain-backtest-engine/` on loopback port
18745 (`BACKTEST_DEMO_TEST_PORT` overrides it). They cover whole-result graph
loading, group/wallet navigation, pair evidence, mode changes, both strategy
outcomes, market history, lineage, direct reload, keyboard navigation, Russian,
theme persistence, mobile layout and missing/corrupt files. Transport tests
reject mutations and unknown requests without contacting an API.

The normal `npm --prefix frontend run build` still builds the operational UI
into the Python package. It neither reads demo data nor includes a fixture
fallback. Both profiles are checked by CI; all repository gates still apply.

## Publish later, explicitly

Publication requires a separate decision. Nothing in the commands above pushes
code, changes repository settings or deploys a site.

When publication is authorized and the code is on GitHub:

1. In **Settings → Pages → Build and deployment**, select **GitHub Actions**.
2. Ensure `demo-pages.yml` exists on the default branch so **Run workflow** is
   available. Select the desired branch/revision under **Actions → Static demo /
   GitHub Pages**.
3. Run with **publish** unchecked first. This generates fixtures, builds and
   runs the tests without uploading or deploying a site.
4. Run with **publish** checked to publish that verified build. The deployment
   job receives only Pages/OIDC permissions and uploads only `frontend/demo-dist`.
5. Open the URL in the deployment result. Do not interpret a prepared local
   link as an already published GitHub Pages URL.

The workflow is manual only and its actions are pinned to immutable commits.
GitHub account/repository eligibility and environment protection settings still
apply. See GitHub's [custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
and [publishing-source settings](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

The normative boundary and caps are in
[deep-dive §34.3](architecture-deep-dive.md#343-static-demonstration-distribution).

---

Language: **English** · [Русский](demo.ru.md)
