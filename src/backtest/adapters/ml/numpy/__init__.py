"""NumPy mmap point-in-time overlay implementation.

The training-only LabelSet reader is deliberately available only from the
``training`` submodule and is not re-exported through this engine-facing API.
"""

from backtest.adapters.ml.numpy.builders import (
    REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID,
    REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST,
    REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID,
    REFERENCE_FEATURE_BUILDER_BUNDLE_ID,
    # Include reference feature names so the builders dependency remains explicit.
    REFERENCE_FEATURE_NAMES,
    REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID,
    REFERENCE_HORIZON_LABEL_CONFIG_DIGEST,
    REFERENCE_HORIZON_LABEL_SPEC_ID,
    LocalReferenceMlRowBuilders,
    # Include reference ml builder error so the builders dependency remains explicit.
    ReferenceMlBuilderError,
)
from backtest.adapters.ml.numpy.embedded import (
    EmbeddedExactInferenceError,
    NumpyEmbeddedExactPredictionProvider,
    # Close the embedded import after its required symbols are visible.
)
from backtest.adapters.ml.numpy.layout import COMPILER_VERSION as NUMPY_ML_COMPILER_VERSION
from backtest.adapters.ml.numpy.overlays import (
    CausalOverlayResolutionError,
    LocalNumpyCausalOverlayFactory,
    # Close the overlays import after its required symbols are visible.
)
from backtest.adapters.ml.numpy.pipelines import (
    EXACT_FROZEN_INFERENCE_BUNDLE_ID,
    EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID,
    EXACT_LINEAR_FRAMEWORK,
    # Include exact ml pipeline error so the pipelines dependency remains explicit.
    ExactMlPipelineError,
    LocalExactFrozenPredictionBuilder,
    LocalExactIntegerLinearTrainer,
)
from backtest.adapters.ml.numpy.publisher import (
    # Include local numpy ml artifact publisher so the publisher dependency remains
    # explicit.
    LocalNumpyMlArtifactPublisher,
    NumpyMlArtifactCompileError,
)
from backtest.adapters.ml.numpy.reader import (
    NumpyFeatureSetProvider,
    # Include numpy ml artifact format error so the reader dependency remains explicit.
    NumpyMlArtifactFormatError,
    NumpyModelBundleReader,
    NumpyModelScheduleReader,
    NumpyPredictionSetProvider,
    NumpyUniverseReader,
    # Close the reader import after its required symbols are visible.
)

__all__ = [
    "EXACT_FROZEN_INFERENCE_BUNDLE_ID",
    "EXACT_INTEGER_LINEAR_TRAINER_BUNDLE_ID",
    "EXACT_LINEAR_FRAMEWORK",
    # Keep the numpy ml compiler version component named inside the all contract.
    "NUMPY_ML_COMPILER_VERSION",
    "REFERENCE_ALL_ROWS_UNIVERSE_BUNDLE_ID",
    "REFERENCE_ALL_ROWS_UNIVERSE_CONFIG_DIGEST",
    "REFERENCE_ALL_ROWS_UNIVERSE_SPEC_ID",
    "REFERENCE_FEATURE_BUILDER_BUNDLE_ID",
    # Keep the reference feature names component named inside the all contract.
    "REFERENCE_FEATURE_NAMES",
    "REFERENCE_HORIZON_LABEL_BUILDER_BUNDLE_ID",
    "REFERENCE_HORIZON_LABEL_CONFIG_DIGEST",
    "REFERENCE_HORIZON_LABEL_SPEC_ID",
    "CausalOverlayResolutionError",
    # Keep the embedded exact inference error component named inside the all contract.
    "EmbeddedExactInferenceError",
    "ExactMlPipelineError",
    "LocalExactFrozenPredictionBuilder",
    "LocalExactIntegerLinearTrainer",
    "LocalNumpyCausalOverlayFactory",
    # Keep the local numpy ml artifact publisher component named inside the all contract.
    "LocalNumpyMlArtifactPublisher",
    "LocalReferenceMlRowBuilders",
    "NumpyEmbeddedExactPredictionProvider",
    "NumpyFeatureSetProvider",
    "NumpyMlArtifactCompileError",
    # Keep the numpy ml artifact format error component named inside the all contract.
    "NumpyMlArtifactFormatError",
    "NumpyModelBundleReader",
    "NumpyModelScheduleReader",
    "NumpyPredictionSetProvider",
    "NumpyUniverseReader",
    # Keep the reference ml builder error component named inside the all contract.
    "ReferenceMlBuilderError",
]
