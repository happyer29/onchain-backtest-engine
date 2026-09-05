"""Bounded exact embedded inference materialized before the event hot loop."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import TracebackType

# Import typing at the visible module dependency boundary.
from typing import Final, Self

import numpy as np
import numpy.typing as npt

from backtest.adapters.columnar.numpy import layout as replay_physical
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource

# Import reader at the visible module dependency boundary.
from backtest.adapters.ml.numpy.reader import (
    NumpyFeatureSetProvider,
    NumpyModelBundleReader,
    NumpyModelScheduleReader,
)

# Import toolchain at the visible module dependency boundary.
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.application.build_tool_roles import ML_EMBEDDED_INFERENCE_ROLE
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.ml_contracts import (
    EXACT_LINEAR_MODEL_KIND,
    # Include exact inference policy so the ml contracts dependency remains explicit.
    ExactInferencePolicy,
    InferenceMissingPolicy,
    InferenceMode,
    ModelCanonicality,
)

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest, ModelBundleId

_INT64_MIN: Final = -(1 << 63)
_INT64_MAX: Final = (1 << 63) - 1
_UINT64_MAX: Final = (1 << 64) - 1
# Bind npy header reserve once as an explicit module-level contract.
_NPY_HEADER_RESERVE: Final = 16 * 1024


class EmbeddedExactInferenceError(RuntimeError):
    """Embedded inference cannot preserve its exact causal/resource contract."""


class NumpyEmbeddedExactPredictionProvider:
    """Precompute a small exact-linear model to bounded temporary mmap arrays.

    All model calls happen during construction, before the engine starts its
    historical reducer. ``value_at`` is therefore only a causal mmap lookup.
    """

    def __init__(
        self,
        *,
        replay: NumpyMmapReplaySource,
        features: tuple[NumpyFeatureSetProvider, ...],
        # Keep the schedule input explicit in the init contract.
        schedule: NumpyModelScheduleReader,
        models: tuple[NumpyModelBundleReader, ...],
        policy: ExactInferencePolicy,
        temporary_parent: Path,
        maximum_temporary_bytes: int,
        # Keep the batch rows input explicit in the init contract.
        batch_rows: int = 65_536,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the numpy embedded exact prediction provider init workflow in explicit,
        # reviewable steps.
        if maximum_temporary_bytes <= 0 or batch_rows <= 0:
            raise ValueError("embedded inference quota and batch size must be positive")
        if policy.mode is not InferenceMode.EMBEDDED_BATCH:
            raise ValueError("embedded provider requires EMBEDDED_BATCH policy")
        if policy.prediction_name is None:  # pragma: no cover - policy validates this
            raise ValueError("embedded provider requires a prediction name")
        self._build_tools = build_tools or unit_ml_build_tools()
        self._build_tools.require_current(ML_EMBEDDED_INFERENCE_ROLE)
        self._prediction_name = policy.prediction_name
        self._policy_digest = policy.inference_policy_digest
        # Assemble self model bundle ids once so the numpy embedded exact prediction
        # provider init workflow shares one value.
        self._model_bundle_ids = tuple(model.model_bundle_id for model in models)
        self._root: Path | None = None
        self._values: npt.NDArray[np.generic] | None = None
        self._available: npt.NDArray[np.generic] | None = None
        self._validity: npt.NDArray[np.generic] | None = None
        # Assemble self row count once so the numpy embedded exact prediction provider
        # init workflow shares one value.
        self._row_count = replay.manifest.event_count
        validate_embedded_exact_inputs(features, schedule, models)
        required = self.required_temporary_bytes(self._row_count)
        if required > maximum_temporary_bytes:
            raise EmbeddedExactInferenceError("embedded inference exceeds hard temporary quota")
        # Invoke mkdir as a visible step within the numpy embedded exact prediction
        # provider init workflow.
        temporary_parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(temporary_parent).free < required:
            raise EmbeddedExactInferenceError("insufficient free disk for embedded inference mmap")
        root = Path(tempfile.mkdtemp(prefix="embedded-exact-", dir=temporary_parent))
        self._root = root
        # Keep expected failures inside the numpy embedded exact prediction provider init
        # error boundary.
        try:
            # Perform the protected numpy embedded exact prediction provider init
            # operation before explicit failure handling.
            self._build_tools.require_current(ML_EMBEDDED_INFERENCE_ROLE)
            self._materialize(
                replay,
                features,
                schedule,
                # Open the model bundle id and replay payload explicitly for _materialize
                # within numpy embedded exact prediction provider init.
                {model.model_bundle_id: model for model in models},
                policy,
                batch_rows,
            )
            actual = sum(path.stat().st_size for path in root.iterdir())
            # Guard this path with actual > maximum_temporary_bytes before applying
            # effects.
            if actual > maximum_temporary_bytes:
                # Handle the numpy embedded exact prediction provider init actual >
                # maximum_temporary_bytes branch as a distinct logical block.
                raise EmbeddedExactInferenceError(
                    "embedded inference mmap crossed hard temporary quota"
                )
            self._values = _open_readonly(root / "values.npy")
            self._available = _open_readonly(root / "available.npy")
            # Assemble self validity once so the numpy embedded exact prediction provider
            # init workflow shares one value.
            self._validity = _open_readonly(root / "validity.npy")
        except BaseException:
            # Translate the BaseException failure through the numpy embedded exact
            # prediction provider init boundary.
            self.close()
            raise

    @staticmethod
    def required_temporary_bytes(row_count: int) -> int:
        # Execute the numpy embedded exact prediction provider required temporary bytes
        # workflow in explicit, reviewable steps.
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
            raise ValueError("embedded inference row count must be non-negative")
        return row_count * 16 + (row_count + 7) // 8 + 3 * _NPY_HEADER_RESERVE

    @property
    def prediction_name(self) -> str:
        # Return the completed numpy embedded exact prediction provider prediction name
        # result without a hidden fallback.
        return self._prediction_name

    @property
    def inference_policy_digest(self) -> ContentDigest:
        return self._policy_digest

    @property
    # Define numpy embedded exact prediction provider model bundle ids as one focused
    # operation with an explicit boundary.
    def model_bundle_ids(self) -> tuple[ModelBundleId, ...]:
        return self._model_bundle_ids

    def value_at(
        self,
        name: str,
        # Keep the entity id input explicit in the value at contract.
        entity_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the numpy embedded exact prediction provider value at workflow in
        # explicit, reviewable steps.
        if name != self._prediction_name:
            return None
        self._validate_row(entity_id)
        if boundary_ordinal < 0:
            raise ValueError("decision boundary must be non-negative")
        # Assemble available once so the numpy embedded exact prediction provider value at
        # workflow shares one value.
        available = self._require_array(self._available)
        if boundary_ordinal < int(available[entity_id]):
            return None
        validity = self._require_array(self._validity)
        if not _bitmap_valid(validity, entity_id):
            # Return explicit absence from the numpy embedded exact prediction provider
            # value at path.
            return None
        return int(self._require_array(self._values)[entity_id])

    def available_boundary_for_row(self, replay_row_id: int) -> int:
        # Execute the numpy embedded exact prediction provider available boundary for row
        # workflow in explicit, reviewable steps.
        self._validate_row(replay_row_id)
        return int(self._require_array(self._available)[replay_row_id])

    def close(self) -> None:
        # Execute the numpy embedded exact prediction provider close workflow in explicit,
        # reviewable steps.
        for name in ("_values", "_available", "_validity"):
            # Process ('_values', '_available', '_validity') inside the bounded numpy
            # embedded exact prediction provider close loop.
            array = getattr(self, name, None)
            if array is not None:
                # Handle the numpy embedded exact prediction provider close array is not
                # None branch as a distinct logical block.
                mmap = getattr(array, "_mmap", None)
                if mmap is not None:
                    mmap.close()
                setattr(self, name, None)
        root = self._root
        # Assemble self root once so the numpy embedded exact prediction provider close
        # workflow shares one value.
        self._root = None
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def __enter__(self) -> Self:
        return self

    # Define numpy embedded exact prediction provider exit as one focused operation with
    # an explicit boundary.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        # Close the exit signature after its explicit inputs.
    ) -> None:
        self.close()

    def _materialize(
        self,
        replay: NumpyMmapReplaySource,
        # Keep the features input explicit in the materialize contract.
        features: tuple[NumpyFeatureSetProvider, ...],
        schedule: NumpyModelScheduleReader,
        models: dict[ModelBundleId, NumpyModelBundleReader],
        policy: ExactInferencePolicy,
        batch_rows: int,
        # Close the materialize signature after its explicit inputs.
    ) -> None:
        # Execute the numpy embedded exact prediction provider materialize workflow in
        # explicit, reviewable steps.
        root = self._root
        if root is None:  # pragma: no cover - constructor establishes it
            raise AssertionError("embedded inference has no temporary root")
        values = np.lib.format.open_memmap(
            root / "values.npy", mode="w+", dtype=np.dtype("<i8"), shape=(self._row_count,)
        )
        available = np.lib.format.open_memmap(
            # Keep the dtype and np dtype step visible while building available.
            root / "available.npy",
            mode="w+",
            dtype=np.dtype("<u8"),
            shape=(self._row_count,),
        )
        # Assemble validity once so the numpy embedded exact prediction provider
        # materialize workflow shares one value.
        validity = np.lib.format.open_memmap(
            root / "validity.npy",
            mode="w+",
            # Keep the dtype and np dtype step visible while building validity.
            dtype=np.dtype("|u1"),
            shape=((self._row_count + 7) // 8,),
        )
        validity[:] = 0
        effective = replay.arrays()[replay_physical.ENVELOPE_BOUNDARY_ORDINAL]
        # Keep expected failures inside the numpy embedded exact prediction provider
        # materialize error boundary.
        try:
            # Perform the protected numpy embedded exact prediction provider materialize
            # operation before explicit failure handling.
            for start in range(0, self._row_count, batch_rows):
                # Process range(0, self._row_count, batch_rows) inside the bounded numpy
                # embedded exact prediction provider materialize loop.
                stop = min(self._row_count, start + batch_rows)
                for row_id in range(start, stop):
                    # Process range(start, stop) inside the bounded numpy embedded exact
                    # prediction provider materialize loop.
                    boundary = int(effective[row_id])
                    model = models[schedule.model_for(boundary)]
                    feature_available = max(
                        feature.available_boundary_for_row(row_id) for feature in features
                    )
                    # Assemble inference start once so the numpy embedded exact prediction
                    # provider materialize workflow shares one value.
                    inference_start = max(
                        feature_available,
                        model.model_available_boundary,
                        *model.fitted_component_available_boundaries,
                    )
                    # Assemble inference completion once so the numpy embedded exact
                    # prediction provider materialize workflow shares one value.
                    inference_completion = inference_start + policy.inference_delay_boundaries
                    if inference_completion > _UINT64_MAX:
                        # Handle the numpy embedded exact prediction provider materialize
                        # inference_completion > _UINT64_MAX branch as a distinct logical
                        # block.
                        raise EmbeddedExactInferenceError(
                            "embedded inference availability exceeds uint64"
                        )
                    materialized: list[int] = []
                    missing = False
                    # Traverse features explicitly so each numpy embedded exact prediction
                    # provider materialize iteration remains traceable.
                    for feature in features:
                        # Process features inside the bounded numpy embedded exact
                        # prediction provider materialize loop.
                        for code in range(len(feature.feature_specs)):
                            # Process range(len(feature.feature_specs)) inside the bounded
                            # numpy embedded exact prediction provider materialize loop.
                            value = feature.materialized_value_for_offline_pipeline(code, row_id)
                            if value is None:
                                missing = True
                            else:
                                materialized.append(value)
                    # Guard this path with missing before applying effects.
                    if missing:
                        # Handle the numpy embedded exact prediction provider materialize
                        # missing branch as a distinct logical block.
                        if policy.missing_policy is InferenceMissingPolicy.REJECT:
                            # Handle the numpy embedded exact prediction provider
                            # materialize missing policy, reject and policy condition as a
                            # distinct block.
                            raise EmbeddedExactInferenceError(
                                "embedded inference encountered a missing feature"
                            )
                        values[row_id] = 0
                    else:
                        # Handle the numpy embedded exact prediction provider materialize
                        # complement of missing explicitly.
                        prediction = model.predict_exact(tuple(materialized))
                        if not _INT64_MIN <= prediction <= _INT64_MAX:
                            # Handle the numpy embedded exact prediction provider
                            # materialize int64 min, prediction and int64 max condition as
                            # a distinct block.
                            raise EmbeddedExactInferenceError(
                                "embedded prediction exceeds checked int64 output"
                            )
                        values[row_id] = prediction
                        validity[row_id // 8] |= np.uint8(1 << (row_id % 8))
                    # Assemble available[row id] once so the numpy embedded exact
                    # prediction provider materialize workflow shares one value.
                    available[row_id] = inference_completion
            values.flush()
            available.flush()
            validity.flush()
        finally:
            # Handle the cleanup path after the protected numpy embedded exact prediction
            # provider materialize operation.
            _close_memmap(values)
            _close_memmap(available)
            _close_memmap(validity)

    def _validate_row(self, replay_row_id: int) -> None:
        # Execute the numpy embedded exact prediction provider validate row workflow in
        # explicit, reviewable steps.
        if isinstance(replay_row_id, bool) or not isinstance(replay_row_id, int):
            raise TypeError("replay row ID must be an integer")
        if not 0 <= replay_row_id < self._row_count:
            raise ValueError("replay row ID is out of bounds")

    @staticmethod
    # Define numpy embedded exact prediction provider require array as one focused
    # operation with an explicit boundary.
    def _require_array(
        value: npt.NDArray[np.generic] | None,
    ) -> npt.NDArray[np.generic]:
        # Execute the numpy embedded exact prediction provider require array workflow in
        # explicit, reviewable steps.
        if value is None:
            raise EmbeddedExactInferenceError("embedded prediction provider is closed")
        return value


def _feature_schema(features: tuple[NumpyFeatureSetProvider, ...]) -> ContentDigest:
    # Execute the feature schema workflow in explicit, reviewable steps.
    return domain_digest(
        "backtest.model-feature-schema.v1",
        [
            {
                "feature_set_id": feature.feature_set_id.hex,
                # Keep feature spec ids named so the v1 and feature set id payload passed
                # to domain_digest remains self-describing within feature schema.
                "feature_spec_ids": [item.feature_spec_id.hex for item in feature.feature_specs],
            }
            for feature in features
        ],
    )


# Define validate embedded exact inputs as one focused operation with an explicit
# boundary.
def validate_embedded_exact_inputs(
    features: tuple[NumpyFeatureSetProvider, ...],
    schedule: NumpyModelScheduleReader,
    models: tuple[NumpyModelBundleReader, ...],
) -> None:
    """Validate exact model/runtime/dtype/schema inputs without running inference."""

    if not features or not models:
        raise EmbeddedExactInferenceError("embedded inference requires features and models")
    model_ids = tuple(model.model_bundle_id for model in models)
    if model_ids != tuple(sorted(set(model_ids), key=lambda item: item.hex)):
        raise EmbeddedExactInferenceError("embedded model inputs must be sorted and unique")
    # Guard this path with model_ids != schedule.model_bundle_ids before applying effects.
    if model_ids != schedule.model_bundle_ids:
        # Handle the validate embedded exact inputs model_ids != schedule.model_bundle_ids
        # branch as a distinct logical block.
        raise EmbeddedExactInferenceError(
            "embedded model inputs differ from the exact ModelSchedule"
        )
    if schedule.canonicality is not ModelCanonicality.CANONICAL_EXACT:
        raise EmbeddedExactInferenceError("embedded inference refuses tolerance schedule")
    # Assemble feature schema once so the validate embedded exact inputs workflow shares
    # one value.
    feature_schema = _feature_schema(features)
    feature_count = sum(len(feature.feature_specs) for feature in features)
    for model in models:
        # Process models inside the bounded validate embedded exact inputs loop.
        if (
            model.canonicality is not ModelCanonicality.CANONICAL_EXACT
            or model.framework != EXACT_LINEAR_MODEL_KIND
            or model.feature_schema_digest != feature_schema
            or model.weights.size != feature_count
            # Evaluate the complete validate embedded exact inputs canonicality, canonical
            # exact and framework condition before guarded effects.
        ):
            # Handle the validate embedded exact inputs canonicality, canonical exact and
            # framework condition as a distinct block.
            raise EmbeddedExactInferenceError(
                "embedded exact-linear model/runtime/schema contract is unsupported"
            )


def _open_readonly(path: Path) -> npt.NDArray[np.generic]:
    # Execute the open readonly workflow in explicit, reviewable steps.
    try:
        value = np.load(path, mmap_mode="r", allow_pickle=False, max_header_size=16 * 1024)
    except (OSError, ValueError) as error:  # pragma: no cover - writer-owned path
        raise EmbeddedExactInferenceError("embedded inference mmap cannot be reopened") from error
    if not isinstance(value, np.memmap) or value.flags.writeable:
        raise EmbeddedExactInferenceError("embedded inference mmap is not read-only")
    return value


def _close_memmap(value: npt.NDArray[np.generic]) -> None:
    # Execute the close memmap workflow in explicit, reviewable steps.
    mmap = getattr(value, "_mmap", None)
    if mmap is not None:
        mmap.close()


def _bitmap_valid(bitmap: npt.NDArray[np.generic], index: int) -> bool:
    return bool(int(bitmap[index // 8]) & (1 << (index % 8)))


# Bind all once as an explicit module-level contract.
__all__ = [
    "EmbeddedExactInferenceError",
    "NumpyEmbeddedExactPredictionProvider",
    "validate_embedded_exact_inputs",
]
