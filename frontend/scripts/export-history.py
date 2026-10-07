"""Export selected verified historical results, without source access or execution.

The selection is a local, explicit allowlist. Only API presentation DTOs reach the
public directory; canonical artifacts and executable manifests remain local.
"""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi.testclient import TestClient

from backtest.bootstrap.config import PathSettings, Settings
from backtest.bootstrap.container import build_runtime_container
from backtest.domain.identifiers import ArtifactId, ContentDigest
from backtest.interfaces.api import create_app

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "backtest.static-history/v1"
MAX_RESPONSE = 2 * 1024**2
MAX_TOTAL = 256 * 1024**2
MAX_RECORDS = 8192
IDENTITY = re.compile(r"[0-9a-f]{64}")
PRIVATE = re.compile(
    r"/Users/|/private/|/tmp/|\.env\b|secret_ref|password|127\.0\.0\.1|localhost", re.I
)
WORKSPACE_ROUTES = ("/api/v1/run-contracts", "/api/v1/ml/reference-contract")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_selection(path):
    value = json.loads(path.read_text())
    if set(value) != {"source", "runs"}:
        raise ValueError("Selection requires only source and runs")
    source = value["source"]
    if (
        set(source)
        != {
            "name",
            "start_utc",
            "end_utc",
            "duration_seconds",
            "from_block_ordinal",
            "to_block_ordinal",
            "snapshot_ids",
        }
        or source["name"] != "OnchainDivers"
    ):
        raise ValueError("Invalid historical source description")
    start, end = (datetime.fromisoformat(source[key]) for key in ("start_utc", "end_utc"))
    if (
        not source["start_utc"].endswith("Z")
        or not source["end_utc"].endswith("Z")
        or (end - start).total_seconds() != 7200
        or source["duration_seconds"] != 7200
    ):
        raise ValueError("The historical decision window must be exactly two UTC hours")
    for key in ("from_block_ordinal", "to_block_ordinal"):
        if not isinstance(source[key], str) or not re.fullmatch(r"[1-9][0-9]{0,19}", source[key]):
            raise ValueError("Block coordinates must be canonical decimal strings")
    if int(source["from_block_ordinal"]) >= int(source["to_block_ordinal"]):
        raise ValueError("Invalid historical block interval")
    if not 1 <= len(source["snapshot_ids"]) <= 16:
        raise ValueError("Invalid snapshot count")
    if not all(IDENTITY.fullmatch(item) for item in source["snapshot_ids"]):
        raise ValueError("Invalid snapshot ID")
    if not 1 <= len(value["runs"]) <= 16:
        raise ValueError("Select between one and sixteen completed runs")
    for run in value["runs"]:
        if set(run) != {"id", "title"} or not IDENTITY.fullmatch(run["id"]):
            raise ValueError("Invalid selected run")
        if not isinstance(run["title"], str) or not 1 <= len(run["title"]) <= 100:
            raise ValueError("Invalid run title")
    if len({run["id"] for run in value["runs"]}) != len(value["runs"]):
        raise ValueError("Duplicate selected run")
    if len(set(source["snapshot_ids"])) != len(source["snapshot_ids"]):
        raise ValueError("Duplicate selected snapshot")
    if PRIVATE.search(canonical(value).decode()):
        raise ValueError("Private metadata cannot enter the selection")
    return value


def read_existing(output, selection, expected_digest):
    """Reuse only a pinned, complete corpus for the exact verified selection."""
    if not IDENTITY.fullmatch(expected_digest or ""):
        raise ValueError("Workspace refresh requires the existing manifest SHA-256")
    if output.is_symlink() or (output / "responses").is_symlink():
        raise ValueError("Historical corpus paths cannot be symbolic links")
    raw = (output / "manifest.json").read_bytes()
    if len(raw) > 4 * 1024**2 or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("Existing historical manifest SHA-256 does not match")
    if (output / "manifest.sha256").read_text().strip() != expected_digest:
        raise ValueError("Existing historical manifest sidecar does not match")
    value = json.loads(raw)
    if (
        set(value)
        != {
            "schema",
            "recipe",
            "synthetic",
            "version",
            "source",
            "runs",
            "response_bytes",
            "responses",
        }
        or PRIVATE.search(raw.decode())
        or value.get("schema") != SCHEMA
        or value.get("recipe") != "indexer-two-hour-results/v1"
        or value.get("synthetic") is not False
        or value.get("version") != "0.2.0"
        or value.get("source") != selection["source"]
        or [{"id": run["id"], "title": run["title"]} for run in value["runs"]] != selection["runs"]
    ):
        raise ValueError("Existing historical corpus does not match the selection")
    records = value["responses"]
    if not isinstance(records, dict) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError("Invalid historical response count")
    total, files = 0, set()
    for route, record in records.items():
        parsed = urlsplit(route)
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        if (
            not route.startswith("/api/v1/")
            or re.search(r"[#\\\s]", route)
            or ".." in route
            or route != parsed.path + ("?" + query if query else "")
            or set(record)
            not in ({"file", "bytes", "sha256"}, {"file", "bytes", "sha256", "status"})
            or record.get("status", 200) not in (200, 400, 404, 409, 422, 503)
            or not IDENTITY.fullmatch(record["sha256"])
            or record["file"] != f"responses/{record['sha256']}.json"
            or not 0 < record["bytes"] <= MAX_RESPONSE
        ):
            raise ValueError("Invalid historical response record")
        path = output / record["file"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record["bytes"]:
            raise ValueError("Historical response size or path does not match")
        contents = path.read_bytes()
        if hashlib.sha256(contents).hexdigest() != record["sha256"]:
            raise ValueError("Historical response SHA-256 does not match")
        if PRIVATE.search(contents.decode()):
            raise ValueError("Historical response contains local metadata")
        total += len(contents)
        files.add(record["file"])
    if total != value["response_bytes"] or total > MAX_TOTAL:
        raise ValueError("Historical response bytes do not reconcile")
    if {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()} != files | {
        "manifest.json",
        "manifest.sha256",
    }:
        raise ValueError("Historical corpus contains unexpected files")
    return value


class Exporter:
    def __init__(self, client, output, existing=None):
        self.client, self.output = client, output
        self.records = {} if existing is None else dict(existing["responses"])
        self.total = 0 if existing is None else existing["response_bytes"]
        self.chart_errors = sum(
            record.get("status", 200) != 200 for record in self.records.values()
        )
        (output / "responses").mkdir(exist_ok=True)

    def get(self, path, *, chart=False):
        parsed = urlsplit(path)
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        key = parsed.path + ("?" + query if query else "")
        response = self.client.get(path)
        allowed_error = chart and response.status_code in (400, 404, 409, 422, 503)
        if response.status_code != 200 and not allowed_error:
            raise RuntimeError(
                f"Historical export rejected ({response.status_code}): {parsed.path}"
            )
        value = response.json()
        if allowed_error:
            if not isinstance(value, dict) or not {"code", "message"} <= value.keys():
                raise ValueError("Chart failure did not use the public error contract")
            if (response.status_code, value["code"]) not in {
                (404, "MARKET_CHART_UNAVAILABLE"),
                (422, "MARKET_CHART_LIMIT_EXCEEDED"),
            }:
                raise ValueError("Transient or invalid chart input cannot be published")
            self.chart_errors += 1
        raw = canonical(value)
        if len(raw) > MAX_RESPONSE or PRIVATE.search(raw.decode()):
            raise ValueError("Response exceeds export bounds or contains local metadata")
        digest = hashlib.sha256(raw).hexdigest()
        record = {"file": f"responses/{digest}.json", "bytes": len(raw), "sha256": digest}
        if response.status_code != 200:
            record["status"] = response.status_code
        if key in self.records:
            if self.records[key] != record:
                raise ValueError("An immutable response changed during export")
        else:
            self.total += len(raw)
            if len(self.records) >= MAX_RECORDS or self.total > MAX_TOTAL:
                raise ValueError("Historical corpus limit exceeded")
            (self.output / record["file"]).write_bytes(raw)
            self.records[key] = record
        return value

    def run(self, run):
        prefix = f"/api/v1/run-artifacts/{run['id']}"
        summary = self.get(prefix + "/strategy-summary")
        if summary["run_artifact_id"] != run["id"]:
            raise ValueError("Run identity mismatch")
        dashboard = self.get(prefix + "/strategy-dashboard?limit=25")
        analytics = self.get(prefix + "/analytics")
        if dashboard["summary"] != summary:
            raise ValueError("Dashboard summary mismatch")
        cursor, seen, count = None, set(), 0
        while True:
            query = {"limit": "25"}
            if cursor:
                query.update(
                    after_target_boundary_ordinal=cursor["target_boundary_ordinal"],
                    after_roundtrip_id=cursor["roundtrip_id"],
                )
            page = self.get(prefix + "/entries?" + urlencode(query))
            if cursor is None and page != dashboard["entries"]:
                raise ValueError("Dashboard first page mismatch")
            for entry in page["items"]:
                if entry["entry_id"] in seen:
                    raise ValueError("Repeated entry in result pagination")
                seen.add(entry["entry_id"])
                count += 1
                if count % 250 == 0:
                    print(f"Exporting {run['title']}: {count} entries", flush=True)
                if entry["chart_availability"] == "AVAILABLE":
                    self.get(
                        prefix
                        + f"/entries/{entry['entry_id']}/chart?"
                        + urlencode({"boundary_ordinal": entry["boundary_ordinal"]}),
                        chart=True,
                    )
            cursor = page["next_cursor"]
            if not cursor:
                break
            if not page["items"] or count > 100_000:
                raise ValueError("Result pagination did not terminate within bounds")
        if count != int(analytics["entry_count"]):
            raise ValueError("Exported entries do not reconcile with whole-run analytics")
        print(f"Exported {run['title']}: {count} entries", flush=True)
        return {**run, "mode": summary["execution_mode"], "summary": summary}

    def workspace(self, selection):
        """Only public product contracts and the explicitly selected run inventory."""
        for route in WORKSPACE_ROUTES:
            self.get(route)
        expected = {run["id"] for run in selection["runs"]}
        cursor, seen, cursors = None, set(), set()
        while True:
            query = {"limit": "10"}
            if cursor:
                query["cursor"] = cursor
            page = self.get("/api/v1/runs?" + urlencode(query))
            for run in page["items"]:
                identity = run["run_artifact_id"]
                if identity not in expected or identity in seen:
                    raise ValueError("Run inventory contains an unselected or repeated run")
                seen.add(identity)
            cursor = page["next_cursor"]
            if cursor is None:
                break
            if not page["items"] or cursor in cursors or len(cursors) >= 2:
                raise ValueError("Run inventory pagination exceeds the selected bounds")
            cursors.add(cursor)
        if seen != expected:
            raise ValueError("Run inventory is missing selected runs")


def generate(data_root, selection, output, existing=None):
    # Source defaults are inert. Neither a source config nor a secret is loaded.
    container = build_runtime_container(
        Settings(paths=PathSettings(data_root)), profile="static-history"
    )
    indexed, used_snapshots = set(), set()

    def index(identity):
        if identity in indexed:
            return
        if len(indexed) >= 512:
            raise ValueError("Selected lineage exceeds 512 artifacts")
        with container.artifacts.open_committed(ArtifactId(identity)) as handle:
            descriptor = handle.descriptor
            with handle.open_binary("manifest.json") as stream:
                manifest = json.load(stream)
        # Only verified descriptors enter the rebuildable local query index.
        indexed.add(identity)
        for dependency in descriptor.input_artifact_ids:
            index(dependency.hex)
        container.catalog.index_committed(descriptor)
        return manifest

    for run in selection["runs"]:
        manifest = index(run["id"])
        snapshot = manifest["resolved_run_spec"]["snapshot_id"]
        used_snapshots.add(snapshot)
        if snapshot not in selection["source"]["snapshot_ids"]:
            raise ValueError("Selected run uses an undeclared snapshot")
    if used_snapshots != set(selection["source"]["snapshot_ids"]):
        raise ValueError("Source description contains an unused snapshot")
    for snapshot in used_snapshots:
        with (
            container.artifacts.open_committed(ArtifactId(snapshot)) as handle,
            handle.open_binary("manifest.json") as stream,
        ):
            manifest = json.load(stream)
        interval = manifest["requested_decision_range"]
        if manifest["validation_status"] != "PASS" or any(
            str(interval[key]) != selection["source"][key]
            for key in ("from_block_ordinal", "to_block_ordinal")
        ):
            raise ValueError("Verified snapshot does not match the selected decision interval")
    app = create_app(container.control, control_plane_id=ContentDigest("d" * 64))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        export = Exporter(client, output, existing)
        if existing is None:
            runs = [export.run(run) for run in selection["runs"]]
        else:
            runs = existing["runs"]
            for run in runs:
                summary = export.get(f"/api/v1/run-artifacts/{run['id']}/strategy-summary")
                if summary != run["summary"] or summary["execution_mode"] != run["mode"]:
                    raise ValueError("Verified run no longer matches its published summary")
        export.workspace(selection)
        pending, done = {run["id"] for run in runs}, set()
        while pending:
            identity = pending.pop()
            lineage = export.get(f"/api/v1/lineage/{identity}")
            done.add(identity)
            pending.update(
                item["artifact_id"]
                for item in lineage["artifacts"]
                if item["artifact_id"] not in done
            )
            if len(done | pending) > 512:
                raise ValueError("Published lineage exceeds its bound")
        manifest = {
            "schema": SCHEMA,
            "recipe": "indexer-two-hour-results/v1",
            "synthetic": False,
            "version": "0.2.0",
            "source": selection["source"],
            "runs": runs,
            "response_bytes": export.total,
            "responses": export.records,
        }
        raw = canonical(manifest)
        if len(raw) > 4 * 1024**2:
            raise ValueError("Historical manifest exceeds its size limit")
        (output / "manifest.json").write_bytes(raw)
        (output / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
        print(
            f"Prepared {len(runs)} runs, {len(export.records)} response routes, "
            f"{export.total} bytes, {export.chart_errors} explicit unavailable charts."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument(
        "--refresh-workspace",
        action="store_true",
        help="Add safe workspace metadata while retaining all verified result response bytes",
    )
    parser.add_argument("--manifest-sha256", help="Required existing digest for workspace refresh")
    args = parser.parse_args()
    selection = read_selection(args.selection)
    output = ROOT / "frontend/demo-data"
    existing = None
    if args.refresh_workspace:
        existing = read_existing(output, selection, args.manifest_sha256)
    elif args.manifest_sha256:
        parser.error("--manifest-sha256 is only used with --refresh-workspace")
    with tempfile.TemporaryDirectory(prefix=".history-export-", dir=output.parent) as staging:
        if existing is not None:
            shutil.copytree(output / "responses", Path(staging) / "responses")
        with patch(
            "socket.socket.connect", side_effect=RuntimeError("Historical export is offline")
        ):
            generate(args.data_root.resolve(), selection, Path(staging), existing)
        if output.exists():
            previous = json.loads((output / "manifest.json").read_text())
            if previous["schema"] not in (SCHEMA, "backtest.static-demo/v1"):
                raise ValueError("Refusing to replace an unknown output directory")
            shutil.rmtree(output)
        shutil.copytree(staging, output)


if __name__ == "__main__":
    main()
