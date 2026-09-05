# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backtest.application.build_tool_roles import (
    # Include canonical projector role so the build tool roles dependency remains
    # explicit.
    CANONICAL_PROJECTOR_ROLE,
    CANONICAL_WRITER_ROLE,
    DELIVERY_COMPILER_ROLE,
    DELIVERY_WRITER_ROLE,
    ML_COMPILER_ROLE,
    # Include ml embedded inference role so the build tool roles dependency remains
    # explicit.
    ML_EMBEDDED_INFERENCE_ROLE,
    ML_FEATURE_BUILDER_ROLE,
    ML_FROZEN_INFERENCE_ROLE,
    ML_LABEL_BUILDER_ROLE,
    ML_TRAINER_ROLE,
    # Include ml universe builder role so the build tool roles dependency remains
    # explicit.
    ML_UNIVERSE_BUILDER_ROLE,
    ML_WRITER_ROLE,
    REPLAY_COMPILER_ROLE,
    REPLAY_WRITER_ROLE,
)

# Import code bundles at the visible module dependency boundary.
from backtest.application.code_bundles import CodeBundleIntegrityError
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.reference_bundles import ReferenceBundleRegistry


@pytest.mark.parametrize(
    ("role", "relevant_source"),
    # Open the role and relevant source payload explicitly for parametrize within test
    # relevant source mutation changes only a physical tool cut and pin fails closed.
    (
        (CANONICAL_PROJECTOR_ROLE, "bootstrap/pumpfun_live_source.py"),
        (CANONICAL_WRITER_ROLE, "adapters/columnar/arrow/canonical.py"),
        (REPLAY_COMPILER_ROLE, "adapters/columnar/numpy/compiler.py"),
        (REPLAY_WRITER_ROLE, "adapters/columnar/numpy/compiler.py"),
        # Open the role and relevant source payload explicitly for parametrize within test
        # relevant source mutation changes only a physical tool cut and pin fails closed.
        (DELIVERY_COMPILER_ROLE, "adapters/delivery_schedule/numpy/compiler.py"),
        (DELIVERY_WRITER_ROLE, "adapters/delivery_schedule/numpy/compiler.py"),
        (ML_FEATURE_BUILDER_ROLE, "adapters/ml/numpy/builders.py"),
        (ML_UNIVERSE_BUILDER_ROLE, "adapters/ml/numpy/builders.py"),
        (ML_LABEL_BUILDER_ROLE, "adapters/ml/numpy/builders.py"),
        # Open the role and relevant source payload explicitly for parametrize within test
        # relevant source mutation changes only a physical tool cut and pin fails closed.
        (ML_TRAINER_ROLE, "adapters/ml/numpy/pipelines.py"),
        (ML_FROZEN_INFERENCE_ROLE, "adapters/ml/numpy/pipelines.py"),
        (ML_EMBEDDED_INFERENCE_ROLE, "adapters/ml/numpy/embedded.py"),
        (ML_COMPILER_ROLE, "adapters/ml/numpy/publisher.py"),
        (ML_WRITER_ROLE, "adapters/ml/numpy/publisher.py"),
        # Complete parametrize only after its role and relevant source inputs are visible in
        # test relevant source mutation changes only a physical tool cut and pin fails closed.
    ),
)
def test_relevant_source_mutation_changes_only_a_physical_tool_cut_and_pin_fails_closed(
    tmp_path: Path,
    role: str,
    # Keep the relevant source input explicit in the test relevant source mutation changes
    # only a physical tool cut and pin fails closed contract.
    relevant_source: str,
) -> None:
    # Execute the test relevant source mutation changes only a physical tool cut and pin
    # fails closed workflow in explicit, reviewable steps.
    installed = BuildToolBundleRegistry()
    copied_root = _copy_declared_sources(installed, tmp_path / "backtest")
    registry = BuildToolBundleRegistry(copied_root)
    pinned = registry.pin()
    original = registry.snapshot().manifest_for(role).bundle_id

    # Assemble unrelated once so the test relevant source mutation changes only a physical
    # tool cut and pin fails closed workflow shares one value.
    unrelated = copied_root / "unrelated.py"
    unrelated.write_text("VALUE = 1\n", encoding="utf-8")
    assert registry.snapshot().manifest_for(role).bundle_id == original

    changed = copied_root.joinpath(*relevant_source.split("/"))
    changed.write_bytes(changed.read_bytes() + b"\n# exact build-tool mutation\n")

    # Verify the bundle id, original and manifest for relationship before this scenario is
    # accepted.
    assert registry.snapshot().manifest_for(role).bundle_id != original
    with pytest.raises(CodeBundleIntegrityError, match="installed exact source bytes changed"):
        pinned.require_current(role)


def test_physical_writer_identity_does_not_pollute_semantic_runtime_closure(
    tmp_path: Path,
    # Close the test physical writer identity does not pollute semantic runtime closure
    # signature after its explicit inputs.
) -> None:
    # Execute the test physical writer identity does not pollute semantic runtime closure
    # workflow in explicit, reviewable steps.
    physical = BuildToolBundleRegistry()
    semantic = ReferenceBundleRegistry()
    copied_root = _copy_union_sources(physical, semantic, tmp_path / "backtest")
    physical_registry = BuildToolBundleRegistry(copied_root)
    semantic_registry = ReferenceBundleRegistry(copied_root)
    # Assemble before physical once so the test physical writer identity does not pollute
    # semantic runtime closure workflow shares one value.
    before_physical = physical_registry.snapshot().manifest_for(CANONICAL_WRITER_ROLE).bundle_id
    before_semantic = tuple(item.bundle_id for item in semantic_registry.snapshot().manifests)

    changed = copied_root / "adapters" / "columnar" / "arrow" / "canonical.py"
    changed.write_bytes(changed.read_bytes() + b"\n# physical writer only\n")

    assert (
        # Keep the physical registry expectation tied to bundle id, before physical and
        # manifest for in this scenario.
        physical_registry.snapshot().manifest_for(CANONICAL_WRITER_ROLE).bundle_id
        != before_physical
    )
    assert (
        tuple(item.bundle_id for item in semantic_registry.snapshot().manifests) == before_semantic
        # Verify the before semantic, bundle id and item relationship before this scenario is
        # accepted.
    )


def _copy_declared_sources(registry: BuildToolBundleRegistry, target: Path) -> Path:
    # Execute the copy declared sources workflow in explicit, reviewable steps.
    paths = {path for declaration in registry.declarations for path in declaration.source_paths}
    _copy_paths(registry.package_root, target, paths)
    return target


def _copy_union_sources(
    physical: BuildToolBundleRegistry,
    # Keep the semantic input explicit in the copy union sources contract.
    semantic: ReferenceBundleRegistry,
    target: Path,
) -> Path:
    # Execute the copy union sources workflow in explicit, reviewable steps.
    paths = {
        path
        for declaration in (*physical.declarations, *semantic.declarations)
        for path in declaration.source_paths
    }
    # Invoke _copy_paths for package root and physical as a visible copy union sources
    # step.
    _copy_paths(physical.package_root, target, paths)
    return target


def _copy_paths(source_root: Path, target: Path, paths: set[str]) -> None:
    # Execute the copy paths workflow in explicit, reviewable steps.
    for relative_path in sorted(paths):
        # Process sorted(paths) inside the bounded copy paths loop.
        source = source_root.joinpath(*relative_path.split("/"))
        destination = target.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
