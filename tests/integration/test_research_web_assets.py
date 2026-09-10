"""Verify the distributed research graph uses pinned same-origin bytes under strict CSP."""

import base64
import hashlib
from html.parser import HTMLParser
from pathlib import Path

# Read assets through the real secure API mount, not a second test-only static server.
from fastapi.testclient import TestClient

from backtest.bootstrap.config import load_settings
from backtest.bootstrap.container import build_runtime_container
from backtest.interfaces.api import create_app
from tests.support.research import DIGEST, configuration


# Parse script declarations using the standard library rather than a new HTML dependency.
class _Scripts(HTMLParser):
    """Collect declared script operands without executing source-provided HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Script ordering and integrity must survive packaging and the actual page response.
        if tag == "script":
            self.scripts.append(dict(attrs))


def test_graph_assets_are_local_pinned_and_serve_under_unchanged_csp(tmp_path: Path) -> None:
    """A missing wheel asset or accidental CDN/CSP change cannot silently ship."""
    config = configuration(tmp_path / "profile.toml", tmp_path / "data")
    container = build_runtime_container(load_settings(config), profile="research-assets")
    client = TestClient(
        create_app(container.control, control_plane_id=DIGEST), base_url="http://127.0.0.1"
    )
    # The document must retain the original strict same-origin script and style policy.
    response = client.get("/research")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'; style-src 'self'" in csp
    assert "unsafe-" not in csp
    # Deferred order loads the dependency before its local integration and client.
    page = _Scripts()
    page.feed(response.text)
    paths = [script["src"] for script in page.scripts]
    assert paths == [
        "/static/vendor/cytoscape-3.34.3.min.js",
        # The graph adapter receives typed page rows from the existing controller client.
        "/static/research-graph.js",
        "/static/research-graph-load.js",
        "/static/research.js",
    ]
    assert all("defer" in script for script in page.scripts)
    for path in paths:
        # Every required script must ship in the package and be reachable without an external host.
        assert isinstance(path, str)
        asset = client.get(path)
        assert asset.status_code == 200
        assert "javascript" in asset.headers["Content-Type"]
    # SRI catches substituted or stale bundle bytes, independently of the response's filename.
    bundle = client.get(str(paths[0])).content
    actual = "sha384-" + base64.b64encode(hashlib.sha384(bundle).digest()).decode("ascii")
    assert page.scripts[0]["integrity"] == actual
    # Pin upstream bytes independently of the HTML checksum, which could otherwise drift with them.
    assert hashlib.sha256(bundle).hexdigest() == (
        "5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91"
    )
    # Preserve legal provenance in the distribution alongside the unchanged upstream build.
    license_response = client.get("/static/vendor/cytoscape-3.34.3.LICENSE")
    assert license_response.status_code == 200
    assert "The Cytoscape Consortium" in license_response.text
    assert "Permission is hereby granted, free of charge" in license_response.text
