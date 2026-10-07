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


class Exporter:
    def __init__(self, client, output):
        self.client, self.output = client, output
        self.records, self.total, self.chart_errors = {}, 0, 0
        (output / "responses").mkdir()

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


def generate(data_root, selection, output):
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
        export = Exporter(client, output)
        runs = [export.run(run) for run in selection["runs"]]
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
    args = parser.parse_args()
    selection = read_selection(args.selection)
    output = ROOT / "frontend/demo-data"
    with tempfile.TemporaryDirectory(prefix=".history-export-", dir=output.parent) as staging:
        with patch(
            "socket.socket.connect", side_effect=RuntimeError("Historical export is offline")
        ):
            generate(args.data_root.resolve(), selection, Path(staging))
        if output.exists():
            previous = json.loads((output / "manifest.json").read_text())
            if previous["schema"] not in (SCHEMA, "backtest.static-demo/v1"):
                raise ValueError("Refusing to replace an unknown output directory")
            shutil.rmtree(output)
        shutil.copytree(staging, output)


if __name__ == "__main__":
    main()
