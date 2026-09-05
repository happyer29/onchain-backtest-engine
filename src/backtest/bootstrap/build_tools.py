"""Exact installed-source identities for physical derived-artifact toolchains.

These roles are intentionally separate from the semantic runtime component
closure: they affect derivation/build keys, never ``logical_run_id``.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final

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
from backtest.application.code_bundles import (
    ExactCodeBundleClosure,
    PinnedCodeBundleIdentity,
    PinnedCodeBundleSet,
)

# Import reference bundles at the visible module dependency boundary.
from backtest.bootstrap.reference_bundles import (
    ReferenceBundleDeclaration,
    ReferenceBundleRegistry,
)
from backtest.domain.identifiers import BundleId


# Define declaration as one focused operation with an explicit boundary.
def _declaration(
    role: str,
    contract: dict[str, object],
    source_paths: tuple[str, ...],
) -> ReferenceBundleDeclaration:
    # Execute the declaration workflow in explicit, reviewable steps.
    return ReferenceBundleDeclaration.create(
        role=role,
        contract=contract,
        source_paths=source_paths,
        package_name=f"local-backtest/physical-tools/{role}",
        # Complete create only after its local-backtest/physical-tools/ and role inputs are
        # visible in declaration.
    )


_CANONICAL_EVENT_CONTRACT: Final = (
    "application/canonical_data.py",
    "application/ports/projectors.py",
    "application/ports/source.py",
    # Keep the domain event hashing py component named inside the canonical event contract
    # contract.
    "domain/event_hashing.py",
    "domain/fidelity.py",
    "domain/market_events.py",
)
_REPLAY_CONTRACT: Final = (
    # Keep the adapters columnar numpy layout component named inside the replay contract
    # contract.
    "adapters/columnar/numpy/layout.py",
    "application/replay_packs.py",
    "domain/event_hashing.py",
    "domain/market_events.py",
    "engine/replay.py",
    # Complete the replay contract group only after its semantic components are visible.
)
_DELIVERY_CONTRACT: Final = (
    "adapters/columnar/numpy/layout.py",
    "adapters/delivery_schedule/numpy/layout.py",
    "application/delivery_schedules.py",
    # Keep the engine reference py component named inside the delivery contract contract.
    "engine/reference.py",
    "engine/rng.py",
    "engine/scheduler.py",
)
_ML_CONTRACT: Final = (
    # Keep the application ml artifacts py component named inside the ml contract
    # contract.
    "application/ml_artifacts.py",
    "application/ml_contracts.py",
)
_ML_READER_CONTRACT: Final = (
    "adapters/ml/numpy/layout.py",
    # Keep the adapters ml numpy reader component named inside the ml reader contract
    # contract.
    "adapters/ml/numpy/reader.py",
    "adapters/ml/numpy/training.py",
)

BUILD_TOOL_DECLARATIONS: Final = (
    _declaration(
        # Pass canonical projector role explicitly so _declaration receives a reviewable
        # configured projection and projector input in module.
        CANONICAL_PROJECTOR_ROLE,
        {
            "configured_projection": "exact-content-digest-v2",
            "projector": "closed-reference-or-pumpfun-v1",
        },
        # Register sorted and canonical event contract through tuple so the build tool
        # declarations table remains scannable.
        tuple(
            sorted(
                (
                    *_CANONICAL_EVENT_CONTRACT,
                    "bootstrap/configured_projector.py",
                    "bootstrap/pumpfun_live_source.py",
                    # Pass bootstrap projector config py explicitly so sorted receives a
                    # reviewable py and canonical event contract input in module.
                    "bootstrap/projector_config.py",
                    "plugins/protocols/pumpfun/live_normalizer.py",
                    "plugins/protocols/pumpfun/model.py",
                    "plugins/protocols/pumpfun/projector.py",
                    "plugins/protocols/pumpfun/sniping.py",
                    "plugins/protocols/reference/projector.py",
                    # Complete sorted only after its py and canonical event contract inputs
                    # are visible in module.
                )
            )
        ),
    ),
    _declaration(
        # Pass canonical writer role explicitly so _declaration receives a reviewable
        # container and sort input in module.
        CANONICAL_WRITER_ROLE,
        {"container": "canonical-parquet-v4", "sort": "external-canonical-v1"},
        tuple(sorted((*_CANONICAL_EVENT_CONTRACT, "adapters/columnar/arrow/canonical.py"))),
    ),
    _declaration(
        # Pass replay compiler role explicitly so _declaration receives a reviewable
        # compiler and layout input in module.
        REPLAY_COMPILER_ROLE,
        {"compiler": "numpy-replay-two-pass-v3", "layout": "numpy-mmap-v1"},
        tuple(sorted((*_REPLAY_CONTRACT, "adapters/columnar/numpy/compiler.py"))),
    ),
    _declaration(
        # Pass replay writer role explicitly so _declaration receives a reviewable
        # container and layout input in module.
        REPLAY_WRITER_ROLE,
        {"container": "numpy-npy-v1", "layout": "replay-pack-v1"},
        tuple(sorted((*_REPLAY_CONTRACT, "adapters/columnar/numpy/compiler.py"))),
    ),
    _declaration(
        # Pass delivery compiler role explicitly so _declaration receives a reviewable
        # compiler and ordering input in module.
        DELIVERY_COMPILER_ROLE,
        {"compiler": "numpy-delivery-two-pass-v1", "ordering": "release-source-stable-v1"},
        tuple(
            sorted(
                (
                    # Pass delivery contract explicitly so sorted receives a reviewable py
                    # and delivery contract input in module.
                    *_DELIVERY_CONTRACT,
                    "adapters/columnar/numpy/reader.py",
                    "adapters/delivery_schedule/numpy/compiler.py",
                    "adapters/delivery_schedule/numpy/policy.py",
                )
                # Complete sorted only after its py and delivery contract inputs are visible
                # in module.
            )
        ),
    ),
    _declaration(
        DELIVERY_WRITER_ROLE,
        # Open the container and layout payload explicitly for _declaration within module.
        {"container": "numpy-npy-v1", "layout": "delivery-schedule-v1"},
        tuple(sorted((*_DELIVERY_CONTRACT, "adapters/delivery_schedule/numpy/compiler.py"))),
    ),
    _declaration(
        ML_FEATURE_BUILDER_ROLE,
        # Open the builder and reference-replay-row-features-v1 payload explicitly for
        # _declaration within module.
        {"builder": "reference-replay-row-features-v1"},
        tuple(
            sorted(
                (
                    *_ML_CONTRACT,
                    # Pass ml reader contract explicitly so sorted receives a reviewable
                    # py and ml contract input in module.
                    *_ML_READER_CONTRACT,
                    "adapters/columnar/numpy/layout.py",
                    "adapters/columnar/numpy/reader.py",
                    "adapters/ml/numpy/builders.py",
                )
                # Complete sorted only after its py and ml contract inputs are visible in
                # module.
            )
        ),
    ),
    _declaration(
        ML_UNIVERSE_BUILDER_ROLE,
        # Open the builder and reference-all-rows-universe-v1 payload explicitly for
        # _declaration within module.
        {"builder": "reference-all-rows-universe-v1"},
        tuple(sorted((*_ML_CONTRACT, *_ML_READER_CONTRACT, "adapters/ml/numpy/builders.py"))),
    ),
    _declaration(
        ML_LABEL_BUILDER_ROLE,
        # Open the builder and reference-membership-horizon-label-v1 payload explicitly
        # for _declaration within module.
        {"builder": "reference-membership-horizon-label-v1"},
        tuple(sorted((*_ML_CONTRACT, *_ML_READER_CONTRACT, "adapters/ml/numpy/builders.py"))),
    ),
    _declaration(
        ML_TRAINER_ROLE,
        # Open the arithmetic and trainer payload explicitly for _declaration within
        # module.
        {"arithmetic": "exact-rational-v1", "trainer": "ridge-linear-v1"},
        tuple(sorted((*_ML_CONTRACT, *_ML_READER_CONTRACT, "adapters/ml/numpy/pipelines.py"))),
    ),
    _declaration(
        ML_FROZEN_INFERENCE_ROLE,
        # Open the compiler and rounding payload explicitly for _declaration within
        # module.
        {"compiler": "exact-frozen-linear-v1", "rounding": "floor-v1"},
        tuple(sorted((*_ML_CONTRACT, *_ML_READER_CONTRACT, "adapters/ml/numpy/pipelines.py"))),
    ),
    _declaration(
        ML_EMBEDDED_INFERENCE_ROLE,
        # Open the compiler and bounded-temporary-mmap-exact-linear-v1 payload explicitly
        # for _declaration within module.
        {"compiler": "bounded-temporary-mmap-exact-linear-v1"},
        tuple(sorted((*_ML_CONTRACT, *_ML_READER_CONTRACT, "adapters/ml/numpy/embedded.py"))),
    ),
    _declaration(
        ML_COMPILER_ROLE,
        # Open the compiler and spill payload explicitly for _declaration within module.
        {"compiler": "numpy-point-in-time-ml-v1", "spill": "bounded-ndjson-v1"},
        tuple(
            sorted(
                (
                    *_ML_CONTRACT,
                    # Pass adapters ml numpy layout explicitly so sorted receives a
                    # reviewable py and ml contract input in module.
                    "adapters/ml/numpy/layout.py",
                    "adapters/ml/numpy/publisher.py",
                    "adapters/ml/numpy/spill.py",
                )
            )
            # Complete tuple only after its py and sorted inputs are visible in module.
        ),
    ),
    _declaration(
        ML_WRITER_ROLE,
        {"container": "numpy-npy-v1", "nullable": "packed-lsb0-v1"},
        # Register sorted and ml contract through tuple so the build tool declarations
        # table remains scannable.
        tuple(
            sorted(
                (
                    *_ML_CONTRACT,
                    "adapters/ml/numpy/layout.py",
                    # Pass adapters ml numpy publisher explicitly so sorted receives a
                    # reviewable py and ml contract input in module.
                    "adapters/ml/numpy/publisher.py",
                )
            )
        ),
    ),
    # Complete the build tool declarations group only after its semantic components are
    # visible.
)


class BuildToolBundleRegistry:
    """Pin physical tool IDs and rederive them from installed bytes on demand."""

    def __init__(
        self,
        package_root: Path | None = None,
        *,
        declarations: tuple[ReferenceBundleDeclaration, ...] = BUILD_TOOL_DECLARATIONS,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the build tool bundle registry init workflow in explicit, reviewable
        # steps.
        self._registry = ReferenceBundleRegistry(
            package_root,
            declarations=declarations,
        )

    @property
    # Define build tool bundle registry package root as one focused operation with an
    # explicit boundary.
    def package_root(self) -> Path:
        return self._registry.package_root

    @property
    def declarations(self) -> tuple[ReferenceBundleDeclaration, ...]:
        return self._registry.declarations

    # Define build tool bundle registry snapshot as one focused operation with an explicit
    # boundary.
    def snapshot(self) -> ExactCodeBundleClosure:
        return self._registry.snapshot()

    def pin(self) -> PinnedCodeBundleSet:
        # Execute the build tool bundle registry pin workflow in explicit, reviewable
        # steps.
        closure = self.snapshot()
        return PinnedCodeBundleSet(
            tuple(
                PinnedCodeBundleIdentity(
                    manifest.role,
                    # Pass manifest explicitly so PinnedCodeBundleIdentity receives a
                    # reviewable role and bundle id input in build tool bundle registry
                    # pin.
                    manifest.bundle_id,
                    partial(self._current_bundle_id, manifest.role),
                )
                for manifest in closure.manifests
            )
            # Complete PinnedCodeBundleSet only after its role and bundle id inputs are
            # visible in build tool bundle registry pin.
        )

    def _current_bundle_id(self, role: str) -> BundleId:
        return self.snapshot().manifest_for(role).bundle_id


__all__ = [
    "BUILD_TOOL_DECLARATIONS",
    # Keep the canonical projector role component named inside the all contract.
    "CANONICAL_PROJECTOR_ROLE",
    "CANONICAL_WRITER_ROLE",
    "DELIVERY_COMPILER_ROLE",
    "DELIVERY_WRITER_ROLE",
    "ML_COMPILER_ROLE",
    # Keep the ml embedded inference role component named inside the all contract.
    "ML_EMBEDDED_INFERENCE_ROLE",
    "ML_FEATURE_BUILDER_ROLE",
    "ML_FROZEN_INFERENCE_ROLE",
    "ML_LABEL_BUILDER_ROLE",
    "ML_TRAINER_ROLE",
    # Keep the ml universe builder role component named inside the all contract.
    "ML_UNIVERSE_BUILDER_ROLE",
    "ML_WRITER_ROLE",
    "REPLAY_COMPILER_ROLE",
    "REPLAY_WRITER_ROLE",
    "BuildToolBundleRegistry",
    # Complete the all group only after its semantic components are visible.
]
