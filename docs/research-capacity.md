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

## Verification

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
