# Wallet research capacity evidence

Date: 2026-09-10. This records one saved live-source cut under
[deep dive §24.6](architecture-deep-dive.md#246-on-chain-wallet-research).
This historical measurement uses v1 snapshots and **all token modes**. Under
v2, reproduce its selection with `--mode ALL` over the original v1 snapshot;
a fresh v2 snapshot also applies explicit data-quality exclusions. This historical
measurement does not measure the new non-Mayhem subset or creation lookup.
It calibrates existing finite implementation guards; it does not establish
general live-source capacity, completeness, finality or causal availability.

## Workload and result

The verified snapshot covers Solana blocks `[445840000,445852744)` and contains
97,040 observations from 10,075 signers. The maximum number of first-BUY
participants for one mint is 1,311; the pre-window candidate count is 2,988,629.
Both exceeded the previous limits of 512 participants and 2 million candidates.
Those guards run before the time filter, so reducing the window cannot help.

The calibrated limits are 2,048 participants per mint and 4 million candidates.
The recipe, first-purchase ordering, inclusive window, multiplicity, complete
output and failure semantics are unchanged. Empty selection includes all
signers; no token is dropped and no top-wallet selection is substituted.

At 180 seconds and a minimum of two shared mints, all 97,040 rows participate:
10,075 activity rows, 81,645 pairs and 213,851 pair/mint evidence rows. The
browser submitted an empty signer selection, the isolated job succeeded in
7.145 seconds including queue/publication, and its verified result opened with
a 25-edge graph and source-purchase drilldown. Whole-result counts cover all
rows; the graph covers only the current page.

- Snapshot: `ea60a0d05140a9d149aa8bda3fee3c4db63f621187ae70b1119e37f379479894`
- Result: `9f3b1efcf5050b070073fd4e5049bfb6abb5cc558e83248966791ff7bfa4954a`
- Analysis code digest: `1d266cc0e6a7327411b55239d4928afe18a68c28e984045bbdb30432ad7f0ecd`
- Runtime digest: `b2cfba5462b19bd3bdab86249097dfffe6355475d8e5c65a3bc5abb0c6d715f8`

## Resource measurement

Two fresh Python processes on macOS arm64 called the actual verified local
store and writer with the same saved snapshot, 256 MB DuckDB memory and one
native thread. The baseline process restored the old two numeric caps; it
aborted before the join without a result. The changed process completed and
reproduced the browser result's exact content ID. Neither connected to a source.

| Measurement | Old caps: rejected | New caps: complete |
| --- | ---: | ---: |
| Store wall time, seconds | 3.931 | 6.192 |
| Peak total RSS, bytes (`getrusage`) | 275,398,656 | 493,322,240 |
| Sampled private footprint, bytes (10 ms) | 217,482,296 | 432,751,792 |
| Major faults (`getrusage`) | 165 | 39 |
| Process swap events (`getrusage`) | 0 | 0 |
| Kernel disk bytes read | 13,901,824 | 4,321,280 |
| Kernel disk bytes written | 0 | 43,929,600 |

These are single warm-host measurements, not a speedup or cold-cache benchmark.
Disk counters are macOS `proc_pid_rusage` deltas, not logical input bytes;
sampled private memory is not a continuous peak. A separate read-only query
probe measured 215,678,976 spill bytes at completion. The unchanged operational
envelope admits 512 MiB child private memory, caps temporary/output space at
1 GiB each, gives DuckDB one third of the temporary allowance for spill, and
interrupts queries after 120 seconds. Larger inputs may still fail these guards.

## Regression and reproduction

The hermetic capacity test uses 1,200 signers buying three mints (2,158,200
candidates), with one independently specified pair exactly 180 seconds apart.
It proves all activity remains and each mint contributes once. Separate cases
exceed only the participant cap or only the candidate cap and prove that no
result is committed. Existing corruption, cancellation and determinism tests
continue to apply.

With the exact snapshot retained in the selected profile's data root:

```bash
backtest research analyze <SNAPSHOT_ID> --window-seconds 180 \
  --minimum-shared-mints 2 --mode ALL --config <LOCAL_PROFILE>
```

Omit `--wallet`, or leave the dashboard signer field empty. A different code
or runtime digest requires a fresh resolution. The snapshot and earlier
results retain their original identity and meaning. This evidence does not
admit any new Sniping cut or make research results executable strategy inputs.

## Wide-window follow-up

The 1,000-second all-signer job subsequently failed in the original string-based
`pairs` aggregation: DuckDB exhausted its 341.3 MiB spill allowance and emitted
`RESEARCH_MEMORY_LIMIT`. Passing the prejoin candidate cap does not guarantee
that later aggregation fits its independent memory/spill budget.

The adapter now assigns bounded `UINTEGER` dense ranks in lexical signer/mint
order after selecting first buys. Only numeric keys and exact observation
references enter the potentially quadratic `matches` relation. Pair grouping
uses those keys, and final streaming projections restore full addresses. No
source row, participant or mint is filtered to save resources; first-buy order,
inclusive windows, pair direction, evidence order, schemas and quotas are unchanged.

The same saved cut, empty selection and minimum of two shared mints produce:

| Window | Wallets | Pairs | Evidence | Result ID |
| --- | ---: | ---: | ---: | --- |
| 1,000 s | 10,075 | 153,869 | 389,460 | `11a963e2dd0a3d23918fe10af03c16ed29f5a50e267659f0ac095dabd9a9c0e5` |
| 3,600 s | 10,075 | 171,226 | 431,295 | `9336a12f4383dec47ce30f29356801fef04eb48aa2e051b3fa4907bf2946b9b3` |

Both retain all 97,040 observations and the same runtime digest. The compact
code digest is `f11599e40d55acf7f9b3599937fa6f04878c740ce9ac18a44b9c8fa011cc8e72`.
Earlier artifacts remain immutable and readable with their original meaning.

Fresh-process measurements use the same method and operational quotas as above:

| Measurement | Original 1,000 s: rejected | Compact 1,000 s: complete | Compact 3,600 s: complete |
| --- | ---: | ---: | ---: |
| Store wall time, seconds | 4.696 | 6.726 | 7.198 |
| Peak total RSS, bytes | 489,062,400 | 541,917,184 | 551,993,344 |
| Sampled private footprint, bytes | 430,359,704 | 482,411,720 | 483,083,464 |
| Major faults | 156 | 1 | 8 |
| Process swap events | 0 | 0 | 0 |
| Kernel disk bytes read | 13,684,736 | 10,534,912 | 4,096 |
| Kernel disk bytes written | 55,115,776 | 66,879,488 | 76,181,504 |

Successful runs do more work than the aborted baseline; these figures are
capacity evidence, not a speedup comparison. Private footprint stays within
the 512 MiB admission budget; total RSS includes shared/mapped memory. The
256 MB native memory, one thread, 120-second interrupt and finite spill/output
limits remain in force. Cache state was not controlled, so disk reads/faults
cannot support a cold-cache performance claim.

An independent run of the original `ab2fbec` SQL, with a larger finite reference
spill allowance, matched every byte of all three complete 1,000-second Parquet
tables. Their SHA-256 values are:

- Activity: `1e3064ed202f2ab0039e39b202d5d2ecb0f5e8790c169f7e0d3ca825d16ce995`
- Pairs: `b9191d92022dc88f7e63cea6309623264bf23dcd3ee71fdcc9ae6cc8f55634c8`
- Evidence: `bfa0a209d0583e825f59a8bd14730eac227ac1c51fc317ec91a566f47055a94b`

The hermetic dense regression has 600 signers buying two mints within 1,000
seconds: all 179,700 pairs and 359,400 evidence rows must fit a 64 MB native /
64 MiB spill workspace. It fails on the original recipe and passes on compact
keys. Frozen original table bytes are also checked with one and two native
threads; a separate tiny-spill case still aborts without publishing a result.

Both windows also passed through the actual loopback browser/API queue and
isolated child with the unchanged deployment profile: 8.891 seconds for
1,000 seconds and 8.193 seconds for 3,600 seconds, including queue/publication.
Their verified IDs match the direct-store measurements. The browser displayed
the complete counters, a bounded 25-edge graph and original-purchase drilldown.

## Verification of the original cap change

All commands ran from the isolated feature worktree using its virtual environment:

```bash
.venv/bin/ruff format --check src tests
.venv/bin/ruff check src tests
.venv/bin/mypy src/backtest
.venv/bin/lint-imports
.venv/bin/pytest --cov=backtest --cov-report=term-missing
```

Formatting/lint/types passed and all five import contracts held. Pytest passed
1,367 tests with 80.80% coverage: one external ClickHouse test remained opt-in
and skipped, and three performance-marked tests were deselected by the standard
gate. The measured full-snapshot run above supplies the change-specific
capacity evidence. Browser checks covered empty selection, graph pagination,
source-purchase drilldown and opening the verified successful result.

The same full gate after the compact-key change passed 1,371 tests with 80.81%
coverage, one opt-in external test skipped and the same three performance tests
deselected. Formatting, lint, types and all five import contracts passed too.
No live source query was needed for this follow-up.


## Whole-result flat graph baseline (2026-09-10)

This historical flat-renderer baseline predates the three-level presentation
recorded below. The display-only §24.6 mode was checked on the retained 1,000-second result
`11a963e2dd0a3d23918fe10af03c16ed29f5a50e267659f0ac095dabd9a9c0e5`:
153,869 exact pairs and 2,924 distinct pair participants. Its 10,075 activity
signers are a different population. No source scan or analytical recalculation
was performed; the research code digest remained
`f11599e40d55acf7f9b3599937fa6f04878c740ce9ac18a44b9c8fa011cc8e72`.

The actual static loader and real Cytoscape 3.34.3 model were measured with
Node 24.15.0 on macOS arm64. The historical `tests/web/research-graph.test.cjs` harness
(retained in commit `8d04150`; replaced by React tests in the current tree)
replaced only browser geometry/mounting. This measures transfer/model costs,
not browser canvas rendering or frame rate:

| Phase | Wall time | RSS after phase | Process high-water RSS |
|---|---:|---:|---:|
| Read all 770 bounded API pages | 4.279 s | — | — |
| Construct 25-row page from the already loaded input | 0.014 s | 221,741,056 B | 216,544 KiB |
| Construct all 153,869 edges in batches of 1,000 | 3.731 s | 656,359,424 B | 675,184 KiB |
| Select first wallet and all 37 incident edges | 0.816 s | 712,556,544 B | 697,744 KiB |

The page measurement retains the same full input for comparison and is not
normal page-only browser memory. After selection, process resource counters
were 59,205 minor / 1,282 major page faults, zero swapped-out pages and zero
filesystem input/output operations reported by Node `resourceUsage`. Loader
byte accounting recorded 39,002,095 response-body bytes. API storage I/O is
outside the Node process, so these counters do not imply zero server disk I/O
or a system-wide no-swap guarantee. The independent earlier 2,000-row / ten
GET probe took 0.054 seconds.

In the real in-app Chromium browser, complete load and canvas construction
reported 8.1 and 8.2 seconds before concurrent full-suite execution. Manual
checks covered cancellation/retry, mode replacement during loading, search of
all pair wallets, exact pair 25 purchase evidence beyond the first 25-row table
page, preserved graph/selection while paginating the table, and narrow 375px
and wide 1280px viewports. The full view uses a geometric grid with straight
edges and no overlapping per-edge labels. Large selection changes yield in
bounded style batches; small changes reuse the mounted canvas. Complete
high-degree inspector pagination and stale selection/build races are also
covered by the JavaScript tests.

The 200,000-edge / 5,000-wallet, response/total-byte and deadline caps reject an
oversized or incomplete whole view rather than sample it. These are display
bounds, not a performance SLA for every browser/device or proof of source
completeness. Dense views cost substantially more than a page; source fidelity
and all analytical/execution admission limits retain their existing meanings.


Verification for this display slice followed deep-dive §§3.4, 6, 24.6, 31,
34.2 and 38. Only the static Web UI, documentation and tests changed; existing
query ports, source access, recipe identity, causality and UNKNOWN fidelity
were preserved. The approved graph count/byte/time limits remain fail closed;
research artifacts still cannot enter replay or Strategy directly.

- `.venv/bin/ruff format --check src tests`: passed (434 files).
- `.venv/bin/ruff check src tests`: passed.
- `.venv/bin/mypy src/backtest`: passed (284 source files).
- `.venv/bin/lint-imports`: passed (5 contracts).
- `.venv/bin/pytest --cov=backtest --cov-report=term-missing`: final quiet run
  passed, 1,372 tests, 80.81% coverage, one explicitly opt-in live ClickHouse
  test skipped and three performance-marked tests deselected by project policy.
- `node --test tests/web/research-graph*.test.cjs`: 22 passed, including limits,
  scope/ordinal/cursor completeness, stream cancellation, exact evidence,
  inspector pagination, prefix-address ordering and replacement races.
- Offline wheel build, installed CLI/API/CSP/SRI and all 13 static assets:
  passed. No credentials, local configuration or extracted data entered the
  wheel or feature diff. No dependency was added.

One intermediate full run had an unchanged existing replay-benchmark worker
initialization failure in
`test_scan_semantic_hash_is_identical_for_serial_and_two_independent_workers`.
The isolated test then passed in 7.26 seconds, and the final full run passed
without parallel graph benchmarking. The replay worker code/tests were not
modified or weakened to obtain that result; the intermittent failure is
recorded rather than treated as graph evidence or hidden by a skip.

## Three-level graph display (2026-09-10)

The approved §24.6 extension changes only static display code. On the same
verified result above, canonical-address weighted local moves stopped after
eight sweeps and produced **81 visual groups**. Every one of 2,924 wallets is
represented. Internal pairs **83,043** plus cross-group pairs **70,826** equal
all **153,869** source-result pairs; the overview has 219 aggregate edges.
The largest group exposes 820 wallets, all 36,349 internal pairs and access to
41,508 external pairs. An initial prototype with a different wallet visitation
order yielded 72 groups; the shipped canonical ordering is covered by an
input-order equivalence test. These are presentation partitions, not findings
of common ownership or coordinated trading.

The same Node 24.15.0 / macOS arm64 harness, real pinned Cytoscape core and
actual sequential verified localhost API were used for the comparison. Canvas
mounting and CoSE geometry are mocked in this harness; these are process/model
measurements, not browser FPS or whole-tab memory. One measured run per version:

| Phase | Flat baseline | Three-level display |
|---|---:|---:|
| Transfer 770 pages / 39,002,095 response bytes | 4.279 s | 5.057 s |
| Full model + initial projection wall time | 3.731 s | 0.788 s |
| RSS after initial projection | 656,359,424 B | 297,877,504 B |
| Process high-water RSS after initial projection | 675,184 KiB | 290,896 KiB |
| Open first wallet's complete 37-pair neighbourhood | 0.816 s | 0.060 s |
| RSS after wallet focus | 712,556,544 B | 298,401,792 B |
| Process high-water RSS after wallet focus | 697,744 KiB | 291,408 KiB |
| Minor / major page faults after focus | 59,205 / 1,282 | 23,883 / 277 |
| Process swappedOut | 0 | 0 |
| Process fsRead / fsWrite | 0 / 0 | 0 / 0 |

The new overview renders 81 nodes and 219 aggregated edges while retaining
all exact rows and compact global adjacency. Expanding a group or wallet
replaces that projection; it does not download or recalculate the result.
The page fixture still retains the same full input for comparison: 0.015 s,
233,897,984 B RSS, so it is not a measurement of normal page-only memory.
API disk I/O is outside the Node process; process counters do not establish
zero server I/O, a system-wide no-swap guarantee or a browser memory ceiling.
Dense individual groups can still contain many edges and consume more memory
than the overview. The unchanged 200,000-pair / 5,000-wallet cap is not a
performance SLA for all devices.

Real-browser inspection initially loaded and grouped the complete result in
7.3 seconds. The 820-wallet group and the first wallet's complete 37 neighbours
were navigable. Its optional neighbour view adds all 666 neighbour-to-neighbour
pairs. Exact pair 25 still opens its two original purchase rows (334 and 86
seconds apart) independently of the first 25-row table page. Grouping, colours,
layout and display toggles do not change the recipe, committed artifacts or
UNKNOWN source fidelity; research artifacts remain unavailable to Strategy.

Final fresh-browser load/build took 6.9 seconds. Cancellation left no canvas and
allowed retry. The member list exposed all 820 members in 50-item pages; opening
its first member showed all 716 incident pairs, with 67,423 optional pairs among
its neighbours. Moving the table to pair 25 preserved that same neighbourhood.
At a 375px viewport there was no horizontal document overflow and the checkbox
remained 13px wide. Wide 1280px inspection and browser warning/error logs passed.

Verification followed §§3.4, 6, 24.6 and 38, retaining existing API/security,
resource and publication boundaries:

- `ruff format --check src tests` / `ruff check src tests`: passed, 434 files.
- `mypy src/backtest`: passed, 284 modules; `lint-imports`: all 5 contracts kept.
- Full `pytest --cov=backtest --cov-report=term-missing`: 1,372 passed,
  80.80% coverage, 192.48 s. One opt-in live ClickHouse test skipped and three
  performance tests deselected by existing project policy; no new live query.
- `node --test tests/web/research-graph*.test.cjs`: 29 passed, covering exact
  group reconciliation, deterministic grouping, all-level/cross-group evidence,
  optional neighbour pairs, bounds, global search, pagination and cancellation/
  replacement races. The focused installed-assets test also passed.
- Offline wheel build and isolated installed CLI/API/CSP/SRI smoke passed;
  all 15 distributed static assets matched source bytes. No new dependency,
  credentials, local configuration or extracted artifacts entered the package.

The research code digest is unchanged from the baseline above. Neither this
presentation nor its grouping policy makes research results causal strategy
inputs or raises UNKNOWN fidelity. Over-limit and incomplete loading still
reject the whole view explicitly; no market completeness or owner clustering
is claimed.


## Research v2 mode filtering and incomplete-creation warnings

The same bounded `[445840000,445852744)` cut completed live preparation and
NON_MAYHEM analysis on 2026-09-10 through the same-origin browser and isolated
supervisor jobs. Parameters: all signers, window 1,000 seconds, minimum 2 shared
mints. The source adapter used the already approved deployment-local HTTP opt-in;
this grants no source completeness, causal-availability or replay fidelity.

- Snapshot: `be09be3b8fd92afff781d7ebe2974b6593ea0ed25b0fb48580b178b3311bb3f1`.
- Result: `59d707f189ed6f4b23d0fe88a25752e0ba257ef446f51dcf570938dc80e98d93`.
- All 97,040 swap observations remain stored, from 10,075 signers and 2,176 mints.
- Reported ordinary mode: 1,656 mints / 53,011 rows; Mayhem: 498 / 44,001;
  missing creation records: 22 / 28, explicitly UNKNOWN.
- Exactly 40 ordinary-mode mints have empty creation signatures, affecting 100
  observation rows. Both snapshot and result warn and list all 40 addresses with
  reasons and row counts. Browser pagination showed 25 + 15 rows and then ended.
- NON_MAYHEM retains 52,911 rows and 9,846 signers; the complete result contains
  150,233 pairs and 367,792 pair-mint evidence rows. Exclusions reconcile as
  `97,040 - 44,001 - 28 - 100 = 52,911`.
- The browser loaded all 150,233 pairs without truncation: 2,752 participating
  wallets and 78 visual groups, in 8.2 seconds on this attempt. Group 1 opened
  all 26,850 internal pairs across 644 wallets; wallet-neighbour navigation
  remains independent of the paginated warning and pair tables.

These are observations for this exact cut and physical browser attempt, not a
new general capacity admission. Mayhem and partial-creation metadata remain
research facts only; Sniping source-evidence gates are unchanged. Legacy v1
artifacts retain their exact original semantics.


Verification for the v2 extension and approved empty-signature exception:

- `ruff format --check src tests` and `ruff check src tests`: passed.
- `mypy src/backtest`: 284 source files passed; `lint-imports`: all 5 contracts kept.
- `pytest --cov=backtest --cov-report=term-missing`: 1,420 passed, 1 external
  read-only test skipped without opt-in, 3 opt-in performance tests deselected;
  coverage 80.92%, 176.70 seconds. The bounded live browser run above is separate.
- All 29 existing Node graph/model/loader tests passed.
- Wheel build, clean installed-package import, installed CLI mode selector,
  API/CSP/SRI and byte equality for all 15 packaged static assets passed.
- Browser warning pagination, complete graph and all three levels passed;
  no browser warning/error log entries were observed and viewport size was restored.
- Changed Markdown local links and `git diff --check` passed. No credentials,
  local source profiles, extracted data or operational artifacts are in the change.

## React workspace integration (2026-09-11)

The existing Cytoscape 3.34.3 renderer was moved from vendored global scripts
into the locked frontend ESM bundle; React now owns forms, tables, warnings,
search, inspectors and projection disposal. No new analytical engine, source
read, recipe identity or grouping policy was introduced by this UI migration.
The former DOM harness is replaced by `frontend/src/research/canvas.test.ts`,
React form tests and `frontend/e2e/research.spec.ts`; the original loader and
weighted grouping oracles remain in `tests/web` and run from `npm test`.

A read-only comparison used the retained NON_MAYHEM result
`59d707f189ed6f4b23d0fe88a25752e0ba257ef446f51dcf570938dc80e98d93`:
150,233 pairs and 2,752 participating wallets. The unchanged bounded loader
read 38,074,725 response-body bytes in 3.837 s through 752 sequential pages.
No ClickHouse query or analytical recomputation was performed.

Three alternating fresh Node 24.15.0 processes per implementation ran on macOS
arm64 with the same cached input and real Cytoscape core. The old side used
commit `8d04150`'s controller harness with its layout stub removed; the new side
used the emitted `canvas.ts` adapter. TypeScript compilation ran before the
measured processes. Canvas mount/painting and React DOM rendering were excluded
on both sides. Each phase includes a full GC before retained-process RSS is
sampled; timings are medians and are observations, not a speed guarantee.

| Phase | Old median | React adapter median | Old retained RSS | React adapter retained RSS |
|---|---:|---:|---:|---:|
| Model + complete overview | 1.579 s | 1.411 s | 303,661,056 B | 303,972,352 B |
| Complete group 1: 644 wallets / 26,850 pairs | 0.975 s | 0.798 s | 548,519,936 B | 569,737,216 B |
| First wallet: 38 nodes / 37 incident pairs | 0.071 s | 0.069 s | 547,438,592 B | 568,819,712 B |

Peak process RSS was 556,992 KiB before and 557,552 KiB after. Final cumulative
minor faults ranged 35,436–37,786 before and 36,959–37,657 after; major faults
were 78 before and 78–171 after. Node reported zero swapped-out pages and zero
filesystem read/write operations for all six processes. These process counters
do not measure API storage I/O or prove a host-wide no-swap condition. Retained
RSS is total process RSS, not private memory or an incremental graph allocation.

Both implementations produced 78 groups after 16 passes, 72,839 internal and
77,394 crossing pairs, and 217 group links. Exact wallet membership SHA-256
matched: `2671a8b72020aa5b87071f0f04db3d628212e82f3fa17a41d6bd672e6a0a5ee5`.
The native browser also opened the complete retained result and the 26,850-pair
group. The hermetic browser gate verifies both actual evidence navigation and
all-signer queued execution, without broadening source fidelity or admission.

Migration checks passed the full Python gate (1,603 tests, 81.40% coverage;
one explicitly opt-in live ClickHouse test skipped and three opt-in performance
tests deselected), TypeScript/build, React/core and loader/model tests, browser
flows, and a wheel installed in an isolated environment. The external container
stylesheet avoids Cytoscape's inline-style injection under the original CSP.
All previous snapshot/analysis versions retain their meaning and failure rules.

## Sigma renderer — 2026-09-11

The user-approved §24.6/§34.2 replacement uses Sigma.js 3.0.3,
React Sigma 5.0.6, Graphology 0.26.0 and ForceAtlas2 0.10.1. These are static
browser display dependencies; DuckDB, the research recipe, exact artifacts,
local-modularity-20-v1 grouping, and source/execution admission are unchanged.
The measured gap was interaction with a complete dense projection: Cytoscape's
canvas handled a series of thirty pan movements much more slowly than Sigma's
WebGL renderer on this retained workload. This is evidence for this UI replacement,
not a claim that every layout or initial load is faster.

The exact retained v2 NON_MAYHEM result is
`59d707f189ed6f4b23d0fe88a25752e0ba257ef446f51dcf570938dc80e98d93`:
150,233 pairs, 2,752 participating wallets, 78 groups, 72,839 internal plus 77,394
crossing pairs and 217 group links. Group 1 has 644 wallets and 26,850 internal pairs.
The selected wallet `1226SFXHBzN68gdPQ12axA8Qa5ynHqQhrbSN8JJuygkJ`
has 37 incident pairs. Both interfaces reported identical counts at all three
levels and read the same 753 bounded pair pages (one initial 25-row page, then
752 whole-result pages). No ClickHouse request or new analysis was performed.

Three fresh headless Chrome 152.0.7977.84 processes per version ran sequentially
at 1440×1000 on macOS arm64, controlled by Node 24.15.0/Playwright. Baseline assets
come from local commit 4996789, fulfilled through the browser test router while
using the same live loopback API/session/CSP. The new assets come from the final
Sigma build. No project test suite ran during these six trials. Measurements
wait for the exact ready group counters and two animation frames; an earlier
selector that could see an outgoing inspector was rejected and the trials rerun.

| Median measurement | Cytoscape at 4996789 | Sigma |
| --- | ---: | ---: |
| Full load, grouping and overview, seconds | 8.458 | 8.885 |
| Open complete group 1, seconds | 2.158 | 0.810 |
| Thirty sequential pointer moves while panning, seconds | 4.611 | 0.524 |
| Zoom-in and Fit controls, milliseconds | 89.0 | 76.1 |
| Open 37-neighbour wallet, milliseconds | 229.8 | 313.3 |
| Group 1 summed process-tree RSS, bytes | 1,297,186,816 | 971,751,424 |
| Group 1 summed physical footprint, bytes | 1,064,068,432 | 834,086,176 |
| Wallet-view summed physical footprint, bytes | 1,372,530,192 | 862,299,424 |

Opening group 1 is approximately 2.66× faster and the thirty-event
interaction completes approximately 8.79× faster in this setup. The initial full load
and the small wallet transition are slightly slower. Median RAF spacing during
panning remains around 16.6ms in both; the pointer-sequence measurement is **not**
an 8.8× FPS claim. The complete group keeps every pair, without top-k omission.

At the final phase, summed process-tree kernel page-ins range 33–366 before and
34–307 after; disk bytes read range 991,232–9,789,440 before and 860,160–9,113,600
after; writes range 2,605,056–2,613,248 before and 2,592,768–2,605,056 after.
These are cumulative Chrome-tree counters, not server I/O or portable
minor/major page-fault counts. RSS can double-count shared pages across processes;
footprint is a sampled OS measure, not a continuous peak. Host `vm_stat` showed
zero swap-outs but 0–52 swap-ins per baseline trial and 20–198 per Sigma trial.
Those are host-wide counts with other applications present, so this is not a
no-swap/cold-cache/production capacity guarantee. OS/disk caches were not reset.

The display threshold is independent of the analysis recipe: at 5 shared tokens,
6,560 of 150,233 pairs remain shown; at 10, 539 remain. Clearing the filter restores
all 150,233 without another pair fetch. Existing groups and every searchable
wallet remain; exact shown/hidden, internal/crossing and current-view counts
reconcile. ForceAtlas2 runs 120 fixed iterations in a single statically bundled
worker within the 30-second projection deadline. Error/cancel/replacement
terminates the worker; missing/lost WebGL leaves tables/evidence available.
Eight coordinate/camera/bounds snapshots and sixteen navigation entries bound
view restoration; inactive renderers and edge copies are not retained.

Validation: 59 Vitest tests plus 20 unchanged loader/grouping tests; 14 full Chrome
scenarios covering existing strategy screens and research, with the final 8
research scenarios rerun after navigation-state completion. The browser tests
exercise worker/CSP failures and retry, actual edge picking, display filters,
exact purchase evidence, and pixel-identical restoration after dragging.
The repository gate passes 1603 Python tests at 81.40% coverage; one explicit live
ClickHouse test is skipped and three opt-in performance tests are deselected.
Frozen npm/uv installation, local wheel build, and installed CLI/API/static-worker
verification complete the packaging gate. Original and v2 research artifacts
retain their meanings and identities.
