"""Verify a real wheel in an isolated environment and an empty working directory."""

from __future__ import annotations

import argparse
import http.client
import importlib
import importlib.metadata

# The helper uses only the standard library before installing frozen runtime inputs.
import json
import os
import shutil
import socket

# Keep build products, runtime state and process output outside the checkout.
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _run(arguments: list[str], directory: Path, environment: dict[str, str]) -> None:
    """Fail immediately when a build or installed entrypoint command fails."""
    subprocess.run(arguments, cwd=directory, env=environment, check=True, timeout=300)


def _environment() -> dict[str, str]:
    """Prevent the parent's editable import path from reaching the installed check."""
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(name, None)
    return environment


def _install_and_verify(wheel: Path) -> None:
    """Install exactly the frozen runtime dependencies and the built distribution."""
    repository = Path(__file__).resolve().parents[1]
    executable = shutil.which("uv") or str(repository / ".venv/bin/uv")
    environment = _environment()
    with tempfile.TemporaryDirectory(prefix="backtest-wheel-smoke-") as temporary:
        # A fresh venv cannot reuse an editable installation from the development venv.
        directory = Path(temporary).resolve()
        interpreter = directory / "venv/bin/python"
        create = [executable, "venv", str(directory / "venv"), "--python", sys.executable]
        _run(create, directory, environment)
        # Export the lock without the project so no editable requirement can reappear.
        requirements = directory / "runtime-requirements.txt"
        export = [executable, "export", "--frozen", "--no-dev", "--no-emit-project", "--quiet"]
        _run([*export, "--output-file", str(requirements)], repository, environment)
        # Hash-pinned runtime inputs remain separate from the wheel being tested.
        sync = [executable, "pip", "sync", "--python", str(interpreter)]
        sync.append("--require-hashes")
        _run([*sync, str(requirements)], directory, environment)
        install = [executable, "pip", "install", "--python", str(interpreter), "--no-deps"]
        _run([*install, str(wheel)], directory, environment)
        # Isolated mode ignores the checkout helper's directory and user-site imports.
        helper = str(Path(__file__).resolve())
        verify = [str(interpreter), "-I", helper, "--installed"]
        _run(verify, directory, environment)


def _request(port: int, path: str, *, host: str | None = None) -> tuple[int, bytes]:
    """Read a bounded response directly from loopback, without proxies or redirects."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        headers = {"Host": host} if host is not None else {}
        connection.request("GET", path, headers=headers)
        # A packaging smoke must not accidentally download unbounded runtime artifacts.
        response = connection.getresponse()
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise RuntimeError("installed API response exceeds the smoke limit")
        return response.status, body
    # Every polling request owns one short-lived connection, including failure paths.
    finally:
        connection.close()


def _wait_for_health(process: subprocess.Popen[bytes], port: int) -> dict[str, object]:
    """Bound startup time and detect a failed server before polling again."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("installed server exited before becoming healthy")
        # A refused connection is expected only while the local server is starting.
        try:
            status, body = _request(port, "/api/v1/health")
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
            continue
        # Healthy JSON must identify the installed package version, checked by the caller.
        if status == 200:
            return json.loads(body)
        raise RuntimeError(f"installed health endpoint returned HTTP {status}")
    raise RuntimeError("installed server did not become healthy within 30 seconds")


def _verify_http(port: int, package_root: Path) -> None:
    """Prove each packaged dashboard and its runtime UI assets are actually served."""
    static = package_root / "interfaces/web/static"
    pages = ("/", "/sniping-results", "/copy-results", "/research", "/runs", "/launch", "/jobs")
    pages += ("/data", "/ml", "/resources", "/artifacts", "/runs/" + "a" * 64)
    routes = dict.fromkeys(pages, "index.html")
    # Validate all emitted chunks, including lazy charts/lineage, without relying on fixed hashes.
    assets = [
        path.relative_to(static).as_posix()
        for path in static.rglob("*")
        if path.is_file() and path.suffix in {".js", ".css", ".txt"}
    ]
    assert assets and any(name.startswith("assets/") for name in assets)
    assert "third-party-licenses.txt" in assets
    assert 'lang="en"' in (static / "index.html").read_text(encoding="utf-8")
    assert not (static / "app.js").exists() and not (static / "copy-results.html").exists()
    assert "graph-canvas.css" in assets
    for obsolete in (
        "research.html",
        "research.js",
        "research.css",
        "research-graph.js",
        "research-hierarchy.js",
        "vendor",
    ):
        assert not (static / obsolete).exists(), obsolete
    assert 'id="__________cytoscape_stylesheet"' in (static / "index.html").read_text()
    assert "cytoscape @ 3.34.3" in (static / "third-party-licenses.txt").read_text()
    routes.update({f"/static/{name}": name for name in assets})
    # Byte equality catches a missing, stale or incorrectly routed packaged asset.
    for route, name in routes.items():
        status, body = _request(port, route)
        assert status == 200, (route, status)
        assert body == (static / name).read_bytes(), route
    # Contract discovery exercises real composition without submitting a source-backed job.
    status, body = _request(port, "/api/v1/run-contracts")
    assert status == 200
    assert json.loads(body)["items"], "installed run-contract discovery is empty"
    assert _request(port, "/api/v1/health", host="untrusted.invalid")[0] == 400


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Always reap the local server, including when an assertion fails."""
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        # Force cleanup only after the controller has had its normal shutdown grace.
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("installed server exceeded its shutdown grace") from None


def _verify_installed() -> None:
    """Run in the new venv with Python isolation enabled and an empty data root."""
    package = importlib.import_module("backtest")
    package_root = Path(package.__file__).resolve().parent
    assert package_root.is_relative_to(Path(sys.prefix).resolve()), package_root
    assert (package_root / "py.typed").is_file(), "wheel has no typing marker"
    # Resolve both console entrypoints from installed metadata before exercising the CLI.
    distribution = importlib.metadata.distribution("on-chain-backtest-engine")
    entries = {entry.name: entry for entry in distribution.entry_points}
    for name in ("backtest", "backtest-job-child"):
        assert callable(entries[name].load()), name
    # Reserve an available loopback port; the controller still enforces its own bind policy.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    directory = Path.cwd()
    environment = _environment()
    # The temporary profile has no source endpoint, credentials or existing local artifacts.
    config = directory / "smoke.toml"
    profile = "[paths]\ndata_root = " + json.dumps(str(directory / "data")) + "\n"
    profile += f'[control]\nhost = "127.0.0.1"\nport = {port}\n'
    config.write_text(profile, encoding="utf-8")
    # Invoke the installed console wrapper, independently of module import checks.
    cli = str(Path(sys.executable).parent / "backtest")
    _run([cli, "--help"], directory, environment)
    command = [cli, "serve", "--config", str(config)]
    # Write diagnostics to a file so a chatty server cannot deadlock a pipe.
    with (directory / "server.log").open("wb") as log:
        process = subprocess.Popen(
            command, cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            # Verify the serving runtime, not only archive membership or module imports.
            health = _wait_for_health(process, port)
            assert health["status"] == "ok"
            assert health["version"] == distribution.version
            _verify_http(port, package_root)
        # Cleanup remains mandatory even if a served asset or security check fails.
        finally:
            _stop(process)
    print("Installed wheel passed: isolated imports, CLI, loopback API, UI assets and shutdown.")


def main() -> None:
    """Select orchestration or the isolated installed-package verification process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=Path)
    parser.add_argument("--installed", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    # Only the orchestrator receives a wheel path; the child uses its installed metadata.
    if arguments.installed:
        _verify_installed()
    elif arguments.wheel is not None and arguments.wheel.is_file():
        _install_and_verify(arguments.wheel.resolve())
    # Missing artifacts are invocation errors, never a reason to fall back to editable code.
    else:
        parser.error("provide exactly one existing wheel built from this repository")


if __name__ == "__main__":
    main()
