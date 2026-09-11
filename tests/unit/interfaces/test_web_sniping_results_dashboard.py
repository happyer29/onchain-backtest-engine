"""Packaged React assets form one closed same-origin application.

Shared result semantics/charts are exercised by frontend component/browser tests.
"""

import json
import re
from pathlib import Path


def test_single_react_shell_has_a_complete_hashed_asset_closure() -> None:
    """Lazy-loaded charts and lineage must be packaged alongside the main entry."""
    static = Path(__file__).parents[3] / "src/backtest/interfaces/web/static"
    manifest = json.loads((static / ".vite/manifest.json").read_text())
    markup = (static / "index.html").read_text()
    assert 'id="root"' in markup and manifest["index.html"]["isEntry"]
    # The manifest describes code/CSS chunks only, not user data or external resources.
    for item in manifest.values():
        assert (static / item["file"]).is_file()
        for stylesheet in item.get("css", []):
            assert (static / stylesheet).is_file()
        assert all(key in manifest for key in item.get("dynamicImports", []))
    # One shell replaces all three renderers; no retained legacy script may be served.
    assert list(static.glob("*.html")) == [static / "index.html"]
    assert not any(
        (static / name).exists()
        for name in ("app.js", "sniping-results.js", "copy-results.js", "copy-market-chart.js")
    )
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', markup)
    assert scripts and all(path.startswith("/static/") for path in scripts)
    assert not re.search(r"<script[^>]*>\s*[^<\s]", markup)


def test_react_source_has_no_legacy_html_injection_or_browser_secret_access() -> None:
    """Framework internals may use DOM sinks; application-authored source may not."""
    source = Path(__file__).parents[3] / "frontend/src"
    files = [*source.glob("*.tsx"), *source.glob("*.ts")]
    forbidden = ("dangerouslySetInnerHTML", "document.cookie", "insertAdjacentHTML", "eval(")
    for path in files:
        if ".test." in path.name:
            continue
        # These source-level guardrails supplement real strict-CSP browser execution.
        text = path.read_text()
        assert not any(token in text for token in forbidden), path
