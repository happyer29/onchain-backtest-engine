"""Serve a fresh hermetic FirstSwap fixture for real React browser tests."""

import importlib
import json
import os
import signal
import subprocess
import sys

# This development-only harness reuses bounded fixtures; no live source configuration is loaded.
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/integration/jobs"))
fixture = importlib.import_module("test_real_control_http")


def prepare(directory: Path, port: int) -> Path:
    """Publish actual immutable inputs/results through the production application boundary."""
    data_root = directory / "data"
    config = directory / "browser.toml"
    fixture._write_config(config, data_root, port, progress_interval_ms=50)
    source = fixture._source()
    # Inspection and planning operate only on the fixed in-memory test source.
    artifacts = fixture.LocalArtifactRepository(data_root)
    inspection = fixture.StoreSourceInspection(
        fixture.InspectSource(source, now=lambda: datetime(2025, 12, 31, tzinfo=UTC)), artifacts
    ).execute(fixture.InspectSourceRequest(fixture.SourceId("fixture-indexer")))
    plan = fixture.PlanDataset(
        fixture.ArtifactSourceInspectionLoader(artifacts), fixture._planning_policy()
    ).execute(fixture._plan_request(inspection.artifact.artifact_id))
    # The canonical writer publishes the fixture under the regular commit protocol.
    tools = fixture.BuildToolBundleRegistry().pin()
    store = fixture.LocalArrowCanonicalStore(artifacts, memory_limit_mb=256, build_tools=tools)
    prepared = fixture.PrepareDataset(
        source, fixture._projector(), store, clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
    ).execute(fixture.PrepareDatasetRequest(plan))
    settings = fixture.load_settings(config)
    container = fixture.build_runtime_container(settings, profile=config.stem)
    # Direct CLI execution creates genuine job/result/index state for browser discovery.
    replay = fixture.CanonicalParquetReplaySource(
        artifacts, prepared.snapshot_id, build_tools=tools
    )
    spec = fixture._resolved_run_spec(prepared, replay, container.runtime_manifest.runtime_lock_id)
    request = fixture.RunBacktestRequest(spec, fixture.ContentDigest("8" * 64))
    result = fixture.RuntimeCliBackend(container, config).run_backtest(request)
    print(json.dumps({"fixture_run": result.artifact.artifact_id.hex}), flush=True)
    return config


def main() -> None:
    """Own temporary storage and always forward test-runner termination to the controller."""
    port = int(os.environ.get("BACKTEST_BROWSER_PORT", "8795"))
    with tempfile.TemporaryDirectory(prefix="backtest-react-browser-") as temporary:
        config = prepare(Path(temporary), port)
        process = subprocess.Popen(
            [sys.executable, "-m", "backtest.bootstrap.cli", "serve", "--config", str(config)],
            cwd=ROOT,
        )
        # The child remains the sole controller; this harness only forwards its lifecycle.
        signal.signal(signal.SIGTERM, lambda *_: process.terminate())
        signal.signal(signal.SIGINT, lambda *_: process.terminate())
        try:
            process.wait()
        finally:
            if process.poll() is None:
                # A failed browser test must not leave an orphan local supervisor.
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
