# Web UI guide

**Language:** English · [Русский](ui-guide.ru.md) · [简体中文](ui-guide.zh-CN.md)

This guide explains the complete browser workflow. Every screenshot was made
from an isolated synthetic fixture: the identifiers and results are examples,
not live-source evidence or recommended strategy parameters.

## Open the workspace

Start the loopback-only server from the repository root:

```bash
backtest serve --config configs/local.toml
```

Open `http://127.0.0.1:<control.port>`. The default language is English. Open
**Settings** at the bottom of the sidebar to select Russian or change the
appearance. If you only want to explore the interface, use the
[static demo](demo.md); it cannot submit execution jobs.

## 1. Start from Overview

![Workspace overview with navigation, host resources, recent results and jobs](assets/ui-overview.png)

The sidebar is the map of the application:

| Page | Use it for |
| --- | --- |
| **Overview** | Check local resources, recent verified results, and recent jobs. |
| **Prepare data** | Inspect a configured source and publish bounded local snapshots. |
| **Launch strategy** | Resolve and queue Sniping, Copy Buy, or FirstSwap. |
| **Job queue** | Follow progress, read events, cancel, or retry when allowed. |
| **Strategy results** | Open completed runs, compare summaries, and inspect trades. |
| **Models and features** | Build the point-in-time ML artifact chain. |
| **On-chain research** | Explore observed signers, shared purchases, and source evidence. |
| **Artifacts and lineage** | Verify exact artifacts and their dependency closure. |
| **Resources** | Inspect current host admission limits and capacity. |

Green **Local execution** means the browser is connected to the local Control
API. It does not mean that an external source has been configured or admitted.

## 2. Prepare verified data

![Prepare data page with source inspection and bounded dataset fields](assets/ui-prepare-data.png)

Use **Prepare data** from top to bottom:

1. In **Source inspection**, select the logical source ID and press
   **Inspect source**. Inspection is bounded and read-only.
2. Use the returned inspection and capability identifiers in the dataset plan.
3. Choose a bounded half-open range: the start is included and the end is
   excluded. Keep the first run small.
4. Submit preparation. Heavy work appears in **Job queue**; the HTTP request
   does not run the extraction itself.
5. After `SUCCEEDED`, open the receipt or **Artifacts and lineage** and copy the
   exact Snapshot/ReplayPack identifiers needed by later forms.

Never paste a password, private key, arbitrary SQL, or a filesystem path into
the UI. Source credentials belong in the local secret mechanism described in
[Configuration](configuration.md).

## 3. Launch a strategy

![Copy Buy launch form with strategy selector and expandable parameter groups](assets/launch-strategy.png)

1. Open **Launch strategy** and choose **Pump.fun Sniping**, **Pump.fun Copy
   Buy**, or **FirstSwap**.
2. Fill **Data and strategy** with the exact artifact IDs and trading pair
   required by the selected contract.
3. Review **Entry and exit**. Values are integer atomic amounts, basis points,
   transaction counts, or seconds as indicated by each label.
4. Expand the account, fee, reproducibility, and resource sections. Defaults
   are examples, not recommended trading parameters.
5. Press **Run strategy**. The UI first validates and resolves an immutable
   specification, then shows a queue receipt.
6. Follow **Open queue**. A successful submission is not a successful result;
   wait for `SUCCEEDED` and open the published output.

Synthetic or virtual settlement is explicitly labelled. Do not interpret its
proceeds as proof that an equivalent sale could execute on-chain.

## 4. Follow work in Job queue

![Job queue with state filter, search, result links and event buttons](assets/ui-job-queue.png)

- Use the state filter to isolate queued, running, failed, or completed work.
- **Events** shows durable progress and the exact typed failure when a job stops.
- **Cancel** is offered only when the current state permits cancellation.
- **Retry** creates another attempt for the same immutable command; it does not
  silently change its inputs.
- Result links appear only after a verified artifact has been published.

The page updates automatically while visible. Use **Refresh** after returning
from a suspended or hidden browser tab.

## 5. Read strategy results

![Verified strategy result with summary cards, tabs and charts](assets/strategy-results.png)

Open **Strategy results**, choose a run, then read the page in this order:

1. Confirm **Verified result**, strategy name, network, and any fidelity or
   synthetic-execution warning.
2. Read the summary cards. A dash means unavailable, not zero.
3. Use **Overview** for aggregate outcomes, **Entries** and **Exits** for
   decisions, **Trades** for exact fills, and **Verification** for provenance.
4. In **Verification**, open the manifest and lineage before comparing results
   produced from different inputs.
5. Open **Details** on a trade to inspect its fills and bounded market history.

![Trade detail chart with signal, buy and sell markers](assets/trade-detail.png)

**Around trade** narrows the view; **Full history** reuses the same bounded
stored history. Hover chart points for exact values and expand the evidence
section when a visual summary is not sufficient.

## 6. Run the basic ML workflow

![Predictions tab with the causal prefix option](assets/ui-ml-predictions.png)

Use the tabs strictly from left to right:

1. **Features** publishes point-in-time features from a ReplayPack.
2. **Universe** defines eligible rows.
3. **Labels** publishes training-only outcomes.
4. **Training** produces one immutable model bundle.
5. **Model schedule** states when that frozen model becomes available.
6. **Predictions** applies the schedule to features.

Each stage consumes exact IDs from the preceding stages. Training may use early
ReplayPack rows even though a fitted model did not exist at those rows. In
**Predictions**, choose **No prediction before first model** to leave that
leading prefix unscored. Internal or trailing schedule gaps remain errors. Use
the same prefix policy in a FirstSwap run that consumes this PredictionSet.

For a minimal source-free example, run `python -m
backtest.examples.ml_baseline` or read [Synthetic ML baseline](ml-baseline.md).

## 7. Explore on-chain research

![Research result summary with exact counts and data-quality warning](assets/ui-research.png)

Research has two separate steps: prepare a bounded snapshot, then analyze a
saved snapshot. An empty signer list means all observed signers within the
snapshot, not every wallet on the network. The result header records the exact
window, threshold, signer scope, and token mode.

Always read data-quality warnings. Rows excluded because creation evidence is
missing remain visible as an explicit problem; they are not silently treated as
ordinary observations.

![Wallet relationship graph built from the saved synthetic research result](assets/ui-research-graph.png)

In the graph:

- nodes are wallets and an edge is an observed qualifying pair;
- **Current page** uses the loaded table page, while **Whole result** loads the
  bounded complete result;
- the display threshold hides edges only from the view and does not recompute
  saved groups or evidence;
- select a wallet or group to narrow the view, then open original purchases to
  verify why a relationship exists;
- use the **Data issues** tab before drawing a conclusion.

Research output is a hypothesis/evidence artifact. It does not automatically
become a strategy, model feature, or execution permission.

## 8. Verify artifacts and resources

Use **Artifacts and lineage** to open an artifact by ID, verify its digest, and
walk the exact dependency graph. Do not edit files under the data root by hand;
modified or incomplete artifacts fail verification.

Use **Resources** to see memory, process, temporary-storage, and disk admission
limits. If a job is rejected for capacity, reduce its bounded scope or change
the local configuration deliberately. Repeatedly pressing the launch button
does not bypass admission.

## Common problems

| Symptom | What to check |
| --- | --- |
| UI opens but source inspection fails | Configure the source profile and secret reference; the UI itself requires no live source. |
| Submit button is unavailable | Complete every required field and use the artifact type/version requested by the selected contract. |
| Job is present but no result link exists | Open **Events**; only `SUCCEEDED` jobs publish a result. |
| A number is shown as `—` | The metric is unavailable for that result; it is not zero. |
| Early ML rows cannot be predicted | Select **No prediction before first model** and use the matching inference policy. |
| A research graph looks smaller than the table | Check page/whole-result mode and the display threshold; hidden edges remain in exact evidence. |

For exact command equivalents, see [CLI and workflows](cli-reference.md). For
security and source settings, see [Configuration](configuration.md).
