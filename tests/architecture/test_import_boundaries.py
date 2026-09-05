# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "backtest"
# Bind forbidden from domain once as an explicit module-level contract.
FORBIDDEN_FROM_DOMAIN = {
    "adapters",
    "application",
    "bootstrap",
    "engine",
    # Keep the interfaces component named inside the forbidden from domain contract.
    "interfaces",
    "plugins",
    "runtime",
}
FORBIDDEN_FROM_APPLICATION = {
    # Keep the adapters component named inside the forbidden from application contract.
    "adapters",
    "bootstrap",
    "interfaces",
    "plugins",
    "runtime",
    # Complete the forbidden from application group only after its semantic components are
    # visible.
}


def _imports(path: Path) -> tuple[str, ...]:
    # Execute the imports workflow in explicit, reviewable steps.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        # Process ast.walk(tree) inside the bounded imports loop.
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        # Handle the imports complement of isinstance(node, ast.Import) explicitly.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(node.module)
    return tuple(imports)


def _backtest_layer(module: str) -> str | None:
    # Execute the backtest layer workflow in explicit, reviewable steps.
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "backtest":
        return parts[1]
    return None


def test_domain_and_application_have_no_third_party_imports() -> None:
    # Execute the test domain and application have no third party imports workflow in
    # explicit, reviewable steps.
    violations: list[str] = []
    for layer in ("domain", "application"):
        # Process ('domain', 'application') inside the bounded test domain and application
        # have no third party imports loop.
        for path in (SOURCE_ROOT / layer).rglob("*.py"):
            # Process (SOURCE_ROOT / layer).rglob('*.py') inside the bounded test domain
            # and application have no third party imports loop.
            for module in _imports(path):
                # Process _imports(path) inside the bounded test domain and application
                # have no third party imports loop.
                top_level = module.split(".")[0]
                if top_level != "backtest" and top_level not in sys.stdlib_module_names:
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


def test_dependency_arrows_point_toward_core() -> None:
    # Execute the test dependency arrows point toward core workflow in explicit,
    # reviewable steps.
    violations: list[str] = []
    for path in (SOURCE_ROOT / "domain").rglob("*.py"):
        # Process (SOURCE_ROOT / 'domain').rglob('*.py') inside the bounded test
        # dependency arrows point toward core loop.
        for module in _imports(path):
            # Process _imports(path) inside the bounded test dependency arrows point
            # toward core loop.
            imported_layer = _backtest_layer(module)
            if imported_layer in FORBIDDEN_FROM_DOMAIN:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")

    for path in (SOURCE_ROOT / "application").rglob("*.py"):
        # Process rglob, source root and application inside the bounded test dependency
        # arrows point toward core loop.
        for module in _imports(path):
            # Process _imports(path) inside the bounded test dependency arrows point
            # toward core loop.
            imported_layer = _backtest_layer(module)
            if imported_layer in FORBIDDEN_FROM_APPLICATION:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")

    assert not violations, "\n".join(violations)
