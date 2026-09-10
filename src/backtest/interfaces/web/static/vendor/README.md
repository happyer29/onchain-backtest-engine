# Packaged graph display dependency

Cytoscape.js **3.34.3**, MIT, is vendored unchanged from the official tagged
release. It is a browser-only renderer for the current research pair page.
No Node server, CDN, analytics plugin, graph-analysis recipe or Python
dependency is added. Existing CSP remains `script-src 'self'` and
`style-src 'self'`; the HTML also pins the bundle with SHA-384 SRI.

| File | Upstream source |
|---|---|
| `cytoscape-3.34.3.min.js` | <https://raw.githubusercontent.com/cytoscape/cytoscape.js/v3.34.3/dist/cytoscape.min.js> |
| `cytoscape-3.34.3.LICENSE` | <https://raw.githubusercontent.com/cytoscape/cytoscape.js/v3.34.3/LICENSE> |

Bundle size: **435,503 bytes**. SHA-256:
`5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91`.
Preserve upstream bytes and license when updating; update the versioned name,
SRI, digest assertion and installed-wheel/browser checks together.

The former SVG displayed 25 edges and, on the saved 1,000-second example,
26 nodes, with zero zoom/pan/drag/selection controls. The library supplies those
missing interactions without building another renderer. The integration still
accepts at most 25 edges / 50 nodes, one graph instance, device pixel ratio 1,
and a non-animated layout capped at 400 iterations. Layout coordinates and
visual emphasis have no analytical meaning or effect on research identity.

`research-graph.js` is the small application-owned integration. Source-scope
filters, time windows, statistical analysis and result publication remain
outside it. The table remains usable if the library is unavailable.

## Verification

Run the extra UI tests when changing this integration:

```bash
node --test tests/web/research-graph.test.cjs
.venv/bin/pytest tests/integration/test_research_web_assets.py
```

Node is a test tool only; installed CLI/API operation requires no Node runtime.
The JavaScript tests use the real pinned graph core with a minimal control
surface, covering exact string evidence IDs, pointer/keyboard selection, zoom
bounds, page replacement, empty/oversized pages and missing-library feedback.
Real-browser smoke additionally checks canvas drag, edge selection, fit,
expansion, page navigation, evidence drilldown, explanation and narrow layouts.
The API test checks actual packaged script responses, load order, CSP, SRI,
upstream hash and license. Repeat it against an installed wheel before release.
