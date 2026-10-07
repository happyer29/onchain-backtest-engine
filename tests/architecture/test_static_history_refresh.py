"""Workspace preview metadata must not silently change a published result corpus."""

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "frontend/scripts/export-history.py"
SPEC = importlib.util.spec_from_file_location("history_export", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
history_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history_export)


def corpus(tmp_path):
    selection = {
        "source": {"snapshot_ids": ["b" * 64]},
        "runs": [{"id": "a" * 64, "title": "Strict replay"}],
    }
    output = tmp_path / "corpus"
    (output / "responses").mkdir(parents=True)
    raw = b'{"unchanged":"historical results"}'
    digest = hashlib.sha256(raw).hexdigest()
    filename = f"responses/{digest}.json"
    (output / filename).write_bytes(raw)
    manifest = {
        "schema": history_export.SCHEMA,
        "recipe": "indexer-two-hour-results/v1",
        "synthetic": False,
        "version": "0.2.0",
        "source": selection["source"],
        "runs": [{**selection["runs"][0], "mode": "EXOGENOUS_REPLAY", "summary": {}}],
        "response_bytes": len(raw),
        "responses": {
            "/api/v1/run-artifacts/" + "a" * 64 + "/analytics": {
                "file": filename,
                "sha256": digest,
                "bytes": len(raw),
            }
        },
    }
    document = history_export.canonical(manifest)
    expected = hashlib.sha256(document).hexdigest()
    (output / "manifest.json").write_bytes(document)
    (output / "manifest.sha256").write_text(expected + "\n")
    return selection, output, expected, manifest


class Client:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, route):
        self.requested.append(route)
        return SimpleNamespace(status_code=200, json=lambda: self.pages[route])


def test_refresh_checks_every_old_response_and_preserves_result_bytes(tmp_path):
    selection, output, expected, original = corpus(tmp_path)
    before = {path: path.read_bytes() for path in (output / "responses").iterdir()}
    verified = history_export.read_existing(output, selection, expected)
    client = Client(
        {
            "/api/v1/run-contracts": {"items": []},
            "/api/v1/ml/reference-contract": {"compiler_version": "reference-test"},
            "/api/v1/runs?limit=10": {
                "items": [{"run_artifact_id": "a" * 64}],
                "next_cursor": None,
            },
        }
    )
    export = history_export.Exporter(client, output, verified)
    export.workspace(selection)
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert all(export.records[key] == record for key, record in original["responses"].items())
    assert client.requested == [*history_export.WORKSPACE_ROUTES, "/api/v1/runs?limit=10"]
    assert len(export.records) == len(original["responses"]) + 3


@pytest.mark.parametrize(
    "corruption", ["pin", "sidecar", "response", "extra", "selection", "source"]
)
def test_refresh_rejects_changed_corpus_or_selection(tmp_path, corruption):
    selection, output, expected, manifest = corpus(tmp_path)
    if corruption == "pin":
        expected = "0" * 64
    elif corruption == "sidecar":
        (output / "manifest.sha256").write_text("0" * 64)
    elif corruption == "response":
        record = next(iter(manifest["responses"].values()))
        (output / record["file"]).write_bytes(b"x" * record["bytes"])
    elif corruption == "extra":
        (output / "extra.json").write_text("{}")
    elif corruption == "selection":
        selection["runs"][0]["title"] = "Changed selection"
    elif corruption == "source":
        selection["source"]["snapshot_ids"] = ["c" * 64]
    with pytest.raises(ValueError):
        history_export.read_existing(output, selection, expected)


@pytest.mark.parametrize("ids", [[], ["b" * 64], ["a" * 64, "a" * 64]])
def test_workspace_inventory_must_equal_explicit_run_allowlist(tmp_path, ids):
    selection, output, _, manifest = corpus(tmp_path)
    client = Client(
        {
            "/api/v1/run-contracts": {"items": []},
            "/api/v1/ml/reference-contract": {},
            "/api/v1/runs?limit=10": {
                "items": [{"run_artifact_id": identity} for identity in ids],
                "next_cursor": None,
            },
        }
    )
    export = history_export.Exporter(client, output, manifest)
    with pytest.raises(ValueError, match=r"[Rr]un inventory"):
        export.workspace(selection)


def test_workspace_never_overwrites_an_existing_immutable_route(tmp_path):
    selection, output, _, manifest = corpus(tmp_path)
    record = next(iter(manifest["responses"].values()))
    manifest["responses"]["/api/v1/run-contracts"] = record
    client = Client({"/api/v1/run-contracts": {"items": []}})
    export = history_export.Exporter(client, output, manifest)
    with pytest.raises(ValueError, match="immutable response changed"):
        export.workspace(selection)
