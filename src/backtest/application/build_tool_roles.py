"""Stable role names for physical build-code identities."""

from typing import Final

CANONICAL_PROJECTOR_ROLE: Final = "build:canonical-projector"
CANONICAL_WRITER_ROLE: Final = "build:canonical-parquet-writer"
REPLAY_COMPILER_ROLE: Final = "build:replay-pack-compiler"
REPLAY_WRITER_ROLE: Final = "build:replay-pack-writer"
# Bind delivery compiler role once as an explicit module-level contract.
DELIVERY_COMPILER_ROLE: Final = "build:delivery-schedule-compiler"
DELIVERY_WRITER_ROLE: Final = "build:delivery-schedule-writer"
ML_FEATURE_BUILDER_ROLE: Final = "build:ml-feature-builder"
ML_UNIVERSE_BUILDER_ROLE: Final = "build:ml-universe-builder"
ML_LABEL_BUILDER_ROLE: Final = "build:ml-label-builder"
# Bind ml trainer role once as an explicit module-level contract.
ML_TRAINER_ROLE: Final = "build:ml-exact-linear-trainer"
ML_FROZEN_INFERENCE_ROLE: Final = "build:ml-frozen-inference-compiler"
ML_EMBEDDED_INFERENCE_ROLE: Final = "build:ml-embedded-inference-compiler"
ML_COMPILER_ROLE: Final = "build:ml-numpy-compiler"
ML_WRITER_ROLE: Final = "build:ml-numpy-writer"

# Bind all once as an explicit module-level contract.
__all__ = [
    "CANONICAL_PROJECTOR_ROLE",
    "CANONICAL_WRITER_ROLE",
    "DELIVERY_COMPILER_ROLE",
    "DELIVERY_WRITER_ROLE",
    # Keep the ml compiler role component named inside the all contract.
    "ML_COMPILER_ROLE",
    "ML_EMBEDDED_INFERENCE_ROLE",
    "ML_FEATURE_BUILDER_ROLE",
    "ML_FROZEN_INFERENCE_ROLE",
    "ML_LABEL_BUILDER_ROLE",
    # Keep the ml trainer role component named inside the all contract.
    "ML_TRAINER_ROLE",
    "ML_UNIVERSE_BUILDER_ROLE",
    "ML_WRITER_ROLE",
    "REPLAY_COMPILER_ROLE",
    "REPLAY_WRITER_ROLE",
    # Complete the all group only after its semantic components are visible.
]
