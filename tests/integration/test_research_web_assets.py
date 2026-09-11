"""Verify the distributed research graph uses pinned same-origin bytes under strict CSP."""

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
    # Historical research URLs use the exact same React shell and secure session boundary.
    assert response.text == client.get("/").text
    assert 'id="__________cytoscape_stylesheet"' in response.text
    assert "position: relative" in client.get("/static/graph-canvas.css").text
    page = _Scripts()
    page.feed(response.text)
    paths = [script["src"] for script in page.scripts]
    assert len(paths) == 2
    assert paths[0] == "/static/theme.js"
    assert page.scripts[1]["type"] == "module"
    for path in paths:
        assert isinstance(path, str) and path.startswith("/static/")
        asset = client.get(path)
        assert asset.status_code == 200
        assert "javascript" in asset.headers["Content-Type"]
    # The production manifest is shipped with every lazy chunk; no old global controller survives.
    from backtest.interfaces import web

    static_root = Path(web.__file__).parent / "static"
    scripts = list((static_root / "assets").glob("*.js"))
    assert any("local-modularity-20-v1" in script.read_text() for script in scripts)
    for script in scripts:
        assert client.get(f"/static/assets/{script.name}").content == script.read_bytes()
    for removed in (
        "research.html",
        "research.js",
        "research.css",
        "research-graph.js",
        "research-hierarchy.js",
        "research-graph-model.js",
        "research-graph-load.js",
        "vendor/cytoscape-3.34.3.min.js",
    ):
        assert client.get(f"/static/{removed}").status_code == 404
    # The existing pinned renderer now participates in the locked frontend closure and notices.
    notices = client.get("/static/third-party-licenses.txt")
    assert notices.status_code == 200
    assert "cytoscape @ 3.34.3" in notices.text
    assert "The Cytoscape Consortium" in notices.text
    assert "Permission is hereby granted, free of charge" in notices.text
