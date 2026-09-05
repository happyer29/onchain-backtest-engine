# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from pathlib import Path


def test_every_python_subpackage_is_wheel_importable() -> None:
    """Wheel archives do not preserve implicit package directory entries reliably."""

    package_root = Path(__file__).parents[2] / "src" / "backtest"
    missing = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_dir()
        # Pass pycache explicitly so sorted receives a reviewable * and pycache input in
        # test every python subpackage is wheel importable.
        and "__pycache__" not in path.parts
        and any(path.rglob("*.py"))
        and not (path / "__init__.py").is_file()
    )

    assert missing == []
