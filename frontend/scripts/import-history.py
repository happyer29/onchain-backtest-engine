"""Import a digest-pinned presentation archive without extracting arbitrary tar paths."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE = 128 * 1024**2
MAX_TAR_STREAM = 280 * 1024**2
MAX_CONTENT = 260 * 1024**2
MAX_FILES = 8194
HISTORY_SCHEMA = "backtest.static-history/v1"


class BoundedReader:
    """Bound decompression too, including tar headers and extension records."""

    def __init__(self, source):
        self.source = source
        self.consumed = 0

    def read(self, size):
        raw = self.source.read(min(size, MAX_TAR_STREAM - self.consumed + 1))
        self.consumed += len(raw)
        if self.consumed > MAX_TAR_STREAM:
            raise ValueError("Historical archive exceeds decompression limit")
        return raw


def import_archive(archive, expected, output):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Expected lowercase SHA-256 of the complete archive")
    output.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("rb") as source:
        if archive.stat().st_size > MAX_ARCHIVE:
            raise ValueError("Historical archive exceeds compressed size limit")
        if hashlib.file_digest(source, "sha256").hexdigest() != expected:
            raise ValueError("Historical archive SHA-256 does not match")
        source.seek(0)
        with tempfile.TemporaryDirectory(prefix=".demo-export-", dir=output.parent) as temporary:
            staging = Path(temporary)
            names, total = set(), 0
            with (
                gzip.GzipFile(fileobj=source) as expanded,
                tarfile.open(fileobj=BoundedReader(expanded), mode="r|") as entries,
            ):
                for member in entries:
                    name = member.name.removeprefix("./")
                    if member.isdir() and name in ("", ".", "responses"):
                        continue
                    if not member.isfile() or name in names:
                        raise ValueError("Historical archive has a link, special or duplicate file")
                    if name == "manifest.json":
                        cap = 4 * 1024**2
                    elif name == "manifest.sha256":
                        cap = 65
                    elif re.fullmatch(r"responses/[0-9a-f]{64}\.json", name):
                        cap = 2 * 1024**2
                    else:
                        raise ValueError("Historical archive has an unexpected path")
                    names.add(name)
                    total += member.size
                    if not 0 <= member.size <= cap or total > MAX_CONTENT:
                        raise ValueError("Historical archive exceeds content size limit")
                    if len(names) > MAX_FILES:
                        raise ValueError("Historical archive has too many files")
                    destination = staging / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    contents = entries.extractfile(member)
                    if contents is None:
                        raise ValueError("Historical archive file is unreadable")
                    with contents, destination.open("xb") as target:
                        shutil.copyfileobj(contents, target)
                    if destination.stat().st_size != member.size:
                        raise ValueError("Historical archive file is incomplete")
            if not {"manifest.json", "manifest.sha256"}.issubset(names):
                raise ValueError("Historical archive has no complete manifest")
            raw = (staging / "manifest.json").read_bytes()
            digest = (staging / "manifest.sha256").read_text(encoding="ascii").strip()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Historical manifest SHA-256 does not match")
            manifest = json.loads(raw)
            if manifest.get("schema") != HISTORY_SCHEMA or manifest.get("synthetic") is not False:
                raise ValueError("Archive is not a historical presentation export")
            if output.exists() or output.is_symlink():
                if output.is_symlink() or not output.is_dir():
                    raise ValueError("Refusing to replace an unexpected output path")
                previous = json.loads((output / "manifest.json").read_bytes())
                if previous.get("schema") not in (HISTORY_SCHEMA, "backtest.static-demo/v1"):
                    raise ValueError("Refusing to replace a non-demo directory")
                shutil.rmtree(output)
            staging.rename(output)
    print(f"Imported pinned historical presentation export: {len(names)} files, {total} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    import_archive(args.archive, args.sha256, ROOT / "frontend/demo-data")


if __name__ == "__main__":
    main()
