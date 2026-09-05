"""Secret-free immutable fingerprint of the concrete local execution runtime."""

from __future__ import annotations

import hashlib
import os
import platform
import stat

# Import sys at the visible module dependency boundary.
import sys
import sysconfig
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from typing import Final

import numpy as np

from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import RuntimeLockId

# Bind locked distributions once as an explicit module-level contract.
_LOCKED_DISTRIBUTIONS = (
    "clickhouse-connect",
    "duckdb",
    "fastapi",
    "on-chain-backtest-engine",
    # Keep the numpy component named inside the locked distributions contract.
    "numpy",
    "pyarrow",
    "pydantic",
    "typer",
    "uvicorn",
    # Complete the locked distributions group only after its semantic components are visible.
)
_DETERMINISM_ENVIRONMENT = (
    "MKL_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    # Keep the pythonhashseed component named inside the determinism environment contract.
    "PYTHONHASHSEED",
)
_APPLICATION_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_HASH_CHUNK_BYTES: Final = 1024 * 1024


# Keep the runtime manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    document: dict[str, object]
    runtime_lock_id: RuntimeLockId

    def __post_init__(self) -> None:
        # Execute the runtime manifest post init workflow in explicit, reviewable steps.
        if self.document.get("runtime_schema_version") != 2:
            raise ValueError("unsupported runtime lock schema version")
        expected = domain_digest("backtest.runtime-lock.v2", self.document)
        if expected.hex != self.runtime_lock_id.hex:
            raise ValueError("runtime lock ID differs from its manifest")

    # Define runtime manifest bytes as one focused operation with an explicit boundary.
    def bytes(self) -> bytes:
        # Execute the runtime manifest bytes workflow in explicit, reviewable steps.
        return canonical_json_bytes(
            {
                "artifact_schema": "runtime-lock/v2",
                "runtime_lock_id": self.runtime_lock_id.hex,
                "runtime": self.document,
                # Close the artifact schema and runtime lock id payload only after all runtime
                # manifest bytes fields are present.
            }
        )


def build_runtime_manifest(
    *,
    native_threads_per_process: int,
    # Keep the environ input explicit in the build runtime manifest contract.
    environ: Mapping[str, str] | None = None,
) -> RuntimeManifest:
    # Execute the build runtime manifest workflow in explicit, reviewable steps.
    if native_threads_per_process <= 0:
        raise ValueError("native_threads_per_process must be positive")
    effective_environment = os.environ if environ is None else environ
    document: dict[str, object] = {
        "abi": {
            # Keep the cache tag component named inside the document contract.
            "cache_tag": sys.implementation.cache_tag,
            "python_abi_flags": getattr(sys, "abiflags", ""),
            "soabi": sysconfig.get_config_var("SOABI"),
        },
        "cpu": {
            # Register enabled numpy cpu features through _enabled_numpy_cpu_features so
            # the document table remains scannable.
            "enabled_features": _enabled_numpy_cpu_features(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "dependencies": [_distribution_document(name) for name in _LOCKED_DISTRIBUTIONS],
        # Register name through get so the document table remains scannable.
        "environment": {name: effective_environment.get(name) for name in _DETERMINISM_ENVIRONMENT},
        "native_threads_per_process": native_threads_per_process,
        "operating_system": {
            "libc": list(platform.libc_ver()),
            "platform": sys.platform,
            # Register release and platform through release so the document table remains
            # scannable.
            "release": platform.release(),
            "system": platform.system(),
        },
        "python": {
            "executable": _single_file_document(Path(sys.executable)),
            # Register python implementation and platform through python_implementation so
            # the document table remains scannable.
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "application_package": _application_package_document(),
        "runtime_schema_version": 2,
        # Complete the document group only after its semantic components are visible.
    }
    digest = domain_digest("backtest.runtime-lock.v2", document)
    return RuntimeManifest(document, RuntimeLockId(digest.hex))


def _distribution_document(name: str) -> dict[str, object]:
    # Execute the distribution document workflow in explicit, reviewable steps.
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        # Translate the metadata.PackageNotFoundError failure through the distribution
        # document boundary.
        return {
            "installed_files": None,
            "name": name,
            "record_sha256": None,
            "version": None,
            # Return the completed distribution document result without a hidden fallback.
        }
    record = distribution.read_text("RECORD")
    files = tuple(
        sorted(
            (
                # Keep the as posix and item as_posix step visible while building files.
                (item.as_posix(), Path(str(distribution.locate_file(item))))
                for item in (distribution.files or ())
                if _runtime_file(item.as_posix())
            ),
            key=lambda item: item[0],
            # Complete sorted only after its as posix and files inputs are visible in
            # distribution document.
        )
    )
    return {
        "installed_files": _file_tree_document(files),
        "name": name,
        # Include record sha256 in the completed distribution document result.
        "record_sha256": None if record is None else hashlib.sha256(record.encode()).hexdigest(),
        "version": distribution.version,
    }


def _application_package_document() -> dict[str, object]:
    # Execute the application package document workflow in explicit, reviewable steps.
    root = _APPLICATION_PACKAGE_ROOT
    files = tuple(
        (path.relative_to(root).as_posix(), path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and _runtime_file(path.relative_to(root).as_posix())
        # Complete tuple only after its * and as posix inputs are visible in application
        # package document.
    )
    return _file_tree_document(files)


def _runtime_file(relative_name: str) -> bool:
    # Execute the runtime file workflow in explicit, reviewable steps.
    parts = relative_name.replace("\\", "/").split("/")
    return (
        "__pycache__" not in parts
        and not relative_name.endswith((".pyc", ".pyo"))
        and not any(part in {".DS_Store"} for part in parts)
        # Return the completed runtime file result without a hidden fallback.
    )


def _file_tree_document(files: tuple[tuple[str, Path], ...]) -> dict[str, object]:
    # Execute the file tree document workflow in explicit, reviewable steps.
    hasher = hashlib.sha256()
    hasher.update(b"backtest.runtime-file-tree.v1\x00")
    total_bytes = 0
    regular_files = 0
    missing_files = 0
    # Traverse files explicitly so each file tree document iteration remains traceable.
    for relative_name, path in files:
        # Process files inside the bounded file tree document loop.
        encoded_name = relative_name.encode("utf-8")
        hasher.update(len(encoded_name).to_bytes(8, "big"))
        hasher.update(encoded_name)
        try:
            # Perform the protected file tree document operation before explicit failure
            # handling.
            metadata_value = path.lstat()
            if stat.S_ISLNK(metadata_value.st_mode):
                # Handle the file tree document stat.S_ISLNK(metadata_value.st_mode)
                # branch as a distinct logical block.
                link = os.readlink(path).encode("utf-8")
                hasher.update(b"SYMLINK\x00")
                hasher.update(len(link).to_bytes(8, "big"))
                hasher.update(link)
            if not path.is_file():
                # Handle the file tree document not path.is_file() branch as a distinct
                # logical block.
                hasher.update(b"NON_REGULAR\x00")
                missing_files += 1
                continue
            size = path.stat().st_size
            hasher.update(b"FILE\x00")
            # Invoke update for big and to bytes as a visible file tree document step.
            hasher.update(size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                # Keep open, rb and path active only for the bounded file tree document
                # operation.
                while chunk := stream.read(_HASH_CHUNK_BYTES):
                    hasher.update(chunk)
        except OSError:
            # Translate the OSError failure through the file tree document boundary.
            hasher.update(b"MISSING\x00")
            missing_files += 1
            continue
        total_bytes += size
        regular_files += 1
    # Return the completed file tree document result without a hidden fallback.
    return {
        "file_count": regular_files,
        "missing_file_count": missing_files,
        "sha256": hasher.hexdigest(),
        "total_bytes": total_bytes,
        # Return the completed file tree document result without a hidden fallback.
    }


def _single_file_document(path: Path) -> dict[str, object]:
    return _file_tree_document(((path.name, path),))


def _enabled_numpy_cpu_features() -> list[str]:
    # Execute the enabled numpy cpu features workflow in explicit, reviewable steps.
    core = getattr(np, "_core", None)
    multiarray = None if core is None else getattr(core, "_multiarray_umath", None)
    raw = None if multiarray is None else getattr(multiarray, "__cpu_features__", None)
    if not isinstance(raw, dict):
        return []
    # Return the completed enabled numpy cpu features result without a hidden fallback.
    return sorted(
        str(name) for name, enabled in raw.items() if isinstance(name, str) and enabled is True
    )


__all__ = ["RuntimeManifest", "build_runtime_manifest"]
