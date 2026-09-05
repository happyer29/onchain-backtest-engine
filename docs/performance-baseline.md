# Performance measurement

Benchmark an exact committed input and compare equivalent execution paths.
Resource and admission requirements are defined in
[architecture deep dive](architecture-deep-dive.md), sections 27 and 32.

## Benchmark command

```bash
backtest benchmark TARGET_ARTIFACT_ID \
  --attempt-nonce SHA256 \
  --workload REPLAY_PACK_SCAN \
  --launch-route LOCAL_ARTIFACT \
  --capacity-days 1 \
  --batch-rows 65536 \
  --readahead 1 \
  --process-count 1
```

Replace `TARGET_ARTIFACT_ID` with a verified local artifact ID and `SHA256`
with a fresh attempt nonce. The command publishes a versioned `BENCHMARK`
artifact through the normal atomic publication protocol.

| Workload | Target | Launch route |
|---|---|---|
| `PARQUET_SCAN` | Snapshot | `LOCAL_ARTIFACT` |
| `REPLAY_PACK_SCAN`, `REFERENCE_REDUCER`, `OPTIMIZED_REDUCER` | ReplayPack | `LOCAL_ARTIFACT` |
| `FULL_BACKTEST`, `EMBEDDED_INFERENCE`, `FROZEN_INFERENCE` | Successful Run | `LOCAL_ARTIFACT` |
| `CONTROL_PLANE_ROUND_TRIP` | Successful Run | `DIRECT` or `CONTROL` |

The resolver verifies target type, retained dependency closure, runtime, and
inference mode before measurement. Control-plane measurements use one process.

## Comparison procedure

1. Pin the same exact semantic input and execution mode for both backends.
2. Record runtime, hardware, batch size, readahead, process count, native
   threads, and cache condition in the benchmark artifact.
3. Profile the one-day target in a separate spawned child. Admit the requested
   process count only after measuring its memory requirements.
4. Separate warm-up from measured iterations. Compare median wall time and
   require the same canonical result hash in every measured iteration.
5. Record wall and CPU time, throughput, private/total RSS with its measurement
   basis, page faults, swap, and available process I/O counters.

Batch choices are 32k/64k/128k/256k, readahead is 1/2/4, and independent-process
choices are 1/2/4. One stateful run always uses one sequential child process.
A repeated base stream for capacity 7/30 is
`REPEATED_INDEPENDENT_BASE_STREAM`; it is not a continuous historical period.

`WARM`, `UNCONTROLLED`, and `EXTERNALLY_COLD` are distinct cache conditions.
`EXTERNALLY_COLD` requires a verified external eviction controller and is
otherwise rejected. An uncontrolled run is not cold-cache evidence.

For `CONTROL_PLANE_ROUND_TRIP`, isolated artifact closure, private SQLite,
controller, and server readiness are prepared outside the timed body. `DIRECT`
measures `DirectJobExecutor`; `CONTROL` measures real loopback HTTP submission,
the durable queue, supervisor, child execution, terminal polling, and typed
result query. Both routes reopen the committed Run manifest and verify its
canonical result.

## Pump.fun optimized-backend admission

Software admission requires byte-identical normalized audit, ledger, fills,
round trips, final balances, and result hashes across reference Parquet,
reference ReplayPack, and optimized ReplayPack. Verify each execution mode
separately; evidence for one mode does not admit another.

Production admission additionally requires a representative exact external
snapshot with:

- median full strategy-plus-ledger wall time at least 2× faster than reference;
- identical canonical results across all measured iterations;
- peak private RSS at most 3 GiB on the 16-GB profile or 6 GiB on the 32-GB profile;
- no sustained swap and one sequential child/native thread per run;
- clock storage proportional to blocks/events rather than transaction count.

Fixture performance does not establish source fidelity or live throughput.
A measurement admits only its exact input, mode, cache condition, and settings.
FirstSwap results do not establish Pump.fun performance. Cold-cache,
7-/30-day workloads, source extraction, ML, and Control API overhead require
separate measurements; no universal throughput or deployment SLO is implied.

## Reproducible fixture checks

```bash
.venv/bin/pytest -q -m performance \
  tests/performance/test_replay_30_day_capacity.py -s
.venv/bin/pytest -q -m performance \
  tests/performance/test_sniping_capacity.py -s
```

These opt-in checks exercise deterministic fixtures. Keep benchmark reports
with the corresponding local artifacts. Before admitting an optimization,
compare equivalent before/after inputs, canonical hashes, wall time, memory,
page faults, swap, and I/O. A speedup without golden equivalence is rejected.

---

**Language:** English · [Русский](performance-baseline.ru.md)
