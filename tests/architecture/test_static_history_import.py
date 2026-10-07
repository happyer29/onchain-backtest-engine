import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "frontend/scripts/import-history.py"
SPEC = importlib.util.spec_from_file_location("history_import", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
history_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history_import)


def archive(tmp_path, extra=(), *, schema="backtest.static-history/v1", corrupt_manifest=False):
    manifest = json.dumps({"schema": schema, "synthetic": False}).encode()
    digest = hashlib.sha256(manifest).hexdigest().encode()
    files = [
        ("manifest.json", manifest),
        ("manifest.sha256", b"0" * 64 if corrupt_manifest else digest),
    ]
    path = tmp_path / "history.tar.gz"
    with tarfile.open(path, "w:gz") as bundle:
        for name, data in [*files, *extra]:
            entry = tarfile.TarInfo(name)
            if data is None:
                entry.type = tarfile.SYMTYPE
                entry.linkname = "../outside.json"
                bundle.addfile(entry)
            else:
                entry.size = len(data)
                bundle.addfile(entry, io.BytesIO(data))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_replaces_only_a_recognized_demo_after_verification(tmp_path):
    path, digest = archive(tmp_path, [(f"responses/{'a' * 64}.json", b"{}")])
    output = tmp_path / "demo-data"
    output.mkdir()
    (output / "manifest.json").write_text('{"schema":"backtest.static-demo/v1"}')
    (output / "old.json").write_text("old")
    history_import.import_archive(path, digest, output)
    assert not (output / "old.json").exists()
    assert (output / f"responses/{'a' * 64}.json").read_bytes() == b"{}"
    assert not list(tmp_path.glob(".demo-export-*"))


@pytest.mark.parametrize(
    "extra",
    [
        [("../outside.json", b"{}")],
        [("/tmp/outside.json", b"{}")],
        [("responses/../../outside.json", b"{}")],
        [("manifest.json", b"{}")],
        [(f"responses/{'a' * 64}.json", None)],
        [("secret.env", b"secret")],
        [(f"responses/{'a' * 64}.json", b"x" * (2 * 1024**2 + 1))],
    ],
)
def test_invalid_archive_cannot_change_existing_output(tmp_path, extra):
    path, digest = archive(tmp_path, extra)
    output = tmp_path / "demo-data"
    output.mkdir()
    marker = output / "manifest.json"
    marker.write_text('{"schema":"backtest.static-demo/v1"}')
    before = marker.read_bytes()
    with pytest.raises(ValueError):
        history_import.import_archive(path, digest, output)
    assert marker.read_bytes() == before
    assert list(output.iterdir()) == [marker]
    assert not (tmp_path / "outside.json").exists()
    assert not list(tmp_path.glob(".demo-export-*"))


@pytest.mark.parametrize(
    "kind",
    [
        "archive_digest",
        "manifest_digest",
        "schema",
        "decompression",
        "compressed",
        "content",
        "files",
    ],
)
def test_integrity_profile_and_decompression_are_checked(tmp_path, monkeypatch, kind):
    path, digest = archive(
        tmp_path,
        schema="other" if kind == "schema" else "backtest.static-history/v1",
        corrupt_manifest=kind == "manifest_digest",
    )
    if kind == "archive_digest":
        digest = "0" * 64
    if kind == "decompression":
        monkeypatch.setattr(history_import, "MAX_TAR_STREAM", 1024)
    if kind == "compressed":
        monkeypatch.setattr(history_import, "MAX_ARCHIVE", 1)
    if kind == "content":
        monkeypatch.setattr(history_import, "MAX_CONTENT", 1)
    if kind == "files":
        monkeypatch.setattr(history_import, "MAX_FILES", 1)
    output = tmp_path / "demo-data"
    with pytest.raises(ValueError):
        history_import.import_archive(path, digest, output)
    assert not output.exists()


def test_import_cannot_replace_an_unrelated_directory(tmp_path):
    path, digest = archive(tmp_path)
    output = tmp_path / "demo-data"
    output.mkdir()
    (output / "manifest.json").write_text('{"schema":"unrelated"}')
    with pytest.raises(ValueError, match="non-demo directory"):
        history_import.import_archive(path, digest, output)
    assert json.loads((output / "manifest.json").read_bytes())["schema"] == "unrelated"
