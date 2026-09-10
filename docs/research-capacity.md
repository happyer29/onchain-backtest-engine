# Wallet research capacity evidence

Date: 2026-09-10. This records one saved live-source cut under
[deep dive §24.6](architecture-deep-dive.md#246-on-chain-wallet-research).
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
  --minimum-shared-mints 2 --config <LOCAL_PROFILE>
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
