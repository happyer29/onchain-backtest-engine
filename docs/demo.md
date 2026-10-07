# Static results on GitHub Pages

The static build shows the version 0.2 React interface with results calculated
before publication. It supports two distinct datasets: generated test examples
and selected results from a real two-hour indexer window. GitHub Pages serves
the interface and presentation JSON without a Python server. The static interface
is English-only, including when the local application previously saved a Russian
language preference. Preparation and publication are separate actions; a push
does not publish the site.

The deployment target is [GitHub Pages](https://happyer29.github.io/onchain-backtest-engine/).
The banner identifies the loaded dataset; a workflow deployment must finish
successfully before that URL serves a new revision.

## Historical version 0.2 results

The historical profile uses OnchainDivers observations for the decision window
**1 September 2026, 00:00–02:00 UTC** (03:00–05:00 Moscow), with the half-open
block interval `[443282098, 443304776)`. Preparation includes an additional
4,096-block settlement tail so positions opened near the decision-window end
can settle. The tail is not an additional entry window.

The main navigation includes Overview, Strategy results, Launch strategy, Job
queue, Prepare data, Models and features, On-chain research, Artifacts and
lineage, and Resources. Published dataset (`#/dataset`) contains the published
window and prepared backtests. Form fields, strategy selection, ML stages and
local display controls can be explored; execution and preparation buttons are
disabled. Queue and resource pages explain why live data is unavailable.

The site lets you choose prepared strategy variants, compare their execution
modes and summary metrics, browse paginated trades, inspect available market
charts, and follow artifact lineage. Real source observations do not make modeled fills real
transactions: strict replay and virtual settlement retain their execution-model
labels. An unavailable chart or one that exceeds the engine's existing query
budget displays its original typed error; publication does not fabricate or
truncate a chart. Other chart failures stop export.

This is a presentation export of completed runs. The full raw indexer dataset,
Parquet snapshots and Python execution engine are not downloaded by the browser.
Changes to preview fields stay in the browser and do not modify the published
results. New runs, data preparation and applying edited settings require the
local application. The static site has no operational API or running job queue.

Historical exports use `backtest.static-history/v1`, recipe
`indexer-two-hour-results/v1`, `synthetic: false` and version `0.2.0`. The manifest
records the UTC window, block interval, verified snapshot IDs and exact selected
run IDs. Limits are 16 runs, 8,192 response records, 2 MiB per response, 256 MiB of
response bytes and a 4 MiB manifest. The build and browser verify all hashes and
reject unsupported requests instead of falling back to a live service.

## Synthetic examples

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
strategy execution, working job queues and live updates require the local
application. The static site has no operational API and cannot create a job.

## Prepare synthetic examples and open locally

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
Use the separate historical exporter below for real completed results; do not
copy operational artifacts into the public directory.

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

## Export completed historical runs

Prepare the snapshot and run the strategies in an isolated local data root with
the normal version 0.2 application. Create a local `selection.json` containing
only `source` and `runs`: `source` has `name: "OnchainDivers"`, `start_utc`,
`end_utc`, `duration_seconds: 7200`, decimal-string `from_block_ordinal` and
`to_block_ordinal`, and `snapshot_ids`; each run has only its artifact `id` and
public `title`. The exporter checks these IDs against committed artifacts and
the snapshots' verified decision intervals.

```bash
.venv/bin/python frontend/scripts/export-history.py \
  --data-root /path/to/isolated-data-root --selection /path/to/selection.json
npm --prefix frontend run demo:build
npm --prefix frontend run demo:test
```

Export runs without network connections and reads no source configuration or
credentials. It writes only allowlisted presentation DTOs, complete trade pages,
available chart responses (including typed chart errors) and bounded lineage.
All source artifacts stay local. An export failure leaves the previous public
corpus in place. Rebuild the site whenever its data changes.

To add the public workspace contracts and selected run inventory to an existing
historical corpus, reuse its verified result responses instead of recalculating
charts. Pin the existing manifest digest and keep the exact source/run selection:

```bash
.venv/bin/python frontend/scripts/export-history.py \
  --data-root /path/to/isolated-data-root --selection /path/to/selection.json \
  --refresh-workspace --manifest-sha256 <existing-manifest-sha256>
```

This checks every existing response, re-verifies the committed artifact closure
and summaries, and adds only the public strategy/ML contracts and selected run
list. It exports no job queue, host measurements or executable manifests.

For CI, archive the **contents** of `frontend/demo-data` as
`pages-history-data.tar.gz` and attach it to a GitHub release. The archive root
contains only `manifest.json`, `manifest.sha256` and `responses/<sha256>.json`.
Record the archive's SHA-256 separately; it pins the bytes even if a release asset
is replaced. A local import uses the same verifier as the publication workflow:

```bash
.venv/bin/python frontend/scripts/import-history.py \
  --archive /path/to/pages-history-data.tar.gz --sha256 <archive-sha256>
npm --prefix frontend run demo:build
```

Import rejects unexpected paths, links, duplicate files, excessive expansion and
incorrect archive or manifest hashes before replacing a recognized demo corpus.
Archive limits are 128 MiB compressed, 260 MiB of file contents and 280 MiB of
decompressed tar data, including headers. The larger historical allowance covers
complete per-trade charts; it does not raise the 2 MiB per-response browser bound.
The build then verifies the complete response inventory and presentation schema.
CI downloads the prepared archive with read-only repository access; it never
connects to the indexer or receives its credentials.

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
outcomes, market history, lineage, direct reload, keyboard navigation, every
product page, editable previews with disabled submissions, fixed English despite
saved Russian preferences, theme persistence, mobile layout and missing/corrupt
files. Transport tests reject mutations and unknown requests without contacting an API.

The normal `npm --prefix frontend run build` still builds the operational UI
into the Python package. It neither reads demo data nor includes a fixture
fallback. Both profiles are checked by CI; all repository gates still apply.

## Publish explicitly

Publication requires a separate decision. Nothing in the commands above pushes
code, changes repository settings or deploys a site.

When publication is authorized and the code is on GitHub:

1. In **Settings → Pages → Build and deployment**, select **GitHub Actions**.
2. Ensure `demo-pages.yml` exists on the default branch so **Run workflow** is
   available. Select the desired branch/revision under **Actions → Static demo /
   GitHub Pages**.
3. Choose **dataset: synthetic** to generate test examples, or
   **dataset: historical** with **data_release_tag** and **data_sha256** to import
   the release asset `pages-history-data.tar.gz`. Synthetic remains the default.
4. Run with **publish** unchecked to verify without deploying, or checked to
   publish the verified build. Both routes run transport and browser tests.
   The deployment job receives only Pages/OIDC permissions and uploads only
   `frontend/demo-dist`.
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
