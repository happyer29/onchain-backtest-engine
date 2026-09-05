"""Isolated unit defaults for NumPy ML tool roles.

Production composition always replaces these fixed IDs with source-bound pins
from :mod:`backtest.bootstrap.build_tools`.
"""

from __future__ import annotations

from typing import Final

from backtest.adapters.columnar.numpy.compiler import unit_replay_build_tools
from backtest.application.build_tool_roles import (
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
)
from backtest.application.code_bundles import (
    PinnedCodeBundleIdentity,
    # Include pinned code bundle set so the code bundles dependency remains explicit.
    PinnedCodeBundleSet,
)
from backtest.application.ml_contracts import EXACT_LINEAR_MODEL_KIND
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import BundleId

# Bind numpy ml compiler version once as an explicit module-level contract.
NUMPY_ML_COMPILER_VERSION: Final = "numpy-point-in-time-ml-v1"
UNIT_ML_COMPILER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.numpy-ml-compiler-bundle.v1",
        {
            # Keep compiler version named so the v1 and compiler version payload passed to
            # domain_digest remains self-describing within module.
            "compiler_version": NUMPY_ML_COMPILER_VERSION,
            "external_sort": "canonical-ndjson-bounded-v1",
            "feature_alignment": "dense-replay-row-id-v1",
            "prediction_mode": "frozen-v1",
        },
        # Complete domain_digest only after its v1 and compiler version inputs are visible in
        # module.
    ).hex
)
UNIT_ML_WRITER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.numpy-ml-writer-bundle.v1",
        # Open the v1 and container payload explicitly for domain_digest within module.
        {
            "container": "numpy-npy-v1",
            "nullable": "packed-lsb0-one-is-valid-v1",
            "order": "C",
            "pickle": False,
            # Close the v1 and container payload only after all module fields are present.
        },
    ).hex
)
UNIT_FEATURE_BUILDER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and
        # features input in module.
        "backtest.reference-feature-builder-bundle.v1",
        {
            "features": [
                "event_boundary_ordinal",
                "event_index",
                # Pass event kind code explicitly so domain_digest receives a reviewable
                # v1 and features input in module.
                "event_kind_code",
                "event_slot",
                "source_boundary_ordinal",
                "transaction_index",
            ],
            # Keep implementation named so the v1 and features payload passed to
            # domain_digest remains self-describing within module.
            "implementation": "numpy-mmap-stream-v1",
        },
    ).hex
)
UNIT_UNIVERSE_BUILDER_BUNDLE_ID: Final = BundleId(
    # Keep the v1 domain_digest step visible while building unit universe builder bundle
    # id.
    domain_digest(
        "backtest.reference-universe-builder-bundle.v1",
        {"implementation": "all-replay-rows-at-feature-availability-v1"},
    ).hex
)
# Bind unit label builder bundle id once as an explicit module-level contract.
UNIT_LABEL_BUILDER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.reference-label-builder-bundle.v1",
        {"implementation": "membership-horizon-length-v1"},
    ).hex
    # Complete BundleId only after its v1 and implementation inputs are visible in module.
)
UNIT_EXACT_TRAINER_BUNDLE_ID: Final = BundleId(
    domain_digest(
        "backtest.exact-integer-linear-trainer-bundle.v1",
        {
            # Keep fit named so the v1 and fit payload passed to domain_digest remains
            # self-describing within module.
            "fit": "ridge-normal-equations-rational-gaussian-elimination-v1",
            "intercept": True,
            "missing_feature_policy": "reject-v1",
            "null_label_policy": "drop-v1",
            "prediction_rounding": "floor-toward-negative-infinity-v1",
            # Close the v1 and fit payload only after all module fields are present.
        },
    ).hex
)
UNIT_FROZEN_INFERENCE_BUNDLE_ID: Final = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and
        # arithmetic input in module.
        "backtest.exact-frozen-linear-inference-bundle.v1",
        {
            "arithmetic": "signed-integer-numerator-v1",
            "model": EXACT_LINEAR_MODEL_KIND,
            "rounding": "floor-toward-negative-infinity-v1",
            # Close the v1 and arithmetic payload only after all module fields are present.
        },
    ).hex
)
UNIT_EMBEDDED_INFERENCE_BUNDLE_ID: Final = BundleId(
    domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v1 and
        # materialization input in module.
        "backtest.exact-embedded-linear-inference-bundle.v1",
        {"materialization": "bounded-temporary-mmap-v1"},
    ).hex
)


def unit_ml_build_tools() -> PinnedCodeBundleSet:
    # Execute the unit ml build tools workflow in explicit, reviewable steps.
    identities = [*unit_replay_build_tools().identities]
    for role, bundle_id in (
        (ML_COMPILER_ROLE, UNIT_ML_COMPILER_BUNDLE_ID),
        (ML_EMBEDDED_INFERENCE_ROLE, UNIT_EMBEDDED_INFERENCE_BUNDLE_ID),
        (ML_FEATURE_BUILDER_ROLE, UNIT_FEATURE_BUILDER_BUNDLE_ID),
        # Traverse ml compiler role, unit ml compiler bundle id and ml embedded inference
        # role explicitly so each unit ml build tools iteration remains traceable.
        (ML_FROZEN_INFERENCE_ROLE, UNIT_FROZEN_INFERENCE_BUNDLE_ID),
        (ML_LABEL_BUILDER_ROLE, UNIT_LABEL_BUILDER_BUNDLE_ID),
        (ML_TRAINER_ROLE, UNIT_EXACT_TRAINER_BUNDLE_ID),
        (ML_UNIVERSE_BUILDER_ROLE, UNIT_UNIVERSE_BUILDER_BUNDLE_ID),
        (ML_WRITER_ROLE, UNIT_ML_WRITER_BUNDLE_ID),
        # Traverse ml compiler role, unit ml compiler bundle id and ml embedded inference role
        # explicitly so each unit ml build tools iteration remains traceable.
    ):
        identities.append(PinnedCodeBundleIdentity.for_unit_tests(role, bundle_id))
    return PinnedCodeBundleSet(tuple(sorted(identities, key=lambda item: item.role)))


__all__ = [
    "NUMPY_ML_COMPILER_VERSION",
    # Keep the unit embedded inference bundle id component named inside the all contract.
    "UNIT_EMBEDDED_INFERENCE_BUNDLE_ID",
    "UNIT_EXACT_TRAINER_BUNDLE_ID",
    "UNIT_FEATURE_BUILDER_BUNDLE_ID",
    "UNIT_FROZEN_INFERENCE_BUNDLE_ID",
    "UNIT_LABEL_BUILDER_BUNDLE_ID",
    # Keep the unit ml compiler bundle id component named inside the all contract.
    "UNIT_ML_COMPILER_BUNDLE_ID",
    "UNIT_ML_WRITER_BUNDLE_ID",
    "UNIT_UNIVERSE_BUILDER_BUNDLE_ID",
    "unit_ml_build_tools",
]
